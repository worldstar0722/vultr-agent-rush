"""Deterministic reply template.

Used by MockLLM (offline demo) and as the fallback when the real LLM fails. It only
restates values the rule engine already computed and cites the evidence ids they came
from. It never promises an outcome.
"""

from __future__ import annotations

import re
from typing import Any

from app.engine import parse_ts

# Template sentences that say "a decision is still pending". They are removed from the final
# text when a professor decision is recorded, so an approved reply never contradicts it.
PENDING_BASIS = (
    "Whether the earlier or later attempt is used is a decision for the instructor. "
    "We cannot say yet what the outcome will be, and we will update you here."
)
PENDING_GAP = (
    "We have not found the reason for the difference between these numbers and are "
    "checking it with the instructor."
)
PENDING_RE = re.compile(
    r"cannot say yet|decision for the instructor|not (?:yet )?been decided|"
    r"checking (?:it|this) with the instructor|awaiting the instructor|pending (?:the )?instructor",
    re.I,
)


def finalize_reply(text: str, approval_ref: str, counted_attempt: str | None) -> str | None:
    """Make an approved reply consistent with a professor decision.

    Removes the known template "decision pending" sentences, appends a deterministic
    statement of the decision, and states that nothing was changed or sent. Returns None
    if the text still claims a pending decision in other words (a human must edit it).
    """
    for sentence in (PENDING_BASIS, PENDING_GAP):
        text = text.replace(sentence, "")
    if PENDING_RE.search(text):
        return None
    text = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", text)).rstrip()
    decided = (
        f"the instructor decided that {counted_attempt} counts as the submission"
        if counted_attempt
        else "the instructor reviewed this case and approved it"
    )
    statement = (
        f"Update: {decided} [{approval_ref}]. GradeCase records recommendations only: no "
        "grade has been changed in Canvas and no message has been sent. Any gradebook "
        "update is a separate step taken by the course staff."
    )
    signoff = "\n\nTA team"
    if text.endswith(signoff):  # keep the sign-off last
        return f"{text[: -len(signoff)]}\n\n{statement}{signoff}"
    return f"{text}\n\n{statement}"


def _n(v: float | None) -> str:
    return "n/a" if v is None else f"{v:g}"


def _when(ts: str) -> str:
    return parse_ts(ts).strftime("%H:%M on %b %d").replace(" 0", " ")


def _rel(minutes: int | None) -> str:
    if minutes is None:
        return ""
    if minutes <= 0:
        return f"{abs(minutes)} minutes before the deadline"
    return f"{minutes} minutes after the deadline"


def build_template_draft(bundle: dict[str, Any]) -> dict[str, Any]:
    a = bundle["analysis"]
    case = bundle["case"]
    s = a["score_state"]
    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    para: list[str] = []

    if a["deadline"]:
        d = a["deadline"]
        verified.append(
            {
                "text": f"The {case['assignment']} deadline is {_when(d['ts'])}.",
                "evidence_ids": [d["ref_id"]],
            }
        )
    for i, at in enumerate(a["attempts"], start=1):
        if at["state"] == "submitted":
            verified.append(
                {
                    "text": f"Attempt {i} was submitted at {_when(at['ts'])}, "
                    f"{_rel(at['minutes_vs_deadline'])}.",
                    "evidence_ids": [at["ref_id"]],
                }
            )
            para.append(
                f"Attempt {i} was submitted at {_when(at['ts'])}, "
                f"{_rel(at['minutes_vs_deadline'])} [{at['ref_id']}]."
            )
        else:
            unverified.append(
                {
                    "text": f"{at['ref_id']} is recorded as {at['state'].replace('_', ' ')}.",
                    "evidence_ids": [at["ref_id"]],
                }
            )
    if not a["attempts"] and a["deadline"]:
        sub_id = next((i for i in a["ids"] if i.startswith("SUB-")), a["deadline"]["ref_id"])
        verified.append(
            {"text": "Canvas shows no submission for this assignment.", "evidence_ids": [sub_id]}
        )
        para.append(f"We could not find a submission in Canvas for this assignment [{sub_id}].")

    if s["rubric_total"] is not None and s["entered"] is not None:
        ids = s["evidence_ids"]
        verified.append(
            {
                "text": f"Rubric total is {_n(s['rubric_total'])}; entered score is "
                f"{_n(s['entered'])}; posted score is {_n(s['posted'])}; "
                f"late deduction recorded is {_n(s['late_deduction_applied'])}.",
                "evidence_ids": ids,
            }
        )
        para.append(
            f"The rubric total is {_n(s['rubric_total'])} and the entered score is "
            f"{_n(s['entered'])} [{s['evidence_ids'][-1]}]; the recorded late deduction is "
            f"{_n(s['late_deduction_applied'])}."
        )
        for diff in s["differences"]:
            if diff["code"] == "entered_vs_expected":
                unverified.append(
                    {
                        "text": "The reason for the score difference is not recorded.",
                        "evidence_ids": diff["evidence_ids"],
                    }
                )
                para.append(PENDING_GAP)

    for b in a["blockers"]:
        text = b["text"]
        if b["code"] == "policy_missing":  # never print a policy id that has no record
            text = "The late policy referenced by the assignment was not found in the records."
        unverified.append(
            {
                "text": text,
                "evidence_ids": b["evidence_ids"]
                or ([a["deadline"]["ref_id"]] if a["deadline"] else []),
            }
        )
    for g in a["gates"]:
        unverified.append({"text": g["text"], "evidence_ids": [i for i in g["evidence_ids"] if i]})
    basis_open = any(g["code"] == "attempt_basis" for g in a["gates"])
    for m in bundle["student_claims"]:
        unverified.append({"text": f"Student states: {m['text']}", "evidence_ids": [m["ref_id"]]})

    if basis_open and not a["professor_approved"]:
        para.append(PENDING_BASIS)
    if a["professor_approved"] and a["approval_ids"]:
        para.append(
            f"The instructor has reviewed this case [{a['approval_ids'][-1]}]. "
            "Any gradebook update is handled separately by the course staff."
        )
    if any(b["code"] == "insufficient_evidence" for b in a["blockers"]) and not a["attempts"]:
        para.append(
            "To continue, please forward the original email with its sent time, or "
            "share a screenshot or link that shows when the file was sent. This does "
            "not mean the work is accepted or rejected."
        )
    if any(b["code"] == "policy_missing" for b in a["blockers"]):
        para.append("We are also confirming which course policy applies to this assignment.")
    if a["suggested_action"] == "approve" and a["deadline"] and not a["gates"]:
        if a["attempts"] and not any(x["late"] for x in a["attempts"]) and not s["differences"]:
            para.append("Our records show no late flag or late deduction for this assignment.")

    reply = "Hello,\n\nThank you for your message about " + case["assignment_name"] + ". "
    reply += "We checked the course records.\n\n" + "\n".join(para) + "\n\nTA team"
    return {
        "classification": case["issue"],
        "summary": f"{case['issue'].replace('_', ' ')} for {case['assignment']}; "
        f"rules suggest: {a['suggested_action']}.",
        "verified": verified,
        "unverified": unverified,
        "reply": reply,
        "rationale": " ".join(a["reasons"]),
        "uncertainty": " ".join(a["uncertainty"]) or "None identified by the rules.",
    }
