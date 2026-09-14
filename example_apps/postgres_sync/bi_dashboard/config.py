"""Shared configuration loader for the bi_dashboard tooling.

`.env` is TOML (not dotenv), and holds every environment-specific value in one
place so nothing is duplicated across the Cube env file, the container spec and
the deploy commands.

The table name is not fixed: the first table in the file is used, so `[default]`,
`[pm]`, `[prod]` all work. Set CONFIG_SECTION to pick a specific one when the file
holds several.
"""

import os
import sys
import tomllib
from pathlib import Path
from typing import Any

# The project root (one level above bi_dashboard/), then bi_dashboard/ itself:
# container images flatten these into the same directory.
_SEARCH_DIRS = [Path(__file__).parent.parent, Path(__file__).parent]

# Anything not present in .env falls back to these, so a minimal .env still works.
DEFAULTS: dict[str, Any] = {
    "bi_schema": "BI",
    "fact_table": "FCT_TRANSACTIONS",
    "dim_product_table": "DIM_PRODUCT",
    "dim_user_table": "DIM_USER",
    "source_schema": "SYNC_DEMO",
    "pg_schema": "sync_demo",
    "pg_ssl": True,
    "PGPORT": 5432,
    "PGDATABASE": "postgres",
    "tile_concurrency": 32,
    "external_access_integration": "",
    "schema": "PUBLIC",
}

REQUIRED = [
    "account",
    "user",
    "role",
    "interactive_warehouse",
    "bi_database",
    "PGHOST",
    "PGUSER",
    "PGPASSWORD",
    "data_start",
    "data_end",
    "data_end_ts",
]


def _config_path() -> Path:
    for base in _SEARCH_DIRS:
        candidate = base / ".env"
        if candidate.exists():
            return candidate
    print(
        "No .env found. Copy .env.example to .env and fill it in:\n"
        f"  cp {_SEARCH_DIRS[0] / '.env.example'} {_SEARCH_DIRS[0] / '.env'}",
        file=sys.stderr,
    )
    sys.exit(1)


def load() -> dict[str, Any]:
    """Returns the merged config table, defaults applied, required keys checked."""
    path = _config_path()
    with path.open("rb") as f:
        doc = tomllib.load(f)

    tables = {k: v for k, v in doc.items() if isinstance(v, dict)}
    if not tables:
        print(f"{path} has no [table] section — see .env.example", file=sys.stderr)
        sys.exit(1)

    wanted = os.environ.get("CONFIG_SECTION")
    if wanted:
        if wanted not in tables:
            print(
                f"CONFIG_SECTION={wanted} not found in {path}. "
                f"Available: {', '.join(tables)}",
                file=sys.stderr,
            )
            sys.exit(1)
        section = tables[wanted]
    else:
        section = next(iter(tables.values()))

    cfg = {**DEFAULTS, **section}

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        print(
            f"{path} is missing required keys: {', '.join(missing)}\n"
            "See .env.example for what each one means.",
            file=sys.stderr,
        )
        sys.exit(1)

    placeholders = [k for k, v in cfg.items() if isinstance(v, str) and v.startswith("<")]
    if placeholders:
        print(
            f"{path} still has unfilled placeholders: {', '.join(sorted(placeholders))}",
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg


def read_token(cfg: dict[str, Any]) -> str:
    """Reads the PAT referenced by token_file_path."""
    name = cfg.get("token_file_path")
    if not name:
        print("token_file_path is not set in .env", file=sys.stderr)
        sys.exit(1)
    for base in _SEARCH_DIRS:
        p = base / name
        if p.exists():
            return p.read_text().strip()
    print(f"Token file {name} not found in {[str(d) for d in _SEARCH_DIRS]}", file=sys.stderr)
    sys.exit(1)


def fqn(cfg: dict[str, Any], table_key: str) -> str:
    """Fully qualified name of one of the BI tables."""
    return f"{cfg['bi_database']}.{cfg['bi_schema']}.{cfg[table_key]}"
