# Troubleshooting

- `LinuxOnlyError` on Windows: expected. Use sim/tests only on Windows.
- Empty observations + `skipped_no_context`: context interval missing (controller
  always writes one; replay needs context.jsonl present).
- `BPF object not found`: build on the VM with `./scripts/build_bpf.sh` (see linux_setup.md).
- `system libbpf.so not found`: install `libbpf` via `scripts/install_linux.sh`.
- `Failed to attach required tracepoints`: missing privileges or kernel support; eBPF backend cannot claim full fidelity — fix or run `--no-bpf` (reduced, non-authoritative).
- `REPLAY FAILED: ... missing/incomplete/modified`: replay needs the frozen `collector_config.json`; never hand-edit it (hash-guarded).
- Unknown scenario: use a canonical id (`cpu_intensive`, `fg_bg_competition`, `fork_churn`, `io_heavy`, `mixed`); the script lists valid values (exit 2).
- `Scenario id mismatch`: internal `scenario:` must equal the file stem.
- PSI missing: kernel without CONFIG_PSI or container mask; QA flags it, run continues.
- `procs_running` fallback: runnable_tasks may be None; recorded with reason.
- Parquet write fails: pyarrow missing -> JSONL fallback written; install
  requirements-linux.txt on the VM.
- High sched drops: shrink scenario, grow ringbuf_size in config, prefer fewer
  tracepoints; drops are counted in QA, never hidden.
- `sched tracepoints missing`: wrong mount (`/sys/kernel/tracing` vs
  `/sys/kernel/debug/tracing`) or restricted kernel; check Баш with
  `ls /sys/kernel/tracing/events/sched`.
- Arch `bpftool` package name differs: install script uses `bpftool`; if pacman
  fails, `pacman -Ss bpftool` and install manually, then re-run checker.
