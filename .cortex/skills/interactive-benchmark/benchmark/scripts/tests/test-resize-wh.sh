#!/usr/bin/env bash

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat >"$TMP_DIR/config.env" <<'EOF'
CONNECTION=test
ROLE=TEST_ROLE
SOLUTION_NAME=TEST
DB=TEST_DB
SCHEMA=SPCS
API_SERVICE=BENCHMARK_API
LOCUST_SERVICE=BENCHMARK_LOCUST
BENCHMARK_IMAGE=interactive-analytics/interactive-benchmark
IMAGE_TAG=0.1.0
BENCHMARK_IMAGE_ARCH=amd64
INTERACTIVE_WAREHOUSE=TEST_INT_WH
EOF

# Mock snow: answers SHOW commands from JSON fixtures and logs every script
# passed on stdin (snow sql -i) to sql.log.
cat >"$TMP_DIR/snow" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
fixtures="$(dirname "$0")"
case "$args" in
  *"SHOW WAREHOUSES LIKE 'TEST_INT_WH'"*) cat "$fixtures/warehouses.json" ;;
  *"SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE TEST_INT_WH"*)
    echo '[{"key":"FALLBACK_WAREHOUSE","value":"TEST_STD_WH","level":"WAREHOUSE"}]' ;;
  *"SHOW SERVICES LIKE"*) cat "$fixtures/services.json" ;;
  *"SHOW GRANTS ON WAREHOUSE TEST_INT_WH"*) cat "$fixtures/grants.json" ;;
  *" -i"*) { cat; echo "---"; } >>"$fixtures/sql.log" ;;
  *) echo "unexpected snow call: $args" >&2; exit 1 ;;
esac
EOF
chmod +x "$TMP_DIR/snow"

warehouse_row() {
  local tables_field="$1"
  cat >"$TMP_DIR/warehouses.json" <<EOF
[
  {"name":"TESTXINT_WH","size":"Large","min_cluster_count":9,"max_cluster_count":9,"owner":"OTHER","resource_monitor":"null"${tables_field}},
  {"name":"TEST_INT_WH","size":"X-Small","min_cluster_count":2,"max_cluster_count":4,"owner":"TEST_ROLE","resource_monitor":"null"${tables_field}}
]
EOF
}

reset() {
  : >"$TMP_DIR/sql.log"
  warehouse_row ',"tables":"SRC_DB.S.ORDERS, SRC_DB.S.NATION"'
  echo '[{"privilege":"OWNERSHIP","granted_to":"ROLE","grantee_name":"TEST_ROLE"}]' >"$TMP_DIR/grants.json"
  cat >"$TMP_DIR/services.json" <<'EOF'
[
  {"name":"BENCHMARK_API","database_name":"TEST_DB","schema_name":"SPCS"},
  {"name":"BENCHMARK_LOCUST","database_name":"TEST_DB","schema_name":"SPCS"}
]
EOF
}

run_resize() {
  PATH="$TMP_DIR:$PATH" BENCHMARK_CONFIG_ENV="$TMP_DIR/config.env" \
    "$SCRIPTS_DIR/resize-wh.sh" "$@"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# 1. Cluster-count change before deploy: ALTER in place, no service calls.
reset
echo '[]' >"$TMP_DIR/services.json"
run_resize --mcw 14 >/dev/null
grep -q "ALTER WAREHOUSE TEST_INT_WH SET MAX_CLUSTER_COUNT = 14;" "$TMP_DIR/sql.log" \
  || fail "--mcw did not ALTER MAX_CLUSTER_COUNT"
! grep -q "CREATE OR REPLACE" "$TMP_DIR/sql.log" || fail "--mcw replaced the warehouse"
! grep -q "ALTER SERVICE" "$TMP_DIR/sql.log" || fail "--mcw touched undeployed services"

# 2. Size change after deploy: replace, keep tables and fallback, resume API only.
reset
run_resize --size medium >/dev/null
grep -q "CREATE OR REPLACE INTERACTIVE WAREHOUSE TEST_INT_WH" "$TMP_DIR/sql.log" \
  || fail "--size did not replace the warehouse"
grep -q "SRC_DB.S.ORDERS," "$TMP_DIR/sql.log" || fail "attached tables were not preserved"
grep -q "SRC_DB.S.NATION" "$TMP_DIR/sql.log" || fail "attached tables were not preserved"
grep -q "WAREHOUSE_SIZE = 'MEDIUM'" "$TMP_DIR/sql.log" || fail "size not applied"
grep -q "MIN_CLUSTER_COUNT = 2" "$TMP_DIR/sql.log" || fail "picked the LIKE-wildcard match"
grep -q "MAX_CLUSTER_COUNT = 4" "$TMP_DIR/sql.log" || fail "max_cluster_count not kept"
grep -q "SET FALLBACK_WAREHOUSE = TEST_STD_WH" "$TMP_DIR/sql.log" || fail "fallback not restored"
grep -q "ALTER SERVICE TEST_DB.SPCS.BENCHMARK_LOCUST SUSPEND" "$TMP_DIR/sql.log" \
  || fail "Locust not suspended"
grep -q "ALTER SERVICE TEST_DB.SPCS.BENCHMARK_API RESUME" "$TMP_DIR/sql.log" || fail "API not resumed"
! grep -q "BENCHMARK_LOCUST RESUME" "$TMP_DIR/sql.log" || fail "Locust resumed before warm-up"

# 3. Missing tables column: fail before replacing.
reset
warehouse_row ''
if run_resize --size medium >/dev/null 2>"$TMP_DIR/err"; then
  fail "missing tables column unexpectedly passed"
fi
grep -q "did not return a tables column" "$TMP_DIR/err" || fail "wrong error for missing tables column"
! grep -q "CREATE OR REPLACE" "$TMP_DIR/sql.log" || fail "replaced without the tables column"
run_resize --mcw 6 >/dev/null || fail "--mcw needs no tables column but failed"
grep -q "SET MAX_CLUSTER_COUNT = 6;" "$TMP_DIR/sql.log" || fail "--mcw without tables column did not ALTER"

# 4. Grants to other roles: refuse unless --force-replace.
reset
cat >"$TMP_DIR/grants.json" <<'EOF'
[
  {"privilege":"OWNERSHIP","granted_to":"ROLE","grantee_name":"TEST_ROLE"},
  {"privilege":"USAGE","granted_to":"ROLE","grantee_name":"ANALYST"}
]
EOF
if run_resize --size medium >/dev/null 2>"$TMP_DIR/err"; then
  fail "replace with foreign grants unexpectedly passed"
fi
grep -q "USAGE to ROLE ANALYST" "$TMP_DIR/err" || fail "foreign grant not reported"
! grep -q "CREATE OR REPLACE" "$TMP_DIR/sql.log" || fail "replaced despite foreign grants"
run_resize --size medium --force-replace >/dev/null
grep -q "CREATE OR REPLACE" "$TMP_DIR/sql.log" || fail "--force-replace did not replace"

echo "resize-wh contract passed."
