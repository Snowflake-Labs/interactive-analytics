"""Step 2: CLI entry point for loading synthetic data into the sync_demo Postgres schema.

Usage:
    uv run generate.py --table {products|users|transactions|all}
                        [--target-gb 50] [--num-users 1000]
                        [--num-products 50000] [--workers N]
"""

import argparse

from cpu import detect_cpu_quota
from db import load_config
from generate_dims import generate_products, generate_users
from generate_facts import add_constraints_and_indexes, generate_transactions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--table",
        choices=["products", "users", "transactions", "all"],
        default="all",
    )
    parser.add_argument("--target-gb", type=float, default=50.0)
    parser.add_argument("--num-users", type=int, default=1000)
    parser.add_argument("--num-products", type=int, default=50000)
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override the detected CPU quota worker count",
    )
    args = parser.parse_args()

    workers = args.workers or detect_cpu_quota()
    print(f"Using {workers} workers (CPU quota detected: {detect_cpu_quota()})")

    cfg = load_config()

    if args.table in ("products", "all"):
        generate_products(cfg, args.num_products, workers)

    if args.table in ("users", "all"):
        generate_users(cfg, args.num_users, workers)

    if args.table in ("transactions", "all"):
        generate_transactions(
            cfg,
            num_users=args.num_users,
            num_products=args.num_products,
            target_gb=args.target_gb,
            workers=workers,
        )
        add_constraints_and_indexes(cfg)

    print("All requested data generation complete.")


if __name__ == "__main__":
    main()
