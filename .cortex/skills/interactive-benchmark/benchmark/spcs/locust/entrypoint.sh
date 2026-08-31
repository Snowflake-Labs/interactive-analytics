#!/usr/bin/env bash
# SPCS entrypoint for the locust container.
#
# Two-phase execution:
#
#   Phase 1 — Baseline:
#     Runs BaselineUser against /api/run/baseline (no-op) to verify the
#     API/SPCS infrastructure can handle the target concurrency without
#     being a bottleneck. If failure rate or p99 exceed thresholds, the
#     container aborts before touching Snowflake.
#
#   Phase 2 — Snowflake Benchmark:
#     Runs BenchmarkUser against /api/run/interactive (real queries).
#     Only executes if Phase 1 passes.
#
# Both phases use --autostart / --autoquit so no external HTTP call is
# needed (SPCS public ingress requires Snowflake auth).
#
# After both phases complete, results are printed to stdout and the
# container loops with periodic heartbeats so `snow spcs service logs`
# can retrieve results at any later time.

set -uo pipefail

: "${LOCUST_HOST:?LOCUST_HOST must be set (e.g. http://benchmark-api:3000)}"

export BENCHMARK_QUERIES_DIR="${BENCHMARK_QUERIES_DIR:-/app/test}"

USERS="${LOCUST_USERS:-10}"
SPAWN="${LOCUST_SPAWN:-5}"
WEB_PORT="${LOCUST_WEB_PORT:-8089}"
RUN_TIME="${LOCUST_RUN_TIME:-3m}"

# Baseline thresholds
BASELINE_RUN_TIME="${BASELINE_RUN_TIME:-1m}"
BASELINE_MAX_FAILURE_PCT="${BASELINE_MAX_FAILURE_PCT:-1}"
BASELINE_MAX_P99_MS="${BASELINE_MAX_P99_MS:-500}"

echo "[entrypoint] target=$LOCUST_HOST users=$USERS spawn=$SPAWN"
echo "[entrypoint] baseline: run_time=$BASELINE_RUN_TIME max_failure_pct=$BASELINE_MAX_FAILURE_PCT max_p99_ms=$BASELINE_MAX_P99_MS"
echo "[entrypoint] benchmark: run_time=$RUN_TIME queries=$BENCHMARK_QUERIES_DIR"

# ---------------------------------------------------------------------------
# Helper: print a results banner from a CSV prefix
# ---------------------------------------------------------------------------
print_results() {
  local label="$1" prefix="$2"
  echo ""
  echo "======================== ${label} RESULTS ========================"
  echo "-- ${prefix}_stats.csv --"
  [[ -f "${prefix}_stats.csv" ]] && cat "${prefix}_stats.csv" || echo "(no stats file)"
  echo ""
  echo "-- ${prefix}_failures.csv --"
  [[ -f "${prefix}_failures.csv" ]] && cat "${prefix}_failures.csv" || echo "(no failures file)"
  echo ""
  echo "-- ${prefix}_stats_history.csv (last 5 rows) --"
  [[ -f "${prefix}_stats_history.csv" ]] && tail -5 "${prefix}_stats_history.csv" || echo "(no history file)"
  echo "===================================================================="
}

# ---------------------------------------------------------------------------
# Helper: parse the Aggregated row from a Locust stats CSV and check
# against thresholds. Returns 0 if pass, 1 if fail.
# ---------------------------------------------------------------------------
check_baseline() {
  local csv="$1"
  if [[ ! -f "$csv" ]]; then
    echo "[baseline] ERROR: stats file not found: $csv"
    return 1
  fi

  # Extract Aggregated row. Locust CSV columns (0-indexed):
  #   0:Type 1:Name 2:Request Count 3:Failure Count ... 18:99% ...
  local result
  result=$(awk -F',' '
    /Aggregated/ {
      requests = $3 + 0
      failures = $4 + 0
      p99      = $19 + 0
      if (requests > 0) {
        fail_pct = (failures / requests) * 100
      } else {
        fail_pct = 0
      }
      printf "%.2f %d %d %d", fail_pct, p99, requests, failures
    }
  ' "$csv")

  if [[ -z "$result" ]]; then
    echo "[baseline] ERROR: no Aggregated row found in $csv"
    return 1
  fi

  local fail_pct p99 requests failures
  read -r fail_pct p99 requests failures <<< "$result"

  echo "[baseline] requests=$requests failures=$failures failure_pct=${fail_pct}% p99=${p99}ms"
  echo "[baseline] thresholds: max_failure_pct=${BASELINE_MAX_FAILURE_PCT}% max_p99=${BASELINE_MAX_P99_MS}ms"

  # Compare using awk for floating-point
  local failed=0
  if awk "BEGIN { exit !(${fail_pct} > ${BASELINE_MAX_FAILURE_PCT}) }"; then
    echo "[baseline] FAIL: failure rate ${fail_pct}% exceeds threshold ${BASELINE_MAX_FAILURE_PCT}%"
    failed=1
  fi
  if (( p99 > BASELINE_MAX_P99_MS )); then
    echo "[baseline] FAIL: p99 ${p99}ms exceeds threshold ${BASELINE_MAX_P99_MS}ms"
    failed=1
  fi

  if (( failed )); then
    echo "[baseline] VERDICT: FAIL — the API/SPCS infrastructure cannot handle $USERS concurrent users."
    echo "[baseline] The benchmark will NOT proceed. Consider:"
    echo "[baseline]   - Increasing API_MIN_INSTANCES / API_MAX_INSTANCES"
    echo "[baseline]   - Increasing API compute pool node count"
    echo "[baseline]   - Reducing LOCUST_USERS"
    return 1
  fi

  echo "[baseline] VERDICT: PASS — infrastructure can handle $USERS concurrent users."
  return 0
}

# ===========================================================================
# Phase 1: Baseline
# ===========================================================================
echo ""
echo "===== PHASE 1: BASELINE TEST ====="
echo "[baseline] Running BaselineUser for $BASELINE_RUN_TIME with $USERS users..."

uv run --no-sync locust -f /app/locustfile.py BaselineUser \
  --host "$LOCUST_HOST" \
  --web-host 0.0.0.0 \
  --web-port "$WEB_PORT" \
  --autostart \
  --autoquit 5 \
  --run-time "$BASELINE_RUN_TIME" \
  --csv /tmp/baseline_stats \
  --html /tmp/baseline_report.html \
  -u "$USERS" \
  -r "$SPAWN" 2>&1 | tee /tmp/baseline_run.log

print_results "BASELINE" "/tmp/baseline_stats"

if ! check_baseline "/tmp/baseline_stats_stats.csv"; then
  echo ""
  echo "[entrypoint] Baseline failed. Skipping Snowflake benchmark."
  echo "[entrypoint] Review the baseline results above to diagnose the issue."

  # Keep container alive for log retrieval
  while true; do
    echo "=== HEARTBEAT $(date -u +%FT%TZ) ==="
    echo "[status] baseline=FAILED benchmark=SKIPPED"
    print_results "BASELINE" "/tmp/baseline_stats"
    sleep 120
  done
fi

# ===========================================================================
# Phase 2: Snowflake Benchmark
# ===========================================================================
echo ""
echo "===== PHASE 2: SNOWFLAKE BENCHMARK ====="
echo "[benchmark] Running BenchmarkUser for $RUN_TIME with $USERS users..."

uv run --no-sync locust -f /app/locustfile.py BenchmarkUser \
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

print_results "BENCHMARK" "/tmp/locust_stats"

# Keep container alive so logs remain retrievable
while true; do
  echo "=== HEARTBEAT $(date -u +%FT%TZ) ==="
  echo "[status] baseline=PASSED benchmark=COMPLETED"
  echo "-- baseline_stats_stats.csv --"
  [[ -f /tmp/baseline_stats_stats.csv ]] && cat /tmp/baseline_stats_stats.csv || true
  echo "-- locust_stats_stats.csv --"
  [[ -f /tmp/locust_stats_stats.csv ]] && cat /tmp/locust_stats_stats.csv || true
  sleep 120
done
