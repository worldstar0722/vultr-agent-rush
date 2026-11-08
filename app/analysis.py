"""AI analysis runs: the one place that may call the model.

A run is an explicit user action (Run analysis / Regenerate); loading a page never starts one.
Each run records the real operations it performed, with real timestamps:

    load_evidence -> compute_checks -> call_model -> validate_evidence -> prepare_draft -> await_human

Safety properties (all covered by tests):
* cached: the same evidence + model + prompt returns the stored run without a provider call;
* one analysis at a time per case (a second click gets 409, never a second paid call);
* the lifetime attempt budget and the per-client hourly limit are checked before any network traffic (429);
* fail closed: a live reply that is malformed, off-schema, cites unknown records, states a number
  or time that conflicts with the rule engine, or promises an outcome is REJECTED. A clearly
  labelled rules-only draft is stored instead; it is never presented as AI output;
* what is stored about the provider is the redacted public message only, never provider output.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app import guardrails
from app.budget import Budget, RateLimited
from app.db import connect, j, row_dict
from app.drafting import build_template_draft
from app.engine import analyze
from app.errors import DeskError
from app.llm import PROMPT_VERSION, LLMError
from app.schema import AIAnalysis, schema_problems

if TYPE_CHECKING:
    from app.service import Desk

log = logging.getLogger("gradecase.analysis")

LIFETIME_MSG = (
    "The lifetime AI budget for this deployment is used up. The rules-only draft is still "
    "available; live AI stays off until an operator re-authorises spending."
)
USABLE = ("accepted", "mock")  # outcomes whose draft may be treated as the AI's reply
RUN_JSON = ("validation", "ai_output", "stages")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Stages:
    """Collects the operations a run really performed."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def begin(self, key: str, label: str) -> dict[str, Any]:
        st = {
            "key": key,
            "label": label,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "duration_ms": None,
            "detail": "",
            "_t": time.monotonic(),
        }
        self.items.append(st)
        return st

    def end(self, st: dict[str, Any], status: str, detail: str = "") -> None:
        st["duration_ms"] = int((time.monotonic() - st.pop("_t")) * 1000)
        st.update(status=status, finished_at=_now(), detail=detail)

    def skip(self, key: str, label: str, detail: str) -> None:
        now = _now()
        self.items.append(
            {
                "key": key,
                "label": label,
                "status": "skipped",
                "started_at": now,
                "finished_at": now,
                "duration_ms": 0,
                "detail": detail,
            }
        )

    def dump(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in self.items]


def build_bundle(
    case: dict[str, Any], ev: list[dict[str, Any]], a: dict[str, Any]
) -> dict[str, Any]:
    return {
        "case": {
            k: case[k]
            for k in ("id", "course", "assignment", "assignment_name", "issue", "student_id")
        },
        "analysis": a,
        "student_claims": [
            {"ref_id": e["ref_id"], "text": e["source_text"]}
            for e in ev
            if e["source_type"] == "message" and e["payload"]["direction"] == "inbound"
        ],
        "evidence": [
            {
                "ref_id": e["ref_id"],
                "type": e["source_type"],
                "ts": e["ts"],
                "summary": e["summary"],
                "source_text": e["source_text"],
            }
            for e in ev
        ],
        "computed": {
            **{
                k: a[k]
                for k in (
                    "deadline",
                    "attempts",
                    "score_state",
                    "policy",
                    "submission_state",
                    "blockers",
                    "gates",
                    "professor_approved",
                    "reconciliation",
                )
            },
            "approval_ids": a["approval_ids"],
        },
    }


class Analyzer:
    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self.s = desk.settings
        self.llm = desk.llm
        self.budget = Budget(desk.settings)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ identity of an analysis
    def fingerprint(self, ev: list[dict[str, Any]]) -> str:
        """Same records + same model + same prompt => same fingerprint => cached result valid."""
        rows = sorted(
            (
                e["ref_id"],
                e["source_type"],
                e["ts"],
                e["source_text"],
                json.dumps(e["payload"], sort_keys=True, default=str),
            )
            for e in ev
        )
        mode = "mock" if self.llm.mock else f"live:{self.s.model}"
        blob = json.dumps([rows, PROMPT_VERSION, mode], ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def _lock(self, case_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(case_id, threading.Lock())

    # ------------------------------------------------------------------------- main entry
    def run(
        self, case_id: str, client: str, force: bool = False, rules_only: bool = False
    ) -> dict[str, Any]:
        lock = self._lock(case_id)
        if not lock.acquire(blocking=False):
            raise DeskError(
                409, "An analysis for this case is already running.", "analysis_in_progress"
            )
        try:
            return self._run(case_id, client, force, rules_only)
        finally:
            lock.release()

    def _run(self, case_id: str, client: str, force: bool, rules_only: bool) -> dict[str, Any]:
        stages = Stages()
        t_run = time.monotonic()
        with connect(self.s.db_path) as conn:
            case = self.desk._case(conn, case_id)
            if case["merged_into"]:
                raise DeskError(409, f"Merged into {case['merged_into']}", "merged")
            if case["status"] == "Closed":
                raise DeskError(409, "This case is closed.", "closed")
            st = stages.begin("load_evidence", "Load evidence")
            ev = self.desk._evidence(conn, case_id)
            ev.sort(key=lambda e: (e["ts"], e["ref_id"]))
            fp = self.fingerprint(ev)
            stages.end(st, "done", f"{len(ev)} records loaded")

            if not force and not rules_only:
                cached = self._cached(conn, case_id, fp)
                if cached:
                    return {
                        "mode": cached["mode"],
                        "status": "cached",
                        "cached": True,
                        "run_id": cached["id"],
                        "error_kind": "",
                        "message": "Valid analysis reused: "
                        "the evidence has not changed since it ran. No model was called.",
                    }

            st = stages.begin("compute_checks", "Compute checks (rules, no AI)")
            a = analyze(ev)
            stages.end(
                st,
                "done",
                f"{len(a['warnings'])} warnings, {len(a['blockers'])} blockers, "
                f"{len(a['gates'])} professor gates",
            )
            bundle = build_bundle(case, ev, a)

            live = not self.llm.mock and not rules_only
            if live:
                if self.s.ai_mode != "configured":
                    return self._record_failure(
                        conn,
                        case_id,
                        fp,
                        stages,
                        bundle,
                        a,
                        client,
                        LLMError("not_configured"),
                        t_run,
                    )
                self.budget.check_client(client)
                if self.budget.usage()["exhausted"]:
                    raise RateLimited(
                        "ai_budget_exhausted",
                        LIFETIME_MSG,
                        None,
                    )
                self.budget.note_client_run(client)
            mode = (
                "live" if live else ("mock" if self.llm.mock and not rules_only else "rules-only")
            )
            # A crashed process can leave a 'running' row behind; no live run holds the case lock.
            conn.execute(
                "UPDATE analysis_runs SET outcome='error', error_kind='abandoned', finished_at=?,"
                " error_message='The run did not finish (server restarted).' "
                "WHERE case_id=? AND outcome='running'",
                (_now(), case_id),
            )
            run_id = self._start_run(conn, case_id, fp, mode, client)
            # Commit now: the run is visible to other requests, and this connection must not hold a
            # write lock while the budget gate writes from its own connection during the call.
            conn.commit()

            result = None
            err: LLMError | None = None
            if rules_only:
                stages.skip(
                    "call_model", "Call model", "Rules-only draft requested: no model was called"
                )
            elif not live:
                st = stages.begin("call_model", "Call model")
                result = self.llm.analyze(bundle)
                stages.end(
                    st,
                    "skipped",
                    "Mock mode: a deterministic template ran locally; no model was called",
                )
            else:
                st = stages.begin("call_model", "Call model")
                try:
                    result = self.llm.analyze(
                        bundle, self.budget.gate(case_id, self.llm.provider, self.s.model)
                    )
                    stages.end(
                        st,
                        "done",
                        f"{result.provider} / {result.model}: {result.latency_ms} ms, "
                        f"{result.attempts} attempt(s)",
                    )
                except LLMError as exc:
                    err = exc
                    stages.end(st, "failed", exc.public_message)
                except Exception as exc:  # a bug must not leak details or break the page
                    log.error("unexpected failure during model call: %s", type(exc).__name__)
                    err = LLMError("provider_error")
                    stages.end(st, "failed", "Unexpected error during the model call.")
            if err is not None and err.kind == "budget" and err.attempts == 0:
                conn.execute("DELETE FROM analysis_runs WHERE id=?", (run_id,))
                conn.commit()
                raise RateLimited(
                    "ai_budget_exhausted",
                    LIFETIME_MSG,
                    None,
                )

            # ---- validate (schema, then evidence guardrails). Anything wrong => reject.
            st = stages.begin("validate_evidence", "Validate against the records")
            validation: dict[str, Any] = {"schema_ok": None, "passed": None, "flags": []}
            usable = False
            cleaned: dict[str, Any] | None = None
            raw_dump: dict[str, Any] = {}
            if result is not None:
                try:
                    parsed = AIAnalysis.model_validate(result.data)
                    raw_dump = parsed.model_dump()
                    validation["schema_ok"] = True
                    cleaned = guardrails.validate_draft(raw_dump, a)
                    blocking = guardrails.blocking_flags(cleaned["flags"])
                    validation.update(passed=not blocking, flags=cleaned["flags"])
                    usable = not blocking
                    stages.end(
                        st,
                        "done" if usable else "failed",
                        "All claims cite real records and match the computed values"
                        if usable
                        else f"Rejected: {len(blocking)} problem(s), e.g. {blocking[0]['message']}",
                    )
                except ValidationError as exc:
                    validation.update(
                        schema_ok=False,
                        passed=False,
                        flags=[{"kind": "schema", "message": schema_problems(exc)}],
                    )
                    stages.end(
                        st, "failed", "Rejected: the reply did not match the required structure"
                    )
                    err = LLMError("schema_invalid", detail=schema_problems(exc))
            else:
                stages.end(st, "skipped", "No model reply to validate")

            # ---- prepare the draft that a human will review
            st = stages.begin("prepare_draft", "Prepare draft")
            if usable and cleaned is not None:
                outcome = "mock" if not live else "accepted"
                source, ai_status, draft = (
                    ("mock" if not live else "llm"),
                    ("mock" if not live else "ok"),
                    cleaned,
                )
                note = f"Draft prepared from the {'mock template' if not live else 'validated model reply'}"
            else:
                fallback = guardrails.validate_draft(build_template_draft(bundle), a)
                draft, source = fallback, "rules-only"
                ai_status = "rules-only" if rules_only else "unavailable"
                outcome = (
                    "rules-only" if rules_only else ("rejected" if result is not None else "error")
                )
                note = (
                    "Rules-only draft prepared (requested)"
                    if rules_only
                    else "Rules-only draft prepared because the AI reply was not usable; "
                    "it is a deterministic template, not AI output"
                )
            draft_id = self._insert_draft(conn, case_id, run_id, draft, ai_status, source)
            self._insert_recommendation(
                conn, case_id, draft, a, "ai" if outcome in USABLE and live else "rules"
            )
            stages.end(st, "done", note)
            stages.items.append(
                {
                    "key": "await_human",
                    "label": "Await human decision",
                    "status": "pending",
                    "started_at": _now(),
                    "finished_at": None,
                    "duration_ms": None,
                    "detail": "A TA or professor must review and decide",
                }
            )

            usage = result.usage if result else {}
            self._finish_run(
                conn,
                run_id,
                outcome=outcome,
                result=result,
                err=err,
                validation=validation,
                ai_output={"raw": raw_dump, "cleaned": _cleaned_view(cleaned) if cleaned else None},
                stages=stages,
                total_ms=int((time.monotonic() - t_run) * 1000),
                usage=usage,
            )
            msg = ""
            status = {"accepted": "succeeded", "mock": "mock", "rules-only": "rules_only"}.get(
                outcome, outcome
            )
            if outcome == "rejected":
                msg = "The model replied, but its answer failed validation against the records and was rejected."
            elif outcome == "error" and err is not None:
                msg = err.public_message
            return {
                "mode": mode,
                "status": status,
                "cached": False,
                "run_id": run_id,
                "error_kind": err.kind if err else "",
                "message": msg,
                "draft_id": draft_id,
            }

    # --------------------------------------------------------------------- failure w/o a call
    def _record_failure(
        self,
        conn: Any,
        case_id: str,
        fp: str,
        stages: Stages,
        bundle: dict[str, Any],
        a: dict[str, Any],
        client: str,
        err: LLMError,
        t_run: float,
    ) -> dict[str, Any]:
        run_id = self._start_run(conn, case_id, fp, "live", client)
        stages.skip("call_model", "Call model", err.public_message)
        stages.skip("validate_evidence", "Validate against the records", "No model reply")
        st = stages.begin("prepare_draft", "Prepare draft")
        draft = guardrails.validate_draft(build_template_draft(bundle), a)
        self._insert_draft(conn, case_id, run_id, draft, "unavailable", "rules-only")
        self._insert_recommendation(conn, case_id, draft, a, "rules")
        stages.end(
            st, "done", "Rules-only draft prepared because AI is not usable; it is not AI output"
        )
        stages.items.append(
            {
                "key": "await_human",
                "label": "Await human decision",
                "status": "pending",
                "started_at": _now(),
                "finished_at": None,
                "duration_ms": None,
                "detail": "A TA or professor must review and decide",
            }
        )
        self._finish_run(
            conn,
            run_id,
            outcome="error",
            result=None,
            err=err,
            validation={},
            ai_output={},
            stages=stages,
            total_ms=int((time.monotonic() - t_run) * 1000),
            usage={},
        )
        return {
            "mode": "live",
            "status": "error",
            "cached": False,
            "run_id": run_id,
            "error_kind": err.kind,
            "message": err.public_message,
        }

    # ------------------------------------------------------------------------ DB helpers
    def _cached(self, conn: Any, case_id: str, fp: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT r.id, r.mode FROM analysis_runs r JOIN response_drafts d ON d.run_id = r.id "
            "WHERE r.case_id=? AND r.fingerprint=? AND r.outcome IN ('accepted','mock') "
            "ORDER BY r.id DESC LIMIT 1",
            (case_id, fp),
        ).fetchone()
        return dict(row) if row else None

    def _start_run(self, conn: Any, case_id: str, fp: str, mode: str, client: str) -> int:
        provider = self.llm.provider if mode == "live" else mode
        cur = conn.execute(
            "INSERT INTO analysis_runs (case_id, fingerprint, mode, outcome, provider, model, started_at, client)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                case_id,
                fp,
                mode,
                "running",
                provider,
                self.s.model if mode == "live" else "",
                _now(),
                client,
            ),
        )
        return int(cur.lastrowid or 0)

    def _finish_run(
        self,
        conn: Any,
        run_id: int,
        *,
        outcome: str,
        result: Any,
        err: LLMError | None,
        validation: dict[str, Any],
        ai_output: dict[str, Any],
        stages: Stages,
        total_ms: int,
        usage: dict[str, Any],
    ) -> None:
        conn.execute(
            "UPDATE analysis_runs SET outcome=?, finished_at=?, latency_ms=?, attempts=?, model=COALESCE(NULLIF(?, ''), model),"
            " prompt_tokens=?, completion_tokens=?, total_tokens=?, error_kind=?, error_message=?,"
            " validation=?, ai_output=?, stages=? WHERE id=?",
            (
                outcome,
                _now(),
                result.latency_ms if result else total_ms,
                result.attempts if result else (err.attempts if err else 0),
                result.model if result else "",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                err.kind if err else "",
                err.public_message if err else "",
                j(validation),
                j(ai_output),
                j(stages.dump()),
                run_id,
            ),
        )

    def _insert_draft(
        self, conn: Any, case_id: str, run_id: int, d: dict[str, Any], ai_status: str, source: str
    ) -> int:
        version = (
            1
            + conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM response_drafts WHERE case_id=?", (case_id,)
            ).fetchone()[0]
        )
        cur = conn.execute(
            "INSERT INTO response_drafts (case_id, version, body_ai, verified, unverified, flags, ai_status,"
            " source, classification_ai, summary_ai, created_at, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                case_id,
                version,
                d["reply"],
                j(d["verified"]),
                j(d["unverified"]),
                j(d["flags"]),
                ai_status,
                source,
                d["classification"],
                d["summary"],
                _now(),
                run_id,
            ),
        )
        return int(cur.lastrowid or 0)

    def _insert_recommendation(
        self, conn: Any, case_id: str, d: dict[str, Any], a: dict[str, Any], source: str
    ) -> None:
        cited = (
            sorted({i for c in d["verified"] for i in c["evidence_ids"]}) if source == "ai" else []
        )
        conn.execute(
            "INSERT INTO recommendations (case_id, source, rationale, uncertainty, evidence_ids,"
            " policy_version, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                case_id,
                source,
                d["rationale"],
                d["uncertainty"],
                j(cited),
                a["policy"]["version"],
                _now(),
            ),
        )

    # ------------------------------------------------------------------------ read side
    @staticmethod
    def _public_run(r: Any) -> dict[str, Any]:
        d = row_dict(r, RUN_JSON)
        d.pop("client", None)
        d.pop("ai_output", None)
        return d

    def describe(
        self, conn: Any, case_id: str, ev: list[dict[str, Any]], case_status: str
    ) -> dict[str, Any]:
        fp = self.fingerprint(ev)
        rows = conn.execute(
            "SELECT * FROM analysis_runs WHERE case_id=? ORDER BY id DESC LIMIT 5", (case_id,)
        ).fetchall()
        runs = [self._public_run(r) for r in rows]
        latest = runs[0] if runs else None
        if latest:
            for stage in latest["stages"]:
                if stage["key"] == "await_human":
                    done = case_status == "Closed"
                    stage["status"] = "done" if done else "pending"
                    stage["detail"] = (
                        "Decision recorded" if done else "A TA or professor must review and decide"
                    )
        usable = next((r for r in rows if r["outcome"] in USABLE), None)
        view = None
        if usable is not None:
            out = json.loads(usable["ai_output"]).get("cleaned")
            if out:
                view = {
                    **out,
                    "run_id": usable["id"],
                    "source": usable["mode"],
                    "model": usable["model"],
                    "stale": usable["fingerprint"] != fp,
                }
        rejected = None
        if latest and latest["outcome"] == "rejected":
            out = json.loads(rows[0]["ai_output"]).get("raw") or {}
            rejected = {
                "run_id": latest["id"],
                "flags": latest["validation"].get("flags", []),
                "reply": out.get("reply", ""),
                "summary": out.get("summary", ""),
            }
        return {
            "fingerprint": fp,
            "latest": latest,
            "runs": runs,
            "stale": bool(latest and latest["fingerprint"] != fp),
            "current_valid": bool(
                latest and latest["fingerprint"] == fp and latest["outcome"] in USABLE
            ),
            "in_progress": bool(latest and latest["outcome"] == "running"),
            "view": view,
            "rejected": rejected,
        }

    def status(self, client: str | None = None) -> dict[str, Any]:
        s = self.s
        with connect(s.db_path) as conn:
            ok = conn.execute(
                "SELECT finished_at, model FROM analysis_runs WHERE mode='live' AND outcome='accepted' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            bad = conn.execute(
                "SELECT finished_at, error_kind, error_message, outcome FROM analysis_runs WHERE mode='live' AND outcome IN ('error','rejected') ORDER BY id DESC LIMIT 1"
            ).fetchone()
        out: dict[str, Any] = {
            "mode": s.ai_mode,  # mock | misconfigured | configured
            "provider": self.llm.provider,
            "model": s.model or None,
            "last_success_at": ok["finished_at"] if ok else None,
            "last_failure": (
                {
                    "at": bad["finished_at"],
                    "kind": bad["error_kind"] or bad["outcome"],
                    "message": bad["error_message"],
                }
                if bad
                else None
            ),
            "budget": self.budget.usage(),
            "limits": {"client_hourly": s.ai_client_hourly_limit},
        }
        return out


def _cleaned_view(c: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "classification",
        "summary",
        "verified",
        "unverified",
        "unresolved",
        "reply",
        "rationale",
        "uncertainty",
        "flags",
    )
    return {k: c[k] for k in keys}
