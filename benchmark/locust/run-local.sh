#!/usr/bin/env bash
# Run locust locally against a deployed (or local) benchmark API.
#
# Usage:
#   ./run-local.sh <API_URL> [locust args...]
#
# Examples:
#   ./run-local.sh http://localhost:3000
#   ./run-local.sh https://<spcs-ingress-url> --users 20 --spawn 5 --run-time 2m --headless

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

HOST="${1:?Usage: run-local.sh <API_URL> [locust args...]}"
shift

export BENCHMARK_QUERIES_DIR="${BENCHMARK_QUERIES_DIR:-$REPO_ROOT/benchmark/test}"

echo "==> Queries dir: $BENCHMARK_QUERIES_DIR"
echo "==> Target host: $HOST"

cd "$SCRIPT_DIR"
uv run locust -f locustfile.py --host "$HOST" "$@"
