"""Blocker 7: replay recovers the exact collection config or refuses."""
import json
import pytest
from m1.builder.replay import ReplayError, _config_hash, load_replay_config, replay
from m1.storage.layout import ExperimentLayout


def _layout(tmp_path, exp="EXP-20260101-003"):
    layout = ExperimentLayout(tmp_path, exp)
    layout.create()
    (layout.metadata / "experiment.json").write_text(json.dumps({"scenario": "s"}))
    return layout


def _good_cfg():
    cfg = {"observation_window_ms": 500, "sampling_interval_ms": 100,
           "schema_version": "1.0.0", "scenario": "s", "clk_tck": 100, "num_cpus": 2}
    cfg["config_hash"] = _config_hash(cfg)
    return cfg


def test_replay_configuration(tmp_path):
    layout = _layout(tmp_path)
    # Missing config → loud refusal, never silent defaults.
    with pytest.raises(ReplayError, match="missing"):
        load_replay_config(layout)
    with pytest.raises(ReplayError):
        replay(layout.experiment_id, tmp_path)
    # Incomplete config → refusal.
    (layout.metadata / "collector_config.json").write_text(json.dumps({"scenario": "s"}))
    with pytest.raises(ReplayError, match="incomplete"):
        load_replay_config(layout)
    # Tampered config (hash mismatch) → refusal.
    cfg = _good_cfg()
    cfg["sampling_interval_ms"] = 50  # post-hoc modification
    (layout.metadata / "collector_config.json").write_text(json.dumps(cfg))
    with pytest.raises(ReplayError, match="modified"):
        replay(layout.experiment_id, tmp_path)
    # Intact config loads.
    cfg = _good_cfg()
    (layout.metadata / "collector_config.json").write_text(json.dumps(cfg))
    assert load_replay_config(layout)["sampling_interval_ms"] == 100


def test_replay_determinism(tmp_path, sim_tasks, sim_sched, sim_sys):
    """raw → replay #1 → A; raw → replay #2 → B; A == B and raw untouched."""
    import hashlib
    layout = _layout(tmp_path, "EXP-20260101-004")
    cfg = _good_cfg()
    (layout.metadata / "collector_config.json").write_text(json.dumps(cfg))
    ts0 = sim_tasks[0]["timestamp_monotonic_ns"]
    ctx = [{"label": "USER_IDLE", "foreground_app": "x", "scenario_id": "s",
            "start_monotonic_ns": ts0 - 10**9, "end_monotonic_ns": ts0 + 10**12}]
    for d, rows in ((layout.raw_tasks, sim_tasks), (layout.raw_sched, sim_sched),
                    (layout.raw_system, sim_sys), (layout.raw_context, ctx)):
        with (d / "data.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")

    def _raw_hash():
        h = hashlib.sha256()
        for p in sorted(layout.root.rglob("*.jsonl")):
            if "processed" not in p.parts:
                h.update(p.read_bytes())
        return h.hexdigest()

    before = _raw_hash()
    replay(layout.experiment_id, tmp_path)
    out_a = (layout.processed / "replay_observations.jsonl").read_text()
    replay(layout.experiment_id, tmp_path)
    out_b = (layout.processed / "replay_observations.jsonl").read_text()
    assert out_a == out_b and len(out_a.splitlines()) > 0
    assert _raw_hash() == before  # replay never modifies raw evidence
