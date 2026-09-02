# Eval Scenarios

Test scenarios to verify the interactive-benchmark skill works correctly across different inputs and edge cases. Each scenario describes an input, the expected behavior, and how to verify the outcome.

---

## E1: Happy Path — Goal Met Without Escalation

**Input:** TPC-H query (e.g. orders-by-nation) on SF100, 50 concurrent users, P95 <= 1s, connection `PM`, Medium scale-up ceiling, 5 cluster ceiling.

**Expected behavior:**
1. Phase 1 collects all 11 inputs, confirms with user
2. `system_todo_write` called immediately after confirmation with 14 items
3. Phase 2 invokes `snowflake-interactive`, which determines the approach (zero-copy or interactive tables), creates the warehouse, suitability check passes
4. Phase 3 deploys SPCS, warms cache, runs baseline + load test, collects server-side metrics
5. P95 goal met — no escalation triggered
6. HTML report generated from template, opened in browser
7. Cleanup options presented

**Verification:**
- `grep '{{' benchmark-report.html` returns 0 matches
- Report contains all 12 mandatory sections
- Locust CSV shows `/api/run/interactive` row with P95 <= 1000ms
- Server-side P95 from `QUERY_HISTORY_BY_WAREHOUSE` aligns with Locust numbers
- `config.env` values match Phase 1 answers (especially `INTERACTIVE_WAREHOUSE` and `LOCUST_USERS`)

---

## E2: Suitability Rejection — Query Too Slow

**Input:** A heavy full-scan aggregation query that takes >10s on a standard warehouse. Same Phase 1 inputs as E1.

**Expected behavior:**
1. Phase 1 completes normally
2. Phase 2 runs query on standard warehouse — exceeds 10 seconds
3. Skill STOPs at the suitability gate with a clear explanation
4. `snowflake-interactive` skill invoked for improvement recommendations
5. No SPCS deployment occurs
6. No HTML report generated

**Verification:**
- No compute pools or SPCS services created
- User receives specific reason why the query failed the gate
- Recommendations provided (query rewrite, clustering, narrower predicates)

---

## E3: Suitability Rejection — No Interactive Speedup

**Input:** A query that runs in ~3s on both standard and interactive warehouses (no speedup from caching).

**Expected behavior:**
1. Phase 2 runs query on both warehouses
2. Interactive is NOT significantly faster (< 1.5x speedup)
3. Skill STOPs with explanation that the query doesn't benefit from interactive
4. Recommendations provided for what query characteristics would benefit

**Verification:**
- Timing comparison table shown to user
- Clear explanation of why no speedup occurred
- No SPCS deployment

---

## E4: Escalation — Scale Out Then Meet Goal

**Input:** Query that meets the 5s interactive gate at rest, but P95 > 1s under 50 concurrent users due to queueing. Scale-up ceiling: Medium, scale-out ceiling: 5 clusters, max iterations: 5.

**Expected behavior:**
1. First load test: server-side `AVG_QUEUE_MS > 0`, P95 misses goal
2. Skill automatically increases `MAX_CLUSTER_COUNT` (no user prompt)
3. Cache re-warmed after cluster count change
4. Load test re-run via Locust service restart
5. Goal met after 1-2 escalation iterations

**Verification:**
- Iteration history log shows starting config, each escalation step, and final result
- No user confirmation requested during escalation (autonomous principle)
- `{{ITERATION_HISTORY}}` placeholder in report filled with escalation path
- Each `locust-run-N.txt` file preserved in reports directory

---

## E5: Limit-Bound — Goal Not Achievable

**Input:** P95 <= 100ms target (very aggressive), scale-up ceiling: X-Small, scale-out ceiling: 2 clusters, max iterations: 3.

**Expected behavior:**
1. Load test runs, P95 misses 100ms goal
2. Skill escalates within limits (max 2 clusters already, X-Small ceiling prevents scale-up)
3. After exhausting both limits, skill STOPs and asks user
4. Report generated with "not met — limit-bound" verdict
5. Options presented: relax ceilings, redesign query, accept performance

**Verification:**
- Executive summary tile shows `limit-bound` status with `bad` pill class
- Escalation capped at max iterations value (3)
- User asked for decision only after limits exhausted, not before

---

## E6: Config Drift — Re-run With Different Settings

**Input:** Run E1 first. Then re-invoke the skill with a different warehouse name and different concurrent user count, same `SOLUTION_NAME`.

**Expected behavior:**
1. Skill detects existing `config.env` and `.env` from previous run
2. Overwrites stale values with new Phase 1 answers (especially `INTERACTIVE_WAREHOUSE` and `LOCUST_USERS`)
3. `grep` sanity check confirms no leftover placeholders or stale values
4. If `SPCS_DEPLOYED=true` in `.env`, skips redeployment and reuses existing services

**Verification:**
- `config.env` contains the NEW warehouse name and user count, not the old ones
- Load test runs against the correct warehouse with the correct concurrency
- Locust CSV `Request Count` is proportional to the new user count, not the old one

---

## E7: Infrastructure Failure — Baseline Fails

**Input:** Same as E1, but API compute pool is undersized (e.g. 1 node, 1 instance) for 50 users.

**Expected behavior:**
1. SPCS deploys successfully
2. Baseline test runs and detects high failure rate or p99 > 500ms
3. `[baseline] VERDICT: FAIL` logged with remediation suggestions
4. Benchmark phase does NOT run
5. Skill reports the baseline failure to the user

**Verification:**
- No `/api/run/interactive` results in Locust CSV (only baseline)
- User receives specific remediation suggestions (increase API instances/nodes or reduce users)
- Stopping point at Step 3.8 triggered

---

## E9: Zero-Copy Path — Source Tables Already Clustered

**Input:** TPC-H LINEITEM query filtered on `L_SHIPDATE` (the table's existing clustering key) on SF100, 50 concurrent users, P95 <= 1s, connection `PM`, Medium scale-up ceiling, 5 cluster ceiling.

**Expected behavior:**
1. Phase 1 collects all 11 inputs, confirms with user
2. Phase 2 invokes `snowflake-interactive`, which detects that LINEITEM is already clustered on `L_SHIPDATE` (matching the query's WHERE predicate) and chooses **zero-copy mode**
3. `INTERACTIVE_MODE` = `zero-copy`, `INTERACTIVE_SCHEMA` = source schema (no new schema created)
4. No `CREATE INTERACTIVE TABLE` or CTAS executed — no data copied
5. Step 3.2 validates via Mode A path (checks warehouse exists, clustering alignment, working set sizing)
6. No `SHOW INTERACTIVE TABLES` executed (expected — zero-copy has none)
7. Phase 3 deploys SPCS, warms cache, runs load test normally
8. Cleanup step does NOT offer to drop `INTERACTIVE_SCHEMA` (it is the source schema)

**Verification:**
- No interactive tables created in any schema
- `config.env` `INTERACTIVE_SCHEMA` matches the source schema name (not a `_INT` suffixed copy)
- Step 3.2 logs show Mode A (zero-copy) validation, not Mode B
- Cleanup resource table does not list "Interactive schema" or "Interactive tables" rows
- `DROP SCHEMA` for `INTERACTIVE_SCHEMA` is NOT in the cleanup SQL
- Report correctly identifies the mode as zero-copy in the executive summary

---

## E10: Template Integrity

**Applies to every run.** After the HTML report is generated:

**Verification:**
- `grep '{{' benchmark-report.html` returns 0 matches (no unfilled placeholders)
- Report contains all 12 mandatory section headings (per `references/report-generation.md`)
- All QUERY_ID values are full 36-character UUIDs (not truncated)
- Pill classes are one of `ok`, `warn`, `bad`
- Bottleneck verdict class is one of `good`, `note`, `bad-box`
