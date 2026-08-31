#!/usr/bin/env bash
# Deploy the benchmark API + Locust services to SPCS.
# Usage: deploy.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

echo "==> [1/5] Setting up database, schema, compute pools, image repo"
snow_sql_run "prerequisites setup" <<EOF
USE ROLE $ROLE;
USE WAREHOUSE $DEPLOY_WAREHOUSE;

CREATE DATABASE IF NOT EXISTS $DB;
USE DATABASE $DB;

CREATE SCHEMA IF NOT EXISTS $SCHEMA;
USE SCHEMA $SCHEMA;

CREATE COMPUTE POOL IF NOT EXISTS $API_COMPUTE_POOL
  MIN_NODES = $API_MIN_NODES
  MAX_NODES = $API_MAX_NODES
  INSTANCE_FAMILY = $API_INSTANCE_FAMILY
  AUTO_RESUME = TRUE;

ALTER COMPUTE POOL $API_COMPUTE_POOL RESUME IF SUSPENDED;

CREATE COMPUTE POOL IF NOT EXISTS $LOCUST_COMPUTE_POOL
  MIN_NODES = $LOCUST_MIN_NODES
  MAX_NODES = $LOCUST_MAX_NODES
  INSTANCE_FAMILY = $LOCUST_INSTANCE_FAMILY
  AUTO_RESUME = TRUE;

ALTER COMPUTE POOL $LOCUST_COMPUTE_POOL RESUME IF SUSPENDED;

CREATE IMAGE REPOSITORY IF NOT EXISTS $IMAGE_REPO;
EOF

echo "==> [2/5] Building and pushing container images"
"$SCRIPT_DIR/build-and-push.sh"

deploy_service() {
  local svc="$1"
  local spec_file="$2"
  local pool="$3"
  local min_instances="${4:-1}"
  local max_instances="${5:-1}"

  local rendered
  rendered="$(render_spec "$spec_file")"

  echo "==> Rendered spec for $svc (pool=$pool):"
  echo "----"
  echo "$rendered" | sed 's/^/    /'
  echo "----"

  snow_sql_run "deploy service $svc" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;

CREATE SERVICE IF NOT EXISTS $svc
  IN COMPUTE POOL $pool
  FROM SPECIFICATION \$\$
$rendered
\$\$
  MIN_INSTANCES = ${min_instances}
  MAX_INSTANCES = ${max_instances}
  COMMENT = 'Managed by benchmark/scripts/';

ALTER SERVICE $svc FROM SPECIFICATION \$\$
$rendered
\$\$;
EOF
}

echo "==> [3/5] Deploying benchmark API service ($API_SERVICE) on pool $API_COMPUTE_POOL"
deploy_service "$API_SERVICE" "$SPCS_DIR/specs/api.yaml" "$API_COMPUTE_POOL" "$API_MIN_INSTANCES" "$API_MAX_INSTANCES"

echo "==> [4/5] Deploying locust service ($LOCUST_SERVICE) on pool $LOCUST_COMPUTE_POOL"
deploy_service "$LOCUST_SERVICE" "$SPCS_DIR/specs/locust.yaml" "$LOCUST_COMPUTE_POOL" 1 1

echo "==> [5/5] Waiting for services to become READY (this can take a few minutes)"
"$SCRIPT_DIR/status.sh" --wait

echo
echo "==> Ingress URLs"
"$SCRIPT_DIR/status.sh" --urls-only
echo
echo "Benchmark API and Locust are ready."
