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

1. **Benchmark name** — A short name for this benchmark (used as the `SOLUTION_NAME`). Suggest `IWBENCH` as the default and ask the user to confirm or provide an alternative. If the user provides a name longer than 20 characters or containing special characters, generate a concise alphanumeric name yourself (e.g. abbreviations, acronyms). The name is used to prefix all created resources (warehouses, databases, schemas). Check if there is an `.env` file already that has a `SOLUTION_NAME` specified, and, if yes, ask user for confirmation.
2. **Connection name** — Which Snowflake connection (from `~/.snowflake/connections.toml`) should be used?
3. **Database** — Which database should the query run against?
4. **Standard warehouse** — Which existing warehouse should be used as the reference for running the benchmark against standard tables?
5. **Concurrent users** — How many concurrent users should the load test simulate? This sets the Locust user count (`LOCUST_USERS`). Default: 50.
6. **Latency goal (P95)** — What is the target P95 latency for the benchmark? (e.g. "under 1 seconds"). If the user does not volunteer a latency goal, you MUST ask for one. This value is used to evaluate pass/fail in the final report and to determine whether the interactive warehouse meets the user's requirements. Default suggestion: 1 second. Note: interactive warehouses are designed for the 30ms–5sec latency range. If the user's target exceeds 5 seconds, warn them that the workload may not be a good fit for interactive warehouses.

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
3. **Run load test** — Run load test against the deployed API
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

### Step 5b: Validate Interactive Setup

After the `snowflake-interactive` skill completes, validate that the setup is correct before proceeding.

**1. Verify interactive tables are attached to the interactive warehouse:**

```sql
SHOW INTERACTIVE TABLES IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Confirm that each table referenced by the query appears in the output and that the `warehouse_name` column shows the `INTERACTIVE_WAREHOUSE`. If any table is missing or attached to a different warehouse, re-run the attachment or inform the user.

**2. Verify predicates align with clustering keys:**

For each interactive table, check its clustering key:

```sql
SHOW TABLES LIKE '<TABLE_NAME>' IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Compare the `cluster_by` column against the columns used in the query's WHERE/JOIN predicates. If the query filters on columns that are NOT part of the clustering key, warn the user that performance may be suboptimal. Suggest either:
- Rewriting the query to filter on clustered columns
- Adjusting the clustering key on the interactive table to match the query's access pattern

**3. Validate working set sizing:**

Check the total data size of the interactive tables:

```sql
SELECT TABLE_NAME, BYTES / (1024*1024*1024) AS SIZE_GB
FROM <DATABASE>.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '<INTERACTIVE_SCHEMA>';
```

Compare the total working set size against the interactive warehouse size. Guidance:
- XS: up to ~350 GB working set
- S: up to ~600 GB
- M: up to ~1200 GB
- L: up to ~2500 GB
- XL+: larger working sets

If the working set exceeds the warehouse's effective cache capacity, warn the user that not all data will fit in cache, leading to cache misses and higher latency. Suggest upsizing the warehouse or reducing the working set.

**Data scan volume guidance:** Monitor the total volume of data scanned by the query. Effective partition pruning should handle the heavy lifting — ideally the execution footprint should be well under 100 GB of scanned data even if the table is much larger. If the scanned volume cannot be further reduced (e.g. an aggregation over 100 GB is unavoidable), consider scaling up the warehouse to increase parallel processing capacity via additional cores rather than trying to shrink the data.

**4. Auto-suspend warning:**

Check the auto-suspend setting on the interactive warehouse:

```sql
SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
```

The minimum auto-suspend for interactive warehouses is 24 hours (86400 seconds). Warn the user:
- Suspending or resuming reintroduces cache warm-up delays (all cached data is lost)
- Each resume starts a new minimum billable period
- For benchmarking, ensure the warehouse has been running long enough for the cache to be warm before collecting measurements

---

### Step 6: Evaluate MWC Before Scaling Up

**CRITICAL: Before scaling up interactive warehouse, you MUST evaluate Multi-Warehouse Concurrency (MWC) capacity for both the interactive and standard warehouses.**

MWC determines how many concurrent queries a warehouse can handle before queueing. Scaling the API and Locust to 100+ users is pointless — and produces misleading results — if the warehouse itself starts queueing at 30 concurrent queries.

1. Check the current MWC setting for both warehouses:
   ```sql
   SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
   SHOW WAREHOUSES LIKE '<STANDARD_WAREHOUSE>';
   ```
   Look at the `max_concurrency_level` column (or `MAX_CLUSTERS` for multi-cluster warehouses).

2. Compare the planned user count against the warehouse's effective concurrency limit. If the target user count exceeds the warehouse's MWC capacity:
   - Inform the user that the warehouse will queue queries beyond its MWC limit
   - Suggest increasing MWC or using a multi-cluster warehouse before scaling up the load test
   - If the user proceeds anyway, note in the final report that results may reflect warehouse queueing rather than true query performance

3. Only after confirming adequate warehouse concurrency should you proceed with deploying higher user counts or adding API replicas.

This prevents a common mistake: increasing the size of a warehouse which is not actually resource constrained (in terms of CPU or Memory), but it is just limited in how many concurrent request it can handle, producing misleading benchmark numbers.

**Horizontal vs vertical scaling principle:** When the working set already resides in cache, horizontal scaling (multi-cluster) is more effective than vertical scaling (upsizing) for increasing throughput. Upsizing adds more compute but doesn't help if the bottleneck is concurrency slots. If the user needs to handle more concurrent queries, recommend adding clusters rather than increasing warehouse size.

---

### Step 7: Quick Suitability Check

Before deploying the full SPCS benchmark infrastructure, verify the query is a good candidate for interactive warehouses. This avoids spending time on a full load test for queries that will not benefit.

**Pre-flight: Verify the query is already tuned on standard compute.**
Migration to an interactive warehouse is NOT a silver bullet for inefficient queries. The query must already be optimized and performing well on a standard warehouse before benchmarking. If the query is slow due to missing clustering keys, bad predicates, or inefficient joins, fix those first.

Run the query on the standard warehouse first (disable result caching):

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <DATABASE>.<STANDARD_SCHEMA>;
<THE QUERY>;
```

**10-second rule:** If the query exceeds 10 seconds on the standard warehouse despite proper clustering and optimization, it is highly improbable to meet the 5-second interactive execution threshold. Stop here and inform the user that the query needs further optimization before it can benefit from an interactive warehouse. Do NOT proceed with the interactive comparison.

If the standard warehouse timing is acceptable (under 10 seconds), proceed with the interactive comparison.

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
- If the interactive query exceeds 5 seconds, treat this as a **fit warning**: interactive warehouses cancel SELECT statements after 5 seconds by design. The query is not suitable for interactive execution without further optimization or simplification. If the workload contains a mix of queries where *some* need more than 5 seconds, recommend setting a **fallback warehouse**: configure a standard warehouse as the fallback so that queries exceeding the interactive ceiling are automatically routed there. Ensure the querying role has USAGE on both the interactive warehouse and the fallback warehouse.
- If performance is similar or the standard warehouse is faster, **stop here** and inform the user: the query is not a good candidate for interactive warehouses. Explain why (e.g., the query does a full table scan, aggregation pattern doesn't benefit from interactive caching, query is too complex, for example with many joins and many subqueries). Suggest query characteristics that work well with interactive warehouses (point lookups, selective filters, dashboard-style queries on hot data). A good workload for interactive is query that is selective, such ones used for dashboards, APIs, alerting, or agentic workloads, not broad exploratory scans or long-running ad hoc analytics. At least more than 100GB in data size is needed for interactive analytics to be really effective. The expected query shapes are narrow and selective: few columns, targeted predicates, bounded time windows, small result sets. Queries should be parameterized (e.g. date ranges, customer IDs) so the same shape is executed repeatedly with different bind values — this is the pattern that benefits most from interactive caching. Avoid SELECT *, year-wide scans, and expensive patterns that force large reads or heavy compute. The ideal latency range for interactive workloads is 30ms–5sec.

Only proceed to the next step if the suitability check passes.

---

### Step 8: Save the Benchmark Query

The user provides the query to benchmark as part of their request to CoCo. Create `benchmark/test/benchmark-query.sql` from the template file `benchmark/test/benchmark-query.sql.template` by replacing the placeholder content with the actual query:

1. Read `<REPO_ROOT>/benchmark/test/benchmark-query.sql.template`
2. Replace the placeholder text with the user's query (or the optimized version if the `snowflake-interactive` skill produced one)
3. Write the result to `<REPO_ROOT>/benchmark/test/benchmark-query.sql`

This file is the single query executed against both warehouse types during the load test.

---

### Step 9: Configure Environment

Both config files MUST be created from their templates — never edit the templates directly.

1. **Create `benchmark/.env`** from `benchmark/.env.example`:
   ```bash
   cp <REPO_ROOT>/benchmark/.env.example <REPO_ROOT>/benchmark/.env
   ```
   Then fill in the values:
   ```
   CONNECTION_NAME=<user's connection>
   SOLUTION_NAME=<benchmark name from Step 1>
   ```

2. **Create `benchmark/spcs/config.env`** from `benchmark/spcs/config.env.template`:
   ```bash
   cp <REPO_ROOT>/benchmark/spcs/config.env.template <REPO_ROOT>/benchmark/spcs/config.env
   ```
   Then fill in values matching the user's environment (connection, role, warehouse names, schemas, user count, etc.). The template contains comments explaining each variable.

3. If `benchmark/.env` or `benchmark/spcs/config.env` already exist, verify their values match the current benchmark parameters. Update them if the user changed any inputs (connection, solution name, warehouses, user count).

---

### Step 10: Deploy to SPCS

```bash
cd <REPO_ROOT>/benchmark/spcs && ./deploy.sh
```

This deploys:
- **Benchmark API** — FastAPI server that executes queries against both warehouse types
- **Locust** — Load generator that POSTs queries to the API

**IMPORTANT — Deployment monitoring:** SPCS deployments can take 3–10 minutes (compute pool provisioning + image pull + container start). To avoid appearing stuck:

1. Run `deploy.sh` in the background.
2. Every 30 seconds, poll service status and report to the user:
   ```bash
   cd <REPO_ROOT>/benchmark/spcs && ./status.sh
   ```
   This shows the current state of each service (PENDING, READY, FAILED) along with a status message (e.g. "Pending scheduling", "Pulling image").
3. If a service stays in PENDING for more than 5 minutes, run `./logs.sh` and report any errors to the user. Common causes:
   - Compute pool still provisioning (normal — wait)
   - Image pull in progress (normal — wait)
   - Image not found (check `build-and-push.sh` succeeded)
   - Insufficient privileges (check ROLE)
4. If a service enters FAILED state, immediately show the user the output of `./logs.sh` and stop.
5. Only proceed to the next step once both services report READY.

---

### Step 11: Warm the Cache

Before collecting benchmark measurements, warm the interactive warehouse cache. This ensures the load test measures steady-state performance rather than cold-start latency.

**Cache warming guidance:**
- If the warehouse was recently resumed, do NOT expect immediate sub-second latency. The cache must be populated first.
- XS warehouses warm at roughly 300–400 MB/s; larger warehouses warm faster.
- For a 100 GB working set on XS, expect ~4–5 minutes of warming time before the cache is fully populated.
- Run the query multiple times (3–5 iterations) to ensure the relevant data pages are cached, not just once.

**Warm-up procedure:**

```bash
# Run multiple warm-up iterations
for i in 1 2 3 4 5; do
  curl -s -X POST <SPCS_API_INGRESS_URL>/api/run/interactive \
    -H 'Content-Type: application/json' \
    -d '{"query": "<THE USER QUERY>"}'
done

# Also warm the standard warehouse for fair comparison
curl -s -X POST <SPCS_API_INGRESS_URL>/api/run/standard \
  -H 'Content-Type: application/json' \
  -d '{"query": "<THE USER QUERY>"}'
```

Check that the last warm-up iteration shows latency close to expected steady-state (e.g. sub-second for a well-fitted workload). If latency is still high on the final iteration, run additional warm-up calls or wait for background cache population to complete.

Discard the results from these warm-up calls — they are not part of the benchmark.

---

### Step 12: Run Load Test

The load test always runs on the SPCS-deployed Locust service. Use the Locust REST API to start and monitor the test via curl.

**Start the test:**
```bash
curl -s -X POST <LOCUST_INGRESS_URL>/swarm \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'user_count=<CONCURRENT_USERS>&spawn_rate=5&host=<LOCUST_API_HOST>'
```

Where `<CONCURRENT_USERS>` is the number from Step 1 and `<LOCUST_API_HOST>` is the internal SPCS host for the API service (e.g. `http://benchmark-api:3000`).

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

### Step 13: Analyze Results and Generate Recommendations

After the load test completes, collect the Locust metrics:
- **Request latency percentiles: P50, P95, P99** — these three MUST be measured for every test run, for each endpoint
- Throughput (requests/sec) for interactive vs standard
- Error rates

**Latency goal convention:** When the user specifies a latency target (e.g. "queries must complete within 2 seconds"), interpret that as a **P95 target** unless they explicitly state otherwise.

Compare `/api/run/interactive` vs `/api/run/standard` metrics to see the performance difference.

Then invoke the `snowflake-interactive` skill again to analyze the benchmark results and produce optimization recommendations:
- Does the query need rewrites or tweaks for better interactive performance?
- Would clustering keys on the interactive tables improve results?
- Are there join or filter patterns that could benefit from search optimization?

Capture these recommendations for the report.

---

### Step 13b: Post-Benchmark Query Profile Diagnostics

After collecting load test metrics, inspect the Snowsight Query Profile for a sample of interactive warehouse queries to validate steady-state health. Use the query IDs returned by the API during the load test (or query `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`).

Check the following metrics:

| Metric | Target | What it means if bad |
|--------|--------|---------------------|
| **Remote read %** | 0% | Query is reading from remote storage instead of cache. Causes: poor clustering, undersized working-set cache, cold cache, or cache thrashing from too many concurrent queries touching different partitions. |
| **Bytes scanned** | Minimal (ideally <100 GB) | Partition pruning is not effective. Check clustering keys and predicate alignment. |
| **Compile time** | Low (< 50 ms) | Query is complex or not parameterized. Consider simplifying or using prepared statements. |
| **Queueing time** | 0 ms | Warehouse concurrency is saturated. Scale out with multi-cluster (see Step 6). |

**Treat high remote read percentage as a first-class smell.** If remote reads are > 0% for steady-state queries (after cache is warm), investigate:
1. **Poor clustering** — predicates don't align with clustering keys (see Step 5b)
2. **Undersized cache** — working set doesn't fit in warehouse cache (see Step 5b sizing)
3. **Cold cache** — warehouse was recently resumed or cache hasn't fully populated yet (see Step 11 warming)
4. **Cache thrashing** — too many diverse query patterns competing for cache space; consider reducing concurrency or narrowing the hot data set

Include these diagnostics in the HTML report (Step 14) under a "Query Profile Health" section.

---

### Step 14: Generate HTML Report

Use the `html-authoring` skill to create a comprehensive HTML report at `<REPO_ROOT>/benchmark/report.html`. The report must include:

1. **Benchmark Summary** — Date, connection, database, warehouse sizes (standard and interactive), number of users, duration
2. **Query** — The SQL query that was benchmarked (formatted with syntax highlighting)
3. **Table Details** — Source tables, row counts, whether subsets were used and what filters were applied
4. **Performance Results** — Latency percentiles (P50, P95, P99) for each endpoint, throughput, and error rates for both interactive and standard warehouses, presented side-by-side. All three percentiles are mandatory.
5. **Performance Comparison** — Speedup factor at P95 (standard_p95 / interactive_p95), visual chart comparing P50/P95/P99 for both warehouses
6. **Optimization Recommendations** — Output from the `snowflake-interactive` skill analysis:
   - Query rewrites or tweaks suggested
   - Clustering key recommendations
   - Any other tuning suggestions
7. **Configuration** — Warehouse sizes, compute pool specs, Locust settings used

Open the report in the browser for the user when done.

---

### Step 15: Teardown or Keep Services

After the report is generated, ask the user whether they want to:

1. **Tear down** — Remove all SPCS services and compute pools to stop incurring costs.
2. **Keep for further benchmarking** — Leave services running so they can re-run tests with different queries or settings.

If the user chooses to **tear down**:
```bash
cd <REPO_ROOT>/benchmark/spcs && ./teardown.sh
```

After the SPCS teardown completes, ask the user whether they also want to **drop the schemas** (and all tables/objects within them) that were created during the benchmark:

- `<DATABASE>.<INTERACTIVE_SCHEMA>` — contains the interactive tables
- `<DATABASE>.<STANDARD_SCHEMA>` — contains the standard tables (if created as copies)
- `<DATABASE>.SPCS` — the schema used for SPCS objects (image repo, services)

If the user confirms, drop them:

```sql
USE ROLE <ROLE>;
DROP SCHEMA IF EXISTS <DATABASE>.<INTERACTIVE_SCHEMA>; -- cascades to all tables/views within
DROP SCHEMA IF EXISTS <DATABASE>.<STANDARD_SCHEMA>;
DROP SCHEMA IF EXISTS <DATABASE>.SPCS;
```

If all schemas in the database have been dropped (i.e. the database was created entirely by this benchmark and is now empty), also ask whether to drop the database itself:

```sql
DROP DATABASE IF EXISTS <DATABASE>;
```

Always require explicit user confirmation before dropping schemas or the database — never do this automatically.

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

After running `teardown.sh`, ask the user whether they also want to drop the created schemas (and all contained tables/objects). See Step 15 for the full teardown flow with user confirmation.

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

## Minimal "Good Setup" Checklist

Before considering a benchmark complete, verify all of the following are true:

- [ ] Interactive table created with a **deliberate CLUSTER BY** matching the query's predicate columns
- [ ] Interactive warehouse created, resumed, and **explicitly used** (not accidentally falling back to a standard warehouse)
- [ ] Hot tables **attached** to the interactive warehouse with ADD TABLES (verified via `SHOW INTERACTIVE TABLES`)
- [ ] Warehouse **sized to working set** and expected concurrency (cache fits the data; MWC handles the user count)
- [ ] Query shapes are **selective, parameterized, and benchmarked after warm-up** (not cold-start measurements)
- [ ] Query Profile shows **low remote reads** (0% ideal), **low compile time** (< 50 ms), and **low queueing** (0 ms) for steady-state traffic

If any item fails, address it before drawing conclusions from benchmark numbers.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No .sql files found` | Place query files in `benchmark/test/` folder |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Connection errors | Verify connection name in `~/.snowflake/connections.toml` |
| Interactive tables not found | Re-run `snowflake-interactive` skill |
