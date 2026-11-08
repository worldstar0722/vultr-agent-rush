from tests.conftest import read_events


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_and_config(client):
    assert "<html" in client.get("/").text
    cfg = client.get("/api/config").json()
    assert cfg["llm_mode"] == "mock"
    assert cfg["sandbox"] == "mock"


def test_models_in_mock_mode(client):
    body = client.get("/api/models").json()
    assert body["mock"] is True


def test_run_streams_events_via_sse(client):
    run_id = client.post("/api/runs", json={"task": "Run some python code"}).json()["id"]
    types = [e["type"] for e in read_events(client, run_id)]
    assert types[0] == "plan"
    assert "tool_call" in types and "tool_result" in types and "verify" in types
    assert types[-1] == "done"
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "done"


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/nope/events").status_code == 404
    assert client.post("/api/runs/nope/approve", json={"approved": True}).status_code == 404


def test_empty_task_rejected(client):
    assert client.post("/api/runs", json={"task": ""}).status_code == 422
