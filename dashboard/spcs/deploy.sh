#!/usr/bin/env bash
# Deploy script supporting two actions:
#   sql      — run the create_lineitem_dashboard SQL (substituting SOLUTION_NAME and SCALE)
#   services — full SPCS deploy (prerequisites, build, push, create services)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

ACTION="${1:-}"

if [[ -z "$ACTION" ]]; then
  echo "Usage: deploy.sh <sql|services>" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Action: sql
# ---------------------------------------------------------------------------
deploy_sql() {
  local scale="${DEFAULT_SCALE:-10}"
  local sql_file="$REPO_DIR/sql/create_lineitem_dashboard.sql"

  if [[ ! -f "$sql_file" ]]; then
    echo "Error: SQL file not found: $sql_file" >&2
    exit 1
  fi

  echo "==> Running create_lineitem_dashboard.sql (SOLUTION_NAME=$SOLUTION_NAME, SCALE=$scale)"

  local rendered
  rendered="$(sed -e "s/{{SOLUTION_NAME}}/${SOLUTION_NAME}/g" \
                  -e "s/{{SCALE}}/${scale}/g" \
                  "$sql_file")"

  snow_sql_run "create_lineitem_dashboard" <<< "$rendered"

  echo "==> Done."
}

# ---------------------------------------------------------------------------
# Action: services
# ---------------------------------------------------------------------------
deploy_services() {
  echo "==> [1/6] Setting up database, schema, compute pools, image repo"
  snow_sql_run "prerequisites setup" <<EOF
USE ROLE $ROLE;
USE WAREHOUSE $DEPLOY_WAREHOUSE;

CREATE DATABASE IF NOT EXISTS $DB;
USE DATABASE $DB;

CREATE SCHEMA IF NOT EXISTS $SCHEMA;
USE SCHEMA $SCHEMA;

CREATE COMPUTE POOL IF NOT EXISTS $DASHBOARD_COMPUTE_POOL
  MIN_NODES = $DASHBOARD_MIN_NODES
  MAX_NODES = $DASHBOARD_MAX_NODES
  INSTANCE_FAMILY = $DASHBOARD_INSTANCE_FAMILY
  AUTO_RESUME = TRUE;

ALTER COMPUTE POOL $DASHBOARD_COMPUTE_POOL RESUME IF SUSPENDED;

CREATE COMPUTE POOL IF NOT EXISTS $LOCUST_COMPUTE_POOL
  MIN_NODES = $LOCUST_MIN_NODES
  MAX_NODES = $LOCUST_MAX_NODES
  INSTANCE_FAMILY = $LOCUST_INSTANCE_FAMILY
  AUTO_RESUME = TRUE;

ALTER COMPUTE POOL $LOCUST_COMPUTE_POOL RESUME IF SUSPENDED;

CREATE IMAGE REPOSITORY IF NOT EXISTS $IMAGE_REPO;
EOF

  echo "==> [2/6] Building and pushing container images"
  "$SCRIPT_DIR/build-and-push.sh"

  deploy_service() {
    local svc="$1"
    local spec_file="$2"
    local pool="$3"

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
  MIN_INSTANCES = 1
  MAX_INSTANCES = 1
  COMMENT = 'Managed by dashboard/spcs/';

ALTER SERVICE $svc FROM SPECIFICATION \$\$
$rendered
\$\$;
EOF
  }

  echo "==> [3/6] Deploying dashboard API service ($DASHBOARD_SERVICE) on pool $DASHBOARD_COMPUTE_POOL"
  deploy_service "$DASHBOARD_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml" "$DASHBOARD_COMPUTE_POOL"

  echo "==> [4/6] Deploying isolated API server for locust ($LOCUST_API_SERVICE) on pool $LOCUST_COMPUTE_POOL"
  deploy_service "$LOCUST_API_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml" "$LOCUST_COMPUTE_POOL"

  echo "==> [5/6] Deploying locust service ($LOCUST_SERVICE) on pool $LOCUST_COMPUTE_POOL"
  deploy_service "$LOCUST_SERVICE" "$SCRIPT_DIR/specs/locust.yaml" "$LOCUST_COMPUTE_POOL"

  echo "==> [6/6] Waiting for services to become READY (this can take a few minutes)"
  "$SCRIPT_DIR/status.sh" --wait

  echo
  echo "==> Ingress URLs"
  "$SCRIPT_DIR/status.sh" --urls-only
  echo
  echo "Open the dashboard URL in your browser (Snowflake login will prompt on first visit)."
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "$ACTION" in
  sql)
    deploy_sql
    ;;
  services)
    deploy_services
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    echo "Usage: deploy.sh <sql|services>" >&2
    exit 1
    ;;
esac
