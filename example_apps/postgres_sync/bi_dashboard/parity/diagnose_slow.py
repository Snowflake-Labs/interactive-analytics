"""Diagnose why the Postgres side is slow at a given window size.

Runs wherever it can reach Postgres (for Snowflake Postgres, a one-off job in the
compute pool the network policy admits).

Reports EXPLAIN (ANALYZE, BUFFERS) for the dashboard's KPI query at a 1-hour and a
1-day window, with and without the dashboard's cache-buster predicate, so the
chosen plan is visible rather than inferred. Two things this is good for:

  * confirming the cache-buster (`transaction_id > <negative>`) is not steering the
    planner onto the primary key instead of the order_date index;
  * finding where the COUNT(DISTINCT order_id) sort stops fitting in memory, which
    is the cliff that makes large windows unusable.

Usage:
    uv run parity/diagnose_slow.py
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import config  # noqa: E402

STATEMENT_TIMEOUT_MS = 10 * 60 * 1000

# Mirrors the dashboard's KPI tiles.
BASE_TMPL = """
SELECT SUM(line_total) AS revenue,
       COUNT(DISTINCT order_id) AS orders,
       SUM(quantity) AS units
FROM {schema}.purchase_transactions
WHERE order_date >= %s AND order_date < %s
"""

# The exact shape web/lib/cube.ts injects on every request, to defeat caching.
NONCE_PREDICATE = " AND transaction_id > -1000000\n"


def run(cur, label: str, sql: str, params: tuple) -> None:
    print(f"\n=== {label} ===", flush=True)
    started = time.monotonic()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        print(f"  elapsed: {time.monotonic() - started:.2f}s -> {rows[0]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED after {time.monotonic() - started:.2f}s: {e}", flush=True)
        return

    try:
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql, params)
        for (line,) in cur.fetchall():
            print(f"    {line}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"    EXPLAIN failed: {e}", flush=True)


def main() -> None:
    cfg = config.load()
    schema = cfg["pg_schema"]
    base = BASE_TMPL.format(schema=schema)
    with_nonce = base + NONCE_PREDICATE

    # Anchor on the data's true end so the windows land on populated rows.
    end = datetime.fromisoformat(str(cfg["data_end_ts"]))
    windows = {
        "1 hour": (end - timedelta(hours=1), end),
        "1 day": (end - timedelta(days=1), end),
    }

    conn = psycopg2.connect(
        host=cfg["PGHOST"],
        port=cfg["PGPORT"],
        user=cfg["PGUSER"],
        password=cfg["PGPASSWORD"],
        dbname=cfg["PGDATABASE"],
        connect_timeout=20,
    )
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")

    for wname, (ws, we) in windows.items():
        params = (ws.isoformat(sep=" "), we.isoformat(sep=" "))
        run(cur, f"{wname} WITHOUT cache-buster", base, params)
        run(cur, f"{wname} WITH cache-buster", with_nonce, params)

    # How many rows each window actually is, for context on what "fast" means.
    print("\n=== row counts ===", flush=True)
    for wname, (ws, we) in windows.items():
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.purchase_transactions "
            "WHERE order_date >= %s AND order_date < %s",
            (ws.isoformat(sep=" "), we.isoformat(sep=" ")),
        )
        (n,) = cur.fetchone()
        print(f"  {wname}: {n:,} rows", flush=True)

    cur.close()
    conn.close()
    print("\ndone", flush=True)


if __name__ == "__main__":
    main()
