#!/usr/bin/env bash
# SPCS entrypoint for the locust container.
#
# Two modes:
#   LOCUST_HEADLESS=0 (default) — start web UI on port 8089; user drives it.
#   LOCUST_HEADLESS=1           — one-shot run for LOCUST_RUN_TIME then exit.

set -uo pipefail

: "${LOCUST_HOST:?LOCUST_HOST must be set (e.g. http://benchmark-api:3000)}"

export WAREHOUSE="${WAREHOUSE:-${LOCUST_WAREHOUSE:-both}}"
export BENCHMARK_QUERIES_DIR="${BENCHMARK_QUERIES_DIR:-/app/test}"

USERS="${LOCUST_USERS:-10}"
SPAWN="${LOCUST_SPAWN:-5}"
WEB_PORT="${LOCUST_WEB_PORT:-8089}"
HEADLESS="${LOCUST_HEADLESS:-0}"
RUN_TIME="${LOCUST_RUN_TIME:-5m}"

echo "[entrypoint] target=$LOCUST_HOST warehouse=$WAREHOUSE users=$USERS spawn=$SPAWN headless=$HEADLESS queries=$BENCHMARK_QUERIES_DIR"

if [[ "$HEADLESS" == "1" || "$HEADLESS" == "true" ]]; then
  uv run --no-sync locust -f /app/locustfile.py \
    --host "$LOCUST_HOST" \
    --headless \
    --only-summary \
    --csv /tmp/locust_stats \
    --loglevel INFO \
    -u "$USERS" \
    -r "$SPAWN" \
    -t "$RUN_TIME" \
    2>&1 | tee /tmp/locust_run.log || true
  echo "[entrypoint] Locust run finished (exit ignored). Keeping container alive."
  # Print stats every 30s so 'snow spcs service logs' can retrieve them even
  # if the tail of the original stream is rotated out.
  while true; do
    echo "=== BENCHMARK SUMMARY (heartbeat $(date -u +%FT%TZ)) ==="
    if [[ -f /tmp/locust_stats_stats.csv ]]; then
      echo "-- locust_stats_stats.csv --"
      cat /tmp/locust_stats_stats.csv
    fi
    if [[ -f /tmp/locust_stats_failures.csv ]]; then
      echo "-- locust_stats_failures.csv --"
      cat /tmp/locust_stats_failures.csv
    fi
    if [[ -f /tmp/locust_stats_stats_history.csv ]]; then
      echo "-- rows in history: $(wc -l < /tmp/locust_stats_stats_history.csv) --"
    fi
    sleep 60
  done
fi

uv run --no-sync locust -f /app/locustfile.py \
  --host "$LOCUST_HOST" \
  --web-host 0.0.0.0 \
  --web-port "$WEB_PORT" \
  --autostart \
  --autoquit 5 \
  --run-time "$RUN_TIME" \
  --csv /tmp/locust_stats \
  --html /tmp/locust_report.html \
  -u "$USERS" \
  -r "$SPAWN" 2>&1 | tee /tmp/locust_run.log

echo ""
echo "======================== BENCHMARK RESULTS ========================"
echo "-- locust_stats_stats.csv --"
[[ -f /tmp/locust_stats_stats.csv ]] && cat /tmp/locust_stats_stats.csv || echo "(no stats file)"
echo ""
echo "-- locust_stats_failures.csv --"
[[ -f /tmp/locust_stats_failures.csv ]] && cat /tmp/locust_stats_failures.csv || echo "(no failures file)"
echo ""
echo "-- locust_stats_stats_history.csv (last 5 rows) --"
[[ -f /tmp/locust_stats_stats_history.csv ]] && tail -5 /tmp/locust_stats_stats_history.csv || echo "(no history file)"
echo "===================================================================="

# Keep container alive so logs remain retrievable and CSV files can be re-read via heartbeats.
while true; do
  echo "=== HEARTBEAT $(date -u +%FT%TZ) ==="
  echo "-- locust_stats_stats.csv --"
  [[ -f /tmp/locust_stats_stats.csv ]] && cat /tmp/locust_stats_stats.csv || true
  sleep 120
done
