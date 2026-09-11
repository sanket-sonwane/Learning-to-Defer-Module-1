"""Experiment directory layout (raw is append-only/immutable after completion).

data/<EXP-ID>/
    raw/
        scheduler_events/   eBPF/tracefs scheduler events (JSONL)
        task_snapshots/     /proc task snapshots (JSONL)
        system_snapshots/   /proc/stat+load snapshots (JSONL)
        context_events/     controlled context intervals (JSONL)
        psi/                PSI time series (JSONL)
        workload_events/    workload launch metadata (JSONL)
    processed/
        observations/       built observations (parquet/jsonl) + replays
    metadata/
        experiment.json collector_config.json machine.json
        qa_report.json summary.json
logs/<EXP-ID>/{collector.log, scheduler.log, qa.log}
"""
from pathlib import Path


class ExperimentLayout:
    def __init__(self, repo_root: Path, experiment_id: str):
        self.repo_root = repo_root
        self.experiment_id = experiment_id
        self.root = repo_root / "data" / experiment_id
        self.raw_sched = self.root / "raw" / "scheduler_events"
        self.raw_tasks = self.root / "raw" / "task_snapshots"
        self.raw_system = self.root / "raw" / "system_snapshots"
        self.raw_context = self.root / "raw" / "context_events"
        self.raw_psi = self.root / "raw" / "psi"
        self.raw_workloads = self.root / "raw" / "workload_events"
        self.processed = self.root / "processed" / "observations"
        self.metadata = self.root / "metadata"
        self.logs = repo_root / "logs" / experiment_id

    def create(self) -> None:
        for d in (self.raw_sched, self.raw_tasks, self.raw_system, self.raw_context,
                  self.raw_psi, self.raw_workloads,
                  self.processed, self.metadata, self.logs):
            d.mkdir(parents=True, exist_ok=True)
