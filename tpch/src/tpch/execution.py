from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from src.tpch.connection import connect, prepare_session


def _make_query_result(
    *,
    status: str,
    elapsed: float,
    row_count: int,
    query_id: str | None,
    error: str | None = None,
) -> dict:
    return {
        "status": status,
        "client_elapsed_s": elapsed,
        "row_count": row_count,
        "query_id": query_id,
        "error": error,
    }


def run_query(cur, sql: str) -> dict:
    """Execute a single query and return timing + result metadata."""
    start = time.perf_counter()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        return _make_query_result(
            status="OK",
            elapsed=time.perf_counter() - start,
            row_count=len(rows),
            query_id=cur.sfqid,
        )
    except Exception as exc:  # noqa: BLE001
        return _make_query_result(
            status="FAILED",
            elapsed=time.perf_counter() - start,
            row_count=0,
            query_id=getattr(cur, "sfqid", None),
            error=str(exc),
        )


def run_attempts(cur, sql: str, repeats: int) -> list[dict]:
    """Run up to `repeats` attempts, stopping early on failure."""
    attempts = []
    for _ in range(repeats):
        attempt = run_query(cur, sql)
        attempts.append(attempt)
        if attempt["status"] != "OK":
            break
    return attempts


def best_result(name: str, iteration: int, attempts: list[dict]) -> dict:
    """Pick the best (min client time) attempt and build a per-query result row."""
    ok_attempts = [a for a in attempts if a["status"] == "OK"]
    if ok_attempts:
        best = min(ok_attempts, key=lambda a: a["client_elapsed_s"])
        return {
            "query": name,
            "iteration": iteration,
            "status": "OK",
            "row_count": best["row_count"],
            "client_elapsed_s": best["client_elapsed_s"],
            "query_id": best["query_id"],
            "attempt_query_ids": [a["query_id"] for a in ok_attempts],
            "error": None,
        }
    last = attempts[-1]
    return {
        "query": name,
        "iteration": iteration,
        "status": "FAILED",
        "row_count": 0,
        "client_elapsed_s": last["client_elapsed_s"],
        "query_id": last["query_id"],
        "attempt_query_ids": [a["query_id"] for a in attempts if a["query_id"]],
        "error": last["error"],
    }


def print_query_finished(
    result: dict, *, style: Literal["inline", "block"], name: str | None = None
) -> None:
    query_name = name or result["query"]
    if style == "inline":
        if result["status"] == "OK":
            print(f" OK ({result['client_elapsed_s']:.3f}s)")
        else:
            print(" FAIL")
            if result["error"]:
                print(f"    error: {result['error'][:200]}")
    else:
        if result["status"] == "OK":
            print(f"  finished {query_name} OK ({result['client_elapsed_s']:.3f}s)")
        else:
            print(f"  finished {query_name} FAIL")
            if result["error"]:
                print(f"    error: {result['error'][:200]}")


def _run_one_query_parallel(
    name: str,
    sql: str,
    *,
    iteration: int,
    repeats: int,
    connection_name: str,
    database: str,
    schema: str,
    warehouse: str,
    print_lock: threading.Lock,
) -> dict:
    """Run one query (best of repeats) on a dedicated sync connection."""
    with connect(connection_name=connection_name, warehouse=warehouse) as conn:
        cur = conn.cursor()
        try:
            prepare_session(cur, database, schema, warehouse)
            attempts = run_attempts(cur, sql, repeats)
        finally:
            cur.close()

    result = best_result(name, iteration, attempts)
    with print_lock:
        print_query_finished(result, style="block")
    return result


def run_iteration_parallel(
    queries: list[tuple[str, str]],
    *,
    iteration: int,
    repeats: int,
    parallel: int,
    connection_name: str,
    database: str,
    schema: str,
    warehouse: str,
) -> list[dict]:
    """Run all queries for one iteration with up to `parallel` concurrent connections."""
    print_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [
            pool.submit(
                _run_one_query_parallel,
                name,
                sql,
                iteration=iteration,
                repeats=repeats,
                connection_name=connection_name,
                database=database,
                schema=schema,
                warehouse=warehouse,
                print_lock=print_lock,
            )
            for name, sql in queries
        ]
        return [f.result() for f in futures]


def run_benchmark_iteration(
    queries: list[tuple[str, str]],
    *,
    iteration: int,
    repeats: int,
    parallel: int,
    connection_name: str,
    database: str,
    schema: str,
    warehouse: str,
    cur=None,
) -> list[dict]:
    if parallel == 1:
        if cur is None:
            raise ValueError("cur is required when parallel == 1")
        results = []
        for name, sql in queries:
            print(f"  running {name} (best of {repeats})…", end="", flush=True)
            attempts = run_attempts(cur, sql, repeats)
            result = best_result(name, iteration, attempts)
            print_query_finished(result, style="inline")
            results.append(result)
        return results

    print(
        f"  launching {len(queries)} queries "
        f"(up to {parallel} concurrent sync connections)…"
    )
    return run_iteration_parallel(
        queries,
        iteration=iteration,
        repeats=repeats,
        parallel=parallel,
        connection_name=connection_name,
        database=database,
        schema=schema,
        warehouse=warehouse,
    )
