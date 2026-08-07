# Plan — Extract shared `ConnectionPool` between `benchmark/` and `tpc-h-sample-dashboard/`

Saved so we can resume later. Confirmed decisions from the last planning turn:

- Scope: **only the `ConnectionPool`** (not conn kwargs, not launcher, not serialization, not middleware).
- Packaging: **uv workspace** at repo root.
- Docker: **unify build contexts to the repo root** (dashboard side moves).

## Context

- `tpc-h-sample-dashboard/api/server.py:228–304` — bounded blocking `ConnectionPool`
  (`Semaphore` + idle `Queue` + `POOL_ACQUIRE_TIMEOUT`, with `warmup()`). Key: `(target, scale)`.
- `benchmark/api/server.py:83–117` — old "burst" pool. Key: `(target,)`.
- Both projects use uv (`uv sync --frozen --no-dev --no-install-project`).
- Dashboard Docker build context is `tpc-h-sample-dashboard/`; benchmark's is the repo root.
- No root `pyproject.toml` currently exists.
- The post-fix pool raises `fastapi.HTTPException` directly — must be decoupled.

## Design decisions

- Pool is decoupled from Snowflake config: takes an opaque string `key` + a
  `connect(key) -> SnowflakeConnection` factory. Callers build their own key
  (`f"{target}:{scale}"` or `target`) and factory closure.
- Pool is decoupled from FastAPI: define plain `PoolTimeoutError`. Each server maps
  it to HTTP 503 in an exception handler.

## Repo layout after refactor

```
interactive-analytics/
├── pyproject.toml                          # NEW: workspace root
├── uv.lock                                  # NEW: single shared lock
├── common/
│   └── iw_api_common/
│       ├── pyproject.toml                  # NEW: package (name = iw-api-common)
│       └── iw_api_common/
│           ├── __init__.py                 # NEW: re-export
│           └── connection_pool.py          # NEW: extracted class + PoolTimeoutError
├── benchmark/
│   └── api/
│       ├── pyproject.toml                  # MODIFIED: add iw-api-common workspace dep
│       └── server.py                       # MODIFIED: import + adapt call sites
└── tpc-h-sample-dashboard/
    └── api/
        ├── pyproject.toml                  # MODIFIED: add iw-api-common workspace dep
        └── server.py                       # MODIFIED: import + adapt call sites
```

Old `benchmark/api/uv.lock` and `tpc-h-sample-dashboard/api/uv.lock` get deleted.

## Implementation steps

### 1. Shared package
`common/iw_api_common/pyproject.toml`:
```toml
[project]
name = "iw-api-common"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["snowflake-connector-python>=3.12"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["iw_api_common"]
```

`common/iw_api_common/iw_api_common/connection_pool.py`:
```python
class PoolTimeoutError(RuntimeError):
    """Raised by ConnectionPool.acquire() when the wait times out."""

class ConnectionPool:
    def __init__(
        self,
        *,
        size: int,
        connect: Callable[[str], SnowflakeConnection],
        acquire_timeout: float = 30.0,
    ) -> None: ...
    def acquire(self, key: str) -> SnowflakeConnection: ...
    def release(self, key: str, conn: SnowflakeConnection) -> None: ...
    def warmup(self, key: str, count: int | None = None) -> int: ...
```

`__init__.py` re-exports `ConnectionPool` and `PoolTimeoutError`.

### 2. Workspace root
`pyproject.toml` at repo root:
```toml
[project]
name = "interactive-analytics"
version = "0"
requires-python = ">=3.11"

[tool.uv.workspace]
members = [
    "common/iw_api_common",
    "benchmark/api",
    "tpc-h-sample-dashboard/api",
]
```

Regenerate a single root `uv.lock`; delete per-project locks.

### 3. Update both api pyproject.tomls
Add:
```toml
dependencies = [
    ...,
    "iw-api-common",
]

[tool.uv.sources]
iw-api-common = { workspace = true }
```

### 4. Refactor `tpc-h-sample-dashboard/api/server.py`
- Delete lines 228–304 (pool class).
- `from iw_api_common import ConnectionPool, PoolTimeoutError`
- Build local factory:
  ```python
  def _connect(key: str) -> snowflake.connector.SnowflakeConnection:
      target, scale = key.split(":", 1)
      return snowflake.connector.connect(**connection_kwargs_for(target, scale))
  pool = ConnectionPool(size=POOL_SIZE, connect=_connect, acquire_timeout=POOL_ACQUIRE_TIMEOUT)
  ```
- Wrap call sites: `pool.acquire(f"{target}:{scale}")`, etc.
- Add exception handler mapping `PoolTimeoutError` → HTTP 503.

### 5. Refactor `benchmark/api/server.py`
- Delete lines 83–117.
- Same import + single-string-key factory.
- Note: the three scalability fixes for `benchmark/` (WORKERS, warmup, CPU/mem)
  are being applied SEPARATELY (before this extraction), so at extract time the
  benchmark pool is already the bounded blocking one and this step is just
  swapping the local class for the shared one.

### 6. Docker contexts
- `tpc-h-sample-dashboard/spcs/_lib.sh:8`: `REPO_DIR="$(cd "$SPCS_DIR/../.." && pwd)"`.
- `tpc-h-sample-dashboard/spcs/dashboard/Dockerfile`: prefix all COPY sources with
  `tpc-h-sample-dashboard/`; add:
  ```dockerfile
  COPY pyproject.toml uv.lock /app/
  COPY common/ /app/common/
  COPY tpc-h-sample-dashboard/api/pyproject.toml /app/tpc-h-sample-dashboard/api/
  COPY benchmark/api/pyproject.toml /app/benchmark/api/
  RUN cd /app && uv sync --frozen --no-dev --package dashboard-api
  COPY tpc-h-sample-dashboard/api/ /app/tpc-h-sample-dashboard/api/
  COPY tpc-h-sample-dashboard/public/ /app/tpc-h-sample-dashboard/public/
  COPY tpc-h-sample-dashboard/spcs/dashboard/entrypoint.sh /usr/local/bin/entrypoint.sh
  ```
- `tpc-h-sample-dashboard/spcs/locust/Dockerfile`: same prefix change; no `iw-api-common`.
- `benchmark/spcs/api/Dockerfile`: workspace-aware install (see plan for exact block).
- `benchmark/spcs/locust/Dockerfile`: no change.

### 7. Entrypoints
- Dashboard entrypoint `--directory /app/api` → `/app/tpc-h-sample-dashboard/api`.
- Benchmark entrypoint: same tweak if it hard-codes `/app/api`.

### 8. `.dockerignore`
Confirm neither excludes `common/` or root `pyproject.toml`.

## Verification

1. Syntax: `python3 -c "import ast; ast.parse(open(...).read())"` on all edited files.
2. `uv lock` at repo root — workspace resolves.
3. `uv sync --package dashboard-api` and `uv sync --package benchmark-api`.
4. `uv run --package dashboard-api python -c "from iw_api_common import ConnectionPool; print(ConnectionPool)"`.
5. Local smoke test each server; hit `/api/config` (dashboard) and `/api/health` (benchmark).
6. `bash -n` all shell scripts.
7. `docker build --platform linux/amd64` for both API images.
8. Regression: re-run current Locust profile against a locally-launched server; verify pool log lines unchanged.

## Critical files

- `common/iw_api_common/iw_api_common/connection_pool.py` — new shared class; the point of the refactor.
- `pyproject.toml` (repo root) — workspace declaration.
- `tpc-h-sample-dashboard/api/server.py` — reference call sites (keying, prewarm loop, HTTP 503 mapping).
- `benchmark/api/server.py` — second consumer; verifies the key-based interface is generic.
- `tpc-h-sample-dashboard/spcs/dashboard/Dockerfile` + `benchmark/spcs/api/Dockerfile` — biggest source of build-time risk (context path + workspace-aware `uv sync`).
