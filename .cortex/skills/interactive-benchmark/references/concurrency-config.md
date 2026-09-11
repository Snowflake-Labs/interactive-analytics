# Concurrency and Fallback Configuration (Step 3.3)

Compute the required cluster counts using the formula from `references/mcw-sizing.md`:

```
RECOMMENDED_MIN_CLUSTER_COUNT = ceil(<CONCURRENT_USERS> / MAX_CONCURRENCY_LEVEL)
RECOMMENDED_MAX_CLUSTER_COUNT = RECOMMENDED_MIN_CLUSTER_COUNT * 2
```

where `MAX_CONCURRENCY_LEVEL` defaults to 8.

Use the user's scale-out limit from Phase 1 as the ceiling. If the recommended value exceeds the user's limit, use the user's limit — the autonomous execution principle means we proceed with what was approved, and Step 3.12 will detect if queueing causes P95 misses and propose escalation at that point.

**IMPORTANT — Use `resize-wh.sh` for any warehouse reconfiguration.** `ALTER WAREHOUSE ... SET WAREHOUSE_SIZE` fails with error 090094 on interactive warehouses that have attached tables — even when suspended. Direct `ALTER WAREHOUSE` via `snowflake_sql_execute` will not work. Always use the `resize-wh.sh` script instead — it reads current properties (size, MCW, fallback warehouse, attached tables), suspends SPCS services, runs `CREATE OR REPLACE INTERACTIVE WAREHOUSE` with the new settings and re-attached tables, restores the fallback warehouse, and resumes services. **Because `CREATE OR REPLACE` resets the data cache, the cache will be cold after `resize-wh.sh` completes. You MUST re-run the cache warm-up procedure (Step 3.6) before any load test.**

Apply the initial cluster count via `bash`:

```bash
cd <SKILL_DIR>/benchmark/scripts && ./resize-wh.sh --mcw <computed_value>
```

**IMPORTANT:** `resize-wh.sh` only resumes the API service — Locust stays suspended so it cannot start benchmarking against a cold cache. After the script completes, you MUST run the cache warm-up (Step 3.6) and THEN explicitly resume Locust via `snowflake_sql_execute`:

```sql
USE ROLE <ROLE>;
USE DATABASE <DB>;
USE SCHEMA <SCHEMA>;
ALTER SERVICE <LOCUST_SERVICE> RESUME;
```

This guarantees warmup queries always execute before any benchmark traffic. **If this is the initial deploy (Step 3.7 has not run yet), skip the Locust resume — Locust will be started by `deploy.sh` after cache warming in Step 3.6.**

Then configure `MIN_CLUSTER_COUNT` and `SCALING_POLICY` via `snowflake_sql_execute` (these do not require service suspension):

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE> SET
  MIN_CLUSTER_COUNT = <RECOMMENDED_MIN_CLUSTER_COUNT>,
  SCALING_POLICY = 'STANDARD';
```

Configure the fallback warehouse via `snowflake_sql_execute` (uses the standard warehouse from Phase 1):

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE>
  SET FALLBACK_WAREHOUSE = <STANDARD_WAREHOUSE>;
```

Verify via `snowflake_sql_execute`:

```sql
SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE <INTERACTIVE_WAREHOUSE>;
```
