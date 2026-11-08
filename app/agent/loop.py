"""The agent loop: plan -> act (tool call) -> verify, with step and retry limits.

Every stage writes a typed event to the store; the UI is just a view of that log.

Rules:
* `max_steps` caps the total number of tool executions in a run (retries count).
* Each plan step gets 1 attempt + up to `max_retries` retries if `verify` says not ok.
* A tool with requires_approval=True pauses the run before EVERY attempt until a human
  approves. Rejecting skips that step (no retry) and the run carries on.
* A tool result containing `blocked` emits a "blocked" event. Being contained counts as a
  successful outcome, so we don't verify/retry it.
"""

from __future__ import annotations

import time
from typing import Any

from app.agent.approvals import ApprovalGate
from app.agent.tools import ToolRegistry
from app.config import Settings
from app.events import DONE, FAILED, RUNNING, WAITING_APPROVAL, EventStore
from app.llm import LLM

MAX_EVENT_TEXT = 2000


def _clip(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    if isinstance(out.get("output"), str) and len(out["output"]) > MAX_EVENT_TEXT:
        out["output"] = out["output"][:MAX_EVENT_TEXT] + "\n...[truncated]"
    return out


def run_agent(
    run_id: str,
    task: str,
    *,
    store: EventStore,
    llm: LLM,
    registry: ToolRegistry,
    gate: ApprovalGate,
    settings: Settings,
) -> None:
    def emit(type: str, **data: Any) -> None:
        store.append(run_id, type, data)

    counts = {"completed": 0, "skipped": 0, "blocked": 0}
    actions = 0
    try:
        steps = llm.plan(task, registry.specs())
        emit("plan", task=task, steps=steps, mock=llm.mock)

        for index, step in enumerate(steps, start=1):
            time.sleep(settings.step_delay)
            tool = registry.get(step["tool"])
            if tool is None:
                emit("error", step=index, message=f"Plan used unknown tool {step['tool']!r}")
                counts["skipped"] += 1
                continue

            for attempt in range(1, settings.max_retries + 2):
                if actions >= settings.max_steps:
                    raise RuntimeError(f"Stopped: reached the limit of {settings.max_steps} steps")

                if tool.requires_approval:
                    gate.open(run_id)
                    store.set_status(run_id, WAITING_APPROVAL)
                    emit("approval_requested", step=index, tool=tool.name, args=step["args"])
                    decision = gate.wait(run_id, settings.approval_timeout)
                    store.set_status(run_id, RUNNING)
                    if not decision:
                        timed_out = decision is None
                        emit(
                            "approval_denied",
                            step=index,
                            tool=tool.name,
                            by="timeout" if timed_out else "user",
                        )
                        counts["skipped"] += 1
                        break
                    emit("approval_granted", step=index, tool=tool.name, by="user")

                actions += 1
                emit("tool_call", step=index, attempt=attempt, tool=tool.name, args=step["args"])
                try:
                    result = tool.fn(step["args"])
                except Exception as exc:  # a crashing tool is a failed attempt, not a crash
                    result = {"ok": False, "output": f"Tool crashed: {exc}"}
                emit("tool_result", step=index, attempt=attempt, tool=tool.name, **_clip(result))

                if result.get("blocked"):
                    emit(
                        "blocked",
                        step=index,
                        tool=tool.name,
                        reason=result["blocked"],
                        kind=result.get("blocked_kind"),
                    )
                    emit(
                        "verify", step=index, ok=True, reason="Contained by the sandbox; no retry."
                    )
                    counts["blocked"] += 1
                    break

                verdict = llm.verify(task, step, result)
                emit("verify", step=index, attempt=attempt, **verdict)
                if verdict["ok"]:
                    counts["completed"] += 1
                    break
                if attempt > settings.max_retries:
                    raise RuntimeError(
                        f"Step {index} failed verification after {attempt} attempts: "
                        f"{verdict['reason']}"
                    )

        emit("done", summary=f"{len(steps)} planned step(s) processed", **counts)
        store.set_status(run_id, DONE)
    except Exception as exc:
        emit("error", message=str(exc))
        store.set_status(run_id, FAILED)
