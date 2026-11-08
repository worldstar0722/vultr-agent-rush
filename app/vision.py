"""Screenshot-to-case intake (synthetic data only).

    upload (png/jpg/webp, <= 5 MiB) -> vision model -> extracted fields -> a person reviews them
    -> POST /api/intake creates the case through the same validated pipeline as the form.

What the vision model returns is UNTRUSTED. It is normalised field by field (never trusted to
be well formed), scrubbed for personal data, and used only to pre-fill a form. A case is created
only through `IntakeRequest` validation; the optional `auto_create` path runs exactly that same
validation and refuses anything incomplete.

Privacy and cost properties (all covered by tests):
* the image is processed in memory: never written to disk, never logged, never stored;
* the response never contains the image or the raw model text;
* every provider attempt is reserved from the same lifetime budget as text analysis, and the
  same per-client hourly throttle applies;
* a student id must be a pseudonymous id (S-XXXX): a real name returned by the model is dropped;
* emails, phone numbers, links and long numbers in any extracted text are removed and reported;
* in mock mode no model looks at the image: clearly labelled sample values come back instead.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.budget import Budget, RateLimited
from app.engine import classify_issue
from app.errors import DeskError
from app.intake import _PII, ASSIGNMENT_RE, STUDENT_RE, IntakeRequest
from app.llm import LLMError, fit_document
from app.uploads import detect, extract_text

if TYPE_CHECKING:
    from app.service import Desk

ISSUES = ("late_flag", "score_gap", "missing_submission", "other")
CHANNELS = ("canvas_inbox", "email", "submission_comment")
ASSUMED_OFFSET = "-07:00"  # the demo course's time zone; shown to the user as an assumption
LIFETIME_MSG = (
    "The lifetime AI budget for this deployment is used up. You can still create the case with "
    "the form; live AI stays off until an operator re-authorises spending."
)

# ------------------------------------------------------------------------ normalisation


class _Norm:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self._tz_noted = False

    def text(self, v: Any, field: str, limit: int) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()[:limit]
        for rx, what in _PII:
            if rx.search(v):
                self.problems.append(
                    f"Removed {field}: it looked like {what}. This tool takes synthetic data only."
                )
                return None
        return v

    def number(self, v: Any, field: str) -> float | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if not 0 <= v <= 1000:
            self.problems.append(f"Ignored {field}: the value is out of range.")
            return None
        return float(v)

    def when(self, v: Any, field: str) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return None
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            self.problems.append(f"Could not read the {field} as a time. Enter it by hand.")
            return None
        if dt.tzinfo is None:
            if not self._tz_noted:
                self.problems.append(
                    f"The screenshot showed no time zone. Times are assumed to be UTC{ASSUMED_OFFSET}: check them, and the year."
                )
                self._tz_noted = True
            return dt.isoformat(timespec="seconds") + ASSUMED_OFFSET
        return dt.isoformat(timespec="seconds")


def normalise(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    n = _Norm()
    sid = raw.get("student_id")
    student = (
        sid.strip().upper()
        if isinstance(sid, str) and re.fullmatch(STUDENT_RE, sid.strip().upper())
        else None
    )
    aid = raw.get("assignment_id")
    assignment = (
        aid.strip() if isinstance(aid, str) and re.fullmatch(ASSIGNMENT_RE, aid.strip()) else None
    )
    issue = raw.get("issue_type") if raw.get("issue_type") in ISSUES else "other"
    ch = raw.get("channel") if raw.get("channel") in CHANNELS else None
    f: dict[str, Any] = {
        "student_id": student,
        "assignment_id": assignment,
        "assignment_name": n.text(raw.get("assignment_name"), "assignment name", 60),
        "course": n.text(raw.get("course"), "course", 40),
        "issue_type": issue,
        "channel": ch,
        "student_message": n.text(raw.get("student_message"), "student message", 2000),
        "message_time": n.when(raw.get("message_time"), "message time"),
        "deadline": n.when(raw.get("deadline"), "deadline"),
        "submission_time": n.when(raw.get("submission_time"), "submission time"),
        "score_entered": n.number(raw.get("score_entered"), "entered score"),
        "rubric_total": n.number(raw.get("rubric_total"), "rubric total"),
        "max_points": n.number(raw.get("max_points"), "maximum points"),
        "confidence": raw.get("confidence")
        if raw.get("confidence") in ("high", "medium", "low")
        else "low",
        "notes": n.text(raw.get("notes"), "model note", 300),
    }
    p = n.problems
    if student is None:
        p.append(
            "No pseudonymous student id (like S-4B21) was readable. Enter one: real names are never accepted."
        )
    if assignment is None:
        p.append("No assignment id (like HW6) was readable. Enter one.")
    if f["student_message"] is None:
        p.append("No usable student message was extracted. Type or paste synthetic text.")
    if f["confidence"] == "low":
        p.append("The model reported low confidence. Check every value against the source file.")
    if f["student_message"]:
        rules = classify_issue(f["student_message"])
        if rules != "other" and rules != issue:
            p.append(
                f"The model labelled this '{issue}' but the rules read the message as '{rules}'. The rules label is used for the case."
            )
    return f, p


def to_intake(
    f: dict[str, Any], source: str = "screenshot"
) -> tuple[dict[str, Any] | None, list[str]]:
    """Map extracted fields onto the intake request shape. Returns (request, missing)."""
    missing = [k for k, label in (("student_id", "student id"), ("assignment_id", "assignment id"),
                                  ("student_message", "student message"), ("deadline", "deadline"),
                                  ("max_points", "maximum points"), ("assignment_name", "assignment name")) if not f.get(k)]  # fmt: skip
    ts = f["message_time"] or datetime.now(UTC).isoformat(timespec="seconds")
    ctx: dict[str, Any] | None = None
    if not [m for m in missing if m in ("deadline", "max_points", "assignment_name")]:
        attempts = (
            [{"ts": f["submission_time"], "state": "submitted"}] if f["submission_time"] else []
        )
        rubric = []
        if f["rubric_total"] is not None and f["rubric_total"] <= f["max_points"]:
            rubric = [
                {
                    "label": "Rubric total (read from screenshot)",
                    "max": f["max_points"],
                    "awarded": f["rubric_total"],
                }
            ]
        score = None
        if f["score_entered"] is not None:
            score = {"entered": f["score_entered"], "posted": f["score_entered"], "graded": True,
                     "late_deduction_applied": 0}  # fmt: skip
        ctx = {"assignment_name": f["assignment_name"], "deadline": f["deadline"], "max_points": f["max_points"],
               "policy_ref": "POL-LATE-v1", "attempts": attempts, "rubric": rubric, "score": score}  # fmt: skip
    req = {"synthetic_ack": True, "source": source, "student": f["student_id"], "assignment": f["assignment_id"],
           "course": f["course"],
           "message": {"channel": f["channel"] or "canvas_inbox", "ts": ts, "text": f["student_message"]},
           "context": ctx}  # fmt: skip
    return (req if not missing else None), missing


# ------------------------------------------------------------------------------ service


class VisionIntake:
    """Despite the name this now handles every upload: images (vision model) and PDF / DOCX /
    text / CSV (parsed locally, then sent to the text model). Same fields, same review step."""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self.s = desk.settings
        self.llm = desk.llm
        self.budget = Budget(desk.settings)
        self._busy: set[str] = set()
        self._guard = threading.Lock()

    def extract(self, data: bytes, client: str, synthetic_ack: bool, auto_create: bool = False,
                filename: str = "", content_type: str = "") -> dict[str, Any]:  # fmt: skip
        if not synthetic_ack:
            raise DeskError(
                400, "Confirm that the file contains only synthetic data.", "synthetic_ack_required"
            )
        if not data:
            raise DeskError(400, "The file is empty.", "empty_file")
        kind, mime = detect(data, filename, content_type)  # from the bytes; hints cannot override
        cap = self.s.ai_max_image_bytes if kind == "image" else self.s.ai_max_doc_bytes
        if len(data) > cap:
            raise DeskError(
                413, f"The file is larger than {cap // (1024 * 1024)} MiB.", "image_too_large"
            )
        mock = self.llm.mock
        if mock and auto_create:
            raise DeskError(
                409,
                "Mock mode returns sample values only. Review them and submit the form.",
                "mock_no_autocreate",
            )

        # Documents are parsed locally (free, in a time- and memory-limited child process) BEFORE any
        # budget is reserved, so an unreadable file never costs a call.
        text, truncated, info = "", False, {}
        if kind != "image":
            info = extract_text(kind, data)
            fixed = self.s.ai_max_prompt_bytes
            text, truncated = fit_document(info["text"], kind, fixed)
            if not text:
                raise DeskError(
                    422, "The text is too long to fit the safety limit.", "prompt_too_large"
                )

        def call(gate: Any) -> Any:
            if kind == "image":
                return self.llm.extract_image(data, mime, gate)
            return self.llm.extract_text(text, kind, gate)

        if not mock:
            if self.s.ai_mode != "configured":
                raise DeskError(
                    503,
                    "AI is not fully configured on the server (a model id is required).",
                    "not_configured",
                )
            with self._guard:
                if client in self._busy:
                    raise DeskError(
                        409, "A file is already being read for this client.", "vision_in_progress"
                    )
                self._busy.add(client)
            try:
                self.budget.check_client(client)
                if self.budget.usage()["exhausted"]:
                    raise RateLimited("ai_budget_exhausted", LIFETIME_MSG, None)
                self.budget.note_client_run(client)
                label = "vision-intake" if kind == "image" else "document-intake"
                try:
                    res = call(self.budget.gate(label, self.llm.provider, self.s.model))
                except LLMError as exc:
                    if exc.kind == "budget" and exc.attempts == 0:
                        raise RateLimited("ai_budget_exhausted", LIFETIME_MSG, None) from None
                    raise DeskError(502, exc.public_message, exc.kind) from None
            finally:
                with self._guard:
                    self._busy.discard(client)
        else:
            res = call(None)

        fields, problems = normalise(res.data if isinstance(res.data, dict) else {})
        if truncated:
            problems.append(
                "The document was longer than the safety limit, so only its first part was read. Check for missing details."
            )
        if info.get("pages") and info["pages"] > info.get("pages_read", info["pages"]):
            problems.append(
                f"Only the first {info['pages_read']} of {info['pages']} PDF pages were read."
            )
        source = "screenshot" if kind == "image" else "document"
        req, missing = to_intake(fields, source)
        out: dict[str, Any] = {
            "mock": mock,
            "kind": kind,
            "extraction": fields,
            "problems": problems,
            "missing_for_case": missing,
            "truncated": truncated,
            "text_chars": len(text) if kind != "image" else None,
            "created": False,
            "case_id": None,
            "provenance": {
                "provider": res.provider,
                "model": res.model,
                "latency_ms": res.latency_ms,
                "attempts": res.attempts,
                "total_tokens": res.usage.get("total_tokens"),
            },  # fmt: skip
        }
        if mock:
            what = "image" if kind == "image" else f"{kind} file"
            out["problems"] = [
                f"Mock mode: no model analysed this {what}. These are SAMPLE values: replace them."
            ] + problems
        if auto_create:
            if req is None:
                out["problems"].append("Not created: " + ", ".join(missing) + " could not be read.")
            else:
                try:
                    created = self.desk.intake(IntakeRequest.model_validate(req))
                    out.update(created=True, case_id=created["case_id"])
                except ValidationError as exc:
                    out["problems"].append(
                        "Not created: "
                        + "; ".join(
                            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                            for e in exc.errors()[:4]
                        )
                    )
        return out
