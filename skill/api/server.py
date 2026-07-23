"""TPC-H benchmark API server — measures query execution time on standard vs interactive warehouses."""

from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any

import snowflake.connector
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Connection
CONNECTION_NAME = os.environ.get("CONNECTION_NAME")
DATABASE = os.environ.get("SNOWFLAKE_DATABASE")

# Standard warehouse config
STANDARD_WAREHOUSE = os.environ.get("STANDARD_WAREHOUSE")
STANDARD_SCHEMA = os.environ.get("STANDARD_SCHEMA")

# Interactive warehouse config
INTERACTIVE_WAREHOUSE = os.environ.get("INTERACTIVE_WAREHOUSE")
INTERACTIVE_SCHEMA = os.environ.get("INTERACTIVE_SCHEMA")

_REQUIRED_ENV = {
    "SNOWFLAKE_DATABASE": DATABASE,
    "STANDARD_WAREHOUSE": STANDARD_WAREHOUSE,
    "STANDARD_SCHEMA": STANDARD_SCHEMA,
    "INTERACTIVE_WAREHOUSE": INTERACTIVE_WAREHOUSE,
    "INTERACTIVE_SCHEMA": INTERACTIVE_SCHEMA,
}
_missing = [k for k, v in _REQUIRED_ENV.items() if not v]
if _missing:
    raise SystemExit(f"ERROR: Missing required environment variables: {', '.join(_missing)}")
QUERY_TAG = "IW_BENCHMARK"

PORT = int(os.environ.get("PORT", "3000"))

log = logging.getLogger("uvicorn")

# Load benchmark SQL
BENCHMARK_SQL = (ROOT_DIR / "sql" / "benchmark-query.sql").read_text().strip()


def credential_cache_options() -> dict[str, Any]:
    enabled = os.environ.get("SNOWFLAKE_CLIENT_STORE_TEMPORARY_CREDENTIAL", "true").lower() != "false"
    return {"client_store_temporary_credential": enabled}


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


TARGETS = {
    "standard": {"warehouse": STANDARD_WAREHOUSE, "schema": STANDARD_SCHEMA},
    "interactive": {"warehouse": INTERACTIVE_WAREHOUSE, "schema": INTERACTIVE_SCHEMA},
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

    def get(self, target: str) -> snowflake.connector.SnowflakeConnection:
        lock = self._lock_for(target)
        with lock:
            conn = self._connections.get(target)
            if conn is not None and not conn.is_closed():
                return conn

            cfg = TARGETS[target]
            kwargs = {
                **base_connection_kwargs(),
                **credential_cache_options(),
                "warehouse": cfg["warehouse"],
                "database": DATABASE,
                "schema": cfg["schema"],
            }
            conn = snowflake.connector.connect(**kwargs)
            with conn.cursor() as cur:
                cur.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")
                cur.execute(f"ALTER SESSION SET QUERY_TAG = '{QUERY_TAG}'")
            self._connections[target] = conn
            return conn


pool = ConnectionPool()


def run_benchmark(target: str) -> dict[str, Any]:
    cfg = TARGETS[target]
    conn = pool.get(target)
    with conn.cursor() as cur:
        start = time.perf_counter()
        cur.execute(BENCHMARK_SQL)
        cur.fetchall()
        elapsed_ms = round((time.perf_counter() - start) * 1000)

    return {
        "warehouse": cfg["warehouse"],
        "schema": cfg["schema"],
        "execution_time_ms": elapsed_ms,
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("TPC-H benchmark API running at http://localhost:%s", PORT)
    log.info("Database: %s", DATABASE)
    log.info("Standard:    warehouse=%s schema=%s", STANDARD_WAREHOUSE, STANDARD_SCHEMA)
    log.info("Interactive: warehouse=%s schema=%s", INTERACTIVE_WAREHOUSE, INTERACTIVE_SCHEMA)
    if CONNECTION_NAME:
        log.info("Snowflake connection: %s", CONNECTION_NAME)
    else:
        log.info("Snowflake account: %s", base_connection_kwargs().get("account"))
    yield


app = FastAPI(title="TPC-H Benchmark API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/standard")
def api_standard():
    result = run_benchmark("standard")
    log.info("\033[1mStandard\033[0m - Total execution time: %dms", result["execution_time_ms"])
    return JSONResponse(result)


@app.get("/api/interactive")
def api_interactive():
    result = run_benchmark("interactive")
    log.info("\033[1mInteractive\033[0m - Total execution time: %dms", result["execution_time_ms"])
    return JSONResponse(result)


def main() -> None:
    global PORT

    parser = argparse.ArgumentParser(description="TPC-H benchmark API server")
    parser.add_argument("--port", type=int, default=PORT, help="HTTP port")
    args, _unknown = parser.parse_known_args()
    PORT = args.port

    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
