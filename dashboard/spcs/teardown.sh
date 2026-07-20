#!/usr/bin/env bash
# Drop the dashboard + locust services, compute pools, and image repository.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

cat <<EOF | snow_sql_run "teardown services"
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
DROP SERVICE IF EXISTS $LOCUST_SERVICE;
DROP SERVICE IF EXISTS $LOCUST_API_SERVICE;
DROP SERVICE IF EXISTS $DASHBOARD_SERVICE;
EOF

echo "Dropped services, compute pools ('$DASHBOARD_COMPUTE_POOL', '$LOCUST_COMPUTE_POOL'), and image repo '$IMAGE_REPO'."
