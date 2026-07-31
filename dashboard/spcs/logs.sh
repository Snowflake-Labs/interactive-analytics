#!/usr/bin/env bash
# Tail logs from one of the services.
#
# Usage:
#   logs.sh dashboard  [container]   default container: dashboard
#   logs.sh locust-api [container]   default container: dashboard
#   logs.sh locust     [container]   default container: locust

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

target="${1:-}"
case "$target" in
  dashboard)  svc="$DASHBOARD_SERVICE";   default_container="dashboard" ;;
  locust-api) svc="$LOCUST_API_SERVICE";  default_container="dashboard" ;;
  locust)     svc="$LOCUST_SERVICE";      default_container="locust" ;;
  *) echo "Usage: $0 <dashboard|locust-api|locust> [container]" >&2; exit 1 ;;
esac

container="${2:-$default_container}"

snow spcs service logs "${DB}.${SCHEMA}.${svc}" \
  --connection "$CONNECTION" \
  --container-name "$container" \
  --instance-id 0
