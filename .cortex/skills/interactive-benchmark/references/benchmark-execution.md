# Benchmark Execution — Steps 3.8 and 3.9 Detail

## Step 3.8: Run Baseline Test (Infrastructure Validation)

The Locust container now runs a **two-phase execution model**. When the container starts, it automatically executes both phases in sequence:

**Phase 1 — Baseline:** Locust runs `BaselineUser` against the no-op `POST /api/run/baseline` endpoint for `BASELINE_RUN_TIME` (default 1 minute) with the same user count and spawn rate as the real benchmark. This measures pure API/SPCS infrastructure throughput without touching Snowflake.

After Phase 1 completes, the entrypoint parses the baseline CSV and checks:
- **Failure rate** must be <= `BASELINE_MAX_FAILURE_PCT` (default 1%)
- **p99 latency** must be <= `BASELINE_MAX_P99_MS` (default 500ms)

If either threshold is exceeded, the container logs an error with remediation suggestions (increase API instances, increase compute pool nodes, or reduce user count) and **does NOT proceed to Phase 2**. The container stays alive for log retrieval.

**Phase 2 — Snowflake Benchmark:** Only runs if Phase 1 passes. This is the real load test against `POST /api/run/interactive`.

Baseline env vars (all have sensible defaults — no SPCS spec changes required):

| Variable | Default | Description |
|---|---|---|
| `BASELINE_RUN_TIME` | `1m` | Duration of the baseline test |
| `BASELINE_MAX_FAILURE_PCT` | `1` | Max acceptable failure % |
| `BASELINE_MAX_P99_MS` | `500` | Max acceptable p99 in milliseconds |

**There is no external HTTP call needed to trigger either phase.** Starting the container starts the baseline, and a passing baseline automatically starts the benchmark. SPCS public ingress requires Snowflake auth, so the auto-start design sidesteps this entirely.

Monitor baseline progress using the `bash` tool:
```bash
cd <SKILL_DIR>/benchmark/scripts && ./logs.sh locust
```

Look for `[baseline] VERDICT: PASS` to confirm the infrastructure is healthy before the benchmark begins.

---

## Step 3.9: Run Load Test (Snowflake Benchmark)

**This step runs automatically after the baseline passes (Step 3.8).** No manual trigger is needed on the first run.

### 9a. Trigger the run

Depending on state:
- **First run after `./deploy.sh`** — both phases run automatically when the container starts. No action needed. Proceed to 9b.
- **Subsequent runs after changing config or warehouse settings** — force a container restart using the `bash` tool:
  ```bash
  cd <SKILL_DIR>/benchmark/scripts && ./update.sh
  ```
  Or suspend+resume directly via `snowflake_sql_execute`:
  ```sql
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST SUSPEND;
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST RESUME;
  ```
  Then wait for locust to report READY using the `bash` tool:
  ```bash
  cd <SKILL_DIR>/benchmark/scripts && ./status.sh --wait
  ```
  Note: the baseline will re-run on every restart. This is intentional — it re-validates the infrastructure after any configuration change.

### 9b. Monitor the run

The benchmark phase runs for `LOCUST_RUN_TIME` (default 3 minutes). While it runs:

- **Watch cluster scaling** on the interactive warehouse via `snowflake_sql_execute`:
  ```sql
  SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
  ```
  Look at `started_clusters` and `running`. If `queued > 0`, `MAX_CLUSTER_COUNT` from Step 3.3 is too low — abort and increase it.

- **Follow locust logs** using the `bash` tool:
  ```bash
  cd <SKILL_DIR>/benchmark/scripts && ./logs.sh locust
  ```
  You'll see lines like `Ramping to 50 users at a rate of 5.00 per second` and `All users spawned`.

### 9c. Retrieve the results

After `LOCUST_RUN_TIME + ~10 s` (for `--autoquit` to fire), locust exits and the entrypoint prints a `======================== BENCHMARK RESULTS ========================` banner followed by the stats CSV. Retrieve using the `bash` tool:

```bash
cd <SKILL_DIR>/benchmark/scripts && ./logs.sh locust | tail -80
```

The `locust_stats_stats.csv` block contains a row for `/api/run/interactive` (plus Aggregated) with columns:

```
Type, Name, Request Count, Failure Count, Median Response Time, Average Response Time,
Min, Max, Avg Content Size, Requests/s, Failures/s, 50%, 66%, 75%, 80%, 90%, 95%, 98%, 99%, 99.9%, 99.99%, 100%
```

Parse the `/api/run/interactive` row for P50, P95, P99 and failure counts.

The baseline results are also available in the logs under the `======================== BASELINE RESULTS ========================` banner. The baseline p99 establishes the infrastructure overhead floor.

If you need results before the test finishes, the container also emits a HEARTBEAT block every 2 minutes with both baseline and benchmark CSVs — grep for `HEARTBEAT` in the logs.
