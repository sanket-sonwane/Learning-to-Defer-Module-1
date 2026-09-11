# QA Protocol

Checks (`src/m1/qa/checks.py::run_all`): collectors_alive (critical),
backend_fidelity (critical unless ebpf; fallback=warning → at best QUARANTINE),
schema_version (critical), task_identity/PID-reuse (critical),
timestamps/retrograde/negative (critical), impossible_timestamps incl. missing
ts (critical), observation_uniqueness (critical), sched_events incl.
drops/malformed (critical if empty/malformed; warning if drops>0),
completeness (critical if streams missing), lifecycle incl. exit-before-create
(critical) and orphan exits (warning), context order/overlap (critical),
performance drops/errors (warning), pydantic sample parse (critical).

Verdict: any critical failure → FAIL; else any warning/failure → QUARANTINE;
else PASS. Raw data is never repaired; corrections become new derived artifacts.
An 8-case adversarial corruption suite (`test_qa_corruption`: stripped ts,
duplicate identity, negative delta, deleted sched stream, exit-before-create,
post-hoc config change via replay hash, far-future ts, duplicate observations)
must never PASS.

Overhead (target ≤2% CPU, a measured engineering target, not a guarantee):
measure externally, e.g. run workload with/without collectors and compare
`/usr/bin/time -v` or `pidstat -p <collector> 1`; record numbers in the
experiment summary. Also record ringbuf drops, python RSS, event rate.
