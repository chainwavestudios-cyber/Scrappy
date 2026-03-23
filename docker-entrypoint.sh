#!/bin/sh
# Render injects PORT at runtime; must listen on 0.0.0.0:$PORT for routing/health checks.
set -e
PORT="${PORT:-10000}"
echo "[scrappy] listening on 0.0.0.0:${PORT} (PYTHONUNBUFFERED=${PYTHONUNBUFFERED:-})"
# Single worker: Playwright must not run concurrently in one process pool.
# graceful-timeout: allow in-flight scrape threads to finish on SIGTERM (Render deploy/restart).
exec gunicorn app:app \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 \
  --threads 1 \
  --timeout 300 \
  --graceful-timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
