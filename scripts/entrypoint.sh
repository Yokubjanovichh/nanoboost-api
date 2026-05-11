#!/bin/sh
# Container entrypoint for the Railway web service.
#
# Migrations and the idempotent superuser seed are managed exclusively
# via railway.toml's preDeployCommand. That runs in a fresh container
# BEFORE this entrypoint executes, so by the time we exec uvicorn the
# schema is already at head. Do NOT add `alembic upgrade head` here.

set -e

echo "[entrypoint] starting uvicorn (migrations applied by Railway preDeployCommand)"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
