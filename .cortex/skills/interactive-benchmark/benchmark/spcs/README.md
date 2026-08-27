# Benchmark API + Locust on Snowpark Container Services

This folder contains everything needed to run the benchmark API server
**and** the Locust load test entirely inside Snowflake, with public
ingress URLs you can hit from your laptop.

## Topology

Two services on two independent compute pools:

```
API_COMPUTE_POOL                      LOCUST_COMPUTE_POOL
┌──────────────────────────┐          ┌────────────────────────────────────────┐
│                          │          │                                        │
│  BENCHMARK_API           │          │  BENCHMARK_LOCUST (locust image)       │
│  (benchmark API image)   │          │   - generates load                     │
│   - serves /api/run/*    │◀─────────│   - targets http://benchmark-api:3000  │
│   - serves /api/health   │          │                                        │
│                          │          │                                        │
└──────────────────────────┘          └────────────────────────────────────────┘
       ▲                                     ▲
       │ curl (public ingress)               │ locust REST API (public ingress)
```

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
├── api/                 # benchmark API image (Dockerfile, entrypoint, .dockerignore)
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
- The API's runtime role (`API_ROLE`) needs `USAGE` on the interactive
  warehouse and `SELECT` on the interactive schema.

## Deploying

```bash
cd spcs
./deploy.sh
```

`deploy.sh` will:

1. Create `DB.SCHEMA`, **two independent compute pools** (one for the
   API, one for Locust), and the image repository (idempotent).
2. Build and push both images to the SPCS image repo.
3. `CREATE SERVICE` for:
   - `API_SERVICE` on `API_COMPUTE_POOL` — the benchmark API.
   - `LOCUST_SERVICE` on `LOCUST_COMPUTE_POOL` — the Locust load generator.
   Or `ALTER SERVICE` if they already exist.
4. Poll `SYSTEM$GET_SERVICE_STATUS` until both report `READY`.
5. Print the public ingress URLs.

## Naming convention

All object names are derived from `SOLUTION_NAME` (set in `benchmark/.env`).
With `SOLUTION_NAME=IW_TPCH`, the objects created are:

| Object | Name |
|--------|------|
| Database | `IW_TPCH_BENCH_DB` |
| Schema | `SPCS` |
| Image repository | `IW_TPCH_BENCH_IMAGES` |
| API compute pool | `IW_TPCH_BENCH_API_POOL` |
| Locust compute pool | `IW_TPCH_BENCH_LOCUST_POOL` |
| API service | `BENCHMARK_API` |
| Locust service | `BENCHMARK_LOCUST` |

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

`api/entrypoint.sh` writes a small `~/.snowflake/connections.toml`
pointing at that token file and sets `CONNECTION_NAME=spcs`. The unchanged
`api/server.py` picks it up via its normal `connections.toml` path.

## Running Locust via REST API

The Locust service exposes a public ingress URL. Control it via curl:

```bash
# Start a test
curl -s -X POST <LOCUST_URL>/swarm \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'user_count=10&spawn_rate=5&host=http://benchmark-api:3000'

# Check stats
curl -s <LOCUST_URL>/stats/requests

# Stop the test
curl -s <LOCUST_URL>/stop
```

## Common operations

```
./deploy.sh                 # full SPCS deploy (idempotent)
./list.sh                   # list all SPCS resources in the schema
./status.sh                 # show state + endpoints for both services
./status.sh --urls-only     # just the ingress URLs
./logs.sh api               # benchmark API logs
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
GRANT SERVICE ROLE <SOLUTION_NAME>_BENCH_DB.SPCS.BENCHMARK_API!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
GRANT SERVICE ROLE <SOLUTION_NAME>_BENCH_DB.SPCS.BENCHMARK_LOCUST!ALL_ENDPOINTS_USAGE
  TO ROLE <consumer_role>;
```

## Troubleshooting

- `snow spcs image-registry login` errors: re-run manually with
  `--connection $CONNECTION --role $ROLE`; tokens expire after ~1h.
- Service stuck in `PENDING`: `./logs.sh api` (or `locust`)
  — usually a missing grant on the runtime warehouse.
- Locust shows "0 requests" or logs `gaierror(-2, 'Name or service not known')`:
  the `LOCUST_HOST` DNS label is wrong. **SPCS converts underscores in the
  service name to hyphens in the DNS name** (e.g. `BENCHMARK_API` →
  `benchmark-api`). Both services must live in the same schema.
