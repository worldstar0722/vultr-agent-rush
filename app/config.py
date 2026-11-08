"""All configuration comes from environment variables. See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    product_name: str = "GradeCase"
    product_tagline: str = "Case desk for grading exceptions: one case, one evidence bundle"

    db_path: str = "/data/gradecase.db"

    # Optional LLM (Vultr Serverless Inference, OpenAI-compatible). Empty key => MOCK mode.
    api_key: str = ""
    base_url: str = "https://api.vultrinference.com/v1"
    model: str = ""  # TODO: verify - choose an id from GET /api/models
    llm_timeout: float = 20.0

    @property
    def mock_llm(self) -> bool:
        return not self.api_key

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        return cls(
            product_name=os.getenv("PRODUCT_NAME", d.product_name),
            product_tagline=os.getenv("PRODUCT_TAGLINE", d.product_tagline),
            db_path=os.getenv("DB_PATH", d.db_path),
            api_key=os.getenv("VULTR_INFERENCE_API_KEY", "").strip(),
            base_url=os.getenv("VULTR_INFERENCE_BASE_URL", d.base_url).rstrip("/"),
            model=os.getenv("LLM_MODEL", "").strip(),
            llm_timeout=_num("LLM_TIMEOUT_SECONDS", d.llm_timeout),
        )
