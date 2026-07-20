#!/usr/bin/env bash
# SPCS entrypoint for the dashboard container.
#
# SPCS injects these env vars into every container:
#   SNOWFLAKE_ACCOUNT        e.g. myacct
#   SNOWFLAKE_HOST           e.g. myacct.snowflakecomputing.com
#   SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA (from the service DB/schema)
# and mounts an OAuth token at /snowflake/session/token that is valid for the
# service's owner role.  We generate a connections.toml that references that
# token file, so server.py's normal CONNECTION_NAME code path just works.

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

DB="${SNOWFLAKE_DATABASE:-${DASHBOARD_DATABASE:-IW_TPCH_BENCH}}"
ROLE="${SNOWFLAKE_ROLE:-${DASHBOARD_ROLE:-}}"
WAREHOUSE="${SNOWFLAKE_WAREHOUSE:-${DASHBOARD_WAREHOUSE:-}}"

{
  echo '[spcs]'
  echo "account = \"${SNOWFLAKE_ACCOUNT}\""
  echo "host = \"${SNOWFLAKE_HOST}\""
  echo 'authenticator = "OAUTH"'
  echo "token_file_path = \"${TOKEN_FILE}\""
  echo "database = \"${DB}\""
  [[ -n "$ROLE" ]] && echo "role = \"${ROLE}\""
  [[ -n "$WAREHOUSE" ]] && echo "warehouse = \"${WAREHOUSE}\""
} > "$CONNECTIONS_FILE"

chmod 600 "$CONNECTIONS_FILE"

export SNOWFLAKE_HOME="$CONNECTIONS_DIR"
export CONNECTION_NAME=spcs
export SNOWFLAKE_DEFAULT_CONNECTION_NAME=spcs
# OAuth tokens live in the file; don't try to use the OS keyring cache.
export SNOWFLAKE_CLIENT_STORE_TEMPORARY_CREDENTIAL=false
export SNOWFLAKE_DATABASE="$DB"
export PORT="${PORT:-3000}"
export DEFAULT_SCALE="${DEFAULT_SCALE:-100}"

echo "[entrypoint] Starting dashboard on port ${PORT} (db=${DB}, scale=${DEFAULT_SCALE})."
exec uv run --directory /app/api --no-sync python server.py
