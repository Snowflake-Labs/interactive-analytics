#!/usr/bin/env bash
# Rebuild + push images and ALTER SERVICE both services in-place (URLs preserved).
#
# Flags:
#   --queries-only   Upload new .sql files to the stage and restart the API
#                    service without rebuilding any Docker images.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

QUERIES_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --queries-only) QUERIES_ONLY=true ;;
  esac
done

if $QUERIES_ONLY; then
  echo "==> Uploading queries to stage (--queries-only)"
  "$SCRIPT_DIR/upload-queries.sh"
  echo "==> Restarting API service to pick up new queries"
  snow spcs service restart "$API_SERVICE" \
    --connection "$CONNECTION" --role "$ROLE" \
    --dbname "$DB" --schema "$SCHEMA"
  echo "Done. API service is restarting with the new queries."
  exit 0
fi

"$SCRIPT_DIR/upload-queries.sh"
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

echo "==> Updating API service"
alter_service "$API_SERVICE" "$SPCS_DIR/specs/api.yaml"

echo "==> Updating locust service"
alter_service "$LOCUST_SERVICE" "$SPCS_DIR/specs/locust.yaml"

"$SCRIPT_DIR/status.sh" --urls-only
