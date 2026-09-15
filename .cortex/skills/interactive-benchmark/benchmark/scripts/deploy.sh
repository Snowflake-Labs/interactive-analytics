#!/usr/bin/env bash
# Deploy the benchmark API + Locust services to SPCS.
# Usage: deploy.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

echo "==> [1/7] Setting up database, schema, and queries stage"
snow_sql_run "prerequisites setup" <<EOF
USE ROLE $ROLE;
USE WAREHOUSE $DEPLOY_WAREHOUSE;

CREATE DATABASE IF NOT EXISTS $DB;
CREATE SCHEMA IF NOT EXISTS $DB.$SCHEMA;

USE DATABASE $DB;
USE SCHEMA $SCHEMA;

CREATE STAGE IF NOT EXISTS $QUERIES_STAGE
  COMMENT = 'Benchmark SQL query files (mounted into the API container)';
EOF

echo "==> [2/7] Creating compute pools and image repository"
spcs_compute_pool_create "$API_COMPUTE_POOL" "$API_INSTANCE_FAMILY" \
  "$API_MIN_NODES" "$API_MAX_NODES"
spcs_compute_pool_create "$LOCUST_COMPUTE_POOL" "$LOCUST_INSTANCE_FAMILY" \
  "$LOCUST_MIN_NODES" "$LOCUST_MAX_NODES"
spcs_image_repo_create "$IMAGE_REPO"

echo "==> [3/7] Uploading benchmark queries to stage"
"$SCRIPT_DIR/upload-queries.sh"

echo "==> [4/7] Building and pushing container images"
"$SCRIPT_DIR/build-and-push.sh"

echo "==> [5/7] Deploying benchmark API service ($API_SERVICE) on pool $API_COMPUTE_POOL"
spcs_service_upsert "$API_SERVICE" "$API_COMPUTE_POOL" "$SPCS_DIR/specs/api.yaml" \
  "$API_MIN_INSTANCES" "$API_MAX_INSTANCES"

echo "==> [6/7] Deploying locust service ($LOCUST_SERVICE) on pool $LOCUST_COMPUTE_POOL"
spcs_service_upsert "$LOCUST_SERVICE" "$LOCUST_COMPUTE_POOL" "$SPCS_DIR/specs/locust.yaml" 1 1

echo "==> [7/7] Waiting for services to become READY (this can take a few minutes)"
"$SCRIPT_DIR/status.sh" --wait

echo
echo "==> Ingress URLs"
"$SCRIPT_DIR/status.sh" --urls-only
echo
echo "Benchmark API and Locust are ready."
