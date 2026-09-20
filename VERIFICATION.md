# Verification

Verification of the FastAPI task-board implementation on the
`xCloudNobin/deploy-test-fastapi` repository. This records what was actually
run locally; **no live xCloud deployment was performed**.

- Date (UTC): 2026-09-20
- Repository: `xCloudNobin/deploy-test-fastapi` (public, created by this work)
- Branch: `feat/taskboard`
- Head commit: `ef861595d02ec93fac35866f3189a134229596c1` (implementation);
  branch head `feat/taskboard` adds only this verification note.
- Status: **local-verified** (NOT **deployment-verified**)

## Environment (local only)

| Component | Version |
| --------- | ------- |
| Python    | 3.11.15 (repo-local `.venv`) |
| FastAPI   | 0.141.1 |
| Starlette | 1.6.0 |
| SQLAlchemy| 2.0.54 |
| Pydantic  | 2.13.5 |
| uvicorn   | 0.53.0 |
| pytest    | 9.1.1 |
| SQLite    | 3.53.1 (stdlib `sqlite3`) |
| Process   | real uvicorn ASGI (bind `127.0.0.1:<random-port>` for checks) |

No `apt`, no global interpreter changes; dependencies installed only inside
the repo-local `.venv`. Each test/verify run used an isolated temporary
SQLite database and unique ephemeral ports, cleaned up afterwards. `data/`,
`.env`, and the venv are gitignored; no secrets are committed.

## Commands and results

### Unit/integration test suite

```bash
.venv/bin/python -m pytest -q
```

Result: `33 passed in 0.68s` (exit 0).

Coverage includes: health/liveness, readiness success and failure (unusable
database), homepage grouping + seed rendering, build marker, nested routes
and static assets, project/task CRUD via forms and JSON API, search/status
filters, validation errors (blank title/name, invalid status, unknown
project), malformed JSON, missing/wrong CSRF token, not-found (404),
unavailable-database degradation (503), deterministic and idempotent schema
with non-duplicated seed, project-delete-orphans-tasks (ON DELETE SET NULL),
and data persistence across a fresh app/engine bound to the same SQLite file.

### Production process verification

```bash
./scripts/verify.sh
```

Result: `39 passed, 0 failed` (exit 0). The script starts the **real
`uvicorn` production process** (not the dev server) and verifies over live
HTTP:

- Liveness `/health` → `200`; readiness `/ready` → `200` on a healthy DB.
- HTML create project → `303`; create task → `303`; read on project page;
  edit task; change status; delete task; delete project; project deletion
  sets its task `project_id` to null.
- JSON API create/read/search/update/delete, delete-then-404; status+text
  filters.
- Negative tests: malformed JSON → `422`; missing title → `422`; invalid
  status → `422`; unknown project → `400`; missing CSRF → `403`; wrong
  CSRF → `403`; unknown task → `404`; invalid status filter → `400`; HTML
  empty name and invalid status → `400`; HTML missing CSRF → `403`;
  unknown project page → `404`.
- Build marker (`BUILD_MARKER=smoke-<port>`) rendered on `/`.
- **Persistence:** process gracefully stopped (SIGTERM), restarted on the
  **same SQLite path**, survivor record still present, seed not duplicated
  (idempotent init, 5 tasks = 4 seed + 1 survivor).
- **Dependency failure:** second instance started with an unusable
  `DATABASE_PATH` (a directory); liveness stayed `200`, readiness and data
  routes/PAGE routes → `503`.
- Full cleanup of temporary database, logs, cookie jar, and ports.

### Production start wrapper

```bash
DATABASE_PATH=<tmp>/start.db SECRET_KEY=starttest PORT=37124 BUILD_MARKER=start-marker ./scripts/start.sh
```

Verified: uvicorn boots on `0.0.0.0:37124`; `/health` → `200`
(`{"status":"ok","app":"deploy-test-fastapi"}`); `/ready` → `200`
(`{"status":"ready","database":"ok"}`); graceful SIGTERM shutdown.

### Release marker

```bash
./scripts/build.sh   # writes VERSION; BUILD_MARKER env / git SHA / date stamps
```

Validated: script emits a marker and the UI footer renders it
(`build-20260920-<time>` when invoked outside git, git SHA otherwise).

## Security / license notes

- MIT licensed (`LICENSE`); fresh fixture, no upstream source to attribute.
- No authentication (demo scope): all visitors may mutate data; README warns
  not to host private data and to use a persistent `DATABASE_PATH` volume.
- CSRF tokens are bound to the signed session cookie on all state-changing
  requests (form, JSON body, or `X-CSRF-Token` header).
- All queries are parameterized via SQLAlchemy; template output is
  autoescaped (no `|safe` used on user data).
- Logs go to uvicorn stdout/stderr without credentials. `.env` and `data/`
  are gitignored; only `.env.example` with safe placeholder values is
  committed.

## Limitations

- **Live xCloud deployment NOT run.** The platform-category deployment and
  external checks still need to be executed at the exact candidate commit
  before marking this `deployment-verified`.
- Restart/deploy persistence is proven locally (same checkout, same DB path);
  redeploy volume behavior depends on the platform mounting
  `DATABASE_PATH` outside the release directory.
- The app uses a single SQLite file with WAL; a shared/external database is
  not required by this fixture.