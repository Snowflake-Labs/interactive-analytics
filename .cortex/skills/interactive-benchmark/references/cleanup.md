# Resource Summary and Cleanup — Step 3.14 Detail

After the report is generated, present the user with a **complete list of all Snowflake resources created during this benchmark session**. Format it as a clear table:

| Resource Type | Name | Location |
|---|---|---|
| Interactive warehouse | `<INTERACTIVE_WAREHOUSE>` | Account-level |
| Interactive schema | `<DATABASE>.<INTERACTIVE_SCHEMA>` | Contains interactive tables |
| Interactive tables | `<TABLE_1>`, `<TABLE_2>`, ... | In `<INTERACTIVE_SCHEMA>` |
| SPCS database | `<SOLUTION_NAME>_BENCH_DB` | Account-level |
| SPCS schema | `<SOLUTION_NAME>_BENCH_DB.SPCS` | Contains services + image repo |
| Compute pool (API) | `<SOLUTION_NAME>_BENCH_API_POOL` | Account-level |
| Compute pool (Locust) | `<SOLUTION_NAME>_BENCH_LOCUST_POOL` | Account-level |
| Image repository | `<SOLUTION_NAME>_BENCH_IMAGES` | In SPCS schema |
| Service (API) | `BENCHMARK_API` | In SPCS schema |
| Service (Locust) | `BENCHMARK_LOCUST` | In SPCS schema |

Then use `ask_user_question` to ask the user: **"Would you like me to clean up these resources, or keep them for further benchmarking?"** with the following three options:
1. **Full cleanup** — tear down everything (SPCS services, compute pools, interactive tables, warehouse, schemas)
2. **Tear down SPCS only** — remove services and compute pools but keep the interactive warehouse and tables
3. **Keep everything** — leave all resources running for re-runs

If the user chooses **full cleanup**, use the `bash` tool:
```bash
cd <SKILL_DIR>/benchmark/scripts && ./teardown.sh
```

Then drop the schemas and warehouse via `snowflake_sql_execute`:

```sql
USE ROLE <ROLE>;
DROP SCHEMA IF EXISTS <DATABASE>.<INTERACTIVE_SCHEMA>;
DROP SCHEMA IF EXISTS <SOLUTION_NAME>_BENCH_DB.SPCS;
DROP WAREHOUSE IF EXISTS <INTERACTIVE_WAREHOUSE>;
```

If the SPCS database was created entirely by this benchmark and is now empty, also drop it via `snowflake_sql_execute`:

```sql
DROP DATABASE IF EXISTS <SOLUTION_NAME>_BENCH_DB;
```

If the user chooses **SPCS only**, use the `bash` tool:
```bash
cd <SKILL_DIR>/benchmark/scripts && ./teardown.sh
```

If the user chooses to **keep everything**, use the `edit` tool to append the deployment state to `benchmark/.env` so future runs reuse the existing services instead of redeploying:

```
# Existing entries
CONNECTION_NAME=<connection>
SOLUTION_NAME=<name>

# SPCS deployment state (added when services are kept)
SPCS_DEPLOYED=true
SPCS_API_INGRESS_URL=<the ingress URL>
SPCS_LOCUST_INGRESS_URL=<the locust ingress URL>
```

On future invocations of this skill, use `read` to check `benchmark/.env` for `SPCS_DEPLOYED=true`. If set, skip Step 3.6 (Deploy to SPCS) and reuse the saved ingress URLs for cache warming and load testing. If the user later wants to tear down, use `bash` to run `./teardown.sh` and `edit` to remove the `SPCS_*` lines from `.env`.

Verify final service state using the `bash` tool:

```bash
cd <SKILL_DIR>/benchmark/scripts && ./status.sh
```

Options:
- `./status.sh --wait` — poll until all services are READY
- `./status.sh --urls-only` — print only ingress URLs
