from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.tpch.config import RESULTS_DIR


def fetch_server_elapsed(conn, query_ids: Iterable[str]) -> dict[str, float]:
    """Look up server-side total_elapsed_time for the executed queries."""
    ids = [q for q in query_ids if q]
    if not ids:
        return {}
    in_list = ", ".join(f"'{q}'" for q in ids)
    sql = (
        "SELECT QUERY_ID, TOTAL_ELAPSED_TIME "
        "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT=>1000)) "
        f"WHERE QUERY_ID IN ({in_list})"
    )
    out: dict[str, float] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for qid, elapsed_ms in cur.fetchall():
            out[qid] = elapsed_ms / 1000.0
    return out


def enrich_server_elapsed(conn, results: list[dict]) -> None:
    """Attach server_elapsed_s to each result (best attempt server time)."""
    all_ids = [qid for r in results for qid in r.get("attempt_query_ids", [])]
    sf_elapsed = fetch_server_elapsed(conn, all_ids)
    for r in results:
        servers = [sf_elapsed[q] for q in r.get("attempt_query_ids", []) if q in sf_elapsed]
        r["server_elapsed_s"] = min(servers) if servers else None


def _stats(times: list[float]) -> dict:
    if not times:
        return {k: 0.0 for k in ("total", "avg", "median", "min", "max", "p95")}
    return {
        "total": sum(times),
        "avg": statistics.fmean(times),
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
        "p95": statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max(times),
    }


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if r["status"] == "OK"]
    failed = [r for r in results if r["status"] != "OK"]
    client_times = [r["client_elapsed_s"] for r in ok]
    server_times = [
        r["server_elapsed_s"] if r.get("server_elapsed_s") is not None else r["client_elapsed_s"]
        for r in ok
    ]
    return {
        "total_queries": len(results),
        "successful": len(ok),
        "failed": len(failed),
        "client_elapsed_s": _stats(client_times),
        "server_elapsed_s": _stats(server_times),
    }


def print_table(results: list[dict]) -> None:
    print("\nPer-query results:")
    print(f"{'query':10}  {'status':7}  {'rows':>8}  {'client_s':>10}  {'server_s':>10}  query_id")
    print("-" * 90)
    for r in results:
        print(
            f"{r['query']:10}  {r['status']:7}  {r['row_count']:>8}  "
            f"{r['client_elapsed_s']:>10.3f}  "
            f"{(r.get('server_elapsed_s') or 0):>10.3f}  "
            f"{r.get('query_id') or ''}"
        )


def print_summary(summary: dict) -> None:
    print("\nSummary:")
    if summary.get("warehouse"):
        print(f"  warehouse     : {summary['warehouse']} ({summary.get('warehouse_size', 'unknown')})")
    if summary.get("parallel", 1) > 1:
        print(f"  parallel      : {summary['parallel']}")
        print(f"  wall_elapsed_s: {summary.get('wall_elapsed_s', 0):.3f}")
    print(f"  total_queries : {summary['total_queries']}")
    print(f"  successful    : {summary['successful']}")
    print(f"  failed        : {summary['failed']}")

    client = summary["client_elapsed_s"]
    server = summary["server_elapsed_s"]
    print(f"\n  {'metric':10}  {'client_s':>10}  {'server_s':>10}")
    print("  " + "-" * 34)
    for key in ("total", "avg", "median", "min", "max", "p95"):
        print(f"  {key:10}  {client[key]:>10.3f}  {server[key]:>10.3f}")


def write_results(
    target: str, scale: str, workload: str, results: list[dict], summary: dict
) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS_DIR / f"run_{target}_sf{scale}_{workload}_{ts}.json"
    csv_path = RESULTS_DIR / f"run_{target}_sf{scale}_{workload}_{ts}.csv"

    json_path.write_text(
        json.dumps(
            {
                "target": target,
                "scale": scale,
                "workload": workload,
                "summary": summary,
                "results": results,
            },
            indent=2,
        )
    )

    fieldnames = [
        "query",
        "iteration",
        "status",
        "row_count",
        "client_elapsed_s",
        "server_elapsed_s",
        "query_id",
        "error",
    ]
    with csv_path.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in fieldnames})

    return json_path, csv_path
