# Interactive Warehouse Benchmark

A generic benchmark tool that compares Snowflake **Interactive Warehouses** against **Standard Warehouses** using any user-provided SQL query. Includes a Locust-based load test to measure query latency under concurrency.

## Repository Structure

```
benchmark/
├── api/          # Python FastAPI backend (two endpoints: /api/run/interactive, /api/run/standard)
├── test/         # SQL query files to benchmark (place your .sql files here)
├── locust/       # Locust load test that POSTs queries to both endpoints
├── reports/      # Generated HTML benchmark reports
└── spcs/         # Snowpark Container Services deployment (Dockerfiles, specs, scripts)
```

### `api/`

FastAPI server that connects to Snowflake and exposes two POST endpoints. Each endpoint executes the provided query against the corresponding warehouse type and returns timing metrics.

### `test/`

Place `.sql` files here — each containing a single query. The locust load test reads all files from this directory and benchmarks them against both warehouse types.

### `locust/`

Locust workload that reads queries from `test/`, then POSTs them to `/api/run/interactive` and `/api/run/standard`. Supports targeting one or both warehouse types.

### `reports/`

Generated HTML benchmark reports. Each report is named `YYYY-MM-DD-<SOLUTION_NAME>-benchmark-report.html` (e.g. `2026-08-06-IWBENCH-benchmark-report.html`). This directory is created automatically by the benchmark skill.

### `spcs/`

Everything needed to deploy the benchmark API and load test to Snowpark Container Services: Dockerfiles, service specs, and shell scripts for build, deploy, update, status, logs, and teardown.

## Running Locally

1. Copy `.env.example` to `.env` and configure:

   ```
   CONNECTION_NAME=<your_connection>
   SOLUTION_NAME=<your_solution_name>
   ```

   The connection must exist in `~/.snowflake/connections.toml`.

   All Snowflake object names are derived from `SOLUTION_NAME`:

   | Object | Name |
   |---|---|
   | Database | `<SOLUTION_NAME>_BENCH_DB` |
   | Standard warehouse | `<SOLUTION_NAME>_BENCH_WH_STD` |
   | Interactive warehouse | `<SOLUTION_NAME>_BENCH_WH_INT` |
   | Standard schema | `<SOLUTION_NAME>` |
   | Interactive schema | `<SOLUTION_NAME>_IT` |

   Override any of these with env vars: `INTERACTIVE_WAREHOUSE`, `STANDARD_WAREHOUSE`, `INTERACTIVE_SCHEMA`, `STANDARD_SCHEMA`.

2. Start the API server:

   ```bash
   cd api
   uv run python server.py
   ```

   The server runs on port 3000. Test with:
   ```bash
   curl -X POST http://localhost:3000/api/run/interactive \
     -H "Content-Type: application/json" \
     -d '{"query": "SELECT COUNT(*) FROM my_table"}'
   ```

## Sample Prompt

Below is a sample prompt you can use with the `interactive-benchmark` CoCo skill. It works against a TPC-H database that can be created using the setup script in the [`tpc-h/`](../tpc-h/) folder (run `./iwtpch.sh setup --scale 100`).

```
hi, I have the following query

SELECT
	N_NAME,
	COUNT(*) AS ORDERS
FROM ORDERS AS O
INNER JOIN CUSTOMER AS C ON O_CUSTKEY = C_CUSTKEY
INNER JOIN NATION   AS N ON C_NATIONKEY = N_NATIONKEY
WHERE O_ORDERDATE BETWEEN '1996-01-01' AND '1996-12-31'
GROUP BY ROLLUP (N_NAME)
ORDER BY N_NAME NULLS LAST;

and I want understand how it can benefit from interactive analytics. The query is
used in Dashboard along with other queries. The query must answer in less than a
second. The database with the table used by the query is DM_TESTTPCH_BENCH_DB and
the schema is TPCH_SF100. The filter on order date will be different and also it
might happen that users filter data for specific nation or region or even market.
How can I make sure that I can obtain the performance I need? Use the "PM"
connection to connect to Snowflake.

Please also run a benchmark so that I can see how it performs when there are 50
concurrent users
```

Adapt the database name, schema, scale factor, and connection name to match your own environment.

## Running the Load Test

The load test runs on SPCS. See [`spcs/README.md`](spcs/README.md) for full deployment instructions.

```bash
cd spcs
./deploy.sh
```

This builds images, pushes to the SPCS registry, creates compute pools and services, then prints ingress URLs. Control the Locust load generator via its REST API (curl).
