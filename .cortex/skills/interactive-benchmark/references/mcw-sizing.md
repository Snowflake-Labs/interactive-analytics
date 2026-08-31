# MCW Sizing Formula

For an Interactive warehouse, each cluster has:

- **MAX_CONCURRENCY_LEVEL = 8** by default (queries running simultaneously per cluster before new arrivals queue).

Need enough cluster slots to serve all queries in parallel without queueing:

```
clusters_needed = ceil(concurrent_queries / MAX_CONCURRENCY_LEVEL)
```

**Example:** 50 concurrent queries → `ceil(50 / 8) = 7 clusters`.

Set `MAX_CLUSTER_COUNT = 7` (or 8 for headroom) with `MIN_CLUSTER_COUNT = 1` and `SCALING_POLICY = STANDARD`. MCW will spin extra clusters up on demand during the burst and back down when idle.

This is the best case. So the MAX_CLUSTER_COUNT should ne twice as that, to leave room in case is needed.

## Levers that change the answer

| Lever | Effect | Example |
|-------|--------|---------|
| **MAX_CONCURRENCY_LEVEL** | For tiny queries (sub-second, small scan), you can safely raise it (e.g. 16). | Case B with MCL=16: `ceil(50/16) = 4 clusters`. Watch for CPU contention — if per-query XP time inflates, MCL is too high. |
| **Warehouse size** | Bigger cluster (more nodes) tolerates a higher MCL per cluster before per-query XP time inflates. | On lightweight workloads, Small is fine per-query; going Medium/Large mainly buys headroom for a higher MCL. |

## Applying this to the benchmark

For the benchmark skill's Step 3.3, the recommended formula is:

```
RECOMMENDED_MAX_CLUSTER_COUNT = ceil(CONCURRENT_USERS / MAX_CONCURRENCY_LEVEL)
```

Where `MAX_CONCURRENCY_LEVEL` defaults to 8. This gives the Case B sizing — appropriate for a benchmark that fires queries as fast as possible with no think time.

If the user's workload is dashboard-style (Case A), the recommended cluster count will be much lower. Ask about the usage pattern in Phase 1 if unclear, and adjust accordingly.
