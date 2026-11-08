from app.llm import MockLLM
from tests.conftest import decide, detail, make_client


class BadMath(MockLLM):
    """Pretends to be a model that gets arithmetic and citations wrong."""

    def draft(self, bundle):
        return {
            "classification": "score_gap",
            "summary": "s",
            "verified": [
                {"text": "The rubric rows add up: 9+1=11.", "evidence_ids": ["RUB-B-row1"]},
                {"text": "Entered score is 8.", "evidence_ids": ["SCORE-B"]},
                {"text": "Policy says rows are capped.", "evidence_ids": ["POL-NOPE"]},
            ],
            "unverified": [],
            "reply": "Your rubric total is 11 [RUB-B-row1] and the cap is in [POL-NOPE]. "
            "Submitted at 09:15 [ATT-B1]. We will regrade it.",
            "rationale": "r",
            "uncertainty": "u",
        }


class Boom(MockLLM):
    def draft(self, bundle):
        raise TimeoutError("model timed out")


def test_arithmetic_conflict_is_flagged_with_code_value(settings):
    client = make_client(settings, BadMath())
    d = client.post("/api/cases/CASE-B/draft").json()["draft"]
    kinds = [(f["kind"], f.get("label")) for f in d["flags"]]
    arith = next(f for f in d["flags"] if f.get("label") == "arithmetic")
    assert arith["ai_text"] == "9+1=11" and arith["code_value"] == "10"
    assert ("needs_verification", "rubric total") in kinds  # "rubric total is 11" vs 10
    # the conflicting claim is not shown as verified
    assert all("9+1=11" not in c["text"] for c in d["verified"])
    bad = next(c for c in d["unverified"] if "9+1=11" in c["text"])
    assert any(f["kind"] == "needs_verification" for f in bad["flags"])
    assert any(
        f["label"] == "recorded times" and f["ai_text"] == "09:15"
        for f in d["flags"]
        if f.get("label")
    )


def test_nonexistent_policy_citation_removed_and_flagged(settings):
    client = make_client(settings, BadMath())
    d = client.post("/api/cases/CASE-B/draft").json()["draft"]
    assert "POL-NOPE" not in d["body_ai"]
    assert any(f["kind"] == "invalid_citation" and f["ai_text"] == "POL-NOPE" for f in d["flags"])
    # a claim whose only citation was fake falls back to unverified
    assert any("capped" in c["text"] for c in d["unverified"])
    assert all("POL-NOPE" not in c["evidence_ids"] for c in d["verified"] + d["unverified"])


def test_commitment_language_flagged_and_blocks_approval(settings):
    client = make_client(settings, BadMath())
    d = client.post("/api/cases/CASE-B/draft").json()["draft"]
    assert any(f["kind"] == "commitment" for f in d["flags"])
    r = decide(client, "CASE-B", "professor", "approve", "x")
    assert r.status_code == 409 and "needs verification" in r.json()["detail"].lower()


def test_human_edit_with_conflict_cannot_be_approved(client):
    client.post("/api/cases/CASE-D/draft")
    r = decide(client, "CASE-D", "ta", "approve", body="Your late deduction of 5 applies [ATT-D1].")
    assert r.status_code == 409
    flags = client.post(
        "/api/cases/CASE-D/draft/check", json={"body": "Final score 3 [SCORE-D]"}
    ).json()["flags"]
    assert flags and flags[0]["code_value"] == "9"


def test_llm_failure_degrades_to_rules_only(settings):
    client = make_client(settings, Boom())
    r = client.post("/api/cases/CASE-A/draft")
    assert r.status_code == 200
    body = r.json()
    assert body["ai"]["status"] == "unavailable" and "timed out" in body["ai"]["error"]
    assert body["draft"]["source"] == "rules-only" and body["draft"]["body_ai"]
    # everything else keeps working
    assert client.get("/api/cases").status_code == 200
    assert detail(client, "CASE-A")["analysis"]["suggested_action"] == "escalate"
    assert client.get("/").status_code == 200
