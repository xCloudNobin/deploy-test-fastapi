#!/usr/bin/env bash
# Reproducible production verification for the FastAPI task board.
#
# Starts the REAL production process (uvicorn, not the dev server), exercises
# HTML + JSON API CRUD and negative tests against it over HTTP, restarts it
# on the SAME SQLite database to prove persistence survives an application
# restart, verifies database-unavailable readiness behavior, then cleans up.
#
# Usage:
#   scripts/verify.sh              # expects ./.venv (created if missing)
#   VENV=/path scripts/verify.sh   # custom venv, created if missing
#
# Exit codes: 0 = all checks passed, nonzero = a check failed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"

WORK="$(mktemp -d /tmp/taskboard-verify.XXXXXX)"
PIDFILE="$WORK/server.pid"
JAR="$WORK/cookies.txt"
LOG1="$WORK/server1.log"
LOG2="$WORK/server2.log"
LOG3="$WORK/server-fail.log"
DB="$WORK/taskboard.db"
FAILDIR="$WORK/db-failure"   # a directory, NOT a file: opened as a DB it fails

cleanup() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); printf 'ok   %s\n' "$*"; }
bad()  { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$*"; }

expect_status() { # label url expected method data...
  local label="$1" url="$2" expected="$3" method="$4"
  shift 4
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
    -X "$method" "$@" "$url" || true)
  if [ "$code" = "$expected" ]; then
    ok "$label ($code)"
  else
    bad "$label: expected $expected got $code"
  fi
}

pick_port() {
  "$PY" - <<'EOF'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
EOF
}

start_server() { # db_path pidfile logfile  -> echoes port
  local db_path="$1" pidfile="$2" logfile="$3"
  local port
  port="$(pick_port)"
  DATABASE_PATH="$db_path" PORT="$port" \
  SECRET_KEY="verify-$(date +%s)-$RANDOM-$RANDOM" \
  BUILD_MARKER="smoke-$port" \
  "$UVICORN" app.main:app --app-dir "$ROOT" \
    --host 127.0.0.1 --port "$port" --log-level info \
    >"$logfile" 2>&1 &
  echo $! > "$pidfile"
  echo "$port"
}

stop_server() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
}

wait_ready_http() { # port label logfile
  local port="$1" label="$2" logfile="${3:-}"
  local code=000
  for _ in $(seq 1 50); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/health" || true)
    [ "$code" = "200" ] && { ok "liveness /health 200 ($label)"; return 0; }
    sleep 0.2
  done
  bad "server did not answer /health (last code $code, $label)"
  [ -n "$logfile" ] && [ -f "$logfile" ] && tail -20 "$logfile" || true
  return 1
}

fetch_csrf() { # port -> echoes session CSRF token (and updates cookie jar)
  local port="$1"
  curl -s -b "$JAR" -c "$JAR" "http://127.0.0.1:$port/tasks/new" \
    | grep -o 'name="csrf_token" value="[^"]*"' \
    | sed 's/.*value="//; s/"$//' \
    | head -1 || true
}

# ---------------------------------------------------------------- bootstrap
if [ ! -x "$VENV/bin/python" ]; then
  echo "creating venv at $VENV"
  python3 -m venv "$VENV"
fi
echo "installing/refreshing dependencies"
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$VENV/bin/python" -r "$ROOT/requirements-dev.txt"
elif "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install --quiet -r "$ROOT/requirements-dev.txt"
else
  echo "ERROR: no uv and no pip available in $VENV" >&2
  exit 1
fi

printf '=== verify start: %s ===\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ------------------------------------------------------- phase 1: CRUD + errors
echo "--- phase 1: production start + CRUD + negatives (fresh DB)"
PORT1="$(start_server "$DB" "$PIDFILE" "$LOG1")"
wait_ready_http "$PORT1" "phase-1"

READY="$(curl -s "http://127.0.0.1:$PORT1/ready")"
case "$READY" in
  *'"status":"ready"'*|*'"status": "ready"'*) ok "readiness reports ready";;
  *) bad "readiness payload: $READY";;
esac

TOKEN="$(fetch_csrf "$PORT1")"
[ -n "$TOKEN" ] && ok "session csrf token acquired" || bad "csrf token missing"

INDEX="$(curl -s -b "$JAR" "http://127.0.0.1:$PORT1/")"
case "$INDEX" in
  *"smoke-$PORT1"*) ok "build marker rendered on index";;
  *) bad "build marker missing on index";;
esac

# HTML create project
resp=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/projects/new" \
  --data-urlencode "name=Smoke Project" \
  --data-urlencode "description=created over HTTP" \
  --data-urlencode "csrf_token=$TOKEN")
case "$resp" in
  303*) ok "HTML create project ($resp)";;
  *) bad "HTML create project: $resp";;
esac
PROJECT_URL="${resp#303 }"
PROJECT_ID="$(basename "$PROJECT_URL")"

# HTML create task inside the project
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/new" \
  --data-urlencode "title=Smoke Task" \
  --data-urlencode "description=over http" \
  --data-urlencode "status=todo" \
  --data-urlencode "project_id=$PROJECT_ID" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "303" ] && ok "HTML create task (303)" || bad "HTML create task: $resp"

DETAIL="$(curl -s -b "$JAR" "$PROJECT_URL")"
case "$DETAIL" in
  *"Smoke Task"*) ok "read: task listed on project page";;
  *) bad "task not listed on project page";;
esac

# discover the task id, then edit it
TASK_ID=$(curl -s -b "$JAR" "$PROJECT_URL" \
  | grep -o '/tasks/[0-9]\+/edit' | head -1 | sed 's#/tasks/##; s#/edit##' || true)
[ -n "$TASK_ID" ] && ok "discovered task id $TASK_ID" || bad "task id not found"
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/edit" \
  --data-urlencode "title=Smoke Task (updated)" \
  --data-urlencode "description=" \
  --data-urlencode "status=in_progress" \
  --data-urlencode "project_id=$PROJECT_ID" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "303" ] && ok "HTML update task (303)" || bad "HTML update task: $resp"

# HTML status change
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/status" \
  --data-urlencode "status=done" --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "303" ] && ok "HTML status change (303)" || bad "HTML status change: $resp"

# HTML delete task
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/delete" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "303" ] && ok "HTML delete task (303)" || bad "HTML delete task: $resp"

# HTML delete project leaves its task unassigned
PIDX=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"name\": \"delete-me-$RANDOM\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/projects" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"])')
TIDX=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"title\": \"orphan-me\", \"project_id\": $PIDX, \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"])')
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/projects/$PIDX/delete" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "303" ] && ok "HTML delete project (303)" || bad "HTML delete project: $resp"
ORPHAN=$(curl -s -b "$JAR" "http://127.0.0.1:$PORT1/api/tasks/$TIDX")
case "$ORPHAN" in
  *'"project_id":null'*|*'"project_id": null'*) ok "project delete sets task unassigned";;
  *) bad "task not unassigned after project delete: $ORPHAN";;
esac
curl -s -o /dev/null -b "$JAR" -c "$JAR" -X DELETE \
  -H "Content-Type: application/json" -d "{\"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks/$TIDX" || true

# ----------------------------------------------- persistence survivor (API)
CREATED=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"title\": \"PERSIST-$$-survivor\", \"status\": \"in_progress\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks")
SURVIVOR_ID=$(printf '%s' "$CREATED" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"])')
[ -n "$SURVIVOR_ID" ] && ok "API create task (survivor id=$SURVIVOR_ID)" || bad "API create returned no id"

LISTED=$(curl -s -H "Accept: application/json" "http://127.0.0.1:$PORT1/api/tasks?q=survivor")
case "$LISTED" in
  *"PERSIST-$$-survivor"*) ok "API read/search finds survivor";;
  *) bad "API search missing survivor";;
esac

UPD=$(curl -s -b "$JAR" -c "$JAR" -X PATCH \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"status\": \"done\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks/$SURVIVOR_ID")
case "$UPD" in
  *'"status":"done"'*|*'"status": "done"'*) ok "API update task (status=done)";;
  *) bad "API update failed: $UPD";;
esac

# API delete (of a throwaway) + 404 afterwards
THROW=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"title\": \"throwaway\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks")
THROW_ID=$(printf '%s' "$THROW" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"])')
expect_status "API delete task" "http://127.0.0.1:$PORT1/api/tasks/$THROW_ID" 204 DELETE \
  -H "Content-Type: application/json" -d "{\"csrf_token\": \"$TOKEN\"}"
expect_status "API 404 after delete" "http://127.0.0.1:$PORT1/api/tasks/$THROW_ID" 404 GET

# ------------------------------------------------------------- negatives
# malformed JSON (CSRF supplied by header so the JSON parser is under test)
expect_status "malformed JSON -> 422" "http://127.0.0.1:$PORT1/api/tasks" 422 POST \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" -d '{oops'
# missing title
expect_status "missing title -> 422" "http://127.0.0.1:$PORT1/api/tasks" 422 POST \
  -H "Content-Type: application/json" -d "{\"csrf_token\": \"$TOKEN\"}"
# invalid status
expect_status "invalid status -> 422" "http://127.0.0.1:$PORT1/api/tasks" 422 POST \
  -H "Content-Type: application/json" -d "{\"title\":\"x\",\"status\":\"warp\",\"csrf_token\": \"$TOKEN\"}"
# unknown project id
expect_status "unknown project -> 400" "http://127.0.0.1:$PORT1/api/tasks" 400 POST \
  -H "Content-Type: application/json" -d "{\"title\":\"x\",\"project_id\":999999,\"csrf_token\": \"$TOKEN\"}"
# missing csrf token
expect_status "missing CSRF -> 403" "http://127.0.0.1:$PORT1/api/tasks" 403 POST \
  -H "Content-Type: application/json" -d "{\"title\":\"x\"}"
# wrong csrf token
expect_status "wrong CSRF -> 403" "http://127.0.0.1:$PORT1/api/tasks" 403 POST \
  -H "Content-Type: application/json" -H "X-CSRF-Token: nope" -d "{\"title\":\"x\"}"
# unknown task
expect_status "unknown task -> 404" "http://127.0.0.1:$PORT1/api/tasks/999999" 404 GET
# invalid status filter
expect_status "invalid status filter -> 400" "http://127.0.0.1:$PORT1/api/tasks?status=nope" 400 GET
# HTML validation + CSRF negatives
expect_status "HTML empty name -> 400" "http://127.0.0.1:$PORT1/projects/new" 400 POST \
  --data-urlencode "name=" --data-urlencode "csrf_token=$TOKEN"
expect_status "HTML invalid status -> 400" "http://127.0.0.1:$PORT1/tasks/new" 400 POST \
  --data-urlencode "title=x" --data-urlencode "status=bogus" --data-urlencode "csrf_token=$TOKEN"
expect_status "HTML missing CSRF -> 403" "http://127.0.0.1:$PORT1/tasks/new" 403 POST \
  --data-urlencode "title=x"
# unknown HTML project page (nested route) -> 404 error page
expect_status "unknown project page -> 404" "http://127.0.0.1:$PORT1/projects/999999" 404 GET
# malformed JSON error body sanity
ERRBODY="$(curl -s -b "$JAR" -X POST -H "Content-Type: application/json" \
  -H "Accept: application/json" -H "X-CSRF-Token: $TOKEN" -d '{oops' \
  "http://127.0.0.1:$PORT1/api/tasks")"
case "$ERRBODY" in
  *"Validation error"*) ok "malformed JSON error body sane";;
  *) bad "unexpected error body: $ERRBODY";;
esac

echo "--- phase 2: graceful stop (SIGTERM), restart on SAME SQLite path"
stop_server
sleep 0.3
echo "--- phase 3: restart persistence check"
PORT2="$(start_server "$DB" "$PIDFILE" "$LOG2")"
wait_ready_http "$PORT2" "phase-3"
FOUND=$(curl -s -H "Accept: application/json" \
  "http://127.0.0.1:$PORT2/api/tasks/$SURVIVOR_ID")
case "$FOUND" in
  *"PERSIST-$$-survivor"*) ok "persistence: survivor task survived restart";;
  *) bad "persistence FAILED: survivor missing after restart";;
esac
ALL=$(curl -s -H "Accept: application/json" "http://127.0.0.1:$PORT2/api/tasks")
COUNT=$(printf '%s' "$ALL" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))')
case "$COUNT" in
  5) ok "idempotent schema init: seed not duplicated (5 tasks)";;
  *) bad "seed duplicated or lost: task count=$COUNT";;
esac
stop_server

echo "--- phase 4: dependency failure (database unavailable)"
mkdir -p "$FAILDIR"   # a directory opened as a DB file must fail to connect
PORT3="$(start_server "$FAILDIR" "$PIDFILE" "$LOG3")"
wait_ready_http "$PORT3" "phase-4"
expect_status "liveness /health still 200" "http://127.0.0.1:$PORT3/health" 200 GET
expect_status "readiness fails -> 503" "http://127.0.0.1:$PORT3/ready" 503 GET
expect_status "page routes degrade -> 503" "http://127.0.0.1:$PORT3/" 503 GET
expect_status "api degrades -> 503 json" "http://127.0.0.1:$PORT3/api/tasks" 503 GET
stop_server

echo
printf '=== verify summary: %s passed, %s failed ===\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]