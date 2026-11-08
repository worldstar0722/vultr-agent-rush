"""FastAPI app. Run with: uvicorn app.main:app --reload"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Settings
from app.llm import LLM, LLMError, get_llm
from app.service import Desk, DeskError

STATIC_DIR = Path(__file__).parent / "static"


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


class ImportBody(BaseModel):
    id: str
    channel: str
    direction: str = "inbound"
    author: str
    role: str = "student"
    student: str
    assignment: str
    ts: str
    text: str
    case_id: str | None = None
    owner: str | None = None


def create_app(settings: Settings | None = None, *, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    llm = llm or get_llm(settings)
    desk = Desk(settings, llm)
    app = FastAPI(title=settings.product_name)

    @app.exception_handler(DeskError)
    async def desk_error(_: Any, exc: DeskError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "product_name": settings.product_name,
            "product_tagline": settings.product_tagline,
            # Only claim Vultr inference when a key is configured.
            "llm_mode": "mock" if llm.mock else "vultr-inference",
            "model": settings.model or None,
            "banner": "Synthetic demo data. No real student records. "
            "No grades are changed and no messages are sent.",
        }

    @app.get("/api/models")
    def models() -> dict:
        try:
            return llm.models()
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from exc

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

    @app.post("/api/cases/{case_id}/draft")
    def generate_draft(case_id: str) -> dict:
        return desk.generate_draft(case_id)

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

    @app.post("/api/messages/import", status_code=201)
    def import_message(body: ImportBody) -> dict:
        return {"case_id": desk.import_message(body.model_dump())}

    @app.post("/api/demo/reset")
    def reset(confirm: bool = Query(False)) -> dict:
        if not confirm:
            raise HTTPException(400, "pass ?confirm=true to reset the demo data")
        desk.seed(reset=True)
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
