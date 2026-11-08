"""All configuration comes from environment variables. See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Hard ceilings. Environment values above these are clamped down, so a typo can never raise the
# worst-case cost of one call. Worst case per call: 32,768 prompt bytes in, 2,048 tokens out.
MAX_TOKENS_CEILING = 2048
MAX_PROMPT_BYTES_CEILING = 32768
MAX_RETRIES_CEILING = 1
MAX_REASONING_CEILING = 1024  # reasoning tokens are billed as output; keep them small


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    product_name: str = "GradeCase"
    product_tagline: str = "Case desk for grading exceptions: one case, one evidence bundle"

    db_path: str = "/data/gradecase.db"
    max_cases: int = 200  # intake refuses new cases beyond this (protects disk on a public demo)

    # --- LLM (Vultr Serverless Inference, OpenAI-compatible). Empty key => MOCK mode. ---
    # repr=False so the key can never leak through logging or an exception message.
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.vultrinference.com/v1"
    model: str = ""  # discover with GET /api/models or `python -m app.tools models`
    llm_timeout: float = 30.0  # seconds per HTTP attempt
    llm_max_tokens: int = MAX_TOKENS_CEILING  # completion cap per call (clamped to the ceiling)
    # Reasoning models (e.g. qwen3.8-flash-next) spend completion tokens on hidden reasoning; with only
    # max_tokens a small cap can leave EMPTY content. We send reasoning.max_tokens (< the completion
    # cap) so the answer always has room. 0 omits the field for models that do not support it.
    llm_reasoning_max_tokens: int = 128
    llm_json_mode: bool = True  # response_format {"type": "json_object"}
    llm_max_retries: int = 0  # 0 = never retry (deployment default); 1 = one retry if transient
    llm_retry_delay: float = 1.0  # pause before that retry

    # --- Spending safety (enforced server-side, persisted in SQLite, survives resets/restarts) ---
    ai_lifetime_max_calls: int = 50  # provider HTTP attempts EVER (every retry counts)
    ai_max_prompt_bytes: int = MAX_PROMPT_BYTES_CEILING  # UTF-8 bytes of system + user prompt
    ai_client_hourly_limit: int = 6  # analysis runs per client per rolling hour

    def __post_init__(self) -> None:
        clamp = object.__setattr__  # frozen dataclass
        clamp(self, "llm_max_tokens", max(1, min(int(self.llm_max_tokens), MAX_TOKENS_CEILING)))
        reasoning = max(0, min(int(self.llm_reasoning_max_tokens), MAX_REASONING_CEILING))
        clamp(self, "llm_reasoning_max_tokens", min(reasoning, self.llm_max_tokens - 1))
        clamp(self, "llm_max_retries", max(0, min(int(self.llm_max_retries), MAX_RETRIES_CEILING)))
        clamp(
            self,
            "ai_max_prompt_bytes",
            max(1024, min(int(self.ai_max_prompt_bytes), MAX_PROMPT_BYTES_CEILING)),
        )

    @property
    def mock_llm(self) -> bool:
        return not self.api_key

    @property
    def ai_mode(self) -> str:
        """mock: no key. misconfigured: key but no model. configured: key + model (unproven)."""
        if not self.api_key:
            return "mock"
        return "configured" if self.model else "misconfigured"

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        return cls(
            product_name=os.getenv("PRODUCT_NAME", d.product_name),
            product_tagline=os.getenv("PRODUCT_TAGLINE", d.product_tagline),
            db_path=os.getenv("DB_PATH", d.db_path),
            max_cases=int(_num("MAX_CASES", d.max_cases)),
            api_key=os.getenv("VULTR_INFERENCE_API_KEY", "").strip(),
            base_url=os.getenv("VULTR_INFERENCE_BASE_URL", d.base_url).strip().rstrip("/"),
            model=os.getenv("LLM_MODEL", "").strip(),
            llm_timeout=_num("LLM_TIMEOUT_SECONDS", d.llm_timeout),
            llm_max_tokens=int(_num("LLM_MAX_TOKENS", d.llm_max_tokens)),
            llm_reasoning_max_tokens=int(
                _num("LLM_REASONING_MAX_TOKENS", d.llm_reasoning_max_tokens)
            ),
            llm_json_mode=os.getenv("LLM_JSON_MODE", "true").strip().lower()
            not in {"0", "false", "no", "off"},
            llm_max_retries=int(_num("LLM_MAX_RETRIES", d.llm_max_retries)),
            llm_retry_delay=_num("LLM_RETRY_DELAY_SECONDS", d.llm_retry_delay),
            ai_lifetime_max_calls=int(_num("AI_LIFETIME_MAX_CALLS", d.ai_lifetime_max_calls)),
            ai_max_prompt_bytes=int(_num("AI_MAX_PROMPT_BYTES", d.ai_max_prompt_bytes)),
            ai_client_hourly_limit=int(_num("AI_CLIENT_HOURLY_LIMIT", d.ai_client_hourly_limit)),
        )
