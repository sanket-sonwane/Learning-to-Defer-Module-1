"""F1: cpu_history is computed from canonical task counters, not from a derived dict."""
from m1.builder.sync import build_observations


def _ctx(ts0):
    return [{"label": "USER_ACTIVE", "foreground_app": "x", "scenario_id": "s",
             "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]


def _task(pid, tid, ts, utime, stime, start=100):
    return {
        "schema_version": "1.0.0", "task_id": f"{pid}:{start}", "pid": pid, "tid": tid,
        "tgid": pid, "state": "R", "starttime_ticks": start, "priority": 20, "nice": 0,
        "num_threads": 1, "processor": 0, "cpu_affinity": [0, 1],
        "utime_ticks": utime, "stime_ticks": stime,
        "voluntary_ctxt_switches": 0, "nonvoluntary_ctxt_switches": 0,
        "read_bytes": 0, "write_bytes": 0, "rss_pages": 512,
        "timestamp_monotonic_ns": ts, "timestamp_wall_ns": None,
        "experiment_id": "EXP-T",
    }


def test_cpu_history_from_raw_no_derived():
    """Raw rows without 'derived' key produce correct cpu_history."""
    ts0 = 1_000_000_000
    step = 100_000_000
    tasks = [_task(100, 100, ts0 + i * step, utime=100 + i * 10, stime=10 + i)
             for i in range(6)]
    sys_rows = [{"timestamp_monotonic_ns": ts0 + i * step, "total_cpu_util_pct": 50.0,
                 "per_cpu_util_pct": [50.0], "runnable_tasks": 1,
                 "load_1": 1.0, "load_5": 1.0, "load_15": 1.0}
                for i in range(6)]
    obs, stats = build_observations(tasks, [], sys_rows, [], _ctx(ts0),
                                    "EXP-T", "s", window_ms=500, sample_ms=100, num_cpus=2)
    assert stats["observations"] > 0
    histories = [o["cpu_history"] for o in obs if o["cpu_history"] is not None]
    assert len(histories) > 0, "expected at least one non-None cpu_history"
    for h in histories:
        assert isinstance(h, list)
        assert h[0] is None, "first sample in window must be None (no predecessor)"
        assert len(h) >= 2, "need at least 2 samples for any non-None value"
        for v in h[1:]:
            assert v is None or isinstance(v, float), f"unexpected type: {type(v)}"
            if v is not None:
                assert 0.0 <= v <= 100.0 * 2, f"cpu_util out of range: {v}"


def test_cpu_history_all_none_with_single_sample():
    """When only one sample per task in window, cpu_history is [None]."""
    ts0 = 1_000_000_000
    tasks = [_task(100, 100, ts0, 100, 10)]
    sys_rows = [{"timestamp_monotonic_ns": ts0, "total_cpu_util_pct": 50.0,
                 "per_cpu_util_pct": [50.0], "runnable_tasks": 1,
                 "load_1": 1.0, "load_5": 1.0, "load_15": 1.0}]
    obs, _ = build_observations(tasks, [], sys_rows, [], _ctx(ts0),
                                "EXP-T", "s", window_ms=500, sample_ms=100, num_cpus=2)
    assert obs
    for o in obs:
        assert o["cpu_history"] is None or all(v is None for v in o["cpu_history"])


def test_cpu_history_no_derived_key_required():
    """Verify raw rows have no 'derived' key and still work."""
    ts0 = 1_000_000_000
    step = 100_000_000
    tasks = [_task(100, 100, ts0 + i * step, 100 + i * 10, 10 + i) for i in range(4)]
    for t in tasks:
        assert "derived" not in t, "raw rows must not have derived key"
    sys_rows = [{"timestamp_monotonic_ns": ts0 + i * step, "total_cpu_util_pct": 50.0,
                 "per_cpu_util_pct": [50.0], "runnable_tasks": 1,
                 "load_1": 1.0, "load_5": 1.0, "load_15": 1.0}
                for i in range(4)]
    obs, stats = build_observations(tasks, [], sys_rows, [], _ctx(ts0),
                                    "EXP-T", "s", window_ms=500, sample_ms=100, num_cpus=2)
    assert stats["observations"] > 0


def test_pid_reuse_no_history_connection():
    """PID reuse: different generations must not connect cpu_history."""
    ts0 = 1_000_000_000
    step = 100_000_000
    # Generation A: pid=100, start=100
    gen_a = [_task(100, 100, ts0 + i * step, 100 + i * 10, 10, start=100) for i in range(3)]
    # Generation B: same pid=100, different start=999 (PID reused)
    gen_b = [_task(100, 100, ts0 + 3 * step + i * step, 200 + i * 10, 20, start=999)
             for i in range(3)]
    tasks = gen_a + gen_b
    sys_rows = [{"timestamp_monotonic_ns": ts0 + i * step, "total_cpu_util_pct": 50.0,
                 "per_cpu_util_pct": [50.0], "runnable_tasks": 1,
                 "load_1": 1.0, "load_5": 1.0, "load_15": 1.0}
                for i in range(6)]
    obs, stats = build_observations(tasks, [], sys_rows, [], _ctx(ts0),
                                    "EXP-T", "s", window_ms=500, sample_ms=100, num_cpus=2)
    # Two distinct task_ids must appear
    task_ids = {o["task_id"] for o in obs}
    assert "100:100" in task_ids
    assert "100:999" in task_ids
    # Each generation's history is independent
    for tid in ("100:100", "100:999"):
        gen_obs = [o for o in obs if o["task_id"] == tid]
        for o in gen_obs:
            if o["cpu_history"] is not None:
                assert o["cpu_history"][0] is None, "first sample must always be None"
