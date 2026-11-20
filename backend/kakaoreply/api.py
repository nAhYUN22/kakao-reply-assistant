"""Loopback-only synthetic control API; no live transport is constructed."""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .domain import BINDING_ID, ROOT
from .engine import Engine
from .storage import Journal


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartInput(StrictInput):
    mode: Literal["auto", "draft"]


class MessageInput(StrictInput):
    text: str = Field(min_length=1, max_length=10000)
    origin: Literal["partner", "owner", "unknown"]
    event_id: str | None = Field(default=None, min_length=1, max_length=100)
    binding_id: str = Field(default=BINDING_ID, min_length=1, max_length=100)


class AdvanceInput(StrictInput):
    seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)


class EmptyInput(StrictInput):
    pass


def create_app(db_path: str | None = None, engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = engine or Engine(Journal(db_path or os.getenv("KAKAOREPLY_DB_PATH", str(ROOT / "data/mock.sqlite"))))
        application.state.token = secrets.token_urlsafe(32)
        try:
            yield
        finally:
            application.state.engine.close()

    application = FastAPI(title="KakaoReply mock API", version=__version__, lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = {f"{host}{port}" for host in ("localhost", "127.0.0.1") for port in ("", ":8765", ":5173")}
    allowed_origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8765, 5173)}

    @application.middleware("http")
    async def boundary(request: Request, call_next):
        if request.headers.get("host", "").lower() not in allowed_hosts:
            return JSONResponse({"detail": "INVALID_HOST"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            return JSONResponse({"detail": "INVALID_ORIGIN"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "CROSS_SITE_REQUEST"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if request.url.path not in {"/api/health", "/api/session"}:
                provided = request.headers.get("x-session-token", "")
                if not secrets.compare_digest(provided, request.app.state.token):
                    return JSONResponse({"detail": "INVALID_SESSION"}, status_code=401)
            if request.method == "POST" and request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON_REQUIRED"}, status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse({"detail": "INVALID_INPUT"}, status_code=422)

    @application.exception_handler(ValueError)
    async def invalid_operation(request, error):
        # Engine errors are finite reason codes; never reflect arbitrary exception text.
        return JSONResponse({"detail": "OPERATION_REJECTED"}, status_code=409)

    @application.get("/api/health")
    async def health():
        return {"status": "ok", "transport": "mock", "version": __version__}

    @application.get("/api/session")
    async def session(request: Request):
        return {"token": request.app.state.token}

    @application.get("/api/state")
    async def state(request: Request):
        return request.app.state.engine.state()

    @application.post("/api/simulator/start")
    async def start(body: StartInput, request: Request):
        return await request.app.state.engine.start(body.mode)

    @application.post("/api/simulator/messages")
    async def message(body: MessageInput, request: Request):
        return await request.app.state.engine.message(**body.model_dump())

    @application.post("/api/simulator/advance")
    async def advance(body: AdvanceInput, request: Request):
        return await request.app.state.engine.advance(body.seconds)

    @application.post("/api/runtime/pause")
    async def pause(body: EmptyInput, request: Request):
        return await request.app.state.engine.pause()

    @application.get("/api/jobs/{job_id}")
    async def detail(job_id: str, request: Request):
        try:
            return request.app.state.engine.detail(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="JOB_NOT_FOUND") from None

    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        application.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return application


app = create_app()
