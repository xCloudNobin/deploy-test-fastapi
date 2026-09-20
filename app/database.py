"""Database engine, session factory and idempotent initialization.

The engine is created lazily at application startup; a failed database does
not prevent the process from booting so the liveness probe stays up while
readiness reports the dependency failure.
"""

import logging
import threading
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from . import seed
from .models import Base

logger = logging.getLogger("taskboard.db")

# Serialize one-time schema/seed initialization so concurrent workers and
# threads never double-seed a fresh database.
_init_lock = threading.Lock()


def create_db_engine(database_path: str):
    """Build a SQLAlchemy engine for the given SQLite path.

    ``check_same_thread=False`` allows FastAPI's thread pool to share the
    connection pool; WAL + foreign keys pragmas are applied per-connection.
    """
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine


def create_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine, database_path: str, ensure_data_dir: bool) -> None:
    """Create the on-disk location, run idempotent schema init and seed.

    Safe to run on an already-initialized database: ``create_all`` is a no-op
    and seed data is inserted only when the tasks table is empty.
    """
    with _init_lock:
        if ensure_data_dir:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(engine)
        _seed_if_empty(engine)
        logger.info("database initialized at %s", database_path)


def _seed_if_empty(engine) -> None:
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        count = session.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
        if count == 0:
            for project in seed.SEED_PROJECTS:
                project_row = seed_project(session, project)
                session.flush()
                for title, description, status in project["tasks"]:
                    session.execute(
                        text(
                            "INSERT INTO tasks (project_id, title, description, status)"
                            " VALUES (:pid, :title, :desc, :status)"
                        ),
                        {
                            "pid": project_row.id,
                            "title": title,
                            "desc": description,
                            "status": status,
                        },
                    )
            session.commit()


def seed_project(session, project: dict):
    from .models import Project

    row = Project(name=project["name"], description=project["description"])
    session.add(row)
    session.flush()
    return row


def database_available(engine) -> bool:
    """Readiness probe: a real ``SELECT 1`` against the configured engine."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
