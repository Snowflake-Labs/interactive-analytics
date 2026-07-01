# TPC-H Benchmark on Snowflake Interactive Warehouse

A small Python harness that runs the [ClickHouse TPC-H Snowflake query set](https://github.com/ClickHouse/tpc-h-openhouse/tree/main/snowflake/queries) against a Snowflake **Interactive Warehouse** built on top of `SNOWFLAKE_SAMPLE_DATA.TPCH_SF10`.

## Layout

```
.
├── iwtpch.sh           # convenience wrapper (same as `uv run iw-tpch`)
├── pyproject.toml          # uv project (snowflake-connector-python)
├── queries/
│   ├── original/           # 22 TPC-H queries 
│   └── modern/             # rewritten variants (window functions / QUALIFY)
├── sql/
│   ├── setup.sql           # template: standard + interactive tables ({{SCALE}} placeholders)
│   └── teardown.sql        # template: drops per-scale warehouses ({{SCALE}} placeholders)
├── src/
│   ├── tpch_runner.py      # CLI entry shim
│   └── tpch/
│       ├── cli.py          # argparse + main
│       ├── commands.py     # setup / run / teardown
│       ├── config.py       # paths, env, target context
│       ├── connection.py   # Snowflake connect + session
│       ├── execution.py    # query runs, thread-pool parallel
│       ├── queries.py      # load query files
│       ├── results.py      # stats, print, JSON/CSV output
│       └── sql_scripts.py  # DDL script runner
└── results/                # JSON + CSV per benchmark run
```

## Prerequisites

- `uv` (the rule for this repo) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Snowflake connection in `~/.snowflake/connections.toml`, with a role (`ACCOUNTADMIN` is used in the setup scripts) that can create databases and warehouses, and read `SNOWFLAKE_SAMPLE_DATA.TPCH_SF10` / `TPCH_SF100`.
- Copy `.env.example` to `.env` and set at least `CONNECTION_NAME` (the connection name from `connections.toml`).

```bash
uv sync
cp .env.example .env   # then edit CONNECTION_NAME, etc.
```

## Scales

The benchmark supports two TPC-H scale factors, selected with `--scale {10,100}` (default from `DEFAULT_SCALE` in `.env`, or `10` if unset):

| Scale | Standard target | Interactive target |
|---|---|---|
| `10` | `IW_TPCH_BENCH.TPCH_SF10` | `IW_TPCH_BENCH.TPCH_SF10_IT` |
| `100` | `IW_TPCH_BENCH.TPCH_SF100` | `IW_TPCH_BENCH.TPCH_SF100_IT` |

Standard tables live in `TPCH_SF<scale>`; interactive tables live in `TPCH_SF<scale>_IT`. Both targets use the `IW_TPCH_BENCH` database unless overridden via CLI flags.

## Snowflake objects created

| Object | Type | Notes |
|---|---|---|
| `IW_TPCH_BENCH` | Database | hosts standard (`TPCH_SF<scale>`) and interactive (`TPCH_SF<scale>_IT`) schemas per scale |
| `IW_TPCH_LOAD_WH` | Standard warehouse (XSMALL for SF10, LARGE for SF100) | drives the CTAS load, then dropped (interactive WH cannot run DDL) |
| `IW_TPCH_BENCH_WH_<scale>` | **Interactive** warehouse (XSMALL for SF10, LARGE for SF100) | one per scale; associated with that scale's interactive tables |
| `TPCH_BENCH_WH_<scale>` | Standard warehouse (XSMALL for SF10, LARGE for SF100) | used by `--target standard` for that scale |

`setup --scale N` loads that scale's 8 tables and creates the interactive and standard warehouses for that scale. Run setup separately for each scale you want to benchmark.

### Clustering keys (only for "alterative" setup script)

Derived from filter / join patterns across the 22 queries:

| Table | `CLUSTER BY` | Drivers |
|---|---|---|
| `LINEITEM` | `(L_SHIPDATE, L_ORDERKEY)` | shipdate range filters in Q1/Q3/Q6/Q7/Q14/Q15/Q20; orderkey is the dominant join key |
| `ORDERS` | `(O_ORDERDATE, O_ORDERKEY)` | orderdate filters in Q3/Q4/Q5/Q8/Q10; orderkey joins |
| `CUSTOMER` | `(C_MKTSEGMENT, C_NATIONKEY)` | Q3 mktsegment filter; nation join broadly used |
| `PART` | `(P_BRAND, P_SIZE)` | brand filters in Q14/Q16/Q17/Q19; size filters in Q2/Q16/Q19 |
| `PARTSUPP` | `(PS_PARTKEY, PS_SUPPKEY)` | natural join keys in Q2/Q9/Q11/Q16/Q20 |
| `SUPPLIER` | `(S_NATIONKEY)` | frequent nation join filter |
| `NATION` / `REGION` | `(N_NATIONKEY)` / `(R_REGIONKEY)` | clustering is mandatory for interactive tables; pruning is moot at 25/5 rows |

### Warehouse Sizes:

| Scale | Warehouse Size |
|---|---|
| 1GB | SMALL |
| 10GB | MEDIUM |
| 100GB | LARGE |
| 1000GB | 2XLARGE |

## Usage

Use `./iwtpch.sh` as a shorthand for `uv run iw-tpch` (both accept the same arguments):

```bash
# 1. Create interactive tables + warehouse for a scale (default scale 10)
./iwtpch.sh setup --scale 10
./iwtpch.sh setup --scale 100   # adds SF100 alongside SF10

# 2. Run the 22 TPC-H queries (interactive target, scale from DEFAULT_SCALE, original workload are the defaults)
./iwtpch.sh run
./iwtpch.sh run --target interactive --scale 10  --workload original
./iwtpch.sh run --target interactive --scale 100 --workload modern

# Same queries on a standard (non-interactive) warehouse, using the standard tables in IW_TPCH_BENCH
./iwtpch.sh run --target standard --scale 10  --workload original
./iwtpch.sh run --target standard --scale 100 --workload modern

# Single query / subset / repeated runs
./iwtpch.sh run --query 17
./iwtpch.sh run --target standard --queries 2,11,15,17,22
./iwtpch.sh run --repeats 5      # best of 5 executions per query
./iwtpch.sh run --iterations 3   # 3 full workload passes
./iwtpch.sh run --parallel 4     # up to 4 queries at once (thread pool)

# 3. Optional cleanup (drops benchmark warehouses for a scale)
./iwtpch.sh teardown --scale 10

# Override connection, database, schema, or warehouse (any subset)
./iwtpch.sh run \
  --connection PM \
  --database IW_TPCH_BENCH \
  --schema TPCH_SF100 \
  --warehouse TPCH_BENCH_WH_100

# Same connection override on setup / teardown
./iwtpch.sh setup --scale 10 --connection PM
./iwtpch.sh teardown --scale 10 --connection PM
```

Each run writes `results/run_<target>_sf<scale>_<workload>_<UTC-timestamp>.json` and `.csv` containing per-query rows (status, row count, client elapsed, server elapsed from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION`, query_id, error) and a summary (connection, database, schema, warehouse, warehouse size, and timing stats).

## Configuration

| Setting | Default | Override |
|---|---|---|
| Connection | `CONNECTION_NAME` in `.env` | `--connection` on `setup`, `run`, `teardown` |
| Scale | `DEFAULT_SCALE` in `.env` (fallback `10`) | `--scale` on `setup`, `run` |
| Database | `IW_TPCH_BENCH` | `--database` on `run` |
| Schema | `TPCH_SF<scale>` (standard) or `TPCH_SF<scale>_IT` (interactive) | `--schema` on `run` |
| Warehouse | `<prefix>_<scale>` for the target (e.g. `IW_TPCH_BENCH_WH_10`) | `--warehouse` on `run` |

CLI flags take precedence over defaults derived from `--target` and `--scale`. Omit them to keep the built-in naming above.

## Targets (engines)

`--target` selects which engine the same query files run against:

| Target | Database | Schema | Warehouse | Tables |
|---|---|---|---|---|
| `interactive` (default) | `IW_TPCH_BENCH` | `TPCH_SF<scale>_IT` | `IW_TPCH_BENCH_WH_<scale>` (interactive) | interactive copies created by `setup` |
| `standard` | `IW_TPCH_BENCH` | `TPCH_SF<scale>` | `TPCH_BENCH_WH_<scale>` (standard) | standard copies created by `setup` |

The query files use unqualified table names, so they resolve via `USE DATABASE`/`USE SCHEMA` and run unchanged on either target and scale. Use `--database`, `--schema`, and `--warehouse` to point at a different Snowflake context without changing the query files.

## Modern query rewrites

Each query was analysed for opportunities to use modern Snowflake SQL (window functions, `QUALIFY`, single-pass CTEs). 6 of the 22 had a clear win; the other 16 are copied unchanged because the optimizer already handles them well (e.g. `IN`/`EXISTS` become semi-joins) or no window construct helps. All rewrites were verified to return identical result sets to the originals via `MINUS` set-difference checks.

| Query | Rewrite | Why it's faster |
|---|---|---|
| Q02 | `QUALIFY ps_supplycost = MIN(ps_supplycost) OVER (PARTITION BY p_partkey)` | Removes the correlated `min()` subquery that re-joined partsupp/supplier/nation/region a second time |
| Q11 | `QUALIFY value > SUM(value) OVER () * 0.0001` | Computes the grand total in a single pass instead of a correlated `HAVING` subquery that repeated the full join |
| Q15 | `QUALIFY total_revenue = MAX(total_revenue) OVER ()` | The CTE is scanned once instead of being referenced again in a `MAX` subquery |
| Q17 | `AVG(l_quantity) OVER (PARTITION BY l_partkey)` | Single `lineitem` pass instead of a correlated per-part `AVG` subquery (largest single-query win) |
| Q18 | CTE computes per-order `SUM(l_quantity)` once and reuses it | Original scans `lineitem` twice (the `IN` subquery's per-order sum equals the final `SUM(l_quantity)`); the rewrite scans it once|
| Q22 | single-pass CTE + `AVG(...) OVER ()` | Scans `customer` once instead of twice (threshold + outer) |

## Notes

- Interactive warehouses can only query interactive tables, so a standard warehouse (`IW_TPCH_LOAD_WH`) is created for the CTAS load.
- `client_elapsed_s` is wall-clock timing measured around `cur.execute` + `fetchall` (so it includes result transfer); `server_elapsed_s` is `TOTAL_ELAPSED_TIME` from Snowflake's query history.
- Each query is executed `--repeats` times (default 3) and the **best** (minimum) client and server times are kept. The first execution warms the warehouse's local cache, so the best of the later runs reflects warm-cache performance (this replaces a separate warm-up phase). The JSON output also records every attempt's `query_id`. Use `--repeats 1` for a single execution per query.
- `--parallel X` (default 1) runs up to X queries concurrently. Each concurrent query uses its own sync Snowflake connection via a thread pool. Per-query timings are unchanged; the summary also reports `wall_elapsed_s` (actual iteration wall time) when `X > 1`. Repeats within a single query still run sequentially on that query's connection.
