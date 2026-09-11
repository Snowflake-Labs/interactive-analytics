# Benchmark Queries

Place `.sql` files in this directory. Each file should contain a single SQL query
that will be benchmarked against the interactive warehouse under concurrent load.

During deployment, these files are uploaded to a Snowflake internal stage
(`@BENCHMARK_QUERIES`) and mounted into the API container at `/app/test/`.
The API server reads all `*.sql` files from that path and registers them as
available queries, keyed by filename stem (e.g. `benchmark-query.sql` →
`query_id: "benchmark-query"`).

To update queries without rebuilding Docker images, edit files here and run:

```bash
.cortex/skills/interactive-benchmark/benchmark/scripts/update.sh --queries-only
```

## Conventions

- One query per file
- Use fully-qualified table names or rely on the server's configured database/schema
- Files are read in alphabetical order
