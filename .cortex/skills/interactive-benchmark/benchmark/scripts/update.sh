#!/usr/bin/env bash
# Upload new .sql files to the stage and restart the API service so it picks
# up the new queries.  No Docker image rebuild is performed.
#
# Application releases use immutable approved image tags; this script only
# updates benchmark queries.
#
# Flags:
#   --queries-only   (default, kept for backward compatibility)
#
# This does not re-run the load test. To re-run Locust, suspend and resume
# the Locust service.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

for arg in "$@"; do
  case "$arg" in
    --queries-only) ;;
    *) echo "Unknown option: $arg" >&2; echo "Usage: update.sh [--queries-only]" >&2; exit 1 ;;
  esac
done

echo "==> Uploading queries to stage"
"$SCRIPT_DIR/upload-queries.sh"

echo "==> Restarting API service to pick up new queries"
snow_sql_run "restart API service" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE IF EXISTS $API_SERVICE SUSPEND;
ALTER SERVICE IF EXISTS $API_SERVICE RESUME;
EOF

echo "Done. API service is restarting with the new queries."
