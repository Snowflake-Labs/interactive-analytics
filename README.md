# Interactive Analytics

This repository contains **samples, demos, and benchmarking tools** to help you
get started with Snowflake [**Interactive Analytics**](https://docs.snowflake.com/en/user-guide/interactive) scenarios — including
interactive warehouses, interactive tables, and low-latency, high-concurrency
workloads.

## Contents

### [`tpc-h/`](tpc-h/)

TPC-H benchmark harness for Snowflake **Interactive Warehouses**. Copies TPC-H tables from `SNOWFLAKE_SAMPLE_DATA` into a local benchmark database, then runs the 22 standard queries (original and modern rewrites) against standard or interactive tables at scale factors 1, 10, 100, and 1000. See [`tpc-h/README.md`](tpc-h/README.md) for setup and usage.

### [`benchmark/`](benchmark/)

Generic Interactive Warehouse benchmark tool. A FastAPI server exposes two endpoints (`/api/run/interactive` and `/api/run/standard`) that execute any user-provided SQL query against the respective warehouse type. Includes a Locust-based load test for concurrency benchmarking and full Snowpark Container Services deployment. See [`benchmark/README.md`](benchmark/README.md) for setup and usage.

## Cortex Code (CoCo) Skill

This repository includes a **project-level CoCo skill** (`interactive-benchmark`) that lets you benchmark any query against interactive vs standard warehouses through conversational prompts in Cortex Code. The skill:

- Chains the `snowflake-interactive` skill to create interactive tables and optimize the query
- Deploys the benchmark API and Locust load test to Snowpark Container Services
- Supports local or SPCS-based load testing
- Reports latency comparisons between warehouse types

To use it, open this project in Cortex Code and ask something like *"benchmark my query on interactive vs standard"* — the skill will guide you through the rest.

---

More samples and scenarios will be added over time.
