#!/usr/bin/env bash
# Shared setup for SPCS image scripts.
# Sourced (not executed) by build-and-push.sh and teardown.sh.
#
# What it does:
#   1. Parses --config <path> from $SCRIPT_ARGS (caller must set it)
#   2. Loads and validates the config file
#   3. Defines snow_sql() helper
#   4. Prints connection info (connection, account, database, schema, role)
#
# Callers must set SCRIPT_DIR before sourcing this file.
# Callers handle their own extra flags (--create-db, --drop-db, etc.)
# by pre-parsing SCRIPT_ARGS and passing the remainder here.

# --- Parse --config from caller-provided args --------------------------------
CONFIG_FILE=""
_REMAINING_ARGS=()
while (( ${#SCRIPT_ARGS[@]} )); do
  case "${SCRIPT_ARGS[0]}" in
    --config) CONFIG_FILE="${SCRIPT_ARGS[1]}"; SCRIPT_ARGS=("${SCRIPT_ARGS[@]:2}") ;;
    *)        _REMAINING_ARGS+=("${SCRIPT_ARGS[0]}"); SCRIPT_ARGS=("${SCRIPT_ARGS[@]:1}") ;;
  esac
done
SCRIPT_ARGS=("${_REMAINING_ARGS[@]+"${_REMAINING_ARGS[@]}"}")
unset _REMAINING_ARGS

if [[ -z "$CONFIG_FILE" ]]; then
  CONFIG_FILE="$SCRIPT_DIR/.env"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config file not found: $CONFIG_FILE" >&2
  echo "Create .env or pass --config /path/to/.env" >&2
  exit 1
fi

# --- Load and validate config ------------------------------------------------
# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${CONNECTION:?CONNECTION must be set in config}"
: "${ROLE:?ROLE must be set in config}"
: "${DB:?DB must be set in config}"
: "${SCHEMA:?SCHEMA must be set in config}"
: "${IMAGE_REPO:?IMAGE_REPO must be set in config}"

# --- Helpers -----------------------------------------------------------------
snow_sql() {
  snow sql --connection "$CONNECTION" --role "$ROLE" "$@"
}

# --- Check snow CLI is available ---------------------------------------------
command -v snow >/dev/null 2>&1 || { echo "Required command not found: snow" >&2; exit 1; }

# --- Print connection info ---------------------------------------------------
echo ""
echo "Connecting to:"
echo ""
echo "  Connection:  $CONNECTION"
echo "  Database:    $DB"
echo "  Schema:      $SCHEMA"
echo "  Role:        $ROLE"
echo ""
ACCOUNT=$(snow_sql -q "SELECT CURRENT_ACCOUNT()" --format json 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['CURRENT_ACCOUNT()'])" 2>/dev/null \
  || echo "unknown")
echo "  Account:     $ACCOUNT"
echo ""
