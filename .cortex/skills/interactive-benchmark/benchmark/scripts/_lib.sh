#!/usr/bin/env bash
# Shared helpers sourced by all orchestration scripts.
# Loads config.env and defines wrappers around `snow sql` and `snow spcs`.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPCS_DIR="$(cd "$SCRIPTS_DIR/../spcs" && pwd)"
REPO_DIR="$(cd "$SPCS_DIR/../.." && pwd)"

CONFIG_ENV_FILE="${BENCHMARK_CONFIG_ENV:-$SPCS_DIR/config.env}"
# shellcheck disable=SC1090
source "$CONFIG_ENV_FILE"

: "${CONNECTION:?CONNECTION must be set in config.env}"
: "${DB:?DB must be set}"
: "${SCHEMA:?SCHEMA must be set}"
: "${BENCHMARK_IMAGE:?BENCHMARK_IMAGE must be set}"
: "${IMAGE_TAG:?IMAGE_TAG must be set}"
: "${BENCHMARK_IMAGE_ARCH:?BENCHMARK_IMAGE_ARCH must be set}"

export CONNECTION DB SCHEMA QUERIES_STAGE ROLE DEPLOY_WAREHOUSE \
       SOLUTION_NAME \
       IMAGE_DB IMAGE_SCHEMA IMAGE_REPO \
       API_COMPUTE_POOL API_INSTANCE_FAMILY \
       API_MIN_NODES API_MAX_NODES \
       API_MIN_INSTANCES API_MAX_INSTANCES \
       LOCUST_COMPUTE_POOL LOCUST_INSTANCE_FAMILY \
       LOCUST_MIN_NODES LOCUST_MAX_NODES \
       API_SERVICE LOCUST_SERVICE \
       BENCHMARK_IMAGE IMAGE_TAG BENCHMARK_IMAGE_ARCH \
       API_DATABASE API_ROLE API_WAREHOUSE API_PORT POOL_SIZE \
       API_WORKERS API_POOL_WARMUP API_POOL_ACQUIRE_TIMEOUT \
       API_CPU_REQUEST API_CPU_LIMIT \
       API_MEMORY_REQUEST API_MEMORY_LIMIT \
       INTERACTIVE_WAREHOUSE INTERACTIVE_SCHEMA \
       LOCUST_HOST LOCUST_WEB_PORT LOCUST_USERS LOCUST_SPAWN \
       LOCUST_RUN_TIME API_READY_TIMEOUT_SECONDS API_READY_POLL_SECONDS

# Defaults for tuning knobs that may be missing on older config.env files.
: "${API_WORKERS:=4}"
: "${API_POOL_WARMUP:=10}"
: "${API_POOL_ACQUIRE_TIMEOUT:=30}"
: "${API_CPU_REQUEST:=2000m}"
: "${API_CPU_LIMIT:=4000m}"
: "${API_MEMORY_REQUEST:=2Gi}"
: "${API_MEMORY_LIMIT:=4Gi}"
: "${API_READY_TIMEOUT_SECONDS:=600}"
: "${API_READY_POLL_SECONDS:=2}"
export API_WORKERS API_POOL_WARMUP API_POOL_ACQUIRE_TIMEOUT \
       API_CPU_REQUEST API_CPU_LIMIT API_MEMORY_REQUEST API_MEMORY_LIMIT \
       API_READY_TIMEOUT_SECONDS API_READY_POLL_SECONDS

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd snow
require_cmd envsubst
require_cmd python3

# Run a SQL statement against $CONNECTION and print JSON output.
snow_sql() {
  snow sql --connection "$CONNECTION" --format json "$@"
}

# Run a SQL statement quietly and return the raw stdout.
# With -i, snow returns a JSON list-of-lists (one per statement).
# We flatten to the LAST non-empty rowset for backward compatibility with
# callers that expect a flat list of dicts.
snow_sql_quiet() {
  snow sql --connection "$CONNECTION" --silent --format json -i "$@" | python3 -c '
import sys, json
d = json.load(sys.stdin)
if isinstance(d, list) and d and isinstance(d[0], list):
    # Pick last non-empty statement rowset, else last one.
    last = d[-1]
    for r in reversed(d):
        if r:
            last = r
            break
    print(json.dumps(last))
else:
    print(json.dumps(d))
'
}

# Run a SQL script (heredoc on stdin) suppressing normal table output.
# Only prints "SQL error:" plus the captured output on failure.
snow_sql_run() {
  local label="${1:-SQL}"
  local out
  local rc=0
  out="$(snow sql --connection "$CONNECTION" -i 2>&1)" || rc=$?
  if (( rc != 0 )); then
    echo "SQL error while running: $label" >&2
    echo "$out" >&2
    return "$rc"
  fi
  return 0
}

validate_image_config() {
  if [[ ! "$BENCHMARK_IMAGE" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "Invalid BENCHMARK_IMAGE: $BENCHMARK_IMAGE" >&2
    return 1
  fi
  if [[ ! "$IMAGE_TAG" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid IMAGE_TAG: $IMAGE_TAG" >&2
    return 1
  fi
  case "$BENCHMARK_IMAGE_ARCH" in
    amd64|arm64) ;;
    *)
      echo "BENCHMARK_IMAGE_ARCH must be amd64 or arm64." >&2
      return 1
      ;;
  esac
}

validate_pool_architecture() {
  local family
  for family in "$API_INSTANCE_FAMILY" "$LOCUST_INSTANCE_FAMILY"; do
    case "$BENCHMARK_IMAGE_ARCH:$family" in
      amd64:CPU_X64_*|arm64:GEN_ARM_*) ;;
      *)
        echo "Image architecture $BENCHMARK_IMAGE_ARCH is incompatible with instance family $family." >&2
        return 1
        ;;
    esac
  done
}

preflight_benchmark_image() {
  local rows
  validate_image_config
  validate_pool_architecture

  rows="$(snow sql --connection "$CONNECTION" --role "$ROLE" --silent --format json -q \
    "SHOW IMAGES LIKE '${BENCHMARK_IMAGE}' IN IMAGE REPOSITORY ${IMAGE_DB}.${IMAGE_SCHEMA}.${IMAGE_REPO}")"

  IMAGE_ROWS="$rows" python3 - "$BENCHMARK_IMAGE" "$IMAGE_TAG" <<'PY'
import json
import os
import sys

image_name, expected_tag = sys.argv[1:]
rows = json.loads(os.environ["IMAGE_ROWS"])
for row in rows:
    if row.get("image_name") != image_name:
        continue
    tags = row.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",")]
    if expected_tag in tags:
        print(
            "Using image "
            f"{row.get('image_path', image_name + ':' + expected_tag)} "
            f"(digest {row.get('digest', 'unknown')})"
        )
        break
else:
    sys.stderr.write(
        f"Image {image_name}:{expected_tag} was not found in the configured repository.\n"
    )
    raise SystemExit(1)
PY
}

# Render a spec yaml with env vars substituted.
render_spec() {
  local spec="$1"
  envsubst < "$spec"
}
