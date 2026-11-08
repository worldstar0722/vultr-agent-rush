"""Rule engine. ALL times, lateness and scores are computed here, in code.

The LLM never produces these numbers; it only receives them. `analyze()` is a pure
function of a case's evidence rows, so it is easy to test.

Evidence row shape (dict): ref_id, source_type, ts (ISO 8601 with offset), summary,
source_text, payload (dict).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

Row = dict[str, Any]


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _g(v: float | Decimal | None) -> str:
    """Format a number for human text: 8.0 -> '8', 2.5 -> '2.5'."""
    return "n/a" if v is None else f"{float(v):g}"


def _f(d: Decimal | None) -> float | None:
    return None if d is None else float(d.quantize(Decimal("0.01")))


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# ----------------------------------------------------------------- text classification


def classify_issue(text: str) -> str:
    """Cheap keyword classifier used for duplicate detection (the AI may add its own)."""
    t = text.lower()
    if re.search(r"\b(e-?mailed|sent (it|my file|the file))\b", t):
        return "missing_submission"
    if re.search(r"\blate\b", t):
        return "late_flag"
    if re.search(r"\b(score|grade|points|rubric|marks?)\b", t):
        return "score_gap"
    return "other"


def detect_claims(text: str) -> list[str]:
    claims = []
    if re.search(r"\be-?mailed\b.*\b(ta|instructor|professor)\b", text, re.I):
        claims.append("emailed_file_to_ta")
    return claims


# ------------------------------------------------------------------------ main analysis


def _deduction(minutes: int, params: dict[str, Any], max_points: Decimal) -> tuple[Decimal, str]:
    if minutes <= 0:
        return Decimal(0), "on_time"
    if minutes > int(params["max_late_hours"]) * 60:
        return max_points, "beyond_window"
    return max_points * _d(params["late_percent"]) / 100, "late"


def analyze(evidence: list[Row]) -> dict[str, Any]:
    ev = sorted(evidence, key=lambda e: (parse_ts(e["ts"]), e["ref_id"]))
    ids = {e["ref_id"] for e in ev}

    def of(kind: str) -> list[Row]:
        return [e for e in ev if e["source_type"] == kind]

    warnings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    # ---- deadline + policy
    dl = next(iter(of("deadline")), None)
    deadline_dt = parse_ts(dl["payload"]["deadline"]) if dl else None
    max_points = _d(dl["payload"]["max_points"]) if dl else None
    policy_ref = dl["payload"].get("policy_ref") if dl else None
    policy = next((e for e in of("policy") if e["payload"].get("version") == policy_ref), None)
    params = policy["payload"]["params"] if policy else None

    if dl is None:
        blockers.append(
            {
                "code": "insufficient_evidence",
                "text": "No deadline record for this assignment.",
                "evidence_ids": [],
            }
        )
    if dl is not None and policy is None:
        text = f"Policy {policy_ref} is referenced by {dl['ref_id']} but not found in the records."
        blockers.append({"code": "policy_missing", "text": text, "evidence_ids": [dl["ref_id"]]})
        review.append(
            {
                "kind": "policy_missing",
                "route_to": "professor",
                "title": f"Confirm which late policy applies ({policy_ref} not found)",
                "evidence_ids": [dl["ref_id"]],
            }
        )

    # ---- attempts
    attempts: list[dict[str, Any]] = []
    for e in of("attempt"):
        minutes = None
        if deadline_dt is not None:
            minutes = round((parse_ts(e["ts"]) - deadline_dt).total_seconds() / 60)
        state = e["payload"].get("state", "submitted")
        attempts.append(
            {
                "ref_id": e["ref_id"],
                "ts": e["ts"],
                "state": state,
                "minutes_vs_deadline": minutes,
                "late": bool(minutes is not None and minutes > 0 and state == "submitted"),
                "file": e["payload"].get("file"),
            }
        )
    gradeable = [a for a in attempts if a["state"] == "submitted"]
    counted_default = gradeable[-1] if gradeable else None

    if attempts:
        present = {a["state"] for a in attempts}
        submission_state = (
            "submitted"
            if "submitted" in present
            else next(s for s in ("unreadable", "empty_file", "alternate_evidence") if s in present)
        )
    else:
        status_row = next(iter(of("submission_status")), None)
        submission_state = status_row["payload"]["state"] if status_row else "not_submitted"

    for a in attempts:
        if a["state"] == "unreadable":
            blockers.append(
                {
                    "code": "insufficient_evidence",
                    "evidence_ids": [a["ref_id"]],
                    "text": f"Insufficient evidence: file for {a['ref_id']} is unreadable.",
                }
            )
            review.append(
                {
                    "kind": f"unreadable_{a['ref_id']}",
                    "route_to": "student",
                    "title": f"Ask the student to re-upload the file for {a['ref_id']}",
                    "evidence_ids": [a["ref_id"]],
                }
            )
        elif a["state"] == "empty_file":
            blockers.append(
                {
                    "code": "insufficient_evidence",
                    "evidence_ids": [a["ref_id"]],
                    "text": f"Insufficient evidence: {a['ref_id']} is an empty file.",
                }
            )
        elif a["state"] == "alternate_evidence":
            gates.append(
                {
                    "code": "alternate_evidence",
                    "evidence_ids": [a["ref_id"]],
                    "text": f"{a['ref_id']} is alternate evidence (screenshot/link/comment), not a "
                    "Canvas submission. Only the professor can decide whether it counts.",
                }
            )
            review.append(
                {
                    "kind": f"alternate_{a['ref_id']}",
                    "route_to": "professor",
                    "title": f"Decide whether alternate evidence {a['ref_id']} counts",
                    "evidence_ids": [a["ref_id"]],
                }
            )

    # ---- claims made by the student that records must back up
    for m in of("message"):
        if m["payload"].get("direction") != "inbound":
            continue
        for claim in detect_claims(m["source_text"]):
            backed = any(e["payload"].get("backs") == claim for e in ev)
            if claim == "emailed_file_to_ta" and not backed:
                blockers.append(
                    {
                        "code": "insufficient_evidence",
                        "evidence_ids": [m["ref_id"]],
                        "text": "Insufficient evidence: the student says they emailed a file to the "
                        "TA, but there is no attempt and no email record to confirm it.",
                    }
                )
                review.append(
                    {
                        "kind": "info_needed",
                        "route_to": "student",
                        "title": "Ask the student for proof of the emailed file",
                        "evidence_ids": [m["ref_id"]],
                    }
                )

    # ---- approvals
    approvals = [
        e
        for e in of("approval")
        if e["payload"].get("role") == "professor" and e["payload"].get("action") == "approve"
    ]
    professor_approved = bool(approvals)
    override_ref = next(
        (
            a["payload"].get("counted_attempt")
            for a in reversed(approvals)
            if a["payload"].get("counted_attempt") in {x["ref_id"] for x in gradeable}
        ),
        None,
    )
    counted_override = next((a for a in gradeable if a["ref_id"] == override_ref), None)

    # ---- attempt-basis ambiguity (Case A): an on-time attempt exists but a later, late one is graded
    if (
        counted_default
        and counted_default["late"]
        and params
        and params.get("grade_basis") == "latest_attempt"
        and any(
            a["minutes_vs_deadline"] is not None and a["minutes_vs_deadline"] <= 0
            for a in gradeable
        )
    ):
        first_on_time = next(a for a in gradeable if a["minutes_vs_deadline"] <= 0)
        gates.append(
            {
                "code": "attempt_basis",
                "evidence_ids": [first_on_time["ref_id"], counted_default["ref_id"], policy_ref],
                "text": f"{first_on_time['ref_id']} was on time but {counted_default['ref_id']} (the "
                "newest attempt) was late. The policy grades the newest attempt unless the "
                "professor approves otherwise.",
            }
        )
        review.append(
            {
                "kind": "attempt_basis",
                "route_to": "professor",
                "title": f"Confirm whether {first_on_time['ref_id']} counts",
                "evidence_ids": [first_on_time["ref_id"], counted_default["ref_id"], policy_ref],
            }
        )

    # ---- score state
    rubric_rows = [
        {
            "ref_id": e["ref_id"],
            "label": e["payload"]["label"],
            "max": e["payload"]["max"],
            "awarded": e["payload"]["awarded"],
        }
        for e in of("rubric")
    ]
    score_ev = next(iter(of("score")), None)
    sp = score_ev["payload"] if score_ev else {}
    rubric_total = sum((_d(r["awarded"]) for r in rubric_rows), Decimal(0)) if rubric_rows else None
    rubric_max = sum((_d(r["max"]) for r in rubric_rows), Decimal(0)) if rubric_rows else None
    entered = _d(sp["entered"]) if sp.get("entered") is not None else None
    posted = _d(sp["posted"]) if sp.get("posted") is not None else None
    applied = _d(sp.get("late_deduction_applied", 0))

    def basis(att: dict[str, Any] | None) -> dict[str, Any] | None:
        if att is None or params is None or max_points is None or rubric_total is None:
            return None
        ded, kind = _deduction(att["minutes_vs_deadline"], params, max_points)
        return {
            "attempt": att["ref_id"],
            "lateness": kind,
            "deduction": _f(ded),
            "final": _f(rubric_total - ded),
            "_ded": ded,
        }

    default_basis = basis(counted_default)
    override_basis = basis(counted_override)
    scenarios = [b for b in (basis(a) for a in gradeable) if b]

    score_ev_ids = [score_ev["ref_id"]] if score_ev else []
    rubric_ids = [r["ref_id"] for r in rubric_rows]
    differences: list[dict[str, Any]] = []
    if default_basis and entered is not None:
        exp_final = rubric_total - default_basis["_ded"]
        if applied != default_basis["_ded"]:
            text = (
                f"Late deduction recorded as {_g(applied)} but the policy gives "
                f"{_g(default_basis['deduction'])} for {default_basis['attempt']}."
            )
            blockers.append(
                {
                    "code": "records_conflict",
                    "text": "Records conflict: " + text,
                    "evidence_ids": score_ev_ids + [default_basis["attempt"]],
                }
            )
            review.append(
                {
                    "kind": "records_conflict",
                    "route_to": "professor",
                    "title": "Resolve conflict between recorded deduction and attempt times",
                    "evidence_ids": score_ev_ids + [default_basis["attempt"]],
                }
            )
            differences.append(
                {
                    "code": "deduction_mismatch",
                    "amount": _f(applied - default_basis["_ded"]),
                    "text": text,
                    "evidence_ids": score_ev_ids + [default_basis["attempt"]],
                }
            )
        if entered != exp_final:
            amount = entered - exp_final
            text = (
                f"Entered score {_g(entered)} differs from rubric total {_g(rubric_total)} minus "
                f"expected deduction {_g(default_basis['deduction'])} (= {_g(exp_final)}) by "
                f"{_g(amount)}."
            )
            differences.append(
                {
                    "code": "entered_vs_expected",
                    "amount": _f(amount),
                    "text": text,
                    "evidence_ids": rubric_ids + score_ev_ids,
                }
            )
            gates.append(
                {
                    "code": "score_gap",
                    "evidence_ids": rubric_ids + score_ev_ids,
                    "text": "A score difference with no recorded reason affects the grade; the "
                    "professor must decide.",
                }
            )
            review.append(
                {
                    "kind": "score_gap",
                    "route_to": "professor",
                    "title": f"Confirm the cause of the {abs(_f(amount)):g}-point score difference",
                    "evidence_ids": rubric_ids + score_ev_ids,
                }
            )
    if sp.get("graded") and entered is not None and posted is None:
        differences.append(
            {
                "code": "graded_not_posted",
                "amount": None,
                "evidence_ids": score_ev_ids,
                "text": "Graded but not posted: the student cannot see the entered score yet.",
            }
        )
    elif entered is not None and posted is not None and entered != posted:
        differences.append(
            {
                "code": "posted_differs",
                "amount": _f(posted - entered),
                "evidence_ids": score_ev_ids,
                "text": f"Posted score {_g(posted)} differs from entered score {_g(entered)}.",
            }
        )

    # score change recommendation exists ONLY after a professor approval; it is never applied
    score_change = None
    chosen = override_basis or default_basis
    if professor_approved and chosen and entered is not None and chosen["final"] != _f(entered):
        score_change = {
            "from": _f(entered),
            "to": chosen["final"],
            "delta": _f(_d(chosen["final"]) - entered),
            "basis_attempt": chosen["attempt"],
            "applied": False,
            "approval_ids": [a["ref_id"] for a in approvals],
        }

    # ---- warnings shown in the evidence view
    if gates and not professor_approved:
        titles = "; ".join(r["title"] for r in review if r["route_to"] == "professor")
        warnings.append(
            {
                "code": "approval_missing",
                "evidence_ids": [],
                "text": "Insufficient evidence: no professor approval on file"
                + (f" for: {titles}." if titles else "."),
            }
        )
    for b in blockers:
        warnings.append({"code": b["code"], "text": b["text"], "evidence_ids": b["evidence_ids"]})
    for g in gates:
        warnings.append({"code": g["code"], "text": g["text"], "evidence_ids": g["evidence_ids"]})
    for d in differences:
        warnings.append({"code": d["code"], "text": d["text"], "evidence_ids": d["evidence_ids"]})
    if submission_state == "not_submitted" and not any(
        w["code"] == "insufficient_evidence" for w in warnings
    ):
        warnings.append(
            {
                "code": "not_submitted",
                "evidence_ids": [],
                "text": "No submission is recorded for this assignment.",
            }
        )

    # ---- suggested action (a suggestion for the human, never executed)
    if any(b["code"] == "insufficient_evidence" for b in blockers):
        suggested, route = "request_info", "student_info"
        reasons = [b["text"] for b in blockers]
    elif blockers:
        suggested, route = "hold", "professor"
        reasons = [b["text"] for b in blockers]
    elif gates and not professor_approved:
        suggested, route = "escalate", "professor"
        reasons = [g["text"] for g in gates]
    else:
        suggested, route = "approve", "ta"
        reasons = ["Records are consistent; no professor decision is required."]
    if any(b["code"] == "policy_missing" for b in blockers) and suggested == "request_info":
        reasons.append("The professor must also confirm which policy applies.")
    uncertainty = []
    if gates and not professor_approved:
        uncertainty.append("Outcome depends on a professor decision that has not been made.")
    if any(b["code"] == "policy_missing" for b in blockers):
        uncertainty.append("The applicable policy text is not available.")
    if any(b["code"] == "insufficient_evidence" for b in blockers):
        uncertainty.append("A student statement could not be confirmed from the records.")

    times = {parse_ts(e["ts"]).strftime("%H:%M") for e in ev}
    if deadline_dt:
        times.add(deadline_dt.strftime("%H:%M"))

    def clean(b: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if b is None else {k: v for k, v in b.items() if not k.startswith("_")}

    return {
        "ids": sorted(ids),
        "deadline": (
            {
                "ref_id": dl["ref_id"],
                "ts": dl["payload"]["deadline"],
                "max_points": _f(max_points),
                "policy_ref": policy_ref,
            }
            if dl
            else None
        ),
        "policy": (
            {"ref_id": policy["ref_id"], "version": policy_ref, "found": True, "params": params}
            if policy
            else {"ref_id": None, "version": policy_ref, "found": False, "params": None}
        ),
        "submission_state": submission_state,
        "attempts": [
            {**a, "counted": bool(counted_default and a["ref_id"] == counted_default["ref_id"])}
            for a in attempts
        ],
        "score_state": {
            "rubric_rows": rubric_rows,
            "rubric_total": _f(rubric_total),
            "rubric_max": _f(rubric_max),
            "late_deduction_applied": _f(applied) if score_ev else None,
            "expected_deduction": default_basis["deduction"] if default_basis else None,
            "expected_final": default_basis["final"] if default_basis else None,
            "entered": _f(entered),
            "posted": _f(posted),
            "graded": bool(sp.get("graded")),
            "basis": clean(default_basis),
            "scenarios": [clean(s) for s in scenarios],
            "approved_basis": clean(override_basis),
            "differences": differences,
            "evidence_ids": rubric_ids + score_ev_ids,
        },
        "score_change": score_change,
        "professor_approved": professor_approved,
        "approval_ids": [a["ref_id"] for a in approvals],
        "warnings": warnings,
        "blockers": blockers,
        "gates": gates,
        "requires_professor": bool(gates),
        "review_items": review,
        "suggested_action": suggested,
        "route": route,
        "reasons": reasons,
        "uncertainty": uncertainty,
        "known_times": sorted(times),
    }
