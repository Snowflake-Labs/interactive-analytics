# Goal Check and Iterative Escalation (Step 3.12)

After collecting the server-side percentiles from Step 3.11, evaluate them against the P95 latency goal captured in Phase 1.

**Case 1 — Goal met on both client and server.** Report success. Proceed to Step 3.13.

**Case 2 — Server-side P95 meets the goal but client-side does not.** Snowflake is doing its job; the tail comes from API/HTTP overhead. Do NOT propose warehouse scale-up — it will not help. Diagnose and document, then proceed to Step 3.13.

**Case 3 — Server-side P95 does NOT meet the goal.** The warehouse itself is not delivering the target latency. Automatically escalate within the user's pre-approved limits. Pick the right lever based on the profile from Step 3.11:

1. **Scale out (increase MAX_CLUSTER_COUNT)** — only if `AVG_QUEUE_MS > 0` on the interactive warehouse. Queueing is the signal that horizontal scaling will help. Bounded by the user's scale-out limit (Phase 1).
2. **Scale up (bump the warehouse SKU)** — if `AVG_QUEUE_MS == 0` (no queueing — the bottleneck is per-query execution, not concurrency). Move to the next SKU (X-Small -> Small -> Medium -> Large -> ...). Each step roughly doubles cache and cores and typically halves per-query execute time. Bounded by the user's scale-up limit (Phase 1).
3. **Both** — if there is queueing AND per-query execute time is already high, do the scale-out first, then re-measure before considering scale-up.

**Do NOT ask for permission to scale within the defined limits.** The user already approved the scale-out limit (MAX_CLUSTER_COUNT) and scale-up limit (warehouse size) in Step 1. As long as the proposed change stays within those boundaries, proceed automatically — inform the user what you are doing (e.g. "P95 goal not met. Scaling warehouse from X-Small to Small — within your approved ceiling of Medium. Re-running benchmark.") but do NOT wait for confirmation. This keeps the benchmark moving without unnecessary interruptions.

**After each escalation:** re-configure the warehouse using `resize-wh.sh` via `bash`. This script uses `CREATE OR REPLACE INTERACTIVE WAREHOUSE` (the only reliable path — `ALTER WAREHOUSE SET WAREHOUSE_SIZE` fails with 090094 on interactive warehouses with attached tables). It preserves attached tables and the fallback warehouse automatically. **Do NOT use `snowflake_sql_execute` with direct `ALTER WAREHOUSE` for size or MCW changes.**

```bash
# Scale up only:
cd <SKILL_DIR>/benchmark/scripts && ./resize-wh.sh --size <NEW_SIZE>
# Scale out only:
cd <SKILL_DIR>/benchmark/scripts && ./resize-wh.sh --mcw <NEW_MCW>
# Both at once:
cd <SKILL_DIR>/benchmark/scripts && ./resize-wh.sh --size <NEW_SIZE> --mcw <NEW_MCW>
```

After `resize-wh.sh` completes, **the data cache is cold** because `CREATE OR REPLACE` resets it, and **Locust is still suspended** (the script only resumes the API service). Follow this exact sequence:

1. **Re-warm the cache** (Step 3.6) — run warmup queries via `snowflake_sql_execute` against the interactive warehouse.
2. **Resume Locust** — only after warmup is complete, resume the Locust service via `snowflake_sql_execute`:
   ```sql
   USE ROLE <ROLE>;
   USE DATABASE <DB>;
   USE SCHEMA <SCHEMA>;
   ALTER SERVICE <LOCUST_SERVICE> RESUME;
   ```
3. **Monitor** the load test (Step 3.9) and re-collect the server-side numbers (Step 3.11).

**Do NOT re-deploy SPCS** — `resize-wh.sh` only suspends/resumes services, it does not recreate them. **Do NOT resume Locust before cache warming is complete** — this is the whole point of keeping Locust suspended after resize. Re-evaluate this step after each iteration. **Cap the iteration count at the user's "Max escalation iterations" value from Phase 1 (default: 5)** to avoid runaway loops.

**Limits already reached — the goal is not achievable within the user's ceilings.** If both `MAX_CLUSTER_COUNT` and warehouse size are already at the user-supplied ceilings and the goal is still missed, do NOT propose further scaling. **Only at this point should you stop and ask the user.** Tell them clearly, for example:

> "The target of **P95 <= 1000 ms** is not achievable within your scale-out limit of **5 clusters** and scale-up limit of **Medium**. Best result reached: server-side P95 = **1800 ms** (Medium x 5 clusters). Options: (a) relax one of the ceilings and re-run, (b) redesign the query (fewer joins, pre-aggregated table, narrower predicates), (c) reduce data scanned (better clustering, search optimization), (d) accept the current performance. How would you like to proceed?"

Then produce the Step 3.13 report with the ceiling-limited numbers and mark the P95 goal as **not met — limit-bound** in the executive summary tile.

**Recording the iteration history.** For the report, keep a short log of each iteration (starting size / MCW, resulting server-side P95, decision) so the reader can see the escalation path. This log populates the `{{ITERATION_HISTORY}}` placeholder in the template.
