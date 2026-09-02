# Checklist and Troubleshooting

## Minimal "Good Setup" Checklist

Before considering a benchmark complete, verify all of the following are true:

- [ ] **Latency goal captured as P95 explicitly** (Phase 1) — assumption stated back to the user
- [ ] **Scale-out (MCW) and scale-up (SKU) limits captured** (Phase 1) — asked before benchmark start if not volunteered
- [ ] **Interactive setup validated for the active mode:**
  - *Interactive-table mode:* Interactive table created with a **deliberate CLUSTER BY** matching the query's predicate columns (every table, including tiny lookups)
  - *Zero-copy mode:* Source table clustering keys verified to align with the query's WHERE/JOIN predicates
- [ ] Interactive warehouse created, resumed, and **explicitly used** (not accidentally falling back to another warehouse)
- [ ] **Tables attached or source tables validated:**
  - *Interactive-table mode:* Hot tables **attached** to the interactive warehouse with ADD TABLES (verified via `SHOW INTERACTIVE TABLES`)
  - *Zero-copy mode:* Source tables accessible from the interactive warehouse (verified by running the query successfully)
- [ ] Warehouse **sized to working set** (cache fits the data) — do NOT upsize to fix concurrency
- [ ] **`MAX_CLUSTER_COUNT` set proportional to target concurrent users** (rule: `ceil(users / 15)`; verified via `SHOW WAREHOUSES`)
- [ ] **Fallback warehouse configured** on the interactive warehouse (verified via `SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE'`)
- [ ] `config.env` values (INTERACTIVE_WAREHOUSE, LOCUST_USERS, schema) match Phase 1/Step 2.1 outputs — no template placeholders left
- [ ] Query shapes are **selective, parameterized, and benchmarked after warm-up** (not cold-start measurements)
- [ ] Query Profile shows **low remote reads** (0% ideal), **low compile time** (< 50 ms), and **low queueing** (0 ms) for steady-state traffic
- [ ] **Server-side P50/P95/P99 collected** from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` and reported **alongside** the Locust client-side percentiles
- [ ] **Client-vs-server delta analyzed** and the bottleneck (API/HTTP vs Snowflake) explicitly named in the report — never rely on Locust numbers alone
- [ ] **Step 3.11 goal check performed** — if server-side P95 missed the goal, escalation was performed automatically within limits, or the limit-bound verdict was recorded
- [ ] **HTML report generated from `templates/benchmark-report.html.template`** — no `{{PLACEHOLDER}}` tokens remain in the output file, and all 12 mandatory sections are present

If any item fails, address it before drawing conclusions from benchmark numbers.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No .sql files found` | Place query files in `benchmark/test/` folder |
| Service stuck in PENDING | Run `./logs.sh` to inspect container logs |
| Connection errors | Verify connection name in `~/.snowflake/connections.toml` |
| Interactive tables not found | **Interactive-table mode:** Re-run `snowflake-interactive` skill. **Zero-copy mode:** This is expected — there are no interactive tables. Verify the source tables exist and the interactive warehouse can query them. |
| `BENCHMARK_LOCUST` stuck in PENDING with "Readiness probe failing at /stats/requests" | Legacy `LOCUST_HEADLESS=1` config. Headless locust does not bind port 8089, so the readiness probe fails forever. Remove `LOCUST_HEADLESS` from `config.env` and `specs/locust.yaml`; use the auto-start non-headless path (default). |
| `An interactive table must contain clustering keys` on `CREATE INTERACTIVE TABLE` | Only applies to interactive-table mode. The table has no `CLUSTER BY`. All interactive tables need one, including tiny lookup tables. Cluster on the primary key column if nothing else fits (e.g. `CLUSTER BY (N_NATIONKEY)`). |
| Most interactive queries fail with `Statement reached its statement or warehouse timeout of 5 second(s) and was canceled` under load | Interactive warehouse is out of concurrency slots. Queries queue past the 5 s cancel. Fix: set `MAX_CLUSTER_COUNT` per Step 3.3 (`ceil(users / 15)`) — do NOT upsize the warehouse. |
| Small number of interactive queries fail with the 5 s cancel; the rest are fast | Long-tail outliers hitting the cancel. Fix: set `FALLBACK_WAREHOUSE` per Step 3.3. This is the expected steady-state for benchmarks — always configure fallback before load-testing. |
| Curl to Locust `/swarm` endpoint returns an HTML auth page | SPCS public ingress requires Snowflake auth. `externalbrowser` connections cannot curl this from a laptop. Use the auto-start execution model (Step 3.8) — no `/swarm` call needed. |
| Benchmark run used a different `LOCUST_USERS` value than requested | `config.env` had a stale value. Step 3.5 checklist requires overwriting `LOCUST_USERS` from Phase 1's answer — do not rely on template defaults. |
