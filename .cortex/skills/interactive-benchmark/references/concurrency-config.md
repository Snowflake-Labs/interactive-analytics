# Concurrency and Fallback Configuration (Step 3.2)

**Before changing anything, record the interactive warehouse's original settings** — cleanup (Step 3.13) restores them on a user-supplied warehouse. Capture `size`, `min_cluster_count`, and `max_cluster_count` from `SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>'` and the value from `SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE <INTERACTIVE_WAREHOUSE>`.

Compute the required cluster counts using the formula from `references/mcw-sizing.md`:

```
IN_FLIGHT_QUERIES             = <CONCURRENT_USERS> * QUERY_LATENCY_S / (QUERY_LATENCY_S + 1.0)
RECOMMENDED_MIN_CLUSTER_COUNT = max(1, ceil(IN_FLIGHT_QUERIES / MAX_CONCURRENCY_LEVEL))
RECOMMENDED_MAX_CLUSTER_COUNT = RECOMMENDED_MIN_CLUSTER_COUNT * 2
```

where `QUERY_LATENCY_S` is the warm interactive latency from the suitability check, `1.0` is Locust's mean think time, and `MAX_CONCURRENCY_LEVEL` defaults to 8.

Use the user's scale-out limit from Phase 1 as the ceiling. If the recommended value exceeds the user's limit, use the user's limit — the autonomous execution principle means we proceed with what was approved, and Step 3.11 will detect if queueing causes P95 misses and propose escalation at that point.

After `config.env` is created in Step 3.4, use `resize-wh.sh` for warehouse
reconfiguration. The script handles two cases:
- `--mcw` only: `ALTER WAREHOUSE ... SET MAX_CLUSTER_COUNT` in place. Grants, attached tables, fallback warehouse, and the data cache are kept.
- `--size`: `ALTER ... SET WAREHOUSE_SIZE` fails with error 090094 on interactive warehouses with attached tables, so the script runs `CREATE OR REPLACE INTERACTIVE WAREHOUSE` with the current attached tables and restores `FALLBACK_WAREHOUSE`. It refuses to replace a warehouse that has grants to other roles or a resource monitor (both would be dropped) unless `--force-replace` is passed. Never pass `--force-replace` on a warehouse the user did not create for this benchmark; stop and ask instead.

Either way, newly started clusters are cold, and a replace resets the cache of every cluster. **You MUST re-run the cache warm-up procedure (Step 3.5) before any load test.**

For the initial pre-deploy configuration, `config.env` does not exist yet.
Apply the computed cluster counts directly via `snowflake_sql_execute`:

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE> SET
  MIN_CLUSTER_COUNT = <RECOMMENDED_MIN_CLUSTER_COUNT>,
  MAX_CLUSTER_COUNT = <RECOMMENDED_MAX_CLUSTER_COUNT>,
  SCALING_POLICY = 'STANDARD';
```

For later changes during escalation, run `resize-wh.sh`; it suspends Locust and
leaves it suspended so benchmarking cannot start against a cold cache. After
the script completes, run the cache warm-up (Step 3.5) and THEN explicitly
resume Locust via `snowflake_sql_execute`:

```sql
USE ROLE <ROLE>;
USE DATABASE <DB>;
USE SCHEMA <SCHEMA>;
ALTER SERVICE <LOCUST_SERVICE> RESUME;
```

This guarantees warmup queries always execute before any benchmark traffic.

Configure the fallback warehouse via `snowflake_sql_execute` (uses the standard warehouse from Phase 1):

```sql
ALTER WAREHOUSE <INTERACTIVE_WAREHOUSE>
  SET FALLBACK_WAREHOUSE = <STANDARD_WAREHOUSE>;
```

Verify via `snowflake_sql_execute`:

```sql
SHOW PARAMETERS LIKE 'FALLBACK_WAREHOUSE' IN WAREHOUSE <INTERACTIVE_WAREHOUSE>;
```
