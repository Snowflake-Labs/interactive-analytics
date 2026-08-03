# Benchmark API + Locust on Snowpark Container Services

This folder contains everything needed to run the benchmark API server
**and** the Locust load test entirely inside Snowflake, with public
ingress URLs you can hit from your laptop.

## Topology

Three services split across two independent compute pools:

```
DASHBOARD_COMPUTE_POOL                LOCUST_COMPUTE_POOL
┌──────────────────────────┐          ┌────────────────────────────────────────┐
│                          │          │                                        │
│  DASHBOARD (benchmark    │          │  DASHBOARD_API_LOCUST (benchmark       │
│  API image)              │          │  API image, same server)               │
│   - serves /api/run/*    │          │                                        │
│   - serves /api/health   │          │             ▲                          │
│                          │          │             │  http://dashboard-api-   │
│                          │          │             │        locust:3000       │
│                          │          │  DASHBOARD_LOCUST (locust image)       │
│                          │          │   - generates load                     │
└──────────────────────────┘          └────────────────────────────────────────┘
       ▲                                     ▲
       │ local locust / curl (public)        │ locust web UI (public)
```

The API server that handles benchmark requests and the API server that
Locust hits are the **same image running as two separate SPCS services on
different compute pools**. They cannot compete for CPU or memory, so the load
test never becomes a bottleneck for direct API usage.

```
spcs/
├── config.env           # all knobs (connection, names, resources, locust params)
├── _lib.sh              # shared helpers sourced by every script
├── build-and-push.sh    # docker build + push both images
├── deploy.sh            # full SPCS deploy (prerequisites, build, push, create services)
├── list.sh              # list all SPCS resources (registries, repos, services, compute pools)
├── update.sh            # rebuild + ALTER SERVICE (preserves ingress URLs)
├── status.sh            # service state + ingress URLs
├── logs.sh              # tail container logs
├── teardown.sh          # drop services, compute pools, and image repo
├── dashboard/           # benchmark API image (Dockerfile, entrypoint, .dockerignore)
├── locust/              # locust image (Dockerfile, entrypoint, .dockerignore)
└── specs/               # SPCS service YAML specs
```

All SQL is generated inline by the shell scripts from `config.env`; there
are no separate SQL files to keep in sync.

## Prerequisites

- Docker Desktop (or any local buildx-capable daemon).
- `snow` CLI configured with the connection listed in `config.env` (`PM` by default).
- The connection's role must be able to `CREATE COMPUTE POOL`, `CREATE IMAGE
  REPOSITORY`, and `CREATE SERVICE`. `ACCOUNTADMIN` works.
- The API's runtime role (`DASHBOARD_ROLE`) needs `USAGE` on the benchmark
  warehouses (`${SOLUTION_NAME}_BENCH_WH_*`) and `SELECT` on the
  `${SOLUTION_NAME}_BENCH_DB.TPCH_SF*_*` schemas.

## Deploying

```bash
cd spcs
./deploy.sh
```

`deploy.sh` will:

1. Create `DB.SCHEMA`, **two independent compute pools** (one for the
   API, one for locust), and the image repository (idempotent).
2. Build and push both images to the SPCS image repo.
3. `CREATE SERVICE` for:
   - `DASHBOARD_SERVICE` on `DASHBOARD_COMPUTE_POOL` — the benchmark API.
   - `LOCUST_API_SERVICE` on `LOCUST_COMPUTE_POOL` — an isolated copy of the
     API that Locust hits (never contends with direct usage).
   - `LOCUST_SERVICE` on `LOCUST_COMPUTE_POOL` — the Locust load generator.
   Or `ALTER SERVICE` if they already exist.
4. Poll `SYSTEM$GET_SERVICE_STATUS` until all three report `READY`.
5. Print the public ingress URLs.

## Naming convention

All object names are derived from `SOLUTION_NAME` (set in `benchmark/.env`).
With `SOLUTION_NAME=DMTESTTPCH`, the objects created are:

| Object | Name |
|--------|------|
| Database | `DMTESTTPCH_BENCH_DB` |
| Schema | `SPCS` |
| Image repository | `DMTESTTPCH_BENCH_IMAGES` |
| Dashboard compute pool | `DMTESTTPCH_BENCH_DASHBOARD_POOL` |
| Locust compute pool | `DMTESTTPCH_BENCH_LOCUST_POOL` |
| Dashboard service | `DASHBOARD` |
| Locust API service | `DASHBOARD_API_LOCUST` |
| Locust service | `DASHBOARD_LOCUST` |

Change `SOLUTION_NAME` in `benchmark/.env` to deploy multiple independent
instances in the same account.

## Iterating

Edit the app code (or `spcs/specs/*.yaml`) and run:

```
./update.sh
```

`update.sh` rebuilds, pushes, and `ALTER SERVICE`s in place, so the public
ingress URLs stay the same.

## Auth model inside the container

Every SPCS container gets:

- `SNOWFLAKE_HOST`, `SNOWFLAKE_ACCOUNT` env vars.
- An OAuth token file at `/snowflake/session/token` scoped to the service's
  owner role.

`dashboard/entrypoint.sh` writes a small `~/.snowflake/connections.toml`
pointing at that token file and sets `CONNECTION_NAME=spcs`. The unchanged
`api/server.py` picks it up via its normal `connections.toml` path.

## Running Locust headlessly

Web UI mode is the default so you can start/stop runs from the browser. For a
one-shot timed run, set in `config.env`:

```
LOCUST_HEADLESS=1
LOCUST_RUN_TIME=5m
LOCUST_USERS=10
LOCUST_SPAWN=5
```

Then `./update.sh` (or `./deploy.sh` on a fresh deploy). The container will
exit when the run completes; check results with `./logs.sh locust`.

## Common operations

```
./deploy.sh                 # full SPCS deploy (idempotent)
./list.sh                   # list all SPCS resources in the schema
./status.sh                 # show state + endpoints for all three services
./status.sh --urls-only     # just the ingress URLs
./logs.sh dashboard         # benchmark API logs
./logs.sh locust-api        # isolated API server that locust hits
./logs.sh locust            # locust load-generator logs
./teardown.sh               # drop services, compute pools, and image repo
```

## Granting another role access to the ingress URLs

By default only the service owner role can hit the public ingress URLs. To let
another role in:

```sql
USE ROLE ACCOUNTADMIN;
GRANT USAGE ON DATABASE <SOLUTION_NAME>_BENCH_DB TO ROLE <consumer_role>;
GRANT USAGE ON SCHEMA <SOLUTION_NAME>_BENCH_DB.SPCS TO ROLE <consumer_role>;
GRANT SERVICE ROLE <SOLUTION_NAME>_BENCH_DB.SPCS.DASHBOARD!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
GRANT SERVICE ROLE <SOLUTION_NAME>_BENCH_DB.SPCS.DASHBOARD_API_LOCUST!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
GRANT SERVICE ROLE <SOLUTION_NAME>_BENCH_DB.SPCS.DASHBOARD_LOCUST!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
```

## Troubleshooting

- `snow spcs image-registry login` errors: re-run manually with
  `--connection $CONNECTION --role $ROLE`; tokens expire after ~1h.
- Service stuck in `PENDING`: `./logs.sh dashboard` (or `locust-api` /
  `locust`) — usually a missing grant on the runtime warehouse.
- Locust web UI shows "0 requests" or logs `gaierror(-2, 'Name or service not known')`:
  the `LOCUST_HOST` DNS label is wrong. **SPCS converts underscores in the
  service name to hyphens in the DNS name** (e.g. `DASHBOARD_API_LOCUST` →
  `dashboard-api-locust`). Both services must live in the same schema.
