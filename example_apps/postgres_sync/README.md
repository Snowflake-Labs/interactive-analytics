# postgres_sync

A side-by-side comparison of the **same** analytical dashboard running against
**Postgres** and against **Snowflake**, to show where an OLTP engine stops coping
with analytical queries — and where it does not.

Three pieces, usable independently:

| Directory | What it does |
|---|---|
| root (`check_env.py`) | Connectivity check: proves a container can reach both Snowflake and Postgres. Start here. |
| [`data_gen/`](#data_gen-synthetic-data-generator) | Generates the dataset — a 3-table star schema, ~50 GB / 134.6M fact rows, in Postgres. |
| [`bi_dashboard/`](#bi_dashboard-postgres-vs-snowflake) | Cube Core + Next.js: 32 tiles, one model, a picker to switch engines, and a latency badge per tile. |

**You do not need all of it.** If you already have data in both places, go
straight to [`bi_dashboard/`](#bi_dashboard-postgres-vs-snowflake) and point
`.env` at your tables.

## What you need

- **Snowflake**, with a warehouse. An [interactive
  warehouse](#do-i-need-interactive-tables) gives the low-latency serving this
  demo is built around, but a standard warehouse works too — it is just slower.
- **Postgres**: Snowflake Postgres, Amazon RDS/Aurora, Cloud SQL, or self-hosted.
  Only the connection details differ.
- **Somewhere to run two containers**: Snowpark Container Services, or any
  Kubernetes (EKS/GKE/AKS), or just Docker on your laptop. See
  [Deploying](#deploying).
- `uv`, Docker, and Node 22+ for local work.

## Configure it

Everything environment-specific lives in one gitignored TOML file. There are no
credentials, hostnames or database names anywhere else in the repo.

```bash
cd example_apps/postgres_sync
cp .env.example .env
$EDITOR .env          # every key is documented inline
uv sync
uv run check_env.py   # verifies Snowflake + Postgres connectivity
```

`.env` is **TOML**, not dotenv. The table name at the top is arbitrary — the
scripts read the first table in the file — so name it after your `snow` CLI
connection if that helps. Set `CONFIG_SECTION` to choose explicitly when the file
holds several.

Every generated artifact is derived from it and gitignored:

| Generated | By | Contains |
|---|---|---|
| `bi_dashboard/.env.cube` | `gen_env.py` | Cube's `CUBEJS_*` vars, incl. credentials |
| `bi_dashboard/cube/model/cubes.js` | `gen_env.py` | the data model, with your table names |
| `bi_dashboard/.spcs-spec.rendered.yaml` | `render_spec.py` | SPCS spec with credentials inlined |
| `bi_dashboard/.k8s.rendered.yaml` | `render_spec.py --target k8s` | k8s Deployment + Secret |

Credentials are injected at deploy time, never baked into an image layer, so the
images themselves carry no secrets.

### Authentication

The examples use a **programmatic access token** (PAT): put it in a file, point
`token_file_path` at it, and leave `authenticator = "PROGRAMMATIC_ACCESS_TOKEN"`.
`*.token` is gitignored.

Cube's Snowflake driver also accepts key-pair auth if you prefer — set
`CUBEJS_DS_SF_DB_SNOWFLAKE_PRIVATE_KEY_PATH` instead of the password, and adjust
`gen_env.py` accordingly. Plain passwords work too.

### Do I need interactive tables?

No, but they are the point of the comparison.

An **interactive warehouse** serves low-latency queries, and can query ordinary
Snowflake tables as well as interactive tables. So there are three ways to run the
`sf` side, in descending order of speed:

1. **Interactive tables on an interactive warehouse** — what this repo builds, and
   what the numbers below were measured on.
2. **Standard tables on an interactive warehouse** — no table conversion needed;
   point `bi_database`/`bi_schema` at what you already have.
3. **Standard tables on a standard warehouse** — works, just slower. Set
   `interactive_warehouse` to any warehouse.

The dashboard does not care which you choose: it only needs tables whose columns
match, and the table names come from `.env`.

### Postgres on RDS, Aurora, Cloud SQL, or self-hosted

Nothing in the dashboard is specific to Snowflake Postgres. Set `PGHOST`, `PGPORT`,
`PGUSER`, `PGPASSWORD`, `PGDATABASE`, and `pg_schema`.

Two things to watch:

- **TLS.** `pg_ssl = true` works for managed Postgres presenting a valid
  certificate. If you need to pin the RDS CA, set
  `CUBEJS_DS_PG_DB_SSL_CA`/`_CERT`/`_KEY` in `gen_env.py` — Cube's Postgres driver
  reads all three.
- **Reachability.** With Snowflake Postgres the instance is typically locked to a
  compute pool's egress IPs, so the Postgres side can only be exercised from inside
  that pool. With RDS you just need a security group that admits your cluster, and
  you can develop entirely locally.

## Files (root)

| File | Purpose |
|---|---|
| `.env.example` | Template for `.env`, every key documented inline. Copy it, do not edit it. |
| `.env` | Your config. **Gitignored.** |
| `*.token` | Snowflake PAT referenced by `token_file_path`. **Gitignored.** |
| `check_env.py` | Connects to Snowflake (PAT) and Postgres (psycopg2), prints OK/FAILED for each. |
| `pyproject.toml` / `uv.lock` | `uv` project: `snowflake-connector-python`, `psycopg2-binary`. |
| `Dockerfile` | Containerises `check_env.py`. Bakes `.env` and the token into the image — fine for a private connectivity test, **do not publish that image**. |
| `service-spec.yaml` | SPCS job spec for running the check in-cluster. |

## Local check (no container)

```bash
cd example_apps/postgres_sync
uv sync
uv run check_env.py
```

Snowflake should connect from anywhere the account's network policy allows.

Postgres depends on your setup. With **Snowflake Postgres** expect a connection
timeout locally: its network policy typically admits only a compute pool's egress
IPs, not arbitrary clients, so the Postgres path can only be exercised from inside
that pool. With **RDS or self-hosted** Postgres reachable from your machine, both
should pass and you can develop entirely locally.

## Running the check inside SPCS (what actually validates the network policy)

### One-time setup, once per Snowflake account

Only needed when deploying to SPCS *and* using Snowflake Postgres. Skip to
[Deploying](#deploying) otherwise.

1. **Image repository**: `CREATE IMAGE REPOSITORY <db>.<schema>.IMAGES;`
2. **Compute pool**: `CREATE COMPUTE POOL <compute_pool> MIN_NODES=1 MAX_NODES=1
   INSTANCE_FAMILY=CPU_X64_L AUTO_RESUME=TRUE;`
3. **Postgres instance ingress control** — if your Postgres restricts inbound by IP:
   - `<db>.<schema>.<pg_ingress_rule>` — `TYPE=IPV4 MODE=POSTGRES_INGRESS`,
     allows the `<compute_pool>` pool's egress CIDRs.
   - `<pg_network_policy>` — network policy wrapping that rule, attached to the
     `pg_sync_demo` Postgres instance (`DESCRIBE POSTGRES INSTANCE "pg_sync_demo"` → `network_policy`).
   - **Important**: this rule's `TYPE`/`MODE` cannot be changed via `ALTER`/`CREATE OR ALTER`
     (Snowflake limitation). It is NOT a valid `ALLOWED_NETWORK_RULES` target for an
     External Access Integration, which requires `TYPE=HOST_PORT MODE=EGRESS`. Do not
     try to repoint the EAI at it — create a separate rule instead (see below).
4. **Egress for the SPCS container** (outbound internet access — required, containers
   have zero egress by default):
   ```sql
   CREATE OR REPLACE NETWORK RULE <db>.<schema>.<pg_egress_rule>
     MODE = EGRESS
     TYPE = HOST_PORT
     VALUE_LIST = (
       'pm.snowflakecomputing.com:443',
       '<postgres_host>:5432'
     );

   CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION <external_access_integration>
     ALLOWED_NETWORK_RULES = (<db>.<schema>.<pg_egress_rule>)
     ENABLED = TRUE;

   GRANT USAGE ON INTEGRATION <external_access_integration> TO ROLE SYSADMIN;
   ```
   (Do not put this rule in `<service_database>.<service_schema>` — keep all `postgres_sync`
   network objects under `<db>.<schema>`.)

### Build, push, and run

```bash
cd example_apps/postgres_sync

# Build (must be amd64 for SPCS)
docker build --platform linux/amd64 -t postgres-sync-check:latest .

# Login + push to the Snowflake image registry (use the `pm` snow CLI connection,
# not the default connection, or the push will get an Authorization Failure)
snow spcs image-registry login --connection "$SNOW_CONNECTION"
docker tag postgres-sync-check:latest \
  ${IMAGE_REGISTRY}${IMAGE_REPO}/postgres-sync-check:latest
docker push \
  ${IMAGE_REGISTRY}${IMAGE_REPO}/postgres-sync-check:latest
```

Run as a one-off job (not a persistent service — the container just runs the
check and exits):

```sql
EXECUTE JOB SERVICE
  IN COMPUTE POOL <compute_pool>
  NAME = POSTGRES_SYNC_CHECK_JOB
  EXTERNAL_ACCESS_INTEGRATIONS = (<external_access_integration>)
  FROM SPECIFICATION_FILE = 'service-spec.yaml';

SELECT SYSTEM$GET_SERVICE_LOGS('<service_database>.<service_schema>.POSTGRES_SYNC_CHECK_JOB', 0, 'postgres-sync-check');
```

If a job with that name already exists from a previous run:

```sql
DROP SERVICE IF EXISTS <service_database>.<service_schema>.POSTGRES_SYNC_CHECK_JOB;
```

### Expected successful output

```
Connecting to Snowflake...
  OK - version=10.32.102 user=<user> role=<role> warehouse=<warehouse>
Connecting to Postgres...
  OK - PostgreSQL 18.6 on aarch64-unknown-linux-gnu, ...

Snowflake: OK
Postgres:  OK
```

Clean up the job after confirming:

```sql
DROP SERVICE IF EXISTS <service_database>.<service_schema>.POSTGRES_SYNC_CHECK_JOB;
```

## Gotchas

- `snow spcs image-registry login` uses the **default** `snow` CLI connection unless
  you pass `--connection "$SNOW_CONNECTION"`. The default connection in this environment points at a
  different account (`SFCOGSOPS-SNOWHOUSE...`), which causes a silent-looking
  `Authorization Failure` on `docker push` even though login "succeeds".
- `.env` is TOML, not standard `KEY=VALUE` dotenv — parse with `tomllib`/`tomlkit`, not
  `python-dotenv`.
- Don't try to make `<pg_ingress_rule>` do double duty for EAI egress — its
  type is fixed at creation. Always add a second, purpose-specific `HOST_PORT`/`EGRESS`
  rule instead.
- The Postgres instance's hostname changes if the instance is recreated — re-verify
  `PGHOST` in `.env` matches `DESCRIBE POSTGRES INSTANCE "pg_sync_demo"` before
  re-running the egress network rule / check.

## `data_gen/`: synthetic data generator

Loads a 3-table star schema (`sync_demo` schema) into the same Postgres
instance: `product_catalog` (50,000 rows), `user_dimensions` (1,000 rows),
and `purchase_transactions` (a fact table sized to hit a target total size,
50GB by default). Reuses the `.env`/PAT/psycopg2 conventions from
`check_env.py` (see `data_gen/db.py`).

### Files

| File | Purpose |
|---|---|
| `data_gen/cpu.py` | Detects the CPU quota available to the process (cgroup v2 `cpu.max`, cgroup v1 `cpu.cfs_quota_us`/`cpu.cfs_period_us`, falling back to `os.sched_getaffinity`) to size the worker-process count. |
| `data_gen/db.py` | `.env`-loading + psycopg2 connection helpers. Checks both the local layout (`.env` one level above `data_gen/`) and the flattened container layout (`.env` alongside the scripts). |
| `data_gen/schema.py` | Step 1: `CREATE SCHEMA`/`CREATE TABLE` DDL for the 3 tables (PK-only on `purchase_transactions` — no FKs/secondary indexes yet, to keep bulk COPY fast). `--reset` drops the schema first. |
| `data_gen/pools.py` | Static value pools (categories, brands, statuses, channels, etc.) shared by dimension and fact generation — avoids per-row `Faker` calls in the hot path. |
| `data_gen/generate_dims.py` | Generates + COPY-loads `product_catalog` and `user_dimensions`, splitting row ranges across worker processes. Uses `Faker` since volume is low. |
| `data_gen/generate_facts.py` | Generates + COPY-loads `purchase_transactions`: calibrates bytes/row with a small measured batch, computes the remaining row count for the target size, fans out across worker processes (`multiprocessing.Process`), then adds FK constraints and secondary indexes (`user_id`, `product_id`, `order_date`) once loading is done. |
| `data_gen/generate.py` | CLI entry point (`argparse`) wiring `--table`, `--target-gb`, `--num-users`, `--num-products`, `--workers`. |
| `data_gen/pyproject.toml` / `uv.lock` | `uv`-managed project, deps: `psycopg2-binary`, `faker`, `numpy`. |
| `data_gen/Dockerfile` | Built with the **`postgres_sync` root** as build context (so it can bake in `.env`/`pm.token`), `COPY`s `data_gen/*.py` flat alongside them. `ENTRYPOINT ["uv", "run"]`, default `CMD ["generate.py", "--table", "all"]` — the service spec's `args` field overrides just the script/flags per step. |
| `data_gen/schema-spec.yaml` | Job service spec for step 1 (`args: schema.py --reset`), tiny resources. |
| `data_gen/service-spec.yaml` | Job service spec for step 2 (`args: generate.py --table all --target-gb 50`), sized resources (8-16 vCPU, 16-32Gi) + deployment commands as comments. |

### Local dry run (fast, small-scale smoke test)

```bash
cd example_apps/postgres_sync/data_gen
uv sync
uv run schema.py --reset
uv run generate.py --table all --target-gb 0.01 --num-users 50 --num-products 500
```

Postgres will reject connections from a local IP per the network policy
(same caveat as `check_env.py`) unless run inside SPCS — this dry run is
only useful for catching Python-level bugs before the full SPCS run.

### Running inside SPCS (two steps)

Uses the existing `<external_access_integration>` external access integration and
`<compute_pool>` compute pool (`CPU_X64_L`: 28 vCPU / 116 GiB per node) — no
new network rule needed.

```bash
cd example_apps/postgres_sync

# Build (must be amd64 for SPCS) — root as build context
docker build --platform linux/amd64 -f data_gen/Dockerfile -t postgres-data-gen:latest .

snow spcs image-registry login --connection "$SNOW_CONNECTION"
docker tag postgres-data-gen:latest \
  ${IMAGE_REGISTRY}${IMAGE_REPO}/postgres-data-gen:latest
docker push \
  ${IMAGE_REGISTRY}${IMAGE_REPO}/postgres-data-gen:latest
```

**Step 1 — create the schema** (run once; `schema-spec.yaml` passes
`--reset`, so re-running it drops and recreates the schema):

```sql
EXECUTE JOB SERVICE
  IN COMPUTE POOL <compute_pool>
  NAME = PG_SCHEMA_SETUP_JOB
  EXTERNAL_ACCESS_INTEGRATIONS = (<external_access_integration>)
  FROM SPECIFICATION_FILE = 'data_gen/schema-spec.yaml';

SELECT SYSTEM$GET_SERVICE_LOGS('<service_database>.<service_schema>.PG_SCHEMA_SETUP_JOB', 0, 'postgres-data-gen');
```

**Step 2 — load the data** (large, parallel, calibration-driven; expect a
long-running job — likely tens of millions of rows for `purchase_transactions`
at the default 50GB target):

```sql
EXECUTE JOB SERVICE
  IN COMPUTE POOL <compute_pool>
  NAME = PG_DATA_GEN_JOB
  EXTERNAL_ACCESS_INTEGRATIONS = (<external_access_integration>)
  FROM SPECIFICATION_FILE = 'data_gen/service-spec.yaml';

SELECT SYSTEM$GET_SERVICE_LOGS('<service_database>.<service_schema>.PG_DATA_GEN_JOB', 0, 'postgres-data-gen');
```

Clean up jobs after confirming (a job with the same name from a previous run
must be dropped before re-running):

```sql
DROP SERVICE IF EXISTS <service_database>.<service_schema>.PG_SCHEMA_SETUP_JOB;
DROP SERVICE IF EXISTS <service_database>.<service_schema>.PG_DATA_GEN_JOB;
```

### Verification queries

Run these via `psql`/any Postgres client connected to `pg_sync_demo`
(from inside SPCS, or via the check-connectivity job):

```sql
-- Schema step: exactly 3 tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'sync_demo';

-- Dimension row counts
SELECT count(*) FROM sync_demo.product_catalog;   -- expect 50000
SELECT count(*) FROM sync_demo.user_dimensions;    -- expect 1000

-- Fact table / total schema size vs. the 50GB target
SELECT pg_size_pretty(pg_total_relation_size('sync_demo.purchase_transactions'));
SELECT pg_size_pretty(sum(pg_total_relation_size(oid)))
FROM pg_class WHERE relnamespace = 'sync_demo'::regnamespace;

-- Referential integrity spot check (expect 0 for both)
SELECT count(*) FROM sync_demo.purchase_transactions t
LEFT JOIN sync_demo.user_dimensions u ON t.user_id = u.user_id
WHERE u.user_id IS NULL;

SELECT count(*) FROM sync_demo.purchase_transactions t
LEFT JOIN sync_demo.product_catalog p ON t.product_id = p.product_id
WHERE p.product_id IS NULL;
```

## `bi_dashboard/`: Postgres vs Snowflake

A 32-tile e-commerce BI dashboard that runs **the same tile definitions against
two engines** — the `sync_demo` Postgres schema and a clustered Snowflake
interactive-table layer over the managed mirror — so the latency difference is
visible per tile.

Live URL once deployed to SPCS (Snowflake SSO required):
(your SPCS ingress URL, from `snow spcs service list-endpoints`)

### Headline result

The interesting result is not "Postgres is slow" — it is *where it stops coping*.
Per-tile latency across the whole 32-tile dashboard, both sources measured from a
clean state with result caching off:

| Range | Rows in window | Postgres | Snowflake interactive |
|---|---|---|---|
| 1 hour | 7.8k | 0.25-0.6s | 1.4-2.0s |
| 6 hours | ~46k | 0.30-1.1s | 0.58-1.9s |
| 1 day | 184k | 0.27-3.8s | 1.2-1.8s |
| 7 days | ~1.3M | **6.9-45.2s** | 0.17-0.92s |
| 30 days | 5.7M | **times out (2 of 32 finish, ~50s)** | 0.9-2.9s |
| 90d / 1y / all | up to 134.6M | times out | ~1-3s |

**Postgres wins at an hour.** At 7.8k rows its indexed scan beats Snowflake, whose
per-query overhead dominates a tiny window. Anyone claiming Snowflake is
universally faster is not measuring small queries.

**The crossover sits between 1 day and 7 days**, and it is a cliff rather than a
slope. Every tile does `COUNT(DISTINCT order_id)` — the grain is the order line —
which must sort every matching row. 184k rows sort in ~13MB of memory; past
roughly a million the sort spills to disk and cost jumps by two orders of
magnitude. Snowflake stays flat at ~1-3s from 7.8k rows to 134.6M.

That flat line is the actual claim worth making: not that Postgres is bad, but that
an OLTP engine's analytical cost tracks the rows it must touch, while a columnar
engine with date clustering prunes to 33 of 768 partitions and barely notices.

Engine-level numbers on a 30-day window, isolated from the dashboard's
concurrency, matching the six [parity](#parity) queries:

| Query (30d window) | Postgres | Snowflake interactive | Ratio |
|---|---|---|---|
| Revenue + orders + units KPI | **319.18s** | 0.258s | ~1240x |
| Margin % | **94.70s** | 0.068s | ~1390x |
| Revenue by sales channel | **92.67s** | 0.084s | ~1100x |
| Top 10 categories (joins `DIM_PRODUCT`) | **90.42s** | 0.116s | ~780x |
| Return rate | **95.32s** | 0.066s | ~1440x |
| Avg ship lag by carrier | **94.70s** | 0.135s | ~700x |

Every Snowflake run above scanned 450-479 MB (`bytes_scanned > 0`), so none was a
result-cache hit. All six pairs match to the cent.

### Two things that distort the comparison if you get them wrong

**Tile concurrency.** The dashboard fires 32 queries at once and Cube's driver pool
defaults to **8**, so tiles queue four deep and the badge reports the wait rather
than the engine. A 1-day Postgres tile costs 0.28s at the engine but showed ~10s in
the browser. `CUBEJS_CONCURRENCY` and `CUBEJS_DS_*_DB_MAX_POOL` are set to 32 on
**both** sources (see `gen_env.py`); raising only one side would hand it a free win.

**Abandoned queries keep running.** Giving up client-side does not stop Postgres.
Before this was handled, visiting the 30-day range left ~30 multi-minute queries
churning, and the *next* page load starved behind them: a 6-hour range that returns
32/32 tiles in under 1.2s from a clean state instead failed on all 32. The Postgres
driver now sets `statement_timeout = 80s` (`cube/cube.js`), just past the proxy's
75s cutoff, so only already-abandoned queries get killed. After the fix the same
sequence completes — though the 6h tiles still land at ~64s while the 30d work
drains, then a subsequent load is back to normal.

The practical consequence for demoing: **go from short ranges to long ones.** After
a 30d or 90d visit, give Postgres a minute before reading small-range numbers.

### Result caching is disabled on both sides

The demo measures how each engine handles an analytical query, so no layer may
serve a previously computed answer. What is off, and how:

| Layer | How it is disabled |
|---|---|
| Snowflake result cache | `ALTER SESSION SET USE_CACHED_RESULT = FALSE`, applied per session by a `SnowflakeDriver` subclass in `cube/cube.js` |
| Cube result cache | Every request carries a unique always-true predicate (`cacheBuster` in `web/lib/cube.ts`) |
| Cube pre-aggregations | `pre_aggregations: {}` on every cube; `CUBEJS_SCHEDULED_REFRESH_DEFAULT=false` |
| Postgres | Nothing to disable — Postgres has no query result cache |

Two things worth being precise about:

- **Postgres has no equivalent of `USE_CACHED_RESULT`.** Its buffer pool and the OS
  page cache still warm up, and neither can be turned off per session. So the
  comparison is as level as the engines permit, not perfectly symmetric.
- **The interactive table's own serving layer is deliberately left on.** That is
  the feature under test, not result reuse.

Overriding the driver keeps `USE_CACHED_RESULT` scoped to Cube's sessions.
`ALTER USER ... SET USE_CACHED_RESULT = FALSE` would have been simpler but would
degrade every other session belonging to the same human user.

#### Cube Core has no switch for its result cache

Worth recording, because it cost real time: four documented-looking approaches
were each implemented and measured, and **none** of them worked. In every case
four identical requests produced exactly **one** SQL execution, with the repeats
answered in ~0.08s:

1. `renewQuery: true` on the request — renews the *refresh key*, does not bypass
   the cache. Cube's default key is a time bucket
   (`SELECT FLOOR(UNIX_TIMESTAMP() / 120)`), so repeats inside the window match.
2. A volatile per-cube `refresh_key` (`{ sql: () => 'SELECT random()' }`) — note it
   must be the function form (a bare string raises `Can't match args for`), and it
   is **not inherited through `extends`**, so it has to go on each concrete cube.
   Even then the cached result was still served.
3. `orchestratorOptions.queryCacheOptions.refreshKeyRenewalThreshold: 0`
   (`queryCacheOptions` at the top level is rejected as an invalid option).
4. `orchestratorOptions.skipExternalCacheAndQueue: true`.

What does work is making the request itself unique. The nonce rides on the fact
table's primary key as an always-true predicate (`transaction_id > <negative>`),
because Cube's cache key derives from the generated SQL and its params — a change
confined to the request JSON is not enough. Both sources get the identical
predicate: Snowflake resolves it from partition metadata, Postgres applies it as a
trivial filter on rows it is already reading.

Verify caching really is off by checking that queries scan bytes rather than
replaying a result:

```sql
SELECT start_time, total_elapsed_time/1000 AS secs, bytes_scanned,
       CASE WHEN bytes_scanned = 0 AND rows_produced > 0
            THEN 'RESULT_CACHE_HIT' ELSE 'EXECUTED' END AS verdict
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_text ILIKE '%FCT_TRANSACTIONS%'
  AND start_time > DATEADD('hour', -2, CURRENT_TIMESTAMP())
ORDER BY start_time DESC;
```

A healthy row reads `EXECUTED` with `bytes_scanned` around 450 MB. A
`RESULT_CACHE_HIT` at ~0.04s means something regressed.

### Architecture

```
Postgres pg_sync_demo (sync_demo)
   │  managed mirror
   ▼
<source_database>.SYNC_DEMO           read-only, application-owned
   │  dynamic interactive table, TARGET_LAG = 1 hour, refresh on ADAPTIVE
   ▼
<bi_database>.BI               FCT_TRANSACTIONS / DIM_PRODUCT / DIM_USER
   │                               served by warehouse INTERACTIVE
   ▼
Cube Core  ── dataSource sf ───────┘
           └─ dataSource pg ──────► Postgres directly (via <external_access_integration>)
   │
   ▼
Next.js dashboard, 32 tiles, latency badge per tile
```

Both containers run in one SPCS service, so the web app reaches Cube on
`localhost:4000` and only the web endpoint is public — Cube holds the Snowflake
PAT and the Postgres password.

### The Snowflake layer

**Already have the data in Snowflake?** Skip this whole section. Point
`bi_database`, `bi_schema` and the three `*_table` keys in `.env` at your tables and
the dashboard works — interactive tables are an optimisation, not a requirement.
See [Do I need interactive tables?](#do-i-need-interactive-tables).

What follows is how this repo builds the Snowflake side from a Snowflake Postgres
mirror.

If you are using Snowflake Postgres, the mirror database is **read-only and
application-owned** (`SHOW DATABASES` reports `owner = SNOWFLAKE`,
`owner_role_type = APPLICATION`). Not even ACCOUNTADMIN can `CREATE SCHEMA` in it,
so the BI layer has to live in a **sibling database** — `<bi_database>.BI` here —
built as dynamic interactive tables over the mirror. If your source is an ordinary
Snowflake table instead, no sibling database is needed.

| Table | Rows | Clustering key |
|---|---|---|
| `FCT_TRANSACTIONS` | 134,584,619 | `(TO_DATE(ORDER_DATE))` |
| `DIM_PRODUCT` | 50,000 | `(CATEGORY, BRAND)` |
| `DIM_USER` | 1,000 | `(COUNTRY, LOYALTY_TIER)` |

`order_date` is the only column that appears in a `WHERE` predicate in all 32
tiles (it is the global time picker). Everything else — `sales_channel`,
`category`, `brand`, `loyalty_tier` — appears only in `GROUP BY`, which is a weak
clustering signal, so the fact key is date-only. The dimension keys are
effectively cosmetic at 50k and 1k rows.

Measured on a 30-day window: **33 of 768 partitions scanned (95.7% pruned)**,
`average_depth` 1.84.

```sql
-- Rebuild with a different key (e.g. if cross-filtering makes sales_channel a
-- WHERE predicate). CREATE OR REPLACE is atomic, but drops the warehouse
-- association with the old object -- skip the re-add and every query silently
-- falls back to non-interactive paths.
CREATE OR REPLACE INTERACTIVE TABLE <bi_database>.BI.FCT_TRANSACTIONS
  CLUSTER BY (SALES_CHANNEL, TO_DATE(ORDER_DATE))
  TARGET_LAG = '1 hour' WAREHOUSE = <warehouse>
AS SELECT <explicit column list> FROM <source_database>.SYNC_DEMO.PURCHASE_TRANSACTIONS;

ALTER WAREHOUSE <interactive_warehouse> ADD TABLES (<bi_database>.BI.FCT_TRANSACTIONS);

SHOW TABLES LIKE 'FCT_TRANSACTIONS' IN SCHEMA <bi_database>.BI;  -- cluster_by, is_interactive
SELECT SYSTEM$CLUSTERING_INFORMATION('<bi_database>.BI.FCT_TRANSACTIONS');
```

The interactive warehouse is X-Small with `max_cluster_count = 4` and
`FALLBACK_WAREHOUSE = <warehouse>`, so any query exceeding the hard 5-second
interactive timeout is transparently retried rather than failing.

### Files

| File | Purpose |
|---|---|
| `config.py` | Loads and validates the TOML `.env`; shared by every script here. Applies defaults, checks required keys, and refuses to run on unfilled `<placeholders>`. |
| `gen_env.py` | Renders `.env.cube` and `cube/model/cubes.js` from `.env`. Run it after any config change. |
| `render_spec.py` | Renders the SPCS spec, or a Kubernetes manifest with `--target k8s`, inlining credentials at deploy time. |
| `cube/cube.js` | Cube config: per-source `dbType`, custom drivers, caching behaviour. |
| `cube/cubes.template.js` | **The data model** — three base cubes plus two concrete trios (`Pg*`, `Sf*`) via `extends`. Edit this, not the generated `cube/model/cubes.js`. |
| `web/lib/cube.ts` | `db` → cube-prefix resolution, range presets, global `order_date` injection, query execution, formatting. |
| `web/app/api/cube/[...path]/route.ts` | Server-side Cube proxy; keeps `CUBEJS_API_SECRET` off the client and handles Cube's `Continue wait` polling. |
| `web/components/Tile.tsx` | Per-tile loading/error boundary and the latency badge. |
| `web/app/page.tsx` | All 32 tile definitions. |
| `parity/` | Standalone jobs: `check_parity.py` compares aggregates and times them; `diagnose_slow.py` dumps `EXPLAIN ANALYZE` plans. |
| `.env.cube.example`, `spcs-spec.example.yaml`, `parity/spec.example.yaml` | Reference copies of the generated files, with placeholder values. |

### Deploying

All three paths use the same two images. Only the orchestration differs, and
nothing in the images is environment-specific.

#### Locally, with Docker

The quickest way to see it, and enough if your Postgres is reachable from your
machine:

```bash
cd bi_dashboard
uv run gen_env.py
docker compose --env-file .env.cube up --build
# dashboard on http://localhost:3000, Cube on http://localhost:4000
```

`--env-file` is required: compose's `${...}` substitution (used for the
`NEXT_PUBLIC_*` build args) reads only that file, whereas `env_file:` merely
populates the running container. Without it the dashboard falls back to its default
date range.

#### Snowpark Container Services

```bash
cd bi_dashboard
uv run gen_env.py
uv run render_spec.py

# Pull the deploy identifiers straight out of .env so nothing is retyped.
eval "$(uv run python -c "
import config
c = config.load()
for k in ('image_registry','image_repo','compute_pool','external_access_integration',
          'service_database','service_schema','snow_connection'):
    print(f'{k.upper()}={c[k]!r}')
")"
REG="${IMAGE_REGISTRY}${IMAGE_REPO}"

snow spcs image-registry login --connection "$SNOW_CONNECTION"
docker build --platform linux/amd64 -t "$REG/bi-cube:latest" ./cube
docker build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_DATA_START="$(grep ^NEXT_PUBLIC_DATA_START= .env.cube | cut -d= -f2)" \
  --build-arg NEXT_PUBLIC_DATA_END="$(grep ^NEXT_PUBLIC_DATA_END= .env.cube | cut -d= -f2)" \
  --build-arg NEXT_PUBLIC_DATA_END_TS="$(grep ^NEXT_PUBLIC_DATA_END_TS= .env.cube | cut -d= -f2)" \
  -t "$REG/bi-web:latest" ./web

# Check each push explicitly. A registry token expiring mid-deploy makes `docker
# push` fail while a following `&&` chain (or a pipe into `tail`) happily proceeds
# to redeploy the OLD image -- silently, and it looks like success.
for img in bi-cube bi-web; do
  docker push "${REG}/${img}:latest" || { echo "PUSH FAILED: $img"; break; }
done

snow spcs service create BI_DASHBOARD \
  --compute-pool "$COMPUTE_POOL" \
  --spec-path .spcs-spec.rendered.yaml \
  --eai-name "$EXTERNAL_ACCESS_INTEGRATION" \
  --database "$SERVICE_DATABASE" --schema "$SERVICE_SCHEMA" --connection "$SNOW_CONNECTION"

# subsequent deploys
snow spcs service upgrade BI_DASHBOARD --spec-path .spcs-spec.rendered.yaml \
  --database "$SERVICE_DATABASE" --schema "$SERVICE_SCHEMA" --connection "$SNOW_CONNECTION"

snow spcs service list-endpoints BI_DASHBOARD \
  --database "$SERVICE_DATABASE" --schema "$SERVICE_SCHEMA" --connection "$SNOW_CONNECTION"
```

`--eai-name` is the flag name — not `--external-access-integrations`. Drop it
entirely if your Postgres needs no external access integration.

SPCS public endpoints sit behind Snowflake SSO, so the dashboard is authenticated
for you. Note the ingress also **hard-kills requests at 90 seconds**, which is why
the proxy gives up at 75s.

#### Kubernetes (EKS, GKE, AKS)

```bash
cd bi_dashboard
uv run gen_env.py
uv run render_spec.py --target k8s     # -> .k8s.rendered.yaml

# Any registry your cluster can pull from; ECR shown here.
REG=<aws_account>.dkr.ecr.<region>.amazonaws.com
docker build --platform linux/amd64 -t "$REG/bi-cube:latest" ./cube
docker build --platform linux/amd64 -t "$REG/bi-web:latest" ./web   # + NEXT_PUBLIC_* build args
docker push "$REG/bi-cube:latest" && docker push "$REG/bi-web:latest"

kubectl apply -f .k8s.rendered.yaml
kubectl get svc bi-dashboard -w        # wait for the LoadBalancer address
```

Set `image_registry`/`image_repo` in `.env` to your registry so the rendered
manifest points at the right images.

Two differences from SPCS worth planning for:

- **Nothing authenticates users.** SPCS gives you SSO; a bare `LoadBalancer` gives
  you an open dashboard. Put an Ingress with OIDC, or a private LB, in front of it.
- **No 90-second ingress timeout**, so you can raise `MAX_WAIT_MS` in
  `web/app/api/cube/[...path]/route.ts` (and `statement_timeout` in `cube/cube.js`)
  if you want long Postgres queries to complete rather than being abandoned.

The manifest keeps both containers in one Pod so the web app still reaches Cube on
`localhost`, matching the SPCS layout. Splitting them into two Deployments works
too — point `CUBE_API_URL` at the Cube Service.

### Parity

`parity/check_parity.py` prints both the values and the timings. Run it locally if
your Postgres is reachable:

```bash
cd bi_dashboard && uv run parity/check_parity.py
```

With Snowflake Postgres it has to run inside the compute pool the network policy
admits, so it ships as a one-off job:

```bash
cd bi_dashboard/parity && cp ../../.env . && cp ../config.py .
REG=${IMAGE_REGISTRY}${IMAGE_REPO}
docker build --platform linux/amd64 -t $REG/bi-parity:latest . && docker push $REG/bi-parity:latest

snow sql -c "$SNOW_CONNECTION" -q "EXECUTE JOB SERVICE IN COMPUTE POOL <compute_pool>
  NAME = <service_database>.<service_schema>.BI_PARITY_JOB
  EXTERNAL_ACCESS_INTEGRATIONS = (<external_access_integration>) ASYNC = TRUE
  FROM SPECIFICATION \$\$
spec:
  containers:
    - name: parity
      image: ${IMAGE_REPO}/bi-parity:latest
\$\$"

snow sql -c "$SNOW_CONNECTION" -q "SELECT SYSTEM\$GET_SERVICE_LOGS('<service_database>.<service_schema>.BI_PARITY_JOB', 0, 'parity', 400)"
```

All six queries matched exactly, e.g. revenue `3884542469.91` on both, orders
`5473692` on both, margin % `27.6998088893318195` vs `27.69980889`.

### Gotchas

**Cube's transpiler needs static cube names.** Member references (`${revenue}`)
and cube references in joins are resolved by scanning the *string literal*
passed to `cube()`. A generated name — `cube(T, {...})` inside a `forEach` — makes
every `${member}` fail with `revenue is not defined`. Hence the model shares
definitions via `extends` on literally-named cubes rather than a loop, and the
one per-dialect block (the ship/delivery lag measures, which have no portable
timestamp-difference spelling) avoids member references entirely.

**`CUBEJS_DATASOURCES` is mandatory and must include `default`.** The decorated
`CUBEJS_DS_<NAME>_DB_*` vars are ignored unless the source is declared, and
omitting `default` raises `The default data source is missing in the declared
CUBEJS_DATASOURCES` — even when no cube uses it. Also give every cube an explicit
`data_source`, including `public: false` base cubes: Cube builds a dialect per
distinct source it sees, and a base cube without one yields `Unsupported db type:
undefined`.

**Do not define `dbType` in `cube.js`.** Even as a function of `dataSource`, it
shadows the env-var resolution and every query fails with `Unsupported db type:
undefined`.

**Cube's Snowflake driver does accept a PAT.** `CUBEJS_DS_SF_DB_SNOWFLAKE_
AUTHENTICATOR=PROGRAMMATIC_ACCESS_TOKEN` with the token as `..._DB_PASS` works;
no key-pair fallback was needed.

**Interactive tables reject `ARRAY` columns.** `product_catalog.tags` is
`ARRAY(VARCHAR)` and fails with `Unsupported data type`. It is serialized with
`ARRAY_TO_STRING(TAGS::ARRAY, ',')` — note the `::ARRAY` cast, since
`ARRAY_TO_STRING` and `TO_JSON` both reject the *structured* array type directly.

**Grant the interactive tables explicitly.** `GRANT OWNERSHIP ON ALL TABLES IN
SCHEMA` reports `0 objects affected` for interactive tables — grant each by name,
or Cube (connecting as `SYSADMIN`) gets `does not exist or not authorized`.

**Recharts discovers axes from direct children.** Wrapping `<XAxis>`/`<YAxis>` in
a `<>...</>` fragment hides them. Vertical layout silently falls back to default
axes, but horizontal bar charts collapse to a single mispositioned bar with no
axes — 6 tiles rendered as empty grids until the fragment was removed.

**`ResponsiveContainer` needs a definite parent height.** `.tile-body` must not be
`flex: 1`: that resolves `flex-basis` to 0, collapsing the inline height and
rendering every chart blank.

**The SPCS ingress cuts requests off at 90s** with a plain-text
`upstream request timeout` body, which a client doing `JSON.parse` reports as
`Unexpected token 'u'`. The proxy gives up at 75s and always returns JSON, and
each tile additionally bounds its own wall clock at 90s — with 32 concurrent
long-lived POSTs, the proxy's own fetch can otherwise sit waiting for a socket in
the per-origin pool and surface its deadline minutes late.

**Cube needs `dbType` and `driverFactory` introduced together, or neither.**
Defining `dbType` alone shadows env-based driver resolution and every query fails
with `Unsupported db type: undefined`. But a `driverFactory` that returns driver
*instances* stops Cube inferring a type per data source, so it falls back to the
default source's dialect — Snowflake SQL gets sent to Postgres and every pg tile
fails instantly with `syntax error at or near "::"` (from `::timestamp_tz`). With
both defined, the factory supplies the driver and `dbType` supplies the dialect.
Verify with the `/cubejs-api/v1/sql` endpoint, which compiles without executing —
Postgres should show `$1::timestamptz`, Snowflake `?::timestamp_tz`.

**`driverFactory` must return the same kind for every data source.** Cube fixes
`driverFactoryType` on the first call, so mixing a driver instance for one source
with a `{ type: 'postgres' }` config for another fails with "must return either
BaseDriver or DriverConfig". Passing `{ dataSource }` is enough — every driver reads
its own `CUBEJS_DS_<NAME>_DB_*` vars, so no credentials need restating.

**A one-day range needs sub-day granularity.** At `day` granularity a one-day window
is a single point, and the trend tiles draw lines with `dot={false}`, so they render
as empty plots. Ranges map to the finest readable grain (`1h`→minute,
`6h`/`1d`→hour). The sub-day presets also anchor on the data's exact end timestamp
(`2026-09-13T00:43:00`), not midnight — the last day is only populated to 00:43, so
a window ending at midnight lands in an empty tail.

**`TABLE_QUERY_PRUNING_HISTORY` lags 4-6 hours.** An empty result means "too
early", not "good". Use `SYSTEM$CLUSTERING_INFORMATION` and
`GET_QUERY_OPERATOR_STATS(<query_id>)` for immediate pruning evidence.
