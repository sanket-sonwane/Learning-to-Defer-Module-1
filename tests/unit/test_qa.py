"""Unit: QA verdict logic (PASS / QUARANTINE / FAIL)."""
from m1.builder.sync import build_observations
from m1.qa.checks import run_all


def _ctx(ts0):
    return [{"label": "USER_IDLE", "foreground_app": "x",
             "scenario_id": "s", "start_monotonic_ns": ts0 - 10**9,
             "end_monotonic_ns": ts0 + 10**12}]


def test_qa_pass_on_healthy(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                _ctx(ts0), "EXP-T", "s")
    cadence = {"samples": 20, "mean_ms": 510, "p95_ms": 700,
               "missed_deadlines": 1, "missed_deadline_ratio": 0.05,
               "effective_freq_hz": 1.96, "requested_ms": 500}
    rep = run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi,
                  _ctx(ts0), obs, sched_stats={"dropped": 0, "errors": 0},
                  sampling_cadence=cadence)
    assert rep.verdict == "PASS"


def test_qa_quarantine_when_cadence_unrecorded(sim_tasks, sim_sched,
                                               sim_sys, sim_psi):
    """We cannot certify timing we did not record: absent cadence must keep an
    otherwise healthy run out of the authoritative set."""
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                _ctx(ts0), "EXP-T", "s")
    rep = run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi,
                  _ctx(ts0), obs, sched_stats={"dropped": 0, "errors": 0})
    assert rep.verdict == "QUARANTINE"


def test_qa_fail_empty():
    rep = run_all("EXP-T", [], [], [], [], [], [])
    assert rep.verdict == "FAIL"


def test_qa_quarantine_on_drops(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    obs, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                _ctx(ts0), "EXP-T", "s")
    rep = run_all("EXP-T", sim_tasks, sim_sched, sim_sys, sim_psi,
                  _ctx(ts0), obs, sched_stats={"dropped": 5, "errors": 0})
    assert rep.verdict == "QUARANTINE"
