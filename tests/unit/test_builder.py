"""Unit: observation builder joins sim streams deterministically."""
from m1.builder.sync import build_observations


def _ctx(ts0):
    return [{"label": "USER_COMPILING", "foreground_app": "make",
             "scenario_id": "s", "start_monotonic_ns": ts0 - 10**9,
             "end_monotonic_ns": ts0 + 10**12}]


def test_builder_produces_observations(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    obs, stats = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                    _ctx(ts0), "EXP-T", "s", window_ms=500,
                                    sample_ms=100, num_cpus=2)
    assert stats["observations"] > 0
    o = obs[0]
    for k in ("observation_id", "experiment_id", "task_id", "user_state",
              "cpu_psi_some_10", "events_in_window"):
        assert k in o
    assert o["context_source"] == "controlled_ground_truth"


def test_builder_skips_without_context(sim_tasks, sim_sched, sim_sys, sim_psi):
    obs, stats = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                                    [], "EXP-T", "s")
    assert obs == [] and stats["skipped_no_context"] > 0


def test_switch_in_uses_next_pid(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    target_pid = sim_tasks[0]["pid"]
    target_tid = sim_tasks[0].get("tid", target_pid)
    # sched_switch where target is switched IN (next_pid = target), placed BEFORE ts0
    sw_in_ev = {"event_type": "sched_switch", "timestamp_monotonic_ns": ts0 - 5_000_000,
                "cpu": 0, "pid": target_pid, "tid": target_tid, "comm": "task",
                "prev_pid": 999, "next_pid": target_pid, "prev_state": 0,
                "next_comm": "task"}
    # sched_switch where target is switched OUT (prev_pid = target)
    # pid=100 means OTHER task switched in; target_tid so it passes the win filter
    sw_out_ev = {"event_type": "sched_switch", "timestamp_monotonic_ns": ts0 - 2_000_000,
                 "cpu": 0, "pid": 100, "tid": target_tid, "comm": "other",
                 "prev_pid": target_pid, "next_pid": 100, "prev_state": 0,
                 "next_comm": "other"}
    obs, stats = build_observations(sim_tasks, [sw_in_ev, sw_out_ev], sim_sys, sim_psi,
                                    _ctx(ts0), "EXP-T", "s", window_ms=500,
                                    sample_ms=100, num_cpus=2)
    assert stats["observations"] > 0
    o = obs[0]
    # sw_in should produce last_switch_in_ns
    assert o.get("last_switch_in_ns") == ts0 - 5_000_000
    # sw_out should produce last_switch_out_ns (different from switch_in!)
    assert o.get("last_switch_out_ns") == ts0 - 2_000_000


def test_sched_window_indexed_merge(sim_tasks, sim_sys, sim_psi):
    """Indexed window selection merges task_id-primary and tid-fallback events.

    Regression guard for the replay fix: events must be selected by bisect
    slices, never by full scans, without changing aggregation semantics.
    """
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    tid = sim_tasks[0].get("tid", sim_tasks[0]["pid"])
    tid2 = sim_tasks[1].get("tid", sim_tasks[1]["pid"]) or tid  # disjoint tid
    # resolved event (has task_id) for the primary path
    ev_resolved = {"event_type": "sched_wakeup", "timestamp_monotonic_ns": ts0 - 4_000_000,
                   "pid": 1, "tid": tid, "task_id": sim_tasks[0]["task_id"]}
    # legacy event (no task_id, matched by tid) for the fallback path
    ev_legacy = {"event_type": "sched_wakeup", "timestamp_monotonic_ns": ts0 - 3_000_000,
                 "pid": 1, "tid": tid}
    # outside window (600ms back > 500ms window; must be excluded)
    ev_out = {"event_type": "sched_wakeup", "timestamp_monotonic_ns": ts0 - 600_000_000,
              "pid": 1, "tid": tid}
    obs, stats = build_observations(sim_tasks, [ev_resolved, ev_legacy, ev_out],
                                    sim_sys, sim_psi, _ctx(ts0), "EXP-T", "s",
                                    window_ms=500, sample_ms=100, num_cpus=2)
    assert stats["observations"] > 0
    o = obs[0]
    # both same-window events counted, out-of-window excluded
    assert o["events_in_window"] == 2, o["events_in_window"]
    # last wakeup = latest of the two (even though fallback had no task_id)
    assert o["last_wakeup_ns"] == ts0 - 3_000_000
