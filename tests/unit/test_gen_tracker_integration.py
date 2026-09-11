"""GenerationTracker integration: end-to-end task_id resolution across PID reuse."""
from m1.sched_events.correlate import GenerationTracker
from m1.builder.sync import build_observations


def _task(pid, start, ts, experiment_id="EXP-T"):
    return {
        "schema_version": "1.0.0", "task_id": f"{pid}:{start}",
        "pid": pid, "tid": pid, "tgid": pid, "ppid": 1, "comm": "task",
        "state": "R", "priority": 20, "nice": 0, "num_threads": 1,
        "starttime_ticks": start, "processor": 0, "cpu_affinity": [0],
        "utime_ticks": 1000, "stime_ticks": 100,
        "voluntary_ctxt_switches": 0, "nonvoluntary_ctxt_switches": 0,
        "read_bytes": 0, "write_bytes": 0, "rss_pages": 512,
        "timestamp_monotonic_ns": ts, "timestamp_wall_ns": None,
        "experiment_id": experiment_id, "simulated": True,
    }


def _sched(pid, ts, event_type="sched_switch", next_pid=None, prev_pid=None):
    return {
        "schema_version": "1.0.0", "event_type": event_type,
        "timestamp_monotonic_ns": ts, "cpu": 0,
        "pid": pid, "tid": pid, "tgid": pid, "comm": "task",
        "experiment_id": "EXP-T", "simulated": True,
        "task_id": "",  # eBPF events arrive without task_id
        "prev_pid": prev_pid or 0, "next_pid": next_pid or pid,
        "prev_state": 0, "next_comm": "task",
    }


def _sys(ts):
    return {"schema_version": "1.0.0", "timestamp_monotonic_ns": ts,
            "experiment_id": "EXP-T", "total_cpu_util_pct": 40.0,
            "per_cpu_util_pct": [40.0, 35.0], "simulated": True}


def _psi(ts):
    d = {"avg10": 5.0, "avg60": 3.0, "avg300": 1.0, "total_us": 1000}
    return {"schema_version": "1.0.0", "timestamp_monotonic_ns": ts,
            "experiment_id": "EXP-T",
            "cpu_some": dict(d), "mem_some": dict(d), "mem_full": dict(d),
            "io_some": dict(d), "io_full": dict(d), "simulated": True}


def _ctx(ts0):
    return [{"label": "USER_COMPILING", "foreground_app": "make",
             "scenario_id": "s", "start_monotonic_ns": ts0 - 10**9,
             "end_monotonic_ns": ts0 + 10**12}]


def test_pid_reuse_generation_safe_resolution():
    """After PID reuse, sched events must NOT be attributed to the wrong generation."""
    g = GenerationTracker()
    ts_base = 1_000_000_000

    # Generation A: pid=100, starttime=100, alive [ts_base, ts_base+500ms]
    g.observe(100, "100:100", 100, ts_base)
    g.close(100, ts_base + 500_000_000)

    # Generation B: pid=100 reused, starttime=200, alive [ts_base+1s, ...]
    g.observe(100, "100:200", 200, ts_base + 1_000_000_000)

    # Event at ts_base+200ms should resolve to generation A
    assert g.resolve(100, ts_base + 200_000_000) == "100:100"
    # Event at ts_base+800ms (gap after A exit, before B start) is unresolved
    assert g.resolve(100, ts_base + 800_000_000) is None
    assert g.unresolved == 1
    # Event at ts_base+1.5s should resolve to generation B
    assert g.resolve(100, ts_base + 1_500_000_000) == "100:200"
    # Old event should still resolve to A, never B
    assert g.resolve(100, ts_base + 300_000_000) == "100:100"


def test_builder_uses_gen_tracker_for_sched_resolution():
    """Builder pre-resolves sched event task_ids via tracker before matching."""
    g = GenerationTracker()
    ts0 = 1_000_000_000

    # Task snapshot for pid=100, generation A
    tasks = [_task(100, 100, ts0)]
    # Sched event with empty task_id (as eBPF produces)
    sched = [_sched(100, ts0 - 5_000_000, next_pid=100)]
    sys_rows = [_sys(ts0)]
    psi_rows = [_psi(ts0)]
    ctx = _ctx(ts0)

    # Feed tracker
    g.observe(100, "100:100", 100, ts0 - 10_000_000)

    obs, stats = build_observations(tasks, sched, sys_rows, psi_rows, ctx,
                                    "EXP-T", "s", window_ms=500, sample_ms=100,
                                    num_cpus=2, gen_tracker=g)
    assert stats["observations"] > 0
    # The sched event should have been resolved to task_id="100:100"
    assert sched[0].get("task_id") == "100:100"
    assert stats.get("unresolved_identities", 0) == 0


def test_unresolved_events_counted():
    """Events that cannot be resolved are counted, never silently attributed."""
    g = GenerationTracker()
    ts0 = 1_000_000_000

    tasks = [_task(100, 100, ts0)]
    # Sched event for pid=999 (never observed by tracker)
    sched = [_sched(999, ts0 - 5_000_000, next_pid=999)]
    sys_rows = [_sys(ts0)]
    psi_rows = [_psi(ts0)]
    ctx = _ctx(ts0)

    obs, stats = build_observations(tasks, sched, sys_rows, psi_rows, ctx,
                                    "EXP-T", "s", window_ms=500, sample_ms=100,
                                    num_cpus=2, gen_tracker=g)
    # pid=999 was never observed, so it should be unresolved
    assert stats.get("unresolved_identities", 0) >= 1
    # The sched event's task_id should still be empty (not falsely resolved)
    assert sched[0].get("task_id") == ""


def test_thread_level_events_resolve_to_own_generation():
    """Sched events carry a TID, not the process pid: a multithreaded process
    must resolve each thread's events to that thread's generation, never leak
    another thread's identity through the shared process pid."""
    g = GenerationTracker()
    ts0 = 1_000_000_000

    # Process pid=617 with threads 695/696/700 (task_id embeds the tid).
    g.observe(617, "695:1618", 1618, ts0, tid=695)
    g.observe(617, "696:1619", 1619, ts0, tid=696)
    g.observe(617, "700:1625", 1625, ts0, tid=700)

    assert g.resolve(695, ts0 + 100_000_000) == "695:1618"
    assert g.resolve(696, ts0 + 100_000_000) == "696:1619"
    assert g.resolve(700, ts0 + 100_000_000) == "700:1625"
    # The process pid is never a schedulable identity here: no interval exists.
    assert g.resolve(617, ts0 + 100_000_000) is None
    # Thread exit closes only its own generation, not the process's.
    g.close(695, ts0 + 500_000_000, tid=695)
    assert g.resolve(695, ts0 + 600_000_000) is None
    assert g.resolve(696, ts0 + 600_000_000) == "696:1619"


def test_builder_thread_resolution_end_to_end():
    """build_observations() pre-resolves thread-level sched events via a
    tid-keyed tracker and attributes them to the right task_id."""
    g = GenerationTracker()
    ts0 = 1_000_000_000
    # Thread row: pid=617 (process), tid=695, task_id embeds tid.
    tasks = [dict(_task(617, 1618, ts0), pid=617, tid=695,
                  task_id="695:1618", starttime_ticks=1618)]
    sched = [_sched(695, ts0 - 5_000_000, next_pid=695)]
    g.observe(617, "695:1618", 1618, ts0 - 10_000_000, tid=695)

    obs, stats = build_observations(tasks, sched, [_sys(ts0)], [_psi(ts0)],
                                    _ctx(ts0), "EXP-T", "s", window_ms=500,
                                    sample_ms=100, num_cpus=2, gen_tracker=g)
    assert stats["observations"] > 0
    assert stats.get("unresolved_sched_events", 0) == 0
    assert sched[0].get("task_id") == "695:1618"
    # The resolved event falls into the thread's observation window.
    rec = next(r for r in obs if r["task_id"] == "695:1618")
    assert rec["events_in_window"] >= 1
