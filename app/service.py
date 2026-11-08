"""Case desk operations: import, duplicates, decisions, drafts. All state is in SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app import fixtures, guardrails
from app.config import Settings
from app.db import clear_all, connect, init_db, j, row_dict
from app.drafting import build_template_draft, finalize_reply
from app.engine import analyze, classify_issue
from app.llm import LLM

STATUSES = ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"]
ACTIONS = ["approve", "hold", "reject", "escalate", "request_info"]
ACTORS = {"ta": "TA Rivera", "professor": "Prof. Demo"}
# status after each action ("hold" keeps the case in TA review but flags it)
NEXT_STATUS = {
    "approve": "Closed",
    "reject": "Closed",
    "hold": "TA review",
    "escalate": "Awaiting professor",
    "request_info": "Awaiting student info",
}
NOTE_REQUIRED = {"hold", "reject", "escalate", "request_info"}


class DeskError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Desk:
    def __init__(self, settings: Settings, llm: LLM) -> None:
        self.settings = settings
        self.llm = llm
        init_db(settings.db_path)
        with connect(settings.db_path) as conn:
            empty = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
        if empty:
            self.seed()

    def _conn(self) -> Any:
        return connect(self.settings.db_path)

    # ------------------------------------------------------------------ import / seed

    def seed(self, reset: bool = False) -> None:
        with self._conn() as conn:
            if reset:
                clear_all(conn)
            for msg in fixtures.MESSAGES:
                self._import(conn, msg)
            self._detect_duplicates(conn)

    def import_message(self, msg: dict[str, Any]) -> str:
        with self._conn() as conn:
            case_id = self._import(conn, msg)
            self._detect_duplicates(conn)
            return case_id

    def _import(self, conn: sqlite3.Connection, m: dict[str, Any]) -> str:
        ctx = next(
            (
                c
                for c in fixtures.CONTEXTS
                if c["student"] == m["student"] and c["assignment"] == m["assignment"]
            ),
            None,
        )
        case_id = m.get("case_id")
        if not case_id:
            n = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            case_id = f"CASE-{n + 1:03d}"
        exists = conn.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone()
        if not exists:
            ts = now()
            conn.execute(
                "INSERT INTO cases (id, course, assignment, assignment_name, student_id, owner,"
                " status, issue, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    fixtures.COURSE,
                    m["assignment"],
                    ctx["name"] if ctx else m["assignment"],
                    m["student"],
                    m.get("owner"),
                    "New",
                    classify_issue(m["text"]) if m["direction"] == "inbound" else "other",
                    ts,
                    ts,
                ),
            )
            if ctx:
                self._attach_context(conn, case_id, ctx)
        conn.execute(
            "INSERT OR IGNORE INTO evidence (case_id, source_type, ref_id, ts, summary, source_text,"
            " payload) VALUES (?,?,?,?,?,?,?)",
            (
                case_id,
                "message",
                m["id"],
                m["ts"],
                f"{m['role']} message via {m['channel']} ({m['direction']}) from {m['author']}",
                m["text"],
                j(
                    {
                        "channel": m["channel"],
                        "direction": m["direction"],
                        "author": m["author"],
                        "role": m["role"],
                    }
                ),
            ),
        )
        self._sync_review_items(conn, case_id)
        return case_id

    def _attach_context(self, conn: sqlite3.Connection, case_id: str, c: dict[str, Any]) -> None:
        L = c["letter"]

        def add(
            kind: str, ref: str, ts: str, summary: str, payload: dict[str, Any], text: str = ""
        ) -> None:
            conn.execute(
                "INSERT OR IGNORE INTO evidence (case_id, source_type, ref_id, ts, summary,"
                " source_text, payload) VALUES (?,?,?,?,?,?,?)",
                (case_id, kind, ref, ts, summary, text, j(payload)),
            )

        add(
            "deadline",
            f"DL-{L}",
            c["deadline"],
            f"{c['name']} deadline; max {c['max_points']} points; policy {c['policy_ref']}",
            {
                "deadline": c["deadline"],
                "max_points": c["max_points"],
                "policy_ref": c["policy_ref"],
            },
        )
        pol = fixtures.POLICIES.get(c["policy_ref"])
        if pol:
            add(
                "policy",
                c["policy_ref"],
                pol["effective"],
                f"Course late work policy {c['policy_ref']}",
                {"version": c["policy_ref"], "params": pol["params"]},
                pol["text"],
            )
        for i, a in enumerate(c["attempts"], start=1):
            add(
                "attempt",
                f"ATT-{L}{i}",
                a["ts"],
                f"Submission attempt {i} ({a['state']})",
                {"state": a["state"], "file": a.get("file")},
            )
        if "submission_status" in c:
            st = c["submission_status"]
            add(
                "submission_status",
                f"SUB-{L}",
                st["checked_at"],
                f"Canvas submission status: {st['state'].replace('_', ' ')}",
                {"state": st["state"]},
            )
        for i, r in enumerate(c["rubric"], start=1):
            add(
                "rubric",
                f"RUB-{L}-row{i}",
                c["score"]["graded_at"],
                f"Rubric row {i} ({r['label']}): {r['awarded']} of {r['max']}",
                r,
            )
        sc = c["score"]
        add(
            "score",
            f"SCORE-{L}",
            sc["graded_at"],
            f"Gradebook: entered {sc['entered']}, posted {sc['posted']}, "
            f"late deduction recorded {sc['late_deduction_applied']}",
            sc,
        )

    def _sync_review_items(self, conn: sqlite3.Connection, case_id: str) -> None:
        a = analyze(self._evidence(conn, case_id))
        for item in a["review_items"]:
            conn.execute(
                "INSERT OR IGNORE INTO review_items (case_id, kind, title, route_to, evidence_ids,"
                " created_at) VALUES (?,?,?,?,?,?)",
                (
                    case_id,
                    item["kind"],
                    item["title"],
                    item["route_to"],
                    j(item["evidence_ids"]),
                    now(),
                ),
            )

    # ---------------------------------------------------------------------- duplicates

    def _detect_duplicates(self, conn: sqlite3.Connection) -> None:
        """Propose (never auto-merge) cases with the same student+course+assignment+issue."""
        rows = conn.execute(
            "SELECT id, student_id, course, assignment, issue FROM cases "
            "WHERE merged_into IS NULL AND status != 'Closed' AND issue != 'other' ORDER BY id"
        ).fetchall()
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                key = ("student_id", "course", "assignment", "issue")
                if all(a[k] == b[k] for k in key):
                    reason = (
                        f"Same student, course, assignment ({a['assignment']}) and issue "
                        f"({a['issue']})"
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO duplicates (case_a, case_b, reason, created_at)"
                        " VALUES (?,?,?,?)",
                        (a["id"], b["id"], reason, now()),
                    )

    def resolve_duplicate(self, dup_id: int, role: str, confirm: bool) -> dict[str, Any]:
        actor = self._actor(role)
        with self._conn() as conn:
            d = conn.execute("SELECT * FROM duplicates WHERE id=?", (dup_id,)).fetchone()
            if d is None:
                raise DeskError(404, "duplicate candidate not found")
            if d["status"] != "proposed":
                raise DeskError(409, f"already {d['status']}")
            if not confirm:
                conn.execute("UPDATE duplicates SET status='dismissed' WHERE id=?", (dup_id,))
                return {"status": "dismissed"}
            keep, drop = d["case_a"], d["case_b"]
            for row in conn.execute("SELECT * FROM evidence WHERE case_id=?", (drop,)).fetchall():
                conn.execute(  # evidence with the same ref id already exists on the primary case
                    "INSERT OR IGNORE INTO evidence (case_id, source_type, ref_id, ts, summary,"
                    " source_text, payload) VALUES (?,?,?,?,?,?,?)",
                    (
                        keep,
                        row["source_type"],
                        row["ref_id"],
                        row["ts"],
                        row["summary"],
                        row["source_text"],
                        row["payload"],
                    ),
                )
            conn.execute(
                "UPDATE cases SET merged_into=?, updated_at=? WHERE id=?", (keep, now(), drop)
            )
            conn.execute("UPDATE duplicates SET status='confirmed' WHERE id=?", (dup_id,))
            note = f"Merged {drop} into {keep}: {d['reason']}"
            for cid in (keep, drop):
                self._log(conn, cid, actor, role, "merge", note, None, None)
            self._sync_review_items(conn, keep)
            return {"status": "confirmed", "primary": keep}

    # ------------------------------------------------------------------------ queries

    @staticmethod
    def _evidence(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
        rows = conn.execute("SELECT * FROM evidence WHERE case_id=?", (case_id,)).fetchall()
        return [row_dict(r, ("payload",)) for r in rows]

    @staticmethod
    def _case(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
        r = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if r is None:
            raise DeskError(404, "case not found")
        return dict(r)

    @staticmethod
    def _actor(role: str) -> str:
        if role not in ACTORS:
            raise DeskError(400, "role must be 'ta' or 'professor'")
        return ACTORS[role]

    @staticmethod
    def _last_reply(evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
        out = [
            e
            for e in evidence
            if e["source_type"] == "message" and e["payload"]["direction"] == "outbound"
        ]
        if not out:
            return None
        e = max(out, key=lambda x: x["ts"])
        return {
            "channel": e["payload"]["channel"],
            "by": e["payload"]["author"],
            "ts": e["ts"],
            "ref_id": e["ref_id"],
        }

    @staticmethod
    def _waiting(case: dict[str, Any], a: dict[str, Any]) -> str:
        st = case["status"]
        if st == "Closed":
            return "-"
        note = case["status_note"]
        if st == "Awaiting student info":
            need = next((r["title"] for r in a["review_items"] if r["route_to"] == "student"), "")
            return "Student to respond: " + (need or note)
        if st == "Awaiting professor":
            need = next((r["title"] for r in a["review_items"] if r["route_to"] == "professor"), "")
            return "Professor to decide: " + (need or note)
        if case["on_hold"]:
            return "On hold: " + note
        if a["blockers"]:
            return "Hold / info needed: " + a["blockers"][0]["text"]
        if a["gates"] and not a["professor_approved"]:
            return "Needs professor decision: " + next(
                (r["title"] for r in a["review_items"] if r["route_to"] == "professor"), ""
            )
        return "TA to review"

    def _summary(self, conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
        ev = self._evidence(conn, case["id"])
        a = analyze(ev)
        dups = conn.execute(
            "SELECT * FROM duplicates WHERE status='proposed' AND (case_a=? OR case_b=?)",
            (case["id"], case["id"]),
        ).fetchall()
        return {
            **case,
            "on_hold": bool(case["on_hold"]),
            "channels": sorted(
                {e["payload"]["channel"] for e in ev if e["source_type"] == "message"}
            ),
            "last_reply": self._last_reply(ev),
            "waiting_reason": self._waiting(case, a),
            "duplicates": [
                {
                    "id": d["id"],
                    "other": d["case_b"] if d["case_a"] == case["id"] else d["case_a"],
                    "reason": d["reason"],
                }
                for d in dups
            ],
            "insufficient_evidence": any(
                w["text"].startswith("Insufficient evidence") for w in a["warnings"]
            ),
            "suggested_action": a["suggested_action"],
            "requires_professor": a["requires_professor"],
        }

    def list_cases(
        self,
        status: str | None = None,
        owner: str | None = None,
        channel: str | None = None,
        duplicates: bool = False,
        include_merged: bool = False,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM cases ORDER BY id").fetchall()
            out = []
            for r in rows:
                case = dict(r)
                if case["merged_into"] and not include_merged:
                    continue
                s = self._summary(conn, case)
                if status and s["status"] != status:
                    continue
                if owner and (s["owner"] or "unassigned") != owner:
                    continue
                if channel and channel not in s["channels"]:
                    continue
                if duplicates and not s["duplicates"]:
                    continue
                out.append(s)
            return out

    def permissions(self, case: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
        def check(role: str, action: str) -> dict[str, Any]:
            def no(code: str, why: str) -> dict[str, Any]:
                return {
                    "enabled": False,
                    "code": code,
                    "reason": why,
                    "next_status": NEXT_STATUS[action],
                }

            if case["merged_into"]:
                return no("merged", f"Merged into {case['merged_into']}")
            if case["status"] == "Closed":
                return no("closed", "Case is closed")
            if action in ("approve", "reject"):
                if a["blockers"]:
                    return no("blocked", "Blocked: " + a["blockers"][0]["text"])
                if a["requires_professor"] and role != "professor" and not a["professor_approved"]:
                    return no("role", "Professor-only: policy exception or score change")
            if action == "escalate" and role == "professor":
                return no("role", "You are the professor")
            if action == "escalate" and case["status"] == "Awaiting professor":
                return no("state", "Already with the professor")
            return {"enabled": True, "code": "ok", "reason": "", "next_status": NEXT_STATUS[action]}

        return {r: {act: check(r, act) for act in ACTIONS} for r in ACTORS}

    def case_detail(self, case_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            case = self._case(conn, case_id)
            ev = self._evidence(conn, case_id)
            ev.sort(key=lambda e: (datetime.fromisoformat(e["ts"]), e["ref_id"]))
            a = analyze(ev)
            summary = self._summary(conn, case)
            draft = conn.execute(
                "SELECT * FROM response_drafts WHERE case_id=? ORDER BY version DESC LIMIT 1",
                (case_id,),
            ).fetchone()
            recs = [
                row_dict(r, ("evidence_ids", "payload"))
                for r in conn.execute(
                    "SELECT * FROM recommendations WHERE case_id=? ORDER BY id", (case_id,)
                )
            ]
            score_rec = next((r for r in reversed(recs) if r["source"] == "score_change"), None)
            return {
                "case": summary,
                "evidence": ev,
                "analysis": {k: v for k, v in a.items() if k != "ids"},
                "review_items": [
                    row_dict(r, ("evidence_ids",))
                    for r in conn.execute(
                        "SELECT * FROM review_items WHERE case_id=? ORDER BY id", (case_id,)
                    )
                ],
                "recommendations": recs,
                "draft": row_dict(draft, ("verified", "unverified", "flags")) if draft else None,
                "decisions": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM decisions WHERE case_id=? ORDER BY id", (case_id,)
                    )
                ],
                "permissions": self.permissions(case, a),
                "score_control": {
                    "enabled": bool(a["score_change"]) and score_rec is None,
                    "reason": ""
                    if a["professor_approved"]
                    else "Disabled until a professor approval exists",
                    "recorded": score_rec,
                },
                "ai": {"mode": "mock" if self.llm.mock else "vultr-inference"},
            }

    # ----------------------------------------------------------------------- decisions

    @staticmethod
    def _log(
        conn: sqlite3.Connection,
        case_id: str,
        actor: str,
        role: str,
        action: str,
        note: str,
        frm: str | None,
        to: str | None,
    ) -> None:
        conn.execute(
            "INSERT INTO decisions (case_id, actor, role, action, ts, note, from_status, to_status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (case_id, actor, role, action, now(), note, frm, to),
        )

    def decide(
        self,
        case_id: str,
        role: str,
        action: str,
        note: str = "",
        counted_attempt: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(role)
        if action not in ACTIONS:
            raise DeskError(400, f"unknown action {action!r}")
        note = (note or "").strip()
        if action in NOTE_REQUIRED and not note:
            raise DeskError(400, "A note is required for this action")
        with self._conn() as conn:
            case = self._case(conn, case_id)
            ev = self._evidence(conn, case_id)
            a = analyze(ev)
            perm = self.permissions(case, a)[role][action]
            if not perm["enabled"]:
                code = {"role": 403, "blocked": 409}.get(perm["code"], 409)
                raise DeskError(code, perm["reason"])

            if action == "approve":
                draft = conn.execute(
                    "SELECT * FROM response_drafts WHERE case_id=? ORDER BY version DESC LIMIT 1",
                    (case_id,),
                ).fetchone()
                if draft is None:
                    raise DeskError(409, "Generate and review the reply draft before approving")
                text = body if body is not None else (draft["body_edited"] or draft["body_ai"])
                flags = guardrails.check_text(text, a)
                if flags:
                    raise DeskError(409, "Reply needs verification: " + flags[0]["message"])
                attempt_item = any(r["kind"] == "attempt_basis" for r in a["review_items"])
                valid_attempts = {x["ref_id"] for x in a["attempts"] if x["state"] == "submitted"}
                if role == "professor" and attempt_item and counted_attempt not in valid_attempts:
                    raise DeskError(400, "Select which attempt counts (counted_attempt)")
                approval_ref = None
                if role == "professor":
                    n = 1 + sum(1 for e in ev if e["source_type"] == "approval")
                    approval_ref = f"APR-{case_id.split('-', 1)[1]}-{n}"
                    fixed = finalize_reply(
                        text, approval_ref, counted_attempt if attempt_item else None
                    )
                    if fixed is None:
                        raise DeskError(
                            409,
                            "The reply still says the decision is pending. Edit that sentence "
                            "or regenerate the draft, then approve again.",
                        )
                    text = fixed
                conn.execute(
                    "UPDATE response_drafts SET body_edited=?, body_final=?, approved_at=?,"
                    " approved_by=? WHERE id=?",
                    (text, text, now(), actor, draft["id"]),
                )
                if role == "professor":
                    conn.execute(
                        "INSERT INTO evidence (case_id, source_type, ref_id, ts, summary,"
                        " source_text, payload) VALUES (?,?,?,?,?,?,?)",
                        (
                            case_id,
                            "approval",
                            approval_ref,
                            now(),
                            f"Professor approval by {actor}",
                            note,
                            j(
                                {
                                    "role": "professor",
                                    "action": "approve",
                                    "actor": actor,
                                    "counted_attempt": counted_attempt if attempt_item else None,
                                }
                            ),
                        ),
                    )

            to_status = NEXT_STATUS[action]
            if action in ("approve", "reject"):
                conn.execute(
                    "UPDATE review_items SET status='resolved' WHERE case_id=?", (case_id,)
                )
            owner = case["owner"] or (actor if role == "ta" else None)
            conn.execute(
                "UPDATE cases SET status=?, status_note=?, on_hold=?, owner=?, updated_at=?"
                " WHERE id=?",
                (to_status, note, 1 if action == "hold" else 0, owner, now(), case_id),
            )
            self._log(conn, case_id, actor, role, action, note, case["status"], to_status)
        return self.case_detail(case_id)

    def record_score_recommendation(self, case_id: str, role: str) -> dict[str, Any]:
        """Writes a recommendation row only. There is no Canvas write anywhere in this app."""
        actor = self._actor(role)
        with self._conn() as conn:
            case = self._case(conn, case_id)
            a = analyze(self._evidence(conn, case_id))
            if not a["professor_approved"]:
                raise DeskError(409, "A professor approval is required first")
            sc = a["score_change"]
            if sc is None:
                raise DeskError(409, "The approved basis gives the same score; nothing to record")
            if conn.execute(
                "SELECT 1 FROM recommendations WHERE case_id=? AND source='score_change'",
                (case_id,),
            ).fetchone():
                raise DeskError(409, "A score recommendation is already recorded")
            conn.execute(
                "INSERT INTO recommendations (case_id, source, rationale, uncertainty, evidence_ids,"
                " policy_version, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    "score_change",
                    f"Recommend entering {sc['to']:g} instead of {sc['from']:g} "
                    f"(basis {sc['basis_attempt']}). Recommendation only; not applied in Canvas.",
                    "Final grade entry is up to the instructor in Canvas.",
                    j(a["score_state"]["evidence_ids"] + sc["approval_ids"]),
                    a["policy"]["version"],
                    j(sc),
                    now(),
                ),
            )
            self._log(
                conn,
                case_id,
                actor,
                role,
                "record_score_recommendation",
                f"{sc['from']:g} -> {sc['to']:g} (recommendation only)",
                case["status"],
                case["status"],
            )
        return self.case_detail(case_id)

    # ----------------------------------------------------------------------- AI draft

    def generate_draft(self, case_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            case = self._case(conn, case_id)
            if case["merged_into"]:
                raise DeskError(409, f"Merged into {case['merged_into']}")
            ev = self._evidence(conn, case_id)
            ev.sort(key=lambda e: e["ts"])
            a = analyze(ev)
            bundle = {
                "case": {
                    k: case[k]
                    for k in (
                        "id",
                        "course",
                        "assignment",
                        "assignment_name",
                        "issue",
                        "student_id",
                    )
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
                    )
                },
            }
            ai_status, source, error = ("mock", "mock", "") if self.llm.mock else ("ok", "llm", "")
            try:
                raw = self.llm.draft(bundle)
            except Exception as exc:  # LLM failure/timeout must never break the app
                raw = build_template_draft(bundle)
                ai_status, source, error = "unavailable", "rules-only", str(exc)[:300]
            draft = guardrails.validate_draft(raw, a)
            version = (
                1
                + (
                    conn.execute(
                        "SELECT COALESCE(MAX(version),0) FROM response_drafts WHERE case_id=?",
                        (case_id,),
                    ).fetchone()[0]
                )
            )
            conn.execute(
                "INSERT INTO response_drafts (case_id, version, body_ai, verified, unverified,"
                " flags, ai_status, source, classification_ai, summary_ai, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    version,
                    draft["reply"],
                    j(draft["verified"]),
                    j(draft["unverified"]),
                    j(draft["flags"]),
                    ai_status,
                    source,
                    draft["classification"],
                    draft["summary"],
                    now(),
                ),
            )
            if ai_status != "unavailable":
                cited = sorted({i for c in draft["verified"] for i in c["evidence_ids"]})
                conn.execute(
                    "INSERT INTO recommendations (case_id, source, rationale, uncertainty,"
                    " evidence_ids, policy_version, created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        case_id,
                        "ai",
                        draft["rationale"],
                        draft["uncertainty"],
                        j(cited),
                        a["policy"]["version"],
                        now(),
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO recommendations (case_id, source, rationale, uncertainty,"
                    " evidence_ids, policy_version, created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        case_id,
                        "rules",
                        draft["rationale"],
                        draft["uncertainty"],
                        j([]),
                        a["policy"]["version"],
                        now(),
                    ),
                )
        result = self.case_detail(case_id)
        result["ai"] = {
            "mode": "mock" if self.llm.mock else "vultr-inference",
            "status": ai_status,
            "error": error,
        }
        return result

    def save_draft(self, case_id: str, body: str) -> dict[str, Any]:
        with self._conn() as conn:
            self._case(conn, case_id)
            d = conn.execute(
                "SELECT id, approved_at FROM response_drafts WHERE case_id=? "
                "ORDER BY version DESC LIMIT 1",
                (case_id,),
            ).fetchone()
            if d is None:
                raise DeskError(404, "no draft yet")
            if d["approved_at"]:
                raise DeskError(409, "Draft already approved")
            conn.execute("UPDATE response_drafts SET body_edited=? WHERE id=?", (body, d["id"]))
        return self.case_detail(case_id)

    def check_body(self, case_id: str, body: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._case(conn, case_id)
            return guardrails.check_text(body, analyze(self._evidence(conn, case_id)))


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=str)
