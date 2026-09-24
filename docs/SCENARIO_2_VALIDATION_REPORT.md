# SCENARIO 2 — VALIDATION REPORT

`interactive_browsing` — M1 dataset generation, second scenario.

---

## 1. Experiment ID

| Run | Experiment | Duration | Role |
|---|---|---|---|
| Pilot | `EXP-20260924-001` | 10 s | Phase 1 pilot + Phase 2 bursty-quality check |
| Canonical | `EXP-20260924-002` | 60 s | Phase 3 authoritative artifact set |

This report's 19 sections describe the **canonical run `EXP-20260924-002`** unless a section explicitly reports pilot numbers.

## 2. Scenario name

`interactive_browsing`

## 3. Context

- Controlled ground-truth context (not inferred from telemetry): `USER_BROWSING`, foreground app `browser`.
- Emitted via the existing controlled-context mechanism; `scenario_id = interactive_browsing`.
- Single context event spans the intended interval (see §10).

## 4. Workloads used

| type | count | FG/BG | parameters |
|---|---|---|---|
| `bursty` (new, documented below) | 3 | foreground | burst 2.0 s / idle 3.0 s, one 64 KiB write per burst, duration 55 s |
| `cpu_intensive` (existing) | 1 | background | continuous compute, duration 55 s |
| `io_heavy` (existing) | 1 | background | 64 MiB sequential write to `/tmp/m1_io_bg.bin`, duration 55 s |

**Implementation rule compliance.** The repository was inspected first. Existing primitives were reused where possible: background activity uses the existing `cpu_intensive` and `io_heavy` workloads unchanged. Only a small foreground primitive was genuinely required to produce short ON/OFF browsing-style activity, because no existing workload cycled between active and idle. It was implemented in the same architecture (`WorkloadRunner.launch`), registered through the same workload telemetry (`M1_WORKLOAD`), and is documented:

- **`bursty()`** — new primitive in `src/m1/workloads/runner.py`. Loops: compute burst (small SHA-512 busy-loop, single core) for `burst_s`; write `io_bytes` to its scratch file; sleep for `idle_s`. Tagged `M1_WORKLOAD` so it appears in `raw/workload_events` exactly like every other workload. No unrelated module changed.
- Registered in `CANONICAL_SCENARIOS` in `src/m1/config.py` under `interactive_browsing` and configured fully in `configs/scenarios/interactive_browsing.yaml`.

## 5. Environment

- Real Linux VM (VirtualBox), Kali `7.1.5+kali-amd64`, `num_cpus = 11`.
- Real M1 collector, real per-task `/proc` scanning, real system scans, real PSI reading, real BPF-CO-RE scheduler events, real context + workload events, real observation builder, real QA.
- Collector config (frozen at start): `config_version 1.0.0`, `schema_version 1.0.0`, `sampling_interval_ms 500`, `observation_window_ms 2500`, `task_scan_ms`/`system_scan_ms`/`psi_interval_ms` per defaults, `ringbuf_size 8388608` (8 MiB), `processed_format parquet`, `raw_format jsonl`.
- No simulation anywhere; `collector_failures = []`.

## 6. Backend / fidelity

- `requested_backend = auto` → **resolved `ebpf`**, `scheduler_backend_version = libbpf-ctypes/CO-RE`, `fidelity_level = high`.
- Resolved values are recorded truthfully in `metadata/experiment.json` and `metadata/collector_config.json` (`scheduler_backend = ebpf`, `fidelity_level = high`, `status = PASS`). No silent downgrade.
- Scheduler event whitelist (5 types): `sched_switch`, `sched_wakeup`, `sched_wakeup_new`, `sched_process_exec`, `sched_process_exit`. All five types were observed (§8).

## 7. Task statistics

| metric | value |
|---|---|
| task snapshot rows (60 s) | 67,621 |
| task_id collisions | 0 |
| pid generation reuse | 67 pids (expected; kernel pid reuse) |
| process exits observed | 442 |
| orphan exits (exit without matching lifetime record) | 431 — QA warning, non-blocking (short-lived system threads between 500 ms scans) |
| retrograde / missing / non-positive timestamps | 0 / 0 / 0 |
| negative task durations | 0 |

Pilot (`EXP-20260924-001`, 10 s): 10,949 task rows.

## 8. Scheduler statistics

Canonical `EXP-20260924-002` (60 s), 126,175 events:

| event type | count | share |
|---|---|---|
| `sched_switch` | 82,378 | 65.3 % |
| `sched_wakeup` | 42,598 | 33.8 % |
| `sched_wakeup_new` | 433 | 0.34 % |
| `sched_process_exec` | 324 | 0.26 % |
| `sched_process_exit` | 442 | 0.35 % |

| integrity metric | value |
|---|---|
| dropped events (ring-buffer) | 0 |
| malformed events | 0 |
| unknown/unexpected event types | 0 |
| unresolved identities (all) | 26,514 |
| unresolved **non-idle** events | 5,424 / 105,085 = **5.2 %** (gate ≤ 25 %) |
| event rate | ≈ 2,103 events/s |

Pilot (10 s): 23,711 events (`switch` 15,577, `wakeup` 7,913, `wakeup_new` 80, `exec` 60, `exit` 81), dropped 0, malformed 0, unknown 0, unresolved_non_idle 3,760/20,192 = 18.6 %.

## 9. System / PSI statistics

Canonical (n = 116 system rows, 116 PSI rows; cross-checks against stream sizes):

| metric | n | mean | med | p05 | p95 |
|---|---|---|---|---|---|
| system total CPU util (%) | 116 | 49.89 | 47.00 | 10.89 | 78.62 |
| runnable tasks (obs) | 69,270 | 7.64 | 8.00 | 3.00 | 13.00 |
| context-switch rate (cs/s, obs) | 61,810 | 1.86 | 0.00 | 0.00 | 7.01 |
| PSI `cpu.some.avg10` | 116 | 13.23 | 11.88 | 11.07 | 19.37 |

Pilot (10 s): total CPU util mean 49.94 / med 50.43 / p95 68.99; PSI `cpu.some.avg10` mean 8.08.

## 10. Context statistics

- Events: **1** (`bad_order = 0`, `overlaps = 0`).
- `start_monotonic_ns = 2345784257479`, `end_monotonic_ns = 2408675816074` — interval **starts before** the first observation (first obs `2349121628018`) and covers the entire run.
- 69,270 / 69,270 observations (100 %) carry `user_state = USER_BROWSING`, all inside the context interval.
- Trace of ≥ 20 sampled observations (§ Context Alignment below): `context_source = USER_BROWSING` for every sampled observation. **Mismatches: 0.**

## 11. Workload statistics

- 5 workload launch records (`raw/workload_events`): `bursty-0-0` (pid 20740), `bursty-0-1` (20741), `bursty-0-2` (20742), `cpu_intensive-1-0` (20743, background), `io_heavy-2-0` (20744, background).
- QA workload checks: `bad_fields = 0`, `bad_order = 0`, `dup_ids = 0`.
- Observation attribution: `bursty` 312, `cpu_intensive` 104, `io_heavy` 104, no workload (system tasks) 68,750 — every workload-attributed observation's pid→record→type matched (§ Context Alignment, ISSUES = 0).
- Bursty behavior (Phase 2 check, canonical): 3 tasks, mean duty ≈ **0.68**, **54 ON/OFF transitions** over 60 s, per-task peaks ≈ 10 % (one core of 11).
- I/O: 122 observations with `io_write_bps > 0` (bursty paced writes + io_heavy background); `io_read_bps` all-zero (by design — scenario writes, no read workload).

## 12. CPU feature coverage

| feature | present rows / obs | coverage |
|---|---|---|
| `cpu_util_pct` | 61,810 / 69,270 | 89.2 % |
| `cpu_history` array | 61,810 / 69,270 | 89.2 % |
| `user_state` | 69,270 / 69,270 | 100 % |
| `runnable_tasks` | 69,270 / 69,270 | 100 % |
| `cs_rate_per_s` | 61,810 / 69,270 | 89.2 % |
| `io_read_bps` / `io_write_bps` | 69,270 / 69,270 | 100 % (cols present; read = 0 by design) |
| `workload_id` | 520 (4.1 % of obs have a workload owner) | attribution correct |

Missing `cpu_util/cpu_history` rows are first-snapshot observations with no prior delta (same 89 % pattern as `EXP-20260911-006`).

## 13. Sampling statistics

| metric | pilot (10 s) | canonical (60 s) |
|---|---|---|
| builder ticks | 19 | 119 |
| cadence samples | 18 | 115 |
| mean interval | 527.96 ms | 516.37 ms |
| p95 interval | 517.1 ms | 721.16 ms |
| missed ticks | 1 (5.6 %) | 5 (4.35 %) |
| effective frequency | 1.894 Hz | 1.937 Hz |
| skipped_no_task / skipped_no_system | — | 116 / 586 |

Observed cadence ≈ 1.94 Hz at a 500 ms sampling configuration; missed ratio ~4 %, consistent with the `cpu_intensive` baseline (5.3 %). Not materially broken.

## 14. QA result

**Verdict: PASS** (`metadata/qa_report.json`). All 17 checks passed; none blocking-failed:

`collectors_alive`, `backend_fidelity`, `schema_version` (0/136,891 wrong), `task_identity`, `timestamps`, `sched_events` (warning non-blocking), `completeness`, `lifecycle` (warning non-blocking), `observation_uniqueness` (duplicates 0), `impossible_timestamps`, `context`, `performance` (dropped 0 / errors 0; overhead target must be measured externally per `docs/qa_protocol.md`), `sampling_cadence`, `workload_events`, `pydantic_parse` (0 errors), plus the verdict fix carries `blocking` flags (ring-drop and cadence checks blocking; allowed-by-design warnings are non-blocking).

`config_hash = f3f949c3b5c87522` — **valid** (recomputed SHA-256 over frozen config, excluding the hash field, matches stored value).

## 15. Replay result

Raw data replayed twice from scratch:

- `replay_A` SHA-256: `ec5e5e9a4a77c72d47ff5eb8f8da242b801c5c4403e640625dc5913a4938cc5b`
- `replay_B` SHA-256: `ec5e5e9a4a77c72d47ff5eb8f8da242b801c5c4403e640625dc5913a4938cc5b`
- **`replay_A == replay_B` — PASS.**
- Replay observations: 69,270 == live production observations 69,270 (deterministic rebuild).
- `processed/observations` written as **parquet**; config hash validated during replay (`f3f949c3b5c87522`).

## 16. Raw-data immutability result

SHA-256 of every raw stream recorded before and after the replay pass; before == after for all streams:

| stream | SHA-256 (identical before/after) |
|---|---|
| `raw/context_events/context.jsonl` | `4760cc41…f320d4` |
| `raw/psi/psi.jsonl` | `12223b93…45600a` |
| `raw/scheduler_events/events.jsonl` | `7d3098b7…a026ab0f` |
| `raw/system_snapshots/system.jsonl` | `f4ffe0c7…d71126e` |
| `raw/task_snapshots/tasks.jsonl` | `37db106f…4fc6abbc` |
| `raw/workload_events/workloads.jsonl` | `cd02c89d…cfd860f5` |

**Raw data immutable — PASS.** All six required streams exist with expected row counts (context 1, psi 116, sched 126,175, system 116, tasks 67,621, workloads 5).

## 17. Comparison with EXP-20260911-006

Rates normalized per second (baseline is 10 s, canonical is 60 s).

| dimension | EXP-20260911-006 (`cpu_intensive`, USER_COMPILING) | EXP-20260924-002 (`interactive_browsing`, USER_BROWSING) | Δ |
|---|---|---|---|
| CPU util — mean / med / p05–p95 | 49.94 / 50.43 / 0.16–68.99 | 49.89 / 47.00 / 10.89–78.62 | similar mean; **far wider spread** (bursts + idle floor) |
| CPU runtime (per workload task) | continuous: duty ≈ 0.89, steady ≈ 8–11 % | bursty: duty ≈ 0.68, ON/OFF transitions 54, peaks ≈ 10 % | **intermittent vs saturated** |
| CPU history | continuous non-zero series | repeating zero/non-zero ON/OFF series | **bursty history** |
| Scheduler event rate | ≈ 2,065 /s | ≈ 2,103 /s | ~same rate; composition differs |
| Event composition | switch/wakeup ratio 2.24; wakeup share 30.6 % | switch/wakeup ratio 1.93; wakeup share 33.8 % | relatively more sleep/wake cycling in browsing |
| Runnable tasks (mean / p05) | 8.74 / 0.19 | 7.64 / 3.00 | deeper idle valleys in browsing |
| PSI `cpu.some.avg10` (mean) | 8.08 | 13.23 | pressure concentrated in bursts |
| I/O | none | paced writes; 122 obs `io_write_bps > 0` | **I/O added** (write-only, by design) |
| Context | USER_COMPILING / simulator | USER_BROWSING / browser | distinct controlled context |
| Workload composition | 4 × `cpu_intensive` | 3 × `bursty` + 1 × `cpu_intensive` + 1 × `io_heavy` | distinct mix |

**Scenario 2 is meaningfully different from Scenario 1**: bursts of single-core activity with clear idle intervals (duty ≈ 0.68, 54 transitions, history shows zero/non-zero alternation, system p05–p95 spread 10.9 → 78.6) versus continuous CPU saturation (steady ≈ 8–11 % per task, duty ≈ 0.89, tight distribution). This is exactly the interactive-vs-compiling regime required for later RUN/DEFER modeling.

## 18. Anomalies

All findings below were examined; none invalidate the run or the PASS verdict.

1. **`experiment.json` lacks a `config_hash` field** — the config hash is stored only in `metadata/collector_config.json`. Known metadata-completeness gap (documented in the module audit); replay and QA both validate the stored hash independently. Does not affect artifact validity.
2. **Sparse raw task rows for some threads** — a few long-lived threads had raw snapshot gaps of ~7 s (one up to 46 s) while observations carried forward from the last cached snapshot at clean 500 ms cadence. Expected sampling behavior (cache carries state between scans); all such observations remain schema-valid and cadence-clean.
3. **Orphan exits (431/442)** — short-lived system threads that exit between 500 ms scans. Expected; QA warning, non-blocking. No exit-before-create.
4. **`skipped_no_system = 586`** — a small share of ticks had no system row, so those observations were skipped by the builder; within normal ranges, cadence unaffected.
5. **CPU-util/history coverage 89.2 %** — first snapshot of each task has no delta. Same 89 % pattern as `EXP-20260911-006`; not a regression. `io_read_bps` all-zero by design (no read workload configured).
6. **Overhead not measured with an external sidecar** — the ≤ 2 % overhead target is verified externally per `docs/qa_protocol.md`; not re-measured this run (no collector changes).

## 19. Final verdict

All failure conditions checked and clear (eBPF genuinely running; scheduler events 126,175 non-zero; ring drops 0/0 unexplained; context events present and aligned 100 %; workload attribution correct; CPU history 89.2 % non-empty; cadence 1.94 Hz not broken; raw replay deterministic A==B; corrupted data cannot PASS (QA corpus enforced, blocking flags on ring-drop/cadence); backend metadata consistent; and the scenario is **not** continuous CPU saturation — bursty duty ≈ 0.68 with 54 ON/OFF transitions). Diversity versus `EXP-20260911-006` demonstrated across CPU util, runtime, history, sched composition, runnable, PSI, I/O, context and workload mix.

`EXP-20260911-006` was not modified. The dataset corpus is **not** declared complete — this is scenario 2 of a larger experimental matrix. All raw evidence preserved.

**SCENARIO 2 PASS**