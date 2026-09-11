# Data Schema (v1.0.0)

All models: `src/m1/models/`, pydantic v2, `SCHEMA_VERSION="1.0.0"`.

## TaskSnapshot (native /proc fields + cumulative counters)
task_id (`<pid>:<starttime_ticks>`, starttime = stat field 22), pid, tid, tgid,
ppid, comm, state, priority, nice, num_threads, starttime_ticks, processor,
cpu_affinity, utime/stime_ticks, voluntary/nonvoluntary_ctxt_switches,
read/write_bytes (cumulative io, **`io_scope="process"`** — `/proc/<pid>/io`
is process-level; thread rows repeat it with this label, never as per-thread),
rss_pages, timestamp_monotonic_ns (+wall separately).

## SchedulerEvent
event_type (switch/wakeup/wakeup_new/exec/exit), timestamp_monotonic_ns,
cpu, pid/tid/tgid, comm, task_id (when resolvable), plus per-type natives
(prev_pid/prev_state/next_pid/success/prio).

## SystemSnapshot
timestamp_monotonic_ns, total_cpu_util_pct (DERIVED from /proc/stat deltas),
per_cpu_util_pct (DERIVED), runnable_tasks (native/best-effort), load_1/5/15.

## PSISnapshot
cpu_some/mem_some/mem_full/io_some/io_full each {avg10, avg60, avg300, total_us}.
Semantics: % of time stalled in window; total = cumulative stall us.
CPU full is undefined system-wide and absent by design.

## ContextEvent
label (7 controlled values), scenario_id, foreground_app, app_state,
source="controlled_ground_truth", start/end monotonic ns.

## ObservationRecord
observation_id, experiment_id, timestamp_monotonic_ns (+wall), task identity
(task_id/pid/tid/tgid/cpu_id/state/priority/nice), native counters, DERIVED
(recent_cpu_runtime_ticks, cpu_util_pct, cs_rate_per_s, io_read/write_bps,
run_sleep_info, cpu_history), scheduler-in-window (events_in_window,
last_wakeup/switch_in/switch_out ns), system (sys_cpu_util_pct, runnable_tasks),
PSI (cpu/mem/io_some_10), context (user_state, foreground_app, scenario_id,
context_source), workload attribution (`workload_id`, `workload_type` from
`raw/workload_events`, None when unattributed). `run_sleep_info` is
**RESERVED/unavailable in M1 v1** (always None; derivation deferred).
Missing = null with optional missing_reason.

## Experiment/Machine/CollectorConfig/QAReport
ExperimentMetadata (scenario, times, versions, git hash, workload/context config,
intervals, `clk_tck`, `num_cpus`, `scheduler_backend` + version + `fidelity_level`,
`collector_failures[]`, `workload_events[]`, status), MachineMetadata (distro,
kernel, arch, cpu, mem, vm_info, btf/bpffs/psi flags, `clk_tck`, tool versions),
CollectorConfig (mirrors default.yaml + `psi_interval_ms` + requested backend),
`collector_config.json` (frozen replay contract + `config_hash`),
QAReport (verdict + checks + stats, incl. `backend_fidelity`,
`observation_uniqueness`, `impossible_timestamps`).
