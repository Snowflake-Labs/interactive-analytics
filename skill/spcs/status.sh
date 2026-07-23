#!/usr/bin/env bash
# Print service status and public ingress URLs.
#
# Usage:
#   status.sh              print status + endpoints for both services
#   status.sh --wait       poll until both services report state RUNNING
#   status.sh --urls-only  print only "<service>: https://<url>" lines

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

MODE="${1:-full}"

service_state() {
  local svc="$1"
  snow spcs service describe "${DB}.${SCHEMA}.${svc}" \
    --connection "$CONNECTION" --format json 2>/dev/null \
    | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
if not rows:
    print("")
    sys.exit(0)
row = rows[0] if isinstance(rows, list) else rows
for key in ("status", "STATUS", "state", "STATE"):
    if key in row and row[key]:
        print(row[key])
        sys.exit(0)
print("")
' || true
}

service_url() {
  local svc="$1"
  snow spcs service list-endpoints "${DB}.${SCHEMA}.${svc}" \
    --connection "$CONNECTION" --format json 2>/dev/null \
    | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for r in rows or []:
    name = r.get("name") or r.get("NAME")
    url  = r.get("ingress_url") or r.get("INGRESS_URL")
    if name == "web" and url:
        print(url)
        break
' || true
}

wait_ready() {
  local svc="$1"
  local tries=60
  while (( tries > 0 )); do
    local state
    state="$(service_state "$svc")"
    echo "[$svc] state=${state:-unknown}"
    if [[ "$state" == "RUNNING" || "$state" == "READY" ]]; then
      return 0
    fi
    if [[ "$state" == "FAILED" ]]; then
      echo "[$svc] service FAILED — check ./logs.sh $svc" >&2
      return 1
    fi
    sleep 10
    tries=$((tries-1))
  done
  echo "[$svc] did not reach RUNNING within timeout" >&2
  return 1
}

case "$MODE" in
  --wait)
    wait_ready "$DASHBOARD_SERVICE"
    wait_ready "$LOCUST_API_SERVICE"
    wait_ready "$LOCUST_SERVICE"
    ;;
  --urls-only)
    du="$(service_url "$DASHBOARD_SERVICE")"
    au="$(service_url "$LOCUST_API_SERVICE")"
    lu="$(service_url "$LOCUST_SERVICE")"
    [[ -n "$du" ]] && echo "dashboard:      https://$du"
    [[ -n "$au" ]] && echo "locust-api:     https://$au"
    [[ -n "$lu" ]] && echo "locust:         https://$lu"
    ;;
  *)
    for svc in "$DASHBOARD_SERVICE" "$LOCUST_API_SERVICE" "$LOCUST_SERVICE"; do
      echo "=== $svc ==="
      snow spcs service describe "${DB}.${SCHEMA}.${svc}" --connection "$CONNECTION" || true
      snow spcs service list-endpoints "${DB}.${SCHEMA}.${svc}" --connection "$CONNECTION" || true
      echo
    done
    ;;
esac
