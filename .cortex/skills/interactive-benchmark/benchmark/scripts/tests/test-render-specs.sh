#!/usr/bin/env bash
# Render both service specs from the unmodified config.env.template.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$(cd "$SCRIPTS_DIR/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/skill/benchmark" "$TMP_DIR/bin"
cp -R "$SKILL_DIR/benchmark/scripts" "$SKILL_DIR/benchmark/spcs" "$TMP_DIR/skill/benchmark/"
printf 'CONNECTION_NAME=test\nSOLUTION_NAME=IWB_TEST\n' >"$TMP_DIR/skill/benchmark/.env"
cp "$TMP_DIR/skill/benchmark/spcs/config.env.template" "$TMP_DIR/skill/benchmark/spcs/config.env"
printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP_DIR/bin/snow"
chmod +x "$TMP_DIR/bin/snow"

render() {
  PATH="$TMP_DIR/bin:$PATH" bash -c '
    source "$1/benchmark/scripts/_lib.sh"
    render_spec "$SPCS_DIR/specs/$2"
  ' _ "$TMP_DIR/skill" "$1"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

locust="$(render locust.yaml)"
api="$(render api.yaml)"

grep -q 'LOCUST_HOST: "http://benchmark-api:3000"' <<<"$locust" || fail "LOCUST_HOST not derived from API_SERVICE/API_PORT"
grep -q 'BASELINE_MAX_P99_MS: "500"' <<<"$locust" || fail "baseline p99 threshold not rendered"
grep -q 'BASELINE_MAX_FAILURE_PCT: "1"' <<<"$locust" || fail "baseline failure threshold not rendered"
grep -q 'BENCHMARK_MAX_FAILURE_PCT: "1"' <<<"$locust" || fail "benchmark failure threshold not rendered"
! grep -q 'readinessProbe' <<<"$locust" || fail "Locust spec still has a readiness probe"
grep -q 'path: /api/ready' <<<"$api" || fail "API readiness probe missing"
! grep -q '\${' <<<"$locust$api" || fail "unrendered placeholder"

echo "Spec rendering contract passed."
