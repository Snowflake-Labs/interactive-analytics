# Plan: Derive All Names from SOLUTION_NAME

## Current State

Two systems use hardcoded names:

1. **Python CLI (`tpc-h/`)** — `config.py` has:
   ```python
   BENCH_DATABASE = "IW_TPCH_BENCH"
   INTERACTIVE_WH_PREFIX = "IW_TPCH_BENCH_WH"
   STANDARD_WH_PREFIX = "TPCH_BENCH_WH"
   SCHEMA_PREFIX = "TPCH_SF"
   ```

2. **SPCS shell scripts (`dashboard/spcs/`)** — `config.env` has:
   ```bash
   DB=IW_TPCH_BENCH
   IMAGE_REPO=IW_DASHBOARD_IMAGES
   DASHBOARD_COMPUTE_POOL=IW_DASHBOARD_POOL
   LOCUST_COMPUTE_POOL=IW_DASHBOARD_LOCUST_POOL
   DASHBOARD_DATABASE=IW_TPCH_BENCH
   ```

## Naming Pattern (derived from SOLUTION_NAME)

Given `SOLUTION_NAME=TPCH`:

| Resource | Derivation | Result |
|---|---|---|
| Database | `IW_${SOLUTION_NAME}_BENCH` | `IW_TPCH_BENCH` |
| Schema (standard) | `${SOLUTION_NAME}_SF${SCALE}` | `TPCH_SF100` |
| Schema (interactive) | `${SOLUTION_NAME}_SF${SCALE}_IT` | `TPCH_SF100_IT` |
| Load warehouse | `IW_${SOLUTION_NAME}_LOAD_WH` | `IW_TPCH_LOAD_WH` |
| Standard warehouse | `${SOLUTION_NAME}_BENCH_WH_${SCALE}` | `TPCH_BENCH_WH_100` |
| Interactive warehouse | `IW_${SOLUTION_NAME}_BENCH_WH_${SCALE}` | `IW_TPCH_BENCH_WH_100` |
| Image repo | `IW_${SOLUTION_NAME}_IMAGES` | `IW_TPCH_IMAGES` |
| Dashboard compute pool | `IW_${SOLUTION_NAME}_DASHBOARD_POOL` | `IW_TPCH_DASHBOARD_POOL` |
| Locust compute pool | `IW_${SOLUTION_NAME}_LOCUST_POOL` | `IW_TPCH_LOCUST_POOL` |

## Changes

### 1. `tpc-h/.env`

```env
CONNECTION_NAME=PM
SOLUTION_NAME=TPCH
DEFAULT_SCALE=100
```

### 2. `tpc-h/src/tpch/config.py`

Replace the hardcoded constants with derivations:

```python
SOLUTION_NAME = os.getenv("SOLUTION_NAME", "TPCH")

BENCH_DATABASE = f"IW_{SOLUTION_NAME}_BENCH"
INTERACTIVE_WH_PREFIX = f"IW_{SOLUTION_NAME}_BENCH_WH"
STANDARD_WH_PREFIX = f"{SOLUTION_NAME}_BENCH_WH"
SCHEMA_PREFIX = f"{SOLUTION_NAME}_SF"
```

No other changes needed — the rest of `config.py` already uses these constants to build full names.

### 3. `dashboard/spcs/config.env`

Add `SOLUTION_NAME` at the top and derive the object names:

```bash
SOLUTION_NAME=TPCH

# Derived names (using bash variable expansion)
DB=IW_${SOLUTION_NAME}_BENCH
IMAGE_REPO=IW_${SOLUTION_NAME}_IMAGES
DASHBOARD_COMPUTE_POOL=IW_${SOLUTION_NAME}_DASHBOARD_POOL
LOCUST_COMPUTE_POOL=IW_${SOLUTION_NAME}_LOCUST_POOL
DASHBOARD_DATABASE=IW_${SOLUTION_NAME}_BENCH
```

Service names (`DASHBOARD`, `DASHBOARD_API_LOCUST`, `DASHBOARD_LOCUST`) stay as-is since they are generic and not solution-specific.

### 4. SQL templates — no changes needed

The SQL templates use `{{SCALE}}`, `{{LOAD_WH_SIZE}}`, `{{BENCH_WH_SIZE}}` placeholders. The Python code already substitutes these from `config.py` constants. Since those constants now derive from `SOLUTION_NAME`, the templates work unchanged.

### 5. CLI `--solution` argument

Add to all subcommands in `cli.py`:

```python
def _add_solution_arg(parser):
    parser.add_argument(
        "--solution",
        default=None,
        help="Solution name (overrides SOLUTION_NAME env var, default: TPCH)",
    )
```

In `main()`, if `args.solution` is provided, set `os.environ["SOLUTION_NAME"]` before importing config (or reload the derived values). Since `config.py` is already imported at module load, we'll need to make the derivation a function that can be called with an override — or set the env var before the module loads. Simplest: set the env var early in `main()` before the config is used, and make the derived constants into a lazy-loaded namespace or module-level variables that are set at first access.

**Preferred approach**: Keep it simple — in `main()`, if `--solution` is passed, set `os.environ["SOLUTION_NAME"]` and then re-derive the config values by calling a `config.reload()` function.

```python
# config.py
def _derive_names():
    global SOLUTION_NAME, BENCH_DATABASE, INTERACTIVE_WH_PREFIX, STANDARD_WH_PREFIX, SCHEMA_PREFIX
    SOLUTION_NAME = os.getenv("SOLUTION_NAME", "TPCH")
    BENCH_DATABASE = f"IW_{SOLUTION_NAME}_BENCH"
    INTERACTIVE_WH_PREFIX = f"IW_{SOLUTION_NAME}_BENCH_WH"
    STANDARD_WH_PREFIX = f"{SOLUTION_NAME}_BENCH_WH"
    SCHEMA_PREFIX = f"{SOLUTION_NAME}_SF"

_derive_names()

def reload():
    _derive_names()
```

## Result

After these changes, changing `SOLUTION_NAME=MYTEST` in `.env` (or passing `--solution MYTEST`) will produce:
- Database: `IW_MYTEST_BENCH`
- Schemas: `MYTEST_SF100`, `MYTEST_SF100_IT`
- Warehouses: `MYTEST_BENCH_WH_100`, `IW_MYTEST_BENCH_WH_100`
- Compute pools: `IW_MYTEST_DASHBOARD_POOL`, `IW_MYTEST_LOCUST_POOL`
