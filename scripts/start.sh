#!/usr/bin/env bash
# Production ASGI start: runs uvicorn (the FastAPI production server) with
# logs on stdout/stderr and a configurable bind address/port.
#
# Usage:
#   DATABASE_PATH=/var/lib/taskboard/taskboard.db \
#   SECRET_KEY="$(cat secret.txt)" \
#   scripts/start.sh
#
# Generate SECRET_KEY once with:
#   python -c "import secrets; print(secrets.token_hex(24))"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"

exec "$PY" -m uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --log-level "$LOG_LEVEL"