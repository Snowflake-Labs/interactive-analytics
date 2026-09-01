# Suitability Check — Phase 2 Detail

## Step 2.1: Invoke `snowflake-interactive` Skill

Invoke the `snowflake-interactive` skill to analyze the query and set up the interactive warehouse. The skill will determine the best approach — **zero-copy interactive** or **interactive tables** — based on the source data characteristics.

**Do this by calling:**
```
skill(command="snowflake-interactive")
```

Provide the skill with:
- The database and schema from Phase 1
- The query to benchmark
- The standard warehouse name — **explicitly state that this warehouse must be used for all DDL, table creation, and CTAS operations** (if interactive tables turn out to be needed)

**The `snowflake-interactive` skill owns the zero-copy vs interactive-table decision.** Do NOT pre-decide which path to use — let the skill's decision tree determine whether the source tables can be queried directly (zero-copy) or need to be copied into interactive tables. The skill considers:
- Whether the source tables' existing clustering keys align with the query's WHERE/JOIN predicates
- Whether the working set fits the target interactive warehouse cache
- Whether the tables are standard or Iceberg (both support zero-copy)

### Possible outcomes

**Path A — Zero-copy interactive (preferred when viable):**
The skill determines the source tables can be queried directly from an interactive warehouse without copying data. In this case:
- `INTERACTIVE_SCHEMA` = the **source schema** (no new schema or tables created)
- `INTERACTIVE_WAREHOUSE` = an interactive warehouse created/configured to query those tables directly
- `OPTIMIZED_QUERY` = the original query (or a rewritten version), referencing the source tables
- `INTERACTIVE_MODE` = `zero-copy`

No data is copied. No interactive tables are created. The interactive warehouse queries the original tables.

**Path B — Interactive tables (when zero-copy is not suitable):**
The skill determines that interactive tables are needed (e.g., clustering misalignment, source tables lack clustering, or other factors). In this case:
- `INTERACTIVE_SCHEMA` = a new schema containing interactive table copies
- `INTERACTIVE_WAREHOUSE` = an interactive warehouse with `TARGET_LAG` attached to those tables
- `OPTIMIZED_QUERY` = the query rewritten for the interactive schema
- `INTERACTIVE_MODE` = `interactive-tables`

**CRITICAL — Use the standard warehouse for all DDL (Path B only):**
Interactive warehouses reject DDL and CTAS operations. Both `CREATE INTERACTIVE TABLE ... AS SELECT` and `CREATE TABLE ... AS SELECT` will fail with errors like:
- `Warehouse '...' must not be an interactive warehouse`
- `Cannot run statement type 'CREATE_TABLE_AS_SELECT' on an interactive warehouse`

When the skill needs to create interactive tables, it MUST use the **standard warehouse** (from Phase 1) for all DDL. The interactive warehouse should only be used for running SELECT queries after setup is complete.

Capture the output:
- `INTERACTIVE_WAREHOUSE` — name of the interactive warehouse created (and its size)
- `INTERACTIVE_SCHEMA` — schema with interactive tables (Path B) or the source schema (Path A)
- `OPTIMIZED_QUERY` — the query rewritten for the interactive schema (if different)
- `INTERACTIVE_MODE` — `zero-copy` or `interactive-tables`

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

If the standard warehouse timing is acceptable (under 10 seconds), run the query on the interactive warehouse via `snowflake_sql_execute`. **Use `INTERACTIVE_SCHEMA` — which is the source schema for zero-copy or the interactive tables schema for interactive-table mode:**

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
