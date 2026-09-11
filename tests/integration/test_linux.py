"""Integration tests — Linux only. Skipped on Windows with a clear message."""
import pytest
from m1.platform_guard import is_linux

needs_linux = pytest.mark.skipif(not is_linux(), reason="requires Linux /proc interfaces")


@needs_linux
def test_task_discovery_live():
    from m1.task_discovery.registry import TaskRegistry
    reg = TaskRegistry("EXP-INT")
    snaps, _ = reg.scan()
    assert len(snaps) > 0
    assert all(s.task_id and ":" in s.task_id for s in snaps)


@needs_linux
def test_system_and_psi_live():
    from m1.system.cpu import SystemCollector
    from m1.psi.reader import PSIReader
    s = SystemCollector("EXP-INT").sample()
    assert s.timestamp_monotonic_ns > 0
    p = PSIReader("EXP-INT").sample()
    assert p.cpu_some.avg10 is None or 0.0 <= p.cpu_some.avg10 <= 100.0


@needs_linux
def test_workload_launch():
    import time
    from m1.workloads.runner import WorkloadRunner
    r = WorkloadRunner()
    rec = r.launch("cpu_intensive", 1.0)
    assert rec["pid"] > 0 and rec["workload_id"].startswith("cpu_intensive")
    time.sleep(1.5)
    assert r.procs[0].poll() is not None  # finished
    r.stop_all()


@needs_linux
def test_observation_end_to_end_no_bpf(tmp_path):
    from m1.builder.sync import build_observations
    from m1.context.store import ContextStore
    from m1.system.cpu import SystemCollector
    from m1.psi.reader import PSIReader
    from m1.task_discovery.registry import TaskRegistry
    reg = TaskRegistry("EXP-INT")
    sysc, psic = SystemCollector("EXP-INT"), PSIReader("EXP-INT")
    tasks, sys_rows, psi_rows = [], [], []
    import time
    ctx = ContextStore("EXP-INT", "smoke")
    ctx.start("USER_ACTIVE", now_ns=0)
    for _ in range(5):
        snaps, _ = reg.scan()
        tasks.extend(s.model_dump() for s in snaps)
        sys_rows.append(sysc.sample().model_dump())
        time.sleep(0.1)
    ctx.end(now_ns=10**18)
    psi_rows.append(psic.sample().model_dump())
    obs, stats = build_observations(
        tasks, [], sys_rows, psi_rows,
        [e.model_dump() for e in ctx.events], "EXP-INT", "smoke")
    assert stats["observations"] > 0
