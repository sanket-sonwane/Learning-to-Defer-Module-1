"""Blocker 6: PSI is a persisted monotonic time series, not a final sample."""
from m1.builder.sync import build_observations
from m1.psi.reader import read_resource


def _psi_row(ts, avg):
    d = {"avg10": avg, "avg60": avg, "avg300": avg, "total_us": ts}
    return {"timestamp_monotonic_ns": ts, "experiment_id": "EXP-T",
            "cpu_some": dict(d), "mem_some": dict(d), "io_some": dict(d)}


def _ctx(ts0):
    return [{"label": "USER_ACTIVE", "foreground_app": "x", "scenario_id": "s",
             "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]


def test_psi_timeseries(sim_tasks, sim_sched, sim_sys):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    psi = [_psi_row(ts0 + 0, 1.0), _psi_row(ts0 + 300_000_000, 9.0)]
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, psi,
                                _ctx(ts0), "EXP-T", "s")
    assert obs, "expected observations with PSI stream"
    early = [o for o in obs if o["timestamp_monotonic_ns"] < ts0 + 300_000_000]
    late = [o for o in obs if o["timestamp_monotonic_ns"] >= ts0 + 300_000_000]
    assert early and all(o["cpu_psi_some_10"] == 1.0 for o in early)
    assert late and all(o["cpu_psi_some_10"] == 9.0 for o in late)


def test_psi_missing_is_none_not_zero(sim_tasks, sim_sched, sim_sys):
    from m1.builder.sync import build_observations as b
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    # Builder with no PSI stream leaves PSI fields None (never 0.0).
    obs, _ = b(sim_tasks, sim_sched, sim_sys, [], _ctx(ts0), "EXP-T", "s")
    assert obs
    assert all(o["cpu_psi_some_10"] is None for o in obs)
