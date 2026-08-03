---
name: interactive-benchmark
description: "Benchmark any SQL query on Snowflake Interactive Warehouses vs Standard Warehouses. Chains the snowflake-interactive skill first to create interactive tables and optimize queries, then deploys a benchmark API + Locust load test to SPCS. Use when: benchmarking queries, comparing interactive vs standard warehouse performance, load testing, deploying benchmark infrastructure. Triggers: benchmark, interactive warehouse benchmark, compare warehouse, load test, locust, benchmark my query, performance comparison."
---

# Interactive Warehouse Benchmark

Benchmarks any user-provided SQL query against both Interactive and Standard Snowflake warehouses, using a FastAPI server deployed to SPCS and Locust for load generation.

## Prerequisites

- `uv` installed (Python package runner)
- A Snowflake connection configured in `~/.snowflake/connections.toml`
- Role with privileges to create databases, warehouses, compute pools, and services
- Docker installed (for SPCS deployment)

## CRITICAL: Chain the `snowflake-interactive` Skill First

Before running any benchmark, you MUST invoke the `snowflake-interactive` skill to:
1. Create interactive tables from the user's source tables
2. Create an interactive warehouse attached to those tables
3. Optimize the query for interactive warehouse execution
4. Create a corresponding standard warehouse for comparison

**Do this by calling:**
```
skill(command="snowflake-interactive")
```

Once the interactive setup is complete, proceed with the benchmark workflow below.

---

## Workflow

### Step 1: Detect Intent

Ask the user what they want to do:

1. **Setup + Benchmark** — Full flow: create interactive tables, optimize query, deploy, run benchmark
2. **Deploy benchmark API** — Deploy the FastAPI + Locust services to SPCS
3. **Run load test** — Execute Locust locally against the deployed API
4. **Check status** — Show SPCS service status and ingress URLs
5. **Teardown** — Remove SPCS services and compute pools

---

### Step 2: Invoke `snowflake-interactive` Skill

**This step is mandatory before benchmarking.**

Invoke the `snowflake-interactive` skill with the user's context:
- The database and schema containing the tables referenced in their query
- The query they want to benchmark

The `snowflake-interactive` skill will:
- Create interactive tables (copies of the source tables optimized for interactive workloads)
- Create an interactive warehouse with `TARGET_LAG` attached to those tables
- Return the warehouse names and schema names to use

Capture the output:
- `INTERACTIVE_WAREHOUSE` — name of the interactive warehouse created
- `STANDARD_WAREHOUSE` — name of the standard warehouse for comparison
- `INTERACTIVE_SCHEMA` — schema with interactive tables
- `STANDARD_SCHEMA` — schema with standard tables
- `OPTIMIZED_QUERY` — the query rewritten for the interactive schema (if different)

---

### Step 3: Place Benchmark Queries

Save the user's query (and/or the optimized version) into the `benchmark/test/` folder:

```bash
cat > <REPO_ROOT>/benchmark/test/user_query.sql << 'EOF'
<THE USER'S QUERY>
EOF
```

Each `.sql` file in `benchmark/test/` will be executed against both warehouse types during the load test.

---

### Step 4: Configure Environment

1. Ensure `benchmark/.env` exists with:
   ```
   CONNECTION_NAME=<user's connection>
   SOLUTION_NAME=<from snowflake-interactive output>
   DEFAULT_SCALE=<scale factor>
   ```

2. Review `benchmark/spcs/config.env` for SPCS deployment settings.

---

### Step 5: Deploy to SPCS

```bash
cd <REPO_ROOT>/benchmark/spcs && ./deploy.sh services
```

This deploys:
- **Benchmark API** — FastAPI server that executes queries against both warehouse types
- **Locust API** — Isolated copy of the API for load testing
- **Locust** — Load generator that POSTs queries to the API

---

### Step 6: Run Load Test

**Option A: Run locust locally** (recommended for quick tests):
```bash
cd <REPO_ROOT>/benchmark/locust
./run-local.sh <SPCS_API_INGRESS_URL> --users 10 --spawn 5 --run-time 2m --headless
```

**Option B: Use the SPCS-deployed Locust** (for sustained load):
Open the Locust ingress URL in a browser, configure users/spawn rate, and start.

---

### Step 7: Analyze Results

Locust reports include:
- Request latency percentiles (p50, p95, p99) per endpoint
- Throughput (requests/sec) for interactive vs standard
- Error rates

Compare `/api/run/interactive` vs `/api/run/standard` metrics to see the performance difference.

---

### Check Status

```bash
cd <REPO_ROOT>/benchmark/spcs && ./status.sh
```

Options:
- `./status.sh --wait` — poll until all services are READY
- `./status.sh --urls-only` — print only ingress URLs

---

### Teardown

```bash
cd <REPO_ROOT>/benchmark/spcs && ./teardown.sh
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/run/interactive` | Execute query on interactive warehouse |
| POST | `/api/run/standard` | Execute query on standard warehouse |

**Request body** for `/api/run/*`:
```json
{
  "query": "SELECT COUNT(*) FROM my_table",
  "scale": "100"
}
```

**Response**:
```json
{
  "elapsed_ms": 42,
  "row_count": 1,
  "warehouse": "IW_TPCH_BENCH_WH_INT_100",
  "target": "interactive",
  "scale": "100",
  "query_id": "01b..."
}
```

---

## Stopping Points

- After detecting intent — confirm action before proceeding
- After `snowflake-interactive` completes — confirm tables/warehouses were created
- Before `deploy.sh services` — warn about compute pool cost implications
- Before teardown — confirm which resources to drop

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No .sql files found` | Place query files in `benchmark/test/` folder |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Connection errors | Verify connection name in `~/.snowflake/connections.toml` |
| Interactive tables not found | Re-run `snowflake-interactive` skill |
