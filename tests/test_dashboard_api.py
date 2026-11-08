"""Read-only data behind the dashboard: real run statistics, the activity feed, and the labelled
guardrail demonstration."""

import sqlite3

from tests.conftest import Provider, chat, decide, live_client, live_settings, reply_a
from tests.test_documents import make_pdf
from tests.test_vision import good


def run(client, case="CASE-A", **body):
    return client.post(f"/api/cases/{case}/analysis", json=body)


def test_run_stats_start_at_zero_and_never_invent_numbers(client):
    r = client.get("/api/ai/status").json()["runs"]
    assert r == {"live_accepted": 0, "live_rejected": 0, "live_errors": 0, "mock": 0, "rules_only": 0,
                 "avg_live_latency_ms": None, "guardrail_rejections": 0}  # fmt: skip


def test_mock_runs_are_counted_as_mock_never_as_ai_success(client):
    client.post("/api/cases/CASE-A/analysis", json={})
    client.post("/api/cases/CASE-D/analysis", json={"rules_only": True})
    r = client.get("/api/ai/status").json()
    assert (
        r["runs"]["mock"] == 1 and r["runs"]["rules_only"] == 1 and r["runs"]["live_accepted"] == 0
    )
    assert r["last_success_at"] is None and r["runs"]["avg_live_latency_ms"] is None


def test_live_accepted_rejected_and_guardrail_catches_are_real_counts(tmp_path):
    bad = reply_a(reply="Per [POL-NOPE] we will regrade this.")
    p = Provider(chat(reply_a()), chat(bad))
    client = live_client(live_settings(tmp_path, ai_client_hourly_limit=99), p)
    run(client, "CASE-A")
    run(client, "CASE-B")
    runs = client.get("/api/ai/status").json()["runs"]
    assert (runs["live_accepted"], runs["live_rejected"], runs["guardrail_rejections"]) == (1, 1, 1)
    assert isinstance(runs["avg_live_latency_ms"], int)


def test_run_stats_follow_a_demo_reset_but_the_lifetime_budget_does_not(tmp_path):
    client = live_client(live_settings(tmp_path), Provider(chat(reply_a())))
    run(client)
    client.post("/api/demo/reset?confirm=true")
    st = client.get("/api/ai/status").json()
    assert st["runs"]["live_accepted"] == 0 and st["budget"]["calls_used"] == 1


def test_activity_feed_lists_real_events_newest_first(tmp_path):
    bad = reply_a(reply="Per [POL-NOPE] the policy allows it.")
    p = Provider(chat(bad))
    client = live_client(live_settings(tmp_path), p)
    run(client, "CASE-C")
    decide(client, "CASE-B", "ta", "escalate", "needs prof")
    feed = client.get("/api/activity?limit=50").json()
    assert [e["ts"] for e in feed] == sorted((e["ts"] for e in feed), reverse=True)
    kinds = {e["kind"] for e in feed}
    assert kinds == {"analysis", "decision", "case"}
    a = next(e for e in feed if e["kind"] == "analysis")
    assert (
        a["case_id"] == "CASE-C"
        and a["outcome"] == "rejected"
        and "does not exist in this case" in a["detail"]
    )
    d = next(e for e in feed if e["kind"] == "decision")
    assert (d["case_id"], d["action"], d["actor"], d["to_status"]) == (
        "CASE-B",
        "escalate",
        "TA Rivera",
        "Awaiting professor",
    )
    assert len(client.get("/api/activity?limit=2").json()) == 2
    assert client.get("/api/activity?limit=0").status_code == 422


def test_activity_marks_cases_created_from_uploaded_documents(tmp_path):
    client = live_client(live_settings(tmp_path), Provider(chat(good())))
    client.post("/api/intake/upload", data={"synthetic_ack": "true", "auto_create": "true"},
                files={"file": ("e.pdf", make_pdf(["I submitted HW6 on time but it shows late."]), "application/pdf")})  # fmt: skip
    created = [
        e
        for e in client.get("/api/activity?limit=50").json()
        if e["kind"] == "case" and e["case_id"] == "CASE-101"
    ]
    assert created and created[0]["source"] == "document"


def test_guardrail_demo_shows_every_check_failing_and_changes_nothing(tmp_path):
    p = Provider(chat(reply_a()))
    s = live_settings(tmp_path)
    client = live_client(s, p)
    before = client.get("/api/ai/status").json()["budget"]["calls_used"]
    r = client.post("/api/cases/CASE-A/guardrail-demo")
    assert r.status_code == 200
    b = r.json()
    assert (
        b["demonstration"] is True
        and "did not come from a model" in b["note"]
        and b["rejected"] is True
    )
    kinds = {f["kind"] for f in b["flags"]}
    assert {"invalid_citation", "needs_verification", "commitment"} <= kinds
    labels = {f.get("label") for f in b["flags"]}
    assert {"arithmetic", "recorded times"} <= labels
    assert any("POL-DEMO-v9" in f["message"] for f in b["flags"])
    # no model call, no budget, no run, nothing stored
    assert p.calls == [] and client.get("/api/ai/status").json()["budget"]["calls_used"] == before
    with sqlite3.connect(s.db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 0
    assert client.post("/api/cases/NOPE/guardrail-demo").status_code == 404


def test_explicit_issue_type_overrides_keyword_detection(client):
    payload = {
        "synthetic_ack": True, "student": "S-4B21", "assignment": "HW6",
        "message": {"channel": "email", "ts": "2026-11-09T08:00:00-07:00", "text": "Please look at my homework."},
    }  # fmt: skip
    auto = client.post("/api/intake", json=payload).json()["case_id"]
    chosen = client.post(
        "/api/intake", json={**payload, "student": "S-4B22", "issue": "score_gap"}
    ).json()["case_id"]
    cases = {c["id"]: c for c in client.get("/api/cases").json()}
    assert cases[auto]["issue"] == "other" and cases[chosen]["issue"] == "score_gap"
    assert client.post("/api/intake", json={**payload, "issue": "bogus"}).status_code == 422
