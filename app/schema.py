"""Strict structure the model must return. Anything else is rejected, not repaired."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

Classification = Literal["late_flag", "score_gap", "missing_submission", "other"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: StrictStr = Field(min_length=1, max_length=500)
    evidence_ids: list[StrictStr] = Field(default_factory=list, max_length=12)


class AIAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    classification: Classification
    summary: StrictStr = Field(min_length=1, max_length=700)
    verified: list[Claim] = Field(max_length=12)
    unverified: list[Claim] = Field(max_length=12)
    unresolved: list[StrictStr] = Field(default_factory=list, max_length=8)
    reply: StrictStr = Field(min_length=1, max_length=3000)
    rationale: StrictStr = Field(default="", max_length=900)
    uncertainty: StrictStr = Field(default="", max_length=700)


def schema_problems(exc: ValidationError) -> str:
    """Field names and error kinds only. Never echoes values (they are untrusted model text)."""
    parts = []
    for err in exc.errors()[:6]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['type']}")
    return "; ".join(parts)
