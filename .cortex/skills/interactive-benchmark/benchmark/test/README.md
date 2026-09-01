# Benchmark Queries

Place `.sql` files in this directory. Each file should contain a single SQL query
that will be benchmarked against the interactive warehouse under concurrent load.

The benchmark tool reads all `*.sql` files from this folder and executes them
via the API server's `/api/run/interactive` endpoint.

## Conventions

- One query per file
- Use fully-qualified table names or rely on the server's configured database/schema
- Files are read in alphabetical order
