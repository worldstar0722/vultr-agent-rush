import copy

import pytest

from app.config import Settings
from app.intake import EXAMPLES
from tests.conftest import detail, make_client

ex = {e["title"].split(":")[0]: e["request"] for e in EXAMPLES}


def post(client, payload):
    return client.post("/api/intake", json=payload)


def example(name="Late flag"):
    return copy.deepcopy(ex[name])


def test_new_case_gets_real_structured_evidence_and_rule_results(client):
    r = post(client, example())
    assert r.status_code == 201
    cid = r.json()["case_id"]
    assert cid == "CASE-101"
    d = detail(client, cid)
    refs = {e["ref_id"] for e in d["evidence"]}
    assert {
        "MSG-101-1",
        "DL-101",
        "ATT-101-1",
        "ATT-101-2",
        "RUB-101-row1",
        "SCORE-101",
        "POL-LATE-v1",
    } <= refs
    a = d["analysis"]
    att = {x["ref_id"]: x for x in a["attempts"]}
    assert (
        att["ATT-101-1"]["minutes_vs_deadline"] == -39
        and att["ATT-101-2"]["minutes_vs_deadline"] == 6
    )
    s = a["score_state"]
    assert (
        s["rubric_total"],
        s["expected_deduction"],
        s["late_deduction_applied"],
        s["entered"],
    ) == (9, 2, 2, 7)
    assert a["suggested_action"] == "escalate" and a["requires_professor"]
    assert d["case"]["issue"] == "late_flag" and d["case"]["status"] == "New"
    assert d["case"]["student_id"] == "S-4B21" and d["case"]["owner"] is None


def test_every_shipped_example_is_valid_and_exercises_its_path(client):
    ids = [post(client, copy.deepcopy(e["request"])).json()["case_id"] for e in EXAMPLES]
    assert ids == ["CASE-101", "CASE-102", "CASE-103"]
    gap = detail(client, ids[1])["analysis"]["score_state"]["differences"][0]
    assert gap["code"] == "entered_vs_expected" and gap["amount"] == -4
    hold = detail(client, ids[2])["analysis"]
    assert (
        any(b["code"] == "policy_missing" for b in hold["blockers"])
        and hold["suggested_action"] == "hold"
    )


def test_examples_endpoint_serves_the_same_payloads(client):
    got = client.get("/api/intake/examples").json()
    assert [g["title"] for g in got] == [e["title"] for e in EXAMPLES]


def test_nothing_is_borrowed_from_fixtures_when_context_is_omitted(client):
    p = example()
    p["student"], p["assignment"] = "S-7F3A", "HW3"  # same pair as the Case A fixture
    del p["context"]
    cid = post(client, p).json()["case_id"]
    a = detail(client, cid)["analysis"]
    assert a["deadline"] is None and a["attempts"] == []  # no invented context
    assert any(b["text"].startswith("No deadline record") for b in a["blockers"])
    assert a["suggested_action"] == "request_info"


def test_message_can_be_added_to_an_existing_case_without_context(client):
    r = post(client, {
        "synthetic_ack": True, "student": "S-7F3A", "assignment": "HW3", "case_id": "CASE-A",
        "message": {"channel": "email", "ts": "2026-11-08T09:00:00-07:00", "text": "Following up."},
    })  # fmt: skip
    assert r.status_code == 201 and r.json()["message_id"] == "MSG-A-3"
    refs = [e["ref_id"] for e in detail(client, "CASE-A")["evidence"]]
    assert "MSG-A-3" in refs and refs.count("ATT-A1") == 1


def test_staff_reply_can_be_logged_on_an_existing_case(client):
    r = post(client, {
        "synthetic_ack": True, "student": "S-2C91", "assignment": "HW4", "case_id": "CASE-B",
        "message": {"channel": "canvas_inbox", "direction": "outbound", "author": "TA Chen",
                    "ts": "2026-11-08T09:00:00-07:00", "text": "We are looking into it."},
    })  # fmt: skip
    assert r.status_code == 201
    assert detail(client, "CASE-B")["case"]["last_reply"]["by"] == "TA Chen"


def test_a_second_report_of_the_same_issue_becomes_a_duplicate_proposal(client):
    a = post(client, example()).json()["case_id"]
    p = example()
    p["message"]["channel"] = "email"
    del p["context"]  # a duplicate report usually arrives without records
    b = post(client, p).json()["case_id"]
    pairs = [
        d for c in client.get("/api/cases").json() if c["id"] in (a, b) for d in c["duplicates"]
    ]
    assert {d["other"] for d in pairs} == {a, b}
    assert all(
        c["merged_into"] is None for c in client.get("/api/cases").json()
    )  # never auto-merged


def test_new_cases_persist_across_a_restart(settings):
    cid = post(make_client(settings), example()).json()["case_id"]
    assert detail(make_client(settings), cid)["case"]["student_id"] == "S-4B21"


def test_case_limit_protects_the_demo(tmp_path):
    client = make_client(Settings(db_path=str(tmp_path / "g.db"), max_cases=5))  # 5 fixtures
    r = post(client, example())
    assert r.status_code == 409 and r.json()["code"] == "case_limit"


def test_cannot_add_to_a_merged_case_or_the_wrong_student(client):
    dup = client.get("/api/cases").json()[0]["duplicates"][0]["id"]
    client.post(f"/api/duplicates/{dup}/confirm", json={"role": "ta"})
    msg = {"channel": "email", "ts": "2026-11-08T09:00:00-07:00", "text": "hi"}
    base = {"synthetic_ack": True, "student": "S-7F3A", "assignment": "HW3", "message": msg}
    assert post(client, {**base, "case_id": "CASE-A2"}).status_code == 409
    assert post(client, {**base, "student": "S-2C91", "case_id": "CASE-A"}).status_code == 409
    assert post(client, {**base, "case_id": "CASE-ZZZ"}).status_code == 404


def bad(mutate):
    p = example()
    mutate(p)
    return p


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda p: p.pop("synthetic_ack"), "synthetic_ack"),
        (lambda p: p.update(synthetic_ack=False), "synthetic_ack"),
        (lambda p: p.update(student="Jane Smith"), "student"),
        (lambda p: p.update(assignment="not a valid id!"), "assignment"),
        (lambda p: p["message"].update(text="Reach me at jane.smith@example.edu"), "message.text"),
        (lambda p: p["message"].update(text="Call 801-555-0199 please"), "message.text"),
        (lambda p: p["message"].update(text="My id is 12345678"), "message.text"),
        (lambda p: p["message"].update(text="See https://example.com"), "message.text"),
        (lambda p: p["message"].update(text=""), "message.text"),
        (lambda p: p["message"].update(text="x" * 2001), "message.text"),
        (lambda p: p["message"].update(ts="2026-11-09T08:15:00"), "message.ts"),
        (lambda p: p["message"].update(ts="yesterday"), "message.ts"),
        (lambda p: p["message"].update(channel="slack"), "message.channel"),
        (lambda p: p["context"].update(deadline="next Friday"), "context.deadline"),
        (lambda p: p["context"].update(policy_ref="policy 1"), "context.policy_ref"),
        (lambda p: p["context"].update(max_points=0), "context.max_points"),
        (lambda p: p["context"]["rubric"][0].update(awarded=99), "context.rubric.0"),
        (lambda p: p["context"].update(attempts=p["context"]["attempts"] * 4), "context.attempts"),
        (lambda p: p["context"]["attempts"][0].update(state="lost"), "context.attempts.0.state"),
        (
            lambda p: p["context"]["attempts"][0].update(file="../../etc/passwd"),
            "context.attempts.0.file",
        ),
        (lambda p: p["context"].update(surprise=1), "context.surprise"),
        (lambda p: p.update(owner="Real Person"), "owner"),
        (lambda p: p.update(case_id="CASE-A"), ""),  # context + case_id together
        (
            lambda p: p["message"].update(direction="outbound", author="TA Chen"),
            "",
        ),  # reply needs a case
        (lambda p: p["message"].update(author="S-0000"), ""),  # inbound author must be the student
    ],
)
def test_invalid_intake_is_rejected_with_field_errors_and_no_echo(client, mutate, field):
    p = bad(mutate)
    r = post(client, p)
    assert r.status_code == 422, p
    body = r.json()
    assert body["detail"] and body["errors"]
    if field:
        assert any(e["field"].startswith(field) for e in body["errors"]), body
    for leaked in ("jane.smith@example.edu", "801-555-0199", "12345678", "passwd"):
        assert leaked not in r.text
    assert len(client.get("/api/cases").json()) == 5  # nothing was created


def test_old_unvalidated_import_endpoint_is_gone(client):
    assert client.post("/api/messages/import", json={}).status_code in (404, 405)
