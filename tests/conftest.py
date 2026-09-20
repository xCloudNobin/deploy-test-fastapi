"""Shared test fixtures.

A single real SQLite database (isolated temp file) is shared across the
session via the module-level ``app``, mirroring the production layout. The
"restart" persistence test rebuilds a fresh app against the SAME database
path to prove data survives a process-equivalent restart.
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TMP = Path(tempfile.mkdtemp(prefix="taskboard-tests-"))
os.environ["DATABASE_PATH"] = str(_TMP / "tests.db")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["BUILD_MARKER"] = "test-marker"
os.environ["HOST"] = "0.0.0.0"

from app.config import Settings  # noqa: E402
from app.main import app, create_app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def csrf(client):
    """Return a valid session-scoped CSRF token for the main client."""
    r = client.get("/tasks/new")
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert match is not None, "csrf token not rendered"
    return match.group(1)


@pytest.fixture()
def restarted_app():
    """A fresh app instance bound to the same shared database file."""
    fresh = create_app(Settings(database_path=str(_TMP / "tests.db")))
    with TestClient(fresh) as c:
        yield c


@pytest.fixture()
def broken_db_app():
    """An app whose DATABASE_PATH cannot be opened (a directory, not a file)."""
    broken_dir = Path(tempfile.mkdtemp(prefix="taskboard-broken-"))
    broken = create_app(Settings(database_path=str(broken_dir)))
    with TestClient(broken) as c:
        yield c
