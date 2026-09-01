#!/usr/bin/env bash
# Rebuild + push images and ALTER SERVICE both services in-place (URLs preserved).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

"$SCRIPT_DIR/build-and-push.sh"

alter_service() {
  local svc="$1"
  local spec_file="$2"
  local min_inst="${3:-}"
  local max_inst="${4:-}"
  local rendered
  rendered="$(render_spec "$spec_file")"

  local instance_sql=""
  if [[ -n "$min_inst" && -n "$max_inst" ]]; then
    instance_sql=$'\nALTER SERVICE '"$svc"$' SET\n  MIN_INSTANCES = '"$min_inst"$'\n  MAX_INSTANCES = '"$max_inst"$';'
  fi

  snow_sql_run "alter service $svc" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE $svc FROM SPECIFICATION \$\$
$rendered
\$\$;$instance_sql
EOF
}

echo "==> Updating dashboard API service (min=$DASHBOARD_MIN_INSTANCES, max=$DASHBOARD_MAX_INSTANCES)"
alter_service "$DASHBOARD_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml" \
  "$DASHBOARD_MIN_INSTANCES" "$DASHBOARD_MAX_INSTANCES"

echo "==> Updating isolated locust API service"
alter_service "$LOCUST_API_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml"

echo "==> Updating locust service"
alter_service "$LOCUST_SERVICE" "$SCRIPT_DIR/specs/locust.yaml"

"$SCRIPT_DIR/status.sh" --urls-only
