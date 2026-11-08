import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import MockLLM, OpenAICompatLLM
from app.main import create_app

SECRET = "sk-test-SECRET-0123456789"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "gc.db"))  # no api_key => mock mode


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


# ------------------------------------------------------------------ live-provider test doubles


class Provider:
    """Stands in for the provider's HTTP API. Records every request it receives.

    steps: responses (httpx.Response), callables(request)->Response, or Exceptions to raise.
    The last step repeats forever.
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step(request) if callable(step) else step

    def bodies(self) -> list[dict]:
        return [json.loads(c.content) for c in self.calls if c.method == "POST"]


def chat(content, *, model="test-model-v1", usage=(500, 200)) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    body = {"model": model, "choices": [{"message": {"content": text}}]}
    if usage:
        body["usage"] = {
            "prompt_tokens": usage[0],
            "completion_tokens": usage[1],
            "total_tokens": usage[0] + usage[1],
        }
    return httpx.Response(200, json=body)


def timeout(request):
    raise httpx.ReadTimeout("timed out", request=request)


def live_settings(tmp_path, **kw) -> Settings:
    base = dict(db_path=str(tmp_path / "gc.db"), api_key=SECRET, model="test-model-v1",
                llm_retry_delay=0.0, llm_max_retries=1)  # fmt: skip
    base.update(kw)
    return Settings(**base)


def live_client(settings: Settings, provider: Provider) -> TestClient:
    llm = OpenAICompatLLM(settings, client=httpx.Client(transport=httpx.MockTransport(provider)),
                          sleep=lambda s: None)  # fmt: skip
    return TestClient(create_app(settings, llm=llm))


# A reply a well-behaved model could return for Case A. It cites only real records and states only
# computed values, and avoids "decision pending" wording so a professor can still approve it.
def reply_a(**over) -> dict:
    d = {
        "classification": "late_flag",
        "summary": "ATT-A1 was on time but the newest attempt ATT-A2 was 11 minutes late.",
        "verified": [
            {
                "text": "Attempt 1 was submitted at 22:40, 79 minutes before the deadline.",
                "evidence_ids": ["ATT-A1"],
            },
            {
                "text": "Attempt 2 was submitted at 00:10, 11 minutes after the deadline.",
                "evidence_ids": ["ATT-A2"],
            },
        ],  # fmt: skip
        "unverified": [
            {
                "text": "Whether attempt 1 should count instead is not settled.",
                "evidence_ids": ["POL-LATE-v1"],
            }
        ],  # fmt: skip
        "unresolved": ["Confirm whether ATT-A1 counts"],
        "reply": "Hello, we checked the records. Attempt 1 was at 22:40 [ATT-A1] and attempt 2 "
        "was at 00:10, 11 minutes after the deadline [ATT-A2].",
        "rationale": "Two attempts straddle the deadline.",
        "uncertainty": "The professor has not recorded which attempt counts.",
    }
    d.update(over)
    return d
