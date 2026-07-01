from __future__ import annotations

import sys
import time

import snowflake.connector

from src.tpch.config import (
    BENCH_DATABASE,
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
from src.tpch.results import enrich_server_elapsed, print_summary, print_table, summarize, write_results
from src.tpch.sql_scripts import execute_script, print_setup_tables


def cmd_setup(args) -> int:
    scale = args.scale
    script = SQL_DIR / "setup.sql"
    if not script.is_file():
        print(f"Setup script not found: {script}", file=sys.stderr)
        return 2
    connection = resolve_connection_name(args.connection)
    print(f"Running setup (scale {scale}) using connection '{connection}'…")
    with connect(connection_name=connection) as conn:
        execute_script(conn, script, sql_substitutions_for_scale(scale))
        print_setup_tables(conn, scale)
    print(
        f"Setup complete. Ready to benchmark:\n"
        f"  interactive: {BENCH_DATABASE}.{interactive_schema_for_scale(scale)} "
        f"on {warehouse_name_for_target('interactive', scale)}\n"
        f"  standard   : {BENCH_DATABASE}.{schema_for_scale(scale)} "
        f"on {warehouse_name_for_target('standard', scale)}"
    )
    return 0


def cmd_teardown(args) -> int:
    scale = args.scale
    script = SQL_DIR / "teardown.sql"
    if not script.is_file():
        print(f"Teardown script not found: {script}", file=sys.stderr)
        return 2
    connection = resolve_connection_name(args.connection)
    print(f"Running teardown (scale {scale}) using connection '{connection}'…")
    with connect(connection_name=connection) as conn:
        execute_script(conn, script, sql_substitutions_for_scale(scale))
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
    connection = resolve_connection_name(args.connection)

    filter_ids, err = parse_query_filter(args)
    if err is not None:
        return err
    queries = load_queries(workload, filter_ids)
    if not queries:
        print("No queries matched the filter.", file=sys.stderr)
        return 2

    parallel = args.parallel
    if parallel < 1:
        print(f"--parallel must be >= 1 (got {parallel}).", file=sys.stderr)
        return 2

    print(
        f"Running {len(queries)} TPC-H queries x {args.iterations} iteration(s), "
        f"best of {args.repeats}, parallel {parallel}"
    )
    print(f"  target    : {target}")
    print(f"  scale     : SF{scale}")
    print(f"  workload  : {workload}")
    print(f"  connection: {connection}")
    print(f"  database  : {database}.{schema}")

    results: list[dict] = []
    wall_elapsed_s = 0.0
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
                    f"Check that {database}.{schema} and warehouse {warehouse} exist and are accessible.",
                    file=sys.stderr,
                )
            return 2

        print(f"  warehouse : {warehouse} ({wh_size})")

        cur.execute("SELECT CURRENT_VERSION()")
        version = cur.fetchone()[0]
        print(f"  version   : {version}")

        for iteration in range(1, args.iterations + 1):
            print(f"\n--- iteration {iteration} ---")
            iter_start = time.perf_counter()
            iter_results = run_benchmark_iteration(
                queries,
                iteration=iteration,
                repeats=args.repeats,
                parallel=parallel,
                connection_name=connection,
                database=database,
                schema=schema,
                warehouse=warehouse,
                cur=cur,
            )
            results.extend(iter_results)
            wall_elapsed_s += time.perf_counter() - iter_start

        enrich_server_elapsed(conn, results)
        cur.close()

    summary = summarize(results)
    summary["connection"] = connection
    summary["database"] = database
    summary["schema"] = schema
    summary["warehouse"] = warehouse
    summary["warehouse_size"] = wh_size
    summary["parallel"] = parallel
    if parallel > 1:
        summary["wall_elapsed_s"] = wall_elapsed_s
    print_table(results)
    print_summary(summary)
    json_path, csv_path = write_results(target, scale, workload, results, summary)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0 if summary["failed"] == 0 else 1
