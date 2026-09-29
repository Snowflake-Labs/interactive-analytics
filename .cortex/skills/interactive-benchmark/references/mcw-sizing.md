# MCW Sizing Formula

For an Interactive warehouse, each cluster has:

- **MAX_CONCURRENCY_LEVEL = 8** by default (queries running simultaneously per cluster before new arrivals queue).

Size clusters from the number of queries **in flight**, not the number of Locust users. Each Locust user waits `wait_time = between(0.5, 1.5)` seconds (mean `THINK_TIME_S = 1.0`) between requests, so a user only has a query running for part of the time. By Little's law:

```
in_flight_queries  = CONCURRENT_USERS * QUERY_LATENCY_S / (QUERY_LATENCY_S + THINK_TIME_S)
clusters_min_count = max(1, ceil(in_flight_queries / MAX_CONCURRENCY_LEVEL))
clusters_max_count = clusters_min_count * 2
```

`QUERY_LATENCY_S` is the warm interactive latency measured in the suitability check (Phase 2).

**Example:** 50 users, 0.3 s queries → `50 * 0.3 / 1.3 = 11.5` in flight → `ceil(11.5 / 8) = 2` → `MIN_CLUSTER_COUNT = 2`, `MAX_CLUSTER_COUNT = 4`. Treating the 50 users as 50 concurrent queries would give 7 / 14 clusters, and the minimum clusters bill continuously.

Set `SCALING_POLICY = STANDARD`. MCW spins extra clusters up on demand during the burst and back down when idle. If the load test shows `AVG_QUEUE_MS > 0`, escalation scales out.

**After a load test, re-derive the estimate from measurements:** `in_flight_queries = (N / run_seconds) * (AVG_MS / 1000)` using the server-side `N` and `AVG_MS` from `references/server-side-validation.md`.

## Levers that change the answer

| Lever | Effect | Example |
|-------|--------|---------|
| **MAX_CONCURRENCY_LEVEL** | For tiny queries (sub-second, small scan), you can safely raise it (e.g. 16). | 20 in flight with MCL=16: `ceil(20/16) = 2` → MIN=2, MAX=4. Watch for CPU contention — if per-query XP time inflates, MCL is too high. |
| **Warehouse size** | Bigger cluster (more nodes) tolerates a higher MCL per cluster before per-query XP time inflates. | On lightweight workloads, Small is fine per-query; going Medium/Large mainly buys headroom for a higher MCL. |
