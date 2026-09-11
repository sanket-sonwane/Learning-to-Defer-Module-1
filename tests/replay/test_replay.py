"""Replay tests: same raw input -> reproducible processed observations."""
import json
from m1.builder.replay import replay
from m1.builder.sync import build_observations


def _ctx(ts0):
    return [{"label": "USER_COMPILING", "foreground_app": "make",
             "scenario_id": "s", "start_monotonic_ns": ts0 - 10**9,
             "end_monotonic_ns": ts0 + 10**12}]


def test_builder_deterministic(sim_tasks, sim_sched, sim_sys, sim_psi):
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    a, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                              _ctx(ts0), "EXP-T", "s")
    b, _ = build_observations(sim_tasks, sim_sched, sim_sys, sim_psi,
                              _ctx(ts0), "EXP-T", "s")
    assert a == b


def test_replay_from_raw(tmp_path, sim_tasks, sim_sched, sim_sys):
    from m1.builder.replay import _config_hash
    from m1.storage.layout import ExperimentLayout
    exp = "EXP-20260101-001"
    layout = ExperimentLayout(tmp_path, exp)
    layout.create()
    (layout.metadata / "experiment.json").write_text(json.dumps({"scenario": "s"}))
    cfg = {"observation_window_ms": 500, "sampling_interval_ms": 100,
           "schema_version": "1.0.0", "scenario": "s", "clk_tck": 100, "num_cpus": 2}
    cfg["config_hash"] = _config_hash(cfg)
    (layout.metadata / "collector_config.json").write_text(json.dumps(cfg))
    for name, rows in (("tasks.jsonl", sim_tasks), ("events.jsonl", sim_sched),
                       ("system.jsonl", sim_sys)):
        d = {"tasks.jsonl": layout.raw_tasks, "events.jsonl": layout.raw_sched,
             "system.jsonl": layout.raw_system}[name]
        with (d / name).open("w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    with (layout.raw_context / "context.jsonl").open("w") as f:
        f.write(json.dumps(_ctx(ts0)[0]) + "\n")
    stats = replay(exp, tmp_path)
    assert stats["observations"] > 0
    # Second replay must reproduce the same output.
    out = (layout.processed / "replay_observations.jsonl").read_text()
    stats2 = replay(exp, tmp_path)
    assert (layout.processed / "replay_observations.jsonl").read_text() == out
    assert stats2["observations"] == stats["observations"]
