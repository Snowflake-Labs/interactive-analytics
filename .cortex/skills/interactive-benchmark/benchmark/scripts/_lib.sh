#!/usr/bin/env bash
# Shared helpers sourced by all orchestration scripts.
# Loads config.env and defines wrappers around `snow sql` and `snow spcs`.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPCS_DIR="$(cd "$SCRIPTS_DIR/../spcs" && pwd)"
REPO_DIR="$(cd "$SPCS_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$SPCS_DIR/config.env"

: "${CONNECTION:?CONNECTION must be set in config.env}"
: "${DB:?DB must be set}"
: "${SCHEMA:?SCHEMA must be set}"

export CONNECTION DB SCHEMA IMAGE_REPO ROLE DEPLOY_WAREHOUSE \
       SOLUTION_NAME \
       API_COMPUTE_POOL API_INSTANCE_FAMILY \
       API_MIN_NODES API_MAX_NODES \
       API_MIN_INSTANCES API_MAX_INSTANCES \
       LOCUST_COMPUTE_POOL LOCUST_INSTANCE_FAMILY \
       LOCUST_MIN_NODES LOCUST_MAX_NODES \
       API_SERVICE LOCUST_SERVICE \
       API_IMAGE LOCUST_IMAGE IMAGE_TAG \
       API_DATABASE API_ROLE API_WAREHOUSE API_PORT POOL_SIZE \
       API_WORKERS API_POOL_WARMUP API_POOL_ACQUIRE_TIMEOUT \
       API_CPU_REQUEST API_CPU_LIMIT \
       API_MEMORY_REQUEST API_MEMORY_LIMIT \
       INTERACTIVE_WAREHOUSE INTERACTIVE_SCHEMA \
       LOCUST_HOST LOCUST_WEB_PORT LOCUST_USERS LOCUST_SPAWN \
       LOCUST_RUN_TIME

# Defaults for tuning knobs that may be missing on older config.env files.
: "${API_WORKERS:=4}"
: "${API_POOL_WARMUP:=10}"
: "${API_POOL_ACQUIRE_TIMEOUT:=30}"
: "${API_CPU_REQUEST:=2000m}"
: "${API_CPU_LIMIT:=4000m}"
: "${API_MEMORY_REQUEST:=2Gi}"
: "${API_MEMORY_LIMIT:=4Gi}"
export API_WORKERS API_POOL_WARMUP API_POOL_ACQUIRE_TIMEOUT \
       API_CPU_REQUEST API_CPU_LIMIT API_MEMORY_REQUEST API_MEMORY_LIMIT

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd snow
require_cmd docker
require_cmd envsubst

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

# Fetch the registry hostname for this account.
registry_url() {
  snow spcs image-registry url --connection "$CONNECTION" --role "$ROLE" 2>/dev/null | tr -d '"'
}

# Full image reference including registry.
image_ref() {
  local image_name="$1"
  local reg
  reg="$(registry_url)"
  local db_lower schema_lower repo_lower
  db_lower="$(echo "$DB" | tr '[:upper:]' '[:lower:]')"
  schema_lower="$(echo "$SCHEMA" | tr '[:upper:]' '[:lower:]')"
  repo_lower="$(echo "$IMAGE_REPO" | tr '[:upper:]' '[:lower:]')"
  echo "${reg}/${db_lower}/${schema_lower}/${repo_lower}/${image_name}:${IMAGE_TAG}"
}

# Render a spec yaml with env vars substituted.
render_spec() {
  local spec="$1"
  envsubst < "$spec"
}
