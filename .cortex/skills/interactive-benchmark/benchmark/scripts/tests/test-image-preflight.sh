#!/usr/bin/env bash

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPCS_DIR="$(cd "$SCRIPTS_DIR/../spcs" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat >"$TMP_DIR/config.env" <<'EOF'
CONNECTION=test
ROLE=SYSADMIN
DEPLOY_WAREHOUSE=COMPUTE_WH
SOLUTION_NAME=TEST
DB=TEST_DB
SCHEMA=SPCS
QUERIES_STAGE=BENCHMARK_QUERIES
IMAGE_DB=SNOWFLAKE
IMAGE_SCHEMA=IMAGES
IMAGE_REPO=SNOWFLAKE_IMAGES
BENCHMARK_IMAGE=interactive-analytics/interactive-benchmark
IMAGE_TAG=0.2.0
BENCHMARK_IMAGE_ARCH=amd64
API_INSTANCE_FAMILY=CPU_X64_M
LOCUST_INSTANCE_FAMILY=CPU_X64_M
EOF

cat >"$TMP_DIR/snow" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
[[ "$args" == *"--role SYSADMIN"* ]]
[[ "$args" == *"SHOW IMAGES LIKE 'interactive-analytics/interactive-benchmark' IN IMAGE REPOSITORY SNOWFLAKE.IMAGES.SNOWFLAKE_IMAGES"* ]]
cat <<'JSON'
[{"image_name":"interactive-analytics/interactive-benchmark","tags":"0.2.0","digest":"sha256:test","image_path":"snowflake/images/snowflake_images/interactive-analytics/interactive-benchmark:0.2.0"}]
JSON
EOF
chmod +x "$TMP_DIR/snow"

export PATH="$TMP_DIR:$PATH"
export BENCHMARK_CONFIG_ENV="$TMP_DIR/config.env"
# shellcheck disable=SC1090
source "$SCRIPTS_DIR/_lib.sh"

if snow sql --connection test --format json -q "SHOW IMAGES" >/dev/null 2>&1; then
  echo "Snow mock unexpectedly accepted a command without the configured role and SQL." >&2
  exit 1
fi

output="$(preflight_benchmark_image)"
grep -q 'sha256:test' <<<"$output"

IMAGE_TAG=0.2.1
if preflight_benchmark_image >/dev/null 2>&1; then
  echo "Missing immutable tag unexpectedly passed preflight." >&2
  exit 1
fi

for tag in 0.1.0 latest 0.2; do
  IMAGE_TAG=$tag
  if validate_image_config >/dev/null 2>&1; then
    echo "IMAGE_TAG=$tag unexpectedly passed validation." >&2
    exit 1
  fi
done
IMAGE_TAG=0.1.0
old_tag_error="$(validate_image_config 2>&1 || true)"
grep -q "requires image 0.2.0 or later" <<<"$old_tag_error"
IMAGE_TAG=1.0.0
validate_image_config
IMAGE_TAG=0.2.0

BENCHMARK_IMAGE_ARCH=arm64
if validate_pool_architecture >/dev/null 2>&1; then
  echo "Architecture mismatch unexpectedly succeeded." >&2
  exit 1
fi

grep -q 'BENCHMARK_ROLE: "api"' "$SPCS_DIR/specs/api.yaml"
grep -q 'BENCHMARK_ROLE: "locust"' "$SPCS_DIR/specs/locust.yaml"
grep -q 'uid: 65532' "$SPCS_DIR/specs/api.yaml"
grep -q 'gid: 65532' "$SPCS_DIR/specs/api.yaml"

echo "Image preflight contract passed."
