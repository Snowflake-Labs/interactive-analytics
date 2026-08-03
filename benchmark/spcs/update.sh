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
  local rendered
  rendered="$(render_spec "$spec_file")"

  snow_sql_run "alter service $svc" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE $svc FROM SPECIFICATION \$\$
$rendered
\$\$;
EOF
}

echo "==> Updating dashboard API service"
alter_service "$DASHBOARD_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml"

echo "==> Updating isolated locust API service"
alter_service "$LOCUST_API_SERVICE" "$SCRIPT_DIR/specs/dashboard.yaml"

echo "==> Updating locust service"
alter_service "$LOCUST_SERVICE" "$SCRIPT_DIR/specs/locust.yaml"

"$SCRIPT_DIR/status.sh" --urls-only
