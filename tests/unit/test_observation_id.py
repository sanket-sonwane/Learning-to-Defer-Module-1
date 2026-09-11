"""observation_id: uniqueness, parseability, replay stability (verification item 8)."""
import re


def _obs_id_format(s):
    """Format: <experiment_id>:<monotonic_ns_tick>:<pid>:<starttime>."""
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+:\d+:\d+:\d+", s or ""))

def _make_obs(obs_id, ts, task_id):
    return {
        "schema_version": "1.0.0", "observation_id": obs_id,
        "experiment_id": "EXP", "timestamp_monotonic_ns": ts,
        "task_id": task_id, "pid": 100, "tid": 100,
        "cpu_history": [1.0], "simulated": True,
    }


def _build_obs_ids(experiment_id="EXP"):
    from m1.builder.sync import build_observations
    ts0 = 1_000_000_000
    tasks = [
        {"schema_version": "1.0.0", "task_id": f"{100}:{start}", "pid": 100,
         "tid": 100, "tgid": 100, "ppid": 1, "comm": "t", "state": "R",
         "priority": 20, "nice": 0, "num_threads": 1, "starttime_ticks": start,
         "processor": 0, "cpu_affinity": [0], "utime_ticks": 1000 + i,
         "stime_ticks": 100, "voluntary_ctxt_switches": 0,
         "nonvoluntary_ctxt_switches": 0, "read_bytes": 0, "write_bytes": 0,
         "rss_pages": 512, "timestamp_monotonic_ns": ts0 + i * 100_000_000,
         "timestamp_wall_ns": None, "experiment_id": experiment_id, "simulated": True}
        for i, start in enumerate((100, 200))
    ]
    sched = [{"schema_version": "1.0.0", "event_type": "sched_switch",
              "timestamp_monotonic_ns": ts0 + i * 10_000_000, "cpu": 0,
              "pid": 100, "tid": 100, "tgid": 100, "comm": "t",
              "experiment_id": experiment_id, "simulated": True,
              "task_id": "100:100", "prev_pid": 50, "next_pid": 100,
              "prev_state": 0, "next_comm": "t"} for i in range(5)]
    sys_rows = [{"schema_version": "1.0.0", "timestamp_monotonic_ns": ts0,
                 "experiment_id": experiment_id, "total_cpu_util_pct": 40.0,
                 "per_cpu_util_pct": [40.0, 35.0], "simulated": True}]
    psi_rows = [{"schema_version": "1.0.0", "timestamp_monotonic_ns": ts0,
                 "experiment_id": experiment_id, "cpu_some": {"avg10": 1.0},
                 "mem_some": {"avg10": 1.0}, "mem_full": {"avg10": 1.0},
                 "io_some": {"avg10": 1.0}, "io_full": {"avg10": 1.0},
                 "simulated": True}]
    ctx = [{"label": "U", "foreground_app": "a", "scenario_id": "s",
            "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]
    obs, _ = build_observations(tasks, sched, sys_rows, psi_rows, ctx,
                                experiment_id, "s", window_ms=500,
                                sample_ms=100, num_cpus=2)
    return [o["observation_id"] for o in obs]


def test_observation_id_unique_within_experiment():
    ids = _build_obs_ids()
    assert len(ids) == len(set(ids)), f"duplicate obs ids: {ids}"


def test_observation_id_parseable_format():
    ids = _build_obs_ids()
    assert len(ids) > 0
    for oid in ids:
        assert _obs_id_format(oid), f"unparseable obs id: {oid}"
        # Parse back: experiment_id, tick, pid, starttime
        exp, tick, pid, starttime = oid.split(":")
        assert exp == "EXP"
        assert tick.isdigit()
        assert pid.isdigit() and starttime.isdigit()


def test_observation_id_replay_stable():
    """Same input data must produce identical IDs across two builds."""
    ids_a = _build_obs_ids()
    ids_b = _build_obs_ids()
    assert ids_a == ids_b


def test_observation_id_distinguishes_experiments():
    ids_a = _build_obs_ids("EXP-A")
    ids_b = _build_obs_ids("EXP-B")
    assert ids_a != ids_b