# MCW Sizing Formula

For an Interactive warehouse, each cluster has:

- **MAX_CONCURRENCY_LEVEL = 8** by default (queries running simultaneously per cluster before new arrivals queue).

Need enough cluster slots to serve all queries in parallel without queueing:

```
clusters_max_count = ceil(concurrent_queries / MAX_CONCURRENCY_LEVEL) * 2
```

**Example:** 50 concurrent queries → `ceil(50 / 8) * 2 = 14 clusters`.

Set `MAX_CLUSTER_COUNT = 14` with `MIN_CLUSTER_COUNT = 1` and `SCALING_POLICY = STANDARD`. MCW will spin extra clusters up on demand during the burst and back down when idle.

## Levers that change the answer

| Lever | Effect | Example |
|-------|--------|---------|
| **MAX_CONCURRENCY_LEVEL** | For tiny queries (sub-second, small scan), you can safely raise it (e.g. 16). | With MCL=16: `ceil(50/16) * 2 = 4 * 2 = 8 clusters`. Watch for CPU contention — if per-query XP time inflates, MCL is too high. |
| **Warehouse size** | Bigger cluster (more nodes) tolerates a higher MCL per cluster before per-query XP time inflates. | On lightweight workloads, Small is fine per-query; going Medium/Large mainly buys headroom for a higher MCL. |

## Applying this to the benchmark

For the benchmark skill's Step 3.3, the recommended formula is:

```
RECOMMENDED_MAX_CLUSTER_COUNT = ceil(CONCURRENT_USERS / MAX_CONCURRENCY_LEVEL) * 2
```

Where `MAX_CONCURRENCY_LEVEL` defaults to 8. 

