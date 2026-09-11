"""Blockers 19/20: collector failure and backend fidelity gate the verdict."""
from m1.builder.sync import build_observations
from m1.qa.checks import run_all


def _ctx(ts0):
    return [{"label": "USER_IDLE", "foreground_app": "x", "scenario_id": "s",
             "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]


def test_collector_failure(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    ctx = _ctx(ts0)
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                ctx, "EXP-T", "s")
    base = run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi, ctx, obs)
    assert base.verdict in ("PASS", "QUARANTINE")
    # A dead critical collector forces non-PASS even with complete rows.
    failed = run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi, ctx, obs,
                     failed_collectors=["task_sampler: 10 consecutive errors"])
    assert failed.verdict == "FAIL"
    # Non-ebpf backends cannot PASS as authoritative.
    assert run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi, ctx, obs,
                   backend="tracefs_fallback").verdict == "QUARANTINE"
    assert run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi, ctx, obs,
                   backend="none").verdict == "FAIL"
