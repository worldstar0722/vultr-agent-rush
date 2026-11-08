"""FastAPI app. Run with: uvicorn app.main:create_app --factory --reload

There is deliberately no module-level `app`: importing this module must not touch the disk.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from app.budget import Budget, RateLimited, client_id
from app.config import Settings
from app.errors import DeskError
from app.intake import EXAMPLES, IntakeRequest
from app.llm import LLM, LLMError, get_llm
from app.service import Desk

STATIC_DIR = Path(__file__).parent / "static"
BANNER = (
    "Synthetic demo data. No real student records. No grades are changed and no messages are sent."
)


class DecisionBody(BaseModel):
    role: str
    action: str
    note: str = ""
    counted_attempt: str | None = None
    body: str | None = None


class RoleBody(BaseModel):
    role: str


class DraftBody(BaseModel):
    body: str


class AnalysisBody(BaseModel):
    """No model, URL, token cap or budget fields: clients cannot choose any of them."""

    model_config = ConfigDict(extra="forbid")

    force: bool = False  # Regenerate: ignore the cached run (still budgeted and throttled)
    rules_only: bool = False  # deterministic template, no model call


def create_app(settings: Settings | None = None, *, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    llm = llm or get_llm(settings)
    desk = Desk(settings, llm)
    app = FastAPI(title=settings.product_name)
    models_cache: dict[str, Any] = {"at": 0.0, "data": None}

    def who(request: Request) -> str:
        """Per-client key: first X-Forwarded-For hop (set by Caddy) or the socket address."""
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        raw = fwd or (request.client.host if request.client else "unknown")
        return client_id(raw, settings.db_path + "|" + settings.api_key)

    @app.exception_handler(DeskError)
    async def desk_error(_: Request, exc: DeskError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content={"detail": exc.message, "code": exc.code}
        )

    @app.exception_handler(RateLimited)
    async def rate_limited(_: Request, exc: RateLimited) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": exc.message,
                "code": exc.code,
                "retry_after_seconds": exc.retry_after,
            },
            # No Retry-After for a lifetime cap: waiting does not help, an operator must act.
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else {},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Field-level problems without echoing the submitted values back."""
        errors = []
        for e in exc.errors():
            loc = [str(p) for p in e["loc"] if p != "body"]
            msg = str(e["msg"]).removeprefix("Value error, ")
            errors.append({"field": ".".join(loc), "message": msg})
        return JSONResponse(
            status_code=422, content={"detail": "Some fields need attention.", "errors": errors}
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict:
        """Branding and truthful AI mode. Never contains a key or the provider URL."""
        return {
            "product_name": settings.product_name,
            "product_tagline": settings.product_tagline,
            "llm_mode": "mock" if llm.mock else "live",
            "ai_mode": settings.ai_mode,
            "model": settings.model or None if not llm.mock else None,
            "banner": BANNER,
        }

    @app.get("/api/ai/status")
    def ai_status(request: Request) -> dict:
        out = desk.analyzer.status()
        used = Budget(settings).client_usage(who(request))
        out["client"] = {"used": used, "limit": settings.ai_client_hourly_limit}
        return out

    @app.get("/api/models")
    def models() -> dict:
        if time.time() - models_cache["at"] < 60 and models_cache["data"] is not None:
            return models_cache["data"]
        try:
            data = llm.models()
        except LLMError as exc:
            raise HTTPException(502, exc.public_message) from exc
        models_cache.update(at=time.time(), data=data)
        return data

    @app.get("/api/cases")
    def list_cases(
        status: str | None = None,
        owner: str | None = None,
        channel: str | None = None,
        duplicates: bool = False,
        include_merged: bool = False,
    ) -> list[dict]:
        return desk.list_cases(status, owner, channel, duplicates, include_merged)

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: str) -> dict:
        return desk.case_detail(case_id)

    def run_analysis(case_id: str, request: Request, body: AnalysisBody) -> dict:
        ai = desk.analyzer.run(case_id, who(request), body.force, body.rules_only)
        detail = desk.case_detail(case_id)
        detail["ai"] = {**detail["ai"], **ai}
        return detail

    @app.post("/api/cases/{case_id}/analysis")
    def analysis(case_id: str, request: Request, body: AnalysisBody | None = None) -> dict:
        """Explicit Run analysis / Regenerate. The only endpoint that can call the model."""
        return run_analysis(case_id, request, body or AnalysisBody())

    @app.post("/api/cases/{case_id}/draft")
    def legacy_draft(case_id: str, request: Request) -> dict:
        """Kept for compatibility: same as POST /analysis (cached when the evidence is unchanged)."""
        return run_analysis(case_id, request, AnalysisBody())

    @app.put("/api/cases/{case_id}/draft")
    def save_draft(case_id: str, body: DraftBody) -> dict:
        return desk.save_draft(case_id, body.body)

    @app.post("/api/cases/{case_id}/draft/check")
    def check_draft(case_id: str, body: DraftBody) -> dict:
        return {"flags": desk.check_body(case_id, body.body)}

    @app.post("/api/cases/{case_id}/decision")
    def decide(case_id: str, body: DecisionBody) -> dict:
        return desk.decide(
            case_id, body.role, body.action, body.note, body.counted_attempt, body.body
        )

    @app.post("/api/cases/{case_id}/score-recommendation")
    def score_recommendation(case_id: str, body: RoleBody) -> dict:
        return desk.record_score_recommendation(case_id, body.role)

    @app.post("/api/duplicates/{dup_id}/confirm")
    def confirm_duplicate(dup_id: int, body: RoleBody) -> dict:
        return desk.resolve_duplicate(dup_id, body.role, True)

    @app.post("/api/duplicates/{dup_id}/dismiss")
    def dismiss_duplicate(dup_id: int, body: RoleBody) -> dict:
        return desk.resolve_duplicate(dup_id, body.role, False)

    @app.post("/api/intake", status_code=201)
    def intake(body: IntakeRequest) -> dict:
        """Create a synthetic case (or add a message to one). No Canvas, no email."""
        return desk.intake(body)

    @app.get("/api/intake/examples")
    def intake_examples() -> list[dict]:
        return EXAMPLES

    @app.post("/api/demo/reset")
    def reset(confirm: bool = Query(False)) -> dict:
        """Restores the fixtures. Does NOT reset the AI budget (see `python -m app.tools`)."""
        if not confirm:
            raise HTTPException(400, "pass ?confirm=true to reset the demo data")
        desk.seed(reset=True)
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
