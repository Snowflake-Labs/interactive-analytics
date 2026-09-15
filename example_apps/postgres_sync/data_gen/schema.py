"""Step 1: create the sync_demo schema and its 3-table star schema.

Creates PK-only tables (no FKs, no secondary indexes on the fact table) so
that bulk COPY loads in generate.py stay fast. Dimension tables get their
normal secondary indexes immediately since they're tiny.

Usage:
    uv run schema.py [--reset]
"""

import argparse

from db import get_pg_conn, load_config

SCHEMA = "sync_demo"

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE {SCHEMA}.product_catalog (
    product_id            BIGINT PRIMARY KEY,
    sku                   TEXT NOT NULL,
    upc                   TEXT,
    product_name          TEXT NOT NULL,
    short_description     TEXT,
    long_description      TEXT,
    category              TEXT,
    subcategory           TEXT,
    department            TEXT,
    brand                 TEXT,
    manufacturer          TEXT,
    supplier              TEXT,
    supplier_country      TEXT,
    cost_price            NUMERIC(12,2),
    list_price            NUMERIC(12,2),
    sale_price            NUMERIC(12,2),
    currency              TEXT,
    discount_pct          NUMERIC(5,2),
    tax_rate              NUMERIC(5,2),
    margin_pct            NUMERIC(5,2),
    weight_kg             NUMERIC(10,3),
    length_cm             NUMERIC(10,2),
    width_cm              NUMERIC(10,2),
    height_cm             NUMERIC(10,2),
    color                 TEXT,
    material              TEXT,
    size                  TEXT,
    stock_quantity        INTEGER,
    reorder_point         INTEGER,
    reorder_quantity      INTEGER,
    lead_time_days        INTEGER,
    warehouse_location    TEXT,
    season                TEXT,
    gender                TEXT,
    age_group             TEXT,
    rating                NUMERIC(3,2),
    review_count          INTEGER,
    is_active             BOOLEAN,
    is_featured           BOOLEAN,
    is_perishable         BOOLEAN,
    launch_date           DATE,
    discontinue_date      DATE,
    last_restocked_at     TIMESTAMP,
    barcode               TEXT,
    country_of_origin     TEXT,
    hs_code               TEXT,
    tags                  TEXT[],
    attributes            JSONB,
    created_at            TIMESTAMP NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_product_catalog_category ON {SCHEMA}.product_catalog (category);
CREATE INDEX idx_product_catalog_brand ON {SCHEMA}.product_catalog (brand);
CREATE INDEX idx_product_catalog_sku ON {SCHEMA}.product_catalog (sku);

CREATE TABLE {SCHEMA}.user_dimensions (
    user_id               BIGINT PRIMARY KEY,
    first_name            TEXT,
    last_name             TEXT,
    email                 TEXT,
    phone                 TEXT,
    date_of_birth         DATE,
    gender                TEXT,
    address_line1         TEXT,
    address_line2         TEXT,
    city                  TEXT,
    state                 TEXT,
    postal_code           TEXT,
    country               TEXT,
    latitude              NUMERIC(9,6),
    longitude             NUMERIC(9,6),
    timezone              TEXT,
    signup_date           DATE,
    account_status        TEXT,
    loyalty_tier          TEXT,
    loyalty_points        INTEGER,
    acquisition_channel   TEXT,
    utm_source            TEXT,
    utm_medium            TEXT,
    utm_campaign          TEXT,
    referral_code         TEXT,
    referred_by_user_id   BIGINT,
    device_type           TEXT,
    os                    TEXT,
    browser               TEXT,
    preferred_language    TEXT,
    marketing_opt_in      BOOLEAN,
    email_verified        BOOLEAN,
    phone_verified        BOOLEAN,
    income_band           TEXT,
    occupation            TEXT,
    education_level       TEXT,
    credit_score_band     TEXT,
    lifetime_value        NUMERIC(14,2),
    churn_probability     NUMERIC(5,4),
    engagement_score      NUMERIC(5,2),
    total_orders          INTEGER,
    last_login_at         TIMESTAMP,
    last_purchase_at      TIMESTAMP,
    is_active             BOOLEAN,
    metadata              JSONB,
    notes                 TEXT,
    created_at            TIMESTAMP NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_dimensions_email ON {SCHEMA}.user_dimensions (email);
CREATE INDEX idx_user_dimensions_country ON {SCHEMA}.user_dimensions (country);

CREATE TABLE {SCHEMA}.purchase_transactions (
    transaction_id        BIGINT PRIMARY KEY,
    order_id              BIGINT NOT NULL,
    line_number           INTEGER NOT NULL,
    user_id               BIGINT NOT NULL,
    product_id            BIGINT NOT NULL,
    order_status          TEXT,
    fulfillment_status    TEXT,
    payment_status        TEXT,
    payment_method        TEXT,
    quantity              INTEGER,
    unit_price            NUMERIC(12,2),
    unit_cost             NUMERIC(12,2),
    discount_amount       NUMERIC(12,2),
    tax_amount            NUMERIC(12,2),
    shipping_amount       NUMERIC(12,2),
    line_total            NUMERIC(14,2),
    margin_amount         NUMERIC(14,2),
    currency              TEXT,
    sales_channel         TEXT,
    store_id              BIGINT,
    warehouse_id          BIGINT,
    shipping_method       TEXT,
    shipping_carrier      TEXT,
    tracking_number       TEXT,
    order_date            TIMESTAMP,
    ship_date             TIMESTAMP,
    delivery_date         TIMESTAMP,
    promo_code            TEXT,
    coupon_amount         NUMERIC(12,2),
    device_type           TEXT,
    session_id            TEXT,
    utm_source            TEXT,
    utm_medium            TEXT,
    utm_campaign          TEXT,
    is_gift               BOOLEAN,
    is_return             BOOLEAN,
    return_reason         TEXT,
    is_refunded           BOOLEAN,
    refund_amount         NUMERIC(12,2),
    customer_notes        TEXT,
    internal_notes        TEXT,
    metadata              JSONB,
    created_at            TIMESTAMP NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP NOT NULL DEFAULT now()
);
"""

RESET_SQL = f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the schema (CASCADE) before recreating it",
    )
    args = parser.parse_args()

    cfg = load_config()
    conn = get_pg_conn(cfg)
    conn.autocommit = True
    cur = conn.cursor()

    if args.reset:
        print(f"Dropping schema {SCHEMA} (if exists)...")
        cur.execute(RESET_SQL)

    print(f"Creating schema {SCHEMA} and tables...")
    cur.execute(DDL)
    print("Done.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
