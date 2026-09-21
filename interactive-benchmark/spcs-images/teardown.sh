#!/usr/bin/env bash
# Drop the image repository and schema (and optionally the database) used by
# the benchmark SPCS images.
#
# Usage:
#   teardown.sh                          # drops schema and image repo only
#   teardown.sh --config /path/to/.env   # uses a custom config
#   teardown.sh --drop-db                # also drops the entire database

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Parse script-specific flags, then hand off to common.sh ----------------
SCRIPT_ARGS=("$@")
DROP_DB=false
_FILTERED=()
for arg in "${SCRIPT_ARGS[@]}"; do
  if [[ "$arg" == "--drop-db" ]]; then
    DROP_DB=true
  else
    _FILTERED+=("$arg")
  fi
done
SCRIPT_ARGS=("${_FILTERED[@]+"${_FILTERED[@]}"}")
unset _FILTERED

# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

# --- Confirm ----------------------------------------------------------------
if $DROP_DB; then
  echo "This will DROP DATABASE ${DB} and everything in it."
else
  echo "This will drop image repository ${DB}.${SCHEMA}.${IMAGE_REPO} and schema ${DB}.${SCHEMA}."
fi
read -rp "Are you sure? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# --- Teardown ---------------------------------------------------------------
if $DROP_DB; then
  echo "==> Dropping database ${DB}"
  snow_sql -q "DROP DATABASE IF EXISTS ${DB}"
  echo "Done. Database ${DB} has been dropped."
else
  echo "==> Dropping image repository ${DB}.${SCHEMA}.${IMAGE_REPO}"
  snow_sql -q "DROP IMAGE REPOSITORY IF EXISTS ${DB}.${SCHEMA}.${IMAGE_REPO}"
  echo "==> Dropping schema ${DB}.${SCHEMA}"
  snow_sql -q "DROP SCHEMA IF EXISTS ${DB}.${SCHEMA}"
  echo "Done. Schema ${DB}.${SCHEMA} has been dropped."
fi
