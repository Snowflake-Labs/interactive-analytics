# Server-Side Validation Reference

## SQL Queries

### 1. Aggregate server-side percentiles for the interactive warehouse

```sql
SELECT
  COUNT(*) AS N,
  AVG(TOTAL_ELAPSED_TIME)::INT AS AVG_MS,
  MEDIAN(TOTAL_ELAPSED_TIME)::INT AS P50_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.90)::INT AS P90_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95)::INT AS P95_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.99)::INT AS P99_MS,
  AVG(COMPILATION_TIME)::INT AS AVG_COMPILE_MS,
  AVG(EXECUTION_TIME)::INT AS AVG_EXEC_MS,
  AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME)::INT AS AVG_QUEUE_MS,
  (AVG(BYTES_SCANNED) / (1024*1024))::INT AS AVG_MB_SCAN
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  RESULT_LIMIT => 5000
))
WHERE START_TIME >= DATEADD(minute, -10, CURRENT_TIMESTAMP())
  AND EXECUTION_STATUS = 'SUCCESS';
```

### 2. Client-vs-server delta table

Build this table for the report:

| Percentile | Locust (client) | Snowflake (server) | Delta (API/HTTP) |
|---|---|---|---|
| P50 | ... | ... | ... |
| P95 | ... | ... | ... |
| P99 | ... | ... | ... |

**Interpretation rules:**
- **Delta < ~50 ms and roughly constant across percentiles** — API and HTTP round-trip are cheap; Snowflake is the whole story. Optimization work should target the warehouse / query / clustering.
- **Delta grows with percentile (P50 delta small, P95 delta large)** — API pool exhaustion or connection queueing under load. Increase `API_WORKERS` / `POOL_SIZE`, add more API instances, or raise the compute pool size.
- **Delta is large at every percentile** — API is undersized regardless of load. Same fix as above but more urgent.
- **Server-side P95 already exceeds the goal** — API tuning cannot save you; go back and fix the warehouse (multi-cluster, fallback size, clustering, query shape).

Always state the conclusion of this analysis in the report — the reader must know which layer to invest in.

### 3. Pick outliers and inspect Query Profile

**IMPORTANT: QUERY_ID values must ALWAYS be included in their full, untruncated form (e.g. `01b8f3a2-0504-b572-0000-0a6d001f436a`). Never shorten, abbreviate, or use ellipsis for query IDs — the user needs to copy-paste them directly into Snowsight.**

```sql
SELECT
  QUERY_ID,
  TOTAL_ELAPSED_TIME,
  COMPILATION_TIME,
  EXECUTION_TIME,
  QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME AS QUEUED_MS,
  BYTES_SCANNED,
  PERCENTAGE_SCANNED_FROM_CACHE
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  RESULT_LIMIT => 5000
))
WHERE START_TIME >= DATEADD(minute, -10, CURRENT_TIMESTAMP())
  AND EXECUTION_STATUS = 'SUCCESS'
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 20;
```

## Query Profile Health Metrics

| Metric | Target | What it means if bad |
|--------|--------|---------------------|
| **Remote read %** | 0% | Query is reading from remote storage instead of cache. Causes: poor clustering, undersized working-set cache, cold cache, or cache thrashing. |
| **Bytes scanned** | Minimal (ideally <100 GB) | Partition pruning is not effective. Check clustering keys and predicate alignment. |
| **Compile time** | Low (< 50 ms) | Query is complex or not parameterized. Consider simplifying or using prepared statements. |
| **Queueing time** | 0 ms | Warehouse concurrency is saturated. Scale out with multi-cluster (see Step 3.3). |

## Remote Read Investigation

If remote reads are > 0% for steady-state queries (after cache is warm), investigate:
1. **Poor clustering** — predicates don't align with clustering keys (see Step 3.2)
2. **Undersized cache** — working set doesn't fit in warehouse cache (see Step 3.2 sizing)
3. **Cold cache** — warehouse was recently resumed or cache hasn't fully populated yet (see Step 3.7 warming)
4. **Cache thrashing** — too many diverse query patterns competing for cache space; consider reducing concurrency or narrowing the hot data set

Include the server-side percentile table, the side-by-side comparison table, and the profile-health verdict in the HTML report (Step 3.12) under a "Server-Side Validation" section.
