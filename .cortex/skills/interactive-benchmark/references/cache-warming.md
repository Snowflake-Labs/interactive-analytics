# Cache Warming Procedure (Step 3.6)

**Cache warming guidance:**
- If the warehouse was recently resumed, do NOT expect immediate sub-second latency. The cache must be populated first.
- XS warehouses warm at roughly 300–400 MB/s; larger warehouses warm faster.
- For a 100 GB working set on XS, expect ~4–5 minutes of warming time before the cache is fully populated.
- Run the query multiple times (3–5 iterations) to ensure the relevant data pages are cached, not just once.

**Warm-up procedure (execute via `snowflake_sql_execute`, since the SPCS API ingress requires Snowflake auth and can't be curled from the laptop with `externalbrowser` connections):**

**CRITICAL — session state does not persist across `snowflake_sql_execute` calls.** Each call runs in its own session, so a `USE WAREHOUSE` in one call has no effect on subsequent calls. You MUST prepend `USE WAREHOUSE` and `USE SCHEMA` to **every** `snowflake_sql_execute` call, or combine them into a single multi-statement call.

For each warm-up iteration, run a single `snowflake_sql_execute` call containing all setup + query:

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <INTERACTIVE_WAREHOUSE>;
USE SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
<THE QUERY>;
```

Run 3–5 iterations of the above (each as one `snowflake_sql_execute` call). Also warm each *variant* query shape (`benchmark-query-q1.sql`, `benchmark-query-nation.sql`, etc.) at least once — each call must include the `USE WAREHOUSE` and `USE SCHEMA` preamble so the query runs on the interactive warehouse, not the fallback.

Check that the last warm-up iteration shows latency close to expected steady-state (e.g. sub-second for a well-fitted workload). If latency is still high on the final iteration, run more iterations or wait for background cache population to complete.

Discard the results from these warm-up calls — they are not part of the benchmark.
