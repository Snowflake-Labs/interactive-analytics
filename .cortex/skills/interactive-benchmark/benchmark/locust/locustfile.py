"""
Locust workload for the interactive warehouse benchmark API.

Two user classes:
  - BenchmarkUser: reads .sql filenames from a queries directory and POSTs
    their IDs to POST /api/run/interactive {"query_id": "<stem>"}.
    The server must have the same .sql files loaded in its query registry.
  - BaselineUser: POSTs to POST /api/run/baseline with a static payload.
    Measures pure API/infra throughput without touching Snowflake.

Query directory can be set three ways (last wins):
  1. Env var: BENCHMARK_QUERIES_DIR
  2. CLI flag: --queries-dir
  3. Default: ../test/ (relative to this file) or /app/test/ (in container)

Examples:
  # Run benchmark (Snowflake queries):
  uv run locust -f locustfile.py BenchmarkUser --host http://localhost:3000
  # Run baseline (no-op, infra only):
  uv run locust -f locustfile.py BaselineUser --host http://localhost:3000 \
      --headless -u 20 -r 5 -t 1m
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

DEFAULT_QUERIES_DIR = str(
    Path(__file__).resolve().parent.parent / "test"
    if not Path("/app/test").exists()
    else Path("/app/test")
)


def load_query_ids(directory: str) -> list[str]:
    """Return filename stems of non-empty .sql files (used as query IDs)."""
    queries_path = Path(directory)
    if not queries_path.exists():
        return []
    return [
        sql_file.stem
        for sql_file in sorted(queries_path.glob("*.sql"))
        if sql_file.read_text().strip()
    ]


@events.init_command_line_parser.add_listener
def _register_cli_args(parser):
    parser.add_argument(
        "--queries-dir",
        type=str,
        default=os.environ.get("BENCHMARK_QUERIES_DIR", DEFAULT_QUERIES_DIR),
        env_var="BENCHMARK_QUERIES_DIR",
        include_in_web_ui=False,
        help="Directory containing .sql benchmark files",
    )


class BenchmarkUser(HttpUser):
    """Sends benchmark queries to the interactive warehouse API endpoint."""

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        opts = getattr(self.environment, "parsed_options", None)
        queries_dir = getattr(opts, "queries_dir", None) or os.environ.get(
            "BENCHMARK_QUERIES_DIR", DEFAULT_QUERIES_DIR
        )
        self.query_ids = load_query_ids(queries_dir)
        if not self.query_ids:
            raise RuntimeError(
                f"No .sql files found in {queries_dir}. "
                "Place benchmark queries in the test/ folder."
            )

    @task
    def run_query(self) -> None:
        query_id = random.choice(self.query_ids)
        payload = {"query_id": query_id}
        endpoint = "/api/run/interactive"
        with self.client.post(
            endpoint,
            json=payload,
            name=endpoint,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"{endpoint} status {response.status_code}: {response.text}")


class BaselineUser(HttpUser):
    """Hits the no-op baseline endpoint to measure pure API/infra throughput."""

    wait_time = between(0.5, 1.5)

    @task
    def run_baseline(self) -> None:
        endpoint = "/api/run/baseline"
        with self.client.post(
            endpoint,
            json={"query_id": "baseline"},
            name=endpoint,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"{endpoint} status {response.status_code}: {response.text}")
