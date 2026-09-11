---
name: interactive-benchmark
version: 0.6.1
description: "Benchmark any SQL query on Snowflake Interactive Warehouses. Chains the snowflake-interactive skill first to create interactive tables and optimize queries, then deploys a benchmark API + Locust load test to Snowpark Container Services (SPCS). Use when: benchmarking queries, testing interactive warehouse performance under load, load testing, deploying benchmark infrastructure. Triggers: benchmark, interactive warehouse benchmark, load test, locust, benchmark my query, performance test, stress test, how fast under load, concurrent query performance, can my query handle N users, latency under concurrency, query throughput test."
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

## Tool Usage

Every step in this skill MUST use the specific tool listed below. Do NOT substitute alternative approaches (e.g. do not use `bash` + `snow sql` instead of `snowflake_sql_execute`).

| Action | Tool | Notes |
|--------|------|-------|
| Run shell commands | `bash` | For `docker info`, `deploy.sh`, `status.sh`, `logs.sh`, `teardown.sh`, `resize-wh.sh`, `update-progress.sh`, `cp`, `update.sh`, `upload-queries.sh`. Scripts live in `benchmark/scripts/`. Use `run_in_background=true` for `deploy.sh`. |
| Monitor background shell | `bash_output` | To check output of background `deploy.sh` (Step 3.7). |
| Read files | `read` | For templates, configs, reference docs, logs. |
| Write / create files | `write` | For `config.env`, `.env`, `benchmark-query.sql`, report HTML, log captures, and initial `progress.json`. |
| Edit existing files | `edit` | For updating specific values in an existing config file without rewriting the whole file. |
| Search file contents | `grep` | For placeholder verification (`{{`) and config sanity checks. |
| Ask user questions | `ask_user_question` | For Phase 1 inputs, Phase 1 confirmation, and cleanup choice (Step 3.14). |
| Open report in browser | `open_browser` | For the final HTML report (Step 3.13). |
| Load sub-skills | `skill` | `snowflake-interactive` (Step 2.1, 3.10), `html-authoring` (Step 3.13). |
| Track progress | `system_todo_write` | **Primary** progress display — drives the CLI/IDE step counter. MUST be called at every step boundary BEFORE `update-progress.sh`. See Progress Tracking section. |

## Paths

`<SKILL_DIR>` refers to the directory containing this SKILL.md file (`.cortex/skills/interactive-benchmark/`). The benchmark source code lives at `<SKILL_DIR>/benchmark/`. Shell scripts (deploy, teardown, status, logs, resize, etc.) live in `<SKILL_DIR>/benchmark/scripts/`. SPCS artifacts (config, specs, Dockerfiles) live in `<SKILL_DIR>/benchmark/spcs/`.

## SPCS Deployment Topology

The benchmark deploys two services to Snowpark Container Services. After deployment (Step 3.7), inform the user exactly what is running:

| Service | Container Instances | Compute Pool Nodes | Instance Family |
|---------|--------------------:|-------------------:|-----------------|
| **Benchmark API** (FastAPI) | 3 (configurable: `API_MIN_INSTANCES` / `API_MAX_INSTANCES`) | 1-4 (configurable: `API_MIN_NODES` / `API_MAX_NODES`) | CPU_X64_M |
| **Locust** (load generator) | 1 (fixed) | 1-2 (configurable: `LOCUST_MIN_NODES` / `LOCUST_MAX_NODES`) | CPU_X64_M |

**Why 3 API instances?** A single FastAPI/Uvicorn process handles requests sequentially per worker. With 3 instances (each running WORKERS uvicorn workers), the API layer can serve high concurrency without becoming the bottleneck. The baseline test (Step 3.8 Phase 1) validates this.

**Why 1 Locust instance?** Locust is the load *generator*, not the system under test. A single instance can simulate hundreds of concurrent users.

All instance and node counts are configurable in `benchmark/spcs/config.env`.

---

## Workflow

**⚠️ CRITICAL — MANDATORY STEP TRANSITION PROTOCOL ⚠️**
**Every step in this skill begins with a PROGRESS UPDATE action. This is NOT optional metadata — it is the first action you execute. The pattern is: (1) call `system_todo_write` to update the IDE task DAG, then (2) run `update-progress.sh` to update `progress.json`. If you skip `system_todo_write`, the user sees a frozen progress tracker for the entire run. Treat every "1. PROGRESS UPDATE" item below exactly like you treat "run this SQL" or "call this tool" — it is a concrete action, not a reminder.**

The workflow has three distinct phases that MUST be followed in order:

1. **Phase 1 — Gather all inputs** from the user (or extract from their request)
2. **Phase 2 — Validate suitability** — confirm the query is a good fit for interactive warehouses. If not, STOP and explain why.
3. **Phase 3 — Run the benchmark** — deploy, load test, analyze, report. This phase runs autonomously within the user-approved limits.

**IMPORTANT — Progress Tracking:** Immediately after the user confirms Phase 1 inputs — before doing ANY Phase 2/3 work — you MUST do ALL of the following: (a) call `system_todo_write` with all 14 steps, (b) create the reports folder, and (c) write an initial `progress.json` file. ALL THREE are NON-NEGOTIABLE; skipping or deferring any of them is a bug. The `progress.json` file is consumed by `update-progress.sh` at every step boundary and by the final HTML report — without it the entire progress pipeline is broken.

**IMPORTANT — Per-Step Updates:** Every step section below starts with a numbered item "1. **PROGRESS UPDATE (mandatory)**". This is the literal first thing you do when entering that step — call `system_todo_write`, then run `update-progress.sh`. Do not skip it. Do not defer it. Do not treat it as a note. Execute it as an action before any other work in that step.

**Initialization (right after Phase 1 confirmation — do this BEFORE anything else):**

1. **FIRST AND MOST IMPORTANT — call `system_todo_write` NOW.** This creates the visible task DAG in the IDE. Without it, the user sees no progress tracker for the entire run. Call it with this exact payload:

```json
[
  {"content": "Step 1: Validate query suitability", "status": "in_progress"},
  {"content": "Step 2: Verify Docker running", "status": "pending"},
  {"content": "Step 3: Validate interactive setup", "status": "pending"},
  {"content": "Step 4: Configure concurrency and fallback", "status": "pending"},
  {"content": "Step 5: Save benchmark query", "status": "pending"},
  {"content": "Step 6: Configure environment", "status": "pending"},
  {"content": "Step 7: Warm the cache", "status": "pending"},
  {"content": "Step 8: Deploy to SPCS", "status": "pending"},
  {"content": "Step 9: Run baseline test", "status": "pending"},
  {"content": "Step 10: Run load test", "status": "pending"},
  {"content": "Step 11: Collect server-side metrics", "status": "pending"},
  {"content": "Step 12: Goal check and escalation", "status": "pending"},
  {"content": "Step 13: Generate HTML report", "status": "pending"},
  {"content": "Step 14: Teardown or keep services", "status": "pending"}
]
```

2. Create the reports directory via `bash`: `mkdir -p <SKILL_DIR>/benchmark/reports/<SOLUTION_NAME>/`
3. Use `write` to create `<SKILL_DIR>/benchmark/reports/<SOLUTION_NAME>/progress.json` with ALL 14 steps set to `"pending"`:

```json
{
  "benchmark_name": "<SOLUTION_NAME>",
  "total_steps": 14,
  "current_step": 0,
  "started_at": "<ISO 8601 now>",
  "updated_at": "<ISO 8601 now>",
  "status": "running",
  "steps": [
    { "id": 1,  "name": "Validate query suitability", "status": "pending" },
    { "id": 2,  "name": "Verify Docker running", "status": "pending" },
    { "id": 3,  "name": "Validate interactive setup", "status": "pending" },
    { "id": 4,  "name": "Configure concurrency and fallback", "status": "pending" },
    { "id": 5,  "name": "Save benchmark query", "status": "pending" },
    { "id": 6,  "name": "Configure environment", "status": "pending" },
    { "id": 7,  "name": "Warm the cache", "status": "pending" },
    { "id": 8,  "name": "Deploy to SPCS", "status": "pending" },
    { "id": 9,  "name": "Run baseline test", "status": "pending" },
    { "id": 10, "name": "Run load test", "status": "pending" },
    { "id": 11, "name": "Collect server-side metrics", "status": "pending" },
    { "id": 12, "name": "Goal check and escalation", "status": "pending" },
    { "id": 13, "name": "Generate HTML report", "status": "pending" },
    { "id": 14, "name": "Teardown or keep services", "status": "pending" }
  ]
}
```

4. Verify the `system_todo_write` call from step 1 succeeded (the task DAG should be visible in the IDE). Then proceed to Phase 2.

**Update protocol — at EVERY step boundary, two calls in this order:**

The script `<SKILL_DIR>/benchmark/scripts/update-progress.sh` updates `progress.json` atomically. Usage:

```bash
<SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> <step_id> <action>
```

where `<action>` is one of: `start`, `complete`, `fail`, `skip`.

- **Before starting a step:** First call `system_todo_write` — set the new step to `in_progress`, all completed steps to `completed`, rest `pending`. Then run `update-progress.sh <REPORT_DIR> <step_id> start` via `bash`.
- **After completing a step:** First call `system_todo_write` — set the step to `completed`. Then run `update-progress.sh <REPORT_DIR> <step_id> complete` via `bash`.
- **On failure:** Run `update-progress.sh <REPORT_DIR> <step_id> fail`.
- **On completion:** The script auto-sets top-level status to `"completed"` when step 14 is completed.

Only ONE step should be `"in_progress"` at a time. Each step section below begins with a numbered item **"1. PROGRESS UPDATE (mandatory)"** — this is the first action you execute when entering that step, not a reminder or a note.

---

## Phase 1: Gather All Inputs

Collect ALL of the following from the user before proceeding. If the user's initial request already provides some of these values, acknowledge them and only ask for what is missing. Use `ask_user_question` to present all missing items as a single consolidated question — do NOT ask one item at a time. Use `type: "text"` fields with sensible `defaultValue` for each input, so the user only edits what differs from the defaults.

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
| 9 | **Max cluster count (scale-out limit)** | Maximum number of clusters. Bounds horizontal scaling. Rule of thumb: `MIN = ceil(concurrent_users / MAX_CONCURRENCY_LEVEL)`, `MAX = MIN * 2` where MCL defaults to 8. See `references/mcw-sizing.md` for details. | ceil(users/8) * 2 |
| 10 | **Benchmark name** | Short alphanumeric name used as `SOLUTION_NAME` to prefix all created resources. | `IWB_YYYYMMDDHHMM` (e.g. `IWB_202608271430`) |
| 11 | **Max escalation iterations** | Maximum number of scale-up/scale-out iterations before stopping. Bounds the benchmark loop in Step 3.12. | 5 |

**Load** `references/phase1-inputs.md` (via the `read` tool) for warehouse creation options, AUTO_SUSPEND requirements, DDL restrictions, resource transparency rules, and the autonomous execution principle.

**Do not proceed past Phase 1 until ALL items are confirmed.** Present the collected values back to the user in a summary table and use `ask_user_question` with a single confirmation option (e.g. "Confirmed — proceed") to get approval before moving on. The summary table MUST include all 11 inputs plus the queries stage. Example:

| Input                                 | Value                                        |
|---------------------------------------|----------------------------------------------|
| Database                              | DM_TESTTPCH_BENCH_DB                         |
| Schema                                | TPCH_SF100                                   |
| Interactive warehouse                 | to be created: IWB_202609101430_BENCH_WH_INT |
| Standard warehouse                    | to be created: IWB_202609101430_BENCH_WH_STD |
| Connection                            | PM                                           |
| P95 latency goal                      | ≤ 1 second                                   |
| Concurrent users                      | 50                                           |
| Max warehouse size (scale-up ceiling) | Large                                        |
| Max cluster count (scale-out ceiling) | 14                                           |
| Benchmark name                        | IWB_202609101430                             |
| Max escalation iterations             | 5                                            |
| Queries stage                         | @IWB_202609101430_SPCS_DB.SPCS.BENCHMARK_QUERIES |

The queries stage path is always `@<SOLUTION_NAME>_SPCS_DB.SPCS.BENCHMARK_QUERIES` — it is derived, not user-supplied.

**Load** `references/phase1-inputs.md` for the autonomous execution principle that governs Phase 2 and Phase 3.

---

## Phase 2: Validate Query Suitability

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 1 to `in_progress` (rest stay `pending`). Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 1 start`. Do not proceed until both calls complete.

**This phase determines whether the query is a good candidate for interactive warehouses. If it is not, STOP HERE — do not proceed to Phase 3.**

**Load** `references/suitability-check.md` (via the `read` tool) for the full Step 2.1 and Step 2.2 procedure.

**Summary:** Invoke `snowflake-interactive` skill to analyze the query and determine the best approach — zero-copy interactive (querying source tables directly) or interactive tables (copied data). The skill owns this decision. Capture `INTERACTIVE_WAREHOUSE`, `INTERACTIVE_SCHEMA`, `OPTIMIZED_QUERY`, and `INTERACTIVE_MODE` (`zero-copy` or `interactive-tables`) from the skill output. Then run the query on both standard and interactive warehouses. **CRITICAL: If the skill chooses interactive-table mode (Path B), explicitly instruct it to use the standard warehouse (`STANDARD_WAREHOUSE` from Phase 1) for ALL DDL and table creation — interactive warehouses reject `CREATE INTERACTIVE TABLE ... AS SELECT` and any CTAS.** If the query exceeds 10s on standard or 5s on interactive, or shows no speedup — **STOP** and do not proceed to Phase 3.

---

## Phase 3: Run the Benchmark

**Only enter this phase after Phase 2 confirms the query is suitable for interactive.**

From this point, everything runs autonomously within the user-approved limits from Phase 1. No further questions are asked unless the limits are exhausted.

### Step 3.1: Verify Docker is Running

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 1 to `completed`, step 2 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 1 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 2 start`. Do not proceed until both calls complete.

2. Use the `bash` tool:

```bash
docker info > /dev/null 2>&1
```

If Docker is not running, warn the user: **"Docker is required to build and push container images for the SPCS benchmark deployment. Please start Docker Desktop (or the Docker daemon) and try again."**

---

### Step 3.2: Validate Interactive Setup

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 2 to `completed`, step 3 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 2 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 3 start`. Do not proceed until both calls complete.

2. Verify the interactive setup is correct before deploying. The validation differs depending on the `INTERACTIVE_MODE` captured in Step 2.1.

**Load** `references/interactive-validation.md` (via the `read` tool) for the full Mode A (zero-copy) and Mode B (interactive tables) validation procedures, including SQL examples, working set sizing guidelines, and failure criteria.

---

### Step 3.3: Configure Concurrency and Fallback

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 3 to `completed`, step 4 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 3 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 4 start`. Do not proceed until both calls complete.

**CRITICAL: Interactive warehouses scale concurrency *horizontally* (multi-cluster), not vertically. Configure `MAX_CLUSTER_COUNT` and a fallback warehouse BEFORE the load test.**

**MANDATORY — Warm-up after any warehouse change:** Every time a warehouse is created, resized, resumed from suspension, or has its cluster count changed (including this initial configuration and every escalation in Step 3.12), you MUST run the cache warm-up procedure (Step 3.6) before measuring performance. Never run a load test against a cold or freshly-reconfigured warehouse.

**Load** `references/mcw-sizing.md` (via the `read` tool) for the MCW sizing formula. Then **Load** `references/concurrency-config.md` for the full configuration procedure: formula application, `resize-wh.sh` usage, Locust resume sequencing, ALTER WAREHOUSE commands, and fallback warehouse setup.

---

### Step 3.4: Save the Benchmark Query

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 4 to `completed`, step 5 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 4 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 5 start`. Do not proceed until both calls complete.

2. The user provides the query to benchmark as part of their request to CoCo. Create `benchmark/test/benchmark-query.sql` from the template file `benchmark/test/benchmark-query.sql.template` by replacing the placeholder content with the actual query:

1. Use `read` to load `<SKILL_DIR>/benchmark/test/benchmark-query.sql.template`
2. Replace the placeholder text with the user's query (or the optimized version if the `snowflake-interactive` skill produced one)
3. Use `write` to save the result to `<SKILL_DIR>/benchmark/test/benchmark-query.sql`

This file is the single query executed against the interactive warehouse during the load test. It will be uploaded to the Snowflake stage automatically during deployment (Step 3.7).

**Updating queries without redeploying:** If you need to change the query after the initial deployment (e.g. during escalation), save the new `.sql` file locally, then run `<SKILL_DIR>/benchmark/scripts/update.sh --queries-only` to upload the new query and restart the API service — no Docker image rebuild is required.

**If the template file does not exist** or the query is empty after substitution: inform the user of the error, then jump to Step 3.14 (cleanup) — the benchmark cannot proceed without a valid query file.

---

### Step 3.5: Configure Environment

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 5 to `completed`, step 6 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 5 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 6 start`. Do not proceed until both calls complete.

2. Both config files MUST be created from their templates — never edit the templates directly.

1. **Create `benchmark/.env`** from `benchmark/.env.template`:
   Use `read` to load the template, then `write` to create the `.env` file with these exact values:
   ```
   CONNECTION_NAME=<connection from Phase 1>
   SOLUTION_NAME=<benchmark name from Phase 1>
   ```

2. **Create `benchmark/spcs/config.env`** from `benchmark/spcs/config.env.template`:
   Use `read` to load the template, then `write` to create `config.env` with all values populated.

   **Explicitly set** these values in `config.env` from the answers gathered in Phase 1 and the outputs captured in Step 2.1. Do NOT rely on template defaults — the whole run is wrong if any of these drift:

   | Variable | Source | Example |
   |---|---|---|
   | `CONNECTION` | Phase 1 answer | `PM` |
   | `ROLE` | Phase 1 or `ACCOUNTADMIN` | `ACCOUNTADMIN` |
   | `INTERACTIVE_WAREHOUSE` | **Step 2.1 output** — the exact name `snowflake-interactive` created | `DM_TESTTPCH_BENCH_WH_INT` |
   | `INTERACTIVE_SCHEMA` | **Step 2.1 output** | `TPCH_SF100_INT` |
   | `API_DATABASE` | **Phase 1 answer** | `DM_TESTTPCH_BENCH_DB` |
   | `LOCUST_USERS` | **Phase 1 answer** — the concurrent-users number | `50` |
   | `LOCUST_RUN_TIME` | Default `3m`, or user-supplied | `3m` |

   After writing, use the `grep` tool on the file to sanity-check that no template placeholder or stale value remains. The `INTERACTIVE_WAREHOUSE` and `LOCUST_USERS` values are the two most common sources of "the benchmark ran with the wrong settings" bugs.

3. If `benchmark/.env` or `benchmark/spcs/config.env` already exist from a previous run, do NOT reuse them blindly. Use `read` to inspect the existing values, then use `edit` to overwrite anything that changed compared to the current Phase 1/Step 2.1 answers.

**If any config file creation fails** (template not found, write error, or `grep` finds leftover placeholders after writing): inform the user which config is invalid and why, then jump to Step 3.14 (cleanup) — the benchmark cannot proceed with misconfigured environment files.

**Note on Locust execution model:** As of this skill version, Locust runs in **non-headless mode with `--autostart` inside the container** — no external HTTP calls are needed to trigger the run. There is no `LOCUST_HEADLESS` toggle. See Step 3.8 and Step 3.9 for the execution flow.

---

### Step 3.6: Warm the Cache

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 6 to `completed`, step 7 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 6 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 7 start`. Do not proceed until both calls complete.

2. Before the load test measures anything, warm the interactive warehouse cache so the numbers reflect steady-state performance, not cold-start latency.

**Load** `references/cache-warming.md` (via the `read` tool) for the full cache warming procedure, including SQL examples, iteration guidance, and convergence checks.

---

### Step 3.7: Deploy to SPCS

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 7 to `completed`, step 8 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 7 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 8 start`. Do not proceed until both calls complete.

**IMPORTANT — Cache must be warm before deploy:** Locust auto-starts immediately when its container becomes READY, so the load test will begin as soon as SPCS finishes provisioning. Ensure Step 3.6 (cache warming) is complete before running this step — otherwise Locust measures cold-cache latency.

Use the `bash` tool with `run_in_background=true`:

```bash
cd <SKILL_DIR>/benchmark/scripts && ./deploy.sh
```

This deploys:
- **Benchmark API** — FastAPI server that executes queries against the interactive warehouse
- **Locust** — Load generator that POSTs queries to the API

**Cost note:** This creates 2 compute pools (CPU_X64_M) that incur credits while running. All resources are listed in Step 3.14 where the user chooses to tear down or keep them.

**IMPORTANT — Deployment monitoring:** SPCS deployments can take 3–10 minutes (compute pool provisioning + image pull + container start). **You MUST give the user clear, human-readable progress updates** so the deployment doesn't look stuck. Bare tool-call blocks with no text are unacceptable.

1. Run `deploy.sh` in the background (`run_in_background=true`). Use `bash_output` to check progress.
2. **Every 30 seconds**, poll service status:
   ```bash
   cd <SKILL_DIR>/benchmark/scripts && ./status.sh
   ```
3. **After every poll, write a one-line text update** summarizing the current state. Examples:
   - "Both services still PENDING — compute pools are provisioning. (~1 min elapsed)"
   - "Benchmark API is READY. Locust is PENDING — pulling image. (~3 min elapsed)"
   - "Both services are READY — deployment complete."

   Include: which services are up, what the current status/message is, and roughly how long it has been. This keeps the user informed instead of showing a wall of silent BASH OUTPUT blocks.
4. If a service stays in PENDING for more than 5 minutes, run `./logs.sh` and report any errors to the user. Common causes:
   - Compute pool still provisioning (normal — wait)
   - Image pull in progress (normal — wait)
   - Image not found (check `build-and-push.sh` succeeded)
   - Insufficient privileges (check ROLE)
5. If a service enters FAILED state, immediately run `./logs.sh`, show the user the output, and stop.
6. Only proceed to the next step once both services report READY.
7. **Display the SPCS topology to the user** (see "SPCS Deployment Topology" section above). This makes it clear how many containers are running and how compute is distributed, so the user can judge whether the infrastructure is appropriately sized for their concurrency target.

---

### Steps 3.8–3.9: Baseline Test + Load Test

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 8 to `completed`, step 9 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 8 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 9 start`. Do not proceed until both calls complete.
2. **Mid-step PROGRESS UPDATE (mandatory):** When the baseline completes successfully, call `system_todo_write` — set step 9 to `completed`, step 10 to `in_progress`. Then run `update-progress.sh <REPORT_DIR> 9 complete && update-progress.sh <REPORT_DIR> 10 start`.

3. **Load** `references/benchmark-execution.md` (via the `read` tool) for the full baseline and load test procedure.

**Summary:** The Locust container runs a two-phase execution model automatically on start: (1) a baseline test against the no-op `/api/run/baseline` endpoint to validate infrastructure, then (2) the real load test against `/api/run/interactive`. No external HTTP calls are needed — auto-start sidesteps SPCS auth. Monitor via `./logs.sh locust`; look for `[baseline] VERDICT: PASS` before the benchmark begins. For subsequent runs (after escalation), restart the Locust service via `./update.sh` or `ALTER SERVICE ... SUSPEND / RESUME`. Parse the `/api/run/interactive` row from the Locust CSV for P50, P95, P99 and failure counts.

---

### Step 3.10: Analyze Results and Generate Recommendations

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 10 to `completed`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 10 complete`. Do not proceed until both calls complete.

2. After the load test completes, collect **three sets of measurements**:

1. **Baseline (Locust HTTP)** — p99 from the baseline CSV for `/api/run/baseline`. This is the infrastructure overhead floor — the minimum latency added by the API/network layer.
2. **Client-side (Locust HTTP)** — P50, P95, P99 from the Locust CSV for the `/api/run/interactive` endpoint. This is what the end user experiences (HTTP round-trip + API pool + Snowflake).
3. **Server-side (Snowflake)** — P50, P95, P99 computed from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` for the interactive warehouse. This is what Snowflake alone spent (compile + queue + execute).

All three sets of numbers are **mandatory**. The server-side numbers are what proves Snowflake performance; the client-side numbers are what the user's dashboard sees; the baseline numbers establish the infrastructure overhead floor. The **delta between client-side and server-side isolates the API/HTTP overhead from Snowflake's real cost**. If that delta is significantly higher than the baseline p99, there may be connection pool contention or other API-layer issues beyond simple HTTP overhead.

Also collect:
- Throughput (requests/sec) from Locust
- Error rates (Locust) and count of fallback-served queries (server-side query count on the fallback WH)

**Latency goal convention:** When the user specifies a latency target (e.g. "queries must complete within 2 seconds"), interpret that as a **P95 target** unless they explicitly state otherwise. Evaluate the goal against **both** client-side and server-side P95 — if server-side meets the goal but client-side does not, the API is the bottleneck; if both fail, the warehouse configuration needs work.

Then invoke the `snowflake-interactive` skill again via `skill(command="snowflake-interactive")` to analyze the benchmark results and produce optimization recommendations:
- Does the query need rewrites or tweaks for better interactive performance?
- Would clustering keys on the interactive tables improve results?
- Are there join or filter patterns that could benefit from search optimization?

Capture these recommendations for the report.

---

### Step 3.11: Post-Benchmark Server-Side Validation

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 11 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 11 start`. Do not proceed until both calls complete.

2. After collecting the Locust CSV, **you MUST run server-side aggregation queries against Snowflake for the interactive warehouse**. This is not optional — the Locust numbers alone cannot distinguish API/HTTP overhead from Snowflake time.

**Important — use `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE`, not `ACCOUNT_USAGE.QUERY_HISTORY`.** The `ACCOUNT_USAGE` view has a 45-minute to 3-hour latency and will return zero rows immediately after the benchmark. `INFORMATION_SCHEMA` is fresh within seconds. Run these diagnostic queries via `snowflake_sql_execute` from a **non-interactive** warehouse (e.g. `USE WAREHOUSE COMPUTE_WH`) — running them on the interactive WH will hit the 5-second cancel.

The API sets `QUERY_TAG` to the `SOLUTION_NAME` (benchmark name) on every request. This allows isolating benchmark traffic in `QUERY_HISTORY` queries. Because the default benchmark name includes a `YYYYMMDDHHMM` timestamp, each benchmark run produces a unique tag. If the user provides a custom name without a timestamp pattern, append `_YYYYMMDDHHMM` to the tag value so that queries from different runs of the same benchmark can be distinguished.

**Load** `references/server-side-validation.md` (via the `read` tool) for the exact SQL queries, delta interpretation rules, and query profile health metrics.

**Cluster usage detection:** The aggregate server-side query includes `COUNT(DISTINCT CLUSTER_NUMBER) AS DISTINCT_CLUSTERS_USED` and `MAX(CLUSTER_NUMBER) AS PEAK_CLUSTER_NUMBER`. These tell you exactly how many clusters actually served queries during the load test, even if `MAX_CLUSTER_COUNT` was set higher. Capture both values — they populate the `{{CLUSTERS_ACTUAL}}` placeholder in the report (format: "X of Y" where X is `DISTINCT_CLUSTERS_USED` and Y is the configured `MAX_CLUSTER_COUNT`). Also include the cluster count in each row of the `{{ITERATION_HISTORY}}` table so the reader can see how cluster usage changed across escalation steps.

---

### Step 3.12: Goal Check and Iterative Escalation

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 11 to `completed`, step 12 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 11 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 12 start`. Do not proceed until both calls complete.

2. After collecting the server-side percentiles from Step 3.11, evaluate them against the P95 latency goal captured in Phase 1.

**Load** `references/escalation.md` (via the `read` tool) for the full escalation procedure: Case 1/2/3 decision logic, scale-out vs scale-up selection, `resize-wh.sh` commands, post-resize warm/resume/monitor sequence, limits-reached messaging, and iteration history recording.

---

### Step 3.13: Generate HTML Report

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 12 to `completed`, step 13 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 12 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 13 start`. Do not proceed until both calls complete.

2. **MANDATORY: Load the `html-authoring` skill first** by calling `skill(command="html-authoring")`. This skill provides the sandboxed-HTML rules that must be followed when writing the report file. Load it before any HTML file creation.

**MANDATORY: use the bundled template.** The report MUST be produced by starting from the canonical HTML template shipped with this skill and filling in its `{{PLACEHOLDER}}` tokens. Do NOT hand-author the report from scratch, do NOT change the section order, and do NOT modify the CSS or structure.

**Template path:** `templates/benchmark-report.html.template`

**Output directory:** `<SKILL_DIR>/benchmark/reports/<SOLUTION_NAME>/`

Create a subfolder named after the benchmark (e.g. `reports/IWB_202608271430/`). Save the following files in it using the `write` tool:
- `benchmark-report.html` — the filled-in HTML report (generated once at the end, after all iterations)
- `locust-run-1.txt` — Locust log from the first load test iteration
- `locust-run-2.txt` — Locust log from the second iteration (if escalation triggered a re-run)
- `locust-run-3.txt` — Locust log from the third iteration (if needed)

Each time the load test runs (Step 3.9), capture the full Locust output (via `bash` running `./logs.sh locust`) and save it to the next numbered file using `write`. This ensures every iteration's results are preserved — even runs that did not meet the goal. The final HTML report references the last successful run's data, but earlier runs provide the escalation history.

**Load** `references/report-generation.md` (via the `read` tool) for the full procedure, coverage requirements, and verification steps.

**Report generation procedure:**
1. Use `read` to load the template from `templates/benchmark-report.html.template`
2. Substitute all `{{PLACEHOLDER}}` tokens with collected values
3. Use `write` to save the filled-in report to `<SKILL_DIR>/benchmark/reports/<SOLUTION_NAME>/benchmark-report.html`
4. Use the `grep` tool to verify no `{{` placeholders remain: `grep '{{' <output-file>` must return zero matches
5. Use `open_browser` to open the report for the user

---

### Step 3.14: Resource Summary and Cleanup

1. **PROGRESS UPDATE (mandatory):** Call `system_todo_write` — set step 13 to `completed`, step 14 to `in_progress`. Then run `bash <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 13 complete && <SKILL_DIR>/benchmark/scripts/update-progress.sh <REPORT_DIR> 14 start`. Do not proceed until both calls complete.
2. **End-of-step PROGRESS UPDATE (mandatory):** After cleanup completes, call `system_todo_write` — set step 14 to `completed`. Then run `update-progress.sh <REPORT_DIR> 14 complete` (this auto-sets top-level status to `"completed"`).

3. **Load** `references/cleanup.md` (via the `read` tool) for the full cleanup procedure.

**Summary:** Present the user with a table of all created resources (interactive warehouse, schema, tables, SPCS database/schema, compute pools, image repo, services). Use `ask_user_question` with three options: (1) Full cleanup, (2) SPCS only, (3) Keep everything. For full cleanup, run `./teardown.sh` then drop schemas/warehouse/database via SQL. For "keep everything", save `SPCS_DEPLOYED=true` to `.env` so future runs skip redeployment.

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

- ⚠️ **Phase 1** — Do not proceed until all inputs are confirmed by the user
- ⚠️ **Phase 2 (Suitability Check)** — STOP if query exceeds 10s on standard, 5s on interactive, or shows no speedup. Do not enter Phase 3.
- ⚠️ **Step 3.1** — STOP if Docker is not running. Cannot deploy SPCS without it.
- ⚠️ **Step 3.7** — STOP if any SPCS service enters FAILED state. Show logs and do not proceed.
- ⚠️ **Step 3.8** — STOP if baseline test fails (high failure rate or p99). Infrastructure is not healthy.
- ⚠️ **Step 3.12** — STOP and ask the user only when both scale-out and scale-up limits are exhausted and the P95 goal is still not met.
- ⚠️ **Step 3.14** — Confirm cleanup choice before dropping any resources.

## Output

- `benchmark/reports/<SOLUTION_NAME>/benchmark-report.html` — HTML report with executive summary, percentile charts, bottleneck diagnosis, escalation path, and optimization recommendations
- `benchmark/reports/<SOLUTION_NAME>/locust-run-N.txt` — Raw Locust logs for each load test iteration (one per escalation step)
- Snowflake resources (interactive warehouse, tables, SPCS services) — listed in Step 3.14 for cleanup or reuse

## Checklist and Troubleshooting

**Load** `references/checklist-and-troubleshooting.md` for the full "Good Setup" checklist and troubleshooting table. Verify all checklist items pass before considering the benchmark complete.
