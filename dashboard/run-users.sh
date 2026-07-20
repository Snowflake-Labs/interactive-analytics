#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCUST_DIR="$SCRIPT_DIR/locust"

usage() {
  echo "Usage: $0 <warehouse>" >&2
  echo "  warehouse: interactive | standard" >&2
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

WAREHOUSE="$1"
export WAREHOUSE

exec uv run --directory "$LOCUST_DIR" locust -f locustfile.py \
  --host http://localhost:3000 \
  --headless \
  --only-summary \
  --loglevel WARNING \
  -u 5 \
  -r 5 \
  -t 5m
