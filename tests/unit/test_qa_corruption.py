"""Blocker 18: adversarial QA — corrupted data must never PASS."""
import copy
import pytest
from m1.builder.sync import build_observations
from m1.qa.checks import run_all


def _ctx(ts0):
    return [{"label": "USER_IDLE", "foreground_app": "x", "scenario_id": "s",
             "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]


def _base(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    ctx = _ctx(ts0)
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                ctx, "EXP-T", "s")
    assert obs
    return (copy.deepcopy(sim_tasks), copy.deepcopy(sim_sched),
            copy.deepcopy(sim_sys), copy.deepcopy(sim_psi),
            copy.deepcopy(ctx), obs)


def _verdict(tasks, sched, sys_rows, psi, ctx, obs, **kw):
    return run_all("EXP-T", tasks, sched, sys_rows, psi, ctx, obs, **kw).verdict


def test_qa_corruption(sim_tasks, sim_sched, sim_sys, sim_psi):
    tasks, sched, sys_rows, psi, ctx, obs = _base(sim_tasks, sim_sched, sim_sys, sim_psi)
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs) in ("PASS", "QUARANTINE")

    # A. Removed timestamps → FAIL.
    t = copy.deepcopy(tasks)
    for r in t:
        del r["timestamp_monotonic_ns"]
    assert _verdict(t, sched, sys_rows, psi, ctx, obs) == "FAIL"

    # B. Duplicate task identity (same id, two generations) → FAIL.
    t = copy.deepcopy(tasks)
    t.append(dict(t[0], starttime_ticks=999_999_999))
    assert _verdict(t, sched, sys_rows, psi, ctx, obs) == "FAIL"

    # C. Negative runtime delta in observations → FAIL (timestamps check).
    o = copy.deepcopy(obs)
    o[0]["recent_cpu_runtime_ticks"] = -50
    assert _verdict(tasks, sched, sys_rows, psi, ctx, o) == "FAIL"

    # D. Deleted scheduler event stream → FAIL (event loss detected).
    assert _verdict(tasks, [], sys_rows, psi, ctx, obs) == "FAIL"

    # E. Exit before create → FAIL.
    s = copy.deepcopy(sched)
    first_ts = min(r["timestamp_monotonic_ns"] for r in tasks)
    s.append({"event_type": "sched_process_exit", "timestamp_monotonic_ns": first_ts - 10**9,
              "cpu": 0, "pid": tasks[0]["pid"], "tid": tasks[0]["tid"], "comm": "x"})
    assert _verdict(tasks, s, sys_rows, psi, ctx, obs) == "FAIL"

    # E2. Orphan exit (PID never in task_rows) — allowed by design: short-lived
    # processes spawn and die between task scans. Must stay visible, not fail.
    s2 = copy.deepcopy(sched)
    s2.append({"event_type": "sched_process_exit", "timestamp_monotonic_ns": first_ts,
               "cpu": 0, "pid": 999999, "tid": 999999, "comm": "ghost"})
    cadence = {"samples": 20, "mean_ms": 510, "p95_ms": 700,
               "missed_deadlines": 1, "missed_deadline_ratio": 0.05,
               "effective_freq_hz": 1.96, "requested_ms": 500}
    assert _verdict(tasks, s2, sys_rows, psi, ctx, obs,
                    sampling_cadence=cadence) == "PASS"

    # G. Impossible (far-future) timestamps → FAIL.
    t = copy.deepcopy(tasks)
    t[0]["timestamp_monotonic_ns"] = 2**63 - 1
    assert _verdict(t, sched, sys_rows, psi, ctx, obs) == "FAIL"

    # H. Duplicate (timestamp, task) observation → FAIL.
    o = copy.deepcopy(obs)
    o.append(copy.deepcopy(o[0]))
    assert _verdict(tasks, sched, sys_rows, psi, ctx, o) == "FAIL"


def test_qa_validates_workload_events(sim_tasks, sim_sched, sim_sys, sim_psi):
    """workload_events is a distinct raw stream: malformed records must FAIL."""
    tasks, sched, sys_rows, psi, ctx, obs = _base(sim_tasks, sim_sched, sim_sys, sim_psi)
    ts0 = tasks[0]["timestamp_monotonic_ns"]
    good = [{"workload_id": "cpu-0", "type": "cpu_intensive", "pid": 1000,
             "start_monotonic_ns": ts0, "end_monotonic_ns": ts0 + 10**9}]
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    workload_events=good) in ("PASS", "QUARANTINE")

    # missing required field -> FAIL
    bad = [{"workload_id": "cpu-0", "type": "cpu_intensive"}]  # no pid/start
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    workload_events=bad) == "FAIL"

    # end < start -> FAIL
    bad2 = [{"workload_id": "cpu-0", "type": "cpu_intensive", "pid": 1000,
             "start_monotonic_ns": ts0 + 10**9, "end_monotonic_ns": ts0}]
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    workload_events=bad2) == "FAIL"

    # duplicate workload_id -> FAIL
    dup = [good[0], dict(good[0])]
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    workload_events=dup) == "FAIL"


def test_sched_attribution_gate(sim_tasks, sim_sched, sim_sys, sim_psi):
    """Broken non-idle sched-event attribution above the hard threshold must
    force FAIL (not a survivable warning); healthy attribution must pass."""
    tasks, sched, sys_rows, psi, ctx, obs = _base(sim_tasks, sim_sched, sim_sys, sim_psi)
    n = len(sched)
    base = n - 10
    healthy = {"sched_events_total": n, "sched_events_idle": 10,
               "unresolved_non_idle": 0}
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    sched_attribution=healthy) in ("PASS", "QUARANTINE")
    low = dict(healthy, unresolved_non_idle=max(1, int(0.09 * base)))  # under 10%
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    sched_attribution=low) in ("PASS", "QUARANTINE")
    broken = dict(healthy, unresolved_non_idle=max(2, int(0.5 * base)))  # well above 10%
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    sched_attribution=broken) == "FAIL"
    # Idle-only unresolved events never trip the hard gate.
    idle_only = {"sched_events_total": n, "sched_events_idle": n,
                 "unresolved_non_idle": 0}
    assert _verdict(tasks, sched, sys_rows, psi, ctx, obs,
                    sched_attribution=idle_only) in ("PASS", "QUARANTINE")


def test_qa_mirror_of_reference_run(sim_tasks, sim_sched, sim_sys, sim_psi):
    """EXP-20260911-005 shape: unresolved non-idle below the 0.25 gate, orphan
    exits, healthy cadence, zero drops. Every finding is expected-by-design or
    under its documented gate, so the run must now PASS (Gate 10)."""
    tasks, sched, sys_rows, psi, ctx, obs = _base(sim_tasks, sim_sched, sim_sys, sim_psi)
    n = len(sched)
    base = n - 10
    runsim = dict(sched_attribution={"sched_events_total": n,
                                     "sched_events_idle": int(0.15 * base),
                                     "unresolved_non_idle": int(0.135 * base)})
    first_ts = min(r["timestamp_monotonic_ns"] for r in tasks)
    s = copy.deepcopy(sched)
    for ghost in range(3):
        s.append({"event_type": "sched_process_exit", "timestamp_monotonic_ns": first_ts,
                  "cpu": 0, "pid": 990000 + ghost, "tid": 990000 + ghost, "comm": "ghost"})
    cadence = {"samples": 18, "mean_ms": 528.6, "p95_ms": 700,
               "missed_deadlines": 1, "missed_deadline_ratio": 0.0556,
               "effective_freq_hz": 1.892, "requested_ms": 500}
    rep = run_all("EXP-T", tasks, s, sys_rows, psi, ctx, obs,
                  sched_stats={"dropped": 0, "errors": 0},
                  sampling_cadence=cadence, **runsim)
    assert rep.verdict == "PASS"
    warn = {c.name for c in rep.checks if c.severity == "warning"}
    assert warn == {"lifecycle", "sched_events"}  # visible, but not blocking
