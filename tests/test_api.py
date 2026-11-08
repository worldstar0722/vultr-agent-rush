def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_and_banner(client):
    assert "Synthetic demo data" in client.get("/").text
    cfg = client.get("/api/config").json()
    assert cfg["product_name"] == "GradeCase"
    assert "No grades are changed and no messages are sent" in cfg["banner"]
    assert cfg["llm_mode"] == "mock"  # no key => we do not claim Vultr inference


def test_models_mock(client):
    assert client.get("/api/models").json()["mock"] is True


def test_queue_has_five_cases_with_owner_and_last_reply(client):
    cases = {c["id"]: c for c in client.get("/api/cases").json()}
    assert set(cases) == {"CASE-A", "CASE-A2", "CASE-B", "CASE-C", "CASE-D"}
    a = cases["CASE-A"]
    assert a["owner"] == "TA Rivera"
    assert a["last_reply"]["channel"] == "submission_comment"
    assert cases["CASE-A2"]["channels"] == ["email"]
    assert all(c["status"] == "New" for c in cases.values())
    assert cases["CASE-C"]["owner"] is None


def test_invalid_role_and_unknown_case(client):
    assert client.get("/api/cases/NOPE").status_code == 404
    r = client.post("/api/cases/CASE-D/decision", json={"role": "student", "action": "hold"})
    assert r.status_code == 400


def test_importing_the_app_module_has_no_side_effects(tmp_path):
    """Regression: CI imports app.main as a non-root user; import must not create a DB."""
    import subprocess
    import sys

    target = tmp_path / "should_not_exist" / "gc.db"
    code = "import app.main"
    subprocess.run([sys.executable, "-c", code], check=True, env={"DB_PATH": str(target)})
    assert not target.parent.exists()


def test_case_list_carries_the_dates_the_board_and_calendar_need(client):
    cases = {c["id"]: c for c in client.get("/api/cases").json()}
    a = cases["CASE-A"]
    assert (
        a["deadline"] == "2026-11-05T23:59:00-07:00"
    )  # from the deadline record, not the import time
    assert a["opened_at"] == "2026-11-06T08:05:00-07:00"  # first inbound message, not the seed time
    assert a["decisions"] == []
    assert cases["CASE-C"]["deadline"] == "2026-11-06T23:59:00-07:00"
    client.post(
        "/api/cases/CASE-A/decision", json={"role": "ta", "action": "escalate", "note": "n"}
    )
    decided = {c["id"]: c for c in client.get("/api/cases").json()}["CASE-A"]["decisions"]
    assert [d["action"] for d in decided] == ["escalate"] and decided[0]["ts"]
