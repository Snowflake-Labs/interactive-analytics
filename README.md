# Interactive Analytics

This repository contains **samples, demos, and benchmarking tools** to help you
get started with Snowflake **Interactive Analytics** scenarios — including
interactive warehouses, interactive tables, and low-latency, high-concurrency
workloads.

## Contents

### [`interactive-vs-standard/`](interactive-vs-standard/)

A parallel-load benchmarking tool that compares query latency and throughput
(queries/second) between a **standard warehouse** (`STD_WH`) and an
**interactive warehouse** (`IW_WH`). It runs a configurable workload across N
simulated concurrent users against TPC-DS interactive tables, and reports
latency percentiles (p50/p95/p99), throughput, and side-by-side deltas.

Includes the SQL setup script to provision the required database, schema,
warehouses, and interactive tables. See the folder's
[README](interactive-vs-standard/README.md) for full usage details.

---

### [`tpch/`](tpch/)

A Python harness that runs the full 22-query TPC-H benchmark against a
Snowflake **Interactive Warehouse** and compares it against a standard
warehouse — using `SNOWFLAKE_SAMPLE_DATA.TPCH_SF10` or `TPCH_SF100` as the
source data.

Key features:

- **Two query sets** — `original/` (standard TPC-H SQL) and `modern/` (6
  queries rewritten with window functions and `QUALIFY` for a measurable
  speed-up; the remaining 16 are unchanged).
- **Two scale factors** — SF10 (~10 GB) and SF100 (~100 GB), each with
  independent interactive and standard warehouses provisioned by `setup`.
- **Flexible run control** — run all 22 queries or a subset (`--query N`,
  `--queries 2,11,15`), repeat each query and keep the best time (`--repeats`),
  run multiple full passes (`--iterations`), and run queries concurrently
  (`--parallel X`).
- **Structured output** — each run writes a timestamped JSON and CSV file with
  per-query status, row counts, client and server elapsed times, and a summary
  (warehouse size, latency stats).

Use `./iwtpch.sh` (or `uv run iw-tpch`) with the `setup`, `run`, and
`teardown` subcommands. See the folder's [README](tpch/README.md) for full
usage details.

---

More samples and scenarios will be added over time.
