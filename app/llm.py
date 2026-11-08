"""LLM access. Two interchangeable classes with the same interface:

* `MockLLM`  - deterministic, no network, used when VULTR_INFERENCE_API_KEY is empty.
* `OpenAICompatLLM` - talks to Vultr Serverless Inference (OpenAI-compatible API).

The agent loop only uses `plan()` and `verify()`; `models()` backs GET /api/models.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.config import Settings

Step = dict[str, Any]  # {"tool": str, "args": dict, "reason": str}


class LLM(Protocol):
    mock: bool

    def plan(self, task: str, tools: list[dict[str, Any]]) -> list[Step]: ...
    def verify(self, task: str, step: Step, result: dict[str, Any]) -> dict[str, Any]: ...
    def models(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- mock

# Code snippets the mock planner hands to the sandbox tool.
_NETWORK_CODE = (
    "import urllib.request\n"
    "print(urllib.request.urlopen('http://example.com', timeout=3).read()[:80])\n"
)
_LOOP_CODE = "while True:\n    pass\n"
_HELLO_CODE = "print('hello from the sandbox', sum(range(10)))\n"


class MockLLM:
    """Keyword-driven fake. Lets the whole app (and the tests) run with no credentials.

    TODO(topic): once the topic is chosen, tweak or delete the keyword rules so the demo
    in mock mode tells the story of your project.
    """

    mock = True

    def plan(self, task: str, tools: list[dict[str, Any]]) -> list[Step]:
        t = task.lower()
        steps: list[Step] = [
            {"tool": "echo_note", "args": {"text": f"Understood task: {task}"}, "reason": "Log"}
        ]
        if any(k in t for k in ("network", "http", "curl", "download", "internet")):
            steps.append(
                {"tool": "run_python", "args": {"code": _NETWORK_CODE}, "reason": "Fetch a page"}
            )
        elif any(k in t for k in ("loop", "forever", "timeout", "hang")):
            steps.append(
                {"tool": "run_python", "args": {"code": _LOOP_CODE}, "reason": "Busy loop"}
            )
        elif any(k in t for k in ("code", "python", "run", "calculate")):
            steps.append(
                {"tool": "run_python", "args": {"code": _HELLO_CODE}, "reason": "Run code"}
            )
        if any(k in t for k in ("send", "email", "notify", "approve", "pay")):
            steps.append(
                {
                    "tool": "send_notification",
                    "args": {"to": "team@example.com", "message": f"Result of: {task}"},
                    "reason": "Notify (needs human approval)",
                }
            )
        return steps

    def verify(self, task: str, step: Step, result: dict[str, Any]) -> dict[str, Any]:
        ok = bool(result.get("ok"))
        return {"ok": ok, "reason": "Mock verifier: " + ("looks good" if ok else "step failed")}

    def models(self) -> dict[str, Any]:
        return {"mock": True, "data": [{"id": "mock-model", "object": "model"}]}


# --------------------------------------------------------------------------- real


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> Any:
    """Models often wrap JSON in prose or ``` fences. Grab the outermost {...} or [...]."""
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model did not return valid JSON: {text[:200]!r}")


class OpenAICompatLLM:
    mock = False

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=60)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def chat(self, system: str, user: str) -> str:
        if not self.settings.model:
            raise LLMError("LLM_MODEL is not set. Call GET /api/models and pick a model id.")
        resp = self.client.post(
            f"{self.settings.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.settings.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        if resp.status_code != 200:
            raise LLMError(f"Inference API returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]

    def plan(self, task: str, tools: list[dict[str, Any]]) -> list[Step]:
        system = (
            "You are the planner of an agent. Break the task into a short list of steps, "
            "each using exactly one of the available tools. Reply with JSON only: "
            '{"steps": [{"tool": "<name>", "args": {...}, "reason": "<why>"}]}'
        )
        user = f"Task: {task}\n\nAvailable tools:\n{json.dumps(tools, indent=2)}"
        data = _extract_json(self.chat(system, user))
        steps = data.get("steps") if isinstance(data, dict) else data
        if not isinstance(steps, list):
            raise LLMError("Plan JSON has no 'steps' list")
        return [
            {
                "tool": str(s.get("tool", "")),
                "args": s.get("args") or {},
                "reason": str(s.get("reason", "")),
            }
            for s in steps
            if isinstance(s, dict)
        ]

    def verify(self, task: str, step: Step, result: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You verify one step of an agent run. Decide if the step achieved its purpose. "
            'Reply with JSON only: {"ok": true|false, "reason": "<short>"}'
        )
        user = json.dumps({"task": task, "step": step, "result": result}, default=str)
        data = _extract_json(self.chat(system, user))
        return {"ok": bool(data.get("ok")), "reason": str(data.get("reason", ""))}

    def models(self) -> dict[str, Any]:
        resp = self.client.get(f"{self.settings.base_url}/models", headers=self._headers())
        if resp.status_code != 200:
            raise LLMError(f"Inference API returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()


def get_llm(settings: Settings) -> LLM:
    return MockLLM() if settings.mock_llm else OpenAICompatLLM(settings)
