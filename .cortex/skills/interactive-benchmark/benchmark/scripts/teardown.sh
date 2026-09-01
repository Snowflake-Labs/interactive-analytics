#!/usr/bin/env bash
# Drop the benchmark API + Locust services, compute pools, and image repository.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

cat <<EOF | snow_sql_run "teardown services"
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
DROP SERVICE IF EXISTS $LOCUST_SERVICE;
DROP SERVICE IF EXISTS $API_SERVICE;
EOF

cat <<EOF | snow_sql_run "teardown compute pools"
USE ROLE $ROLE;
ALTER COMPUTE POOL IF EXISTS $API_COMPUTE_POOL STOP ALL;
ALTER COMPUTE POOL IF EXISTS $LOCUST_COMPUTE_POOL STOP ALL;
DROP COMPUTE POOL IF EXISTS $API_COMPUTE_POOL;
DROP COMPUTE POOL IF EXISTS $LOCUST_COMPUTE_POOL;
EOF

cat <<EOF | snow_sql_run "teardown image repo"
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
DROP IMAGE REPOSITORY IF EXISTS $IMAGE_REPO;
EOF

echo "Dropped services, compute pools ('$API_COMPUTE_POOL', '$LOCUST_COMPUTE_POOL'), and image repo '$IMAGE_REPO'."
