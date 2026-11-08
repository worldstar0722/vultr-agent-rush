"""Checks applied to AI output (and to the human-edited reply before approval).

1. Every claim must cite an existing evidence id; unknown ids are removed and flagged.
   Claims left with no valid citation are demoted to "unverified".
2. Numbers and times in AI text are compared with the rule engine. A conflict is flagged
   "Needs verification" and carries the code value so the UI can show it next to the text.
3. Commitment language (promising a regrade, a waiver, a grade change) is flagged.

Nothing here edits numbers: the AI text is kept as written and the code value is shown beside it.
"""

from __future__ import annotations

import re
from typing import Any

CITE_RE = re.compile(r"\b(?:POL|ATT|MSG|RUB|DL|SCORE|APR|SUB)-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")
BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
NUM = r"(-?\d+(?:\.\d+)?)"
ARITH_RE = re.compile(rf"{NUM}\s*([+\-−])\s*{NUM}\s*=\s*{NUM}")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s*([ap])\.?m\b\.?)?", re.I)
MINUTES_RE = re.compile(r"\b(\d+)\s*(?:minutes?|mins?)\b", re.I)

COMMITMENT_RES = [
    re.compile(
        r"\b(we|i)\s*(will|'ll)\s*(re-?grade|re-?mark|change|adjust|raise|correct|waive|"
        r"remove the (late )?(penalty|deduction)|fix)",
        re.I,
    ),
    re.compile(
        r"\byour (grade|score|mark)\s+(has been|will be|is going to be)\s+"
        r"(changed|updated|corrected|raised|adjusted|fixed)",
        re.I,
    ),
    re.compile(r"\b(will|shall) be (re-?graded|waived|removed|corrected)\b", re.I),
    re.compile(r"\bguarantee", re.I),
    re.compile(
        r"\b(the )?(late )?(penalty|deduction) (is|has been|will be) (removed|waived)", re.I
    ),
]


def _labeled(analysis: dict[str, Any]) -> list[tuple[str, re.Pattern[str], list[float]]]:
    s = analysis["score_state"]
    scenario_finals = [x["final"] for x in s["scenarios"]]
    scenario_deds = [x["deduction"] for x in s["scenarios"]]

    def vals(*items: Any) -> list[float]:
        return [v for v in items if v is not None]

    def pat(expr: str) -> re.Pattern[str]:
        return re.compile(expr + r"\s*" + NUM, re.I)

    return [
        (
            "rubric total",
            pat(r"\brubric (?:total|sum)(?: is| of| was| =|:)?"),
            vals(s["rubric_total"]),
        ),
        (
            "rubric total",
            pat(r"\brubric rows?[^.\d]{0,30}?(?:add up to|sum to|total(?:s)?(?: is)?)"),
            vals(s["rubric_total"]),
        ),
        (
            "entered score",
            pat(r"\bentered (?:score|grade)(?: is| of| was| =|:)?"),
            vals(s["entered"]),
        ),
        ("posted score", pat(r"\bposted (?:score|grade)(?: is| of| was| =|:)?"), vals(s["posted"])),
        (
            "final score",
            pat(r"\bfinal (?:score|grade)(?: is| of| was| =|:)?"),
            vals(s["expected_final"], s["entered"], *scenario_finals),
        ),
        (
            "late deduction",
            pat(r"\b(?:late )?(?:deduction|penalty)(?: is| of| was| =|:)?"),
            vals(s["expected_deduction"], s["late_deduction_applied"], *scenario_deds),
        ),
    ]


def _close(a: float, b: float) -> bool:
    return abs(a - b) < 0.005


def number_conflicts(text: str, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    def flag(ai_text: str, code_value: Any, label: str) -> None:
        flags.append(
            {
                "kind": "needs_verification",
                "ai_text": ai_text,
                "code_value": code_value,
                "label": label,
                "message": f"Needs verification: AI wrote '{ai_text}'; "
                f"code value ({label}) is {code_value}.",
            }
        )

    for m in ARITH_RE.finditer(text):
        a, op, b, claimed = float(m[1]), m[2], float(m[3]), float(m[4])
        real = a + b if op == "+" else a - b
        if not _close(real, claimed):
            flag(m[0], f"{real:g}", "arithmetic")

    for label, rx, allowed in _labeled(analysis):
        if not allowed:
            continue
        for m in rx.finditer(text):
            if not any(_close(float(m[1]), v) for v in allowed):
                flag(m[0].strip(), f"{allowed[0]:g}", label)

    if analysis["attempts"]:
        allowed_min = {
            abs(a["minutes_vs_deadline"])
            for a in analysis["attempts"]
            if a["minutes_vs_deadline"] is not None
        }
        for m in MINUTES_RE.finditer(text):
            if int(m[1]) not in allowed_min:
                shown = ", ".join(str(x) for x in sorted(allowed_min)) or "none"
                flag(m[0], shown, "minutes vs deadline")

    known = set(analysis["known_times"])
    for m in TIME_RE.finditer(text):
        hour, minute = int(m[1]), int(m[2])
        if m[3]:
            hour = hour % 12 + (12 if m[3].lower() == "p" else 0)
        if f"{hour:02d}:{minute:02d}" not in known:
            flag(m[0], ", ".join(sorted(known)) or "none", "recorded times")
    return flags


def commitment_flags(text: str) -> list[dict[str, Any]]:
    out = []
    for rx in COMMITMENT_RES:
        for m in rx.finditer(text):
            out.append(
                {
                    "kind": "commitment",
                    "ai_text": m[0],
                    "code_value": None,
                    "message": f"Commitment language ('{m[0]}'). A draft must not promise a "
                    "regrade, waiver or grade change.",
                }
            )
    return out


def strip_invalid_citations(text: str, valid: set[str]) -> tuple[str, list[dict[str, Any]]]:
    """Remove citations that are not real evidence ids. Policy ids get a specific message."""
    flags: list[dict[str, Any]] = []

    def record(token: str) -> None:
        what = "Policy" if token.startswith("POL-") else "Evidence id"
        flags.append(
            {
                "kind": "invalid_citation",
                "ai_text": token,
                "code_value": None,
                "message": f"{what} {token} does not exist in this case's records; citation removed.",
            }
        )

    def fix_bracket(m: re.Match[str]) -> str:
        parts = [p.strip() for p in m[1].split(",")]
        if not all(CITE_RE.fullmatch(p) for p in parts):
            return m[0]
        keep = [p for p in parts if p in valid]
        for p in parts:
            if p not in valid:
                record(p)
        return f"[{', '.join(keep)}]" if keep else ""

    text = BRACKET_RE.sub(fix_bracket, text)

    def fix_bare(m: re.Match[str]) -> str:
        if m[0] in valid:
            return m[0]
        record(m[0])
        return ""

    text = CITE_RE.sub(fix_bare, text)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\s+([.,;])", r"\1", text)).strip(), flags


def check_text(text: str, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Flags that must be resolved before a human can approve this reply text."""
    valid = set(analysis["ids"])
    _, bad_cites = strip_invalid_citations(text, valid)
    return bad_cites + number_conflicts(text, analysis) + commitment_flags(text)


def _claims(raw: Any) -> list[dict[str, Any]]:
    out = []
    for c in raw if isinstance(raw, list) else []:
        if isinstance(c, dict) and isinstance(c.get("text"), str) and c["text"].strip():
            ids = c.get("evidence_ids")
            out.append(
                {
                    "text": c["text"].strip(),
                    "evidence_ids": [i for i in ids if isinstance(i, str)]
                    if isinstance(ids, list)
                    else [],
                }
            )
    return out


def validate_draft(raw: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    valid = set(analysis["ids"])
    flags: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    def clean_claim(claim: dict[str, Any], where: str) -> dict[str, Any]:
        text, f1 = strip_invalid_citations(claim["text"], valid)
        ids = [i for i in claim["evidence_ids"] if i in valid]
        f2 = []
        for i in claim["evidence_ids"]:
            if i not in valid:
                f2.append(
                    {
                        "kind": "invalid_citation",
                        "ai_text": i,
                        "code_value": None,
                        "message": f"{'Policy' if i.startswith('POL-') else 'Evidence id'} {i} "
                        "does not exist in this case's records; citation removed.",
                    }
                )
        fl = [{**f, "where": where} for f in f1 + f2]
        return {"text": text, "evidence_ids": ids, "flags": fl}

    for n, claim in enumerate(_claims(raw.get("verified"))):
        c = clean_claim(claim, f"verified[{n}]")
        conflicts = number_conflicts(c["text"], analysis)
        if not c["evidence_ids"]:
            c["flags"].append(
                {
                    "kind": "no_citation",
                    "where": f"verified[{n}]",
                    "ai_text": "",
                    "code_value": None,
                    "message": "Claim has no valid evidence citation; moved to unverified.",
                }
            )
            unverified.append(c)
        elif conflicts:
            c["flags"] += [{**f, "where": f"verified[{n}]"} for f in conflicts]
            unverified.append(c)
        else:
            verified.append(c)
        flags += c["flags"]
    for n, claim in enumerate(_claims(raw.get("unverified"))):
        c = clean_claim(claim, f"unverified[{n}]")
        c["flags"] += [
            {**f, "where": f"unverified[{n}]"} for f in number_conflicts(c["text"], analysis)
        ]
        unverified.append(c)
        flags += c["flags"]

    reply, f_reply = strip_invalid_citations(str(raw.get("reply", "")), valid)
    reply_flags = [
        {**f, "where": "reply"}
        for f in f_reply + number_conflicts(reply, analysis) + commitment_flags(reply)
    ]
    flags += reply_flags
    return {
        "classification": str(raw.get("classification", "")),
        "summary": str(raw.get("summary", "")),
        "verified": verified,
        "unverified": unverified,
        "reply": reply,
        "rationale": str(raw.get("rationale", "")),
        "uncertainty": str(raw.get("uncertainty", "")),
        "flags": flags,
    }
