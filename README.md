# Interactive Analytics

This repository contains **samples, demos, and benchmarking tools** to help you
get started with Snowflake [**Interactive Analytics**](https://docs.snowflake.com/en/user-guide/interactive) scenarios — including
interactive warehouses, interactive tables, and low-latency, high-concurrency
workloads.

## Contents

### [`tpc-h/`](tpc-h/)

TPC-H benchmark harness for Snowflake **Interactive Warehouses**. Copies TPC-H tables from `SNOWFLAKE_SAMPLE_DATA` into a local benchmark database, then runs the 22 standard queries (original and modern rewrites) against standard or interactive tables at scale factors 1, 10, 100, and 1000. See [`tpc-h/README.md`](tpc-h/README.md) for setup and usage.

### [`benchmark/`](.cortex/skills/interactive-benchmark/benchmark/)

Generic Interactive Warehouse benchmark tool. A FastAPI server exposes an endpoint (`/api/run/interactive`) that executes any user-provided SQL query against an interactive warehouse under concurrent load. Includes a Locust-based load test for concurrency benchmarking and full Snowpark Container Services deployment. See [`benchmark/README.md`](.cortex/skills/interactive-benchmark/benchmark/README.md) for setup and usage.

### [`tpc-h-sample-dashboard/`](tpc-h-sample-dashboard/)

TPC-H interactive dashboard demo. A FastAPI + Chart.js single-page app that visualizes TPC-H data (KPIs, orders over time, segment/region breakdowns) with a Locust load generator for concurrent user simulation. Deployable to SPCS. See [`tpc-h-sample-dashboard/README.md`](tpc-h-sample-dashboard/README.md) for setup and usage.

## Cortex Code (CoCo) Skills

This repository includes three **project-level CoCo skills** that automate common workflows through conversational prompts in Cortex Code.

### `interactive-benchmark`

Benchmark **any SQL query** on interactive warehouses under concurrent load.

- Chains the `snowflake-interactive` skill to create interactive tables and optimize the query
- Deploys the benchmark API and Locust load test to Snowpark Container Services
- Reports whether the query meets its P95 latency goal under load

**Usage:** Ask something like *"benchmark my query on interactive vs standard"*.

### `interactive-tpch-benchmark`

Set up and run the **TPC-H benchmark locally** against interactive and standard warehouses.

- Creates TPC-H tables at various scale factors (1, 10, 100, 1000)
- Runs the 22 standard queries and collects timing results (JSON + CSV)
- Supports both `original` and `modern` (window functions, QUALIFY) query variants

**Usage:** Ask something like *"set up the TPC-H benchmark at scale 10"* or *"run tpch queries against interactive"*.

### `interactive-tpch-dashboard`

Deploy the **TPC-H dashboard demo** and Locust load test to SPCS.

- Deploys FastAPI + Chart.js dashboard with real-time TPC-H visualizations
- Deploys a Locust load generator for simulating concurrent dashboard users
- Manages SPCS service lifecycle (deploy, status, update, teardown)

**Usage:** Ask something like *"deploy the TPC-H dashboard to SPCS"* or *"check tpch dashboard status"*.

---

More samples and scenarios will be added over time.
