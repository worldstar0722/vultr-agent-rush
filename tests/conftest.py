import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # Mock LLM (no api_key), no delays, tiny approval timeout so tests are fast.
    return Settings(step_delay=0, approval_timeout=5, sandbox_enabled=False)


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


def read_events(client: TestClient, run_id: str) -> list[dict]:
    """Read the SSE stream until the server ends it (run finished)."""
    import json

    events = []
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                events.append(json.loads(line[6:]))
    return events
