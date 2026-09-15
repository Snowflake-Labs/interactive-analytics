"""Shared Postgres connection helpers, reusing the .env TOML conventions from
check_env.py (see ../check_env.py).
"""

import os
import sys
import tomllib
from pathlib import Path

import psycopg2

# Locally, .env lives in the project root (one level above data_gen/). In the
# container image, data_gen/ scripts and the root .env are flattened into the
# same directory, so check both locations.
_CANDIDATE_ENV_PATHS = [
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent / ".env",
]


def load_config() -> dict:
    for path in _CANDIDATE_ENV_PATHS:
        if path.exists():
            with path.open("rb") as f:
                return tomllib.load(f)
    print(f"Config file not found in any of: {_CANDIDATE_ENV_PATHS}")
    sys.exit(1)


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


def get_pg_conn(cfg: dict):
    pm = section(cfg)
    return psycopg2.connect(
        host=pm["PGHOST"],
        port=pm["PGPORT"],
        user=pm["PGUSER"],
        password=pm["PGPASSWORD"],
        dbname=pm["PGDATABASE"],
        connect_timeout=10,
    )


def pg_relation_size_bytes(conn, schema: str, table: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT pg_total_relation_size(%s)", (f"{schema}.{table}",))
    (size,) = cur.fetchone()
    cur.close()
    return int(size)
