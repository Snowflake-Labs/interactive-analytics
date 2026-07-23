#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec uv run --directory "$SCRIPT_DIR/locust" locust -f locustfile.py \
  --host http://localhost:3000 \
  --headless \
  --only-summary \
  --loglevel WARNING \
  -u 1 \
  -r 1 \
  -t 1m \
  "$@"
