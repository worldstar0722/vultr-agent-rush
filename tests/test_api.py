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
