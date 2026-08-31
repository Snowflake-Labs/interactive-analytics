#!/usr/bin/env bash
# Reconfigure the interactive warehouse safely by suspending SPCS services first.
#
# SPCS API workers hold connections to the interactive warehouse and resume it
# on every request, which blocks ALTER WAREHOUSE ... SET WAREHOUSE_SIZE.
# This script deterministically:
#   1. Suspends both SPCS services (Locust + API)
#   2. Waits for connections to drain
#   3. Suspends the warehouse
#   4. Applies size and/or cluster changes
#   5. Resumes the warehouse
#   6. Resumes both SPCS services
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
DRAIN_WAIT=20
MAX_DRAIN_RETRIES=6

# Build description for logging.
DESC=""
[[ -n "$NEW_SIZE" ]] && DESC="size=$NEW_SIZE"
[[ -n "$NEW_MCW" ]]  && DESC="${DESC:+$DESC, }max_cluster_count=$NEW_MCW"

echo "=== Reconfigure interactive warehouse: $FQ_WH ($DESC) ==="
echo

# --- Step 1: Suspend SPCS services ---
echo "[1/6] Suspending SPCS services..."
cat <<EOF | snow_sql_run "suspend services"
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE IF EXISTS $LOCUST_SERVICE SUSPEND;
ALTER SERVICE IF EXISTS $API_SERVICE SUSPEND;
EOF
echo "  ✓ Services suspended."

# --- Step 2: Wait for connections to drain ---
echo "[2/6] Waiting ${DRAIN_WAIT}s for connections to drain..."
sleep "$DRAIN_WAIT"

cat <<EOF | snow_sql_run "abort queries"
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH ABORT ALL QUERIES;
EOF
echo "  ✓ Queries aborted."

# --- Step 3: Suspend the warehouse ---
echo "[3/6] Suspending warehouse..."
retries=0
while (( retries < MAX_DRAIN_RETRIES )); do
  if cat <<EOF | snow_sql_run "suspend warehouse" 2>/dev/null; then
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH SUSPEND;
EOF
    echo "  ✓ Warehouse suspended."
    break
  fi
  retries=$((retries + 1))
  echo "  ⏳ Warehouse still active (attempt $retries/$MAX_DRAIN_RETRIES), waiting ${DRAIN_WAIT}s..."
  sleep "$DRAIN_WAIT"
done

if (( retries == MAX_DRAIN_RETRIES )); then
  echo "  ⚠ Could not suspend warehouse after $MAX_DRAIN_RETRIES attempts — proceeding anyway."
fi

# --- Step 4: Apply changes ---
echo "[4/6] Applying changes..."

if [[ -n "$NEW_SIZE" ]]; then
  cat <<EOF | snow_sql_run "resize warehouse"
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH SET WAREHOUSE_SIZE='$NEW_SIZE';
EOF
  echo "  ✓ Warehouse size set to $NEW_SIZE."
fi

if [[ -n "$NEW_MCW" ]]; then
  cat <<EOF | snow_sql_run "set max cluster count"
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH SET MAX_CLUSTER_COUNT=$NEW_MCW;
EOF
  echo "  ✓ Max cluster count set to $NEW_MCW."
fi

# --- Step 5: Resume warehouse ---
echo "[5/6] Resuming warehouse..."
cat <<EOF | snow_sql_run "resume warehouse"
USE ROLE $ROLE;
ALTER WAREHOUSE $FQ_WH RESUME IF SUSPENDED;
EOF
echo "  ✓ Warehouse resumed."

# --- Step 6: Resume SPCS services ---
echo "[6/6] Resuming SPCS services..."
cat <<EOF | snow_sql_run "resume services"
USE ROLE $ROLE;
USE DATABASE $DB;
USE SCHEMA $SCHEMA;
ALTER SERVICE IF EXISTS $API_SERVICE RESUME;
ALTER SERVICE IF EXISTS $LOCUST_SERVICE RESUME;
EOF
echo "  ✓ Services resumed."

echo
echo "=== Done. $FQ_WH reconfigured ($DESC). ==="
echo "Run ./status.sh --wait to confirm services are back to READY."
