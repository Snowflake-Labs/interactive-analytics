---
name: interactive-tpch-dashboard
description: "Deploy the TPC-H interactive dashboard demo and Locust load test to SPCS. Use ONLY when the user explicitly asks to deploy, update, or manage the TPC-H dashboard demo. Do NOT use for running the TPC-H benchmark locally (use interactive-tpch-benchmark) or for generic benchmarking (use interactive-benchmark). Triggers: TPC-H dashboard, tpch dashboard, deploy tpch dashboard, dashboard demo, tpch demo, locust tpch, tpch SPCS."
---

# Interactive Analytics TPC-H Dashboard Demo

Guides users through deploying the TPC-H interactive dashboard (FastAPI + Chart.js) and Locust load test to Snowpark Container Services (SPCS).

## Prerequisites

- `uv` installed (Python package runner)
- A Snowflake connection configured in `~/.snowflake/connections.toml`
- Role with privileges to create compute pools and services (e.g. `SYSADMIN` or `ACCOUNTADMIN`)
- Docker installed
- TPC-H tables already set up (run the `interactive-tpch-benchmark` skill's setup first)

## Workflow

### Step 1: Detect Intent

Ask the user what they want to do:

1. **Deploy dashboard** — Deploy the FastAPI dashboard + Locust load test to SPCS
2. **Check status** — Show SPCS service status and ingress URLs
3. **Update** — Rebuild and redeploy without changing URLs
4. **Teardown** — Remove SPCS services and compute pools

Route to the matching section below.

---

### Deploy Dashboard to SPCS

**Goal:** Deploy the FastAPI + Chart.js dashboard and Locust load test to Snowpark Container Services.

**Actions:**

1. Ensure `.env` exists in `tpc-h-sample-dashboard/`:
   ```bash
   cp tpc-h-sample-dashboard/.env.example tpc-h-sample-dashboard/.env
   ```

2. Ask the user for:
   - `CONNECTION_NAME` — Snowflake connection
   - `SOLUTION_NAME` — same as used for TPC-H setup (default: `IW_TPCH`)
   - `DEFAULT_SCALE` — scale for the dashboard queries

3. Update `tpc-h-sample-dashboard/.env` with the values.

4. Ensure `tpc-h-sample-dashboard/spcs/config.env` exists (create from template if missing):
   ```bash
   cp tpc-h-sample-dashboard/spcs/config.env.template tpc-h-sample-dashboard/spcs/config.env
   ```
   Then review — key settings:
   - `CONNECTION` — Snowflake connection for SPCS deployment
   - `ROLE` — role for creating SPCS objects (default: `ACCOUNTADMIN`)
   - `DEPLOY_WAREHOUSE` — warehouse for deploy SQL session
   - `SOLUTION_NAME` — must match the value in `tpc-h-sample-dashboard/.env`
   - `DEFAULT_SCALE` — must match the scale in `tpc-h-sample-dashboard/.env`

5. Create the denormalized dashboard table:
   ```bash
   cd <REPO_ROOT>/tpc-h-sample-dashboard/spcs && ./deploy.sh sql
   ```

6. Deploy SPCS services (builds Docker images, pushes, creates compute pools and services):
   ```bash
   cd <REPO_ROOT>/tpc-h-sample-dashboard/spcs && ./deploy.sh services
   ```

**Services deployed:**
- `DASHBOARD` — browser UI + API (dashboard compute pool)
- `DASHBOARD_API_LOCUST` — isolated API copy for load testing (locust compute pool)
- `DASHBOARD_LOCUST` — Locust load generator (locust compute pool)

**After deployment:** The script prints ingress URLs. Open the dashboard URL in a browser (Snowflake login prompts on first visit).

---

### Check Status

```bash
cd <REPO_ROOT>/tpc-h-sample-dashboard/spcs && ./status.sh
```

Options:
- `./status.sh --wait` — poll until all services are READY
- `./status.sh --urls-only` — print only ingress URLs

---

### Update Dashboard (rebuild without changing URLs)

```bash
cd <REPO_ROOT>/tpc-h-sample-dashboard/spcs && ./update.sh
```

---

### Teardown

**SPCS services** (drops services, compute pools, image repo):
```bash
cd <REPO_ROOT>/tpc-h-sample-dashboard/spcs && ./teardown.sh
```

---

## Stopping Points

- After detecting intent — confirm the action before proceeding
- After collecting configuration values — confirm `.env` contents before running setup
- Before `deploy.sh services` — warn that this builds Docker images and creates compute pools (cost implications)
- Before teardown — confirm which resources to drop

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `uv: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker build fails | Ensure Docker daemon is running; check `docker info` |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Service FAILED | Check `./logs.sh`; common cause is missing grants or network rules |
| Connection errors | Verify connection name exists in `~/.snowflake/connections.toml` |

## Output

- Running SPCS services with public ingress URLs for the dashboard and Locust UI
