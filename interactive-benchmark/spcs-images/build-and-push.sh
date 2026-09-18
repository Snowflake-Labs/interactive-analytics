#!/usr/bin/env bash
# Build and push both container images to the SPCS image repository.
#
# Usage:
#   build-and-push.sh                          # uses .env in this directory
#   build-and-push.sh --config /path/to/.env   # uses a custom config
#
# Required config variables: CONNECTION, ROLE, DB, SCHEMA, IMAGE_REPO,
#   API_IMAGE, LOCUST_IMAGE, IMAGE_TAG.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Load configuration -----------------------------------------------------
CONFIG_FILE=""
while (( $# )); do
  case "$1" in
    --config) CONFIG_FILE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$CONFIG_FILE" ]]; then
  CONFIG_FILE="$SCRIPT_DIR/.env"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config file not found: $CONFIG_FILE" >&2
  echo "Create .env or pass --config /path/to/.env" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${CONNECTION:?CONNECTION must be set in config}"
: "${ROLE:?ROLE must be set in config}"
: "${DB:?DB must be set in config}"
: "${SCHEMA:?SCHEMA must be set in config}"
: "${IMAGE_REPO:?IMAGE_REPO must be set in config}"
: "${API_IMAGE:=benchmark-api}"
: "${LOCUST_IMAGE:=benchmark-locust}"
: "${IMAGE_TAG:=latest}"

# --- Helpers ----------------------------------------------------------------
snow_sql() {
  snow sql --connection "$CONNECTION" --role "$ROLE" "$@"
}

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

# --- Check prerequisites ----------------------------------------------------
for cmd in snow docker; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Required command not found: $cmd" >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker is not running. Please start Docker Desktop and try again." >&2; exit 1; }

# --- Create database, schema, and image repository --------------------------
echo "==> Ensuring database, schema, and image repository exist"
snow_sql -q "CREATE DATABASE IF NOT EXISTS $DB"
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
