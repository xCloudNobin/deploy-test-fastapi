"""Shared FastAPI dependencies: database sessions and CSRF protection."""

import hmac
import secrets

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session as SessionType


def get_db(request: Request):
    """Yield a database session bound to the current request; always closed.

    The session factory lives on ``request.app.state`` so tests can spin up
    isolated apps against their own SQLite files.
    """
    factory = request.app.state.session_factory
    db: SessionType = factory()
    try:
        yield db
    finally:
        db.close()


def ensure_csrf_token(request: Request) -> str:
    """Return (creating if needed) the per-session CSRF token."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf_token"] = token
    return token


async def require_csrf(request: Request) -> None:
    """Enforce a CSRF token on state-changing requests.

    The token signs the visitor's session cookie (via
    ``SessionMiddleware``) and must be supplied in the ``X-CSRF-Token``
    header, the JSON body (``csrf_token``), or form data — whichever matches
    the request content type.
    """
    expected = request.session.get("csrf_token")
    if not expected:
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

    supplied = request.headers.get("X-CSRF-Token")
    if not supplied:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                raw = await request.json()
            except Exception:
                raw = {}
            supplied = raw.get("csrf_token") if isinstance(raw, dict) else None
        else:
            try:
                form = await request.form()
            except Exception:
                form = {}
            supplied = form.get("csrf_token")

    if not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")


def flash(request: Request, message: str, category: str = "success") -> None:
    flashes = request.session.get("_flashes", [])
    flashes.append({"category": category, "message": message})
    request.session["_flashes"] = flashes


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("_flashes", [])
