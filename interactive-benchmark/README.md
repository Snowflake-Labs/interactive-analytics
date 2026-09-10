# Interactive Benchmark Skill

A [Cortex Code (CoCo)](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code) skill that benchmarks Snowflake **Interactive Warehouse** performance under concurrent load using any user-provided SQL query. The skill automates the entire workflow — from creating interactive tables to deploying the benchmark infrastructure and generating reports — through conversational prompts.

To use it, open this project in Cortex Code and describe what you want to benchmark. See [GETTING-STARTED.md](GETTING-STARTED.md) for a step-by-step walkthrough, and the [slide deck](slide-deck/index.html) for an overview presentation.

## Sample Prompt

Below is a sample prompt you can use with the `interactive-benchmark` CoCo skill. It works against a TPC-H database that can be created using the setup script in the [`tpc-h/`](../tpc-h/) folder (run `./iwtpch.sh setup --scale 100`).

```
$interactive-benchmark hi, I have the following query

SELECT
	N_NAME,
	COUNT(*) AS ORDERS
FROM ORDERS AS O
INNER JOIN CUSTOMER AS C ON O_CUSTKEY = C_CUSTKEY
INNER JOIN NATION   AS N ON C_NATIONKEY = N_NATIONKEY
WHERE O_ORDERDATE BETWEEN '1996-01-01' AND '1996-12-31'
GROUP BY ROLLUP (N_NAME)
ORDER BY N_NAME NULLS LAST;

and I want understand how it can benefit from interactive analytics. The query is
used in Dashboard along with other queries. The query must answer in less than a
second. The database with the table used by the query is DM_TESTTPCH_BENCH_DB and
the schema is TPCH_SF100. The filter on order date will be different and also it
might happen that users filter data for specific nation or region or even market.
How can I make sure that I can obtain the performance I need? Use the "PM"
connection to connect to Snowflake.

Please also run a benchmark so that I can see how it performs when there are 50
concurrent users
```

Adapt the database name, schema, scale factor, and connection name to match your own environment.

## Repository Structure

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of the SPCS topology, directory layout, naming conventions, and deployment internals.

```
.cortex/skills/interactive-benchmark/
├── SKILL.md              # Skill definition (loaded by CoCo)
├── references/           # Supporting docs loaded on-demand by the skill
│   ├── benchmark-execution.md
│   ├── checklist-and-troubleshooting.md
│   ├── cleanup.md
│   ├── evals.md
│   ├── mcw-sizing.md
│   ├── report-generation.md
│   ├── server-side-validation.md
│   └── suitability-check.md
├── templates/
│   └── benchmark-report.html.template
└── benchmark/
    ├── .env.template     # Project-level env config template
    ├── api/              # Python FastAPI backend (endpoint: /api/run/interactive)
    ├── test/             # SQL query files to benchmark (place your .sql files here)
    ├── locust/           # Locust load test that POSTs queries to the API
    ├── reports/          # Generated benchmark reports (one subfolder per run)
    │   └── <SOLUTION_NAME>/
    │       ├── benchmark-report.html
    │       ├── progress.json
    │       ├── locust-run-1.txt
    │       ├── locust-run-2.txt   (if escalation triggered re-runs)
    │       └── ...               (additional runs as needed)
    ├── scripts/          # Deployment and management shell scripts
    └── spcs/             # SPCS deployment (Dockerfiles, specs, scripts)
```

- **`api/`** — FastAPI server that connects to Snowflake and exposes a POST endpoint. The endpoint executes the provided query against the interactive warehouse and returns timing metrics.
- **`test/`** — Place `.sql` files here — each containing a single query. The locust load test reads all files from this directory and benchmarks them against the interactive warehouse.
- **`locust/`** — Locust workload that reads queries from `test/`, then POSTs them to `/api/run/interactive`.
- **`reports/`** — Generated benchmark reports. Each run creates a subfolder (e.g. `reports/IWB_202608271430/`) containing the final HTML report and Locust execution logs.
- **`spcs/`** — Everything needed to deploy the benchmark API and load test to Snowpark Container Services: Dockerfiles, service specs, and shell scripts for build, deploy, update, status, logs, and teardown.

## Running on SPCS (manual)

The skill handles SPCS deployment automatically. The instructions below are for those who want to understand how the skill works behind the scenes or run the infrastructure manually without CoCo.

The benchmark runs on [Snowpark Container Services](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/overview) (SPCS), deploying the API server and Locust load test as two independent services with public ingress URLs. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full topology and deployment details.

### Prerequisites

- Docker Desktop (or any local buildx-capable daemon).
- `snow` CLI configured with a connection that has privileges to `CREATE COMPUTE POOL`, `CREATE IMAGE REPOSITORY`, and `CREATE SERVICE`.
- The API's runtime role needs `USAGE` on the interactive warehouse and `SELECT` on the interactive schema.

### Configuration

1. Copy `.env.template` to `.env` in the `benchmark/` directory and set `CONNECTION_NAME` and `SOLUTION_NAME`.

2. Copy `spcs/config.env.template` to `spcs/config.env` and adjust as needed. All object names are derived from `SOLUTION_NAME`. Key settings include compute pool sizes, API instance count, Locust user count, and run time.

### Deploy

```bash
.cortex/skills/interactive-benchmark/benchmark/scripts/deploy.sh
```

This will create the database/schema, two compute pools (one for the API, one for Locust), build and push both Docker images, create the services, and print the public ingress URLs once ready.

### Common operations

```bash
SCRIPTS=.cortex/skills/interactive-benchmark/benchmark/scripts

$SCRIPTS/status.sh              # show state + endpoints for both services
$SCRIPTS/status.sh --urls-only  # just the ingress URLs
$SCRIPTS/logs.sh api            # benchmark API logs
$SCRIPTS/logs.sh locust         # locust load-generator logs
$SCRIPTS/update.sh              # rebuild + ALTER SERVICE (preserves ingress URLs)
$SCRIPTS/resize-wh.sh --size M  # resize the interactive warehouse
$SCRIPTS/teardown.sh            # drop services, compute pools, and image repo
```

## Running Locally (manual)

As with SPCS deployment, the skill manages local execution automatically. These instructions are for those who want to run the API server manually outside of CoCo, for debugging or development purposes.

1. Copy `.env.template` to `.env` and configure:

   ```
   CONNECTION_NAME=<your_connection>
   SOLUTION_NAME=<your_solution_name>
   ```

   The connection must exist in `~/.snowflake/connections.toml`.

   All Snowflake object names are derived from `SOLUTION_NAME`:

   | Object | Name |
   |---|---|
   | Database | `<SOLUTION_NAME>_BENCH_DB` |
   | Interactive warehouse | `<SOLUTION_NAME>_BENCH_WH_INT` |
   | Interactive schema | `<SOLUTION_NAME>_IT` |

   Override any of these with env vars: `INTERACTIVE_WAREHOUSE`, `INTERACTIVE_SCHEMA`.

2. Start the API server:

   ```bash
   cd .cortex/skills/interactive-benchmark/benchmark/api
   uv run python server.py
   ```

   The server runs on port 3000. It loads all `.sql` files from the `test/` directory into a query registry keyed by filename stem (e.g. `test/q1.sql` → `query_id: "q1"`). Test with:
   ```bash
   # List available queries
   curl http://localhost:3000/api/queries

   # Run a query by ID
   curl -X POST http://localhost:3000/api/run/interactive \
     -H "Content-Type: application/json" \
     -d '{"query_id": "q1"}'
   ```

