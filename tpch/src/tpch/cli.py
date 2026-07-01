from __future__ import annotations

import argparse

from src.tpch.commands import cmd_run, cmd_setup, cmd_teardown
from src.tpch.config import (
    DEFAULT_SCALE,
    DEFAULT_TARGET,
    DEFAULT_WORKLOAD,
    SCALES,
    TARGETS,
    WORKLOADS,
)


def _add_connection_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--connection",
        default=None,
        help="Snowflake connection name from connections.toml (default: CONNECTION_NAME env var)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TPC-H benchmark on Snowflake Interactive Warehouse")
    sub = p.add_subparsers(dest="command", required=True)

    setup_p = sub.add_parser("setup", help="Create database, interactive tables and warehouse")
    setup_p.add_argument(
        "--scale",
        choices=tuple(SCALES),
        default=DEFAULT_SCALE,
        help=f"TPC-H scale factor to load: 10 or 100 (default {DEFAULT_SCALE})",
    )
    _add_connection_arg(setup_p)

    teardown_p = sub.add_parser("teardown", help="Drop benchmark warehouses for a scale factor")
    teardown_p.add_argument(
        "--scale",
        choices=tuple(SCALES),
        default=DEFAULT_SCALE,
        help=f"TPC-H scale factor to tear down: 10 or 100 (default {DEFAULT_SCALE})",
    )
    _add_connection_arg(teardown_p)

    run_p = sub.add_parser("run", help="Run the TPC-H benchmark")
    run_p.add_argument(
        "--target",
        choices=TARGETS,
        default=DEFAULT_TARGET,
        help=(
            f"Engine to run against: interactive (TPCH_SF<scale>_IT + interactive warehouse) "
            f"or standard (TPCH_SF<scale> + standard warehouse). Default {DEFAULT_TARGET}"
        ),
    )
    run_p.add_argument(
        "--scale",
        choices=tuple(SCALES),
        default=DEFAULT_SCALE,
        help=f"TPC-H scale factor: 10 or 100 (default {DEFAULT_SCALE})",
    )
    run_p.add_argument(
        "--workload",
        choices=WORKLOADS,
        default=DEFAULT_WORKLOAD,
        help=f"Query set to run: original or modern (default {DEFAULT_WORKLOAD})",
    )
    run_p.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Executions per query, keeping the best (min) time (default 3)",
    )
    run_p.add_argument("--iterations", type=int, default=1, help="Number of full passes (default 1)")
    run_p.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="X",
        help=(
            "Run up to X queries concurrently via a thread pool of sync connections "
            "(default 1 = sequential)"
        ),
    )
    run_p.add_argument(
        "--query",
        type=int,
        metavar="N",
        default=None,
        help="Run a single query by number (1–22), e.g. --query 17",
    )
    run_p.add_argument(
        "--queries",
        type=str,
        default=None,
        help="Comma-separated query numbers to run, e.g. 2,11,15 (default: all 22)",
    )
    run_p.add_argument(
        "--database",
        default=None,
        help="Snowflake database to use (overrides the default for --target)",
    )
    run_p.add_argument(
        "--schema",
        default=None,
        help="Snowflake schema to use (overrides TPCH_SF<scale> or TPCH_SF<scale>_IT)",
    )
    run_p.add_argument(
        "--warehouse",
        default=None,
        help="Snowflake warehouse to use (overrides the default for --target and --scale)",
    )
    _add_connection_arg(run_p)

    return p


COMMANDS = {
    "setup": cmd_setup,
    "run": cmd_run,
    "teardown": cmd_teardown,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
