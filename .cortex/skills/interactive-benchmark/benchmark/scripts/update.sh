#!/usr/bin/env bash
# Upload new .sql files to the stage and restart the API service so it picks
# up the new queries.  No Docker image rebuild is performed.
#
# Application releases use immutable approved image tags; this script only
# updates benchmark queries.
#
# Flags:
#   --queries-only   (default, kept for backward compatibility)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

echo "==> Uploading queries to stage"
"$SCRIPT_DIR/upload-queries.sh"

echo "==> Restarting API service to pick up new queries"
snow spcs service restart "$API_SERVICE" \
  --connection "$CONNECTION" --role "$ROLE" \
  --dbname "$DB" --schema "$SCHEMA"

echo "Done. API service is restarting with the new queries."
