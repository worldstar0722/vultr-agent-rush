"""Agent loop tests run the loop directly (synchronously) with fakes - no threads."""

from app.agent.approvals import ApprovalGate
from app.agent.loop import run_agent
from app.agent.tools import Tool, ToolRegistry
from app.config import Settings
from app.events import InMemoryEventStore
from app.llm import MockLLM


class ScriptedLLM(MockLLM):
    def __init__(self, steps, verdicts):
        self._steps, self._verdicts = steps, list(verdicts)

    def plan(self, task, tools):
        return self._steps

    def verify(self, task, step, result):
        return self._verdicts.pop(0) if self._verdicts else {"ok": True, "reason": "default"}


def run(llm, registry, **settings_kw):
    settings = Settings(step_delay=0, **settings_kw)
    store = InMemoryEventStore()
    r = store.create_run("task")
    run_agent(
        r.id,
        "task",
        store=store,
        llm=llm,
        registry=registry,
        gate=ApprovalGate(),
        settings=settings,
    )
    return store.get_run(r.id), [e.type for e in store.events(r.id)], store.events(r.id)


def registry_with(fn):
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="d", fn=fn))
    return reg


def test_happy_path_in_mock_mode():
    from app.agent.tools import build_default_registry
    from app.sandbox import MockSandbox

    reg = build_default_registry(MockSandbox())
    run_obj, types, _ = run(MockLLM(), reg)
    assert run_obj.status == "done"
    assert types == ["plan", "tool_call", "tool_result", "verify", "done"]


def test_retries_then_succeeds():
    calls = []
    llm = ScriptedLLM(
        [{"tool": "t", "args": {}, "reason": ""}],
        [
            {"ok": False, "reason": "no"},
            {"ok": False, "reason": "no"},
            {"ok": True, "reason": "yes"},
        ],
    )
    run_obj, types, _ = run(llm, registry_with(lambda a: calls.append(1) or {"ok": True}))
    assert run_obj.status == "done"
    assert len(calls) == 3


def test_gives_up_after_max_retries():
    calls = []
    llm = ScriptedLLM(
        [{"tool": "t", "args": {}, "reason": ""}], [{"ok": False, "reason": "x"}] * 10
    )
    run_obj, types, events = run(llm, registry_with(lambda a: calls.append(1) or {"ok": False}))
    assert run_obj.status == "failed"
    assert len(calls) == 4  # 1 attempt + 3 retries
    assert types[-1] == "error"


def test_max_steps_limit():
    steps = [{"tool": "t", "args": {}, "reason": ""}] * 5
    llm = ScriptedLLM(steps, [])
    calls = []
    run_obj, types, events = run(
        llm, registry_with(lambda a: calls.append(1) or {"ok": True}), max_steps=2
    )
    assert len(calls) == 2
    assert run_obj.status == "failed"
    assert "limit" in events[-1].data["message"]


def test_blocked_result_emits_blocked_event():
    reg = registry_with(lambda a: {"ok": False, "blocked": "no network", "blocked_kind": "network"})
    llm = ScriptedLLM([{"tool": "t", "args": {}, "reason": ""}], [])
    run_obj, types, events = run(llm, reg)
    assert run_obj.status == "done"
    assert "blocked" in types
    assert [e for e in events if e.type == "blocked"][0].data["reason"] == "no network"


def test_unknown_tool_is_reported_not_fatal():
    llm = ScriptedLLM([{"tool": "nope", "args": {}, "reason": ""}], [])
    run_obj, types, _ = run(llm, registry_with(lambda a: {"ok": True}))
    assert "error" in types and run_obj.status == "done"
