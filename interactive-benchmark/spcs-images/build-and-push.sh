#!/usr/bin/env bash
# Build and push both container images to the SPCS image repository.
#
# Usage:
#   build-and-push.sh                          # uses .env in this directory
#   build-and-push.sh --config /path/to/.env   # uses a custom config
#   build-and-push.sh --create-db              # create DB if it doesn't exist

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Parse script-specific flags, then hand off to common.sh ----------------
SCRIPT_ARGS=("$@")
CREATE_DB=false
_FILTERED=()
for arg in "${SCRIPT_ARGS[@]}"; do
  if [[ "$arg" == "--create-db" ]]; then
    CREATE_DB=true
  else
    _FILTERED+=("$arg")
  fi
done
SCRIPT_ARGS=("${_FILTERED[@]+"${_FILTERED[@]}"}")
unset _FILTERED

# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

# --- Image defaults ---------------------------------------------------------
: "${API_IMAGE:=benchmark-api}"
: "${LOCUST_IMAGE:=benchmark-locust}"
: "${IMAGE_TAG:=latest}"

# --- Helpers ----------------------------------------------------------------
registry_url() {
  snow spcs image-registry url --connection "$CONNECTION" --role "$ROLE" 2>/dev/null | tr -d '"'
}

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

# --- Check Docker -----------------------------------------------------------
command -v docker >/dev/null 2>&1 || { echo "Required command not found: docker" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running. Please start Docker Desktop and try again." >&2; exit 1; }

# --- Create database (only with --create-db), schema, and image repository ---
if $CREATE_DB; then
  echo "==> Creating database $DB (if not exists)"
  snow_sql -q "CREATE DATABASE IF NOT EXISTS $DB"
fi
echo "==> Ensuring schema and image repository exist"
snow_sql -q "CREATE SCHEMA IF NOT EXISTS $DB.$SCHEMA"
snow_sql -q "CREATE IMAGE REPOSITORY IF NOT EXISTS $DB.$SCHEMA.$IMAGE_REPO"

# --- Build and push ---------------------------------------------------------
echo "==> Logging into SPCS image registry via connection '$CONNECTION'"
snow spcs image-registry login --connection "$CONNECTION" --role "$ROLE"

API_REF="$(image_ref "$API_IMAGE")"
LOCUST_REF="$(image_ref "$LOCUST_IMAGE")"

echo "==> Building API image: $API_REF"
docker build \
  --platform linux/amd64 \
  -f "$SCRIPT_DIR/api/Dockerfile" \
  -t "$API_REF" \
  "$SCRIPT_DIR"

echo "==> Pushing API image"
docker push "$API_REF"

echo "==> Building locust image: $LOCUST_REF"
docker build \
  --platform linux/amd64 \
  -f "$SCRIPT_DIR/locust/Dockerfile" \
  -t "$LOCUST_REF" \
  "$SCRIPT_DIR"

echo "==> Pushing locust image"
docker push "$LOCUST_REF"

echo "==> Done. Images pushed to $DB.$SCHEMA.$IMAGE_REPO:"
echo "    $API_REF"
echo "    $LOCUST_REF"
