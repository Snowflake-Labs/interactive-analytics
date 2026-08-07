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

**Every interactive table MUST have a `CLUSTER BY`, including tiny dimension/lookup tables.** `CREATE INTERACTIVE TABLE` fails with `An interactive table must contain clustering keys` if omitted. For lookup tables with no natural filter column (e.g. `NATION` with 25 rows, `REGION` with 5 rows), cluster on the primary key column — it satisfies the requirement at zero cost:

```sql
CREATE INTERACTIVE TABLE <SCHEMA>.NATION CLUSTER BY (N_NATIONKEY) AS SELECT * FROM <SRC>.NATION;
CREATE INTERACTIVE TABLE <SCHEMA>.REGION CLUSTER BY (R_REGIONKEY) AS SELECT * FROM <SRC>.REGION;
```

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

### Step 6: Configure Concurrency and Fallback Before Load Test

**CRITICAL: Interactive warehouses scale concurrency *horizontally* (multi-cluster), not vertically. You MUST configure `MAX_CLUSTER_COUNT` and a fallback warehouse BEFORE running the load test — not after failures show up.**

A single-cluster XSMALL interactive warehouse saturates at ~10–15 concurrent queries. Anything above that queues, and queued queries hit the 5-second interactive cancel threshold and fail. Upsizing the warehouse doesn't help — the working set already fits in a small cache. What's needed is more clusters serving in parallel.

#### 6a. Check current settings

```sql
SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
SHOW WAREHOUSES LIKE '<STANDARD_WAREHOUSE>';
```

Look at `min_cluster_count`, `max_cluster_count`, and `scaling_policy`.

#### 6b. Configure the interactive warehouse for the target user count

Compute the required cluster count from the user count captured in Step 1:

```
MAX_CLUSTER_COUNT = ceil(<CONCURRENT_USERS> / 15)
```

Round up. For 50 users this is 4; use 5 to leave headroom. Then apply:

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE> SET
  MIN_CLUSTER_COUNT = 1,
  MAX_CLUSTER_COUNT = <computed_value>,
  SCALING_POLICY = 'STANDARD';
```

#### 6c. Configure the fallback warehouse (mandatory before load-testing)

Interactive warehouses cancel any query exceeding 5 seconds. Under concurrent load there will always be a tail of queries that trip this limit — from momentary cache misses, cross-cluster metadata sync, or unlucky co-location on a hot cluster. A fallback warehouse transparently reroutes those queries to a standard warehouse so users see slower results instead of errors:

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE>
  SET FALLBACK_WAREHOUSE = <STANDARD_WAREHOUSE>;
```

The querying role must have `USAGE` on both warehouses.

**Fallback is not optional for benchmarks.** The load test itself creates outlier queries via contention even if the underlying query shape is fine. Without fallback, you will report failure rates that are an artifact of the interactive cancel policy, not real query performance.

#### 6d. Verify

```sql
SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE <INTERACTIVE_WAREHOUSE>;
```

Confirm `max_cluster_count` matches your computed value and `FALLBACK_WAREHOUSE` shows the standard warehouse.

**Horizontal vs vertical scaling principle:** When the working set already resides in cache, horizontal scaling (multi-cluster) is more effective than vertical scaling (upsizing) for increasing throughput. Upsizing adds more compute per cluster but doesn't help if the bottleneck is concurrency slots. If the user needs to handle more concurrent queries, add clusters — do not increase warehouse size.

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
- If the interactive warehouse is significantly faster (≥1.5× speedup), proceed with the full SPCS load test. The fallback warehouse configured in Step 6c will catch any tail queries that exceed 5 seconds under load.
- If the interactive query exceeds 5 seconds even at rest, treat this as a **fit warning**: interactive warehouses cancel SELECT statements after 5 seconds by design. The query is not suitable for interactive execution without further optimization or simplification. The fallback warehouse will absorb some outliers, but if the *typical* query takes >5 s the fallback becomes the primary path and interactive gives you nothing.
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

1. **Create `benchmark/.env`** from `benchmark/.env.template`:
   ```bash
   cp <REPO_ROOT>/benchmark/.env.template <REPO_ROOT>/benchmark/.env
   ```
   Write these exact values:
   ```
   CONNECTION_NAME=<connection from Step 1>
   SOLUTION_NAME=<benchmark name from Step 1>
   ```

2. **Create `benchmark/spcs/config.env`** from `benchmark/spcs/config.env.template`:
   ```bash
   cp <REPO_ROOT>/benchmark/spcs/config.env.template <REPO_ROOT>/benchmark/spcs/config.env
   ```

   Then **explicitly overwrite** these values in `config.env` from the answers gathered in Step 1 and the outputs captured in Step 5. Do NOT rely on template defaults — the whole run is wrong if any of these drift:

   | Variable | Source | Example |
   |---|---|---|
   | `CONNECTION` | Step 1 answer | `PM` |
   | `ROLE` | Step 1 or `ACCOUNTADMIN` | `ACCOUNTADMIN` |
   | `INTERACTIVE_WAREHOUSE` | **Step 5 output** — the exact name `snowflake-interactive` created | `DM_TESTTPCH_BENCH_WH_INT` |
   | `STANDARD_WAREHOUSE` | **Step 1 answer** — the warehouse the user pointed to | `DM_TESTTPCH_BENCH_WH_STD_100` |
   | `INTERACTIVE_SCHEMA` | **Step 5 output** | `TPCH_SF100_INT` |
   | `STANDARD_SCHEMA` | **Step 1 answer** | `TPCH_SF100` |
   | `API_DATABASE` | **Step 1 answer** | `DM_TESTTPCH_BENCH_DB` |
   | `LOCUST_USERS` | **Step 1 answer** — the concurrent-users number | `50` |
   | `LOCUST_RUN_TIME` | Default `3m`, or user-supplied | `3m` |
   | `LOCUST_WAREHOUSE` | Fixed as `both` for A/B comparison | `both` |

   After writing, `grep` the file to sanity-check that no template placeholder or stale value remains. The `INTERACTIVE_WAREHOUSE` and `LOCUST_USERS` values are the two most common sources of "the benchmark ran with the wrong settings" bugs.

3. If `benchmark/.env` or `benchmark/spcs/config.env` already exist from a previous run, do NOT reuse them blindly. Diff each value in the table above against the current Step 1/Step 5 answers and overwrite anything that changed.

**Note on Locust execution model:** As of this skill version, Locust runs in **non-headless mode with `--autostart` inside the container** — no external HTTP calls are needed to trigger the run. There is no `LOCUST_HEADLESS` toggle. See Step 12 for the execution flow.

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

Before the load test measures anything, warm the interactive warehouse cache. This ensures the numbers reflect steady-state performance, not cold-start latency.

**Cache warming guidance:**
- If the warehouse was recently resumed, do NOT expect immediate sub-second latency. The cache must be populated first.
- XS warehouses warm at roughly 300–400 MB/s; larger warehouses warm faster.
- For a 100 GB working set on XS, expect ~4–5 minutes of warming time before the cache is fully populated.
- Run the query multiple times (3–5 iterations) to ensure the relevant data pages are cached, not just once.

**Warm-up procedure (via SQL, since the SPCS API ingress requires Snowflake auth and can't be curled from the laptop with `externalbrowser` connections):**

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;

-- Warm interactive warehouse and each attached table
USE WAREHOUSE <INTERACTIVE_WAREHOUSE>;
USE SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
<THE QUERY>;               -- iteration 1
<THE QUERY>;               -- iteration 2
<THE QUERY>;               -- iteration 3

-- Then warm standard for a fair comparison
USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <DATABASE>.<STANDARD_SCHEMA>;
<THE QUERY>;
<THE QUERY>;
```

Also warm each *variant* query shape (`benchmark-query-q1.sql`, `benchmark-query-nation.sql`, etc.) at least once so the tail of the load test doesn't include cold-cache measurements.

Check that the last warm-up iteration shows latency close to expected steady-state (e.g. sub-second for a well-fitted workload). If latency is still high on the final iteration, run more iterations or wait for background cache population to complete.

Discard the results from these warm-up calls — they are not part of the benchmark.

---

### Step 12: Run Load Test

**Execution model:** Locust runs inside the SPCS container in **non-headless mode with `--autostart --autoquit --run-time`**. When the container starts, the swarm begins automatically, runs for `LOCUST_RUN_TIME`, then locust quits. The container stays alive afterward and periodically re-prints the results CSV to stdout so `snow spcs service logs` can retrieve them at any time.

This means **there is no external HTTP call needed to trigger the test.** Starting the container starts the test. SPCS public ingress requires Snowflake auth, so external `curl /swarm` calls will not work with `externalbrowser` connections and no stored PAT — the auto-start design sidesteps this entirely.

#### 12a. Trigger the run

Depending on state:
- **First run after `./deploy.sh`** — the locust container just came up; the swarm is already running. No action needed. Proceed to 12b.
- **Subsequent runs after changing config or warehouse settings** — force a container restart by re-applying the spec:
  ```bash
  cd <REPO_ROOT>/benchmark/spcs && ./update.sh
  ```
  Or suspend+resume directly via SQL:
  ```sql
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST SUSPEND;
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST RESUME;
  ```
  Then wait for locust to report READY:
  ```bash
  cd <REPO_ROOT>/benchmark/spcs && ./status.sh --wait
  ```

#### 12b. Monitor the run

The test runs for `LOCUST_RUN_TIME` (default 3 minutes). While it runs:

- **Watch cluster scaling** on the interactive warehouse:
  ```sql
  SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
  ```
  Look at `started_clusters` and `running`. If `queued > 0`, `MAX_CLUSTER_COUNT` from Step 6b is too low — abort and increase it.

- **Follow locust logs** for progress:
  ```bash
  cd <REPO_ROOT>/benchmark/spcs && ./logs.sh locust
  ```
  You'll see lines like `Ramping to 50 users at a rate of 5.00 per second` and `All users spawned`.

#### 12c. Retrieve the results

After `LOCUST_RUN_TIME + ~10 s` (for `--autoquit` to fire), locust exits and the entrypoint prints a `======================== BENCHMARK RESULTS ========================` banner followed by the stats CSV:

```bash
cd <REPO_ROOT>/benchmark/spcs && ./logs.sh locust | tail -80
```

The `locust_stats_stats.csv` block contains three rows (per endpoint + Aggregated) with columns:

```
Type, Name, Request Count, Failure Count, Median Response Time, Average Response Time,
Min, Max, Avg Content Size, Requests/s, Failures/s, 50%, 66%, 75%, 80%, 90%, 95%, 98%, 99%, 99.9%, 99.99%, 100%
```

Parse the `/api/run/interactive` and `/api/run/standard` rows for P50, P95, P99 and failure counts.

If you need results before the test finishes, the container also emits a HEARTBEAT block every 2 minutes with the current CSV — grep for `HEARTBEAT` in the logs.

---

### Step 13: Analyze Results and Generate Recommendations

After the load test completes, collect **two independent measurements** of latency for every run:

1. **Client-side (Locust HTTP)** — P50, P95, P99 from the Locust CSV for each endpoint. This is what the end user experiences (HTTP round-trip + API pool + Snowflake).
2. **Server-side (Snowflake)** — P50, P95, P99 computed from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` for each warehouse. This is what Snowflake alone spent (compile + queue + execute).

Both sets of numbers are **mandatory**. The server-side numbers are what proves Snowflake performance; the client-side numbers are what the user's dashboard sees. The **delta between them isolates the API/HTTP overhead from Snowflake's real cost** — without this comparison you cannot tell whether the API layer is a bottleneck or the warehouse is.

Also collect:
- Throughput (requests/sec) for interactive vs standard (Locust)
- Error rates (Locust) and count of fallback-served queries (server-side query count on the standard WH minus direct standard-endpoint Locust requests)

**Latency goal convention:** When the user specifies a latency target (e.g. "queries must complete within 2 seconds"), interpret that as a **P95 target** unless they explicitly state otherwise. Evaluate the goal against **both** client-side and server-side P95 — if server-side meets the goal but client-side does not, the API is the bottleneck; if both fail, the warehouse configuration needs work.

Then invoke the `snowflake-interactive` skill again to analyze the benchmark results and produce optimization recommendations:
- Does the query need rewrites or tweaks for better interactive performance?
- Would clustering keys on the interactive tables improve results?
- Are there join or filter patterns that could benefit from search optimization?

Capture these recommendations for the report.

---

### Step 13b: Post-Benchmark Server-Side Validation

After collecting the Locust CSV, **you MUST run server-side aggregation queries against Snowflake for both warehouses and both compute percentiles + per-query profile metrics**. This is not optional — the Locust numbers alone cannot distinguish API/HTTP overhead from Snowflake time, and cannot tell you whether the P99 tail is queueing, cold cache, or genuine execution cost.

**Important — use `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE`, not `ACCOUNT_USAGE.QUERY_HISTORY`.** The `ACCOUNT_USAGE` view has a 45-minute to 3-hour latency and will return zero rows immediately after the benchmark. `INFORMATION_SCHEMA` is fresh within seconds. Also run these diagnostic queries from a **standard** warehouse (e.g. `USE WAREHOUSE <STANDARD_WAREHOUSE>` or any non-interactive WH) — running them on the interactive WH will hit the 5-second cancel because meta queries against QUERY_HISTORY on large windows can exceed that limit.

The API sets `QUERY_TAG='IW_BENCHMARK'` on every request, which is useful for isolating benchmark traffic when the account is busy.

**1. Aggregate server-side percentiles per warehouse.**

Run this for each of the interactive and standard warehouses:

```sql
SELECT
  COUNT(*) AS N,
  AVG(TOTAL_ELAPSED_TIME)::INT AS AVG_MS,
  MEDIAN(TOTAL_ELAPSED_TIME)::INT AS P50_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.90)::INT AS P90_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95)::INT AS P95_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.99)::INT AS P99_MS,
  AVG(COMPILATION_TIME)::INT AS AVG_COMPILE_MS,
  AVG(EXECUTION_TIME)::INT AS AVG_EXEC_MS,
  AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME)::INT AS AVG_QUEUE_MS,
  (AVG(BYTES_SCANNED) / (1024*1024))::INT AS AVG_MB_SCAN
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  RESULT_LIMIT => 5000
))
WHERE START_TIME >= DATEADD(minute, -10, CURRENT_TIMESTAMP())
  AND EXECUTION_STATUS = 'SUCCESS';
```

Repeat with the standard warehouse name. These two rows give you the **authoritative server-side P50/P95/P99** for each warehouse over the load-test window.

**2. Compare client-side vs server-side — this is the API-vs-Snowflake diagnosis.**

Build this table for the report:

| Percentile | Locust interactive | Snowflake interactive | Delta (API+HTTP) | Locust standard | Snowflake standard | Delta (API+HTTP) |
|---|---|---|---|---|---|---|
| P50 | … | … | … | … | … | … |
| P95 | … | … | … | … | … | … |
| P99 | … | … | … | … | … | … |

Interpretation rules:
- **Delta < ~50 ms and roughly constant across percentiles** → API and HTTP round-trip are cheap; Snowflake is the whole story. Optimization work should target the warehouse / query / clustering.
- **Delta grows with percentile (P50 delta small, P95 delta large)** → API pool exhaustion or connection queueing under load. Increase `API_WORKERS` / `POOL_SIZE`, add more API instances, or raise the compute pool size.
- **Delta is large at every percentile** → API is undersized regardless of load. Same fix as above but more urgent.
- **Server-side P95 already exceeds the goal** → API tuning cannot save you; go back and fix the warehouse (multi-cluster, fallback size, clustering, query shape).

Always state the conclusion of this analysis in the report — the reader must know which layer to invest in.

**3. Pick outliers and inspect Query Profile.**

For a mix of median and slow queries, pull query IDs and open the Query Profile in Snowsight:

```sql
SELECT
  QUERY_ID,
  TOTAL_ELAPSED_TIME,
  COMPILATION_TIME,
  EXECUTION_TIME,
  QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME AS QUEUED_MS,
  BYTES_SCANNED,
  PERCENTAGE_SCANNED_FROM_CACHE
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  RESULT_LIMIT => 5000
))
WHERE START_TIME >= DATEADD(minute, -10, CURRENT_TIMESTAMP())
  AND EXECUTION_STATUS = 'SUCCESS'
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 20;
```

Check the following metrics per profile:

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

Include the server-side percentile table, the side-by-side comparison table, and the profile-health verdict in the HTML report (Step 14) under a "Server-Side Validation" section.

---

### Step 14: Generate HTML Report

**MANDATORY: use the bundled template.** The report MUST be produced by starting from the canonical HTML template shipped with this skill and filling in its `{{PLACEHOLDER}}` tokens. Do NOT hand-author the report from scratch, do NOT change the section order, and do NOT modify the CSS or structure. This guarantees every benchmark report has the same layout, the same mandatory sections, and the same style.

**Template path (relative to this SKILL.md):**

```
templates/benchmark-report.html.template
```

**Output path and filename:**

Write the filled-in report to `<REPO_ROOT>/benchmark/reports/YYYY-MM-DD-<SOLUTION_NAME>-benchmark-report.html`, where `YYYY-MM-DD` is the current date and `<SOLUTION_NAME>` is the benchmark name from Step 1 (e.g. `2026-08-06-IWBENCH-benchmark-report.html`). Create the `reports` directory if it does not already exist.

**Procedure:**

1. Read the template file from `templates/benchmark-report.html.template` in this skill folder.
2. Substitute every `{{PLACEHOLDER}}` token with the corresponding value collected during Steps 1, 5, 6, 12b, and 13b. The template's header comment lists every placeholder and what it expects. Do NOT leave any placeholders unfilled — grep the output file for `{{` before saving to verify.
3. When a section's placeholder expects HTML fragments (e.g. `{{VARIANT_ROWS}}`, `{{BAR_CLIENT_ROWS}}`, `{{RECOMMENDATIONS_TO_MEET_GOAL}}`), emit valid HTML that follows the same tag patterns as the surrounding structure — do not invent new CSS classes.
4. Compute the speedup value (`{{P95_SPEEDUP}}`) from **server-side** numbers: `round(standard_p95_ms / interactive_p95_ms, 1) + "×"`. Never derive it from client-side numbers.
5. For the pill-class placeholders (`{{P95_INT_SERVER_CLASS}}`, `{{P50_INT_SERVER_CLASS}}`, `{{P50_INT_CLIENT_CLASS}}`, `{{FAILURE_CLASS}}`), pick one of `ok`, `warn`, or `bad` based on whether the value meets/misses the user-supplied latency goal from Step 1.
6. For the bottleneck verdict box (`{{BOTTLENECK_VERDICT_CLASS}}` and `{{BOTTLENECK_VERDICT}}`), the class must be one of `good`, `note`, or `bad-box`, matching the severity of the diagnosis: `good` if both API and Snowflake meet the goal, `note` if the tail is contained by fallback, `bad-box` if the goal is missed.
7. For the client-side and server-side percentile bar rows, compute each `width:N%` value using a shared scale-max per section — see the template's header comment for the sizing rule.

**Coverage requirement — every section in the template is mandatory:**

1. Executive Summary tiles (all 6)
2. Benchmark Setup (`kv` block)
3. Query and Filter Variants (primary query + variants table)
4. Table Details (Interactive)
5. Performance Results — Client-side (Locust HTTP), with P50/P95/P99 (all three mandatory)
6. Performance Results — Server-side (Snowflake), with P50/P95/P99 and compile / exec / queue / scan averages (mandatory — must appear ALONGSIDE the client-side section, never in place of it)
7. Client vs Server — Bottleneck Diagnosis (delta table + explicit verdict box naming which layer to optimize)
8. Client-Side and Server-Side Percentile Comparison bar charts
9. Query Profile Health (top-slowest table + verdict list)
10. Optimization Recommendations (to-meet-goal / already-ok / general)
11. Configuration Used (compute pools / API / interactive WH / Locust)

If any section is missing from the final HTML, the report is invalid — re-derive the missing placeholder from the collected data and re-emit.

**Verification before opening the report:**

- `grep '{{' <output-file>` must return zero matches (all placeholders filled).
- The file must contain each of the 11 section headings above.
- The `{{P95_SPEEDUP}}` value must be computed from server-side numbers.

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

- [ ] Interactive table created with a **deliberate CLUSTER BY** matching the query's predicate columns (every table, including tiny lookups)
- [ ] Interactive warehouse created, resumed, and **explicitly used** (not accidentally falling back to a standard warehouse)
- [ ] Hot tables **attached** to the interactive warehouse with ADD TABLES (verified via `SHOW INTERACTIVE TABLES`)
- [ ] Warehouse **sized to working set** (cache fits the data) — do NOT upsize to fix concurrency
- [ ] **`MAX_CLUSTER_COUNT` set proportional to target concurrent users** (rule: `ceil(users / 15)`; verified via `SHOW WAREHOUSES`)
- [ ] **Fallback warehouse configured** on the interactive warehouse (verified via `SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE'`)
- [ ] `config.env` values (INTERACTIVE_WAREHOUSE, STANDARD_WAREHOUSE, LOCUST_USERS, schemas) match Step 1/Step 5 outputs — no template placeholders left
- [ ] Query shapes are **selective, parameterized, and benchmarked after warm-up** (not cold-start measurements)
- [ ] Query Profile shows **low remote reads** (0% ideal), **low compile time** (< 50 ms), and **low queueing** (0 ms) for steady-state traffic
- [ ] **Server-side P50/P95/P99 collected** per warehouse from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` and reported **alongside** the Locust client-side percentiles
- [ ] **Client-vs-server delta analyzed** and the bottleneck (API/HTTP vs Snowflake) explicitly named in the report — never rely on Locust numbers alone
- [ ] **HTML report generated from `templates/benchmark-report.html.template`** — no `{{PLACEHOLDER}}` tokens remain in the output file, and all 11 mandatory sections are present

If any item fails, address it before drawing conclusions from benchmark numbers.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No .sql files found` | Place query files in `benchmark/test/` folder |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Connection errors | Verify connection name in `~/.snowflake/connections.toml` |
| Interactive tables not found | Re-run `snowflake-interactive` skill |
| `BENCHMARK_LOCUST` stuck in PENDING with "Readiness probe failing at /stats/requests" | Legacy `LOCUST_HEADLESS=1` config. Headless locust does not bind port 8089, so the readiness probe fails forever. Remove `LOCUST_HEADLESS` from `config.env` and `specs/locust.yaml`; use the auto-start non-headless path (default). |
| `An interactive table must contain clustering keys` on `CREATE INTERACTIVE TABLE` | The table has no `CLUSTER BY`. All interactive tables need one, including tiny lookup tables. Cluster on the primary key column if nothing else fits (e.g. `CLUSTER BY (N_NATIONKEY)`). |
| Most interactive queries fail with `Statement reached its statement or warehouse timeout of 5 second(s) and was canceled` under load | Interactive warehouse is out of concurrency slots. Queries queue past the 5 s cancel. Fix: set `MAX_CLUSTER_COUNT` per Step 6b (`ceil(users / 15)`) — do NOT upsize the warehouse. |
| Small number of interactive queries fail with the 5 s cancel; the rest are fast | Long-tail outliers hitting the cancel. Fix: set `FALLBACK_WAREHOUSE` per Step 6c. This is the expected steady-state for benchmarks — always configure fallback before load-testing. |
| Curl to Locust `/swarm` endpoint returns an HTML auth page | SPCS public ingress requires Snowflake auth. `externalbrowser` connections cannot curl this from a laptop. Use the auto-start execution model (Step 12) — no `/swarm` call needed. |
| Benchmark run used a different `LOCUST_USERS` value than requested | `config.env` had a stale value. Step 9 checklist requires overwriting `LOCUST_USERS` from Step 1's answer — do not rely on template defaults. |
