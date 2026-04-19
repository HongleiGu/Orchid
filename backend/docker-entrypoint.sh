#!/bin/sh
# Runs DB migrations then starts the app.
# Docker waits for Postgres to be healthy before this runs (see compose healthcheck).
set -e

cd /app
echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head
echo "[entrypoint] Migrations done. Starting uvicorn..."

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
