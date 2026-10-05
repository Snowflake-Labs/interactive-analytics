#!/usr/bin/env bash
# Reconfigure the interactive warehouse.
#
# --mcw only: ALTER WAREHOUSE ... SET MAX_CLUSTER_COUNT in place. The warehouse,
#             its grants, and its data cache are kept.
# --size:     CREATE OR REPLACE INTERACTIVE WAREHOUSE. ALTER WAREHOUSE ... SET
#             WAREHOUSE_SIZE fails with error 090094 on interactive warehouses
#             that have attached tables, even when suspended. The replace keeps
#             size/cluster settings, attached tables, and FALLBACK_WAREHOUSE, but
#             resets the data cache and drops every grant, comment, and resource
#             monitor. It therefore refuses to run when another role holds a grant
#             on the warehouse or a resource monitor is attached, unless
#             --force-replace is passed.
#
# Both paths suspend Locust (if deployed) so the next resume starts a fresh run
# after the cache has been re-warmed. The replace path also suspends the API
# service and resumes it afterwards.
#
# Usage:
#   resize-wh.sh [--size <SIZE>] [--mcw <MAX_CLUSTER_COUNT>] [--force-replace]
#
# At least one of --size or --mcw must be provided.
#
# Examples:
#   resize-wh.sh --size MEDIUM
#   resize-wh.sh --mcw 5
#   resize-wh.sh --size LARGE --mcw 3

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

usage() {
  echo "Usage: resize-wh.sh [--size <SIZE>] [--mcw <MAX_CLUSTER_COUNT>] [--force-replace]" >&2
  exit 1
}

NEW_SIZE=""
NEW_MCW=""
FORCE_REPLACE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size)          [[ $# -ge 2 ]] || usage
                     NEW_SIZE="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
    --mcw)           [[ $# -ge 2 ]] || usage
                     NEW_MCW="$2"; shift 2 ;;
    --force-replace) FORCE_REPLACE=1; shift ;;
    *)               echo "Unknown option: $1" >&2; usage ;;
  esac
done

if [[ -z "$NEW_SIZE" && -z "$NEW_MCW" ]]; then
  echo "Error: at least one of --size or --mcw must be provided." >&2
  usage
fi
if [[ -n "$NEW_SIZE" && ! "$NEW_SIZE" =~ ^[A-Z0-9-]+$ ]]; then
  echo "Error: invalid --size: $NEW_SIZE" >&2
  exit 1
fi
if [[ -n "$NEW_MCW" && ! "$NEW_MCW" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --mcw must be a positive integer: $NEW_MCW" >&2
  exit 1
fi
validate_unquoted_identifier INTERACTIVE_WAREHOUSE "$INTERACTIVE_WAREHOUSE"

WH="$INTERACTIVE_WAREHOUSE"

sql_rows() {
  snow sql --connection "$CONNECTION" --role "$ROLE" --silent --format json -q "$1"
}

# Prints 1 if the service exists in $DB.$SCHEMA, else 0. SHOW ... IN ACCOUNT
# works before deploy.sh has created the SPCS database.
service_exists() {
  sql_rows "SHOW SERVICES LIKE '$1' IN ACCOUNT" | python3 -c '
import json, sys
name, db, schema = (a.upper() for a in sys.argv[1:])
rows = json.load(sys.stdin)
print(int(any(
    r["name"].upper() == name
    and r["database_name"].upper() == db
    and r["schema_name"].upper() == schema
    for r in rows
)))
' "$1" "$DB" "$SCHEMA"
}

suspend_service() {
  snow_sql_run "suspend $1" <<EOF
USE ROLE $ROLE;
ALTER SERVICE $DB.$SCHEMA.$1 SUSPEND;
EOF
}

# --- Step 1: Read current warehouse properties ---
echo "[1/5] Reading current warehouse properties..."
# LIKE treats '_' as a wildcard, so match the exact name.
WH_PROPS="$(sql_rows "SHOW WAREHOUSES LIKE '$WH'" | python3 -c '
import json, shlex, sys
wh = sys.argv[1].upper()
rows = [r for r in json.load(sys.stdin) if r["name"].upper() == wh]
if len(rows) != 1:
    sys.exit(f"Expected exactly one warehouse named {wh}, found {len(rows)}.")
r = rows[0]
monitor = r.get("resource_monitor") or ""
values = {
    "CURRENT_SIZE": r["size"],
    "CURRENT_MINCW": r["min_cluster_count"],
    "CURRENT_MCW": r["max_cluster_count"],
    "CURRENT_OWNER": r["owner"],
    "CURRENT_MONITOR": "" if monitor.lower() == "null" else monitor,
    "HAS_TABLES_COLUMN": int("tables" in r),
    "CURRENT_TABLES": ",\n        ".join(
        t.strip() for t in (r.get("tables") or "").split(",") if t.strip()
    ),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
' "$WH")"
eval "$WH_PROPS"

CURRENT_FALLBACK="$(sql_rows "SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE $WH" | python3 -c '
import json, sys
rows = [r for r in json.load(sys.stdin) if r["key"].upper() == "FALLBACK_WAREHOUSE"]
if len(rows) != 1:
    sys.exit("Could not read the FALLBACK_WAREHOUSE parameter.")
print(rows[0]["value"] or "")
')"
if [[ -n "$CURRENT_FALLBACK" ]]; then
  validate_unquoted_identifier FALLBACK_WAREHOUSE "$CURRENT_FALLBACK"
fi

SIZE="${NEW_SIZE:-$CURRENT_SIZE}"
MCW="${NEW_MCW:-$CURRENT_MCW}"

echo "  Current: size=$CURRENT_SIZE, min_cluster_count=$CURRENT_MINCW, max_cluster_count=$CURRENT_MCW"
echo "  Fallback warehouse: ${CURRENT_FALLBACK:-<none>}"
echo "  Target:  size=$SIZE, min_cluster_count=$CURRENT_MINCW, max_cluster_count=$MCW"

LOCUST_DEPLOYED="$(service_exists "$LOCUST_SERVICE")"
API_DEPLOYED="$(service_exists "$API_SERVICE")"

# --- Cluster-count-only change: alter in place ---
if [[ -z "$NEW_SIZE" ]]; then
  echo "[2/5] Suspending Locust service..."
  if (( LOCUST_DEPLOYED )); then
    suspend_service "$LOCUST_SERVICE"
    echo "  ✓ Locust suspended."
  else
    echo "  Locust is not deployed yet — skipping."
  fi

  echo "[3/5] Altering interactive warehouse (max_cluster_count=$MCW)..."
  snow_sql_run "alter max_cluster_count" <<EOF
USE ROLE $ROLE;
ALTER WAREHOUSE $WH SET MAX_CLUSTER_COUNT = $MCW;
EOF
  echo "  ✓ Warehouse altered in place; grants, tables, fallback, and cache are unchanged."
  echo "[4/5] No fallback restore needed."
  echo "[5/5] API service was not suspended."
else
  # --- Size change: replace the warehouse ---
  echo "[2/5] Checking what CREATE OR REPLACE would drop..."
  # SHOW WAREHOUSES only has a tables column when the 2026_01 behavior change
  # bundle is enabled; without it the replace would silently detach every table.
  if (( ! HAS_TABLES_COLUMN )); then
    echo "SHOW WAREHOUSES did not return a tables column, so attached tables cannot be" \
      "preserved. Enable the 2026_01 behavior change bundle or resize manually." >&2
    exit 1
  fi
  OTHER_GRANTS="$(sql_rows "SHOW GRANTS ON WAREHOUSE $WH" | python3 -c '
import json, sys
owner = sys.argv[1].upper()
for g in json.load(sys.stdin):
    privilege, kind, grantee = g["privilege"], g["granted_to"], g["grantee_name"]
    if privilege != "OWNERSHIP" and grantee.upper() != owner:
        print(f"    {privilege} to {kind} {grantee}")
' "$CURRENT_OWNER")"
  if [[ -n "$OTHER_GRANTS" || -n "$CURRENT_MONITOR" ]] && (( ! FORCE_REPLACE )); then
    {
      echo "Refusing to replace $WH: CREATE OR REPLACE would drop:"
      [[ -n "$OTHER_GRANTS" ]] && echo "$OTHER_GRANTS"
      [[ -n "$CURRENT_MONITOR" ]] && echo "    resource monitor $CURRENT_MONITOR"
      echo "Resize a benchmark-dedicated warehouse instead, or pass --force-replace."
    } >&2
    exit 1
  fi

  echo "[3/5] Suspending SPCS services..."
  if (( LOCUST_DEPLOYED )); then suspend_service "$LOCUST_SERVICE"; fi
  if (( API_DEPLOYED )); then suspend_service "$API_SERVICE"; fi
  echo "  ✓ Deployed services suspended."

  if [[ -n "$CURRENT_TABLES" ]]; then
    echo "  Attached tables: $(echo "$CURRENT_TABLES" | tr -d '\n' | tr -s ' ')"
    TABLES_CLAUSE="TABLES (
        ${CURRENT_TABLES}
      )"
  else
    echo "  No tables attached."
    TABLES_CLAUSE=""
  fi

  echo "[4/5] Replacing interactive warehouse (size=$SIZE, max_cluster_count=$MCW)..."
  snow_sql_run "replace interactive warehouse" <<EOF
USE ROLE $ROLE;
CREATE OR REPLACE INTERACTIVE WAREHOUSE $WH
  ${TABLES_CLAUSE}
  WAREHOUSE_SIZE = '$SIZE'
  MIN_CLUSTER_COUNT = $CURRENT_MINCW
  MAX_CLUSTER_COUNT = $MCW
  SCALING_POLICY = 'STANDARD'
  AUTO_SUSPEND = 86400
  AUTO_RESUME = TRUE;
EOF
  if [[ -n "$CURRENT_FALLBACK" ]]; then
    snow_sql_run "restore fallback warehouse" <<EOF
USE ROLE $ROLE;
ALTER WAREHOUSE $WH SET FALLBACK_WAREHOUSE = $CURRENT_FALLBACK;
EOF
  fi
  echo "  ✓ Warehouse replaced; fallback warehouse: ${CURRENT_FALLBACK:-<none>}."

  echo "[5/5] Resuming API service (Locust stays suspended until cache is warm)..."
  if (( API_DEPLOYED )); then
    snow_sql_run "resume API service" <<EOF
USE ROLE $ROLE;
ALTER SERVICE $DB.$SCHEMA.$API_SERVICE RESUME;
EOF
    echo "  ✓ API service resumed."
  else
    echo "  API is not deployed yet — skipping."
  fi
fi

echo
echo "=== Done. $WH: size=$SIZE, max_cluster_count=$MCW. ==="
echo "Run the cache warm-up queries before any load test (new clusters start cold)."
if (( LOCUST_DEPLOYED )); then
  echo "After warm-up, resume Locust with:"
  echo "  ALTER SERVICE $DB.$SCHEMA.$LOCUST_SERVICE RESUME;"
fi
