"""TPC-H benchmark dashboard API server (Python + Snowflake connector)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

import snowflake.connector
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from snowflake.connector import DictCursor
from snowflake.connector.compat import IS_LINUX, IS_MACOS, IS_WINDOWS

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "IW_TPCH_BENCH")
SCALES = ["1", "10", "100", "1000"]
CONNECTION_NAME = os.environ.get("CONNECTION_NAME")
LOOKBACK_DAYS = 15
TARGETS = ["standard", "interactive"]
DEFAULT_TARGET = "interactive"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("dashboard")


def parse_cli_scale(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--scale" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.isdigit() and arg in SCALES:
            return arg
    return None


DEFAULT_SCALE = parse_cli_scale(sys.argv[1:]) or os.environ.get("DEFAULT_SCALE", "100")
PORT = int(os.environ.get("PORT", "3000"))
CREDENTIAL_CACHE_DIR = os.environ.get(
    "SNOWFLAKE_CREDENTIAL_CACHE_DIR",
    os.path.join(
        os.environ.get("SNOWFLAKE_HOME", os.path.join(Path.home(), ".snowflake")),
        "credential_cache",
    ),
)


def credential_cache_enabled() -> bool:
    return os.environ.get("SNOWFLAKE_CLIENT_STORE_TEMPORARY_CREDENTIAL", "true").lower() != "false"


def credential_cache_options() -> dict[str, Any]:
    if not credential_cache_enabled():
        return {"client_store_temporary_credential": False}
    return {"client_store_temporary_credential": True}


def credential_cache_description() -> str:
    if not credential_cache_enabled():
        return "disabled"
    if IS_MACOS or IS_WINDOWS:
        return "system keyring (secure-local-storage)"
    if IS_LINUX:
        cache_dir = os.environ.get(
            "SF_TEMPORARY_CREDENTIAL_CACHE_DIR",
            os.path.join(Path.home(), ".cache", "snowflake"),
        )
        return cache_dir
    return CREDENTIAL_CACHE_DIR


def schema_for_target(target: str, scale: str) -> str:
    return f"TPCH_SF{scale}_IT" if target == "interactive" else f"TPCH_SF{scale}"


def warehouse_for_target(target: str, scale: str) -> str:
    return (
        f"IW_TPCH_BENCH_WH_{scale}"
        if target == "interactive"
        else f"TPCH_BENCH_WH_{scale}"
    )


def resolve_target(raw: str | None) -> str:
    target = DEFAULT_TARGET if raw in (None, "") else str(raw)
    if target not in TARGETS:
        raise ValueError(
            f'Invalid warehouse target {raw!r}. Use "standard" or "interactive".'
        )
    return target


def resolve_scale(raw: str | None) -> str:
    scale = str(raw or DEFAULT_SCALE)
    if scale not in SCALES:
        raise ValueError(f"Invalid scale {scale}. Use one of: {', '.join(SCALES)}")
    return scale


def boundaries_cte() -> str:
    return f"""
WITH boundaries AS (
  SELECT
    MAX(L_SHIPDATE) AS end_date,
    DATEADD(day, -{LOOKBACK_DAYS}, MAX(L_SHIPDATE)) AS start_date
  FROM LINEITEM_DASHBOARD
)"""


def ship_date_filter(alias: str = "l") -> str:
    return f"{alias}.L_SHIPDATE BETWEEN boundaries.start_date AND boundaries.end_date"


def lineitem_revenue(alias: str = "l") -> str:
    return f"{alias}.L_EXTENDEDPRICE * (1 - {alias}.L_DISCOUNT)"


def build_dashboard_query(
    *,
    select: str,
    segment: str | None,
    extra_where: list[str] | None = None,
    group_by: str = "",
    order_by: str = "",
    limit: str = "",
) -> tuple[str, list[Any]]:
    where = [ship_date_filter("l")]
    binds: list[Any] = []
    if segment:
        where.append("l.L_MKTSEGMENT = %s")
        binds.append(segment)
    if extra_where:
        where.extend(extra_where)

    parts = [
        boundaries_cte().strip(),
        select.strip(),
        "FROM LINEITEM_DASHBOARD l",
        "CROSS JOIN boundaries",
        f"WHERE {' AND '.join(where)}",
    ]
    if group_by:
        parts.append(group_by)
    if order_by:
        parts.append(order_by)
    if limit:
        parts.append(limit)

    return "\n".join(parts), binds


def serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize_rows(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, dict):
        return {k: serialize_value(v) for k, v in data.items()}
    if isinstance(data, list):
        if not data or not isinstance(data[0], dict):
            return [serialize_value(v) for v in data]
        return [{k: serialize_value(v) for k, v in row.items()} for row in data]
    return serialize_value(data)


def response_row_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    return 0 if data is None else 1


def base_connection_kwargs() -> dict[str, Any]:
    if CONNECTION_NAME:
        os.environ["SNOWFLAKE_DEFAULT_CONNECTION_NAME"] = CONNECTION_NAME
        return {"connection_name": CONNECTION_NAME}
    return {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ.get("SNOWFLAKE_USER"),
        "role": os.environ.get("SNOWFLAKE_ROLE", "PUBLIC"),
        "authenticator": os.environ.get("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
    }


def connection_kwargs_for(target: str, scale: str) -> dict[str, Any]:
    return {
        **base_connection_kwargs(),
        **credential_cache_options(),
        "warehouse": warehouse_for_target(target, scale),
        "database": DATABASE,
        "schema": schema_for_target(target, scale),
    }


class ConnectionPool:
    def __init__(self) -> None:
        self._connections: dict[str, snowflake.connector.SnowflakeConnection] = {}
        self._locks: dict[str, Lock] = {}
        self._global_lock = Lock()

    def _lock_for(self, key: str) -> Lock:
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = Lock()
            return self._locks[key]

    def get(self, target: str, scale: str) -> snowflake.connector.SnowflakeConnection:
        key = f"{target}:{scale}"
        lock = self._lock_for(key)
        with lock:
            conn = self._connections.get(key)
            if conn is not None and not conn.is_closed():
                return conn

            kwargs = connection_kwargs_for(target, scale)
            conn = snowflake.connector.connect(**kwargs)
            with conn.cursor() as cur:
                cur.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")
            self._connections[key] = conn
            return conn


pool = ConnectionPool()


def execute_query(
    sql: str, target: str, scale: str, binds: list[Any] | None = None
) -> list[dict[str, Any]]:
    conn = pool.get(target, scale)
    with conn.cursor(DictCursor) as cur:
        cur.execute(sql, binds or ())
        return cur.fetchall()


def run_dashboard_query(
    target: str,
    scale: str,
    segment: str | None,
    **options: Any,
) -> list[dict[str, Any]]:
    sql, binds = build_dashboard_query(segment=segment, **options)
    return execute_query(sql, target, scale, binds)


def snowflake_log_context(warehouse: str | None, scale: str | None) -> str:
    try:
        resolved_target = resolve_target(warehouse)
        resolved_scale = resolve_scale(scale)
        wh = warehouse_for_target(resolved_target, resolved_scale)
        schema = schema_for_target(resolved_target, resolved_scale)
        return f" warehouse={wh} schema={schema}"
    except ValueError:
        return ""


def request_params(
    warehouse: str | None,
    scale: str | None,
    segment: str | None,
) -> tuple[str, str, str | None]:
    try:
        target = resolve_target(warehouse)
        resolved_scale = resolve_scale(scale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if segment is None:
        resolved_segment = None
    else:
        trimmed = segment.strip()
        resolved_segment = trimmed if trimmed else None

    return target, resolved_scale, resolved_segment


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scale = resolve_scale(DEFAULT_SCALE)
    log.info("TPC-H dashboard running at http://localhost:%s", PORT)
    log.info("Database: %s, default scale: SF%s", DATABASE, scale)
    log.info(
        "Warehouses: interactive=%s, standard=%s",
        warehouse_for_target("interactive", scale),
        warehouse_for_target("standard", scale),
    )
    if CONNECTION_NAME:
        log.info(
            "Snowflake connection: %s (from ~/.snowflake/connections.toml)",
            CONNECTION_NAME,
        )
    else:
        log.info("Snowflake account: %s", base_connection_kwargs().get("account"))
    if credential_cache_enabled():
        log.info("Snowflake credential cache: %s", credential_cache_description())
    try:
        opts = connection_kwargs_for("interactive", scale)
        pool.get("interactive", scale)
        log.info(
            "Snowflake connection established (%s / %s.%s).",
            opts["warehouse"],
            opts["database"],
            opts["schema"],
        )
    except Exception as exc:
        log.error("Snowflake connection failed: %s", exc)
    yield


app = FastAPI(title="TPC-H Benchmark Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "public"), name="static")


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.middleware("http")
async def api_logging(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    start = time.perf_counter()
    query = f" {dict(request.query_params)}" if request.query_params else ""
    context = snowflake_log_context(
        request.query_params.get("warehouse"),
        request.query_params.get("scale"),
    )
    route_name = request.url.path

    try:
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        rows = getattr(request.state, "response_rows", "?")
        log.info(
            "[api] %s %s%s%s %sms rows=%s",
            request.method,
            route_name,
            query,
            context,
            elapsed_ms,
            rows,
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        log.error(
            "[api] %s %s%s%s %sms error=%s",
            request.method,
            route_name,
            query,
            context,
            elapsed_ms,
            exc,
        )
        raise


def json_api(data: Any, request: Request) -> JSONResponse:
    request.state.response_rows = response_row_count(data)
    return JSONResponse(serialize_rows(data))


@app.get("/")
def index():
    from fastapi.responses import FileResponse

    return FileResponse(ROOT_DIR / "public" / "index.html")


@app.get("/api/config")
def api_config(
    request: Request,
    scale: str | None = Query(default=None),
):
    try:
        resolved_scale = resolve_scale(scale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return json_api(
        {
            "database": DATABASE,
            "scale": resolved_scale,
            "defaultScale": DEFAULT_SCALE,
            "scales": SCALES,
            "lookbackDays": LOOKBACK_DAYS,
            "standard": {
                "schema": schema_for_target("standard", resolved_scale),
                "warehouse": warehouse_for_target("standard", resolved_scale),
            },
            "interactive": {
                "schema": schema_for_target("interactive", resolved_scale),
                "warehouse": warehouse_for_target("interactive", resolved_scale),
            },
        },
        request,
    )


@app.get("/api/segments")
def api_segments(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select="SELECT DISTINCT l.L_MKTSEGMENT AS market_segment",
        extra_where=["l.L_MKTSEGMENT IS NOT NULL"],
        order_by="ORDER BY market_segment ASC",
    )
    return json_api(
        [r["MARKET_SEGMENT"] for r in rows if r.get("MARKET_SEGMENT")],
        request,
    )


@app.get("/api/kpis")
def api_kpis(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select=f"""SELECT
          COUNT(DISTINCT l.L_ORDERKEY) AS total_orders,
          ROUND(SUM({lineitem_revenue("l")}), 2) AS total_revenue,
          COUNT(DISTINCT l.L_CUSTKEY) AS total_customers,
          COUNT(*) AS total_line_items,
          ROUND(SUM({lineitem_revenue("l")}) / NULLIF(COUNT(DISTINCT l.L_ORDERKEY), 0), 2) AS avg_order_value""",
    )
    return json_api(rows[0] if rows else {}, request)


@app.get("/api/orders-over-time")
def api_orders_over_time(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select=f"""SELECT
          DATE_TRUNC('day', l.L_SHIPDATE) AS order_day,
          COUNT(DISTINCT l.L_ORDERKEY) AS total_orders,
          SUM({lineitem_revenue("l")}) AS total_revenue""",
        group_by="GROUP BY 1",
        order_by="ORDER BY order_day ASC",
    )
    return json_api(rows, request)


@app.get("/api/by-segment")
def api_by_segment(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select=f"""SELECT l.L_MKTSEGMENT AS market_segment,
               COUNT(DISTINCT l.L_ORDERKEY) AS order_count,
               SUM({lineitem_revenue("l")}) AS revenue""",
        group_by="GROUP BY 1",
        order_by="" if segment else "ORDER BY revenue DESC",
    )
    return json_api(rows, request)


@app.get("/api/by-region")
def api_by_region(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select=f"""SELECT l.L_REGIONNAME AS region,
               COUNT(DISTINCT l.L_ORDERKEY) AS order_count,
               SUM({lineitem_revenue("l")}) AS revenue""",
        group_by="GROUP BY 1",
        order_by="ORDER BY revenue DESC",
    )
    return json_api(rows, request)


@app.get("/api/latest-orders")
def api_latest_orders(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select=f"""SELECT l.L_ORDERKEY AS order_id,
             MAX(l.L_SHIPDATE) AS order_date,
             l.L_ORDERSTATUS AS status,
             l.L_MKTSEGMENT AS market_segment,
             l.L_REGIONNAME AS region,
             ROUND(SUM({lineitem_revenue("l")}), 2) AS total_amount""",
        group_by="GROUP BY l.L_ORDERKEY, l.L_ORDERSTATUS, l.L_MKTSEGMENT, l.L_REGIONNAME",
        order_by="ORDER BY MAX(l.L_SHIPDATE) DESC, l.L_ORDERKEY DESC",
        limit="LIMIT 20",
    )
    return json_api(rows, request)


@app.get("/api/table-stats")
def api_table_stats(request: Request):
    target, scale, segment = request_params(
        warehouse=request.query_params.get("warehouse"),
        scale=request.query_params.get("scale"),
        segment=request.query_params.get("segment"),
    )
    rows = run_dashboard_query(
        target,
        scale,
        segment,
        select="""SELECT
        COUNT(*) AS lineitem_rows,
        COUNT(DISTINCT l.L_ORDERKEY) AS order_rows""",
    )
    return json_api(rows[0] if rows else {}, request)


def main() -> None:
    global DEFAULT_SCALE, PORT

    parser = argparse.ArgumentParser(description="TPC-H benchmark dashboard server")
    parser.add_argument("--scale", choices=SCALES, help="Default TPC-H scale factor")
    parser.add_argument("--port", type=int, default=PORT, help="HTTP port")
    args, _unknown = parser.parse_known_args()

    if args.scale:
        DEFAULT_SCALE = args.scale
    PORT = args.port

    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
