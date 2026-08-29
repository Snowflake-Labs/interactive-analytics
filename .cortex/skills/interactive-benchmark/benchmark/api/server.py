"""Benchmark API server — runs queries against an interactive warehouse."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Lock, Semaphore
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
INTERACTIVE_WAREHOUSE = os.environ.get("INTERACTIVE_WAREHOUSE", f"{SOLUTION_NAME}_BENCH_WH_INT")
INTERACTIVE_SCHEMA = os.environ.get("INTERACTIVE_SCHEMA", f"{SOLUTION_NAME}_IT")
QUERY_TAG = os.environ.get("QUERY_TAG", SOLUTION_NAME)
POOL_SIZE = int(os.environ.get("POOL_SIZE", "40"))
POOL_WARMUP = int(os.environ.get("POOL_WARMUP", "0"))
POOL_ACQUIRE_TIMEOUT = float(os.environ.get("POOL_ACQUIRE_TIMEOUT", "30"))
QUERIES_DIR = os.environ.get(
    "BENCHMARK_QUERIES_DIR",
    str(ROOT_DIR / "test") if not Path("/app/test").exists() else "/app/test",
)
WORKERS = int(os.environ.get("WORKERS", "1"))
PORT = int(os.environ.get("PORT", "3000"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("benchmark")


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


def connection_kwargs() -> dict[str, Any]:
    return {
        **base_connection_kwargs(),
        "warehouse": INTERACTIVE_WAREHOUSE,
        "database": DATABASE,
        "schema": INTERACTIVE_SCHEMA,
        "session_parameters": {
            "QUERY_TAG": QUERY_TAG,
            "USE_CACHED_RESULT": False,
        },
    }


class ConnectionPool:
    """Bounded, blocking pool: at most POOL_SIZE live connections.

    - A Semaphore caps total live connections (idle + borrowed).
    - Idle connections are kept in an unbounded Queue.
    - acquire() blocks up to POOL_ACQUIRE_TIMEOUT waiting for a slot; if the
      idle queue is empty when a slot is granted, a new connection is created.
    - release() returns the connection to the idle queue and frees the slot.
    """

    def __init__(self, size: int = POOL_SIZE) -> None:
        self._size = size
        self._idle: Queue[snowflake.connector.SnowflakeConnection] = Queue()
        self._sem = Semaphore(size)

    def _new_connection(self) -> snowflake.connector.SnowflakeConnection:
        return snowflake.connector.connect(**connection_kwargs())

    def acquire(self) -> snowflake.connector.SnowflakeConnection:
        if not self._sem.acquire(timeout=POOL_ACQUIRE_TIMEOUT):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Connection pool exhausted "
                    f"(size={self._size}, timeout={POOL_ACQUIRE_TIMEOUT}s)"
                ),
            )
        try:
            while True:
                try:
                    conn = self._idle.get_nowait()
                except Empty:
                    return self._new_connection()
                if conn.is_closed():
                    continue
                return conn
        except Exception:
            self._sem.release()
            raise

    def release(self, conn: snowflake.connector.SnowflakeConnection) -> None:
        try:
            if not conn.is_closed():
                self._idle.put_nowait(conn)
        finally:
            self._sem.release()

    def warmup(self, count: int | None = None) -> int:
        """Pre-open up to `count` (default: POOL_SIZE) connections and park them."""
        want = self._size if count is None else min(count, self._size)
        opened = 0
        for _ in range(want):
            try:
                conn = self._new_connection()
            except Exception as exc:
                log.warning("Pool warmup failed after %d/%d: %s", opened, want, exc)
                break
            self._idle.put_nowait(conn)
            opened += 1
        return opened


pool = ConnectionPool()


def load_query_registry(directory: str) -> dict[str, str]:
    """Load .sql files from directory into a {stem: sql_text} registry."""
    queries_path = Path(directory)
    registry: dict[str, str] = {}
    if not queries_path.exists():
        log.warning("Queries directory does not exist: %s", directory)
        return registry
    for sql_file in sorted(queries_path.glob("*.sql")):
        text = sql_file.read_text().strip()
        if text:
            registry[sql_file.stem] = text
    log.info("Loaded %d queries from %s", len(registry), directory)
    return registry


query_registry: dict[str, str] = load_query_registry(QUERIES_DIR)


def execute_query(sql: str) -> dict[str, Any]:
    conn = pool.acquire()
    try:
        with conn.cursor(DictCursor) as cur:
            t0 = time.perf_counter()
            cur.execute(sql)
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            rows = cur.fetchall()
            return {
                "elapsed_ms": elapsed_ms,
                "row_count": len(rows),
                "warehouse": INTERACTIVE_WAREHOUSE,
                "query_id": cur.sfqid,
            }
    finally:
        pool.release(conn)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Benchmark API running at http://localhost:%s", PORT)
    log.info("Pool size: %d, workers: %d", POOL_SIZE, WORKERS)
    log.info("Database: %s", DATABASE)
    log.info("Warehouse: %s", INTERACTIVE_WAREHOUSE)
    log.info("Schema: %s", INTERACTIVE_SCHEMA)
    if CONNECTION_NAME:
        log.info("Snowflake connection: %s", CONNECTION_NAME)

    if POOL_WARMUP > 0:
        async def _warmup() -> None:
            try:
                opened = await asyncio.to_thread(pool.warmup, POOL_WARMUP)
                log.info("Prewarmed %d/%d connections", opened, POOL_WARMUP)
            except Exception as exc:  # noqa: BLE001
                log.warning("Warmup failed: %s", exc)

        warmup_task = asyncio.create_task(_warmup())
    else:
        warmup_task = None
    yield
    if warmup_task is not None and not warmup_task.done():
        warmup_task.cancel()


app = FastAPI(title="Interactive Warehouse Benchmark API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})
    return JSONResponse(status_code=500, content={"error": str(exc)})


class RunRequest(BaseModel):
    query_id: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/queries")
async def list_queries():
    return sorted(query_registry.keys())


@app.post("/api/run")
@app.post("/api/run/interactive")
async def run_query(body: RunRequest):
    sql = query_registry.get(body.query_id)
    if sql is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown query_id '{body.query_id}'. Use GET /api/queries to list available IDs.",
        )
    return await asyncio.to_thread(execute_query, sql)


def main() -> None:
    global PORT, WORKERS

    parser = argparse.ArgumentParser(description="Benchmark API server")
    parser.add_argument("--port", type=int, default=PORT, help="HTTP port")
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help="Number of Uvicorn worker processes (default: WORKERS env or 1)",
    )
    args, _unknown = parser.parse_known_args()

    PORT = args.port
    WORKERS = max(1, args.workers)

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=WORKERS if WORKERS > 1 else None,
    )


if __name__ == "__main__":
    main()
