"""All configuration lives here. Everything is read from environment variables.

See .env.example for the documented list of variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    # --- Branding (TODO: set once the topic is chosen; shown in the UI) ---
    product_name: str = "TODO: Product Name"
    product_tagline: str = "TODO: one-line tagline about what the agent does"

    # --- LLM (Vultr Serverless Inference, OpenAI-compatible) ---
    api_key: str = ""  # empty => deterministic MOCK mode
    base_url: str = "https://api.vultrinference.com/v1"
    model: str = ""  # TODO: verify - pick one from GET /api/models

    # --- Agent loop ---
    max_steps: int = 8  # max tool executions per run (retries count)
    max_retries: int = 3  # retries per step after the first attempt
    approval_timeout: float = 600.0  # seconds to wait for a human before auto-reject
    step_delay: float = 0.4  # small pause between steps so the UI timeline feels live

    # --- Sandbox (Track 1) ---
    sandbox_enabled: bool = False
    sandbox_image: str = "python:3.12-slim"
    sandbox_timeout: float = 10.0  # wall-clock seconds
    sandbox_memory: str = "128m"
    sandbox_cpus: str = "0.5"
    sandbox_pids: int = 64

    @property
    def mock_llm(self) -> bool:
        return not self.api_key

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        return cls(
            product_name=os.getenv("PRODUCT_NAME", d.product_name),
            product_tagline=os.getenv("PRODUCT_TAGLINE", d.product_tagline),
            api_key=os.getenv("VULTR_INFERENCE_API_KEY", "").strip(),
            base_url=os.getenv("VULTR_INFERENCE_BASE_URL", d.base_url).rstrip("/"),
            model=os.getenv("LLM_MODEL", "").strip(),
            max_steps=int(_num("MAX_STEPS", d.max_steps)),
            max_retries=int(_num("MAX_RETRIES", d.max_retries)),
            approval_timeout=_num("APPROVAL_TIMEOUT_SECONDS", d.approval_timeout),
            step_delay=_num("STEP_DELAY_SECONDS", d.step_delay),
            sandbox_enabled=_bool("SANDBOX_ENABLED", d.sandbox_enabled),
            sandbox_image=os.getenv("SANDBOX_IMAGE", d.sandbox_image),
            sandbox_timeout=_num("SANDBOX_TIMEOUT_SECONDS", d.sandbox_timeout),
            sandbox_memory=os.getenv("SANDBOX_MEMORY", d.sandbox_memory),
            sandbox_cpus=os.getenv("SANDBOX_CPUS", d.sandbox_cpus),
            sandbox_pids=int(_num("SANDBOX_PIDS", d.sandbox_pids)),
        )
