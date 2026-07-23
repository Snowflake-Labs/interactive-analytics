#!/usr/bin/env bash
# SPCS entrypoint for the benchmark API container.
#
# SPCS injects these env vars into every container:
#   SNOWFLAKE_ACCOUNT, SNOWFLAKE_HOST, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA
# and mounts an OAuth token at /snowflake/session/token.
# We generate a connections.toml so server.py's CONNECTION_NAME path works.

set -euo pipefail

TOKEN_FILE=/snowflake/session/token
CONNECTIONS_DIR=${SNOWFLAKE_HOME:-/root/.snowflake}
CONNECTIONS_FILE="$CONNECTIONS_DIR/connections.toml"

mkdir -p "$CONNECTIONS_DIR"

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "[entrypoint] ERROR: OAuth token file $TOKEN_FILE not found — is this running inside SPCS?" >&2
  exit 1
fi

: "${SNOWFLAKE_HOST:?SNOWFLAKE_HOST must be set by SPCS}"
: "${SNOWFLAKE_ACCOUNT:?SNOWFLAKE_ACCOUNT must be set by SPCS}"

DB="${SNOWFLAKE_DATABASE:-IW_TPCH_BENCH}"

{
  echo '[spcs]'
  echo "account = \"${SNOWFLAKE_ACCOUNT}\""
  echo "host = \"${SNOWFLAKE_HOST}\""
  echo 'authenticator = "OAUTH"'
  echo "token_file_path = \"${TOKEN_FILE}\""
  echo "database = \"${DB}\""
} > "$CONNECTIONS_FILE"

chmod 600 "$CONNECTIONS_FILE"

export SNOWFLAKE_HOME="$CONNECTIONS_DIR"
export CONNECTION_NAME=spcs
export SNOWFLAKE_DEFAULT_CONNECTION_NAME=spcs
export SNOWFLAKE_CLIENT_STORE_TEMPORARY_CREDENTIAL=false
export SNOWFLAKE_DATABASE="$DB"
export PORT="${PORT:-3000}"

echo "[entrypoint] Starting benchmark API on port ${PORT} (db=${DB})."
exec uv run --directory /app/api --no-sync python server.py
