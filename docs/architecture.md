# Architecture

M1 has six subsystems with clean boundaries:

- **M1.1 Task Discovery** (`task_discovery/`): /proc scans, `task_id=pid:starttime`, registry (create/exists/exit).
- **M1.2 Runtime Telemetry** (`telemetry/`): repeated sampling, `delta_or_none` deltas (missing→None, negative→None+anomaly, never 0-fill) → cpu_util/io rates/cs rates + history windows, using the experiment's recorded `SC_CLK_TCK`. Native vs derived labeled.
- **M1.3 Scheduler Events** (`sched_events/`): libbpf CO-RE BPF (`bpf/sched_collect.bpf.c`, ringbuf) + ctypes `libbpf_loader.py` (loads the compiled `.o`, attaches all 5 tracepoints; NO BCC mixing) + `collector.py` (canonical 84-byte ABI decode per `abi.md`, counters received/decoded/dropped/malformed/unknown) + `correlate.py` (PID/TID→task_id generation resolution) + tracefs fallback. Drop counters mandatory. No sched_ext.
- **M1.4 System Context** (`system/`): /proc/stat deltas (total/per-CPU util), loadavg, runnable count (sched_debug -> procs_running -> None).
- **M1.5 PSI** (`psi/`): `/proc/pressure/{cpu,memory,io}` sampled as a **monotonic time series** (`raw/psi/psi.jsonl`, `psi_interval_ms` cadence), `some avg10/60/300 total` (+full for mem/io only; CPU full never collected).
- **M1.6 Context** (`context/`): controlled ground truth labels, interval store with resolve(T).
- **Builder** (`builder/sync.py`): joins the five streams on CLOCK_MONOTONIC ns at configurable sampling (default 100ms) over a window (default 500ms). Temporal model: observation T, window [T−W,T]; task/system/PSI = latest sample ≤ T; sched events aggregated in-window; context must contain T. Event frequency != observation frequency. Stamps `workload_id/type` from launch metadata; `run_sleep_info` reserved (None) in v1.
- **Storage** (`storage/`): raw JSONL immutable (incl. `psi/`, `workload_events/`) + processed Parquet + `metadata/{experiment,machine,collector_config,qa_report,summary}.json`. `collector_config.json` is the frozen replay contract (+config hash). Replay regenerates processed from raw and refuses on missing/incomplete/tampered config.
- **Experiment** (`experiment/controller.py`): 13-step automation with canonical scenario resolution, recorded `SC_CLK_TCK`, resolved `scheduler_backend`/`fidelity_level`, per-component failure records (component, monotonic time, reason), consecutive-error breakers, workload launch metadata. `scripts/run_collector.sh` is a thin orchestrator (args, env check, trap, delegate).
- **QA** (`qa/checks.py`): schema/identity/timestamps/impossible-ts/uniqueness/events/completeness/lifecycle(+exit-before-create)/context/backend-fidelity/performance/parse → PASS/QUARANTINE/FAIL. Critical collector failure or non-ebpf backend can never PASS as authoritative.
