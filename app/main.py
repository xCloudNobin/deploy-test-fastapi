"""FastAPI application factory and ASGI entry point.

Production process (see README):

    DATABASE_PATH=/var/lib/taskboard/taskboard.db \\
    SECRET_KEY="$(cat secret.txt)" \\
    PORT=8000 \\
    .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"

The module-level ``app`` is the ASGI entry point (``app.main:app``). The
database is initialized on startup but a failed database only degrades
readiness/data routes — ``/health`` (liveness) stays green.
"""

import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import OperationalError
from starlette.middleware.sessions import SessionMiddleware

from .config import BASE_DIR, Settings, get_settings
from .database import (
    create_db_engine,
    create_session_factory,
    database_available,
    init_db,
)
from .models import STATUSES, Base

logger = logging.getLogger("taskboard.app")

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Maximum number of database rows to return for list queries.
MAX_FILTER_LENGTH = 100


def resolve_build_marker(settings: Settings) -> str:
    if settings.build_marker:
        return settings.build_marker.strip()
    version_file = BASE_DIR / "VERSION"
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return "dev"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=resolve_build_marker(settings),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    secret_key = settings.secret_key or secrets.token_hex(24)
    app.add_middleware(
        SessionMiddleware, secret_key=secret_key, max_age=60 * 60 * 24 * 7
    )

    database_path = settings.resolved_database_path
    engine = create_db_engine(database_path)
    session_factory = create_session_factory(engine)

    build_marker = resolve_build_marker(settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.build_marker = build_marker
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.max_content_length = settings.max_content_length

    try:
        init_db(
            engine, database_path, ensure_data_dir=settings.database_path_is_default
        )
    except Exception as exc:  # pragma: no cover - depends on filesystem state
        logger.warning("database not available at startup: %s", exc)

    mount_assets(app)
    register_error_handlers(app)

    from .routers import api, health, pages

    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(pages.router)

    return app


def mount_assets(app: FastAPI) -> None:
    if (STATIC_DIR / "app.css").exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static",
        )


def _wants_json(request: Request) -> bool:
    best = request.headers.get("accept", "*/*").split(",")[0].strip()
    if "application/json" in best:
        return True
    if "/html" in best or "text/html" in best:
        return False
    return request.url.path.startswith(("/api/", "/health", "/ready"))


def _error_content(request: Request, status_code: int, content: dict):
    if _wants_json(request):
        return JSONResponse(status_code=status_code, content=content)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "build_marker": request.app.state.build_marker,
            "code": status_code,
            "title": content.get("error", "Error"),
            "message": content.get("detail", "Request failed."),
        },
        status_code=status_code,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            content = dict(detail)
            content.setdefault("status", "error")
        else:
            content = {"status": "error", "error": "Error", "detail": str(detail)}
        return _error_content(request, exc.status_code, content)

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError):
        logger.error("database unavailable: %s", exc)
        return _error_content(
            request,
            503,
            {
                "status": "unavailable",
                "error": "Database is unavailable. Check the persistent database path.",
                "detail": str(exc),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "error": "Validation error",
                "detail": exc.errors(),
            },
        )


app = create_app()

__all__ = ["app", "create_app", "STATUSES", "Base"]
