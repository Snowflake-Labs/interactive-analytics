# Interactive Tables Dashboard

A sample dashboard that benchmarks Snowflake **Interactive Tables + Interactive Warehouse** against **Standard Tables** using TPC-H workloads. The dashboard displays live KPIs and charts, while a Locust-based load test simulates concurrent dashboard users to measure query latency under load.

## Repository Structure

```
dashboard/
├── api/          # Python FastAPI backend (Snowflake connector, REST endpoints)
├── public/       # Frontend single-page HTML dashboard (Chart.js)
├── sql/          # SQL scripts to create the denormalized LINEITEM_DASHBOARD table
├── locust/       # Locust load test simulating concurrent dashboard users
└── spcs/         # Snowpark Container Services deployment (Dockerfiles, specs, scripts)
```

### `api/`

FastAPI server that connects to Snowflake and exposes REST endpoints consumed by the dashboard UI. It routes queries to either an Interactive Warehouse or a Standard Warehouse depending on the selected mode.

### `public/`

Static HTML/JS frontend with Chart.js visualizations: KPI cards, time-series line charts, doughnut charts, and bar charts. Served directly by the FastAPI backend.

### `sql/`

Contains `create_lineitem_dashboard.sql` which builds the denormalized `LINEITEM_DASHBOARD` table (joining LINEITEM, ORDERS, CUSTOMER, NATION, REGION) in both a standard schema and an interactive-table schema.

### `locust/`

Locust workload definition that simulates real dashboard users. Each virtual user fetches configuration, then repeatedly calls all dashboard API endpoints in parallel with randomized segment filters.

### `spcs/`

Everything needed to deploy the dashboard and load test to Snowpark Container Services: Dockerfiles, service specs, and shell scripts for build, deploy, update, status, logs, and teardown.

## Running the Dashboard Locally

1. Copy `.env.example` to `.env` and set your Snowflake connection name:

   ```
   CONNECTION_NAME=<your_connection>
   DEFAULT_SCALE=100
   ```

   The connection must exist in `~/.snowflake/connections.toml`.

2. Start the server:

   ```bash
   ./run-dashboard.sh
   ```

   This launches the FastAPI backend on port 3000. Open `http://localhost:3000` in your browser.

## Running the Simulation (Load Test)

### Headless mode

```bash
./run-users.sh <warehouse>
```

Where `<warehouse>` is `interactive` or `standard`. This runs Locust against `http://localhost:3000` with 5 concurrent users for 5 minutes.

### Interactive mode (Locust web UI)

```bash
cd locust
uv run locust -f locustfile.py --host http://localhost:3000
```

Open `http://localhost:8089` to configure the number of users, ramp-up rate, and duration.

## Deploying to Snowpark Container Services

See [`spcs/README.md`](spcs/README.md) for full deployment instructions. In short:

```bash
cd spcs
./deploy.sh
```

This builds Docker images, pushes them to the Snowflake image registry, and creates the services across isolated compute pools.
