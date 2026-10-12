#!/bin/sh
# Bring the schema up to date, then serve. Safe on every start: Alembic only
# applies migrations that have not run yet.
set -e

alembic upgrade head

# Production-style: no --reload. Worker count comes from WEB_CONCURRENCY
# (read by uvicorn itself). Several workers are fine because realtime events
# and presence go through Redis, not process memory.
#
# PORT is injected by hosts such as Railway; 8000 otherwise. HOST defaults to
# "::", which on Linux is dual-stack: every IPv4 address (what 0.0.0.0 would
# give) plus IPv6, which Railway's private network may require.
exec uvicorn app.main:app \
  --host "${HOST:-::}" \
  --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
