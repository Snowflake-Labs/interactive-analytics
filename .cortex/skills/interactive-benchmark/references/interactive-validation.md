# Interactive Setup Validation (Step 3.2)

Verify the interactive setup is correct before deploying. The validation differs depending on the `INTERACTIVE_MODE` captured in Step 2.1.

---

## Mode A — Zero-copy (`INTERACTIVE_MODE = zero-copy`)

In zero-copy mode the interactive warehouse queries the **original source tables** directly. There are no interactive tables to verify. Instead, validate:

**1. Verify the interactive warehouse exists and is running** (via `snowflake_sql_execute`):

```sql
SHOW WAREHOUSES LIKE '<INTERACTIVE_WAREHOUSE>';
```

Confirm the warehouse type is `INTERACTIVE` (or `SNOWPARK-OPTIMIZED` with interactive capabilities, depending on the account).

**2. Verify source table clustering aligns with query predicates:**

For each source table referenced by the query, check its clustering key (via `snowflake_sql_execute`):

```sql
SHOW TABLES LIKE '<TABLE_NAME>' IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Compare the `cluster_by` column against the columns used in the query's WHERE/JOIN predicates. For zero-copy to perform well, the source tables' clustering should align with the query's filter and join columns. If clustering is missing or misaligned, warn the user — the `snowflake-interactive` skill should have caught this, but verify as a safety net.

**3. Validate working set sizing** (via `snowflake_sql_execute`):

```sql
SELECT TABLE_NAME, BYTES / (1024*1024*1024) AS SIZE_GB
FROM <DATABASE>.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '<INTERACTIVE_SCHEMA>';
```

Compare total working set size against the interactive warehouse size:
- XS: up to ~350 GB working set
- S: up to ~600 GB
- M: up to ~1200 GB
- L: up to ~2500 GB
- XL+: larger working sets

**If validation fails** (warehouse not found, severe clustering misalignment, or working set exceeds warehouse cache capacity): inform the user which check failed, then jump to Step 3.14 (cleanup).

---

## Mode B — Interactive tables (`INTERACTIVE_MODE = interactive-tables`)

**1. Verify interactive tables are attached to the interactive warehouse** (via `snowflake_sql_execute`):

```sql
SHOW INTERACTIVE TABLES IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Confirm that each table referenced by the query appears in the output and that the `warehouse_name` column shows the `INTERACTIVE_WAREHOUSE`.

**2. Verify predicates align with clustering keys:**

For each interactive table, check its clustering key (via `snowflake_sql_execute`):

```sql
SHOW TABLES LIKE '<TABLE_NAME>' IN SCHEMA <DATABASE>.<INTERACTIVE_SCHEMA>;
```

Compare the `cluster_by` column against the columns used in the query's WHERE/JOIN predicates.

**Every interactive table MUST have a `CLUSTER BY`, including tiny dimension/lookup tables.** `CREATE INTERACTIVE TABLE` fails with `An interactive table must contain clustering keys` if omitted. For lookup tables with no natural filter column (e.g. `NATION` with 25 rows, `REGION` with 5 rows), cluster on the primary key column:

```sql
CREATE INTERACTIVE TABLE <SCHEMA>.NATION CLUSTER BY (N_NATIONKEY) AS SELECT * FROM <SRC>.NATION;
CREATE INTERACTIVE TABLE <SCHEMA>.REGION CLUSTER BY (R_REGIONKEY) AS SELECT * FROM <SRC>.REGION;
```

**3. Validate working set sizing** (via `snowflake_sql_execute`):

```sql
SELECT TABLE_NAME, BYTES / (1024*1024*1024) AS SIZE_GB
FROM <DATABASE>.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '<INTERACTIVE_SCHEMA>';
```

Compare total working set size against the interactive warehouse size:
- XS: up to ~350 GB working set
- S: up to ~600 GB
- M: up to ~1200 GB
- L: up to ~2500 GB
- XL+: larger working sets

**If any validation fails** (no interactive tables found, tables not attached to the expected warehouse, missing clustering keys, or working set exceeds warehouse cache capacity): inform the user which check failed and why, then jump to Step 3.14 (cleanup) — the benchmark cannot proceed with an invalid interactive setup.
