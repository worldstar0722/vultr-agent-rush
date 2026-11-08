import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import MockLLM
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "gc.db"))  # no api key => mock LLM


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


def make_client(settings: Settings, llm=None) -> TestClient:
    return TestClient(create_app(settings, llm=llm or MockLLM()))


def detail(client: TestClient, case_id: str) -> dict:
    r = client.get(f"/api/cases/{case_id}")
    assert r.status_code == 200, r.text
    return r.json()


def decide(client, case_id, role, action, note="", **extra):
    return client.post(
        f"/api/cases/{case_id}/decision",
        json={"role": role, "action": action, "note": note, **extra},
    )
