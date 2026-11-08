"""Starts agent runs in background threads and routes approvals."""

from __future__ import annotations

import threading

from app.agent.approvals import ApprovalGate
from app.agent.loop import run_agent
from app.agent.tools import ToolRegistry
from app.config import Settings
from app.events import WAITING_APPROVAL, EventStore, Run
from app.llm import LLM


class RunManager:
    def __init__(
        self, store: EventStore, llm: LLM, registry: ToolRegistry, settings: Settings
    ) -> None:
        self.store = store
        self.llm = llm
        self.registry = registry
        self.settings = settings
        self.gate = ApprovalGate()

    def start(self, task: str) -> Run:
        run = self.store.create_run(task)
        threading.Thread(
            target=run_agent,
            args=(run.id, task),
            kwargs=dict(
                store=self.store,
                llm=self.llm,
                registry=self.registry,
                gate=self.gate,
                settings=self.settings,
            ),
            daemon=True,
        ).start()
        return run

    def approve(self, run_id: str, approved: bool) -> bool:
        """True if a decision was delivered, False if the run isn't waiting for one."""
        run = self.store.get_run(run_id)
        if run is None or run.status != WAITING_APPROVAL:
            return False
        return self.gate.resolve(run_id, approved)
