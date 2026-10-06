# Server-Side Validation Reference

## SQL Queries

Three rules make the server-side numbers comparable to the Locust numbers:

- **Filter on `QUERY_TAG`.** The API tags every benchmark query with `SOLUTION_NAME`. Warm-up, suitability, and deploy-preflight queries run on the same interactive warehouse without that tag and must not be counted.
- **Use the Locust run window, not "the last N minutes".** The tag is the same for every escalation iteration, so the time window is what separates iterations. The `BENCHMARK RESULTS` banner prints the last rows of `locust_stats_stats_history.csv`; its first column is a Unix timestamp. `RUN_END` = the last row's timestamp, `RUN_START` = `RUN_END` − `LOCUST_RUN_TIME` in seconds.
- **Keep the run window as Unix epoch seconds.** Pass those numeric values
  directly to `TO_TIMESTAMP_LTZ` as shown below. Do not copy UTC clock strings
  from the Locust logs or manually offset them to the Snowflake session
  timezone; epoch values identify the same instant in every session timezone.
- **Keep failed and fallback-served queries.** Locust's percentiles include failed requests, so success-only server percentiles make the client-server delta look like API overhead. A query that hits the 5 s interactive timeout is retried on the fallback warehouse under the **same query ID**; whether history attributes it to the interactive or the fallback warehouse is not guaranteed, so collect both warehouses and de-duplicate by `QUERY_ID`. A successful query with `TOTAL_ELAPSED_TIME` above 5000 ms can only have been served by the fallback.

`QUERY_HISTORY_BY_WAREHOUSE` returns at most 10,000 rows per call and returns the newest rows first, so a single call over a 3-minute run can silently drop the beginning of the run. Collect the window in 60-second slices into a table.

### 1. Collect the run's query history (one `snowflake_sql_execute` call per iteration)

Replace `<N>` with the iteration number. Add one `INSERT` per 60-second slice per warehouse until the slices cover `RUN_START`–`RUN_END`.

```sql
USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <SOLUTION_NAME>_DB.SPCS;

CREATE OR REPLACE TABLE QH_RUN_<N> AS
SELECT * FROM TABLE(<SOLUTION_NAME>_DB.INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  END_TIME_RANGE_START => TO_TIMESTAMP_LTZ(<RUN_START>),
  END_TIME_RANGE_END => TO_TIMESTAMP_LTZ(<RUN_START + 60>),
  RESULT_LIMIT => 10000))
WHERE QUERY_TAG = '<SOLUTION_NAME>';

INSERT INTO QH_RUN_<N>
SELECT * FROM TABLE(<SOLUTION_NAME>_DB.INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
  WAREHOUSE_NAME => '<INTERACTIVE_WAREHOUSE>',
  END_TIME_RANGE_START => TO_TIMESTAMP_LTZ(<RUN_START + 60>),
  END_TIME_RANGE_END => TO_TIMESTAMP_LTZ(<RUN_START + 120>),
  RESULT_LIMIT => 10000))
WHERE QUERY_TAG = '<SOLUTION_NAME>';

-- ... remaining slices, then the same slices for WAREHOUSE_NAME => '<STANDARD_WAREHOUSE>' (the fallback)

SELECT WAREHOUSE_NAME, DATE_TRUNC('minute', END_TIME) AS SLICE, COUNT(*) AS N
FROM QH_RUN_<N> GROUP BY 1, 2 ORDER BY 1, 2;
```

If any slice has close to 10,000 rows, it was truncated: re-collect with 30-second slices. The `QH_RUN_<N>` tables are dropped with `<SOLUTION_NAME>_DB` at cleanup.

### 2. Aggregate server-side percentiles

```sql
USE WAREHOUSE <STANDARD_WAREHOUSE>;
WITH q AS (
  SELECT * FROM <SOLUTION_NAME>_DB.SPCS.QH_RUN_<N>
  QUALIFY ROW_NUMBER() OVER (PARTITION BY QUERY_ID ORDER BY END_TIME DESC) = 1
)
SELECT
  COUNT(*) AS N,
  COUNT_IF(EXECUTION_STATUS <> 'SUCCESS') AS N_FAILED,
  COUNT_IF(EXECUTION_STATUS = 'SUCCESS'
           AND (WAREHOUSE_NAME = '<STANDARD_WAREHOUSE>' OR TOTAL_ELAPSED_TIME > 5000)) AS N_FALLBACK,
  -- All requests, comparable to Locust's percentiles. Use these for the goal check.
  AVG(TOTAL_ELAPSED_TIME)::INT AS AVG_MS,
  MEDIAN(TOTAL_ELAPSED_TIME)::INT AS P50_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.90)::INT AS P90_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95)::INT AS P95_MS,
  APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.99)::INT AS P99_MS,
  -- Queries served entirely by the interactive warehouse.
  APPROX_PERCENTILE(IFF(EXECUTION_STATUS = 'SUCCESS' AND TOTAL_ELAPSED_TIME <= 5000,
                        TOTAL_ELAPSED_TIME, NULL), 0.95)::INT AS P95_INTERACTIVE_ONLY_MS,
  AVG(COMPILATION_TIME)::INT AS AVG_COMPILE_MS,
  AVG(EXECUTION_TIME)::INT AS AVG_EXEC_MS,
  AVG(QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME)::INT AS AVG_QUEUE_MS,
  (AVG(BYTES_SCANNED) / (1024*1024))::INT AS AVG_MB_SCAN,
  COUNT(DISTINCT IFF(WAREHOUSE_NAME = '<INTERACTIVE_WAREHOUSE>', CLUSTER_NUMBER, NULL)) AS DISTINCT_CLUSTERS_USED,
  MAX(IFF(WAREHOUSE_NAME = '<INTERACTIVE_WAREHOUSE>', CLUSTER_NUMBER, NULL)) AS PEAK_CLUSTER_NUMBER
FROM q;
```

`N` should be close to the Locust `Request Count` for `/api/run/interactive`. A large gap means the window, the tag, or the slicing is wrong — fix that before reporting any numbers. Report `N_FAILED` and `N_FALLBACK` next to the percentiles.

### 3. Client-vs-server delta table

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

### 4. Pick outliers and inspect Query Profile

**IMPORTANT: QUERY_ID values must ALWAYS be included in their full, untruncated form (e.g. `01b8f3a2-0504-b572-0000-0a6d001f436a`). Never shorten, abbreviate, or use ellipsis for query IDs — the user needs to copy-paste them directly into Snowsight.**

```sql
USE WAREHOUSE <STANDARD_WAREHOUSE>;
SELECT
  QUERY_ID,
  EXECUTION_STATUS,
  ERROR_CODE,
  WAREHOUSE_NAME,
  WAREHOUSE_SIZE,
  CLUSTER_NUMBER,
  TOTAL_ELAPSED_TIME,
  COMPILATION_TIME,
  EXECUTION_TIME,
  QUEUED_PROVISIONING_TIME + QUEUED_OVERLOAD_TIME AS QUEUED_MS,
  BYTES_SCANNED
FROM <SOLUTION_NAME>_DB.SPCS.QH_RUN_<N>
QUALIFY ROW_NUMBER() OVER (PARTITION BY QUERY_ID ORDER BY END_TIME DESC) = 1
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 20;
```

`QUERY_HISTORY_BY_WAREHOUSE` has no cache or remote-read column. Read remote-read % from the Query Profile of these query IDs (or `GET_QUERY_OPERATOR_STATS('<QUERY_ID>')`).

## Query Profile Health Metrics

| Metric | Target | What it means if bad |
|--------|--------|---------------------|
| **Remote read %** | 0% | Query is reading from remote storage instead of cache. Causes: poor clustering, undersized working-set cache, cold cache, or cache thrashing. |
| **Bytes scanned** | Minimal (ideally <100 GB) | Partition pruning is not effective. Check clustering keys and predicate alignment. |
| **Compile time** | Low (< 50 ms) | Query is complex or not parameterized. Consider simplifying or using prepared statements. |
| **Queueing time** | 0 ms | Warehouse concurrency is saturated. Scale out with multi-cluster (see Step 3.2). |

## Remote Read Investigation

If remote reads are > 0% for steady-state queries (after cache is warm), investigate:
1. **Poor clustering** — predicates don't align with clustering keys (see Step 3.1)
2. **Undersized cache** — working set doesn't fit in warehouse cache (see Step 3.1 sizing)
3. **Cold cache** — warehouse was recently resumed or cache hasn't fully populated yet (see Step 3.5 warming)
4. **Cache thrashing** — too many diverse query patterns competing for cache space; consider reducing concurrency or narrowing the hot data set

Include the server-side percentile table, the side-by-side comparison table, and the profile-health verdict in the HTML report (Step 3.12) under a "Server-Side Validation" section.
