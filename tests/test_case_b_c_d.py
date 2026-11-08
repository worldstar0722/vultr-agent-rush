import re

from tests.conftest import decide, detail

COMMITMENT = re.compile(
    r"(will (be )?re-?grade|we will (change|adjust|waive|correct)|guarantee)", re.I
)


def test_case_b_gap_is_computed_exactly_with_evidence_rows(client):
    a = detail(client, "CASE-B")["analysis"]
    s = a["score_state"]
    assert (s["rubric_total"], s["entered"], s["posted"]) == (10, 8, 8)
    assert (s["late_deduction_applied"], s["expected_deduction"], s["expected_final"]) == (0, 0, 10)
    diff = s["differences"][0]
    assert diff["code"] == "entered_vs_expected" and diff["amount"] == -2
    assert diff["evidence_ids"] == [f"RUB-B-row{i}" for i in range(1, 6)] + ["SCORE-B"]
    assert a["score_change"] is None  # nothing suggested before a professor approves
    assert a["suggested_action"] == "escalate"


def test_case_b_ta_cannot_close_professor_can(client):
    client.post("/api/cases/CASE-B/draft")
    assert decide(client, "CASE-B", "ta", "approve").status_code == 403
    d = decide(client, "CASE-B", "professor", "approve", "Rubric is correct").json()
    assert d["analysis"]["score_change"]["to"] == 10  # still only a recommendation
    assert d["analysis"]["score_state"]["entered"] == 8


def test_case_c_insufficient_info_and_no_regrade_promise(client):
    d = client.post("/api/cases/CASE-C/draft").json()
    a = d["analysis"]
    assert a["submission_state"] == "not_submitted"
    assert any(w["text"].startswith("Insufficient evidence") for w in a["warnings"])
    assert a["suggested_action"] == "request_info" and a["route"] in ("student_info", "professor")
    assert d["draft"]["body_ai"] and not COMMITMENT.search(d["draft"]["body_ai"])
    assert "grade it" not in d["draft"]["body_ai"].lower()
    # approving is blocked for everyone
    assert decide(client, "CASE-C", "professor", "approve").status_code == 409
    r = decide(client, "CASE-C", "ta", "request_info", "Ask for the forwarded email")
    assert r.json()["case"]["status"] == "Awaiting student info"
    assert "Student to respond" in r.json()["case"]["waiting_reason"]


def test_missing_policy_means_hold_and_no_fake_citation(client):
    d = client.post("/api/cases/CASE-C/draft").json()
    assert d["analysis"]["policy"] == {
        "ref_id": None,
        "version": "POL-LATE-v2",
        "found": False,
        "params": None,
    }
    assert any(b["code"] == "policy_missing" for b in d["analysis"]["blockers"])
    assert "POL-LATE-v2" not in d["draft"]["body_ai"]
    for c in d["draft"]["verified"] + d["draft"]["unverified"]:
        assert "POL-LATE-v2" not in c["evidence_ids"]
    r = decide(client, "CASE-C", "ta", "hold", "Waiting for policy confirmation")
    assert r.json()["case"]["on_hold"] is True and r.json()["case"]["status"] == "TA review"


def test_case_d_clean_case_ta_can_close(client):
    d = client.post("/api/cases/CASE-D/draft").json()
    assert d["analysis"]["suggested_action"] == "approve"
    assert d["draft"]["flags"] == []
    r = decide(client, "CASE-D", "ta", "approve", "Records show on time")
    assert r.status_code == 200 and r.json()["case"]["status"] == "Closed"
    assert r.json()["draft"]["body_final"]  # approved text stored, still never sent
    assert decide(client, "CASE-D", "ta", "hold", "again").status_code == 409  # closed
