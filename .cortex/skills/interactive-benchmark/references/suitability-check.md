# Suitability Check — Phase 2 Detail

## Step 2.1: Invoke `snowflake-interactive` Skill

Invoke the `snowflake-interactive` skill to:
- Analyze the query for interactive warehouse suitability
- Create interactive tables (copies of the source tables with appropriate clustering)
- Create an interactive warehouse attached to those tables
- Optimize the query for interactive warehouse execution

**CRITICAL — Use the standard warehouse for all DDL:**
Interactive warehouses reject DDL and CTAS operations. Both `CREATE INTERACTIVE TABLE ... AS SELECT` and `CREATE TABLE ... AS SELECT` will fail with errors like:
- `Warehouse '...' must not be an interactive warehouse`
- `Cannot run statement type 'CREATE_TABLE_AS_SELECT' on an interactive warehouse`

When invoking the `snowflake-interactive` skill, you MUST explicitly instruct it to use the **standard warehouse** (from Phase 1) for creating interactive tables and any other DDL. The interactive warehouse should only be used for running SELECT queries after the tables are created and attached.

**Do this by calling:**
```
skill(command="snowflake-interactive")
```

Provide the skill with:
- The database and schema from Phase 1
- The query to benchmark
- The standard warehouse name — **explicitly state that this warehouse must be used for all DDL, table creation, and CTAS operations**

The `snowflake-interactive` skill will:
- Create interactive tables (copies of the source tables optimized for interactive workloads)
- Determine the best size for the interactive warehouse based on the data and workload characteristics
- Create an interactive warehouse with `TARGET_LAG` attached to those tables
- Return the warehouse name and schema name to use

Capture the output:
- `INTERACTIVE_WAREHOUSE` — name of the interactive warehouse created (and its size)
- `INTERACTIVE_SCHEMA` — schema with interactive tables
- `OPTIMIZED_QUERY` — the query rewritten for the interactive schema (if different)

## Step 2.2: Suitability Check

**This is the critical gate. If the query fails this check, STOP and do not proceed to Phase 3.**

Run the query on the standard warehouse first (disable result caching). Execute each statement via `snowflake_sql_execute`:

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <STANDARD_WAREHOUSE>;
USE SCHEMA <DATABASE>.<SCHEMA>;
<THE QUERY>;
```

**10-second rule:** If the query exceeds 10 seconds on a standard warehouse despite proper clustering and optimization, it is highly improbable to meet the 5-second interactive execution threshold. **STOP HERE** and inform the user that the query needs further optimization before it can benefit from an interactive warehouse. Use the `snowflake-interactive` skill to provide improvement suggestions (query changes, better clustering, etc.).

If the standard warehouse timing is acceptable (under 10 seconds), run the query on the interactive warehouse via `snowflake_sql_execute`:

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
USE WAREHOUSE <INTERACTIVE_WAREHOUSE>;
USE SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
<THE QUERY>;
```

Compare the two elapsed times. Present the results to the user:

| Warehouse | Elapsed |
|---|---|
| Standard (`<STANDARD_WAREHOUSE>`) | X ms |
| Interactive (`<INTERACTIVE_WAREHOUSE>`) | Y ms |

**Decision gate — STOP or PROCEED:**

- **PROCEED** — Interactive is significantly faster (>=1.5x speedup) and completes in under 5 seconds. Move to Phase 3.
- **STOP — query exceeds 5 seconds on interactive even at rest.** Interactive warehouses cancel SELECT statements after 5 seconds by design. The query is not suitable for interactive execution. Invoke the `snowflake-interactive` skill to analyze why and provide improvement recommendations:
  - Query rewrites (fewer joins, narrower predicates, pre-aggregation)
  - Better clustering keys on the tables
  - Reducing data scanned (partition pruning alignment)
  - Whether a subset of the data would work
- **STOP — performance is similar or standard is faster.** The query is not a good candidate for interactive warehouses. Explain why (full table scan, aggregation pattern doesn't benefit from caching, too complex with many joins/subqueries). Use the `snowflake-interactive` skill to suggest what characteristics would make the query work well: point lookups, selective filters, dashboard-style queries on hot data, parameterized shapes (date ranges, customer IDs). The ideal workload is narrow and selective: few columns, targeted predicates, bounded time windows, small result sets. At least 100GB of data is needed for interactive analytics to be really effective.

**When stopping:** Provide the user with a clear summary including:
1. Why the query is not suitable (specific reason)
2. What the `snowflake-interactive` skill recommends to improve it
3. Whether a modified version of the query could work
