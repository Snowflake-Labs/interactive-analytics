---
name: interactive-tpch-benchmark
description: "Deploy and run the TPC-H benchmark on Snowflake Interactive Warehouses, and deploy the dashboard to SPCS. Use when: setting up the benchmark, running TPC-H queries, deploying the dashboard, tearing down resources, checking service status. Triggers: tpc-h, benchmark, interactive warehouse, interactive tables, deploy dashboard, spcs dashboard, locust, load test, setup benchmark, teardown."
---

# Interactive Analytics TPC-H Benchmark

Guides users through deploying and running the TPC-H benchmark on Snowflake Interactive Warehouses, and deploying the interactive dashboard + load test to SPCS.

## Prerequisites

- `uv` installed (Python package runner)
- A Snowflake connection configured in `~/.snowflake/connections.toml`
- Role with privileges to create databases, warehouses, compute pools, and services (e.g. `SYSADMIN` or `ACCOUNTADMIN`)
- Docker installed (for SPCS dashboard deployment only)

## Workflow

### Step 1: Detect Intent

Ask the user what they want to do:

1. **Setup** — Create TPC-H tables + warehouses for benchmarking
2. **Run benchmark** — Execute TPC-H queries against interactive or standard warehouses
3. **Deploy dashboard** — Deploy the FastAPI dashboard + Locust load test to SPCS
4. **Check status** — Show SPCS service status and ingress URLs
5. **Teardown** — Remove benchmark resources or SPCS services

Route to the matching section below.

---

### Setup: Create TPC-H Tables and Warehouses

**Goal:** Copy TPC-H data from `SNOWFLAKE_SAMPLE_DATA` into a local benchmark database with standard and interactive tables.

**Actions:**

1. Ensure `.env` exists in `tpc-h/`:
   ```bash
   cp tpc-h/.env.example tpc-h/.env
   ```

2. Ask the user for configuration:
   - `CONNECTION_NAME` — their Snowflake connection name (from `~/.snowflake/connections.toml`)
   - `SOLUTION_NAME` — prefix for all object names (default: `TPCH`)
   - `DEFAULT_SCALE` — scale factor: 1, 10, 100, or 1000 (default: 10)

3. Update `tpc-h/.env` with the user's values.

4. Run setup:
   ```bash
   cd <REPO_ROOT>/tpc-h && ./iwtpch.sh setup --scale <SCALE>
   ```

**Objects created:**
- Database: `<SOLUTION_NAME>_BENCH_DB`
- Schemas: `TPCH_SF<scale>` (standard tables), `TPCH_SF<scale>_IT` (interactive tables)
- Warehouses: `<SOLUTION_NAME>_BENCH_WH_STD_<scale>` (standard), `<SOLUTION_NAME>_BENCH_WH_INT_<scale>` (interactive)

**Note:** Run setup separately for each scale factor the user wants to benchmark. The interactive warehouse is attached to all 8 interactive tables in the `_IT` schema.

---

### Run Benchmark: Execute TPC-H Queries

**Goal:** Run the 22 TPC-H queries and collect timing results.

**Actions:**

1. Ask the user:
   - Target: `interactive` (default) or `standard`
   - Scale: 1, 10, 100, or 1000
   - Workload: `original` (standard SQL) or `modern` (window functions, QUALIFY)
   - Specific queries (optional): comma-separated list like `2,11,15`
   - Repeats per query (default: 3, keeps best time)

2. Run the benchmark:
   ```bash
   cd <REPO_ROOT>/tpc-h && ./iwtpch.sh run \
     --target <TARGET> \
     --scale <SCALE> \
     --workload <WORKLOAD>
   ```

   Optional flags:
   - `--queries 2,11,15` — run only specific queries
   - `--repeats 5` — best of N executions per query
   - `--iterations 3` — full workload passes

3. Results are saved to `tpc-h/results/run_<target>_sf<scale>_<workload>_<timestamp>.json` and `.csv`.

**Typical comparison flow:**
```bash
./iwtpch.sh run --target interactive --scale 10 --workload original
./iwtpch.sh run --target standard --scale 10 --workload original
```

At SF1, result validation automatically checks against reference values in `tpc-h-results-1GB.json`.

---

### Deploy Dashboard to SPCS

**Goal:** Deploy the FastAPI + Chart.js dashboard and Locust load test to Snowpark Container Services.

**Actions:**

1. Ensure `dashboard/.env` exists:
   ```bash
   cp dashboard/.env.example dashboard/.env
   ```

2. Ask the user for:
   - `CONNECTION_NAME` — Snowflake connection
   - `SOLUTION_NAME` — same as used for TPC-H setup (default: `IW_TPCH`)
   - `DEFAULT_SCALE` — scale for the dashboard queries

3. Update `dashboard/.env` with the values.

4. Review `dashboard/spcs/config.env` — key settings:
   - `CONNECTION` — Snowflake connection for SPCS deployment
   - `ROLE` — role for creating SPCS objects (default: `ACCOUNTADMIN`)
   - `DEPLOY_WAREHOUSE` — warehouse for deploy SQL session

5. Create the denormalized dashboard table:
   ```bash
   cd <REPO_ROOT>/dashboard/spcs && ./deploy.sh sql
   ```

6. Deploy SPCS services (builds Docker images, pushes, creates compute pools and services):
   ```bash
   cd <REPO_ROOT>/dashboard/spcs && ./deploy.sh services
   ```

**Services deployed:**
- `DASHBOARD` — browser UI + API (dashboard compute pool)
- `DASHBOARD_API_LOCUST` — isolated API copy for load testing (locust compute pool)
- `DASHBOARD_LOCUST` — Locust load generator (locust compute pool)

**After deployment:** The script prints ingress URLs. Open the dashboard URL in a browser (Snowflake login prompts on first visit).

---

### Check Status

```bash
cd <REPO_ROOT>/dashboard/spcs && ./status.sh
```

Options:
- `./status.sh --wait` — poll until all services are READY
- `./status.sh --urls-only` — print only ingress URLs

---

### Update Dashboard (rebuild without changing URLs)

```bash
cd <REPO_ROOT>/dashboard/spcs && ./update.sh
```

---

### Teardown

**TPC-H resources** (drops warehouses for a specific scale):
```bash
cd <REPO_ROOT>/tpc-h && ./iwtpch.sh teardown --scale <SCALE>
```

**SPCS services** (drops services, compute pools, image repo):
```bash
cd <REPO_ROOT>/dashboard/spcs && ./teardown.sh
```

---

## Stopping Points

- After detecting intent — confirm the action before proceeding
- After collecting configuration values — confirm `.env` contents before running setup
- Before `deploy.sh services` — warn that this builds Docker images and creates compute pools (cost implications)
- Before teardown — confirm which resources to drop

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `uv: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `SNOWFLAKE_SAMPLE_DATA` not accessible | Ensure the role has USAGE on the shared database |
| Docker build fails | Ensure Docker daemon is running; check `docker info` |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Service FAILED | Check `./logs.sh`; common cause is missing grants or network rules |
| Connection errors | Verify connection name exists in `~/.snowflake/connections.toml` |

## Output

- TPC-H benchmark results (JSON + CSV) in `tpc-h/results/`
- Running SPCS services with public ingress URLs for the dashboard and Locust UI
