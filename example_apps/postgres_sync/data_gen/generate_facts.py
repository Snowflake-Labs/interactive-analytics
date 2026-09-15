"""Generate & load purchase_transactions (the fact table that must carry
~all of the target dataset size). Uses a calibration pass to measure actual
bytes/row, then fans out the remaining row count across worker processes
via multiprocessing.Process, each COPYing its shard in batches. FK
constraints and secondary indexes are added only after all data is loaded.
"""

import csv
import io
import json
import multiprocessing
import random
import time
from datetime import datetime, timedelta

import numpy as np

import pools
from db import get_pg_conn, load_config, pg_relation_size_bytes

SCHEMA = "sync_demo"
TABLE = "purchase_transactions"
BATCH_SIZE = 50_000
CALIBRATION_ROWS = 200_000

TRANSACTION_COLUMNS = [
    "transaction_id", "order_id", "line_number", "user_id", "product_id",
    "order_status", "fulfillment_status", "payment_status", "payment_method",
    "quantity", "unit_price", "unit_cost", "discount_amount", "tax_amount",
    "shipping_amount", "line_total", "margin_amount", "currency",
    "sales_channel", "store_id", "warehouse_id", "shipping_method",
    "shipping_carrier", "tracking_number", "order_date", "ship_date",
    "delivery_date", "promo_code", "coupon_amount", "device_type",
    "session_id", "utm_source", "utm_medium", "utm_campaign", "is_gift",
    "is_return", "return_reason", "is_refunded", "refund_amount",
    "customer_notes", "internal_notes", "metadata",
]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _generate_batch(rng: random.Random, ids: range, order_state: dict, num_users: int, num_products: int) -> list:
    n = len(ids)
    quantities = np.random.randint(1, 6, size=n)
    unit_prices = np.round(np.random.uniform(3, 500, size=n), 2)
    cost_ratios = np.random.uniform(0.4, 0.8, size=n)
    unit_costs = np.round(unit_prices * cost_ratios, 2)
    discount_pcts = np.random.uniform(0, 0.3, size=n)
    discount_amounts = np.round(unit_prices * quantities * discount_pcts, 2)
    tax_rates = np.random.uniform(0, 0.1, size=n)
    subtotals = unit_prices * quantities - discount_amounts
    tax_amounts = np.round(subtotals * tax_rates, 2)
    shipping_choices = np.array([0, 4.99, 5.99, 9.99, 14.99])
    shipping_amounts = shipping_choices[np.random.randint(0, len(shipping_choices), size=n)]
    line_totals = np.round(subtotals + tax_amounts + shipping_amounts, 2)
    margin_amounts = np.round((unit_prices - unit_costs) * quantities - discount_amounts, 2)

    now = datetime.now()
    rows = []
    for i, tid in enumerate(ids):
        if order_state["lines_left"] == 0:
            order_state["order_id"] = tid
            order_state["lines_left"] = rng.randint(1, 4)
            order_state["line_number"] = 0
        order_state["line_number"] += 1
        order_state["lines_left"] -= 1

        order_status = rng.choice(pools.ORDER_STATUSES)
        is_return = rng.random() < 0.05
        is_refunded = is_return and rng.random() < 0.7
        order_date = now - timedelta(
            days=rng.randint(0, 730), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        ship_date = order_date + timedelta(days=rng.randint(0, 3)) if order_status not in ("pending", "cancelled") else None
        delivery_date = ship_date + timedelta(days=rng.randint(1, 7)) if ship_date and order_status == "delivered" else None

        rows.append([
            tid,
            order_state["order_id"],
            order_state["line_number"],
            rng.randint(1, num_users),
            rng.randint(1, num_products),
            order_status,
            rng.choice(pools.FULFILLMENT_STATUSES),
            rng.choice(pools.PAYMENT_STATUSES),
            rng.choice(pools.PAYMENT_METHODS),
            int(quantities[i]),
            float(unit_prices[i]),
            float(unit_costs[i]),
            float(discount_amounts[i]),
            float(tax_amounts[i]),
            float(shipping_amounts[i]),
            float(line_totals[i]),
            float(margin_amounts[i]),
            rng.choice(pools.CURRENCIES),
            rng.choice(pools.SALES_CHANNELS),
            rng.randint(1, 200),
            rng.randint(1, 20),
            rng.choice(pools.SHIPPING_METHODS),
            rng.choice(pools.SHIPPING_CARRIERS),
            f"TRK{rng.randint(10**9, 10**10 - 1)}" if ship_date else None,
            order_date,
            ship_date,
            delivery_date,
            rng.choice(pools.UTM_CAMPAIGNS) if rng.random() < 0.2 else None,
            round(rng.uniform(1, 20), 2) if rng.random() < 0.2 else None,
            rng.choice(pools.DEVICE_TYPES),
            f"sess_{rng.randint(10**12, 10**13 - 1)}",
            rng.choice(pools.UTM_SOURCES),
            rng.choice(pools.UTM_MEDIUMS),
            rng.choice(pools.UTM_CAMPAIGNS),
            rng.random() < 0.03,
            is_return,
            rng.choice(pools.RETURN_REASONS) if is_return else None,
            is_refunded,
            round(float(line_totals[i]) * rng.uniform(0.5, 1.0), 2) if is_refunded else None,
            None,
            None,
            {"utm_content": rng.choice(["banner_top", "banner_side", "email_cta", "none"])},
        ])
    return rows


def _copy_batch(conn, rows: list) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(_fmt(v) for v in row)
    buf.seek(0)
    cur = conn.cursor()
    col_list = ", ".join(TRANSACTION_COLUMNS)
    cur.copy_expert(
        f"COPY {SCHEMA}.{TABLE} ({col_list}) FROM STDIN WITH (FORMAT csv)",
        buf,
    )
    conn.commit()
    cur.close()


def _worker_generate_transactions(start_id: int, end_id: int, cfg: dict, seed: int, num_users: int, num_products: int) -> None:
    rng = random.Random(seed)
    np.random.seed(seed % (2**32))
    conn = get_pg_conn(cfg)
    order_state = {"order_id": None, "lines_left": 0, "line_number": 0}
    current = start_id
    while current <= end_id:
        batch_end = min(current + BATCH_SIZE - 1, end_id)
        ids = range(current, batch_end + 1)
        rows = _generate_batch(rng, ids, order_state, num_users, num_products)
        _copy_batch(conn, rows)
        current = batch_end + 1
    conn.close()


def calibrate(cfg: dict, num_users: int, num_products: int) -> tuple:
    """Load CALIBRATION_ROWS rows starting at id=1, return (bytes_per_row, next_id)."""
    print(f"Calibrating with {CALIBRATION_ROWS} rows...")
    conn = get_pg_conn(cfg)
    before = pg_relation_size_bytes(conn, SCHEMA, TABLE)
    conn.close()

    _worker_generate_transactions(1, CALIBRATION_ROWS, cfg, seed=1, num_users=num_users, num_products=num_products)

    conn = get_pg_conn(cfg)
    after = pg_relation_size_bytes(conn, SCHEMA, TABLE)
    conn.close()

    bytes_per_row = (after - before) / CALIBRATION_ROWS
    print(f"Calibration done: {bytes_per_row:.1f} bytes/row (delta {after - before} bytes over {CALIBRATION_ROWS} rows)")
    return bytes_per_row, CALIBRATION_ROWS + 1


def _split_ranges(start_id: int, count: int, workers: int) -> list:
    workers = max(1, min(workers, count)) if count > 0 else 0
    if workers == 0:
        return []
    base = count // workers
    remainder = count % workers
    ranges = []
    cur = start_id
    for i in range(workers):
        size = base + (1 if i < remainder else 0)
        if size == 0:
            continue
        end = cur + size - 1
        ranges.append((cur, end))
        cur = end + 1
    return ranges


def _load_shards(cfg: dict, ranges: list, num_users: int, num_products: int, seed_base: int) -> None:
    procs = []
    for i, (start, end) in enumerate(ranges):
        p = multiprocessing.Process(
            target=_worker_generate_transactions,
            args=(start, end, cfg, seed_base + i, num_users, num_products),
        )
        p.start()
        procs.append(p)
    for p in procs:
        p.join()
        if p.exitcode != 0:
            raise RuntimeError(f"transaction worker failed with exit code {p.exitcode}")


def generate_transactions(cfg: dict, num_users: int, num_products: int, target_gb: float, workers: int) -> None:
    target_bytes = target_gb * (1024 ** 3)

    bytes_per_row, next_id = calibrate(cfg, num_users, num_products)

    conn = get_pg_conn(cfg)
    current_size = pg_relation_size_bytes(conn, SCHEMA, TABLE)
    conn.close()

    remaining_bytes = target_bytes - current_size
    remaining_rows = max(0, int(remaining_bytes / bytes_per_row) + 1) if bytes_per_row > 0 else 0

    print(
        f"Current size: {current_size / (1024**3):.2f} GiB, target: {target_gb:.2f} GiB, "
        f"remaining rows to generate: {remaining_rows}"
    )

    if remaining_rows > 0:
        ranges = _split_ranges(next_id, remaining_rows, workers)
        print(f"Loading {remaining_rows} rows across {len(ranges)} workers...")
        start_time = time.time()
        _load_shards(cfg, ranges, num_users, num_products, seed_base=10_000)
        print(f"Main load done in {time.time() - start_time:.1f}s.")
        next_id = ranges[-1][1] + 1 if ranges else next_id

    # Top-off pass in case bytes/row estimate undershot the target.
    conn = get_pg_conn(cfg)
    current_size = pg_relation_size_bytes(conn, SCHEMA, TABLE)
    conn.close()
    if current_size < target_bytes:
        shortfall_bytes = target_bytes - current_size
        topoff_rows = max(0, int(shortfall_bytes / bytes_per_row) + 1) if bytes_per_row > 0 else 0
        if topoff_rows > 0:
            print(f"Topping off with {topoff_rows} additional rows...")
            ranges = _split_ranges(next_id, topoff_rows, workers)
            _load_shards(cfg, ranges, num_users, num_products, seed_base=20_000)

    conn = get_pg_conn(cfg)
    final_size = pg_relation_size_bytes(conn, SCHEMA, TABLE)
    conn.close()
    print(f"Final purchase_transactions size: {final_size / (1024**3):.2f} GiB")


def add_constraints_and_indexes(cfg: dict) -> None:
    print("Adding foreign keys and secondary indexes on purchase_transactions...")
    conn = get_pg_conn(cfg)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} "
        f"ADD CONSTRAINT fk_transactions_user FOREIGN KEY (user_id) "
        f"REFERENCES {SCHEMA}.user_dimensions (user_id) NOT VALID"
    )
    cur.execute(f"ALTER TABLE {SCHEMA}.{TABLE} VALIDATE CONSTRAINT fk_transactions_user")
    cur.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} "
        f"ADD CONSTRAINT fk_transactions_product FOREIGN KEY (product_id) "
        f"REFERENCES {SCHEMA}.product_catalog (product_id) NOT VALID"
    )
    cur.execute(f"ALTER TABLE {SCHEMA}.{TABLE} VALIDATE CONSTRAINT fk_transactions_product")
    cur.execute(f"CREATE INDEX idx_transactions_user_id ON {SCHEMA}.{TABLE} (user_id)")
    cur.execute(f"CREATE INDEX idx_transactions_product_id ON {SCHEMA}.{TABLE} (product_id)")
    cur.execute(f"CREATE INDEX idx_transactions_order_date ON {SCHEMA}.{TABLE} (order_date)")
    cur.close()
    conn.close()
    print("Constraints and indexes done.")


if __name__ == "__main__":
    cfg = load_config()
    generate_transactions(cfg, num_users=1000, num_products=50000, target_gb=50, workers=4)
    add_constraints_and_indexes(cfg)
