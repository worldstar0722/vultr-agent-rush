"""Tool registry. A tool is a plain function: `fn(args: dict) -> dict`.

The returned dict should contain `ok` (bool) and `output` (str). A tool that was stopped
by a safety control should also set `blocked` (human-readable reason) and `blocked_kind`;
the agent loop turns that into a red "blocked" event.

TODO(topic): replace the three demo tools below with your project's real tools.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.sandbox import SandboxRunner

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Tool:
    name: str
    description: str
    fn: ToolFn
    args_hint: str = "{}"  # shown to the LLM so it knows what args to pass
    requires_approval: bool = False  # pause the run until a human clicks Approve


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        """Description of every tool, passed to the planner LLM."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "args": t.args_hint,
                "requires_approval": t.requires_approval,
            }
            for t in self._tools.values()
        ]


def build_default_registry(runner: SandboxRunner) -> ToolRegistry:
    reg = ToolRegistry()

    # Demo tool, harmless. TODO(topic): delete.
    reg.register(
        Tool(
            name="echo_note",
            description="Write a note to the run log.",
            args_hint='{"text": "string"}',
            fn=lambda a: {"ok": True, "output": str(a.get("text", ""))},
        )
    )

    # Track 1 tool: runs code in the sandbox. TODO(topic): keep, adapt or delete.
    def run_python(args: dict[str, Any]) -> dict[str, Any]:
        res = runner.run(str(args.get("code", "")))
        out = (res.stdout + res.stderr).strip()
        result: dict[str, Any] = {"ok": res.ok, "output": out, "sandbox": res.runner}
        if res.blocked:
            result["blocked"] = res.blocked
            result["blocked_kind"] = res.blocked_kind
        return result

    reg.register(
        Tool(
            name="run_python",
            description="Run untrusted Python code inside an isolated sandbox. No network.",
            args_hint='{"code": "python source"}',
            fn=run_python,
        )
    )

    # Track 2 tool: a side effect that must be approved by a human. TODO(topic): replace
    # the body with a real action (send email, create ticket, post to Slack, ...).
    reg.register(
        Tool(
            name="send_notification",
            description="Send a message to a person. Has a real-world side effect.",
            args_hint='{"to": "address", "message": "text"}',
            requires_approval=True,
            fn=lambda a: {
                "ok": True,
                "output": f"(demo) would send to {a.get('to')}: {a.get('message')}",
            },
        )
    )
    return reg
