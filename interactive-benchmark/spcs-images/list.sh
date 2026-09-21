#!/usr/bin/env bash
# List the shared image repository and its images.
#
# Usage:
#   list.sh                          # uses .env in this directory
#   list.sh --config /path/to/.env   # uses a custom config

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Load common config and print connection info ---------------------------
SCRIPT_ARGS=("$@")
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

echo "=== Shared Image Resources: ${DB}.${SCHEMA} ==="
echo

echo "--- Image Registry URL ---"
snow spcs image-registry url --connection "$CONNECTION" --role "$ROLE" 2>/dev/null | tr -d '"'
echo

echo "--- Image Repository ---"
snow_sql --format json -q \
  "SHOW IMAGE REPOSITORIES LIKE '${IMAGE_REPO}' IN SCHEMA ${DB}.${SCHEMA}" 2>/dev/null \
  | python3 -c '
import json, sys
data = sys.stdin.read().strip()
if not data:
    print("  (none — database or schema does not exist yet)")
else:
    rows = json.loads(data)
    if not rows:
        print("  (none)")
    else:
        for r in rows:
            name = r.get("name") or r.get("NAME")
            url = r.get("repository_url") or r.get("REPOSITORY_URL") or ""
            print(f"  {name:30s} {url}")
'
echo

echo "--- Images ---"
snow_sql --format json -q \
  "SHOW IMAGES IN IMAGE REPOSITORY ${DB}.${SCHEMA}.${IMAGE_REPO}" 2>/dev/null \
  | python3 -c '
import json, sys
data = sys.stdin.read().strip()
if not data:
    print("  (none — image repository does not exist yet)")
else:
    rows = json.loads(data)
    if not rows:
        print("  (none)")
    else:
        for r in rows:
            image = r.get("image_path") or r.get("IMAGE_PATH") or r.get("image_name") or r.get("IMAGE_NAME") or "?"
            tag = r.get("tag") or r.get("TAG") or ""
            size = r.get("image_size") or r.get("IMAGE_SIZE") or ""
            created = r.get("created_on") or r.get("CREATED_ON") or ""
            print(f"  {image}:{tag}  size={size}  created={created}")
'
echo
