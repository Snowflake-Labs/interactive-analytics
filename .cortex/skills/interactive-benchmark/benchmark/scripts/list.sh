#!/usr/bin/env bash
# List all SPCS resources created by deploy.sh: image registry, repositories,
# services, and compute pools.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

echo "=== SPCS Resources for ${DB}.${SCHEMA} ==="
echo

echo "--- Image Registry URL ---"
registry_url
echo

echo "--- Image Repositories ---"
snow sql --connection "$CONNECTION" --format json -q \
  "SHOW IMAGE REPOSITORIES IN SCHEMA ${DB}.${SCHEMA}" 2>/dev/null \
  | python3 -c '
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print("  (none)")
else:
    for r in rows:
        name = r.get("name") or r.get("NAME")
        url = r.get("repository_url") or r.get("REPOSITORY_URL") or ""
        print(f"  {name:30s} {url}")
'
echo

echo "--- Services ---"
snow sql --connection "$CONNECTION" --format json -q \
  "SHOW SERVICES IN SCHEMA ${DB}.${SCHEMA}" 2>/dev/null \
  | python3 -c '
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print("  (none)")
else:
    for r in rows:
        name = r.get("name") or r.get("NAME")
        status = r.get("status") or r.get("STATUS") or "?"
        pool = r.get("compute_pool") or r.get("COMPUTE_POOL") or ""
        print(f"  {name:30s} {status:12s} pool={pool}")
'
echo

echo "--- Compute Pools ---"
snow sql --connection "$CONNECTION" --format json -q \
  "SHOW COMPUTE POOLS LIKE '${SOLUTION_NAME}_BENCH%'" 2>/dev/null \
  | python3 -c '
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print("  (none)")
else:
    for r in rows:
        name = r.get("name") or r.get("NAME")
        state = r.get("state") or r.get("STATE") or "?"
        family = r.get("instance_family") or r.get("INSTANCE_FAMILY") or ""
        min_n = r.get("min_nodes") or r.get("MIN_NODES") or ""
        max_n = r.get("max_nodes") or r.get("MAX_NODES") or ""
        print(f"  {name:35s} {state:12s} {family} (nodes: {min_n}-{max_n})")
'
echo
