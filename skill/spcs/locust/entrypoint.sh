#!/usr/bin/env bash
# SPCS entrypoint for the locust container.
#
# Two modes:
#   LOCUST_HEADLESS=0 (default) — start web UI on port 8089; user drives it
#                                 from the ingress URL in their browser.
#   LOCUST_HEADLESS=1          — one-shot run for LOCUST_RUN_TIME then exit.

set -euo pipefail

: "${LOCUST_HOST:?LOCUST_HOST must be set (e.g. http://dashboard:3000)}"

export WAREHOUSE="${WAREHOUSE:-${LOCUST_WAREHOUSE:-interactive}}"
export SCALE="${SCALE:-${LOCUST_SCALE:-100}}"

USERS="${LOCUST_USERS:-10}"
SPAWN="${LOCUST_SPAWN:-5}"
WEB_PORT="${LOCUST_WEB_PORT:-8089}"
HEADLESS="${LOCUST_HEADLESS:-0}"
RUN_TIME="${LOCUST_RUN_TIME:-5m}"

echo "[entrypoint] target=$LOCUST_HOST warehouse=$WAREHOUSE scale=$SCALE users=$USERS spawn=$SPAWN headless=$HEADLESS"

if [[ "$HEADLESS" == "1" || "$HEADLESS" == "true" ]]; then
  exec uv run --no-sync locust -f /app/locustfile.py \
    --host "$LOCUST_HOST" \
    --headless \
    --only-summary \
    --loglevel INFO \
    -u "$USERS" \
    -r "$SPAWN" \
    -t "$RUN_TIME"
fi

exec uv run --no-sync locust -f /app/locustfile.py \
  --host "$LOCUST_HOST" \
  --web-host 0.0.0.0 \
  --web-port "$WEB_PORT" \
  -u "$USERS" \
  -r "$SPAWN"
