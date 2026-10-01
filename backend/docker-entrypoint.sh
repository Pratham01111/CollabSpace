#!/bin/sh
# Bring the schema up to date, then serve. Safe on every start: Alembic only
# applies migrations that have not run yet.
set -e

alembic upgrade head

# Production-style: no --reload. Worker count comes from WEB_CONCURRENCY
# (read by uvicorn itself). Several workers are fine because realtime events
# and presence go through Redis, not process memory.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
