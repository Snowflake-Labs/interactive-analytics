"""
Locust workload for the interactive warehouse benchmark API.

Reads .sql files from a queries directory and POSTs them to:
  - POST /api/run/interactive

Query directory can be set three ways (last wins):
  1. Env var: BENCHMARK_QUERIES_DIR
  2. CLI flag: --queries-dir
  3. Default: ../test/ (relative to this file) or /app/test/ (in container)

Examples:
  uv run locust -f locustfile.py --host http://localhost:3000
  uv run locust -f locustfile.py --host http://localhost:3000 \
      --headless -u 20 -r 5 -t 2m
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


def load_queries(directory: str) -> list[str]:
    queries_path = Path(directory)
    if not queries_path.exists():
        return []
    queries = []
    for sql_file in sorted(queries_path.glob("*.sql")):
        text = sql_file.read_text().strip()
        if text:
            queries.append(text)
    return queries


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
        self.queries = load_queries(queries_dir)
        if not self.queries:
            raise RuntimeError(
                f"No .sql files found in {queries_dir}. "
                "Place benchmark queries in the test/ folder."
            )

    @task
    def run_query(self) -> None:
        query = random.choice(self.queries)
        payload = {"query": query}
        endpoint = "/api/run/interactive"
        with self.client.post(
            endpoint,
            json=payload,
            name=endpoint,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"{endpoint} status {response.status_code}: {response.text}")
