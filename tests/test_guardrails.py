"""Guardrail unit tests on real engine output (Case B: rubric 10, entered 8, deadline 23:59)."""

import pytest

from app import guardrails
from app.engine import analyze
from tests.conftest import decide, detail


@pytest.fixture
def analysis_b(client):
    return analyze(detail(client, "CASE-B")["evidence"])


def draft(**over):
    d = {
        "classification": "score_gap",
        "summary": "The entered score is below the rubric total [SCORE-B].",
        "verified": [{"text": "Entered score is 8.", "evidence_ids": ["SCORE-B"]}],
        "unverified": [],
        "unresolved": [],
        "reply": "We compared the records [SCORE-B].",
        "rationale": "r",
        "uncertainty": "u",
    }
    d.update(over)
    return d


def kinds(result):
    return {(f["kind"], f.get("label")) for f in result["flags"]}


def test_clean_draft_has_no_blocking_flags(analysis_b):
    out = guardrails.validate_draft(draft(), analysis_b)
    assert guardrails.blocking_flags(out["flags"]) == []


def test_arithmetic_conflict_is_flagged_with_the_code_value(analysis_b):
    out = guardrails.validate_draft(
        draft(verified=[{"text": "The rows add up: 9+1=11.", "evidence_ids": ["RUB-B-row1"]}]),
        analysis_b,
    )
    arith = next(f for f in out["flags"] if f.get("label") == "arithmetic")
    assert arith["ai_text"] == "9+1=11" and arith["code_value"] == "10"
    assert out["verified"] == []  # the conflicting claim is not shown as verified
    assert any("9+1=11" in c["text"] for c in out["unverified"])


def test_labelled_values_and_times_are_checked_in_every_text_field(analysis_b):
    out = guardrails.validate_draft(
        draft(
            summary="Rubric total is 11.",
            rationale="Submitted at 03:33.",
            uncertainty="Entered score 9.",
        ),
        analysis_b,
    )
    wheres = {f["where"] for f in guardrails.blocking_flags(out["flags"])}
    assert {"summary", "rationale", "uncertainty"} <= wheres


def test_unknown_policy_citation_is_removed_and_flagged(analysis_b):
    out = guardrails.validate_draft(
        draft(reply="Per [POL-NOPE] and [SCORE-B, POL-ALSO-FAKE]."), analysis_b
    )
    assert "POL-NOPE" not in out["reply"] and "POL-ALSO-FAKE" not in out["reply"]
    assert "[SCORE-B]" in out["reply"]
    assert {f["ai_text"] for f in out["flags"] if f["kind"] == "invalid_citation"} == {
        "POL-NOPE",
        "POL-ALSO-FAKE",
    }


def test_commitment_language_is_flagged(analysis_b):
    for text in [
        "We will regrade your work.",
        "Your grade will be changed.",
        "We guarantee a fix.",
    ]:
        out = guardrails.validate_draft(draft(reply=text), analysis_b)
        assert any(f["kind"] == "commitment" for f in out["flags"]), text


def test_unresolved_items_are_checked_too(analysis_b):
    out = guardrails.validate_draft(draft(unresolved=["Confirm with [POL-FAKE-v9]"]), analysis_b)
    assert any(f["where"] == "unresolved[0]" for f in out["flags"])


def test_human_edit_with_conflict_cannot_be_approved(client):
    client.post("/api/cases/CASE-D/analysis", json={})
    r = decide(client, "CASE-D", "ta", "approve", body="Your late deduction of 5 applies [ATT-D1].")
    assert r.status_code == 409
    flags = client.post(
        "/api/cases/CASE-D/draft/check", json={"body": "Final score 3 [SCORE-D]"}
    ).json()["flags"]
    assert flags and flags[0]["code_value"] == "9"
