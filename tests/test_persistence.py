from tests.conftest import decide, detail, make_client


def test_decision_survives_a_fresh_app_instance(settings):
    c1 = make_client(settings)
    c1.post("/api/cases/CASE-D/draft")
    assert decide(c1, "CASE-D", "ta", "approve", "ok").status_code == 200

    c2 = make_client(settings)  # new app object, same DB file
    d = detail(c2, "CASE-D")
    assert d["case"]["status"] == "Closed"
    log = d["decisions"][-1]
    assert (log["actor"], log["role"], log["action"]) == ("TA Rivera", "ta", "approve")
    assert (log["from_status"], log["to_status"]) == ("New", "Closed")
    assert log["ts"]
    assert d["draft"]["body_final"] and d["draft"]["approved_by"] == "TA Rivera"


def test_restart_does_not_reseed_over_existing_data(settings):
    c1 = make_client(settings)
    decide(c1, "CASE-C", "ta", "hold", "waiting")
    c2 = make_client(settings)
    assert detail(c2, "CASE-C")["case"]["on_hold"] is True


def test_reset_restores_fixtures(client):
    client.post("/api/cases/CASE-D/draft")
    decide(client, "CASE-D", "ta", "approve")
    assert client.post("/api/demo/reset").status_code == 400  # needs explicit confirm
    assert client.post("/api/demo/reset?confirm=true").status_code == 200
    d = detail(client, "CASE-D")
    assert d["case"]["status"] == "New" and d["decisions"] == [] and d["draft"] is None
