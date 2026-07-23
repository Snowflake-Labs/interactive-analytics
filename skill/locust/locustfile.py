"""
Locust workload for the TPC-H benchmark API.

Hits /api/standard and /api/interactive endpoints to measure query latency
under concurrent load.

Warehouse target can be set via:
  1. Env var: WAREHOUSE (interactive | standard | both)
  2. CLI flag: --warehouse

Examples:
  uv run locust -f locustfile.py --host http://localhost:3000
  uv run locust -f locustfile.py --host http://localhost:3000 \
      --warehouse both --headless -u 20 -r 5 -t 2m
"""

from __future__ import annotations

import os

from locust import HttpUser, between, events, task

WAREHOUSES = ["interactive", "standard", "both"]


@events.init_command_line_parser.add_listener
def _register_cli_args(parser):
    parser.add_argument(
        "--warehouse",
        type=str,
        choices=WAREHOUSES,
        default=os.environ.get("WAREHOUSE", "both"),
        env_var="WAREHOUSE",
        include_in_web_ui=True,
        help="Which endpoint(s) to hit: interactive, standard, or both",
    )


class BenchmarkUser(HttpUser):
    """Simulates users hitting the benchmark API endpoints."""

    wait_time = between(0.5, 1.5)

    def _resolve_warehouse(self) -> str:
        opts = getattr(self.environment, "parsed_options", None)
        wh = getattr(opts, "warehouse", None) or os.environ.get("WAREHOUSE", "both")
        if wh not in WAREHOUSES:
            wh = "both"
        return wh

    def on_start(self) -> None:
        self.warehouse = self._resolve_warehouse()

    @task
    def run_benchmark(self) -> None:
        if self.warehouse in ("standard", "both"):
            self.client.get("/api/standard", name="/api/standard")
        if self.warehouse in ("interactive", "both"):
            self.client.get("/api/interactive", name="/api/interactive")
