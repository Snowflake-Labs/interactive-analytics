#!/usr/bin/env bash
# Contract tests for status.sh, upload-queries.sh, and list.sh against a mock snow.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/queries"
echo "SELECT 1;" >"$TMP_DIR/queries/benchmark-query.sql"

cat >"$TMP_DIR/config.env" <<EOF
CONNECTION=test
ROLE=TEST_ROLE
SOLUTION_NAME=TEST
DB=TEST_DB
SCHEMA=SPCS
QUERIES_STAGE=BENCHMARK_QUERIES
API_SERVICE=BENCHMARK_API
LOCUST_SERVICE=BENCHMARK_LOCUST
API_COMPUTE_POOL=TEST_API_POOL
LOCUST_COMPUTE_POOL=TEST_LOCUST_POOL
IMAGE_DB=SNOWFLAKE
IMAGE_SCHEMA=IMAGES
IMAGE_REPO=SNOWFLAKE_IMAGES
BENCHMARK_IMAGE=interactive-analytics/interactive-benchmark
IMAGE_TAG=0.1.0
BENCHMARK_IMAGE_ARCH=amd64
EOF

cat >"$TMP_DIR/snow" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
fixtures="$(dirname "$0")"
echo "$args" >>"$fixtures/calls.log"
case "$args" in
  *"GET_SERVICE_STATUS('TEST_DB.SPCS.BENCHMARK_API')"*)
    python3 -c 'import json; print(json.dumps([{"INFO": json.dumps([
      {"status": "READY", "message": "Running"},
      {"status": "PENDING", "message": "Pulling image"},
      {"status": "READY", "message": "Running"}])}]))' ;;
  *"GET_SERVICE_STATUS('TEST_DB.SPCS.BENCHMARK_LOCUST')"*)
    python3 -c 'import json; print(json.dumps([{"INFO": json.dumps([
      {"status": "READY", "message": "Running"}])}]))' ;;
  *"list-endpoints"*) echo '[]' ;;
  *"SHOW IMAGES"*|*"SHOW SERVICES"*) echo '[]' ;;
  *"SHOW COMPUTE POOLS"*)
    echo '[{"name":"TEST_API_POOL","state":"ACTIVE"},{"name":"TEST_OTHER_POOL","state":"ACTIVE"},{"name":"TEST_LOCUST_POOL","state":"IDLE"}]' ;;
  *"sql --connection test -i"*)
    cat >>"$fixtures/calls.log"
    echo '[]' ;;
  *"REMOVE @TEST_DB.SPCS.BENCHMARK_QUERIES PATTERN = '.*[.]sql'"*|*"stage copy"*) ;;
  *) echo "unexpected snow call: $args" >&2; exit 1 ;;
esac
EOF
chmod +x "$TMP_DIR/snow"

run() {
  PATH="$TMP_DIR:$PATH" BENCHMARK_CONFIG_ENV="$TMP_DIR/config.env" \
    BENCHMARK_QUERY_DIR="$TMP_DIR/queries" "$@"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# status.sh: one PENDING instance out of three makes the API not READY.
status="$(run "$SCRIPTS_DIR/status.sh")"
grep -q "BENCHMARK_API *PENDING *(Pulling image)" <<<"$status" || fail "API status ignored a PENDING instance: $status"
grep -q "BENCHMARK_LOCUST *READY" <<<"$status" || fail "Locust status wrong: $status"

# upload-queries.sh: a full upload clears old .sql files before copying.
: >"$TMP_DIR/calls.log"
run "$SCRIPTS_DIR/upload-queries.sh" >/dev/null
remove_line="$(grep -n "REMOVE @TEST_DB.SPCS.BENCHMARK_QUERIES" "$TMP_DIR/calls.log" | cut -d: -f1)"
copy_line="$(grep -n "stage copy" "$TMP_DIR/calls.log" | cut -d: -f1)"
[[ -n "$remove_line" && -n "$copy_line" && "$remove_line" -lt "$copy_line" ]] || fail "stale queries not removed before upload"

# Explicit files are additive.
: >"$TMP_DIR/calls.log"
run "$SCRIPTS_DIR/upload-queries.sh" "$TMP_DIR/queries/benchmark-query.sql" >/dev/null
! grep -q "REMOVE" "$TMP_DIR/calls.log" || fail "explicit upload removed other queries"

# update.sh: restart the API through supported SQL, not a removed CLI command.
: >"$TMP_DIR/calls.log"
run "$SCRIPTS_DIR/update.sh" >/dev/null
grep -q "ALTER SERVICE IF EXISTS BENCHMARK_API SUSPEND" "$TMP_DIR/calls.log" || fail "API suspend SQL missing"
grep -q "ALTER SERVICE IF EXISTS BENCHMARK_API RESUME" "$TMP_DIR/calls.log" || fail "API resume SQL missing"
! grep -q "spcs service restart" "$TMP_DIR/calls.log" || fail "unsupported CLI restart still used"

# list.sh: only the two benchmark pools are listed.
listing="$(run "$SCRIPTS_DIR/list.sh")"
grep -q "TEST_API_POOL" <<<"$listing" || fail "API pool missing from list.sh"
grep -q "TEST_LOCUST_POOL" <<<"$listing" || fail "Locust pool missing from list.sh"
! grep -q "TEST_OTHER_POOL" <<<"$listing" || fail "list.sh listed an unrelated pool"

echo "Helper script contract passed."
