# Report Generation Procedure

## Procedure

1. Read the template file from `templates/benchmark-report.html.template` in the skill folder.
2. Substitute every `{{PLACEHOLDER}}` token with the corresponding value collected during Phase 1, Step 2.1, and Phase 3 steps. The template's header comment lists every placeholder and what it expects. Do NOT leave any placeholders unfilled — grep the output file for `{{` before saving to verify.
3. When a section's placeholder expects HTML fragments (e.g. `{{VARIANT_ROWS}}`, `{{BAR_ROWS}}`, `{{RECOMMENDATIONS_TO_MEET_GOAL}}`), emit valid HTML that follows the same tag patterns as the surrounding structure — do not invent new CSS classes.
4. For the pill-class placeholders (`{{P95_INT_SERVER_CLASS}}`, `{{P50_INT_SERVER_CLASS}}`, `{{P50_INT_CLIENT_CLASS}}`, `{{FAILURE_CLASS}}`), pick one of `ok`, `warn`, or `bad` based on whether the value meets/misses the latency goal from Phase 1. **Special case:** if the P95 goal was missed AND the user's scale-out / scale-up ceilings were both reached in Step 3.11, use pill class `bad` and status text `"limit-bound"` instead of `"above goal"`.
5. For the bottleneck verdict box (`{{BOTTLENECK_VERDICT_CLASS}}` and `{{BOTTLENECK_VERDICT}}`), the class must be one of `good`, `note`, or `bad-box`, matching the severity of the diagnosis: `good` if both API and Snowflake meet the goal, `note` if the tail is contained by fallback, `bad-box` if the goal is missed.
6. For the percentile bar rows, compute each `width:N%` value using a shared scale-max per section — see the template's header comment for the sizing rule.

## Coverage Requirement — every section in the template is mandatory

1. Executive Summary tiles (all tiles)
2. Benchmark Setup (`kv` block — must include `{{CLUSTERS_ACTUAL}}` showing actual vs configured cluster count)
3. Query and Filter Variants (primary query + variants table)
4. Table Details (Interactive)
5. Performance Results — Client-side (Locust HTTP), with P50/P95/P99 (all three mandatory)
6. Performance Results — Server-side (Snowflake), with P50/P95/P99 and compile / exec / queue / scan averages and clusters used (mandatory — must appear ALONGSIDE the client-side section, never in place of it)
7. Client vs Server — Bottleneck Diagnosis (delta table + explicit verdict box naming which layer to optimize)
8. Client-Side and Server-Side Percentile Comparison bar charts
9. Query Profile Health (top-slowest table + verdict list)
10. Escalation Path (`{{ITERATION_HISTORY}}` — one iteration entry if no escalation was needed, or the full log of scale-up / scale-out steps taken during Step 3.11)
11. Optimization Recommendations (to-meet-goal / already-ok / general)
12. Configuration Used (compute pools / API / interactive WH / Locust)

If any section is missing from the final HTML, the report is invalid — re-derive the missing placeholder from the collected data and re-emit.

## Verification

- `grep '{{' <output-file>` must return zero matches (all placeholders filled).
- The file must contain each of the 12 section headings above.
- All QUERY_ID values in the report MUST be full and untruncated (e.g. `01b8f3a2-0504-b572-0000-0a6d001f436a`). Never shorten, abbreviate, or use ellipsis — users need to copy-paste them into Snowsight.
