#!/usr/bin/env bash
# Shared helpers sourced by all orchestration scripts.
# Loads config.env and defines wrappers around `snow sql` and `snow spcs`.

set -euo pipefail

SPCS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SPCS_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$SPCS_DIR/config.env"

: "${CONNECTION:?CONNECTION must be set in config.env}"
: "${DB:?DB must be set}"
: "${SCHEMA:?SCHEMA must be set}"

export CONNECTION DB SCHEMA IMAGE_REPO ROLE DEPLOY_WAREHOUSE \
       DASHBOARD_COMPUTE_POOL DASHBOARD_INSTANCE_FAMILY \
       DASHBOARD_MIN_NODES DASHBOARD_MAX_NODES \
       LOCUST_COMPUTE_POOL LOCUST_INSTANCE_FAMILY \
       LOCUST_MIN_NODES LOCUST_MAX_NODES \
       DASHBOARD_SERVICE LOCUST_API_SERVICE LOCUST_SERVICE \
       DASHBOARD_IMAGE LOCUST_IMAGE IMAGE_TAG \
       DASHBOARD_DATABASE DASHBOARD_ROLE DASHBOARD_WAREHOUSE \
       DASHBOARD_DEFAULT_SCALE DASHBOARD_PORT \
       LOCUST_HOST LOCUST_WEB_PORT LOCUST_USERS LOCUST_SPAWN \
       LOCUST_HEADLESS LOCUST_RUN_TIME LOCUST_WAREHOUSE LOCUST_SCALE

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
snow_sql_quiet() {
  snow sql --connection "$CONNECTION" --silent --format json "$@"
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
