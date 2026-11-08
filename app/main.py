"""FastAPI app. Run with: uvicorn app.main:app --reload"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import RunManager, ToolRegistry, build_default_registry
from app.config import Settings
from app.events import TERMINAL, EventStore, InMemoryEventStore
from app.llm import LLM, LLMError, get_llm
from app.sandbox import SandboxRunner, get_runner

STATIC_DIR = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=2000)


class ApprovalRequest(BaseModel):
    approved: bool


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLM | None = None,
    store: EventStore | None = None,
    registry: ToolRegistry | None = None,
    runner: SandboxRunner | None = None,
) -> FastAPI:
    """App factory. Every dependency can be overridden (the tests do this)."""
    settings = settings or Settings.from_env()
    llm = llm or get_llm(settings)
    store = store or InMemoryEventStore()
    runner = runner or get_runner(settings)
    registry = registry or build_default_registry(runner)
    manager = RunManager(store, llm, registry, settings)

    app = FastAPI(title=settings.product_name)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict:
        """What the frontend needs: branding + which modes are active."""
        return {
            "product_name": settings.product_name,
            "product_tagline": settings.product_tagline,
            "llm_mode": "mock" if llm.mock else "vultr-inference",
            "model": settings.model or None,
            "sandbox": runner.name,
        }

    @app.get("/api/models")
    def models() -> dict:
        try:
            return llm.models()
        except (LLMError, OSError) as exc:  # OSError covers httpx connection failures
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/runs", status_code=201)
    def create_run(body: RunRequest) -> dict:
        run = manager.start(body.task)
        return {"id": run.id, "status": run.status}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return {"id": run.id, "task": run.task, "status": run.status}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        """Server-Sent Events. Replays the whole log, then streams new events until the
        run finishes. Supports Last-Event-ID so a browser reconnect doesn't duplicate."""
        if store.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        try:
            last_id = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            last_id = 0

        async def stream() -> AsyncIterator[str]:
            sent = last_id
            while True:
                # Read status BEFORE events so we never miss a final event.
                run = store.get_run(run_id)
                finished = run is None or run.status in TERMINAL
                for ev in store.events(run_id, after=sent):
                    sent = ev.id
                    yield f"id: {ev.id}\ndata: {json.dumps(ev.to_dict())}\n\n"
                if finished:
                    yield "event: end\ndata: {}\n\n"
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.15)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/runs/{run_id}/approve")
    def approve(run_id: str, body: ApprovalRequest) -> dict:
        if store.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        if not manager.approve(run_id, body.approved):
            raise HTTPException(409, "run is not waiting for approval")
        return {"ok": True, "approved": body.approved}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
