#!/bin/sh
# Container entrypoint for the Railway web service.
#
# Runs alembic migrations and the idempotent superuser seed on every
# container start, then execs uvicorn. `set -e` aborts before uvicorn
# if either preparatory step fails, so the container will not serve
# traffic against an out-of-date schema.

set -e

echo "[entrypoint] applying database migrations"
alembic upgrade head

echo "[entrypoint] seeding superuser (idempotent)"
python -m app.scripts.create_superuser

echo "[entrypoint] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
