"""Blocker 12: workload launch metadata attributes observations, survives replay."""
import json
from m1.builder.sync import build_observations


def _ctx(ts0):
    return [{"label": "USER_COMPILING", "foreground_app": "make", "scenario_id": "s",
             "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]


def _workloads(ts0):
    return [{"workload_id": "cpu-001", "type": "cpu_intensive", "pid": 1000,
             "start_monotonic_ns": ts0, "experiment_id": "EXP-T"}]


def test_workload_attribution(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                _ctx(ts0), "EXP-T", "s",
                                workloads=_workloads(ts0))
    assert obs
    assert all(o["workload_id"] == "cpu-001" for o in obs)
    assert all(o["workload_type"] == "cpu_intensive" for o in obs)
    # Tasks unrelated to the workload (own pid AND tgid) stay unattributed.
    other = [dict(t, pid=9999, tid=9999, tgid=9999) for t in sim_tasks]
    obs2, _ = build_observations(other, sim_sched, sim_sys, sim_psi,
                                 _ctx(ts0), "EXP-T", "s",
                                 workloads=_workloads(ts0))
    assert all(o["workload_id"] is None for o in obs2)


def test_workload_survives_replay(tmp_path, sim_tasks, sim_sched, sim_sys):
    import json as _j
    from m1.builder.replay import _config_hash, replay
    from m1.storage.layout import ExperimentLayout
    exp = "EXP-20260101-002"
    layout = ExperimentLayout(tmp_path, exp)
    layout.create()
    (layout.metadata / "experiment.json").write_text(_j.dumps({"scenario": "s"}))
    cfg = {"observation_window_ms": 500, "sampling_interval_ms": 100,
           "schema_version": "1.0.0", "scenario": "s", "clk_tck": 100, "num_cpus": 2}
    cfg["config_hash"] = _config_hash(cfg)
    (layout.metadata / "collector_config.json").write_text(_j.dumps(cfg))
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    payloads = [(layout.raw_tasks, sim_tasks), (layout.raw_sched, sim_sched),
                (layout.raw_system, sim_sys),
                (layout.raw_context, _ctx(ts0)),
                (layout.raw_workloads, _workloads(ts0))]
    for d, rows in payloads:
        with (d / "data.jsonl").open("w") as f:
            for r in rows:
                f.write(_j.dumps(r, default=str) + "\n")
    stats = replay(exp, tmp_path)
    assert stats["observations"] > 0
    rows = [(tmp_path / f"data/{exp}/processed/observations/replay_observations.jsonl")
            .read_text().splitlines()]
    first = json.loads(rows[0][0])
    assert first["workload_id"] == "cpu-001"


def _single_task(ts, pid, tgid=None):
    tgid = tgid if tgid is not None else pid
    return {"task_id": f"{pid}:1", "pid": pid, "tid": pid, "tgid": tgid,
            "timestamp_monotonic_ns": ts, "utime_ticks": 0, "stime_ticks": 0,
            "read_bytes": 0, "write_bytes": 0, "state": "R"}


def _one_obs(tasks, workloads):
    ts0 = min(t["timestamp_monotonic_ns"] for t in tasks)
    ctx = _ctx(ts0)
    sys_rows = [{"timestamp_monotonic_ns": ts0, "total_cpu_util_pct": 40.0,
                 "runnable_tasks": 3, "per_cpu_util_pct": [40.0]}]
    psi_rows = [{"timestamp_monotonic_ns": ts0,
                 "cpu_some": {"avg10": 1.0, "avg60": 1.0, "avg300": 1.0, "total_us": 0},
                 "mem_some": {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0, "total_us": 0},
                 "io_some": {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0, "total_us": 0}}]
    obs, _ = build_observations(tasks, [], sys_rows, psi_rows, ctx, "EXP-T", "s",
                                window_ms=500, sample_ms=100, num_cpus=2,
                                workloads=workloads)
    return obs


def test_workload_not_pid_only():
    """A THREAD (tid != pid, tgid == workload pid) is attributed."""
    start = 1_000_000_000
    wl = [{"workload_id": "cpu-001", "type": "cpu_intensive", "pid": 1000,
           "start_monotonic_ns": start, "duration_s": 10.0}]
    # thread: pid/tid = 4242, tgid = 1000 (workload's pid)
    tasks = [_single_task(start + 5 * 10**9, pid=4242, tgid=1000)]
    obs = _one_obs(tasks, wl)
    assert obs and obs[0]["workload_id"] == "cpu-001"


def test_workload_child_not_attributed():
    """A forked CHILD (own pid/tgid) without its own metadata stays unattributed."""
    start = 1_000_000_000
    wl = [{"workload_id": "cpu-001", "type": "cpu_intensive", "pid": 1000,
           "start_monotonic_ns": start, "duration_s": 10.0}]
    tasks = [_single_task(start + 5 * 10**9, pid=4242, tgid=4242)]
    obs = _one_obs(tasks, wl)
    assert obs and obs[0]["workload_id"] is None


def test_workload_attr_excludes_after_exit():
    """Membership ends at nominal lifetime: post-exit snapshots unattributed."""
    start = 1_000_000_000
    wl = [{"workload_id": "cpu-001", "type": "cpu_intensive", "pid": 1000,
           "start_monotonic_ns": start, "end_monotonic_ns": start + 3 * 10**9}]
    before = _single_task(start + 2 * 10**9, pid=1000)
    after = _single_task(start + 4 * 10**9, pid=1000)
    obs = _one_obs([before, after], wl)
    attr = [(o["timestamp_monotonic_ns"], o["workload_id"]) for o in obs]
    in_wl = [t for t, w in attr if w == "cpu-001"]
    assert in_wl and all(t <= start + 3 * 10**9 for t in in_wl)
    post = [t for t, w in attr if t > start + 3 * 10**9]
    assert post and all(w is None for t, w in attr if t in post)


def test_workload_attr_pid_reuse_cannot_steal_label():
    """A NEW process reusing a workload's pid late still cannot grab the label
    when membership is time-bounded by the original launch lifetime."""
    start = 1_000_000_000
    wl = [{"workload_id": "cpu-001", "type": "cpu_intensive", "pid": 1000,
           "start_monotonic_ns": start, "end_monotonic_ns": start + 3 * 10**9}]
    # original workload generation while alive -> attributed
    early = _single_task(start + 1 * 10**9, pid=1000)
    # a LATER, different generation reusing pid 1000 after the workload ended
    late = _single_task(start + 9 * 10**9, pid=1000)
    obs = _one_obs([early, late], wl)
    by_ts = {o["timestamp_monotonic_ns"]: o["workload_id"] for o in obs}
    assert by_ts[start + 1 * 10**9] == "cpu-001"
    assert by_ts[start + 9 * 10**9] is None
