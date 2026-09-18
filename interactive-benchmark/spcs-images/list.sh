#!/usr/bin/env bash
# List the shared image repository and its images.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1090
source "$SCRIPT_DIR/.env"

: "${CONNECTION:?CONNECTION must be set in .env}"
: "${ROLE:?ROLE must be set in .env}"
: "${DB:?DB must be set in .env}"
: "${SCHEMA:?SCHEMA must be set in .env}"
: "${IMAGE_REPO:?IMAGE_REPO must be set in .env}"

echo "=== Shared Image Resources: ${DB}.${SCHEMA} ==="
echo

echo "--- Image Registry URL ---"
snow spcs image-registry url --connection "$CONNECTION" --role "$ROLE" 2>/dev/null | tr -d '"'
echo

echo "--- Image Repository ---"
snow sql --connection "$CONNECTION" --role "$ROLE" --format json -q \
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
snow sql --connection "$CONNECTION" --role "$ROLE" --format json -q \
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
