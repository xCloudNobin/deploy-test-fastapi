"""Health (liveness) and readiness endpoints.

``/health`` answers with the process's own liveness and never touches the
database. ``/ready`` performs a real ``SELECT 1`` against the configured
engine and returns 503 when the database is unavailable while the process
stays alive — a static "ready" marker is deliberately not used.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..database import database_available

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "app": request.app.state.settings.app_name,
    }


@router.get("/ready")
def ready(request: Request):
    try:
        database_available(request.app.state.engine)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "database": "error",
                "detail": str(exc),
            },
        )
    return {"status": "ready", "database": "ok"}
