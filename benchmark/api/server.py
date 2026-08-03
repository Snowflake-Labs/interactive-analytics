"""Generic benchmark API server — runs any query against interactive or standard warehouses."""

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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from snowflake.connector import DictCursor

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

SOLUTION_NAME = os.environ.get("SOLUTION_NAME", "IW_TPCH")
DATABASE = os.environ.get("SNOWFLAKE_DATABASE", f"{SOLUTION_NAME}_BENCH_DB")
SCALES = ["1", "10", "100", "1000"]
CONNECTION_NAME = os.environ.get("CONNECTION_NAME")
TARGETS = ["standard", "interactive"]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("benchmark")


def parse_cli_scale(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--scale" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.isdigit() and arg in SCALES:
            return arg
    return None


DEFAULT_SCALE = parse_cli_scale(sys.argv[1:]) or os.environ.get("DEFAULT_SCALE", "100")
PORT = int(os.environ.get("PORT", "3000"))


def schema_for_target(target: str, scale: str) -> str:
    return f"TPCH_SF{scale}_IT" if target == "interactive" else f"TPCH_SF{scale}"


def warehouse_for_target(target: str, scale: str) -> str:
    return (
        f"{SOLUTION_NAME}_BENCH_WH_INT_{scale}"
        if target == "interactive"
        else f"{SOLUTION_NAME}_BENCH_WH_STD_{scale}"
    )


def resolve_target(raw: str | None) -> str:
    target = "interactive" if raw in (None, "") else str(raw)
    if target not in TARGETS:
        raise ValueError(f'Invalid target {raw!r}. Use "standard" or "interactive".')
    return target


def resolve_scale(raw: str | None) -> str:
    scale = str(raw or DEFAULT_SCALE)
    if scale not in SCALES:
        raise ValueError(f"Invalid scale {scale}. Use one of: {', '.join(SCALES)}")
    return scale


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
            wh = warehouse_for_target(target, scale)
            schema = schema_for_target(target, scale)
            with conn.cursor() as cur:
                cur.execute(f"USE WAREHOUSE {wh}")
                cur.execute(f"USE DATABASE {DATABASE}")
                cur.execute(f"USE SCHEMA {schema}")
                cur.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")
                cur.execute("ALTER SESSION SET QUERY_TAG = 'IW_BENCHMARK'")
            self._connections[key] = conn
            return conn


pool = ConnectionPool()


def execute_query(sql: str, target: str, scale: str) -> dict[str, Any]:
    conn = pool.get(target, scale)
    with conn.cursor(DictCursor) as cur:
        t0 = time.perf_counter()
        cur.execute(sql)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        rows = cur.fetchall()
        return {
            "elapsed_ms": elapsed_ms,
            "row_count": len(rows),
            "warehouse": warehouse_for_target(target, scale),
            "target": target,
            "scale": scale,
            "query_id": cur.sfqid,
        }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scale = resolve_scale(DEFAULT_SCALE)
    log.info("Benchmark API running at http://localhost:%s", PORT)
    log.info("Database: %s, default scale: SF%s", DATABASE, scale)
    log.info(
        "Warehouses: interactive=%s, standard=%s",
        warehouse_for_target("interactive", scale),
        warehouse_for_target("standard", scale),
    )
    if CONNECTION_NAME:
        log.info("Snowflake connection: %s", CONNECTION_NAME)
    yield


app = FastAPI(title="Interactive Warehouse Benchmark API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})
    return JSONResponse(status_code=500, content={"error": str(exc)})


class RunRequest(BaseModel):
    query: str
    scale: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/run/interactive")
async def run_interactive(body: RunRequest):
    scale = resolve_scale(body.scale)
    return execute_query(body.query, "interactive", scale)


@app.post("/api/run/standard")
async def run_standard(body: RunRequest):
    scale = resolve_scale(body.scale)
    return execute_query(body.query, "standard", scale)


def main() -> None:
    global DEFAULT_SCALE, PORT

    parser = argparse.ArgumentParser(description="Benchmark API server")
    parser.add_argument("--scale", choices=SCALES, help="Default TPC-H scale factor")
    parser.add_argument("--port", type=int, default=PORT, help="HTTP port")
    args, _unknown = parser.parse_known_args()

    if args.scale:
        DEFAULT_SCALE = args.scale
    PORT = args.port

    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
