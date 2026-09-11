"""Simulation layer for Windows development/testing ONLY.

Feeds synthetic Linux-like records into builder/storage/QA/replay.
Every record is labeled simulated=True. NEVER mix with authoritative data.
"""
import random
from m1 import timebase

SIMULATED = True


def make_task_snapshot(pid: int = 1000, tid: int = 1000, i: int = 0) -> dict:
    now = timebase.monotonic_ns()
    return {
        "schema_version": "1.0.0",
        "task_id": f"{pid}:123456",
        "pid": pid, "tid": tid, "tgid": pid, "ppid": 1,
        "comm": "sim_task",
        "state": "R" if i % 2 == 0 else "S",
        "priority": 20, "nice": 0, "num_threads": 1,
        "starttime_ticks": 123456,
        "processor": 0, "cpu_affinity": [0, 1],
        "utime_ticks": 1000 + i * 10, "stime_ticks": 100 + i,
        "voluntary_ctxt_switches": i, "nonvoluntary_ctxt_switches": i // 2,
        "read_bytes": 4096 * i, "write_bytes": 1024 * i,
        "rss_pages": 512,
        "timestamp_monotonic_ns": now + i * 100_000_000,
        "timestamp_wall_ns": None,
        "experiment_id": "SIM-EXP",
        "simulated": True,
    }


def make_sched_event(i: int = 0, event_type: str = "sched_switch") -> dict:
    return {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "timestamp_monotonic_ns": timebase.monotonic_ns() + i * 1_000_000,
        "cpu": 0, "pid": 1000, "tid": 1000, "tgid": 1000,
        "comm": "sim_task", "task_id": "1000:123456",
        "experiment_id": "SIM-EXP",
        "simulated": True,
    }


def make_system_snapshot(i: int = 0) -> dict:
    return {
        "schema_version": "1.0.0",
        "timestamp_monotonic_ns": timebase.monotonic_ns() + i * 100_000_000,
        "experiment_id": "SIM-EXP",
        "total_cpu_util_pct": 40.0 + (i % 10),
        "per_cpu_util_pct": [40.0, 35.0],
        "runnable_tasks": 3,
        "load_1": 1.2, "load_5": 0.9, "load_15": 0.5,
        "simulated": True,
    }


def make_psi_snapshot(i: int = 0) -> dict:
    d = {"avg10": 5.0, "avg60": 3.0, "avg300": 1.0, "total_us": 1000 * i}
    return {
        "schema_version": "1.0.0",
        "timestamp_monotonic_ns": timebase.monotonic_ns() + i * 500_000_000,
        "experiment_id": "SIM-EXP",
        "cpu_some": dict(d), "mem_some": dict(d), "mem_full": dict(d),
        "io_some": dict(d), "io_full": dict(d),
        "simulated": True,
    }
