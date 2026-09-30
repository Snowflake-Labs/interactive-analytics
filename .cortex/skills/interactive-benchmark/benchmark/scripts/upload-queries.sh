#!/usr/bin/env bash
# Upload benchmark .sql files to the Snowflake stage.
#
# Usage:
#   upload-queries.sh              # replaces the stage's .sql files with $BENCHMARK_QUERY_DIR/*.sql
#   upload-queries.sh /path/to/*.sql   # adds/overwrites the specified files
#
# After uploading, restart the API service so it picks up the new queries:
#   snow spcs service restart $API_SERVICE --connection $CONNECTION \
#       --role $ROLE --dbname $DB --schema $SCHEMA

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_lib.sh"

STAGE_PATH="@${DB}.${SCHEMA}.${QUERIES_STAGE}"
TEST_DIR="$BENCHMARK_QUERY_DIR"

# Accept explicit file list or default to $BENCHMARK_QUERY_DIR/*.sql (benchmark/test/)
if (( $# > 0 )); then
  files=("$@")
else
  shopt -s nullglob
  files=("$TEST_DIR"/*.sql)
  shopt -u nullglob
fi

if (( ${#files[@]} == 0 )); then
  echo "No .sql files found to upload." >&2
  exit 1
fi

# The API benchmarks every .sql file on the stage, so a full upload must not
# leave files from a previous run behind.
if (( $# == 0 )); then
  echo "Removing existing .sql files from ${STAGE_PATH}"
  snow sql --connection "$CONNECTION" --role "$ROLE" --silent -q \
    "REMOVE ${STAGE_PATH} PATTERN = '.*[.]sql'" >/dev/null
fi

echo "Uploading ${#files[@]} query file(s) to ${STAGE_PATH}:"

for f in "${files[@]}"; do
  fname="$(basename "$f")"
  echo "  - $fname"
  snow stage copy "$f" "${STAGE_PATH}/" \
    --connection "$CONNECTION" --role "$ROLE" --overwrite
done

echo "Done. ${#files[@]} file(s) uploaded to ${STAGE_PATH}."
