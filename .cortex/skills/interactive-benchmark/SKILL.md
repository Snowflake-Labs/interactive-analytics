---
name: interactive-benchmark
description: "Benchmark any SQL query on Snowflake Interactive Warehouses. Chains the snowflake-interactive skill first to create interactive tables and optimize queries, then deploys a benchmark API + Locust load test to Snowpark Container Services (SPCS). Use when: benchmarking queries, testing interactive warehouse performance under load, load testing, deploying benchmark infrastructure. Triggers: benchmark, interactive warehouse benchmark, load test, locust, benchmark my query, performance test."
version: 0.5.0
---

# Interactive Warehouse Benchmark

Benchmarks any user-provided SQL query against a Snowflake Interactive Warehouse under concurrent load, using a FastAPI server deployed to Snowpark Container Services (SPCS) and Locust for load generation. The goal is to determine whether the query can meet a specified latency target (P95) on an interactive warehouse.

**IMPORTANT: This benchmark MUST use the SPCS-deployed API server and Locust load generator. Do NOT create alternative benchmarking approaches (e.g. running queries directly from the client, writing custom scripts, or bypassing Locust). The entire benchmark infrastructure — API server, Locust, compute pools — runs on SPCS.**

## Prerequisites

- `uv` installed (Python package runner)
- A Snowflake connection configured in `~/.snowflake/connections.toml`
- Role with privileges to create databases, warehouses, compute pools, and services
- Ability to use Snowpark Container Services (SPCS)
- Docker installed (for SPCS deployment)

## Paths

`<SKILL_DIR>` refers to the directory containing this SKILL.md file (`.cortex/skills/interactive-benchmark/`). The benchmark source code lives at `<SKILL_DIR>/benchmark/`.

## SPCS Deployment Topology

The benchmark deploys two services to Snowpark Container Services. After deployment (Step 3.6), inform the user exactly what is running:

| Service | Container Instances | Compute Pool Nodes | Instance Family |
|---------|--------------------:|-------------------:|-----------------|
| **Benchmark API** (FastAPI) | 3 (configurable: `API_MIN_INSTANCES` / `API_MAX_INSTANCES`) | 1-4 (configurable: `API_MIN_NODES` / `API_MAX_NODES`) | CPU_X64_M |
| **Locust** (load generator) | 1 (fixed) | 1-2 (configurable: `LOCUST_MIN_NODES` / `LOCUST_MAX_NODES`) | CPU_X64_M |

**Why 3 API instances?** A single FastAPI/Uvicorn process handles requests sequentially per worker. With 3 instances (each running WORKERS uvicorn workers), the API layer can serve high concurrency without becoming the bottleneck. The baseline test (Step 3.8 Phase 1) validates this.

**Why 1 Locust instance?** Locust is the load *generator*, not the system under test. A single instance can simulate hundreds of concurrent users.

All instance and node counts are configurable in `benchmark/spcs/config.env`.

---

## Workflow

The workflow has three distinct phases that MUST be followed in order:

1. **Phase 1 — Gather all inputs** from the user (or extract from their request)
2. **Phase 2 — Validate suitability** — confirm the query is a good fit for interactive warehouses. If not, STOP and explain why.
3. **Phase 3 — Run the benchmark** — deploy, load test, analyze, report. This phase runs autonomously within the user-approved limits.

**IMPORTANT — Progress visibility (DAG):** Immediately after the user confirms Phase 1 inputs — before doing ANY other work — you MUST call `system_todo_write` to create a task list with ALL of the following steps. This is NON-NEGOTIABLE; skipping or deferring it is a bug. The task list MUST contain every step below (one todo item per step):

1. Validate query suitability (snowflake-interactive skill)
2. Verify Docker is running
3. Validate interactive setup
4. Configure concurrency and fallback
5. Save benchmark query
6. Configure environment (config.env)
7. Deploy to SPCS
8. Warm the cache
9. Run baseline test (infrastructure validation)
10. Run load test (Snowflake benchmark)
11. Collect server-side metrics
12. Goal check and escalation (if needed)
13. Generate HTML report
14. Teardown or keep services

The FIRST call after Phase 1 confirmation MUST be `system_todo_write` with all 14 items (first item marked `in_progress`, rest `pending`). Do NOT start any Phase 2/3 work before this call. Update the task list in real-time as you progress — mark each task as `in_progress` when you start it and `completed` when you finish it. Only have ONE task `in_progress` at a time.

---

## Phase 1: Gather All Inputs

Collect ALL of the following from the user before proceeding. If the user's initial request already provides some of these values, acknowledge them and only ask for what is missing. Present the missing items as a single consolidated question — do NOT ask one item at a time.

| # | Input | Description | Default |
|---|-------|-------------|---------|
| 1 | **Database name** | Which database contains the tables used by the query? | (required) |
| 2 | **Schema** | Which schema within that database? | (required) |
| 3 | **Interactive warehouse** | Name of an existing interactive warehouse to benchmark, OR let the skill create one dedicated to this benchmark. | skill creates it |
| 4 | **Standard warehouse** | An existing standard warehouse for the suitability check and fallback, OR let the skill create one dedicated to this benchmark. | skill creates it |
| 5 | **Connection name** | Which Snowflake connection (from `~/.snowflake/connections.toml`) to use? | (required) |
| 6 | **P95 latency goal** | Target P95 latency under concurrent load. Any latency figure is interpreted as P95 unless the user explicitly says otherwise. | P95 <= 1 second |
| 7 | **Concurrent users** | How many simulated concurrent users for the load test? | 50 |
| 8 | **Max warehouse size (scale-up limit)** | Maximum SKU the interactive warehouse can grow to (X-Small, Small, Medium, Large, X-Large, ...). Bounds vertical scaling. | Medium |
| 9 | **Max cluster count (scale-out limit)** | Maximum number of clusters. Bounds horizontal scaling. Rule of thumb: `ceil(concurrent_users / 15)`. | ceil(users/15) + 1 |
| 10 | **Benchmark name** | Short alphanumeric name used as `SOLUTION_NAME` to prefix all created resources. | `IWB_YYYYMMDDHHMM` (e.g. `IWB_202608271430`) |
| 11 | **Max escalation iterations** | Maximum number of scale-up/scale-out iterations before stopping. Bounds the benchmark loop in Step 3.12. | 5 |

**Warehouse creation option:** If the user does not have existing warehouses or prefers dedicated benchmark resources, offer to create both a standard warehouse (e.g. `<SOLUTION_NAME>_BENCH_WH_STD`) and an interactive warehouse (e.g. `<SOLUTION_NAME>_BENCH_WH_INT`) specifically for this benchmark. The standard warehouse size should match a reasonable baseline (e.g. X-Small or Small). These benchmark-dedicated warehouses will be included in the cleanup list at the end (Step 3.14).

**Resource creation transparency:** Whenever the skill creates a warehouse (or any other Snowflake resource), immediately inform the user what was created, including the full name, type, and size. For example: "Created standard warehouse `IWB_202608271430_BENCH_WH_STD` (X-Small) and interactive warehouse `IWB_202608271430_BENCH_WH_INT` (X-Small, multi-cluster)." Never create resources silently.

**Do not proceed past Phase 1 until ALL items are confirmed.** Present the collected values back to the user in a summary table and get a single confirmation before moving on.

**Autonomous execution principle:** Once the user confirms these inputs — especially the latency goal and the scale-out / scale-up limits — the benchmark runs autonomously without further questions. If the P95 goal is not met, the benchmark automatically scales out or up (within the approved limits) and re-runs. No additional user confirmation is needed until either (a) the limits are reached and the goal is still not met, or (b) the benchmark completes successfully.

---

## Phase 2: Validate Query Suitability

**This phase determines whether the query is a good candidate for interactive warehouses. If it is not, STOP HERE — do not proceed to Phase 3.**

### Step 2.1: Invoke `snowflake-interactive` Skill

Invoke the `snowflake-interactive` skill to:
- Analyze the query for interactive warehouse suitability
- Create interactive tables (copies of the source tables with appropriate clustering)
- Create an interactive warehouse attached to those tables
- Optimize the query for interactive warehouse execution

**Do this by calling:**
```
skill(command="snowflake-interactive")
```

Provide the skill with:
- The database and schema from Phase 1
- The query to benchmark
- The standard warehouse name (for sizing reference)

The `snowflake-interactive` skill will:
- Create interactive tables (copies of the source tables optimized for interactive workloads)
- Determine the best size for the interactive warehouse based on the data and workload characteristics
- Create an interactive warehouse with `TARGET_LAG` attached to those tables
- Return the warehouse name and schema name to use

Capture the output:
- `INTERACTIVE_WAREHOUSE` — name of the interactive warehouse created (and its size)
- `INTERACTIVE_SCHEMA` — schema with interactive tables
- `OPTIMIZED_QUERY` — the query rewritten for the interactive schema (if different)

### Step 2.2: Suitability Check

**This is the critical gate. If the query fails this check, STOP and do not proceed to Phase 3.**

Run the query on the standard warehouse first (disable result caching):

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <DATABASE>.<SCHEMA>;
<THE QUERY>;
```

**10-second rule:** If the query exceeds 10 seconds on a standard warehouse despite proper clustering and optimization, it is highly improbable to meet the 5-second interactive execution threshold. **STOP HERE** and inform the user that the query needs further optimization before it can benefit from an interactive warehouse. Use the `snowflake-interactive` skill to provide improvement suggestions (query changes, better clustering, etc.).

If the standard warehouse timing is acceptable (under 10 seconds), run the query on the interactive warehouse:

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <INTERACTIVE_WAREHOUSE>;
USE SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
<THE QUERY>;
```

Compare the two elapsed times. Present the results to the user:

| Warehouse | Elapsed |
|---|---|
| Standard (`<STANDARD_WAREHOUSE>`) | X ms |
| Interactive (`<INTERACTIVE_WAREHOUSE>`) | Y ms |

**Decision gate — STOP or PROCEED:**

- **PROCEED** — Interactive is significantly faster (>=1.5x speedup) and completes in under 5 seconds. Move to Phase 3.
- **STOP — query exceeds 5 seconds on interactive even at rest.** Interactive warehouses cancel SELECT statements after 5 seconds by design. The query is not suitable for interactive execution. Invoke the `snowflake-interactive` skill to analyze why and provide improvement recommendations:
  - Query rewrites (fewer joins, narrower predicates, pre-aggregation)
  - Better clustering keys on the tables
  - Reducing data scanned (partition pruning alignment)
  - Whether a subset of the data would work
- **STOP — performance is similar or standard is faster.** The query is not a good candidate for interactive warehouses. Explain why (full table scan, aggregation pattern doesn't benefit from caching, too complex with many joins/subqueries). Use the `snowflake-interactive` skill to suggest what characteristics would make the query work well: point lookups, selective filters, dashboard-style queries on hot data, parameterized shapes (date ranges, customer IDs). The ideal workload is narrow and selective: few columns, targeted predicates, bounded time windows, small result sets. At least 100GB of data is needed for interactive analytics to be really effective.

**When stopping:** Provide the user with a clear summary including:
1. Why the query is not suitable (specific reason)
2. What the `snowflake-interactive` skill recommends to improve it
3. Whether a modified version of the query could work

---

## Phase 3: Run the Benchmark

**Only enter this phase after Phase 2 confirms the query is suitable for interactive.**

From this point, everything runs autonomously within the user-approved limits from Phase 1. No further questions are asked unless the limits are exhausted.

### Step 3.1: Verify Docker is Running

```bash
docker info > /dev/null 2>&1
```

If Docker is not running, warn the user: **"Docker is required to build and push container images for the SPCS benchmark deployment. Please start Docker Desktop (or the Docker daemon) and try again."**

---

### Step 3.2: Validate Interactive Setup

Verify the interactive setup is correct before deploying.

**1. Verify interactive tables are attached to the interactive warehouse:**

```sql
SHOW INTERACTIVE TABLES IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Confirm that each table referenced by the query appears in the output and that the `warehouse_name` column shows the `INTERACTIVE_WAREHOUSE`.

**2. Verify predicates align with clustering keys:**

For each interactive table, check its clustering key:

```sql
SHOW TABLES LIKE '<TABLE_NAME>' IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Compare the `cluster_by` column against the columns used in the query's WHERE/JOIN predicates.

**Every interactive table MUST have a `CLUSTER BY`, including tiny dimension/lookup tables.** `CREATE INTERACTIVE TABLE` fails with `An interactive table must contain clustering keys` if omitted. For lookup tables with no natural filter column (e.g. `NATION` with 25 rows, `REGION` with 5 rows), cluster on the primary key column:

```sql
CREATE INTERACTIVE TABLE <SCHEMA>.NATION CLUSTER BY (N_NATIONKEY) AS SELECT * FROM <SRC>.NATION;
CREATE INTERACTIVE TABLE <SCHEMA>.REGION CLUSTER BY (R_REGIONKEY) AS SELECT * FROM <SRC>.REGION;
```

**3. Validate working set sizing:**

```sql
SELECT TABLE_NAME, BYTES / (1024*1024*1024) AS SIZE_GB
FROM <DATABASE>.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '<INTERACTIVE_SCHEMA>';
```

Compare total working set size against the interactive warehouse size:
- XS: up to ~350 GB working set
- S: up to ~600 GB
- M: up to ~1200 GB
- L: up to ~2500 GB
- XL+: larger working sets

---

### Step 3.3: Configure Concurrency and Fallback

**CRITICAL: Interactive warehouses scale concurrency *horizontally* (multi-cluster), not vertically. Configure `MAX_CLUSTER_COUNT` and a fallback warehouse BEFORE the load test.**

**MANDATORY — Warm-up after any warehouse change:** Every time a warehouse is created, resized, resumed from suspension, or has its cluster count changed (including this initial configuration and every escalation in Step 3.12), you MUST run the cache warm-up procedure (Step 3.7) before measuring performance. Never run a load test against a cold or freshly-reconfigured warehouse.

Compute the required cluster count:

```
RECOMMENDED_MAX_CLUSTER_COUNT = ceil(<CONCURRENT_USERS> / 15)
```

Use the user's scale-out limit from Phase 1 as the ceiling. If the recommended value exceeds the user's limit, use the user's limit — the autonomous execution principle means we proceed with what was approved, and Step 3.12 will detect if queueing causes P95 misses and propose escalation at that point. Apply:

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE> SET
  MIN_CLUSTER_COUNT = 1,
  MAX_CLUSTER_COUNT = <computed_value>,
  SCALING_POLICY = 'STANDARD';
```

Configure the fallback warehouse (uses the standard warehouse from Phase 1):

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE>
  SET FALLBACK_WAREHOUSE = <STANDARD_WAREHOUSE>;
```

Verify:

```sql
SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE <INTERACTIVE_WAREHOUSE>;
```

---

### Step 3.4: Save the Benchmark Query

The user provides the query to benchmark as part of their request to CoCo. Create `benchmark/test/benchmark-query.sql` from the template file `benchmark/test/benchmark-query.sql.template` by replacing the placeholder content with the actual query:

1. Read `<SKILL_DIR>/benchmark/test/benchmark-query.sql.template`
2. Replace the placeholder text with the user's query (or the optimized version if the `snowflake-interactive` skill produced one)
3. Write the result to `<SKILL_DIR>/benchmark/test/benchmark-query.sql`

This file is the single query executed against the interactive warehouse during the load test.

---

### Step 3.5: Configure Environment

Both config files MUST be created from their templates — never edit the templates directly.

1. **Create `benchmark/.env`** from `benchmark/.env.template`:
   ```bash
   cp <SKILL_DIR>/benchmark/.env.template <SKILL_DIR>/benchmark/.env
   ```
   Write these exact values:
   ```
   CONNECTION_NAME=<connection from Phase 1>
   SOLUTION_NAME=<benchmark name from Phase 1>
   ```

2. **Create `benchmark/spcs/config.env`** from `benchmark/spcs/config.env.template`:
   ```bash
   cp <SKILL_DIR>/benchmark/spcs/config.env.template <SKILL_DIR>/benchmark/spcs/config.env
   ```

   Then **explicitly overwrite** these values in `config.env` from the answers gathered in Phase 1 and the outputs captured in Step 2.1. Do NOT rely on template defaults — the whole run is wrong if any of these drift:

   | Variable | Source | Example |
   |---|---|---|
   | `CONNECTION` | Phase 1 answer | `PM` |
   | `ROLE` | Phase 1 or `ACCOUNTADMIN` | `ACCOUNTADMIN` |
   | `INTERACTIVE_WAREHOUSE` | **Step 2.1 output** — the exact name `snowflake-interactive` created | `DM_TESTTPCH_BENCH_WH_INT` |
   | `INTERACTIVE_SCHEMA` | **Step 2.1 output** | `TPCH_SF100_INT` |
   | `API_DATABASE` | **Phase 1 answer** | `DM_TESTTPCH_BENCH_DB` |
   | `LOCUST_USERS` | **Phase 1 answer** — the concurrent-users number | `50` |
   | `LOCUST_RUN_TIME` | Default `3m`, or user-supplied | `3m` |

   After writing, `grep` the file to sanity-check that no template placeholder or stale value remains. The `INTERACTIVE_WAREHOUSE` and `LOCUST_USERS` values are the two most common sources of "the benchmark ran with the wrong settings" bugs.

3. If `benchmark/.env` or `benchmark/spcs/config.env` already exist from a previous run, do NOT reuse them blindly. Diff each value in the table above against the current Phase 1/Step 2.1 answers and overwrite anything that changed.

**Note on Locust execution model:** As of this skill version, Locust runs in **non-headless mode with `--autostart` inside the container** — no external HTTP calls are needed to trigger the run. There is no `LOCUST_HEADLESS` toggle. See Step 3.8 and Step 3.9 for the execution flow.

---

### Step 3.6: Deploy to SPCS

```bash
cd <SKILL_DIR>/benchmark/spcs && ./deploy.sh
```

This deploys:
- **Benchmark API** — FastAPI server that executes queries against the interactive warehouse
- **Locust** — Load generator that POSTs queries to the API

**IMPORTANT — Deployment monitoring:** SPCS deployments can take 3–10 minutes (compute pool provisioning + image pull + container start). To avoid appearing stuck:

1. Run `deploy.sh` in the background.
2. Every 30 seconds, poll service status and report to the user:
   ```bash
   cd <SKILL_DIR>/benchmark/spcs && ./status.sh
   ```
   This shows the current state of each service (PENDING, READY, FAILED) along with a status message (e.g. "Pending scheduling", "Pulling image").
3. If a service stays in PENDING for more than 5 minutes, run `./logs.sh` and report any errors to the user. Common causes:
   - Compute pool still provisioning (normal — wait)
   - Image pull in progress (normal — wait)
   - Image not found (check `build-and-push.sh` succeeded)
   - Insufficient privileges (check ROLE)
4. If a service enters FAILED state, immediately show the user the output of `./logs.sh` and stop.
5. Only proceed to the next step once both services report READY.
6. **Display the SPCS topology to the user** (see "SPCS Deployment Topology" section above). This makes it clear how many containers are running and how compute is distributed, so the user can judge whether the infrastructure is appropriately sized for their concurrency target.

---

### Step 3.7: Warm the Cache

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
```

Also warm each *variant* query shape (`benchmark-query-q1.sql`, `benchmark-query-nation.sql`, etc.) at least once so the tail of the load test doesn't include cold-cache measurements.

Check that the last warm-up iteration shows latency close to expected steady-state (e.g. sub-second for a well-fitted workload). If latency is still high on the final iteration, run more iterations or wait for background cache population to complete.

Discard the results from these warm-up calls — they are not part of the benchmark.

---

### Step 3.8: Run Baseline Test (Infrastructure Validation)

The Locust container now runs a **two-phase execution model**. When the container starts, it automatically executes both phases in sequence:

**Phase 1 — Baseline:** Locust runs `BaselineUser` against the no-op `POST /api/run/baseline` endpoint for `BASELINE_RUN_TIME` (default 1 minute) with the same user count and spawn rate as the real benchmark. This measures pure API/SPCS infrastructure throughput without touching Snowflake.

After Phase 1 completes, the entrypoint parses the baseline CSV and checks:
- **Failure rate** must be <= `BASELINE_MAX_FAILURE_PCT` (default 1%)
- **p99 latency** must be <= `BASELINE_MAX_P99_MS` (default 500ms)

If either threshold is exceeded, the container logs an error with remediation suggestions (increase API instances, increase compute pool nodes, or reduce user count) and **does NOT proceed to Phase 2**. The container stays alive for log retrieval.

**Phase 2 — Snowflake Benchmark:** Only runs if Phase 1 passes. This is the real load test against `POST /api/run/interactive`.

Baseline env vars (all have sensible defaults — no SPCS spec changes required):

| Variable | Default | Description |
|---|---|---|
| `BASELINE_RUN_TIME` | `1m` | Duration of the baseline test |
| `BASELINE_MAX_FAILURE_PCT` | `1` | Max acceptable failure % |
| `BASELINE_MAX_P99_MS` | `500` | Max acceptable p99 in milliseconds |

**There is no external HTTP call needed to trigger either phase.** Starting the container starts the baseline, and a passing baseline automatically starts the benchmark. SPCS public ingress requires Snowflake auth, so the auto-start design sidesteps this entirely.

Monitor baseline progress in the logs:
```bash
cd <SKILL_DIR>/benchmark/spcs && ./logs.sh locust
```

Look for `[baseline] VERDICT: PASS` to confirm the infrastructure is healthy before the benchmark begins.

---

### Step 3.9: Run Load Test (Snowflake Benchmark)

**This step runs automatically after the baseline passes (Step 3.8).** No manual trigger is needed on the first run.

#### 9a. Trigger the run

Depending on state:
- **First run after `./deploy.sh`** — both phases run automatically when the container starts. No action needed. Proceed to 9b.
- **Subsequent runs after changing config or warehouse settings** — force a container restart by re-applying the spec:
  ```bash
  cd <SKILL_DIR>/benchmark/spcs && ./update.sh
  ```
  Or suspend+resume directly via SQL:
  ```sql
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST SUSPEND;
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST RESUME;
  ```
  Then wait for locust to report READY:
  ```bash
  cd <SKILL_DIR>/benchmark/spcs && ./status.sh --wait
  ```
  Note: the baseline will re-run on every restart. This is intentional — it re-validates the infrastructure after any configuration change.

#### 9b. Monitor the run

The benchmark phase runs for `LOCUST_RUN_TIME` (default 3 minutes). While it runs:

- **Watch cluster scaling** on the interactive warehouse:
  ```sql
  SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
  ```
  Look at `started_clusters` and `running`. If `queued > 0`, `MAX_CLUSTER_COUNT` from Step 3.3 is too low — abort and increase it.

- **Follow locust logs** for progress:
  ```bash
  cd <SKILL_DIR>/benchmark/spcs && ./logs.sh locust
  ```
  You'll see lines like `Ramping to 50 users at a rate of 5.00 per second` and `All users spawned`.

#### 9c. Retrieve the results

After `LOCUST_RUN_TIME + ~10 s` (for `--autoquit` to fire), locust exits and the entrypoint prints a `======================== BENCHMARK RESULTS ========================` banner followed by the stats CSV:

```bash
cd <SKILL_DIR>/benchmark/spcs && ./logs.sh locust | tail -80
```

The `locust_stats_stats.csv` block contains a row for `/api/run/interactive` (plus Aggregated) with columns:

```
Type, Name, Request Count, Failure Count, Median Response Time, Average Response Time,
Min, Max, Avg Content Size, Requests/s, Failures/s, 50%, 66%, 75%, 80%, 90%, 95%, 98%, 99%, 99.9%, 99.99%, 100%
```

Parse the `/api/run/interactive` row for P50, P95, P99 and failure counts.

The baseline results are also available in the logs under the `======================== BASELINE RESULTS ========================` banner. The baseline p99 establishes the infrastructure overhead floor.

If you need results before the test finishes, the container also emits a HEARTBEAT block every 2 minutes with both baseline and benchmark CSVs — grep for `HEARTBEAT` in the logs.

---

### Step 3.10: Analyze Results and Generate Recommendations

After the load test completes, collect **three sets of measurements**:

1. **Baseline (Locust HTTP)** — p99 from the baseline CSV for `/api/run/baseline`. This is the infrastructure overhead floor — the minimum latency added by the API/network layer.
2. **Client-side (Locust HTTP)** — P50, P95, P99 from the Locust CSV for the `/api/run/interactive` endpoint. This is what the end user experiences (HTTP round-trip + API pool + Snowflake).
3. **Server-side (Snowflake)** — P50, P95, P99 computed from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` for the interactive warehouse. This is what Snowflake alone spent (compile + queue + execute).

All three sets of numbers are **mandatory**. The server-side numbers are what proves Snowflake performance; the client-side numbers are what the user's dashboard sees; the baseline numbers establish the infrastructure overhead floor. The **delta between client-side and server-side isolates the API/HTTP overhead from Snowflake's real cost**. If that delta is significantly higher than the baseline p99, there may be connection pool contention or other API-layer issues beyond simple HTTP overhead.

Also collect:
- Throughput (requests/sec) from Locust
- Error rates (Locust) and count of fallback-served queries (server-side query count on the fallback WH)

**Latency goal convention:** When the user specifies a latency target (e.g. "queries must complete within 2 seconds"), interpret that as a **P95 target** unless they explicitly state otherwise. Evaluate the goal against **both** client-side and server-side P95 — if server-side meets the goal but client-side does not, the API is the bottleneck; if both fail, the warehouse configuration needs work.

Then invoke the `snowflake-interactive` skill again to analyze the benchmark results and produce optimization recommendations:
- Does the query need rewrites or tweaks for better interactive performance?
- Would clustering keys on the interactive tables improve results?
- Are there join or filter patterns that could benefit from search optimization?

Capture these recommendations for the report.

---

### Step 3.11: Post-Benchmark Server-Side Validation

After collecting the Locust CSV, **you MUST run server-side aggregation queries against Snowflake for the interactive warehouse**. This is not optional — the Locust numbers alone cannot distinguish API/HTTP overhead from Snowflake time.

**Important — use `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE`, not `ACCOUNT_USAGE.QUERY_HISTORY`.** The `ACCOUNT_USAGE` view has a 45-minute to 3-hour latency and will return zero rows immediately after the benchmark. `INFORMATION_SCHEMA` is fresh within seconds. Run these diagnostic queries from a **non-interactive** warehouse (e.g. `USE WAREHOUSE COMPUTE_WH`) — running them on the interactive WH will hit the 5-second cancel.

The API sets `QUERY_TAG` to the `SOLUTION_NAME` (benchmark name) on every request. This allows isolating benchmark traffic in `QUERY_HISTORY` queries. Because the default benchmark name includes a `YYYYMMDDHHMM` timestamp, each benchmark run produces a unique tag. If the user provides a custom name without a timestamp pattern, append `_YYYYMMDDHHMM` to the tag value so that queries from different runs of the same benchmark can be distinguished.

**Load** `references/server-side-validation.md` for the exact SQL queries, delta interpretation rules, and query profile health metrics.

---

### Step 3.12: Goal Check and Iterative Escalation

After collecting the server-side percentiles from Step 3.11, evaluate them against the P95 latency goal captured in Phase 1.

**Case 1 — Goal met on both client and server.** Report success. Proceed to Step 3.13.

**Case 2 — Server-side P95 meets the goal but client-side does not.** Snowflake is doing its job; the tail comes from API/HTTP overhead. Do NOT propose warehouse scale-up — it will not help. Diagnose and document, then proceed to Step 3.13.

**Case 3 — Server-side P95 does NOT meet the goal.** The warehouse itself is not delivering the target latency. Automatically escalate within the user's pre-approved limits. Pick the right lever based on the profile from Step 3.11:

1. **Scale out (increase MAX_CLUSTER_COUNT)** — only if `AVG_QUEUE_MS > 0` on the interactive warehouse. Queueing is the signal that horizontal scaling will help. Bounded by the user's scale-out limit (Phase 1).
2. **Scale up (bump the warehouse SKU)** — if `AVG_QUEUE_MS == 0` (no queueing — the bottleneck is per-query execution, not concurrency). Move to the next SKU (X-Small -> Small -> Medium -> Large -> ...). Each step roughly doubles cache and cores and typically halves per-query execute time. Bounded by the user's scale-up limit (Phase 1).
3. **Both** — if there is queueing AND per-query execute time is already high, do the scale-out first, then re-measure before considering scale-up.

**Do NOT ask for permission to scale within the defined limits.** The user already approved the scale-out limit (MAX_CLUSTER_COUNT) and scale-up limit (warehouse size) in Step 1. As long as the proposed change stays within those boundaries, proceed automatically — inform the user what you are doing (e.g. "P95 goal not met. Scaling warehouse from X-Small to Small — within your approved ceiling of Medium. Re-running benchmark.") but do NOT wait for confirmation. This keeps the benchmark moving without unnecessary interruptions.

**After each escalation:** re-configure the warehouse via SQL (`ALTER WAREHOUSE ... SET WAREHOUSE_SIZE=... / MAX_CLUSTER_COUNT=...`), re-warm the cache (Step 3.7), then re-run the load test (Step 3.9) and re-collect the server-side numbers (Step 3.11). **Do NOT re-deploy SPCS** — the API and Locust services are already running; only the warehouse configuration changes. To re-trigger the load test, suspend/resume the Locust service as described in Step 3.9 ("Subsequent runs"). Re-evaluate this step after each iteration. **Cap the iteration count at the user's "Max escalation iterations" value from Phase 1 (default: 6)** to avoid runaway loops.

**Limits already reached — the goal is not achievable within the user's ceilings.** If both `MAX_CLUSTER_COUNT` and warehouse size are already at the user-supplied ceilings and the goal is still missed, do NOT propose further scaling. **Only at this point should you stop and ask the user.** Tell them clearly, for example:

> "The target of **P95 <= 1000 ms** is not achievable within your scale-out limit of **5 clusters** and scale-up limit of **Medium**. Best result reached: server-side P95 = **1800 ms** (Medium x 5 clusters). Options: (a) relax one of the ceilings and re-run, (b) redesign the query (fewer joins, pre-aggregated table, narrower predicates), (c) reduce data scanned (better clustering, search optimization), (d) accept the current performance. How would you like to proceed?"

Then produce the Step 3.13 report with the ceiling-limited numbers and mark the P95 goal as **not met — limit-bound** in the executive summary tile.

**Recording the iteration history.** For the report, keep a short log of each iteration (starting size / MCW, resulting server-side P95, decision) so the reader can see the escalation path. This log populates the `{{ITERATION_HISTORY}}` placeholder in the template.

---

### Step 3.13: Generate HTML Report

**MANDATORY: use the bundled template.** The report MUST be produced by starting from the canonical HTML template shipped with this skill and filling in its `{{PLACEHOLDER}}` tokens. Do NOT hand-author the report from scratch, do NOT change the section order, and do NOT modify the CSS or structure.

**Template path:** `templates/benchmark-report.html.template`

**Output directory:** `<SKILL_DIR>/benchmark/reports/<SOLUTION_NAME>/`

Create a subfolder named after the benchmark (e.g. `reports/IWB_202608271430/`). Save the following files in it:
- `benchmark-report.html` — the filled-in HTML report (generated once at the end, after all iterations)
- `locust-run-1.txt` — Locust log from the first load test iteration
- `locust-run-2.txt` — Locust log from the second iteration (if escalation triggered a re-run)
- `locust-run-3.txt` — Locust log from the third iteration (if needed)

Each time the load test runs (Step 3.9), save the full Locust output (`./logs.sh locust`) to the next numbered file. This ensures every iteration's results are preserved — even runs that did not meet the goal. The final HTML report references the last successful run's data, but earlier runs provide the escalation history.

**Load** `references/report-generation.md` for the full procedure, coverage requirements, and verification steps.

Open the report in the browser for the user when done.

---

### Step 3.14: Resource Summary and Cleanup

After the report is generated, present the user with a **complete list of all Snowflake resources created during this benchmark session**. Format it as a clear table:

| Resource Type | Name | Location |
|---|---|---|
| Interactive warehouse | `<INTERACTIVE_WAREHOUSE>` | Account-level |
| Interactive schema | `<DATABASE>.<INTERACTIVE_SCHEMA>` | Contains interactive tables |
| Interactive tables | `<TABLE_1>`, `<TABLE_2>`, ... | In `<INTERACTIVE_SCHEMA>` |
| SPCS database | `<SOLUTION_NAME>_BENCH_DB` | Account-level |
| SPCS schema | `<SOLUTION_NAME>_BENCH_DB.SPCS` | Contains services + image repo |
| Compute pool (API) | `<SOLUTION_NAME>_BENCH_API_POOL` | Account-level |
| Compute pool (Locust) | `<SOLUTION_NAME>_BENCH_LOCUST_POOL` | Account-level |
| Image repository | `<SOLUTION_NAME>_BENCH_IMAGES` | In SPCS schema |
| Service (API) | `BENCHMARK_API` | In SPCS schema |
| Service (Locust) | `BENCHMARK_LOCUST` | In SPCS schema |

Then ask the user: **"Would you like me to clean up these resources, or keep them for further benchmarking?"**

Options:
1. **Full cleanup** — tear down everything (SPCS services, compute pools, interactive tables, warehouse, schemas)
2. **Tear down SPCS only** — remove services and compute pools but keep the interactive warehouse and tables
3. **Keep everything** — leave all resources running for re-runs

If the user chooses **full cleanup**:
```bash
cd <SKILL_DIR>/benchmark/spcs && ./teardown.sh
```

Then drop the schemas and warehouse:

```sql
USE ROLE <ROLE>;
DROP SCHEMA IF EXISTS <DATABASE>.<INTERACTIVE_SCHEMA>;
DROP SCHEMA IF EXISTS <SOLUTION_NAME>_BENCH_DB.SPCS;
DROP WAREHOUSE IF EXISTS <INTERACTIVE_WAREHOUSE>;
```

If the SPCS database was created entirely by this benchmark and is now empty, also drop it:

```sql
DROP DATABASE IF EXISTS <SOLUTION_NAME>_BENCH_DB;
```

If the user chooses **SPCS only**:
```bash
cd <SKILL_DIR>/benchmark/spcs && ./teardown.sh
```

If the user chooses to **keep everything**, save the deployment state in `benchmark/.env` so future runs reuse the existing services instead of redeploying:

```
# Existing entries
CONNECTION_NAME=<connection>
SOLUTION_NAME=<name>

# SPCS deployment state (added when services are kept)
SPCS_DEPLOYED=true
SPCS_API_INGRESS_URL=<the ingress URL>
SPCS_LOCUST_INGRESS_URL=<the locust ingress URL>
```

On future invocations of this skill, check `benchmark/.env` for `SPCS_DEPLOYED=true`. If set, skip Step 3.6 (Deploy to SPCS) and reuse the saved ingress URLs for cache warming and load testing. If the user later wants to tear down, run `./teardown.sh` and remove the `SPCS_*` lines from `.env`.

```bash
cd <SKILL_DIR>/benchmark/spcs && ./status.sh
```

Options:
- `./status.sh --wait` — poll until all services are READY
- `./status.sh --urls-only` — print only ingress URLs

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/run/interactive` | Execute query on interactive warehouse |
| POST | `/api/run` | Alias for `/api/run/interactive` |
| POST | `/api/run/baseline` | No-op endpoint for infrastructure baseline testing |

Request body: `{"query_id": "<id>"}`. Response includes `elapsed_ms`, `row_count`, `warehouse`, `query_id`. The baseline endpoint returns `elapsed_ms: 0` and `null` for warehouse/query_id.

---

## Stopping Points

- After detecting intent — confirm action before proceeding
- After `snowflake-interactive` completes — confirm tables/warehouses were created
- After suitability check — stop if query shows no interactive benefit
- Before `deploy.sh services` — warn about compute pool cost implications
- Before teardown — confirm which resources to drop

## Checklist and Troubleshooting

**Load** `references/checklist-and-troubleshooting.md` for the full "Good Setup" checklist and troubleshooting table. Verify all checklist items pass before considering the benchmark complete.
