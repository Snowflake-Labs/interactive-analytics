# Interactive Analytics

This repository contains **samples, demos, and benchmarking tools** to help you
get started with Snowflake [**Interactive Analytics**](https://docs.snowflake.com/en/user-guide/interactive) scenarios — including
interactive warehouses, interactive tables, and low-latency, high-concurrency
workloads.

## Contents

### [`tpc-h/`](tpc-h/)

TPC-H benchmark harness for Snowflake **Interactive Warehouses**. Copies TPC-H tables from `SNOWFLAKE_SAMPLE_DATA` into a local benchmark database, then runs the 22 standard queries (original and modern rewrites) against standard or interactive tables at scale factors 1, 10, 100, and 1000. See [`tpc-h/README.md`](tpc-h/README.md) for setup and usage.

### [`dashboard/`](dashboard/)

Interactive Tables benchmarking dashboard. A FastAPI + Chart.js single-page app that compares Snowflake **Interactive Tables + Interactive Warehouse** vs **Standard Tables** using TPC-H-derived queries. Includes a Locust-based load test to simulate concurrent dashboard users and measure query latency under load, plus full Snowpark Container Services deployment scripts. See [`dashboard/README.md`](dashboard/README.md) for setup and usage.

## Cortex Code (CoCo) Skill

This repository includes a **project-level CoCo skill** (`interactive-tpch-benchmark`) that lets you run the TPC-H benchmark and deploy the dashboard entirely through conversational prompts in Cortex Code. The skill automates:

- Setting up TPC-H tables and warehouses
- Running benchmark queries against interactive or standard warehouses
- Deploying the dashboard and Locust load test to Snowpark Container Services
- Checking SPCS service status and ingress URLs
- Tearing down benchmark resources

To use it, open this project in Cortex Code and ask something like *"run the TPC-H benchmark"* or *"deploy the dashboard to SPCS"* — the skill will guide you through the rest.

---

More samples and scenarios will be added over time.
