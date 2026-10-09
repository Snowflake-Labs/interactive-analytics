# Benchmark Execution — Steps 3.7 and 3.8 Detail

## Step 3.7: Run Baseline Test (Infrastructure Validation)

The Locust container now runs a **two-phase execution model**. When the container starts, it automatically executes both phases in sequence:

**Phase 1 — Baseline:** Locust runs `BaselineUser` against the no-op `POST /api/run/baseline` endpoint for `BASELINE_RUN_TIME` (default 1 minute) with the same user count and spawn rate as the real benchmark. This measures pure API/SPCS infrastructure throughput without touching Snowflake.

After Phase 1 completes, the entrypoint parses the baseline CSV and checks:
- **Failure rate** must be <= `BASELINE_MAX_FAILURE_PCT` (default 1%)
- **p99 latency** must be <= `BASELINE_MAX_P99_MS` (default 500ms)

If either threshold is exceeded, the container logs an error with remediation suggestions (increase API instances, increase compute pool nodes, or reduce user count) and **does NOT proceed to Phase 2**. The container stays alive for log retrieval.

**Phase 2 — Snowflake Benchmark:** Only runs if Phase 1 passes. This is the real load test against `POST /api/run/interactive`.

Baseline thresholds are set in `config.env` and passed through `specs/locust.yaml`:

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

## Step 3.8: Run Load Test (Snowflake Benchmark)

**This step runs automatically after the baseline passes (Step 3.7).** No manual trigger is needed on the first run.

### 8a. Trigger the run

Depending on state:
- **First run after `./deploy.sh`** — both phases run automatically when the container starts. No action needed. Proceed to 8b.
- **Subsequent runs after changing config or warehouse settings** — restart the Locust container by suspending and resuming it via `snowflake_sql_execute` (`update.sh` only re-uploads queries and restarts the API; it does not re-run Locust):
  ```sql
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST SUSPEND;
  ALTER SERVICE <DATABASE>.SPCS.BENCHMARK_LOCUST RESUME;
  ```
  Then wait for locust to report READY using the `bash` tool:
  ```bash
  cd <SKILL_DIR>/benchmark/scripts && ./status.sh --wait
  ```
  Note: the baseline will re-run on every restart. This is intentional — it re-validates the infrastructure after any configuration change.

### 8b. Monitor the run

Both phases first ramp up to `LOCUST_USERS` at `LOCUST_SPAWN` users/s (about `LOCUST_USERS / LOCUST_SPAWN` seconds), then reset their stats (`Resetting stats` in the log) and measure full load: `BASELINE_RUN_TIME` (default 1 minute) for the baseline, `LOCUST_RUN_TIME` (default 3 minutes) for the benchmark. Ramp-up requests are not in the results. While the benchmark phase runs:

- **Watch cluster scaling** on the interactive warehouse via `snowflake_sql_execute`:
  ```sql
  SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
  ```
  Look at `started_clusters` and `running`. If `queued > 0`, `MAX_CLUSTER_COUNT` from Step 3.2 is too low — abort and increase it.

- **Follow locust logs** using the `bash` tool:
  ```bash
  cd <SKILL_DIR>/benchmark/scripts && ./logs.sh locust
  ```
  You'll see lines like `Ramping to 50 users at a rate of 5.00 per second` and `All users spawned`.

### 8c. Retrieve the results

About `LOCUST_USERS / LOCUST_SPAWN + LOCUST_RUN_TIME` seconds after the benchmark phase starts, locust exits and the entrypoint prints a `======================== BENCHMARK RESULTS ========================` banner followed by the stats CSV and a verdict line. Retrieve using the `bash` tool:

```bash
cd <SKILL_DIR>/benchmark/scripts && ./logs.sh locust \
  | awk '/=+ BENCHMARK RESULTS =+/ {p = 1} p; p && /^\[benchmark\] VERDICT/ {exit}'
```

This prints from the results banner through the verdict line, however many heartbeats have been logged since.

The `locust_stats_stats.csv` block contains a row for `/api/run/interactive` (plus Aggregated) with columns:

```
Type, Name, Request Count, Failure Count, Median Response Time, Average Response Time,
Min, Max, Avg Content Size, Requests/s, Failures/s, 50%, 66%, 75%, 80%, 90%, 95%, 98%, 99%, 99.9%, 99.99%, 100%
```

Parse the `/api/run/interactive` row for P50, P95, P99 and failure counts.

Then read the verdict printed after the results:
- `[benchmark] VERDICT: PASS` — the numbers are a valid measurement.
- `[benchmark] VERDICT: FAIL — no /api/run/interactive requests were recorded.` or `[benchmark] VERDICT: FAIL — no requests completed.` — no query ran (e.g. the queries stage is empty). Fix and re-run; there is nothing to report.
- `[benchmark] VERDICT: FAIL — failure rate ...` — more than `BENCHMARK_MAX_FAILURE_PCT` (default 1%) of requests failed. The percentiles are not a valid measurement. Read the `locust_stats_failures.csv` block and `./logs.sh api`, fix the cause, and re-run instead of reporting the numbers.
- Any other line starting with `[benchmark] VERDICT: FAIL` — treat it the same way: do not report the run.
- `[benchmark] WARNING: Locust was CPU-bound` (printed before the verdict) — Locust runs as a single process, so client-side percentiles are inflated by the load generator itself. Use the server-side numbers (Step 3.10) for the goal check and state in the report that client-side numbers are an upper bound.

The heartbeat's `[status]` line repeats the outcome (`benchmark=COMPLETED` or `benchmark=FAILED`).

The baseline results are also available in the logs under the `======================== BASELINE RESULTS ========================` banner. The baseline p99 establishes the infrastructure overhead floor.

After both phases finish, the container emits a HEARTBEAT block every 2 minutes with its `[status]` line and the baseline and benchmark stats CSVs (not the failures CSV), so the outcome stays visible in later log reads.
