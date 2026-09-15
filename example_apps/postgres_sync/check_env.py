"""Confirm Snowflake and Snowflake Postgres connectivity using .env config.

Usage:
    uv run check_env.py
"""

import os
import sys
import tomllib
from pathlib import Path

import psycopg2
import snowflake.connector

ENV_PATH = Path(__file__).parent / ".env"


def load_config() -> dict:
    if not ENV_PATH.exists():
        print(f"Config file not found: {ENV_PATH}")
        print("Copy .env.example to .env and fill it in.")
        sys.exit(1)
    with ENV_PATH.open("rb") as f:
        return tomllib.load(f)


def section(cfg: dict) -> dict:
    """Returns the config table.

    The table name in .env is arbitrary: the first table in the file is used, so
    `[default]`, `[pm]`, `[prod]` all work. Set CONFIG_SECTION to pick one
    explicitly when the file holds several.
    """
    tables = {k: v for k, v in cfg.items() if isinstance(v, dict)}
    if not tables:
        print("No [table] section in .env - see .env.example")
        sys.exit(1)
    wanted = os.environ.get("CONFIG_SECTION")
    if wanted:
        if wanted not in tables:
            print(f"CONFIG_SECTION={wanted} not in .env. Available: {', '.join(tables)}")
            sys.exit(1)
        return tables[wanted]
    return next(iter(tables.values()))


def check_snowflake(cfg: dict) -> bool:
    pm = section(cfg)
    token_path = Path(__file__).parent / pm["token_file_path"]
    token = token_path.read_text().strip()

    print("Connecting to Snowflake...")
    try:
        conn = snowflake.connector.connect(
            account=pm["account"],
            user=pm["user"],
            role=pm["role"],
            warehouse=pm["warehouse"],
            database=pm["database"],
            schema=pm["schema"],
            authenticator=pm["authenticator"],
            token=token,
        )
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_VERSION(), CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
        version, user, role, warehouse = cur.fetchone()
        print(f"  OK - version={version} user={user} role={role} warehouse={warehouse}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  FAILED - {e}")
        return False


def check_postgres(cfg: dict) -> bool:
    pm = section(cfg)
    print("Connecting to Postgres...")
    try:
        conn = psycopg2.connect(
            host=pm["PGHOST"],
            port=pm["PGPORT"],
            user=pm["PGUSER"],
            password=pm["PGPASSWORD"],
            dbname=pm["PGDATABASE"],
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute("SELECT version()")
        (version,) = cur.fetchone()
        print(f"  OK - {version}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  FAILED - {e}")
        return False


def main() -> None:
    cfg = load_config()
    sf_ok = check_snowflake(cfg)
    pg_ok = check_postgres(cfg)

    print()
    print(f"Snowflake: {'OK' if sf_ok else 'FAILED'}")
    print(f"Postgres:  {'OK' if pg_ok else 'FAILED'}")

    if not (sf_ok and pg_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
