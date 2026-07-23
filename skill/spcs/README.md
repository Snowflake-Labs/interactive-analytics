# Dashboard + Locust on Snowpark Container Services

This folder contains everything needed to run the TPC-H benchmark dashboard
**and** the Locust load test against it entirely inside Snowflake, with public
ingress URLs you can hit from your laptop.

## Topology

Three services split across two independent compute pools:

```
DASHBOARD_COMPUTE_POOL                LOCUST_COMPUTE_POOL
┌──────────────────────────┐          ┌────────────────────────────────────────┐
│                          │          │                                        │
│  DASHBOARD (dashboard    │          │  DASHBOARD_API_LOCUST (dashboard       │
│  image)                  │          │  image, same /api server)              │
│   - serves UI            │          │                                        │
│   - serves /api/* for    │          │             ▲                          │
│     the browser          │          │             │  http://dashboard_api_   │
│                          │          │             │        locust:3000       │
│                          │          │  DASHBOARD_LOCUST (locust image)       │
│                          │          │   - generates load                     │
└──────────────────────────┘          └────────────────────────────────────────┘
       ▲                                     ▲
       │ user browser (public)               │ locust web UI (public)
```

The API server that services the browser dashboard and the API server that
Locust hits are the **same image running as two separate SPCS services on
different compute pools**. They cannot compete for CPU or memory, so the load
test never becomes a bottleneck for the interactive dashboard experience.
This makes it possible to demonstrate that Interactive Tables sustain much
higher API concurrency than standard tables without the API layer confounding
the results.

```
spcs/
├── config.env           # all knobs (connection, names, resources, locust params)
├── _lib.sh              # shared helpers sourced by every script
├── build-and-push.sh    # docker build + push both images
├── deploy.sh            # end-to-end: setup + build/push + create services
├── update.sh            # rebuild + ALTER SERVICE (preserves ingress URLs)
├── status.sh            # service state + ingress URLs
├── logs.sh              # tail container logs
├── teardown.sh          # drop services, compute pools, and image repo
├── dashboard/           # dashboard image (Dockerfile, entrypoint, .dockerignore)
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
- The dashboard's runtime role (`DASHBOARD_ROLE`) needs `USAGE` on the TPC-H
  warehouses (`IW_TPCH_BENCH_WH_*`, `TPCH_BENCH_WH_*`) and `SELECT` on the
  `IW_TPCH_BENCH.TPCH_SF*_*` schemas.

## First-time deploy

```
cd spcs
./deploy.sh
```

`deploy.sh` will:

1. Create `DB.SCHEMA`, **two independent compute pools** (one for the
   dashboard, one for locust), and the image repository (idempotent).
2. Build and push both images to the SPCS image repo.
3. `CREATE SERVICE` for:
   - `DASHBOARD_SERVICE` on `DASHBOARD_COMPUTE_POOL` — the API server that
     answers browser dashboard requests.
   - `LOCUST_API_SERVICE` on `LOCUST_COMPUTE_POOL` — an isolated copy of the
     same API server that Locust hits (never contends with the dashboard).
   - `LOCUST_SERVICE` on `LOCUST_COMPUTE_POOL` — the Locust load generator.
   Or `ALTER SERVICE` if they already exist.
4. Poll `SYSTEM$GET_SERVICE_STATUS` until all three report `READY`.
5. Print the public ingress URLs.

Open the dashboard URL in your browser — Snowflake will prompt for login on
first visit, then the dashboard loads and starts calling `/api/*` on the
dashboard-pool API server.

Open the locust URL to drive load from the Locust web UI. Its target host is
pre-set via SPCS internal DNS to the isolated API server on the locust pool
(`http://dashboard_api_locust:3000`), so the load never hits the same API
process the browser uses.

## Compute pools

The dashboard and locust services run on **completely independent** compute
pools so they can be sized and scaled without affecting each other. Both pools
are declared in `config.env`:

```
DASHBOARD_COMPUTE_POOL=IW_DASHBOARD_POOL
DASHBOARD_INSTANCE_FAMILY=CPU_X64_M
DASHBOARD_MIN_NODES=1
DASHBOARD_MAX_NODES=2

LOCUST_COMPUTE_POOL=IW_DASHBOARD_LOCUST_POOL
LOCUST_INSTANCE_FAMILY=CPU_X64_M
LOCUST_MIN_NODES=1
LOCUST_MAX_NODES=2
```

`INSTANCE_FAMILY` is immutable after pool creation. To change it, run
`./teardown.sh` then `./deploy.sh`. Similarly, the compute pool of an existing
service cannot be changed via `ALTER SERVICE` — if you're migrating a deployment
that previously ran both services on the same pool, run `./teardown.sh` before
`./deploy.sh`.

## Iterating

Edit the app code (or `spcs/specs/*.yaml`) and run:

```
./update.sh
```

`update.sh` rebuilds, pushes, and `ALTER SERVICE`s in place, so the public
ingress URLs stay the same.

Just want to tweak service resources / env without a rebuild?  Edit the yaml
under `specs/` and:

```
./update.sh   # will still rebuild; skip build-and-push manually if you prefer
```

## Auth model inside the container

Every SPCS container gets:

- `SNOWFLAKE_HOST`, `SNOWFLAKE_ACCOUNT` env vars.
- An OAuth token file at `/snowflake/session/token` scoped to the service's
  owner role.

`dashboard/entrypoint.sh` writes a small `~/.snowflake/connections.toml`
pointing at that token file and sets `CONNECTION_NAME=spcs`.  The unchanged
`api/server.py` picks it up via its normal `connections.toml` path.

## Running Locust headlessly

Web UI mode is the default so you can start/stop runs from the browser. For a
one-shot timed run (matches `run-users.sh`), set in `config.env`:

```
LOCUST_HEADLESS=1
LOCUST_RUN_TIME=5m
LOCUST_USERS=5
LOCUST_SPAWN=5
```

Then `./update.sh` (or `./deploy.sh` on a fresh deploy). The container will
exit when the run completes; check results with `./logs.sh locust`.

## Common operations

```
./status.sh                 # show state + endpoints for all three services
./status.sh --urls-only     # just the ingress URLs
./logs.sh dashboard         # dashboard API (browser-facing) logs
./logs.sh locust-api        # isolated API server that locust hits
./logs.sh locust            # locust load-generator logs
./teardown.sh               # drop services, compute pools, and image repo
```

## Granting another role access to the ingress URLs

By default only the service owner role can hit the public ingress URLs. To let
another role in:

```sql
USE ROLE ACCOUNTADMIN;
GRANT USAGE ON DATABASE IW_TPCH_BENCH TO ROLE <consumer_role>;
GRANT USAGE ON SCHEMA IW_TPCH_BENCH.SPCS TO ROLE <consumer_role>;
GRANT SERVICE ROLE IW_TPCH_BENCH.SPCS.DASHBOARD!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
GRANT SERVICE ROLE IW_TPCH_BENCH.SPCS.DASHBOARD_API_LOCUST!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
GRANT SERVICE ROLE IW_TPCH_BENCH.SPCS.DASHBOARD_LOCUST!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
```

## Troubleshooting

- `snow spcs image-registry login` errors: re-run it manually with
  `--connection $CONNECTION --role $ROLE`; tokens expire after ~1h.
- Service stuck in `PENDING`: `./logs.sh dashboard` (or `locust-api` /
  `locust`) — usually a missing grant on the runtime warehouse or a Snowflake
  connection error at startup.
- Dashboard shows connection errors after login: confirm `DASHBOARD_ROLE` has
  access to the TPC-H warehouses and schemas listed above.
- Locust web UI shows "0 requests" or logs `gaierror(-2, 'Name or service not known')`:
  the `LOCUST_HOST` DNS label is wrong. **SPCS converts underscores in the
  service name to hyphens in the DNS name** (Snowflake docs example: service
  `ECHO_SERVICE` → DNS `echo-service.<...>.svc.spcs.internal`). So
  `DASHBOARD_API_LOCUST` must be referenced as `http://dashboard-api-locust:3000`.
  Both services must also live in the same schema (they do by design in
  `config.env`).
