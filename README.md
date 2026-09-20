# Task Board (FastAPI)

A compact project/task board built with FastAPI, SQLAlchemy and SQLite:
project grouping, task CRUD, statuses, search/filter, a small JSON API, and
real persistent storage. Designed as a production-shaped FastAPI deployment
test with proper health, readiness, validation, and reproducible automated
checks.

## Features

- **Projects and tasks** — create, read, update, delete; tasks are grouped
  under projects (deleting a project leaves its tasks *unassigned*).
- **Statuses** — `todo`, `in_progress`, `done` via inline dropdown
  (client-side autosubmit with a no-JS fallback) or the edit form.
- **Search / filter** — free-text match on title/description plus a status
  filter, on the board and per-project pages.
- **SQLite + SQLAlchemy persistence** — deterministic, idempotent schema
  initialization (`Base.metadata.create_all`) with repeatable seed data;
  parameterized queries everywhere and Jinja autoescaping on all output;
  CSRF tokens on every state-changing request.
- **Health vs readiness** — `/health` is a pure liveness probe (never touches
  the database); `/ready` performs a real `SELECT 1` and returns `503` when
  the database is unavailable while the process stays alive.
- **JSON API** — `/api/tasks` and `/api/projects` for scripting and the
  verify script, with malformed-JSON, validation, and not-found handling
  (OpenAPI docs at `/docs`).
- **Release marker** — non-sensitive `VERSION`/`BUILD_MARKER` rendered in the
  footer to identify the deployed revision.

## Requirements

- Python 3.11+ (pinned via `.python-version`)
- SQLite (bundled with CPython)

## Install (repo-local virtualenv)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # runtime + pytest
# or with uv:  uv venv && uv pip install -r requirements-dev.txt
```

## Configure

Copy `.env.example` and adjust, or export variables in the process
environment. All values are optional; the safe local defaults are shown:

| Variable          | Default                 | Purpose                                              |
| ----------------- | ----------------------- | ---------------------------------------------------- |
| `PORT`            | `8000`                  | Listen port                                          |
| `HOST`            | `0.0.0.0`               | Bind address (required by platforms; do not change)  |
| `DATABASE_PATH`   | `./data/taskboard.db`   | Persistent SQLite file                               |
| `SECRET_KEY`      | random at boot          | Session/CSRF signing key                             |
| `BUILD_MARKER`    | `VERSION` file          | Non-sensitive revision marker shown in the UI        |
| `LOG_LEVEL`       | `info`                  | Uvicorn log level                                    |

> **Persistence is the operator's job.** The default `./data/taskboard.db`
> lives inside the release checkout and is wiped on redeploy. In production
> always set `DATABASE_PATH` to a path **outside** the checkout (a mounted
> volume), e.g. `/var/lib/taskboard/taskboard.db`. Generate `SECRET_KEY` once
> with `python -c "import secrets; print(secrets.token_hex(24))"` and keep it
> stable so sessions/CSRF tokens survive restarts.

## Run

Development server (local debugging only — not production):

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Production ASGI process (`scripts/start.sh`, logs to stdout/stderr):

```bash
DATABASE_PATH=/var/lib/taskboard/taskboard.db \
SECRET_KEY="$(cat secret.txt)" \
PORT=8000 \
./scripts/start.sh                    # 1 worker; WEB_CONCURRENCY to scale
# equivalent direct command:
# .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --workers 2
```

Set or regenerate the release marker before shipping:

```bash
./scripts/build.sh                    # writes VERSION (BUILD_MARKER, git SHA, or date)
```

## Schema and seed behavior

Schema is created idempotently at startup via SQLAlchemy
(`CreateTableIfNotExists`) with CHECK constraints on status and non-blank
titles, plus `ON DELETE SET NULL` for project deletion. Seed data (two
projects, four tasks) is inserted **only when the tasks table is empty**, with
fixed values, so re-initialization never duplicates and databases are
reproducible. To refresh from scratch, stop the app and delete the database
file (not automatic). SQLite runs with WAL mode and foreign keys enabled.

## Endpoints

HTML:

- `GET /` — board: projects with grouped tasks, `?q=` and `?status=` filters
- `GET /projects/<id>` — project detail (nested route) with the same filters
- `GET/POST /projects/new`, `GET/POST /projects/<id>/edit`,
  `POST /projects/<id>/delete`
- `GET/POST /tasks/new`, `GET/POST /tasks/<id>/edit`, `POST /tasks/<id>/status`,
  `POST /tasks/<id>/delete`

JSON API (CSRF token required in the JSON body or `X-CSRF-Token` header):

- `GET /api/tasks?q=&status=`, `POST /api/tasks`,
  `GET/PATCH/DELETE /api/tasks/<id>`
- `GET /api/projects`, `POST /api/projects`

Health:

- `GET /health` — `{"status":"ok","app":"deploy-test-fastapi"}` (liveness)
- `GET /ready` — `{"status":"ready","database":"ok"}` or `503` with the error
  detail when the database is unavailable (readiness)

Error conventions (documented in the code too):

- body validation → `422` (FastAPI/Pydantic structured `detail`)
- semantic errors (unknown project, invalid filter) → `400` with
  `{"errors": {...}}`
- malformed JSON → `422`
- missing/wrong CSRF token → `403`
- unknown resource → `404`
- database unavailable → `503` (pages render an HTML error page for browsers;
  `/api/*` returns JSON). Liveness stays `200`.

## Public demo limitations

This app has **no authentication** — it is a single-board collaborative demo.
All visitors can create/edit/delete everything; do not put private data on a
public deployment. CSRF tokens are tied to the per-visitor session cookie but
are not a substitute for login. A public demo should also use a persistent
`DATABASE_PATH` volume or expect all data to reset on redeploy.

## Tests and verification

```bash
.venv/bin/python -m pytest -q        # unit/integration suite (33 tests)
./scripts/verify.sh                  # production HTTP CRUD + errors + restart persistence + DB readiness
```

`scripts/verify.sh` starts the **real production uvicorn process** on a
temporary port with an isolated temporary SQLite database, then:

1. exercises HTML and JSON create/read/update/delete plus search/filter and
   project-delete-orphans-tasks,
2. runs negative tests (malformed JSON, missing title, invalid status,
   unknown project, missing/wrong CSRF, missing resources, invalid filters),
3. gracefully restarts the server (SIGTERM) on the **same database path** and
   proves a record survives, with idempotent schema init (seed not doubled),
4. starts a second instance whose `DATABASE_PATH` is unusable and verifies
   `/health` stays `200` while `/ready` and data routes fail with `503`,
5. removes the temporary database and port.

No simulated output: every check is a real HTTP request against the running
production process. Build markers, ports, and database paths are ephemeral
and isolated per run.

## License

MIT — see [`LICENSE`](LICENSE). This is a fresh application fixture created
for the xCloud application-compatibility suite.