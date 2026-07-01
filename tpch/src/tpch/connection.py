from __future__ import annotations

import time

import snowflake.connector

from src.tpch.config import DEFAULT_CONNECTION_NAME, ROOT


def resolve_connection_name(override: str | None = None) -> str:
    name = override or DEFAULT_CONNECTION_NAME
    if not name:
        raise RuntimeError(
            f"Missing connection name. Pass --connection or set CONNECTION_NAME "
            f"in {ROOT / '.env'} or your shell."
        )
    return name


def _connect_kwargs(
    *, connection_name: str | None = None, warehouse: str | None = None
) -> dict:
    kwargs: dict = {"connection_name": resolve_connection_name(connection_name)}
    if warehouse:
        kwargs["warehouse"] = warehouse
    return kwargs


def disable_cached_results(cur) -> None:
    cur.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")


def use_benchmark_context(cur, database: str, schema: str, warehouse: str) -> None:
    cur.execute(f"USE DATABASE {database}")
    cur.execute(f"USE SCHEMA {schema}")
    cur.execute(f"USE WAREHOUSE {warehouse}")


def prepare_session(cur, database: str, schema: str, warehouse: str) -> None:
    disable_cached_results(cur)
    use_benchmark_context(cur, database, schema, warehouse)


def connect(*, connection_name: str | None = None, warehouse: str | None = None):
    """Open a connection using the named connection from connections.toml."""
    conn = snowflake.connector.connect(**_connect_kwargs(
        connection_name=connection_name, warehouse=warehouse
    ))
    with conn.cursor() as cur:
        disable_cached_results(cur)
    return conn


def _warehouse_row(conn, warehouse: str) -> dict[str, object] | None:
    """Return the SHOW WAREHOUSES row for ``warehouse``, or None if not found."""
    with conn.cursor() as cur:
        cur.execute(f"SHOW WAREHOUSES LIKE '{warehouse}'")
        cols = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
    if not rows:
        return None
    return dict(zip(cols, rows[0], strict=False))


def warehouse_size(conn, warehouse: str) -> str:
    """Return the warehouse size (e.g. 'XSMALL'), or 'unknown' if unavailable.

    Run this BEFORE `USE WAREHOUSE <interactive_wh>`: a SHOW issued while the
    interactive warehouse is active is subject to its 5s timeout and can be
    cancelled.
    """
    try:
        row = _warehouse_row(conn, warehouse)
        if row is None:
            return "unknown"
        size = row.get("size")
        return str(size).upper() if size else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def ensure_warehouse_started(
    conn,
    warehouse: str,
    *,
    poll_interval_s: float = 5.0,
) -> str:
    """Ensure ``warehouse`` is STARTED; resume and poll if needed.

    Uses ``SHOW WAREHOUSES LIKE '<warehouse>'`` to read state. When not
    STARTED, runs ``ALTER WAREHOUSE ... RESUME IF SUSPENDED`` and polls every
    ``poll_interval_s`` seconds until the state becomes STARTED.

    Run this BEFORE ``USE WAREHOUSE``: a SHOW issued while the interactive
    warehouse is active is subject to its 5s timeout and can be cancelled.

    Returns the warehouse size (e.g. 'XSMALL'), or 'unknown' if unavailable.
    """
    row = _warehouse_row(conn, warehouse)
    if row is None:
        raise RuntimeError(f"Warehouse '{warehouse}' not found.")

    state = str(row["state"]).upper()
    if state != "STARTED":
        print(f"Warehouse {warehouse} is {state}; resuming…")
        with conn.cursor() as cur:
            cur.execute(f"ALTER WAREHOUSE {warehouse} RESUME IF SUSPENDED")
        while True:
            time.sleep(poll_interval_s)
            row = _warehouse_row(conn, warehouse)
            if row is None:
                raise RuntimeError(f"Warehouse '{warehouse}' not found.")
            state = str(row["state"]).upper()
            if state == "STARTED":
                break
            print(f"Waiting for warehouse {warehouse} to start (state: {state})…")

    size = row.get("size")
    return str(size).upper() if size else "unknown"
