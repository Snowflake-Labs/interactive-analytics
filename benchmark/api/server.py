"""Generic benchmark API server — runs any query against interactive or standard warehouses."""

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
TARGETS = ["standard", "interactive"]
POOL_SIZE = int(os.environ.get("POOL_SIZE", "40"))
POOL_WARMUP = int(os.environ.get("POOL_WARMUP", "0"))
POOL_ACQUIRE_TIMEOUT = float(os.environ.get("POOL_ACQUIRE_TIMEOUT", "30"))
WORKERS = int(os.environ.get("WORKERS", "1"))
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
        "session_parameters": {
            "QUERY_TAG": "IW_BENCHMARK",
            "USE_CACHED_RESULT": False,
        },
    }


class ConnectionPool:
    """Bounded, blocking pool: at most POOL_SIZE live connections per target.

    - A per-key Semaphore caps total live connections (idle + borrowed).
    - Idle connections are kept in an unbounded Queue.
    - acquire() blocks up to POOL_ACQUIRE_TIMEOUT waiting for a slot; if the
      idle queue is empty when a slot is granted, a new connection is created.
    - release() returns the connection to the idle queue and frees the slot.
    """

    def __init__(self, size: int = POOL_SIZE) -> None:
        self._size = size
        self._idle: dict[str, Queue[snowflake.connector.SnowflakeConnection]] = {}
        self._sem: dict[str, Semaphore] = {}
        self._init_lock = Lock()

    def _slots_for(
        self, key: str
    ) -> tuple[Queue[snowflake.connector.SnowflakeConnection], Semaphore]:
        with self._init_lock:
            if key not in self._idle:
                self._idle[key] = Queue()
                self._sem[key] = Semaphore(self._size)
            return self._idle[key], self._sem[key]

    def _new_connection(self, target: str) -> snowflake.connector.SnowflakeConnection:
        return snowflake.connector.connect(**connection_kwargs_for(target))

    def acquire(self, target: str) -> snowflake.connector.SnowflakeConnection:
        idle, sem = self._slots_for(target)
        if not sem.acquire(timeout=POOL_ACQUIRE_TIMEOUT):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Connection pool exhausted for {target} "
                    f"(size={self._size}, timeout={POOL_ACQUIRE_TIMEOUT}s)"
                ),
            )
        try:
            while True:
                try:
                    conn = idle.get_nowait()
                except Empty:
                    return self._new_connection(target)
                if conn.is_closed():
                    continue
                return conn
        except Exception:
            sem.release()
            raise

    def release(self, target: str, conn: snowflake.connector.SnowflakeConnection) -> None:
        idle, sem = self._slots_for(target)
        try:
            if not conn.is_closed():
                idle.put_nowait(conn)
        finally:
            sem.release()

    def warmup(self, target: str, count: int | None = None) -> int:
        """Pre-open up to `count` (default: POOL_SIZE) connections and park them."""
        idle, _sem = self._slots_for(target)
        want = self._size if count is None else min(count, self._size)
        opened = 0
        for _ in range(want):
            try:
                conn = self._new_connection(target)
            except Exception as exc:
                log.warning("Pool warmup failed for %s after %d/%d: %s", target, opened, want, exc)
                break
            idle.put_nowait(conn)
            opened += 1
        return opened


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
    log.info("Pool size: %d per target, workers: %d", POOL_SIZE, WORKERS)
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

    if POOL_WARMUP > 0:
        async def _warmup_all() -> None:
            for target in TARGETS:
                try:
                    opened = await asyncio.to_thread(
                        pool.warmup, target, POOL_WARMUP
                    )
                    log.info(
                        "Prewarmed %d/%d connections for %s",
                        opened,
                        POOL_WARMUP,
                        target,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Warmup failed for %s: %s", target, exc)

        # Run warmup in the background so the app can start serving requests
        # immediately (important for SPCS readiness probes on cold start).
        warmup_task = asyncio.create_task(_warmup_all())
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
    query: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/run/interactive")
async def run_interactive(body: RunRequest):
    return await asyncio.to_thread(execute_query, body.query, "interactive")


@app.post("/api/run/standard")
async def run_standard(body: RunRequest):
    return await asyncio.to_thread(execute_query, body.query, "standard")


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
