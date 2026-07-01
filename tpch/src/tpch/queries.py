from __future__ import annotations

import sys

from src.tpch.config import QUERIES_DIR


def load_queries(workload: str, filter_ids: list[int] | None) -> list[tuple[str, str]]:
    workload_dir = QUERIES_DIR / workload
    if not workload_dir.is_dir():
        raise RuntimeError(f"Workload directory not found: {workload_dir}")
    files = sorted(workload_dir.glob("query_*.sql"))
    queries: list[tuple[str, str]] = []
    for path in files:
        stem = path.stem  # e.g. query_01
        qid = int(stem.split("_")[1])
        if filter_ids and qid not in filter_ids:
            continue
        sql = path.read_text().strip().rstrip(";")
        queries.append((stem, sql))
    return queries


def parse_query_filter(args) -> tuple[list[int] | None, int | None]:
    """Parse --query / --queries args. Returns (filter_ids, error_code)."""
    if args.query is not None and args.queries:
        print("Use either --query or --queries, not both.", file=sys.stderr)
        return None, 2
    if args.query is not None:
        if not 1 <= args.query <= 22:
            print(f"Query number must be 1–22 (got {args.query}).", file=sys.stderr)
            return None, 2
        return [args.query], None
    if args.queries:
        return [int(x) for x in args.queries.split(",") if x.strip()], None
    return None, None
