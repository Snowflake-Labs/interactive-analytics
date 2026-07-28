from __future__ import annotations

import sys
from collections.abc import Callable

import snowflake.connector

from src.tpch import config as _cfg
from src.tpch.config import (
    EXPECTED_RESULTS_1GB_PATH,
    SQL_DIR,
    interactive_schema_for_scale,
    schema_for_scale,
    sql_substitutions_for_scale,
    target_context,
    warehouse_name_for_target,
)
from src.tpch.connection import (
    connect,
    ensure_warehouse_started,
    resolve_connection_name,
    use_benchmark_context,
)
from src.tpch.execution import run_benchmark_iteration
from src.tpch.queries import load_queries, parse_query_filter
from src.tpch.results import (
    enrich_server_elapsed,
    print_summary,
    print_table,
    summarize,
    write_results,
)
from src.tpch.sql_scripts import execute_script, print_setup_tables
from src.tpch.types import QueryResult
from src.tpch.validation import apply_validation, load_expected_results_1gb


def _run_sql_script_cmd(
    args,
    *,
    script_name: str,
    action_label: str,
    post_run: Callable | None = None,
) -> int:
    scale = args.scale
    script = SQL_DIR / script_name
    if not script.is_file():
        print(f"{action_label} script not found: {script}", file=sys.stderr)
        return 2
    try:
        connection = resolve_connection_name(args.connection)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Running {action_label.lower()} (scale {scale}) using connection '{connection}'…")
    with connect(connection_name=connection) as conn:
        execute_script(conn, script, sql_substitutions_for_scale(scale))
        if post_run is not None:
            post_run(conn, scale)
    return 0


def cmd_setup(args) -> int:
    rc = _run_sql_script_cmd(
        args,
        script_name="setup.sql",
        action_label="Setup",
        post_run=print_setup_tables,
    )
    if rc != 0:
        return rc
    scale = args.scale
    print(
        f"Setup complete. Ready to benchmark:\n"
        f"  interactive: {_cfg.BENCHMARK_DATABASE}.{interactive_schema_for_scale(scale)} "
        f"on {warehouse_name_for_target('interactive', scale)}\n"
        f"  standard   : {_cfg.BENCHMARK_DATABASE}.{schema_for_scale(scale)} "
        f"on {warehouse_name_for_target('standard', scale)}"
    )
    return 0


def cmd_teardown(args) -> int:
    rc = _run_sql_script_cmd(
        args,
        script_name="teardown.sql",
        action_label="Teardown",
    )
    if rc != 0:
        return rc
    print("Teardown complete.")
    return 0


def cmd_run(args) -> int:
    target = args.target
    scale = args.scale
    workload = args.workload
    database, schema, warehouse = target_context(
        target,
        scale,
        database=args.database,
        schema=args.schema,
        warehouse=args.warehouse,
    )
    try:
        connection = resolve_connection_name(args.connection)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    filter_ids, err = parse_query_filter(args)
    if err is not None:
        return err
    try:
        queries = load_queries(workload, filter_ids)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not queries:
        print("No queries matched the filter.", file=sys.stderr)
        return 2

    print(
        f"Running {len(queries)} TPC-H queries x {args.iterations} iteration(s), "
        f"best of {args.repeats}"
    )
    print(f"  target    : {target}")
    print(f"  scale     : SF{scale}")
    print(f"  workload  : {workload}")
    print(f"  connection: {connection}")
    print(f"  database  : {database}.{schema}")

    results: list[QueryResult] = []
    wh_size = "unknown"
    with connect(connection_name=connection) as conn:
        cur = conn.cursor()
        try:
            wh_size = ensure_warehouse_started(conn, warehouse)
        except RuntimeError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 2
        try:
            use_benchmark_context(cur, database, schema, warehouse)
        except snowflake.connector.errors.ProgrammingError as exc:
            print(f"\nCould not use {database}.{schema} on {warehouse}: {exc.msg}", file=sys.stderr)
            if target == "interactive":
                print(
                    f"The interactive schema {database}.{schema} is not set up. "
                    f"Run:  ./iwtpch.sh setup --scale {scale}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Check that {database}.{schema} and warehouse {warehouse} "
                    "exist and are accessible.",
                    file=sys.stderr,
                )
            return 2

        print(f"  warehouse : {warehouse} ({wh_size})")

        cur.execute("SELECT CURRENT_VERSION()")
        version = cur.fetchone()[0]
        print(f"  version   : {version}")

        for iteration in range(1, args.iterations + 1):
            print(f"\n--- iteration {iteration} ---")
            iter_results = run_benchmark_iteration(
                queries,
                iteration=iteration,
                repeats=args.repeats,
                cur=cur,
            )
            results.extend(iter_results)

        enrich_server_elapsed(conn, results)
        cur.close()

    if scale == "1":
        if not EXPECTED_RESULTS_1GB_PATH.is_file():
            print(
                f"Expected results file {EXPECTED_RESULTS_1GB_PATH.name} not found; "
                "skipping validation.",
                file=sys.stderr,
            )
        else:
            print(f"\nValidating SF1 query results against {EXPECTED_RESULTS_1GB_PATH.name}…")
            apply_validation(results, load_expected_results_1gb())

    summary = summarize(results)
    summary["connection"] = connection
    summary["database"] = database
    summary["schema"] = schema
    summary["warehouse"] = warehouse
    summary["warehouse_size"] = wh_size
    summary["server_version"] = version
    print_table(results)
    print_summary(summary)
    json_path, csv_path = write_results(target, scale, workload, results, summary)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")
    validation_failed = summary.get("validation_failed", 0)
    return 0 if summary["failed"] == 0 and validation_failed == 0 else 1
