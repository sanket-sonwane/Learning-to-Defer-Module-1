# Experiment Protocol

Run: `./scripts/run_collector.sh --scenario <canonical-id> --duration <secs> [--no-bpf]`
Canonical IDs (= file stems in configs/scenarios/): `cpu_intensive` (default),
`fg_bg_competition`, `fork_churn`, `io_heavy`, `mixed`. Unknown IDs fail with
the valid list (exit 2). Duration 60s default for real runs; 10s smoke with --no-bpf.

The controller: resolves+validates the scenario (internal id must match the
file), generates EXP-YYYYMMDD-NNN, writes metadata (config versions, git hash,
machine incl. `SC_CLK_TCK`, resolved backend/fidelity, workload/context config),
freezes `collector_config.json` (+hash), launches workloads (each launch
persisted to `raw/workload_events/` with id/type/pid/start — env tags are
secondary markers only), records one controlled context interval, streams
task/system/PSI (own cadence)/sched samples for the duration with
consecutive-error breakers and timestamped failure records, stops everything
safely (trap INT/TERM), builds observations (500ms window / 100ms sampling
defaults, experiment clk_tck), writes Parquet (or JSONL fallback), runs QA,
writes summary + verdict. Any critical failure forces non-PASS.

Reproducibility: config_version + schema_version + git_commit + machine metadata
+ frozen collector config stored per experiment. Replay:
`python -m m1.replay --experiment-id EXP-...` uses ONLY the frozen config and
refuses on missing/incomplete/tampered config (hash check); output is
`replay_observations.*`, raw untouched (verified by test).
