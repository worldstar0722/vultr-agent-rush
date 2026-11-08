"""Typed run events + a swappable event store.

The agent loop only talks to the `EventStore` interface. `InMemoryEventStore` is the
default. To persist runs, write a SQLite class with the same five methods and pass it
to `create_app(store=...)` (optional, not needed for the hackathon demo).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

EVENT_TYPES = (
    "plan",
    "tool_call",
    "tool_result",
    "verify",
    "approval_requested",
    "approval_granted",
    "approval_denied",
    "blocked",  # containment moment: the sandbox stopped something
    "error",
    "done",
)

# Run statuses
RUNNING = "running"
WAITING_APPROVAL = "waiting_approval"
DONE = "done"
FAILED = "failed"
TERMINAL = (DONE, FAILED)


@dataclass
class Event:
    id: int  # sequence number inside one run, starting at 1
    run_id: str
    type: str
    data: dict[str, Any]
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    id: str
    task: str
    status: str = RUNNING
    created_at: float = field(default_factory=time.time)


class EventStore(Protocol):
    def create_run(self, task: str) -> Run: ...
    def get_run(self, run_id: str) -> Run | None: ...
    def set_status(self, run_id: str, status: str) -> None: ...
    def append(self, run_id: str, type: str, data: dict[str, Any]) -> Event: ...
    def events(self, run_id: str, after: int = 0) -> list[Event]: ...


class InMemoryEventStore:
    """Thread-safe, lost on restart. Fine for a demo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._events: dict[str, list[Event]] = {}

    def create_run(self, task: str) -> Run:
        run = Run(id=uuid.uuid4().hex[:12], task=task)
        with self._lock:
            self._runs[run.id] = run
            self._events[run.id] = []
        return run

    def get_run(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def set_status(self, run_id: str, status: str) -> None:
        with self._lock:
            self._runs[run_id].status = status

    def append(self, run_id: str, type: str, data: dict[str, Any]) -> Event:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type}")
        with self._lock:
            log = self._events[run_id]
            event = Event(id=len(log) + 1, run_id=run_id, type=type, data=data)
            log.append(event)
            return event

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        with self._lock:
            return list(self._events.get(run_id, [])[after:])
