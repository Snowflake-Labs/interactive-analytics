from __future__ import annotations

import sys
from collections.abc import Callable

import snowflake.connector

from src.tpch import config as _cfg
from src.tpch.config import (
    EXPECTED_RESULTS_1GB_PATH,
    SQL_DIR,
    SQL_SCHEMA_NAME,
    iceberg_schema_for_scale,
    interactive_schema_for_scale,
    schema_for_scale,
    schema_for_tables_type,
    sql_substitutions_for_scale,
    target_context,
    warehouse_name_for_type,
)
from src.tpch.connection import (
    connect,
    ensure_warehouse_started,
    resolve_connection_name,
    use_benchmark_context,
    _warehouse_row,
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
    scale = args.scale
    tables_type = args.tables_type
    warehouse_type = args.warehouse_type

    try:
        connection = resolve_connection_name(args.connection)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    subs = sql_substitutions_for_scale(scale)

    table_scripts = {
        "standard": "setup_standard_tables.sql",
        "interactive": "setup_interactive_tables.sql",
        "iceberg": "setup_iceberg_tables.sql",
    }
    warehouse_scripts = {
        "standard": "setup_standard_warehouse.sql",
        "interactive": "setup_interactive_warehouse.sql",
    }

    tbl_keys = list(table_scripts) if tables_type == "all" else [tables_type]
    wh_keys = list(warehouse_scripts) if warehouse_type == "all" else [warehouse_type]

    # An interactive warehouse requires a standard fallback warehouse.
    if "interactive" in wh_keys and "standard" not in wh_keys:
        wh_keys.insert(0, "standard")

    scripts: list[tuple[str, str]] = []
    for k in tbl_keys:
        scripts.append((table_scripts[k], f"Setup {k} tables"))
    for k in wh_keys:
        scripts.append((warehouse_scripts[k], f"Setup {k} warehouse"))

    # Warehouse scripts reference the schema where tables live.
    # When tables_type is specific, use that schema; when "all", use the
    # natural pairing (interactive tables for interactive warehouse).
    if tables_type != "all":
        wh_schema = schema_for_tables_type(tables_type, scale)
    else:
        wh_schema = interactive_schema_for_scale(scale)
    subs[SQL_SCHEMA_NAME] = wh_schema

    with connect(connection_name=connection) as conn:
        for script_name, label in scripts:
            script = SQL_DIR / script_name
            if not script.is_file():
                print(f"{label} script not found: {script}", file=sys.stderr)
                return 2
            print(f"Running {label.lower()} (scale {scale}) using connection '{connection}'\u2026")
            execute_script(conn, script, subs)

        # Run metadata query on the standard warehouse to avoid the
        # interactive warehouse's short statement timeout.
        if "interactive" in wh_keys:
            cur = conn.cursor()
            try:
                cur.execute(f"USE WAREHOUSE {_cfg.SOLUTION_NAME}_BENCH_WH_STD_{scale}")
            finally:
                cur.close()
        print_setup_tables(conn, scale)

    print(
        f"\nSetup complete. Created:"
        f"\n  tables     : {', '.join(tbl_keys)}"
        f"\n  warehouses : {', '.join(wh_keys)}"
    )
    return 0


def cmd_teardown(args) -> int:
    scale = args.scale
    tables_type = args.tables_type
    warehouse_type = args.warehouse_type

    try:
        connection = resolve_connection_name(args.connection)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    subs = sql_substitutions_for_scale(scale)

    table_scripts = {
        "standard": "teardown_standard_tables.sql",
        "interactive": "teardown_interactive_tables.sql",
        "iceberg": "teardown_iceberg_tables.sql",
    }
    warehouse_scripts = {
        "standard": "teardown_standard_warehouse.sql",
        "interactive": "teardown_interactive_warehouse.sql",
    }

    tbl_keys = list(table_scripts) if tables_type == "all" else [tables_type]
    wh_keys = list(warehouse_scripts) if warehouse_type == "all" else [warehouse_type]

    # Warehouses must be dropped before schemas (interactive WH references IT tables)
    scripts: list[tuple[str, str]] = []
    for k in wh_keys:
        scripts.append((warehouse_scripts[k], f"Teardown {k} warehouse"))
    for k in tbl_keys:
        scripts.append((table_scripts[k], f"Teardown {k} tables"))
    if args.drop_database:
        scripts.append(("teardown_database.sql", "Teardown database"))

    with connect(connection_name=connection) as conn:
        for script_name, label in scripts:
            script = SQL_DIR / script_name
            if not script.is_file():
                print(f"{label} script not found: {script}", file=sys.stderr)
                return 2
            print(f"Running {label.lower()} (scale {scale}) using connection '{connection}'\u2026")
            execute_script(conn, script, subs)

    dropped = [f"tables: {', '.join(tbl_keys)}", f"warehouses: {', '.join(wh_keys)}"]
    if args.drop_database:
        dropped.append(f"database: {_cfg.BENCHMARK_DATABASE}")
    print(f"Teardown complete. Dropped: {'; '.join(dropped)}")
    return 0


def cmd_run(args) -> int:
    warehouse_type = args.warehouse_type
    tables_type = args.tables_type
    scale = args.scale
    workload = args.workload
    database, schema, warehouse = target_context(
        warehouse_type,
        tables_type,
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

    mode_label = f"avg of {args.repeats} (+1 warmup)" if args.avg else f"best of {args.repeats}"
    print(
        f"Running {len(queries)} TPC-H queries x {args.iterations} iteration(s), "
        f"{mode_label}"
    )
    if not args.schema and not args.warehouse:
        print(f"  warehouse : {warehouse_type}")
        print(f"  tables    : {tables_type}")
    print(f"  scale     : SF{scale}")
    print(f"  workload  : {workload}")
    print(f"  connection: {connection}")
    print(f"  database  : {database}")
    print(f"  schema    : {schema}")

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
            if tables_type == "interactive":
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
                use_avg=args.avg,
            )
            results.extend(iter_results)

        enrich_server_elapsed(conn, results, use_avg=args.avg)
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
    json_path, csv_path = write_results(warehouse_type, tables_type, scale, workload, results, summary)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")
    validation_failed = summary.get("validation_failed", 0)
    return 0 if summary["failed"] == 0 and validation_failed == 0 else 1


def cmd_list(args) -> int:
    try:
        connection = resolve_connection_name(args.connection)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"Listing resources for solution '{_cfg.SOLUTION_NAME}' using connection '{connection}'…\n")

    with connect(connection_name=connection) as conn:
        cur = conn.cursor()

        # Check database
        cur.execute(f"SHOW DATABASES LIKE '{_cfg.BENCHMARK_DATABASE}'")
        db_rows = cur.fetchall()
        if db_rows:
            print(f"Database: {_cfg.BENCHMARK_DATABASE}")
            # List schemas in the database
            cur.execute(f"SHOW SCHEMAS IN DATABASE {_cfg.BENCHMARK_DATABASE}")
            schema_cols = [c[0].lower() for c in cur.description]
            schema_rows = cur.fetchall()
            bench_schemas = [
                dict(zip(schema_cols, r, strict=False))
                for r in schema_rows
                if dict(zip(schema_cols, r, strict=False))["name"].startswith(_cfg.SCHEMA_PREFIX)
            ]
            if bench_schemas:
                print("  Schemas:")
                for s in bench_schemas:
                    print(f"    {s['name']}")
            else:
                print("  Schemas: (none)")
        else:
            print(f"Database: {_cfg.BENCHMARK_DATABASE} (not found)")

        # Check warehouses
        print()
        wh_pattern = f"{_cfg.SOLUTION_NAME}_BENCH_WH%"
        cur.execute(f"SHOW WAREHOUSES LIKE '{wh_pattern}'")
        wh_cols = [c[0].lower() for c in cur.description]
        wh_rows = cur.fetchall()
        if wh_rows:
            print("Warehouses:")
            for row in wh_rows:
                wh = dict(zip(wh_cols, row, strict=False))
                name = wh["name"]
                size = str(wh.get("size", "unknown")).upper()
                state = str(wh.get("state", "unknown")).upper()
                wh_type = str(wh.get("type", "STANDARD")).upper()
                print(f"  {name:<40} size={size:<10} state={state:<10} type={wh_type}")
        else:
            print("Warehouses: (none found)")

        cur.close()

    return 0
