"""Detect the CPU quota available to this process (cgroup-aware).

SPCS containers get a cgroup CPU quota matching the container's
resources.requests/limits.cpu, not the physical node's full core count.
os.cpu_count() on the host can be misleading in containers, so read the
cgroup limits directly, falling back to os.cpu_count()/sched_getaffinity
when no quota is set (unlimited).

Usage:
    uv run cpu.py
"""

import math
import os
from pathlib import Path

CGROUP_V2_MAX = Path("/sys/fs/cgroup/cpu.max")
CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _fallback_cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def detect_cpu_quota() -> int:
    """Return the number of whole CPUs available to this process, min 1."""
    if CGROUP_V2_MAX.exists():
        quota_str, period_str = CGROUP_V2_MAX.read_text().split()
        if quota_str != "max":
            quota = int(quota_str)
            period = int(period_str)
            return max(1, math.ceil(quota / period))
        return max(1, _fallback_cpu_count())

    if CGROUP_V1_QUOTA.exists() and CGROUP_V1_PERIOD.exists():
        quota = int(CGROUP_V1_QUOTA.read_text().strip())
        period = int(CGROUP_V1_PERIOD.read_text().strip())
        if quota > 0:
            return max(1, math.ceil(quota / period))
        return max(1, _fallback_cpu_count())

    return max(1, _fallback_cpu_count())


if __name__ == "__main__":
    print(detect_cpu_quota())
