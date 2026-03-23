#!/bin/sh
# Render injects PORT at runtime; must listen on 0.0.0.0:$PORT for routing/health checks.
set -e
PORT="${PORT:-10000}"
echo "[scrappy] listening on 0.0.0.0:${PORT} (PYTHONUNBUFFERED=${PYTHONUNBUFFERED:-})"
exec gunicorn app:app \
  --bind "0.0.0.0:${PORT}" \
  --timeout 300 \
  --workers 1 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
