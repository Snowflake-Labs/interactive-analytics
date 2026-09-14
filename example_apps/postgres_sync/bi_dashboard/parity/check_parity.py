"""Parity and latency probe for the Postgres side of the dashboard.

Runs wherever it can reach Postgres. With Snowflake Postgres that usually means a
one-off job in the compute pool whose egress IPs the instance's network policy
admits, because the Postgres path is then untestable from a laptop. With RDS or a
self-hosted instance you can just run it locally.

Answers two questions the dashboard alone cannot:

  1. Parity: do the aggregates match the Snowflake tables? Run the equivalent
     Snowflake SQL separately and compare - this container needs no Snowflake
     connectivity.
  2. Latency: how long does each query actually take on Postgres? The dashboard
     only ever sees its own timeout, which hides whether a query needed 80 seconds
     or 40 minutes.

Every query carries a generous statement_timeout so a slow one reports its own
duration instead of hanging the job forever.

Usage:
    uv run parity/check_parity.py
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import config  # noqa: E402

STATEMENT_TIMEOUT_MS = 15 * 60 * 1000  # 15 minutes per query

# Days of history to measure. 30 is where Postgres starts failing outright on the
# demo dataset, which is the interesting end of the curve.
WINDOW_DAYS = 30


def build_queries(schema: str) -> list[tuple[str, str]]:
    """The same six aggregates the README's comparison table reports."""
    return [
        (
            "kpi_revenue_orders_units",
            f"""
            SELECT SUM(line_total) AS revenue,
                   COUNT(DISTINCT order_id) AS orders,
                   SUM(quantity) AS units,
                   COUNT(*) AS lines
            FROM {schema}.purchase_transactions
            WHERE order_date >= %s AND order_date < %s
            """,
        ),
        (
            "margin_pct",
            f"""
            SELECT 100.0 * SUM(margin_amount) / NULLIF(SUM(line_total), 0) AS margin_pct
            FROM {schema}.purchase_transactions
            WHERE order_date >= %s AND order_date < %s
            """,
        ),
        (
            "revenue_by_channel",
            f"""
            SELECT sales_channel, SUM(line_total) AS revenue
            FROM {schema}.purchase_transactions
            WHERE order_date >= %s AND order_date < %s
            GROUP BY sales_channel ORDER BY revenue DESC
            """,
        ),
        (
            "top_categories",
            f"""
            SELECT c.category, SUM(f.line_total) AS revenue
            FROM {schema}.purchase_transactions f
            JOIN {schema}.product_catalog c ON f.product_id = c.product_id
            WHERE f.order_date >= %s AND f.order_date < %s
            GROUP BY c.category ORDER BY revenue DESC LIMIT 10
            """,
        ),
        (
            "return_rate",
            f"""
            SELECT 100.0 * COUNT(*) FILTER (WHERE is_return) / NULLIF(COUNT(*), 0) AS return_rate
            FROM {schema}.purchase_transactions
            WHERE order_date >= %s AND order_date < %s
            """,
        ),
        (
            "ship_lag_by_carrier",
            f"""
            SELECT shipping_carrier,
                   AVG(EXTRACT(EPOCH FROM (ship_date - order_date)) / 86400.0)
                     AS avg_ship_lag_days
            FROM {schema}.purchase_transactions
            WHERE order_date >= %s AND order_date < %s AND ship_date IS NOT NULL
            GROUP BY shipping_carrier ORDER BY avg_ship_lag_days DESC
            """,
        ),
    ]


def main() -> None:
    cfg = config.load()
    schema = cfg["pg_schema"]

    end = date.fromisoformat(str(cfg["data_end"]))
    start = end - timedelta(days=WINDOW_DAYS)
    window = (start.isoformat(), end.isoformat())

    print(f"connecting to {cfg['PGHOST']}:{cfg['PGPORT']}", flush=True)
    t0 = time.monotonic()
    conn = psycopg2.connect(
        host=cfg["PGHOST"],
        port=cfg["PGPORT"],
        user=cfg["PGUSER"],
        password=cfg["PGPASSWORD"],
        dbname=cfg["PGDATABASE"],
        connect_timeout=20,
    )
    print(f"connected in {time.monotonic() - t0:.2f}s", flush=True)

    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")

    print(f"\nschema: {schema}   window: {window[0]} .. {window[1]}\n", flush=True)

    for name, sql in build_queries(schema):
        print(f"--- {name} ---", flush=True)
        started = time.monotonic()
        try:
            cur.execute(sql, window)
            rows = cur.fetchall()
            print(f"  elapsed: {time.monotonic() - started:.2f}s  rows: {len(rows)}", flush=True)
            for r in rows[:12]:
                print(f"  {r}", flush=True)
        except Exception as e:  # noqa: BLE001 - the failure itself is the result
            print(f"  FAILED after {time.monotonic() - started:.2f}s: {e}", flush=True)
            conn.rollback()
            cur = conn.cursor()
            cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")

    # Indexes are the biggest single factor in whether the Postgres side is usable
    # at all, so report what exists.
    print("\n--- indexes ---", flush=True)
    cur.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes WHERE schemaname = %s ORDER BY tablename, indexname
        """,
        (schema,),
    )
    for r in cur.fetchall():
        print(f"  {r[0]}.{r[1]}: {r[2]}", flush=True)

    cur.close()
    conn.close()
    print("\ndone", flush=True)


if __name__ == "__main__":
    main()
