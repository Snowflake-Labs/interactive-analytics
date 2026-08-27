#!/usr/bin/env bash
# SPCS entrypoint for the locust container.
#
# Non-headless auto-start mode:
#   - Serves the locust web UI on $LOCUST_WEB_PORT so the SPCS readinessProbe
#     on /stats/requests can pass.
#   - --autostart triggers the swarm immediately when the container comes up,
#     so no external POST to /swarm is needed (SPCS public ingress requires
#     Snowflake auth and can't be curled from a laptop with externalbrowser
#     connections — the auto-start design sidesteps this).
#   - --autoquit 5 exits locust ~5 s after --run-time expires.
#   - After locust exits, we print the results CSV to stdout and then loop
#     with periodic heartbeats so `snow spcs service logs` can retrieve
#     results at any later time.

set -uo pipefail

: "${LOCUST_HOST:?LOCUST_HOST must be set (e.g. http://benchmark-api:3000)}"

export BENCHMARK_QUERIES_DIR="${BENCHMARK_QUERIES_DIR:-/app/test}"

USERS="${LOCUST_USERS:-10}"
SPAWN="${LOCUST_SPAWN:-5}"
WEB_PORT="${LOCUST_WEB_PORT:-8089}"
RUN_TIME="${LOCUST_RUN_TIME:-3m}"

echo "[entrypoint] target=$LOCUST_HOST users=$USERS spawn=$SPAWN run_time=$RUN_TIME queries=$BENCHMARK_QUERIES_DIR"

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

# Keep container alive so logs remain retrievable and CSV files can be
# re-read via periodic heartbeats even after the initial log stream is
# rotated out of `snow spcs service logs`.
while true; do
  echo "=== HEARTBEAT $(date -u +%FT%TZ) ==="
  echo "-- locust_stats_stats.csv --"
  [[ -f /tmp/locust_stats_stats.csv ]] && cat /tmp/locust_stats_stats.csv || true
  sleep 120
done
