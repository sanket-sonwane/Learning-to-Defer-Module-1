"""Replay: regenerate processed observations from preserved raw data.

Usage: python -m m1.replay --experiment-id EXP-YYYYMMDD-NNN [--repo ROOT]

Determinism contract: replay uses ONLY the experiment's recorded
metadata/collector_config.json. If that file is missing or incomplete,
replay FAILS loudly instead of substituting current defaults (which could
silently produce a different dataset). A config-hash check detects post-hoc
modification of the collection configuration (QA corruption case F).
"""
import argparse
import hashlib
import json
from pathlib import Path
from m1.builder.sync import build_observations
from m1.storage.layout import ExperimentLayout

REQUIRED_REPLAY_KEYS = ("observation_window_ms", "sampling_interval_ms",
                        "schema_version", "scenario", "clk_tck", "num_cpus")


class ReplayError(RuntimeError):
    pass


def _config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_replay_config(layout: ExperimentLayout) -> dict:
    """Load the frozen collection config; fail loudly if absent/incomplete."""
    path = layout.metadata / "collector_config.json"
    if not path.exists():
        raise ReplayError(
            f"{path} missing — cannot replay without the original collection "
            "configuration. Refusing to substitute defaults.")
    cfg = json.loads(path.read_text())
    missing = [k for k in REQUIRED_REPLAY_KEYS if k not in cfg or cfg[k] is None]
    if missing:
        raise ReplayError(f"collector_config.json incomplete, missing {missing} — refusing replay.")
    return cfg


def replay(experiment_id: str, repo_root: Path) -> dict:
    layout = ExperimentLayout(repo_root, experiment_id)
    meta_path = layout.metadata / "experiment.json"
    if not meta_path.exists():
        raise ReplayError(f"{meta_path} missing — unknown experiment {experiment_id!r}.")
    meta = json.loads(meta_path.read_text())
    cfg = load_replay_config(layout)
    # Detect post-hoc modification: stored hash must match recomputed hash.
    stored_hash = cfg.get("config_hash")
    if stored_hash is not None:
        check = dict(cfg)
        check.pop("config_hash", None)
        if _config_hash(check) != stored_hash:
            raise ReplayError(
                "collector_config.json was modified after collection "
                f"(hash {stored_hash} != recomputed {_config_hash(check)}). "
                "Refusing replay to avoid a silently different dataset.")

    def load_all(d: Path) -> list[dict]:
        rows = []
        for f in sorted(d.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    tasks = load_all(layout.raw_tasks)
    sched = load_all(layout.raw_sched)
    sys_rows = load_all(layout.raw_system)
    psi = load_all(layout.raw_psi)
    ctx = load_all(layout.raw_context)
    workloads = load_all(layout.raw_workloads)
    obs, stats = build_observations(
        tasks, sched, sys_rows, psi, ctx, experiment_id, cfg["scenario"],
        window_ms=int(cfg["observation_window_ms"]),
        sample_ms=int(cfg["sampling_interval_ms"]),
        num_cpus=int(cfg["num_cpus"]) or 1,
        clk_tck=int(cfg["clk_tck"]),
        workloads=workloads)
    # Derived artifact (never touches raw): replay_observations.jsonl
    out_path = layout.processed / "replay_observations.jsonl"
    with out_path.open("w") as f:
        for o in obs:
            f.write(json.dumps(o, default=str) + "\n")
    try:
        from m1.storage.parquet_writer import write_observations_parquet
        write_observations_parquet(obs, layout.processed / "replay_observations.parquet")
        stats["parquet"] = True
    except RuntimeError:
        stats["parquet"] = False
    stats["output"] = str(out_path)
    stats["config_hash"] = stored_hash
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment-id", required=True)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    try:
        stats = replay(args.experiment_id, Path(args.repo))
    except ReplayError as e:
        print(f"REPLAY FAILED: {e}")
        raise SystemExit(1)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
