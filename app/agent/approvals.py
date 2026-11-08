"""Human-approval gate: the agent thread waits here until someone clicks Approve/Reject."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class ApprovalGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}

    def open(self, run_id: str) -> None:
        """Register a pending approval. Call BEFORE emitting approval_requested."""
        with self._lock:
            self._pending[run_id] = _Pending()

    def wait(self, run_id: str, timeout: float) -> bool | None:
        """Block until resolved. Returns True/False, or None on timeout."""
        with self._lock:
            pending = self._pending[run_id]
        got = pending.event.wait(timeout)
        with self._lock:
            self._pending.pop(run_id, None)
        return pending.approved if got else None

    def resolve(self, run_id: str, approved: bool) -> bool:
        """Called from the HTTP endpoint. False if nothing is waiting."""
        with self._lock:
            pending = self._pending.get(run_id)
        if pending is None or pending.event.is_set():
            return False
        pending.approved = approved
        pending.event.set()
        return True
