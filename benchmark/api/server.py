"""Generic benchmark API server — runs any query against interactive or standard warehouses."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Lock
from typing import Any

import snowflake.connector
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from snowflake.connector import DictCursor

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

SOLUTION_NAME = os.environ.get("SOLUTION_NAME", "IW_TPCH")
DATABASE = os.environ.get("SNOWFLAKE_DATABASE", f"{SOLUTION_NAME}_BENCH_DB")
CONNECTION_NAME = os.environ.get("CONNECTION_NAME")
TARGETS = ["standard", "interactive"]
POOL_SIZE = int(os.environ.get("POOL_SIZE", "10"))
PORT = int(os.environ.get("PORT", "3000"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("benchmark")


def schema_for_target(target: str) -> str:
    if target == "interactive":
        return os.environ.get("INTERACTIVE_SCHEMA", f"{SOLUTION_NAME}_IT")
    return os.environ.get("STANDARD_SCHEMA", SOLUTION_NAME)


def warehouse_for_target(target: str) -> str:
    if target == "interactive":
        return os.environ.get("INTERACTIVE_WAREHOUSE", f"{SOLUTION_NAME}_BENCH_WH_INT")
    return os.environ.get("STANDARD_WAREHOUSE", f"{SOLUTION_NAME}_BENCH_WH_STD")


def resolve_target(raw: str | None) -> str:
    target = "interactive" if raw in (None, "") else str(raw)
    if target not in TARGETS:
        raise ValueError(f'Invalid target {raw!r}. Use "standard" or "interactive".')
    return target


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


def connection_kwargs_for(target: str) -> dict[str, Any]:
    return {
        **base_connection_kwargs(),
        "warehouse": warehouse_for_target(target),
        "database": DATABASE,
        "schema": schema_for_target(target),
    }


class ConnectionPool:
    """Queue-based pool: up to POOL_SIZE concurrent connections per target."""

    def __init__(self, size: int = POOL_SIZE) -> None:
        self._size = size
        self._queues: dict[str, Queue[snowflake.connector.SnowflakeConnection]] = {}
        self._init_lock = Lock()

    def _queue_for(self, key: str) -> Queue[snowflake.connector.SnowflakeConnection]:
        with self._init_lock:
            if key not in self._queues:
                self._queues[key] = Queue(maxsize=self._size)
            return self._queues[key]

    def _new_connection(self, target: str) -> snowflake.connector.SnowflakeConnection:
        kwargs = connection_kwargs_for(target)
        conn = snowflake.connector.connect(**kwargs)
        wh = warehouse_for_target(target)
        schema = schema_for_target(target)
        with conn.cursor() as cur:
            cur.execute(f"USE WAREHOUSE {wh}")
            cur.execute(f"USE DATABASE {DATABASE}")
            cur.execute(f"USE SCHEMA {schema}")
            cur.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")
            cur.execute("ALTER SESSION SET QUERY_TAG = 'IW_BENCHMARK'")
        return conn

    def acquire(self, target: str) -> snowflake.connector.SnowflakeConnection:
        q = self._queue_for(target)
        try:
            conn = q.get_nowait()
            if conn.is_closed():
                conn = self._new_connection(target)
            return conn
        except Empty:
            return self._new_connection(target)

    def release(self, target: str, conn: snowflake.connector.SnowflakeConnection) -> None:
        q = self._queue_for(target)
        try:
            q.put_nowait(conn)
        except Exception:
            conn.close()


pool = ConnectionPool()


def execute_query(sql: str, target: str) -> dict[str, Any]:
    conn = pool.acquire(target)
    try:
        with conn.cursor(DictCursor) as cur:
            t0 = time.perf_counter()
            cur.execute(sql)
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            rows = cur.fetchall()
            return {
                "elapsed_ms": elapsed_ms,
                "row_count": len(rows),
                "warehouse": warehouse_for_target(target),
                "target": target,
                "query_id": cur.sfqid,
            }
    finally:
        pool.release(target, conn)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Benchmark API running at http://localhost:%s", PORT)
    log.info("Database: %s", DATABASE)
    log.info(
        "Warehouses: interactive=%s, standard=%s",
        warehouse_for_target("interactive"),
        warehouse_for_target("standard"),
    )
    log.info(
        "Schemas: interactive=%s, standard=%s",
        schema_for_target("interactive"),
        schema_for_target("standard"),
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/run/interactive")
async def run_interactive(body: RunRequest):
    return execute_query(body.query, "interactive")


@app.post("/api/run/standard")
async def run_standard(body: RunRequest):
    return execute_query(body.query, "standard")


def main() -> None:
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
