# Getting Started with the Interactive Benchmark Skill

This skill benchmarks any SQL query against a Snowflake Interactive Warehouse under concurrent load. It deploys a FastAPI server and Locust load generator to Snowpark Container Services (SPCS), measures latency percentiles (P50/P95/P99), and auto-scales the warehouse until the P95 target is met.

## 1. Clone the repo

```bash
git clone https://github.com/Snowflake-Labs/interactive-analytics.git
cd interactive-analytics
```

## 2. Install prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| **Cortex Code** (Desktop or CLI) | Runs the skill | [Docs](https://docs.snowflake.com/en/user-guide/ui-snowsight/cortex-code) |
| **Docker** | Builds and pushes SPCS container images | [docker.com](https://www.docker.com/get-started) |
| **`snow` CLI** | Snowflake CLI for SPCS operations | `pip install snowflake-cli` or `brew install snowflake-cli` |
| **`uv`** | Python package runner (used by the API and Locust) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **`envsubst`** | Renders YAML specs from templates | Comes with `gettext` (`brew install gettext` on macOS) |

## 3. Configure a Snowflake connection

Make sure you have a connection in `~/.snowflake/connections.toml` with a role that can create databases, warehouses, compute pools, image repositories, and services. `ACCOUNTADMIN` or `SYSADMIN` with appropriate grants will work.

```toml
# ~/.snowflake/connections.toml
[myconn]
account = "myorg-myaccount"
user = "myuser"
authenticator = "externalbrowser"
role = "SYSADMIN"
warehouse = "COMPUTE_WH"
```

Verify the connection:

```bash
snow connection test -c myconn
```

## 4. Open the project in Cortex Code

Open the cloned `interactive-analytics` folder in Cortex Code Desktop, or `cd` into it in Cortex Code CLI. The skill is auto-discovered from `.cortex/skills/interactive-benchmark/SKILL.md`.

## 5. Run the benchmark

In the Cortex Code chat panel, type something like:

> Benchmark this query on an interactive warehouse with 50 concurrent users and a P95 goal of 1 second:
> ```sql
> SELECT l_returnflag, l_linestatus,
>        SUM(l_quantity) AS sum_qty,
>        SUM(l_extendedprice) AS sum_base_price
> FROM   lineitem
> WHERE  l_shipdate <= DATEADD(day, -90, '1998-12-01')
> GROUP  BY l_returnflag, l_linestatus
> ORDER  BY l_returnflag, l_linestatus;
> ```

The skill takes over from here. It will:

1. **Collect inputs** -- ask you to confirm the database, schema, connection name, P95 latency goal, concurrency level, warehouse size limits, and benchmark name.
2. **Create interactive tables** -- invoke the `snowflake-interactive` sub-skill to set up the interactive warehouse and tables for your query.
3. **Validate suitability** -- run the query on both standard and interactive warehouses to confirm the interactive warehouse provides a meaningful speedup.
4. **Deploy SPCS infrastructure** -- build Docker images, push them to the SPCS image registry, create compute pools, and deploy the API and Locust services.
5. **Run the benchmark** -- Locust auto-starts inside SPCS, runs a baseline test, then the actual load test at your target concurrency.
6. **Auto-escalate** -- if the P95 goal is not met, the skill scales the warehouse (out or up) and re-runs, repeating until the goal is met or limits are reached.
7. **Generate a report** -- produce an HTML report with latency percentiles, throughput, and warehouse configuration for each iteration.
8. **Clean up** -- ask whether to tear down SPCS resources, keep them, or keep just the warehouse.

## What gets created in Snowflake

All object names derive from the `SOLUTION_NAME` you choose (default: `IWBENCH`):

| Object | Name Pattern |
|--------|-------------|
| Database | `<SOLUTION_NAME>_BENCH_DB` |
| Interactive warehouse | `<SOLUTION_NAME>_BENCH_WH_INT` |
| Standard warehouse (fallback) | `<SOLUTION_NAME>_BENCH_WH_STD` |
| API compute pool | `<SOLUTION_NAME>_BENCH_API_POOL` |
| Locust compute pool | `<SOLUTION_NAME>_BENCH_LOCUST_POOL` |
| Image repository | `<SOLUTION_NAME>_BENCH_IMAGES` |
| API service | `BENCHMARK_API` |
| Locust service | `BENCHMARK_LOCUST` |

## Benchmark reports

Each run stores artifacts in `.cortex/skills/interactive-benchmark/benchmark/reports/<SOLUTION_NAME>/`:

- `progress.json` -- step-by-step progress tracker (14 steps)
- `benchmark-report.html` -- the final HTML report
- `locust-run-N.txt` -- raw Locust output for each iteration

## Manual script reference

The scripts in `benchmark/scripts/` can be run directly for operational tasks. They all read configuration from `benchmark/spcs/config.env`.

```bash
SCRIPTS=.cortex/skills/interactive-benchmark/benchmark/scripts

# Check service status
$SCRIPTS/status.sh

# Wait for services to become READY
$SCRIPTS/status.sh --wait

# Get ingress URLs only
$SCRIPTS/status.sh --urls-only

# Resize the interactive warehouse
$SCRIPTS/resize-wh.sh --size LARGE
$SCRIPTS/resize-wh.sh --mcw 3
$SCRIPTS/resize-wh.sh --size MEDIUM --mcw 5

# Tail logs
$SCRIPTS/logs.sh api
$SCRIPTS/logs.sh locust

# Rebuild and redeploy in-place
$SCRIPTS/update.sh

# List all SPCS resources
$SCRIPTS/list.sh

# Tear everything down
$SCRIPTS/teardown.sh
```
