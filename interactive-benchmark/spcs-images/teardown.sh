#!/usr/bin/env bash
# Drop the shared image database and everything in it (schema, image repo, images).
# Prompts for confirmation before proceeding.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1090
source "$SCRIPT_DIR/.env"

: "${CONNECTION:?CONNECTION must be set in .env}"
: "${ROLE:?ROLE must be set in .env}"
: "${DB:?DB must be set in .env}"

echo "This will DROP DATABASE ${DB} and everything in it (schema, image repository, images)."
read -rp "Are you sure? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

echo "==> Dropping database ${DB}"
snow sql --connection "$CONNECTION" --role "$ROLE" -q "DROP DATABASE IF EXISTS ${DB}"

echo "Done. Database ${DB} has been dropped."
