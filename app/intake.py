"""Validated, synthetic-only intake for new cases.

A new case needs its own structured records (deadline, attempts, rubric, scores). Nothing is
guessed or borrowed from the demo fixtures: whatever is not supplied is simply missing, and
the rule engine reports it ("Insufficient evidence"). There is no Canvas or email connector.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

STUDENT_RE = r"^S-[0-9A-F]{4,8}$"  # pseudonymous id, e.g. S-7F3A
ASSIGNMENT_RE = r"^[A-Za-z][A-Za-z0-9]{0,11}$"  # e.g. HW6
POLICY_RE = r"^POL-[A-Z]+-v[0-9]{1,2}$"
DEMO_STAFF = ("TA Rivera", "TA Chen", "Prof. Demo")

_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "an email address"),
    (
        re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
        "a phone number",
    ),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "a government id"),
    (re.compile(r"(?<![\w-])\d{8,}(?![\w-])"), "a long id number"),
    (re.compile(r"https?://", re.I), "a link"),
]


def _no_pii(value: str) -> str:
    for rx, what in _PII:
        if rx.search(value):
            raise ValueError(f"looks like {what}. This tool accepts synthetic data only: remove it")
    return value


def _aware_ts(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("must be an ISO time such as 2026-11-05T22:40:00-07:00") from None
    if dt.tzinfo is None:
        raise ValueError("must include a UTC offset such as -07:00")
    return dt.isoformat(timespec="seconds")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AttemptIn(_Strict):
    ts: str
    state: Literal["submitted", "unreadable", "empty_file", "alternate_evidence"] = "submitted"
    file: str | None = Field(default=None, max_length=60, pattern=r"^[\w.\- ]*$")

    _ts = field_validator("ts")(_aware_ts)


class RubricIn(_Strict):
    label: str = Field(min_length=1, max_length=60)
    max: float = Field(ge=0, le=1000)
    awarded: float = Field(ge=0, le=1000)

    _pii = field_validator("label")(_no_pii)

    @model_validator(mode="after")
    def _within_max(self) -> RubricIn:
        if self.awarded > self.max:
            raise ValueError("awarded cannot exceed max")
        return self


class ScoreIn(_Strict):
    entered: float | None = Field(default=None, ge=0, le=1000)
    posted: float | None = Field(default=None, ge=0, le=1000)
    graded: StrictBool = False
    late_deduction_applied: float = Field(default=0, ge=0, le=1000)


class ContextIn(_Strict):
    assignment_name: str = Field(min_length=1, max_length=60)
    deadline: str
    max_points: float = Field(gt=0, le=1000)
    policy_ref: str = Field(pattern=POLICY_RE)
    attempts: list[AttemptIn] = Field(default_factory=list, max_length=6)
    rubric: list[RubricIn] = Field(default_factory=list, max_length=12)
    score: ScoreIn | None = None

    _pii = field_validator("assignment_name")(_no_pii)
    _dl = field_validator("deadline")(_aware_ts)


class MessageIn(_Strict):
    channel: Literal["canvas_inbox", "email", "submission_comment"]
    direction: Literal["inbound", "outbound"] = "inbound"
    author: str | None = Field(default=None, max_length=40)
    ts: str
    text: str = Field(min_length=1, max_length=2000)

    _ts = field_validator("ts")(_aware_ts)
    _pii = field_validator("text", "author")(lambda v: _no_pii(v) if v else v)


class IntakeRequest(_Strict):
    synthetic_ack: StrictBool
    student: str = Field(pattern=STUDENT_RE)
    assignment: str = Field(pattern=ASSIGNMENT_RE)
    message: MessageIn
    context: ContextIn | None = None
    case_id: str | None = Field(default=None, pattern=r"^CASE-[A-Za-z0-9]{1,6}$")
    owner: str | None = None
    course: str | None = Field(default=None, max_length=40)  # defaults to the demo course
    # Provenance only: "screenshot" / "document" mean the form was pre-filled by the model from an
    # uploaded image / file and then reviewed and submitted by a person.
    source: Literal["form", "screenshot", "document"] = "form"

    _course = field_validator("course")(lambda v: _no_pii(v) if v else None)

    @field_validator("synthetic_ack")
    @classmethod
    def _ack(cls, v: bool) -> bool:
        if not v:
            raise ValueError("you must confirm that this is synthetic data")
        return v

    @field_validator("owner")
    @classmethod
    def _owner(cls, v: str | None) -> str | None:
        if v and v not in DEMO_STAFF:
            raise ValueError(f"must be one of {', '.join(DEMO_STAFF)}")
        return v or None

    @model_validator(mode="after")
    def _consistency(self) -> IntakeRequest:
        m = self.message
        if m.direction == "outbound":
            if m.author not in DEMO_STAFF:
                raise ValueError(
                    f"an outbound reply must be authored by one of {', '.join(DEMO_STAFF)}"
                )
            if not self.case_id:
                raise ValueError("a reply can only be added to an existing case (case_id)")
        elif m.author and m.author != self.student:
            raise ValueError("an inbound message must be authored by the student id")
        if self.case_id and self.context is not None:
            raise ValueError("context can only be supplied when creating a new case")
        return self


def to_context(req: IntakeRequest, letter: str) -> dict[str, Any] | None:
    """Convert validated input into the same context shape the fixtures use."""
    c = req.context
    if c is None:
        return None
    sc = c.score or ScoreIn()
    ctx: dict[str, Any] = {
        "letter": letter,
        "student": req.student,
        "assignment": req.assignment,
        "name": c.assignment_name,
        "deadline": c.deadline,
        "max_points": c.max_points,
        "policy_ref": c.policy_ref,
        "attempts": [a.model_dump() for a in c.attempts],
        "rubric": [r.model_dump() for r in c.rubric],
        "score": {
            "entered": sc.entered,
            "posted": sc.posted,
            "graded": sc.graded,
            "late_deduction_applied": sc.late_deduction_applied,
            "graded_attempt": None,
            "graded_at": req.message.ts,
        },
    }
    if not c.attempts:
        ctx["submission_status"] = {"state": "not_submitted", "checked_at": req.message.ts}
    return ctx


EXAMPLES: list[dict[str, Any]] = [
    {
        "title": "Late flag: on-time first attempt, late second attempt",
        "request": {
            "synthetic_ack": True,
            "student": "S-4B21",
            "assignment": "HW6",
            "message": {
                "channel": "canvas_inbox",
                "ts": "2026-11-09T08:15:00-07:00",
                "text": "I submitted on time but HW6 shows late. My first upload was before midnight.",
            },
            "context": {
                "assignment_name": "Homework 6",
                "deadline": "2026-11-08T23:59:00-07:00",
                "max_points": 10,
                "policy_ref": "POL-LATE-v1",
                "attempts": [
                    {"ts": "2026-11-08T23:20:00-07:00", "state": "submitted", "file": "hw6_a.pdf"},
                    {"ts": "2026-11-09T00:05:00-07:00", "state": "submitted", "file": "hw6_b.pdf"},
                ],
                "rubric": [
                    {"label": "Part 1", "max": 5, "awarded": 5},
                    {"label": "Part 2", "max": 5, "awarded": 4},
                ],
                "score": {"entered": 7, "posted": 7, "graded": True, "late_deduction_applied": 2},
            },
        },
    },
    {
        "title": "Score gap: rubric rows add up to more than the entered score",
        "request": {
            "synthetic_ack": True,
            "student": "S-9C07",
            "assignment": "HW7",
            "message": {
                "channel": "email",
                "ts": "2026-11-09T10:00:00-07:00",
                "text": "My HW7 rubric shows full marks on every row but the score is 6 out of 10.",
            },
            "context": {
                "assignment_name": "Homework 7",
                "deadline": "2026-11-07T23:59:00-07:00",
                "max_points": 10,
                "policy_ref": "POL-LATE-v1",
                "attempts": [{"ts": "2026-11-07T20:00:00-07:00", "state": "submitted"}],
                "rubric": [{"label": f"Row {i}", "max": 2, "awarded": 2} for i in range(1, 6)],
                "score": {"entered": 6, "posted": 6, "graded": True, "late_deduction_applied": 0},
            },
        },
    },
    {
        "title": "Policy not on file: forces the hold path",
        "request": {
            "synthetic_ack": True,
            "student": "S-1E55",
            "assignment": "HW8",
            "message": {
                "channel": "submission_comment",
                "ts": "2026-11-09T11:30:00-07:00",
                "text": "I submitted on time but it says late on HW8.",
            },
            "context": {
                "assignment_name": "Homework 8",
                "deadline": "2026-11-08T23:59:00-07:00",
                "max_points": 10,
                "policy_ref": "POL-LATE-v9",
                "attempts": [{"ts": "2026-11-09T00:30:00-07:00", "state": "submitted"}],
                "rubric": [{"label": "All", "max": 10, "awarded": 10}],
                "score": {"entered": 8, "posted": 8, "graded": True, "late_deduction_applied": 2},
            },
        },
    },
]
