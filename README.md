# M1 — Context & Runtime Data Collection ("Observation Framework v1")

Research project: **Learning to Defer: Context-Aware CPU Scheduling for Linux.**

M1 is a reliable, reproducible, low-overhead Linux observation layer capturing
task/runtime info, scheduler events (eBPF), system context, PSI time series,
and controlled user/application ground truth as synchronized time-series
observations for downstream CPU-need learning.

**Scope:** collection + synchronization + storage + QA only.
**Non-goals:** CPU-need model, training, SLM, RUN/DEFER decisions, scheduler
replacement, sched_ext (explicitly deferred to a later module).

## Architecture

```
Experiment Definition -> Scenario resolve -> Experiment ID -> Env Validation
 -> Task Discovery (/proc, pid:starttime identity)
 -> Runtime Telemetry (delta_or_none deltas, experiment SC_CLK_TCK)
 -> eBPF Scheduler Events (libbpf CO-RE, ringbuf, 84-byte ABI)
 -> System Metrics (/proc/stat) -> PSI time series (/proc/pressure/*)
 -> Controlled Context -> Workload launch metadata
 -> Raw JSONL (immutable) -> Observation Builder (500ms window / 100ms sampling)
 -> Parquet observations -> QA (PASS/QUARANTINE/FAIL) -> Summary + Metadata
```

eBPF stack: **libbpf CO-RE** loaded via ctypes (`libbpf_loader.py`), BPF ring
buffer, canonical ABI in `src/m1/sched_events/abi.md`. Config: **YAML**.
Parquet via **pyarrow** (required on Linux, JSONL fallback on Windows dev).

## Windows development

```powershell
pip install -r requirements-base.txt
$env:PYTHONPATH="D:\Final Year PRoject\Module 1\M1\src"
pytest tests -q   # unit + replay pass; Linux-only integration skips
python -m compileall src tests
```

Linux-only collectors raise `LinuxOnlyError` on Windows. Sim fixtures feed
synthetic Linux-like data into builder/storage/QA/replay (`simulated=True`).

## BlackArch VM execution

```bash
git pull
./scripts/check_environment.sh          # PASS/WARN/FAIL tagged REQUIRED/EBPF/OPTIONAL/FALLBACK
sudo ./scripts/install_linux.sh         # Arch-aware (pacman); re-run checker
./scripts/build_bpf.sh                  # BTF -> vmlinux.h -> sched_collect.bpf.o (hard-fails, no fallback)
./scripts/run_collector.sh --scenario cpu_intensive --duration 10 --no-bpf --dry-run
sudo ./scripts/run_collector.sh --scenario cpu_intensive --duration 60
python -m m1.replay --experiment-id EXP-20260910-001   # strict: uses frozen collector_config.json
```

Canonical scenarios: `cpu_intensive` (default), `fg_bg_competition`,
`fork_churn`, `io_heavy`, `mixed`. Unknown IDs exit 2 with the valid list.

## Output layout

```
data/<EXP-ID>/raw/{scheduler_events,task_snapshots,system_snapshots,context_events,psi,workload_events}/*.jsonl
data/<EXP-ID>/processed/observations/{observations.*,replay_observations.*}
data/<EXP-ID>/metadata/{experiment,machine,collector_config,qa_report,summary}.json
logs/<EXP-ID>/{collector.log,scheduler.log,qa.log}
```

Raw is append-only; replay/QA never modify it. `collector_config.json` is the
frozen replay contract (window, sampling, PSI cadence, backend, fidelity,
scenario, clk_tck, cpus, versions + config hash).

## Data model

Pydantic v2 (`src/m1/models/`, `SCHEMA_VERSION="1.0.0"`). Integrity rules:
`task_id = "<pid>:<starttime_ticks>"` (never PID-only; events correlated via
generation tracker); missing = `None` (never 0; `delta_or_none` + anomaly
counts); `io_scope="process"` (`/proc/<pid>/io` is process-level);
`run_sleep_info` reserved/unavailable in v1; `workload_id/type` stamped from
launch metadata; drops/malformed/unknown counted; `scheduler_backend` +
`fidelity_level` on every experiment (eBPF=high required for authoritative
verdicts); VM measurements never claimed as native.

## Docs

- `docs/architecture.md`, `docs/data_schema.md`, `docs/linux_setup.md`,
- `docs/experiment_protocol.md`, `docs/qa_protocol.md`, `docs/troubleshooting.md`
- `src/m1/sched_events/abi.md` — canonical 84-byte event ABI.

## Limitations

VM ≠ native; CO-RE needs BTF; runnable source varies by kernel; high event
rates may drop (counted); BPF needs root/CAP_BPF; `pyarrow` heavy on Arch;
BPF load/ring-buffer validation is Linux-only (see validation report).
