---
name: interactive-benchmark
description: "Benchmark any SQL query on Snowflake Interactive Warehouses vs Standard Warehouses. Chains the snowflake-interactive skill first to create interactive tables and optimize queries, then deploys a benchmark API + Locust load test to SPCS. Use when: benchmarking queries, comparing interactive vs standard warehouse performance, load testing, deploying benchmark infrastructure. Triggers: benchmark, interactive warehouse benchmark, compare warehouse, load test, locust, benchmark my query, performance comparison."
---

# Interactive Warehouse Benchmark

Benchmarks any user-provided SQL query against both Interactive and Standard Snowflake warehouses, using a FastAPI server deployed to SPCS and Locust for load generation.

**IMPORTANT: This benchmark MUST use the SPCS-deployed API server and Locust load generator. Do NOT create alternative benchmarking approaches (e.g. running queries directly from the client, writing custom scripts, or bypassing Locust). The entire benchmark infrastructure — API server, Locust, compute pools — runs on SPCS.**

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

The user provides the SQL query to benchmark as part of their request to CoCo. CoCo writes it to `benchmark/test/benchmark-query.sql` before building and deploying.

### Step 1: Gather User Input

Before proceeding, ask the user for:

1. **Benchmark name** — A short name for this benchmark (used as the `SOLUTION_NAME`). If the user provides a name longer than 20 characters or containing special characters, generate a concise alphanumeric name yourself (e.g. abbreviations, acronyms). The name is used to prefix all created resources (warehouses, databases, schemas).
2. **Connection name** — Which Snowflake connection (from `~/.snowflake/connections.toml`) should be used?
3. **Database** — Which database should the query run against?
4. **Standard warehouse** — Which existing warehouse should be used as the reference for running the benchmark against standard tables?
5. **Concurrent users** — How many concurrent users should the load test simulate? This sets the Locust user count (`LOCUST_USERS`). Default: 10.

Use `SHOW WAREHOUSES LIKE '<warehouse_name>'` to determine the size of the provided standard warehouse. This size will be used later when creating the benchmark standard warehouse so the comparison is fair.

These values are used for both the `snowflake-interactive` setup and the benchmark API deployment.

---

### Step 2: Verify Docker is Running

Before proceeding, check that Docker is running:

```bash
docker info > /dev/null 2>&1
```

If Docker is not running, warn the user: **"Docker is required to build and push container images for the SPCS benchmark deployment. Please start Docker Desktop (or the Docker daemon) and try again."**

Do not continue with deployment steps until Docker is confirmed running.

---

### Step 3: Detect Intent

Ask the user what they want to do:

1. **Setup + Benchmark** — Full flow: create interactive tables, optimize query, deploy, run benchmark
2. **Deploy benchmark API** — Deploy the FastAPI + Locust services to SPCS
3. **Run load test** — Execute Locust locally against the deployed API
4. **Check status** — Show SPCS service status and ingress URLs
5. **Teardown** — Remove SPCS services and compute pools

---

### Step 4: Check Source Table Sizes

Before creating interactive tables, check the row count of each table referenced in the user's query:

```sql
SELECT TABLE_NAME, ROW_COUNT
FROM <DATABASE>.INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN (<list of tables from the query>);
```

If any table has more than 1 billion rows, ask the user whether they want to run the benchmark on a subset of the data. If they confirm:

1. Analyze the query's WHERE/JOIN predicates to determine which rows are actually needed.
2. Propose a filtering strategy that preserves data relevant to the query (e.g. a date range, a specific partition, or a LIMIT on a key dimension).
3. Clearly explain to the user exactly which subset will be used — specify the filter conditions and estimated row counts so there are no surprises about what the interactive tables will contain.
4. Create the subset tables (e.g. using `CREATE TABLE ... AS SELECT ... WHERE <filter>`) and use those as the source for the interactive tables.

If the user declines subsetting, proceed with the full tables.

---

### Step 5: Invoke `snowflake-interactive` Skill

**This step is mandatory before benchmarking.**

Invoke the `snowflake-interactive` skill with the user's context:
- The database and schema containing the tables referenced in their query
- The query they want to benchmark
- The size of the standard warehouse (from Step 1) — the skill will use this to determine the optimal interactive warehouse size

The `snowflake-interactive` skill will:
- Create interactive tables (copies of the source tables optimized for interactive workloads)
- Determine the best size for the interactive warehouse based on the data and workload characteristics
- Create an interactive warehouse with `TARGET_LAG` attached to those tables
- Return the warehouse names and schema names to use

Capture the output:
- `INTERACTIVE_WAREHOUSE` — name of the interactive warehouse created (and its size)
- `STANDARD_WAREHOUSE` — name of the standard warehouse for comparison
- `INTERACTIVE_SCHEMA` — schema with interactive tables
- `STANDARD_SCHEMA` — schema with standard tables
- `OPTIMIZED_QUERY` — the query rewritten for the interactive schema (if different)

---

### Step 6: Quick Suitability Check

Before deploying the full SPCS benchmark infrastructure, run the query once against each warehouse type to verify the query actually benefits from an interactive warehouse. This avoids spending time on a full load test for queries that show no improvement.

Run the query against both warehouses (disable result caching to get honest timings):

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;

USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <DATABASE>.<STANDARD_SCHEMA>;
<THE QUERY>;

USE WAREHOUSE <INTERACTIVE_WAREHOUSE>;
USE SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
<THE QUERY>;
```

Compare the two elapsed times. Present the results to the user:

| Warehouse | Elapsed |
|---|---|
| Standard (`<STANDARD_WAREHOUSE>`) | X ms |
| Interactive (`<INTERACTIVE_WAREHOUSE>`) | Y ms |
| **Speedup** | **N×** |

**Decision gate:**
- If the interactive warehouse is significantly faster (≥1.5× speedup), proceed with the full SPCS load test.
- If performance is similar or the standard warehouse is faster, **stop here** and inform the user: the query is not a good candidate for interactive warehouses. Explain why (e.g., the query does a full table scan, aggregation pattern doesn't benefit from interactive caching, data volume is too small). Suggest query characteristics that work well with interactive warehouses (point lookups, selective filters, dashboard-style queries on hot data).

Only proceed to the next step if the suitability check passes.

---

### Step 7: Save the Benchmark Query

The user provides the query to benchmark as part of their request to CoCo. Write it into the benchmark query file so it gets uploaded to SPCS during the Docker image build:

```bash
cat > <REPO_ROOT>/benchmark/test/benchmark-query.sql << 'EOF'
<THE USER'S QUERY>
EOF
```

If the `snowflake-interactive` skill produced an optimized version of the query, save the optimized query here instead.

This file is the single query executed against both warehouse types during the load test.

---

### Step 8: Configure Environment

1. Ensure `benchmark/.env` exists with:
   ```
   CONNECTION_NAME=<user's connection>
   SOLUTION_NAME=<from snowflake-interactive output>
   ```

2. Review `benchmark/spcs/config.env` for SPCS deployment settings.

---

### Step 9: Deploy to SPCS

```bash
cd <REPO_ROOT>/benchmark/spcs && ./deploy.sh services
```

This deploys:
- **Benchmark API** — FastAPI server that executes queries against both warehouse types
- **Locust API** — Isolated copy of the API for load testing
- **Locust** — Load generator that POSTs queries to the API

---

### Step 10: Warm the Cache

Before collecting benchmark measurements, run the query once against each warehouse to warm caches. This ensures the load test measures steady-state performance rather than cold-start latency.

```bash
curl -s -X POST <SPCS_API_INGRESS_URL>/api/run/interactive \
  -H 'Content-Type: application/json' \
  -d '{"query": "<THE USER QUERY>"}'

curl -s -X POST <SPCS_API_INGRESS_URL>/api/run/standard \
  -H 'Content-Type: application/json' \
  -d '{"query": "<THE USER QUERY>"}'
```

Discard the results from these warm-up calls — they are not part of the benchmark.

---

### Step 11: Run Load Test

The load test always runs on the SPCS-deployed Locust service. Use the Locust REST API to start and monitor the test via curl.

**Start the test:**
```bash
curl -s -X POST <LOCUST_INGRESS_URL>/swarm \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'user_count=<CONCURRENT_USERS>&spawn_rate=5&host=<LOCUST_API_HOST>'
```

Where `<CONCURRENT_USERS>` is the number from Step 1 and `<LOCUST_API_HOST>` is the internal SPCS host for the Locust API service (e.g. `http://dashboard-api-locust:3000`).

**Poll for completion** (check every 30 seconds):
```bash
curl -s <LOCUST_INGRESS_URL>/stats/requests
```

**Stop the test** after the desired duration:
```bash
curl -s <LOCUST_INGRESS_URL>/stop
```

**Retrieve final stats:**
```bash
curl -s <LOCUST_INGRESS_URL>/stats/requests
```

---

### Step 12: Analyze Results and Generate Recommendations

After the load test completes, collect the Locust metrics:
- Request latency percentiles (p50, p95, p99) per endpoint
- Throughput (requests/sec) for interactive vs standard
- Error rates

Compare `/api/run/interactive` vs `/api/run/standard` metrics to see the performance difference.

Then invoke the `snowflake-interactive` skill again to analyze the benchmark results and produce optimization recommendations:
- Does the query need rewrites or tweaks for better interactive performance?
- Would clustering keys on the interactive tables improve results?
- Are there join or filter patterns that could benefit from search optimization?

Capture these recommendations for the report.

---

### Step 13: Generate HTML Report

Use the `html-authoring` skill to create a comprehensive HTML report at `<REPO_ROOT>/benchmark/report.html`. The report must include:

1. **Benchmark Summary** — Date, connection, database, warehouse sizes (standard and interactive), number of users, duration
2. **Query** — The SQL query that was benchmarked (formatted with syntax highlighting)
3. **Table Details** — Source tables, row counts, whether subsets were used and what filters were applied
4. **Performance Results** — Latency percentiles (p50, p95, p99), throughput, and error rates for both interactive and standard warehouses, presented side-by-side
5. **Performance Comparison** — Speedup factor (standard_latency / interactive_latency), visual chart comparing the two
6. **Optimization Recommendations** — Output from the `snowflake-interactive` skill analysis:
   - Query rewrites or tweaks suggested
   - Clustering key recommendations
   - Any other tuning suggestions
7. **Configuration** — Warehouse sizes, compute pool specs, Locust settings used

Open the report in the browser for the user when done.

---

### Step 14: Teardown or Keep Services

After the report is generated, ask the user whether they want to:

1. **Tear down** — Remove all SPCS services and compute pools to stop incurring costs.
2. **Keep for further benchmarking** — Leave services running so they can re-run tests with different queries or settings.

If the user chooses to **tear down**:
```bash
cd <REPO_ROOT>/benchmark/spcs && ./teardown.sh
```

If the user chooses to **keep**, save the deployment state in `benchmark/.env` so future runs reuse the existing services instead of redeploying:

```
# Existing entries
CONNECTION_NAME=<connection>
SOLUTION_NAME=<name>

# SPCS deployment state (added when services are kept)
SPCS_DEPLOYED=true
SPCS_API_INGRESS_URL=<the ingress URL>
SPCS_LOCUST_INGRESS_URL=<the locust ingress URL>
```

On future invocations of this skill, check `benchmark/.env` for `SPCS_DEPLOYED=true`. If set, skip Step 9 (Deploy to SPCS) and reuse the saved ingress URLs for cache warming and load testing. If the user later wants to tear down, run `./teardown.sh` and remove the `SPCS_*` lines from `.env`.

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
  "query": "SELECT COUNT(*) FROM my_table"
}
```

**Response**:
```json
{
  "elapsed_ms": 42,
  "row_count": 1,
  "warehouse": "IW_TPCH_BENCH_WH_INT",
  "target": "interactive",
  "query_id": "01b..."
}
```

---

## Stopping Points

- After detecting intent — confirm action before proceeding
- After `snowflake-interactive` completes — confirm tables/warehouses were created
- After suitability check — stop if query shows no interactive benefit
- Before `deploy.sh services` — warn about compute pool cost implications
- Before teardown — confirm which resources to drop

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No .sql files found` | Place query files in `benchmark/test/` folder |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Connection errors | Verify connection name in `~/.snowflake/connections.toml` |
| Interactive tables not found | Re-run `snowflake-interactive` skill |
