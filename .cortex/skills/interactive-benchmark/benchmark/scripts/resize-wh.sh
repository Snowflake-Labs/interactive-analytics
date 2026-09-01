#!/usr/bin/env bash
# Reconfigure the interactive warehouse by replacing it (DROP + CREATE in one atomic op).
#
# ALTER WAREHOUSE ... SET WAREHOUSE_SIZE fails with error 090094 on interactive
# warehouses that have attached tables — even when suspended. This script uses
# CREATE OR REPLACE INTERACTIVE WAREHOUSE which is atomic and sidesteps the issue.
#
# Because CREATE OR REPLACE drops metadata like FALLBACK_WAREHOUSE, the script
# captures it beforehand and re-applies it after the replace.
#
# Steps:
#   1. Reads current warehouse properties (size, max_cluster_count, fallback)
#   2. Discovers attached interactive tables
#   3. Suspends both SPCS services (Locust + API)
#   4. Replaces the warehouse with new settings + re-attached tables
#   5. Restores fallback warehouse (if any)
#   6. Resumes both SPCS services
#
# Note: after replacement the data cache is cold and warms in the background.
# An XS warehouse warms at ~300-400 MB/s; larger sizes are faster.
# Monitor cache readiness via remote read % in query profile.
#
# Usage:
#   resize-wh.sh [--size <SIZE>] [--mcw <MAX_CLUSTER_COUNT>]
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

# --- Parse arguments ---
NEW_SIZE=""
NEW_MCW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size)  NEW_SIZE="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
    --mcw)   NEW_MCW="$2"; shift 2 ;;
    *)       echo "Unknown option: $1" >&2
             echo "Usage: resize-wh.sh [--size <SIZE>] [--mcw <MAX_CLUSTER_COUNT>]" >&2
             exit 1 ;;
  esac
done

if [[ -z "$NEW_SIZE" && -z "$NEW_MCW" ]]; then
  echo "Error: at least one of --size or --mcw must be provided." >&2
  echo "Usage: resize-wh.sh [--size <SIZE>] [--mcw <MAX_CLUSTER_COUNT>]" >&2
  exit 1
fi

FQ_WH="$INTERACTIVE_WAREHOUSE"

# --- Step 1: Read current warehouse properties ---
echo "[1/6] Reading current warehouse properties..."
CURRENT_PROPS="$(snow_sql_quiet <<EOF
USE ROLE $ROLE;
SHOW WAREHOUSES LIKE '${FQ_WH}';
EOF
)"

# snow sql --format json with multi-statement returns [[{status}], [{row},...]].
# This helper extracts the last non-empty sub-array of dicts.
_PY_UNWRAP='import sys,json
data=json.load(sys.stdin)
if data and isinstance(data[0],list):
    for sub in reversed(data):
        if sub and isinstance(sub[0],dict): data=sub; break
'

CURRENT_SIZE="$(echo "$CURRENT_PROPS" | python3 -c "
${_PY_UNWRAP}
print(data[-1].get('size','XSMALL') or 'XSMALL' if data else 'XSMALL')
")"
CURRENT_MCW="$(echo "$CURRENT_PROPS" | python3 -c "
${_PY_UNWRAP}
print(data[-1].get('max_cluster_count',1) if data else 1)
")"
CURRENT_FALLBACK="$(echo "$CURRENT_PROPS" | python3 -c "
${_PY_UNWRAP}
fb = data[-1].get('fallback_warehouse', '') if data else ''
print(fb if fb else '')
" 2>/dev/null || true)"

# Apply overrides: keep current value for anything not specified.
SIZE="${NEW_SIZE:-$CURRENT_SIZE}"
MCW="${NEW_MCW:-$CURRENT_MCW}"

# Build description for logging.
DESC=""
[[ -n "$NEW_SIZE" ]] && DESC="size=$NEW_SIZE"
[[ -n "$NEW_MCW" ]]  && DESC="${DESC:+$DESC, }max_cluster_count=$NEW_MCW"

echo "  Current: size=$CURRENT_SIZE, max_cluster_count=$CURRENT_MCW"
[[ -n "$CURRENT_FALLBACK" ]] && echo "  Fallback warehouse: $CURRENT_FALLBACK"
echo "  Target:  size=$SIZE, max_cluster_count=$MCW"

# --- Step 2: Discover attached interactive tables ---
echo "[2/6] Discovering attached interactive tables..."
ATTACHED_TABLES="$(snow_sql_quiet <<EOF
USE ROLE $ROLE;
SHOW INTERACTIVE TABLES IN SCHEMA ${API_DATABASE}.${INTERACTIVE_SCHEMA};
EOF
)"
TABLE_LIST="$(echo "$ATTACHED_TABLES" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Unwrap multi-statement [[{status}],[{rows},...]] to flat list of dicts
if data and isinstance(data[0], list):
    flat = []
    for sub in data:
        if isinstance(sub, list):
            flat.extend(sub)
    data = flat
names = [r['name'] for r in data if isinstance(r, dict) and r.get('warehouse_name','').upper() == '${FQ_WH}'.upper()]
if names:
    print(',\n        '.join(f'${API_DATABASE}.${INTERACTIVE_SCHEMA}.{n}' for n in names))
" 2>/dev/null || true)"

if [[ -n "$TABLE_LIST" ]]; then
  echo "  Attached tables: $(echo "$TABLE_LIST" | tr '\n' ' ')"
  TABLES_CLAUSE="TABLES (
        ${TABLE_LIST}
      )"
else
  echo "  No interactive tables attached."
  TABLES_CLAUSE=""
fi

echo
echo "=== Reconfigure interactive warehouse: $FQ_WH ($DESC) ==="
echo

# --- Step 3: Suspend SPCS services ---
echo "[3/6] Suspending SPCS services..."
snow_sql_run "suspend services" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE IF EXISTS $LOCUST_SERVICE SUSPEND;
ALTER SERVICE IF EXISTS $API_SERVICE SUSPEND;
EOF
echo "  ✓ Services suspended."

# --- Step 4: Replace the warehouse ---
echo "[4/6] Replacing interactive warehouse (size=$SIZE, max_cluster_count=$MCW)..."
snow_sql_run "replace interactive warehouse" <<EOF
USE ROLE $ROLE;
CREATE OR REPLACE INTERACTIVE WAREHOUSE $FQ_WH
  ${TABLES_CLAUSE}
  WAREHOUSE_SIZE = '$SIZE'
  MIN_CLUSTER_COUNT = 1
  MAX_CLUSTER_COUNT = $MCW
  SCALING_POLICY = 'STANDARD'
  AUTO_SUSPEND = 86400
  AUTO_RESUME = TRUE;
EOF
echo "  ✓ Warehouse replaced."

# --- Step 5: Restore fallback warehouse ---
if [[ -n "$CURRENT_FALLBACK" ]]; then
  echo "[5/6] Restoring fallback warehouse ($CURRENT_FALLBACK)..."
  snow_sql_run "set fallback warehouse" <<EOF
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH SET FALLBACK_WAREHOUSE = $CURRENT_FALLBACK;
EOF
  echo "  ✓ Fallback warehouse restored."
else
  echo "[5/6] No fallback warehouse to restore — skipping."
fi

# --- Step 6: Resume SPCS services ---
echo "[6/6] Resuming SPCS services..."
snow_sql_run "resume services" <<EOF
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE IF EXISTS $API_SERVICE RESUME;
ALTER SERVICE IF EXISTS $LOCUST_SERVICE RESUME;
EOF
echo "  ✓ Services resumed."

echo
echo "=== Done. $FQ_WH reconfigured ($DESC). ==="
echo "Note: cache is cold after replacement and warms in the background."
echo "Queries may see higher latency until warm (check remote read % in query profile)."
echo "Run $SCRIPT_DIR/status.sh --wait to confirm services are back to READY."
