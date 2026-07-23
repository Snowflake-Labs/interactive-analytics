# Plan: Benchmark API Restructure

## Overview

Remove the dashboard frontend and rewrite the API to expose exactly two endpoints (`/api/standard` and `/api/interactive`) that execute `sql/benchmark-query.sql` against the appropriate warehouse/schema and return only execution timing.

## Changes

### 1. Delete `public/` folder
Remove `public/index.html` entirely — no frontend needed.

### 2. Rewrite `api/server.py`

Strip the server down to:

- **Startup**: Read `sql/benchmark-query.sql`, connect to Snowflake using existing connection logic (CONNECTION_NAME or explicit env vars). Scale is fixed from `DEFAULT_SCALE` env var.
- **`GET /api/standard`** — Use warehouse `TPCH_BENCH_WH_{scale}`, schema `TPCH_SF{scale}`, execute the benchmark query, return JSON:
  ```json
  {"warehouse": "TPCH_BENCH_WH_10", "schema": "TPCH_SF10", "table": "LINEITEM_DASHBOARD", "execution_time_ms": 342}
  ```
- **`GET /api/interactive`** — Use warehouse `IW_TPCH_BENCH_WH_{scale}`, schema `TPCH_SF{scale}_IT`, execute the same query, return same shape.
- Remove all other endpoints (`/api/config`, `/api/segments`, `/api/kpis`, etc.).
- Remove static file serving.
- Simplify the connection pool (only need two connections: one per warehouse target).

### 3. Update `.env.example` and `run-dashboard.sh`

- `.env.example`: keep `CONNECTION_NAME` and `DEFAULT_SCALE`, remove comments about other unneeded vars.
- Optionally rename `run-dashboard.sh` → `run-benchmark.sh` (or keep as-is).

### 4. Update `locust/locustfile.py`

Simplify to hit only `/api/standard` and `/api/interactive` (or one of them based on `--warehouse` flag).

### 5. Clean up SPCS configs

Remove references to the dashboard frontend service if they are now irrelevant (the `spcs/dashboard/` Docker setup). Adjust spec files if needed. (This is optional — can be a follow-up if SPCS deployment isn't the immediate focus.)

## API Response Shape

```json
{
  "warehouse": "TPCH_BENCH_WH_10",
  "schema": "TPCH_SF10",
  "table": "LINEITEM_DASHBOARD",
  "execution_time_ms": 342
}
```

No query results are returned — only timing metadata for benchmarking purposes.
