"""Generate & load product_catalog and user_dimensions (small tables:
50,000 / 1,000 rows). Splits row ranges across worker processes, each with
its own psycopg2 connection, building CSV batches in memory and loading via
copy_expert. Faker is used here (unlike the fact-table hot path) since
volume is low and richer names/addresses/text matter more.
"""

import csv
import io
import json
import multiprocessing
import random
from datetime import date, timedelta

from faker import Faker

import pools
from db import get_pg_conn, load_config

SCHEMA = "sync_demo"

PRODUCT_COLUMNS = [
    "product_id", "sku", "upc", "product_name", "short_description",
    "long_description", "category", "subcategory", "department", "brand",
    "manufacturer", "supplier", "supplier_country", "cost_price",
    "list_price", "sale_price", "currency", "discount_pct", "tax_rate",
    "margin_pct", "weight_kg", "length_cm", "width_cm", "height_cm",
    "color", "material", "size", "stock_quantity", "reorder_point",
    "reorder_quantity", "lead_time_days", "warehouse_location", "season",
    "gender", "age_group", "rating", "review_count", "is_active",
    "is_featured", "is_perishable", "launch_date", "discontinue_date",
    "last_restocked_at", "barcode", "country_of_origin", "hs_code",
    "tags", "attributes",
]

USER_COLUMNS = [
    "user_id", "first_name", "last_name", "email", "phone", "date_of_birth",
    "gender", "address_line1", "address_line2", "city", "state",
    "postal_code", "country", "latitude", "longitude", "timezone",
    "signup_date", "account_status", "loyalty_tier", "loyalty_points",
    "acquisition_channel", "utm_source", "utm_medium", "utm_campaign",
    "referral_code", "referred_by_user_id", "device_type", "os", "browser",
    "preferred_language", "marketing_opt_in", "email_verified",
    "phone_verified", "income_band", "occupation", "education_level",
    "credit_score_band", "lifetime_value", "churn_probability",
    "engagement_score", "total_orders", "last_login_at", "last_purchase_at",
    "is_active", "metadata", "notes",
]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(str(v) for v in value) + "}"
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    return str(value)


def _make_product_row(rng: random.Random, faker: Faker, product_id: int) -> list:
    brand = rng.choice(pools.BRANDS)
    cost = round(rng.uniform(2, 400), 2)
    list_price = round(cost * rng.uniform(1.3, 3.0), 2)
    sale_price = round(list_price * rng.uniform(0.7, 1.0), 2)
    launch = faker.date_between(start_date="-5y", end_date="today")
    discontinued = None
    if rng.random() < 0.1:
        discontinued = launch + timedelta(days=rng.randint(30, 1500))
    return [
        product_id,
        f"SKU-{product_id:08d}",
        faker.ean13(),
        f"{brand} {faker.word().capitalize()} {rng.choice(['Pro', 'Lite', 'Max', 'Plus', ''])}".strip(),
        faker.sentence(nb_words=8),
        faker.paragraph(nb_sentences=3),
        rng.choice(pools.CATEGORIES),
        rng.choice(pools.SUBCATEGORIES),
        rng.choice(pools.DEPARTMENTS),
        brand,
        rng.choice(pools.MANUFACTURERS),
        rng.choice(pools.SUPPLIERS),
        rng.choice(pools.SUPPLIER_COUNTRIES),
        cost,
        list_price,
        sale_price,
        rng.choice(pools.CURRENCIES),
        round(rng.uniform(0, 40), 2),
        round(rng.uniform(0, 12), 2),
        round((list_price - cost) / list_price * 100, 2) if list_price else 0,
        round(rng.uniform(0.01, 25), 3),
        round(rng.uniform(1, 120), 2),
        round(rng.uniform(1, 120), 2),
        round(rng.uniform(1, 120), 2),
        rng.choice(pools.COLORS),
        rng.choice(pools.MATERIALS),
        rng.choice(pools.SIZES),
        rng.randint(0, 5000),
        rng.randint(5, 200),
        rng.randint(10, 500),
        rng.randint(1, 90),
        rng.choice(pools.WAREHOUSE_LOCATIONS),
        rng.choice(pools.SEASONS),
        rng.choice(pools.GENDERS),
        rng.choice(pools.AGE_GROUPS),
        round(rng.uniform(1, 5), 2),
        rng.randint(0, 20000),
        rng.random() < 0.92,
        rng.random() < 0.1,
        rng.random() < 0.05,
        launch,
        discontinued,
        faker.date_time_between(start_date="-30d", end_date="now"),
        faker.ean8(),
        rng.choice(pools.SUPPLIER_COUNTRIES),
        f"{rng.randint(1000, 9999)}.{rng.randint(10, 99)}",
        rng.sample(["sale", "new", "trending", "bestseller", "eco", "limited", "premium"], k=rng.randint(0, 3)),
        {"weight_class": rng.choice(["light", "medium", "heavy"]), "warranty_months": rng.choice([0, 6, 12, 24])},
    ]


def _make_user_row(rng: random.Random, faker: Faker, user_id: int) -> list:
    first = faker.first_name()
    last = faker.last_name()
    signup = faker.date_between(start_date="-4y", end_date="today")
    return [
        user_id,
        first,
        last,
        f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@{faker.free_email_domain()}",
        faker.phone_number(),
        faker.date_of_birth(minimum_age=18, maximum_age=85),
        rng.choice(pools.GENDERS),
        faker.street_address(),
        faker.secondary_address() if rng.random() < 0.3 else None,
        faker.city(),
        faker.state(),
        faker.postcode(),
        rng.choice(pools.COUNTRIES),
        round(rng.uniform(-90, 90), 6),
        round(rng.uniform(-180, 180), 6),
        faker.timezone(),
        signup,
        rng.choice(pools.ACCOUNT_STATUSES),
        rng.choice(pools.LOYALTY_TIERS),
        rng.randint(0, 50000),
        rng.choice(pools.ACQUISITION_CHANNELS),
        rng.choice(pools.UTM_SOURCES),
        rng.choice(pools.UTM_MEDIUMS),
        rng.choice(pools.UTM_CAMPAIGNS),
        faker.bothify(text="REF-????##"),
        rng.randint(1, 1000) if rng.random() < 0.2 else None,
        rng.choice(pools.DEVICE_TYPES),
        rng.choice(pools.OS_LIST),
        rng.choice(pools.BROWSERS),
        rng.choice(pools.LANGUAGES),
        rng.random() < 0.6,
        rng.random() < 0.85,
        rng.random() < 0.7,
        rng.choice(pools.INCOME_BANDS),
        rng.choice(pools.OCCUPATIONS),
        rng.choice(pools.EDUCATION_LEVELS),
        rng.choice(pools.CREDIT_SCORE_BANDS),
        round(rng.uniform(0, 50000), 2),
        round(rng.uniform(0, 1), 4),
        round(rng.uniform(0, 100), 2),
        rng.randint(0, 200),
        faker.date_time_between(start_date="-60d", end_date="now"),
        faker.date_time_between(start_date="-1y", end_date="now"),
        rng.random() < 0.9,
        {"newsletter": rng.random() < 0.5, "app_installed": rng.random() < 0.4},
        faker.sentence(nb_words=6) if rng.random() < 0.15 else None,
    ]


def _copy_rows(conn, table: str, columns: list, rows: list) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(_fmt(v) for v in row)
    buf.seek(0)
    cur = conn.cursor()
    col_list = ", ".join(columns)
    cur.copy_expert(
        f"COPY {SCHEMA}.{table} ({col_list}) FROM STDIN WITH (FORMAT csv)",
        buf,
    )
    conn.commit()
    cur.close()


def _worker_generate(kind: str, start_id: int, end_id: int, cfg: dict, seed: int) -> None:
    rng = random.Random(seed)
    faker = Faker()
    faker.seed_instance(seed)
    conn = get_pg_conn(cfg)
    rows = []
    if kind == "products":
        for pid in range(start_id, end_id + 1):
            rows.append(_make_product_row(rng, faker, pid))
        _copy_rows(conn, "product_catalog", PRODUCT_COLUMNS, rows)
    else:
        for uid in range(start_id, end_id + 1):
            rows.append(_make_user_row(rng, faker, uid))
        _copy_rows(conn, "user_dimensions", USER_COLUMNS, rows)
    conn.close()


def _split_ranges(total: int, workers: int) -> list:
    workers = max(1, min(workers, total))
    base = total // workers
    remainder = total % workers
    ranges = []
    start = 1
    for i in range(workers):
        size = base + (1 if i < remainder else 0)
        if size == 0:
            continue
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def generate_products(cfg: dict, num_products: int, workers: int) -> None:
    print(f"Generating {num_products} products with {workers} workers...")
    ranges = _split_ranges(num_products, workers)
    procs = []
    for i, (start, end) in enumerate(ranges):
        p = multiprocessing.Process(
            target=_worker_generate, args=("products", start, end, cfg, 1000 + i)
        )
        p.start()
        procs.append(p)
    for p in procs:
        p.join()
        if p.exitcode != 0:
            raise RuntimeError(f"product worker failed with exit code {p.exitcode}")
    print("Products done.")


def generate_users(cfg: dict, num_users: int, workers: int) -> None:
    print(f"Generating {num_users} users with {workers} workers...")
    ranges = _split_ranges(num_users, workers)
    procs = []
    for i, (start, end) in enumerate(ranges):
        p = multiprocessing.Process(
            target=_worker_generate, args=("users", start, end, cfg, 2000 + i)
        )
        p.start()
        procs.append(p)
    for p in procs:
        p.join()
        if p.exitcode != 0:
            raise RuntimeError(f"user worker failed with exit code {p.exitcode}")
    print("Users done.")


if __name__ == "__main__":
    cfg = load_config()
    generate_products(cfg, 50000, 4)
    generate_users(cfg, 1000, 4)
