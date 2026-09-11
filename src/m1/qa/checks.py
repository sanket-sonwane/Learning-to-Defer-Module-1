"""M1 QA checks: schema, identity, timestamps, scheduler events,
completeness, lifecycle, context alignment, performance.

Verdict: FAIL if any critical check fails; QUARANTINE if warnings;
PASS otherwise. Suspicious raw data is flagged, never repaired.
"""
from m1.models.observation import ObservationRecord
from m1.models.qa import QACheck, QAReport
from m1.models.sched import SchedulerEvent
from m1.models.task import TaskSnapshot

EXPECTED_EVENTS = {"sched_switch", "sched_wakeup", "sched_wakeup_new",
                   "sched_process_exec", "sched_process_exit"}


def check_schema_version(rows: list[dict], expected: str = "1.0.0") -> QACheck:
    bad = [r for r in rows if r.get("schema_version") != expected]
    return QACheck(name="schema_version",
                   passed=not bad,
                   severity="critical" if bad else "info",
                   detail=f"{len(bad)}/{len(rows)} rows with wrong schema_version")


def check_task_identity(task_rows: list[dict]) -> QACheck:
    """PID reuse: same pid with different starttime must give different task_id."""
    seen: dict[int, set] = {}
    collisions = 0
    for r in task_rows:
        pid = r.get("pid")
        tid = r.get("task_id", "")
        seen.setdefault(pid, set()).add(tid)
    multi = {p: ids for p, ids in seen.items() if len(ids) > 1}
    # Merging different generations into one id would be a collision:
    id_to_gens: dict[str, set] = {}
    for r in task_rows:
        id_to_gens.setdefault(r.get("task_id", ""), set()).add(r.get("starttime_ticks"))
    collisions = sum(1 for gens in id_to_gens.values() if len(gens) > 1)
    ok = collisions == 0
    return QACheck(name="task_identity", passed=ok,
                   severity="critical" if not ok else "info",
                   detail=(f"{len(multi)} pids with multiple generations (expected w/ reuse); "
                           f"{collisions} task_id collisions"))


def check_timestamps(task_rows: list[dict], obs: list[dict]) -> QACheck:
    """Timestamp monotonicity within each task generation (not globally).

    Rows are interleaved across PIDs; checking global order produces false
    retrograde detections.  We group by task_id and verify monotonicity
    within each group.  Additionally, all timestamps must be positive and
    present.
    """
    retrograde = missing = nonpositive = 0
    # Group task_rows by task_id for generation-scoped monotonicity.
    by_task: dict[str, list[int]] = {}
    for r in task_rows:
        tid = r.get("task_id", "")
        ts = r.get("timestamp_monotonic_ns")
        if ts is None:
            missing += 1
            continue
        if ts <= 0:
            nonpositive += 1
            continue
        by_task.setdefault(tid, []).append(ts)
    for ts_list in by_task.values():
        for a, b in zip(ts_list, ts_list[1:]):
            if b < a - 1_000_000_000:  # 1s tolerance for clock jitter
                retrograde += 1
    # Observations: check for negative durations and missing timestamps.
    neg = 0
    for o in obs:
        ts = o.get("timestamp_monotonic_ns")
        if ts is None:
            missing += 1
        elif ts <= 0:
            nonpositive += 1
        if (o.get("recent_cpu_runtime_ticks") or 0) < 0:
            neg += 1
    bad = retrograde + missing + nonpositive
    return QACheck(name="timestamps", passed=(bad == 0 and neg == 0),
                   severity="critical" if (bad or neg) else "info",
                   detail=f"retrograde={retrograde} missing={missing} "
                          f"nonpositive={nonpositive} negative_durations={neg}")


def check_sched_events(sched_rows: list[dict], sched_stats: dict,
                       unresolved_identities: int = 0,
                       attribution: dict | None = None) -> QACheck:
    types = {r.get("event_type") for r in sched_rows}
    malformed = [r for r in sched_rows if r.get("event_type") not in EXPECTED_EVENTS]
    missing_ref = [r for r in sched_rows if r.get("tid") is None and r.get("pid") is None]
    dropped = int(sched_stats.get("dropped") or 0)
    detail = (f"types={sorted(types)} malformed={len(malformed)} "
              f"missing_ref={len(missing_ref)} dropped={dropped} "
              f"unresolved_identities={unresolved_identities}")
    # Drops are recorded, not hidden; missing ALL events is critical.
    if not sched_rows:
        return QACheck(name="sched_events", passed=False, severity="critical",
                       detail="no scheduler events collected; " + detail)
    if malformed or missing_ref:
        return QACheck(name="sched_events", passed=False, severity="critical", detail=detail)
    # Attribution gate: unresolved non-idle events above a hard threshold are a
    # critical data-quality failure (production verdicts must not pass with
    # broken sched-event attribution). Idle/swapper (pid 0) events are excluded
    # — they are never present in /proc and can never resolve by design.
    un_idle = None
    if attribution:
        total = int(attribution.get("sched_events_total") or 0)
        idle = int(attribution.get("sched_events_idle") or 0)
        un_non_idle = int(attribution.get("unresolved_non_idle") or 0)
        base = max(0, total - idle)
        if base > 0:
            un_idle = un_non_idle / base
            detail += (f" unresolved_non_idle={un_non_idle}/{base} "
                       f"({un_idle:.1%})")
            if un_idle > SCHED_UNRESOLVED_MAX_RATIO:
                return QACheck(name="sched_events", passed=False, severity="critical",
                               detail=detail)
    if un_idle is not None and un_idle > 0:
        # non-zero but under the hard threshold: keep it loud, not blocking.
        return QACheck(name="sched_events", passed=True, severity="warning",
                       detail=detail)
    sev = "warning" if (dropped > 0 or unresolved_identities > 0) else "info"
    return QACheck(name="sched_events", passed=True, severity=sev,
                   blocking=(dropped > 0), detail=detail)


def check_completeness(task_rows: list[dict], sys_rows: list[dict],
                       ctx_events: list[dict], obs: list[dict]) -> QACheck:
    problems = []
    if not task_rows:
        problems.append("no task snapshots")
    if not sys_rows:
        problems.append("no system snapshots")
    if not ctx_events:
        problems.append("no context events")
    if not obs:
        problems.append("no observations")
    null_cpu = sum(1 for o in obs if o.get("cpu_util_pct") is None)
    null_hist = sum(1 for o in obs if o.get("cpu_history") is None
                    or all(v is None for v in o["cpu_history"]))
    total = len(obs)
    cpu_coverage = ((total - null_cpu) / total * 100) if total else 0
    hist_coverage = ((total - null_hist) / total * 100) if total else 0
    # All-null cpu_history is a critical completeness failure unless the dataset
    # is genuinely too short for any history.
    hist_all_null = (null_hist == total and total > 1)
    severity = "critical" if hist_all_null else ("info" if not problems else "critical")
    detail = (f"obs={total} null_cpu_util={null_cpu} ({cpu_coverage:.1f}% coverage) "
              f"null_cpu_history={null_hist} ({hist_coverage:.1f}% coverage)")
    if problems:
        detail = "; ".join(problems) + "; " + detail
    return QACheck(name="completeness", passed=not problems and not hist_all_null,
                   severity=severity, detail=detail)


def check_lifecycle(task_rows: list[dict], sched_rows: list[dict]) -> QACheck:
    """Exit-before-create and orphan exits.

    Every sched_process_exit pid should have been seen in task snapshots;
    an exit timestamped before the pid's first task sample is an impossible
    lifecycle transition (critical).
    """
    seen_pids = {r.get("pid") for r in task_rows} | {r.get("tid") for r in task_rows}
    first_seen: dict[int, int] = {}
    for r in task_rows:
        for key in ("pid", "tid"):
            pid = r.get(key)
            ts = r.get("timestamp_monotonic_ns", 0)
            if pid is not None and (pid not in first_seen or ts < first_seen[pid]):
                first_seen[pid] = ts
    exits = [e for e in sched_rows if e.get("event_type") == "sched_process_exit"]
    orphan = [e for e in exits if e.get("pid") not in seen_pids]
    inverted = [e for e in exits
                if e.get("pid") in first_seen
                and e.get("timestamp_monotonic_ns", 0) < first_seen[e["pid"]]]
    if inverted:
        return QACheck(name="lifecycle", passed=False, severity="critical",
                       detail=f"exits={len(exits)} exit_before_create={len(inverted)}")
    return QACheck(name="lifecycle", passed=True,
                   severity="warning" if orphan else "info",
                   detail=f"exits={len(exits)} orphan_exits={len(orphan)}")


def check_observation_uniqueness(obs: list[dict]) -> QACheck:
    """Duplicate (timestamp, task_id) combinations indicate double-counting."""
    seen: set[tuple] = set()
    dupes = 0
    for o in obs:
        key = (o.get("timestamp_monotonic_ns"), o.get("task_id"))
        if key in seen:
            dupes += 1
        seen.add(key)
    return QACheck(name="observation_uniqueness", passed=dupes == 0,
                   severity="critical" if dupes else "info",
                   detail=f"obs={len(obs)} duplicates={dupes}")


def check_impossible_timestamps(task_rows: list[dict], sched_rows: list[dict],
                                obs: list[dict],
                                mode: str = "live") -> QACheck:
    """Missing, non-positive, or far-future monotonic timestamps.

    mode='live': compares against current CLOCK_MONOTONIC with 1h tolerance.
    mode='replay': derives bounds from the data itself (no wall-clock dependency).
    """
    import time as _time
    all_rows = task_rows + sched_rows + obs
    timestamps = [r.get("timestamp_monotonic_ns") for r in all_rows
                  if r.get("timestamp_monotonic_ns") is not None]
    if mode == "replay" and timestamps:
        data_max = max(timestamps)
        horizon = data_max + 3_600_000_000_000  # 1h beyond data max
    else:
        try:
            now = _time.clock_gettime_ns(_time.CLOCK_MONOTONIC)
        except AttributeError:
            now = _time.monotonic_ns()
        horizon = now + 3_600_000_000_000  # 1h tolerance for clock skew
    missing = nonpositive = future = 0
    for rows in (task_rows, sched_rows, obs):
        for r in rows:
            ts = r.get("timestamp_monotonic_ns")
            if ts is None:
                missing += 1
            elif ts <= 0:
                nonpositive += 1
            elif ts > horizon:
                future += 1
    bad = missing + nonpositive + future
    return QACheck(name="impossible_timestamps", passed=bad == 0,
                   severity="critical" if bad else "info",
                   detail=f"missing={missing} nonpositive={nonpositive} far_future={future} mode={mode}")


def check_context(ctx_events: list[dict]) -> QACheck:
    bad_order = 0
    overlap = 0
    for i, ev in enumerate(ctx_events):
        s, e = ev.get("start_monotonic_ns", 0), ev.get("end_monotonic_ns")
        if e is not None and e < s:
            bad_order += 1
        for other in ctx_events[i + 1:]:
            s2, e2 = other.get("start_monotonic_ns", 0), other.get("end_monotonic_ns")
            e = e if e is not None else s
            e2 = e2 if e2 is not None else s2
            if s < e2 and s2 < e:
                overlap += 1
    ok = bad_order == 0 and overlap == 0
    return QACheck(name="context", passed=ok,
                   severity="critical" if not ok else "info",
                   detail=f"bad_order={bad_order} overlaps={overlap} events={len(ctx_events)}")


def check_performance(sched_stats: dict) -> QACheck:
    dropped = int(sched_stats.get("dropped") or 0)
    errors = int(sched_stats.get("errors") or 0)
    return QACheck(name="performance", passed=True,
                   severity="warning" if (dropped or errors) else "info",
                   blocking=(dropped or errors) > 0,
                   detail=(f"dropped={dropped} errors={errors}; "
                           "overhead target <=2% must be measured externally (see docs/qa_protocol.md)"))


def check_failed_collectors(failed: list[str]) -> QACheck:
    return QACheck(name="collectors_alive", passed=not failed,
                   severity="critical" if failed else "info",
                   detail="all collectors ok" if not failed else f"failed: {failed}")


def check_workload_events(workload_events: list[dict]) -> QACheck:
    """Validate the distinct workload_events raw stream (schema + ordering).

    workload_events is a raw data stream like any other; a malformed launch
    record must be caught here, never trusted for attribution downstream.
    """
    bad_fields = bad_order = dup_ids = 0
    seen: set = set()
    for w in workload_events:
        wid = w.get("workload_id")
        if wid is None or not w.get("type") or w.get("pid") is None \
                or w.get("start_monotonic_ns") is None:
            bad_fields += 1
        else:
            start = w["start_monotonic_ns"]
            end = w.get("end_monotonic_ns")
            if end is not None and end < start:
                bad_order += 1
            if wid in seen:
                dup_ids += 1
            seen.add(wid)
    bad = bad_fields + bad_order + dup_ids
    detail = (f"{len(workload_events)} workload records; "
              f"bad_fields={bad_fields} bad_order={bad_order} dup_ids={dup_ids}")
    return QACheck(name="workload_events", passed=not bad,
                   severity="critical" if bad else "info", detail=detail)


# Documented cadence thresholds (fix doc #17: thresholds must be explicit).
# A "missed deadline" is an interval > 1.5x the requested period.
#   max_missed_ratio:        default 0.30 (QA warning above 30% of ticks late)
#   min_achieved_freq_ratio: default 0.50 (QA warning if effective frequency
#                                           drops below half the requested rate)
CADENCE_MAX_MISSED_RATIO = 0.30
CADENCE_MIN_FREQ_RATIO = 0.50
# Hard attribution gate: if more than this fraction of non-idle scheduler
# events is unattributable, sched-event data cannot be certified.  On a
# typical Linux VM under CPU-intense workloads the structural unresolved
# baseline (short-lived threads, kernel threads, first-scan lag) is ~15-20%;
# this constant is calibrated to that floor plus a margin.
SCHED_UNRESOLVED_MAX_RATIO = 0.25


def check_sampling_cadence(cadence: dict | None) -> QACheck:
    """Gate: a sustained cadence collapse must never silently pass.

    Absence of cadence data (cadence=None or samples=0) in a long run is an
    anomaly worth a warning — we cannot certify timing we did not record.
    """
    if not cadence:
        return QACheck(name="sampling_cadence", passed=True, blocking=True,
                       severity="warning",
                       detail="no cadence data recorded")
    n = int(cadence.get("samples") or 0)
    if n == 0:
        return QACheck(name="sampling_cadence", passed=True, blocking=True,
                       severity="warning",
                       detail="cadence recorded but no intervals measured")
    missed_ratio = float(cadence.get("missed_deadline_ratio") or 0.0)
    eff_hz = cadence.get("effective_freq_hz")
    requested_ms = float(cadence.get("requested_ms") or 0.0)
    freqs = []
    if requested_ms > 0 and eff_hz is not None:
        freqs.append(1000.0 / requested_ms)
    details = (f"n={n} mean={cadence.get('mean_ms')}ms p95={cadence.get('p95_ms')}ms "
               f"missed={cadence.get('missed_deadlines')} "
               f"missed_ratio={missed_ratio} eff_freq={eff_hz}Hz")
    problems = []
    if missed_ratio > CADENCE_MAX_MISSED_RATIO:
        problems.append("missed deadline ratio exceeds 0.30")
    if freqs and eff_hz and eff_hz < freqs[0] * CADENCE_MIN_FREQ_RATIO:
        problems.append(f"effective frequency {eff_hz}Hz below half of requested "
                        f"{freqs[0]:.1f}Hz")
    if problems:
        return QACheck(name="sampling_cadence", passed=False, severity="warning",
                       detail=f"{details}; {'; '.join(problems)}")
    return QACheck(name="sampling_cadence", passed=True, severity="info",
                   detail=details)


def check_backend(backend: str, sched_rows: list[dict]) -> QACheck:
    """Authoritative scheduler analysis requires the eBPF backend.

    tracefs_fallback/none runs are usable for pipeline testing but must never
    PASS as authoritative scheduler observations.
    """
    if backend == "ebpf":
        return QACheck(name="backend_fidelity", passed=True, severity="info",
                       detail="ebpf/high fidelity")
    if backend == "tracefs_fallback":
        return QACheck(name="backend_fidelity", passed=False, severity="warning",
                       detail="tracefs_fallback/reduced fidelity: non-authoritative scheduler data")
    return QACheck(name="backend_fidelity", passed=False, severity="critical",
                   detail=f"no scheduler backend ({backend}): {len(sched_rows)} events")


def run_all(experiment_id: str, task_rows: list[dict], sched_rows: list[dict],
            sys_rows: list[dict], psi_rows: list[dict], ctx_events: list[dict],
            obs: list[dict], sched_stats: dict | None = None,
            failed_collectors: list[str] | None = None,
            backend: str = "ebpf",
            mode: str = "live",
            unresolved_identities: int = 0,
            sched_attribution: dict | None = None,
            sampling_cadence: dict | None = None,
            workload_events: list[dict] | None = None) -> QAReport:
    sched_stats = sched_stats or {}
    checks = [
        check_failed_collectors(failed_collectors or []),
        check_backend(backend, sched_rows),
        check_schema_version(task_rows + obs),
        check_task_identity(task_rows),
        check_timestamps(task_rows, obs),
        check_sched_events(sched_rows, sched_stats,
                           unresolved_identities=unresolved_identities,
                           attribution=sched_attribution),
        check_completeness(task_rows, sys_rows, ctx_events, obs),
        check_lifecycle(task_rows, sched_rows),
        check_observation_uniqueness(obs),
        check_impossible_timestamps(task_rows, sched_rows, obs, mode=mode),
        check_context(ctx_events),
        check_performance(sched_stats),
        check_sampling_cadence(sampling_cadence),
        check_workload_events(workload_events or []),
    ]
    # Validate pydantic parsing on ALL rows (schema/type/range gate).
    # Never cap at 200 — corruption past that threshold must be caught.
    parse_errors = 0
    for r in task_rows:
        try:
            TaskSnapshot(**{k: v for k, v in r.items() if k != "derived" and k != "simulated"})
        except Exception:
            parse_errors += 1
    for r in sched_rows:
        try:
            SchedulerEvent(**{k: v for k, v in r.items() if k != "simulated"})
        except Exception:
            parse_errors += 1
    from m1.models.system import SystemSnapshot
    from m1.models.psi import PSISnapshot
    from m1.models.context import ContextEvent
    for r in sys_rows:
        try:
            SystemSnapshot(**{k: v for k, v in r.items() if k != "simulated"})
        except Exception:
            parse_errors += 1
    for r in psi_rows:
        try:
            PSISnapshot(**{k: v for k, v in r.items() if k != "simulated"})
        except Exception:
            parse_errors += 1
    for r in ctx_events:
        try:
            ContextEvent(**{k: v for k, v in r.items() if k != "simulated"})
        except Exception:
            parse_errors += 1
    for r in obs:
        try:
            ObservationRecord(**{k: v for k, v in r.items() if k != "simulated"})
        except Exception:
            parse_errors += 1
    checks.append(QACheck(name="pydantic_parse", passed=parse_errors == 0,
                          severity="critical" if parse_errors else "info",
                          detail=f"sample parse errors={parse_errors}"))
    if any(c.severity == "critical" and not c.passed for c in checks):
        verdict = "FAIL"
    elif any(not c.passed or c.blocking for c in checks):
        verdict = "QUARANTINE"
    else:
        verdict = "PASS"
    stats = {"tasks": len(task_rows), "sched_events": len(sched_rows),
             "sys": len(sys_rows), "psi": len(psi_rows),
             "ctx": len(ctx_events), "obs": len(obs)}
    return QAReport(experiment_id=experiment_id, verdict=verdict, checks=checks, stats=stats)  # type: ignore[arg-type]
