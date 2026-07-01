#!/usr/bin/env bash
set -euo pipefail

# Thin wrapper around the iw-tpch CLI (same as `uv run iw-tpch`).
# Forwards all arguments unchanged.
#
# Usage:
#   ./iwtpch.sh setup --scale 10
#   ./iwtpch.sh run --target interactive --scale 10 --workload original
#   ./iwtpch.sh run --target standard --scale 100 --queries 2,11,15 --repeats 5
#   ./iwtpch.sh teardown
#
# Run `./iwtpch.sh --help` for full CLI options.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

exec uv run iw-tpch "$@"
