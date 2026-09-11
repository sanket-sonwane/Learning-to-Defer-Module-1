"""Experiment controller: the 13-step automated run.

1. Create experiment ID   2. Load+validate scenario 3. Record metadata
4. Launch workload (+persist launch metadata) 5. Start collectors
6. Record controlled context 7. Run for duration (task+system+PSI+sched streams)
8. Stop workload    9. Stop collectors
10. Build observations     11. Run QA          12. Summary  13. Final status

Failure policy: any critical collector failure is recorded with component,
monotonic timestamp and reason, and forces the final verdict to FAIL or
QUARANTINE — never silent PASS. Raw output is append-only.
Linux-only for live collection; import-safe on Windows for tests.
"""
import hashlib
import json
import time
from pathlib import Path
from m1 import timebase
from m1.config import load_config, resolve_scenario, load_scenario
from m1.context.store import ContextStore
from m1.experiment.metadata import collect_machine_metadata, git_commit
from m1.ids import generate_experiment_id
from m1.models.experiment import CollectorFailure, ExperimentMetadata
from m1.platform_guard import require_linux
from m1.storage.layout import ExperimentLayout
from m1.storage.raw_writer import RawWriter


def _config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _cadence_stats(intervals_ms: list[float], requested_period_ns: int) -> dict:
    """Honest cadence measurement (fix doc #17): never claim the configured
    rate was achieved unless the data says so."""
    if not intervals_ms:
        return {"requested_period_ns": requested_period_ns, "samples": 0,
                "effective_freq_hz": None}
    s = sorted(intervals_ms)
    n = len(s)
    mean = sum(s) / n
    median = s[n // 2]
    p95 = s[min(n - 1, int(round(0.95 * (n - 1))))]
    p99 = s[min(n - 1, int(round(0.99 * (n - 1))))]
    jitter_ms = max(0.0, p95 - median)
    requested_ms = requested_period_ns / 1e6
    missed = [i for i in s if i > 1.5 * requested_ms]
    return {
        "requested_period_ns": requested_period_ns,
        "requested_ms": requested_ms,
        "samples": n,
        "mean_ms": round(mean, 3),
        "median_ms": round(median, 3),
        "p95_ms": round(p95, 3),
        "p99_ms": round(p99, 3),
        "jitter_ms": round(jitter_ms, 3),
        "missed_deadlines": len(missed),
        "missed_deadline_ratio": round(len(missed) / n, 4),
        "effective_freq_hz": round(1000.0 / mean, 3),
    }


class ExperimentController:
    def __init__(self, repo_root: Path, scenario: str, duration_s: float,
                 config_path: Path | None = None, no_bpf: bool = False):
        self.repo_root = repo_root
        self.scenario = scenario
        self.duration_s = duration_s
        self.config = load_config(config_path or repo_root / "configs" / "default.yaml")
        self.no_bpf = no_bpf
        self.experiment_id = generate_experiment_id(repo_root / "data")
        self.layout = ExperimentLayout(repo_root, self.experiment_id)
        self.failures: list[CollectorFailure] = []
        self.stats: dict = {}

    def _fail(self, component: str, reason: str, critical: bool = True) -> None:
        self.failures.append(CollectorFailure(
            component=component, failure_time_monotonic_ns=timebase.monotonic_ns(),
            reason=str(reason), critical=critical))

    def run(self) -> dict:
        require_linux("Experiment controller")
        import logging
        from m1.logging_setup import setup_logging, log_event
        self.layout.create()
        logger = setup_logging(self.layout.logs, self.experiment_id)
        scenario_path = resolve_scenario(self.scenario, self.repo_root)
        scenario_cfg = load_scenario(scenario_path)
        machine = collect_machine_metadata()
        clk_tck = machine.clk_tck
        num_cpus = machine.num_cpus or 1

        # Resolve scheduler backend BEFORE collection (recorded, never silent).
        requested = self.config.scheduler_backend
        if self.no_bpf or requested == "no-bpf":
            backend, fidelity, backend_version = "none", "none", ""
        elif requested in ("auto", "ebpf"):
            backend, fidelity = "ebpf", "high"
            backend_version = "libbpf-ctypes/CO-RE"
        else:
            backend, fidelity, backend_version = "tracefs_fallback", "reduced", "tracefs"

        meta = ExperimentMetadata(
            experiment_id=self.experiment_id, scenario=self.scenario,
            start_wall_ns=timebase.wall_ns(), duration_s=self.duration_s,
            config_version=self.config.config_version,
            git_commit=git_commit(self.repo_root),
            machine=machine, workload_config=scenario_cfg,
            context_config=scenario_cfg.get("context", {}),
            collection_intervals_ms={
                "task": self.config.task_scan_ms, "system": self.config.system_scan_ms,
                "psi": self.config.psi_scan_ms,
                "sampling": self.config.sampling_interval_ms},
            observation_window_ms=self.config.observation_window_ms,
            clk_tck=clk_tck, num_cpus=num_cpus,
            scheduler_backend=backend, scheduler_backend_version=backend_version,
            fidelity_level=fidelity)
        (self.layout.metadata / "experiment.json").write_text(meta.model_dump_json(indent=2))
        (self.layout.metadata / "machine.json").write_text(machine.model_dump_json(indent=2))
        frozen_cfg = {
            "experiment_id": self.experiment_id,
            "observation_window_ms": self.config.observation_window_ms,
            "sampling_interval_ms": self.config.sampling_interval_ms,
            "psi_interval_ms": self.config.psi_interval_ms,
            "task_scan_ms": self.config.task_scan_ms,
            "system_scan_ms": self.config.system_scan_ms,
            "requested_backend": requested,
            "scheduler_backend": backend,
            "scheduler_backend_version": backend_version,
            "fidelity_level": fidelity,
            "scenario": self.scenario,
            "clk_tck": clk_tck,
            "num_cpus": num_cpus,
            "schema_version": self.config.schema_version,
            "config_version": self.config.config_version,
            "sched_events": list(self.config.sched_events),
            "ringbuf_size": getattr(self.config, "ringbuf_size", 8388608),
            "raw_format": "jsonl",
            "processed_format": "parquet",
        }
        frozen_cfg["config_hash"] = _config_hash(frozen_cfg)
        (self.layout.metadata / "collector_config.json").write_text(
            json.dumps(frozen_cfg, indent=2))

        # Context: single controlled interval for the whole run (v1).
        ctx_store = ContextStore(self.experiment_id, self.scenario)
        ctx_cfg = scenario_cfg.get("context", {})
        ctx_store.start(ctx_cfg.get("label", "USER_ACTIVE"),
                        foreground_app=ctx_cfg.get("foreground_app", ""))

        # Workloads (+ persisted launch metadata, not just env tags).
        from m1.workloads.runner import WorkloadRunner
        runner = WorkloadRunner(self.experiment_id)
        try:
            for i, w in enumerate(scenario_cfg.get("workloads", [])):
                for rep in range(int(w.get("count", 1))):
                    runner.launch(w.get("type", "cpu_intensive"),
                                  float(w.get("duration_s", self.duration_s)),
                                  workload_id=f"{w.get('type', 'cpu')}-{i}-{rep}",
                                  **{k: v for k, v in w.items()
                                     if k not in ("type", "count", "duration_s")})
        except Exception as e:
            log_event(logger, logging.ERROR, "workload_launch_failed", error=str(e))
            self._fail("workload", e)
        wl_w = RawWriter(self.layout.raw_workloads / "workloads.jsonl")
        wl_w.write_many(runner.launched)
        meta.workload_events = runner.launched

        # Collectors
        from m1.system.cpu import SystemCollector
        from m1.psi.reader import PSIReader
        from m1.telemetry.sampler import TaskSampler
        task_w = RawWriter(self.layout.raw_tasks / "tasks.jsonl")
        sys_w = RawWriter(self.layout.raw_system / "system.jsonl")
        psi_w = RawWriter(self.layout.raw_psi / "psi.jsonl")
        psi_rows: list[dict] = []
        sched_rows: list[dict] = []
        task_rows: list[dict] = []
        sys_rows: list[dict] = []
        sampler = TaskSampler(self.experiment_id, self.config.task_scan_ms, num_cpus, clk_tck)
        sys_col = SystemCollector(self.experiment_id)
        psi_col = PSIReader(self.experiment_id)
        sched = None
        if backend == "ebpf":
            try:
                from m1.sched_events.collector import SchedCollector
                sched = SchedCollector(self.experiment_id)
                sched.start()
                if set(sched.attached()) != set(self.config.sched_events):
                    self._fail("sched",
                               f"attached {sched.attached()} != required {self.config.sched_events}")
            except Exception as e:
                log_event(logger, logging.ERROR, "sched_collector_failed", error=str(e))
                self._fail("sched", e)
                sched = None
                # Fall back to tracefs if auto, otherwise disable.
                if requested == "auto":
                    try:
                        from m1.sched_events.fallback import TracefsFallback
                        fb = TracefsFallback(self.experiment_id)
                        if fb.available():
                            fb.start()
                            sched = fb
                            backend, fidelity = "tracefs_fallback", "reduced"
                            backend_version = "tracefs"
                            meta.scheduler_backend = backend
                            meta.fidelity_level = fidelity
                            log_event(logger, logging.INFO, "tracefs_fallback_activated")
                        else:
                            backend, fidelity = "none", "none"
                            meta.scheduler_backend, meta.fidelity_level = backend, fidelity
                    except Exception as e2:
                        log_event(logger, logging.ERROR, "tracefs_fallback_failed", error=str(e2))
                        backend, fidelity = "none", "none"
                        meta.scheduler_backend, meta.fidelity_level = backend, fidelity
                else:
                    backend, fidelity = "none", "none"
                    meta.scheduler_backend, meta.fidelity_level = backend, fidelity

        # GenerationTracker: maps (pid, timestamp_range) -> task_id for
        # scheduler event attribution across PID reuse.
        from m1.sched_events.correlate import GenerationTracker
        gen_tracker = GenerationTracker()

        psi_cadence = max(1, int(self.config.psi_interval_ms / self.config.sampling_interval_ms))
        end = time.monotonic() + self.duration_s
        # Absolute-deadline scheduler (fix doc #17): never `scan(); sleep(period)`.
        # Cadence is driven by adding the period to an absolute deadline, so the
        # scan/poll/sys cost never accumulates into the interval.
        period_s = self.config.sampling_interval_ms / 1000.0
        next_deadline = time.monotonic() + period_s
        prev_scan_start: float | None = None
        cadence_ms: list[float] = []
        tick = 0
        task_consec_errors = sys_consec_errors = psi_consec_errors = 0
        try:
            while time.monotonic() < end:
                scan_start = time.monotonic()
                if prev_scan_start is not None:
                    cadence_ms.append((scan_start - prev_scan_start) * 1e3)
                prev_scan_start = scan_start
                try:
                    rows = sampler.sample_once()
                    task_w.write_many(rows)
                    task_rows.extend(rows)
                    # Feed GenerationTracker: observe new/updated tasks, close exited.
                    now_ns = timebase.monotonic_ns()
                    for r in rows:
                        pid = r.get("pid")
                        if pid is not None:
                            gen_tracker.observe(pid, r["task_id"],
                                                r.get("starttime_ticks"), now_ns,
                                                tid=r.get("tid"))
                    for exited_id in getattr(sampler, "exited_ids", []):
                        # exited_id is task_id = "<tid>:<starttime>"; the prefix
                        # is the thread-level identity sched events carry.
                        try:
                            e_tid = int(exited_id.split(":")[0])
                            gen_tracker.close(e_tid, now_ns)
                        except (ValueError, IndexError):
                            pass
                    task_consec_errors = 0
                except Exception as e:
                    task_consec_errors += 1
                    log_event(logger, logging.ERROR, "task_sample_failed", error=str(e))
                    if task_consec_errors >= 10:
                        self._fail("task_sampler", f"10 consecutive errors: {e}")
                        break
                try:
                    s = sys_col.sample()
                    sys_w.write(s)
                    sys_rows.append(s.model_dump())
                    sys_consec_errors = 0
                except Exception as e:
                    sys_consec_errors += 1
                    log_event(logger, logging.ERROR, "system_sample_failed", error=str(e))
                    if sys_consec_errors >= 10:
                        self._fail("system_sampler", f"10 consecutive errors: {e}")
                        break
                if tick % psi_cadence == 0:
                    try:
                        p = psi_col.sample()
                        psi_w.write(p)
                        psi_rows.append(p.model_dump())
                        psi_consec_errors = 0
                    except Exception as e:
                        psi_consec_errors += 1
                        log_event(logger, logging.ERROR, "psi_sample_failed", error=str(e))
                        if psi_consec_errors >= 5:
                            self._fail("psi_sampler", f"5 consecutive errors: {e}",
                                       critical=False)
                if sched is not None:
                    try:
                        # Non-blocking drain (0ms): ring buffer holds events
                        # between polls, so we never burn scan budget waiting.
                        for ev in sched.poll(0):
                            sched_rows.append(ev.model_dump())
                    except Exception as e:
                        log_event(logger, logging.ERROR, "sched_poll_failed", error=str(e))
                        self._fail("sched", f"poll failed: {e}")
                        try:
                            sched.stop()
                        except Exception:
                            pass
                        sched = None
                tick += 1
                # Absolute-deadline: sleep only the remaining budget of this
                # period; overruns fall through to the next tick immediately.
                next_deadline += period_s
                sleep_for = next_deadline - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            runner.stop_all()
            if sched is not None:
                try:
                    sched.stop()
                except Exception:
                    pass
            try:
                ctx_store.end()
            except Exception:
                pass
            ctx_w = RawWriter(self.layout.raw_context / "context.jsonl")
            ctx_w.write_many([e.model_dump() for e in ctx_store.events])
            ctx_w.close()
            sched_w = RawWriter(self.layout.raw_sched / "events.jsonl")
            sched_w.write_many(sched_rows)
            sched_w.close()
            task_w.close()
            sys_w.close()
            psi_w.close()
            wl_w.close()

        # Build observations (experiment's recorded clk_tck + workload attribution).
        from m1.builder.sync import build_observations
        ctx_dicts = [e.model_dump() for e in ctx_store.events]
        obs, bstats = build_observations(
            task_rows, sched_rows, sys_rows, psi_rows, ctx_dicts,
            self.experiment_id, self.scenario,
            window_ms=self.config.observation_window_ms,
            sample_ms=self.config.sampling_interval_ms,
            num_cpus=num_cpus, clk_tck=clk_tck,
            workloads=runner.launched,
            gen_tracker=gen_tracker)
        self.stats["builder"] = bstats
        self.stats["task_anomalies"] = sampler.anomalies
        self.stats["sampling_cadence"] = _cadence_stats(cadence_ms,
                                                        period_s * 1e9)
        try:
            from m1.storage.parquet_writer import write_observations_parquet
            write_observations_parquet(obs, self.layout.processed / "observations.parquet")
            self.stats["parquet"] = True
        except RuntimeError:
            (self.layout.processed / "observations.jsonl").write_text(
                "\n".join(json.dumps(o, default=str) for o in obs))
            self.stats["parquet"] = False

        # QA (critical failures force non-PASS inside run_all).
        from m1.qa.checks import run_all
        sched_stats = sched.stats() if sched else {"backend": backend, "fidelity": fidelity}
        report = run_all(self.experiment_id, task_rows, sched_rows, sys_rows,
                         psi_rows, ctx_dicts, obs,
                         sched_stats=sched_stats,
                         failed_collectors=[f"{f.component}: {f.reason}" for f in self.failures
                                            if f.critical],
                         backend=backend,
                         unresolved_identities=gen_tracker.unresolved,
                         sched_attribution=bstats,
                         sampling_cadence=self.stats.get("sampling_cadence"),
                         workload_events=runner.launched)
        (self.layout.metadata / "qa_report.json").write_text(report.model_dump_json(indent=2))
        summary = {"experiment_id": self.experiment_id, "scenario": self.scenario,
                   "verdict": report.verdict, "stats": self.stats,
                   "backend": backend, "fidelity": fidelity,
                   "failures": [f.model_dump() for f in self.failures],
                   "sched": sched_stats,
                   "unresolved_identities": gen_tracker.unresolved}
        (self.layout.metadata / "summary.json").write_text(json.dumps(summary, indent=2))
        meta.status = report.verdict
        meta.end_wall_ns = timebase.wall_ns()
        meta.collector_failures = self.failures
        meta.scheduler_backend = backend
        meta.fidelity_level = fidelity
        (self.layout.metadata / "experiment.json").write_text(meta.model_dump_json(indent=2))
        log_event(logger, logging.INFO, "experiment_done", verdict=report.verdict)
        return summary
