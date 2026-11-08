"""Case A: on-time first attempt, late second attempt, late penalty on newest attempt."""

from tests.conftest import decide, detail


def test_attempts_deduction_and_approval_are_shown_separately(client):
    a = detail(client, "CASE-A")["analysis"]
    att = {x["ref_id"]: x for x in a["attempts"]}
    assert att["ATT-A1"]["minutes_vs_deadline"] == -79 and not att["ATT-A1"]["late"]
    assert att["ATT-A2"]["minutes_vs_deadline"] == 11 and att["ATT-A2"]["late"]
    s = a["score_state"]
    assert (s["rubric_total"], s["late_deduction_applied"], s["expected_deduction"]) == (9, 2, 2)
    assert (s["entered"], s["posted"], s["expected_final"]) == (7, 7, 7)
    assert s["differences"] == []
    assert a["professor_approved"] is False
    assert any(
        w["text"].startswith("Insufficient evidence: no professor approval") for w in a["warnings"]
    )


def test_review_item_routes_to_professor_and_no_score_change_suggested(client):
    d = detail(client, "CASE-A")
    item = next(r for r in d["review_items"] if r["kind"] == "attempt_basis")
    assert item["title"] == "Confirm whether ATT-A1 counts"
    assert item["route_to"] == "professor"
    assert d["analysis"]["suggested_action"] == "escalate"
    assert d["analysis"]["score_change"] is None
    assert d["score_control"]["enabled"] is False


def test_draft_does_not_assert_policy_outcome(client):
    d = client.post("/api/cases/CASE-A/draft").json()
    reply = d["draft"]["body_ai"]
    assert "decision for the instructor" in reply
    assert "cannot say yet" in reply
    assert "[ATT-A1]" in reply and "[ATT-A2]" in reply
    assert d["draft"]["flags"] == []
    assert d["analysis"]["score_change"] is None


def test_ta_cannot_approve_but_can_escalate(client):
    client.post("/api/cases/CASE-A/draft")
    r = decide(client, "CASE-A", "ta", "approve")
    assert r.status_code == 403 and "Professor-only" in r.json()["detail"]
    r = decide(client, "CASE-A", "ta", "escalate", "Needs professor ruling on attempt 1")
    assert r.status_code == 200 and r.json()["case"]["status"] == "Awaiting professor"


def test_professor_approval_then_recommendation_only(client):
    client.post("/api/cases/CASE-A/draft")
    r = decide(client, "CASE-A", "professor", "approve", "Attempt 1 counts")
    assert r.status_code == 400  # must pick the counted attempt
    r = decide(
        client, "CASE-A", "professor", "approve", "Attempt 1 counts", counted_attempt="ATT-A1"
    )
    assert r.status_code == 200
    d = r.json()
    assert d["case"]["status"] == "Closed"
    assert d["analysis"]["professor_approved"] is True
    assert any(e["ref_id"] == "APR-A-1" for e in d["evidence"])
    assert d["analysis"]["score_change"]["to"] == 9 and d["analysis"]["score_change"]["from"] == 7
    assert d["score_control"]["enabled"] is True

    d = client.post("/api/cases/CASE-A/score-recommendation", json={"role": "professor"}).json()
    assert d["score_control"]["recorded"]["payload"]["applied"] is False
    assert "not applied" in d["score_control"]["recorded"]["rationale"]
    # the gradebook evidence is untouched: no Canvas write, no auto-correction
    assert d["analysis"]["score_state"]["entered"] == 7
    assert (
        client.post(
            "/api/cases/CASE-A/score-recommendation", json={"role": "professor"}
        ).status_code
        == 409
    )


def test_score_control_blocked_without_approval(client):
    r = client.post("/api/cases/CASE-A/score-recommendation", json={"role": "professor"})
    assert r.status_code == 409
