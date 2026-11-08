import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import read_events


def wait_for_status(client, run_id, status, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if client.get(f"/api/runs/{run_id}").json()["status"] == status:
            return
        time.sleep(0.02)
    raise AssertionError(f"run never reached {status}")


def start(client):
    return client.post("/api/runs", json={"task": "Summarize and email the team"}).json()["id"]


def test_pause_then_approve(client):
    run_id = start(client)
    wait_for_status(client, run_id, "waiting_approval")
    r = client.post(f"/api/runs/{run_id}/approve", json={"approved": True})
    assert r.status_code == 200
    types = [e["type"] for e in read_events(client, run_id)]
    assert "approval_requested" in types and "approval_granted" in types
    assert types.index("approval_requested") < types.index("approval_granted")
    assert types[-1] == "done"
    # the side-effecting tool only ran after approval
    assert types.index("approval_granted") < len(types) - 1 - types[::-1].index("tool_call")


def test_pause_then_reject_skips_the_tool(client):
    run_id = start(client)
    wait_for_status(client, run_id, "waiting_approval")
    client.post(f"/api/runs/{run_id}/approve", json={"approved": False})
    events = read_events(client, run_id)
    types = [e["type"] for e in events]
    assert "approval_denied" in types
    assert not any(
        e["type"] == "tool_call" and e["data"]["tool"] == "send_notification" for e in events
    )
    assert types[-1] == "done"


def test_approve_when_not_waiting_is_409(client):
    run_id = client.post("/api/runs", json={"task": "hello"}).json()["id"]
    read_events(client, run_id)  # let it finish
    assert client.post(f"/api/runs/{run_id}/approve", json={"approved": True}).status_code == 409


def test_approval_timeout_auto_rejects():
    client = TestClient(create_app(Settings(step_delay=0, approval_timeout=0.1)))
    run_id = start(client)
    events = read_events(client, run_id)
    denied = [e for e in events if e["type"] == "approval_denied"]
    assert denied and denied[0]["data"]["by"] == "timeout"
