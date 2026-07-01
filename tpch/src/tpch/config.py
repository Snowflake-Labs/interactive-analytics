from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
QUERIES_DIR = ROOT / "queries"
SQL_DIR = ROOT / "sql"
RESULTS_DIR = ROOT / "results"

WORKLOADS = ("original", "modern")
DEFAULT_WORKLOAD = "original"

load_dotenv(ROOT / ".env", override=False)

DEFAULT_CONNECTION_NAME = os.getenv("CONNECTION_NAME")

BENCH_DATABASE = "IW_TPCH_BENCH"
INTERACTIVE_WH_PREFIX = "IW_TPCH_BENCH_WH"
STANDARD_WH_PREFIX = "TPCH_BENCH_WH"

SCHEMA_PREFIX = "TPCH_SF"

TARGETS = ("interactive", "standard")
DEFAULT_TARGET = "interactive"

class ScaleConfig(TypedDict):
    load_warehouse: str
    benchmark_warehouse: str

SCALES: dict[str, ScaleConfig] = {
    "1": {"load_warehouse": "SMALL", "benchmark_warehouse": "SMALL"},
    "10": {"load_warehouse": "LARGE", "benchmark_warehouse": "MEDIUM"},
    "100": {"load_warehouse": "XLARGE", "benchmark_warehouse": "LARGE"},
    "1000": {"load_warehouse": "XXLARGE", "benchmark_warehouse": "XXLARGE"},
}
DEFAULT_SCALE = os.getenv("DEFAULT_SCALE", "10")

SQL_SCALE = "{{SCALE}}"
SQL_LOAD_WH_SIZE = "{{LOAD_WH_SIZE}}"
SQL_BENCH_WH_SIZE = "{{BENCH_WH_SIZE}}"

def sql_substitutions_for_scale(scale: str) -> dict[str, str]:
    config = SCALES[scale]
    return {
        SQL_SCALE: scale,
        SQL_LOAD_WH_SIZE: config["load_warehouse"],
        SQL_BENCH_WH_SIZE: config["benchmark_warehouse"],
    }


def schema_for_scale(scale: str) -> str:
    return f"{SCHEMA_PREFIX}{scale}"


def interactive_schema_for_scale(scale: str) -> str:
    return f"{schema_for_scale(scale)}_IT"


def schema_for_target(target: str, scale: str) -> str:
    if target == "interactive":
        return interactive_schema_for_scale(scale)
    return schema_for_scale(scale)


def warehouse_name_for_target(target: str, scale: str) -> str:
    prefix = INTERACTIVE_WH_PREFIX if target == "interactive" else STANDARD_WH_PREFIX
    return f"{prefix}_{scale}"


def target_context(
    target: str,
    scale: str,
    *,
    database: str | None = None,
    schema: str | None = None,
    warehouse: str | None = None,
) -> tuple[str, str, str]:
    """Return (database, schema, warehouse) for the requested target + scale."""
    return (
        database or BENCH_DATABASE,
        schema or schema_for_target(target, scale),
        warehouse or warehouse_name_for_target(target, scale),
    )
