# Interactive Warehouse Benchmark

A generic benchmark tool that compares Snowflake **Interactive Warehouses** against **Standard Warehouses** using any user-provided SQL query. Includes a Locust-based load test to measure query latency under concurrency.

## Repository Structure

```
benchmark/
├── api/          # Python FastAPI backend (two endpoints: /api/run/interactive, /api/run/standard)
├── test/         # SQL query files to benchmark (place your .sql files here)
├── locust/       # Locust load test that POSTs queries to both endpoints
└── spcs/         # Snowpark Container Services deployment (Dockerfiles, specs, scripts)
```

### `api/`

FastAPI server that connects to Snowflake and exposes two POST endpoints. Each endpoint executes the provided query against the corresponding warehouse type and returns timing metrics.

### `test/`

Place `.sql` files here — each containing a single query. The locust load test reads all files from this directory and benchmarks them against both warehouse types.

### `locust/`

Locust workload that reads queries from `test/`, then POSTs them to `/api/run/interactive` and `/api/run/standard`. Supports targeting one or both warehouse types.

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

## Running the Load Test

### Local (against local or remote API)

```bash
cd locust
./run-local.sh http://localhost:3000 --users 10 --spawn 5 --run-time 2m --headless
```

### Interactive mode (Locust web UI)

```bash
cd locust
uv run locust -f locustfile.py --host http://localhost:3000
```

Open `http://localhost:8089` to configure users, ramp-up rate, and duration.

## Deploying to Snowpark Container Services

See [`spcs/README.md`](spcs/README.md) for full deployment instructions.

```bash
cd spcs
./deploy.sh
```

This builds images, pushes to the SPCS registry, creates compute pools and services, then prints ingress URLs.
