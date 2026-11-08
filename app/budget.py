"""Spending safety. Everything is in SQLite, so restarts and "Reset demo data" never refill it.

Limits (all server-side; clients cannot choose a model, a URL, a token cap or a budget):
* LIFETIME cap on provider HTTP attempts (AI_LIFETIME_MAX_CALLS, default 50, all visitors together).
  Each attempt, including a retry, is reserved in a transaction BEFORE the request is sent and is
  never refunded, whatever happens afterwards (a timeout may still have been billed).
* A hard ceiling per call: prompt bytes (AI_MAX_PROMPT_BYTES, <= 32768) and completion tokens
  (LLM_MAX_TOKENS, <= 2048), enforced in config.py and llm.py.
* A per-client cap on analysis runs per rolling hour (clients are stored as salted hashes).

Reaching a limit returns HTTP 429 with a stable `code`; nothing is queued.
Worst case at the defaults: 50 calls x (32,768 bytes in + 2,048 tokens out). At the operator's
stated model price ceiling that is far below the authorised total; see README for the arithmetic.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.db import connect
from app.llm import LLMError


class RateLimited(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None) -> None:
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


def client_id(raw: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{raw}".encode()).hexdigest()[:16]


class Budget:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    # ------------------------------------------------------------------- per client
    def check_client(self, client: str) -> None:
        """Raises RateLimited if this client already used its hourly analysis runs."""
        limit = self.s.ai_client_hourly_limit
        cutoff = time.time() - 3600
        with connect(self.s.db_path) as conn:
            conn.execute("DELETE FROM ai_client_calls WHERE ts < ?", (cutoff,))
            rows = conn.execute(
                "SELECT ts FROM ai_client_calls WHERE client=? ORDER BY ts", (client,)
            ).fetchall()
        if len(rows) >= limit:
            wait = max(1, int(rows[0]["ts"] + 3600 - time.time()))
            raise RateLimited(
                "ai_client_throttled",
                f"This client has used its {limit} analysis runs for the past hour. Try again later.",
                wait,
            )

    def client_usage(self, client: str) -> int:
        cutoff = time.time() - 3600
        with connect(self.s.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM ai_client_calls WHERE client=? AND ts >= ?",
                (client, cutoff),
            ).fetchone()
        return int(row["n"])

    def note_client_run(self, client: str) -> None:
        with connect(self.s.db_path) as conn:
            conn.execute(
                "INSERT INTO ai_client_calls (client, ts) VALUES (?, ?)", (client, time.time())
            )

    # --------------------------------------------------------------- lifetime attempts
    def usage(self) -> dict[str, Any]:
        with connect(self.s.db_path) as conn:
            row = conn.execute("SELECT calls, tokens FROM ai_usage_total WHERE id=1").fetchone()
        calls, tokens = (row["calls"], row["tokens"]) if row else (0, 0)
        limit = self.s.ai_lifetime_max_calls
        return {
            "scope": "lifetime",
            "calls_used": calls,
            "calls_limit": limit,
            "calls_remaining": max(0, limit - calls),
            "tokens_reported": tokens,  # information only; the call cap is what bounds spend
            "max_prompt_bytes": self.s.ai_max_prompt_bytes,
            "max_completion_tokens": self.s.llm_max_tokens,
            "max_retries": self.s.llm_max_retries,
            "exhausted": calls >= limit,
        }

    def reserve_attempt(self, prompt_bytes: int, case_id: str, provider: str, model: str) -> int:
        """Atomically reserve one provider attempt, or raise before any network traffic.

        The reservation is permanent: it is not refunded on timeout, error or retry.
        """
        with connect(self.s.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO ai_usage_total (id) VALUES (1)")
            calls = conn.execute("SELECT calls FROM ai_usage_total WHERE id=1").fetchone()["calls"]
            if calls + 1 > self.s.ai_lifetime_max_calls:
                raise LLMError("budget")
            conn.execute("UPDATE ai_usage_total SET calls = calls + 1 WHERE id=1")
            cur = conn.execute(
                "INSERT INTO ai_attempt_log (ts, case_id, provider, model, prompt_bytes) "
                "VALUES (?,?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    case_id,
                    provider,
                    model,
                    prompt_bytes,
                ),
            )
            return int(cur.lastrowid or 0)

    def finish_attempt(self, attempt_id: int, outcome: str, tokens: int | None) -> None:
        with connect(self.s.db_path) as conn:
            conn.execute(
                "UPDATE ai_attempt_log SET outcome=?, total_tokens=? WHERE id=?",
                (outcome, tokens, attempt_id),
            )
            if tokens:
                conn.execute("UPDATE ai_usage_total SET tokens = tokens + ? WHERE id=1", (tokens,))

    def gate(self, case_id: str, provider: str, model: str) -> BudgetGate:
        return BudgetGate(self, case_id, provider, model)

    # ------------------------------------------------------------------- operator reset
    def reset(self) -> None:
        """Operator-only (`python -m app.tools reset-ai-budget --i-understand-...`): never over HTTP.

        Clears the lifetime counters and client throttles. The attempt log is kept as the record.
        """
        with connect(self.s.db_path) as conn:
            conn.execute("DELETE FROM ai_usage_total")
            conn.execute("DELETE FROM ai_client_calls")


class BudgetGate:
    """Handed to the provider client; every HTTP attempt passes through it."""

    def __init__(self, budget: Budget, case_id: str, provider: str, model: str) -> None:
        self.budget, self.case_id, self.provider, self.model = budget, case_id, provider, model
        self._attempt = 0

    def before_attempt(self, prompt_bytes: int) -> None:
        self._attempt = self.budget.reserve_attempt(
            prompt_bytes, self.case_id, self.provider, self.model
        )

    def after_attempt(self, usage: dict[str, int | None], outcome: str) -> None:
        total = usage.get("total_tokens")
        self.budget.finish_attempt(
            self._attempt, outcome, total if isinstance(total, int) else None
        )


__all__ = ["Budget", "BudgetGate", "RateLimited", "client_id"]
