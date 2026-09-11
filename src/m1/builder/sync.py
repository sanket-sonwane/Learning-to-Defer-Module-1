"""Observation Builder: synchronized decision-time records.

Temporal model (canonical: CLOCK_MONOTONIC nanoseconds; wall-clock is
metadata-only and NEVER used for alignment):

- Observation timestamp T advances in fixed `sample_ms` steps from the first
  to the last task sample.
- Observation window is [T - W, T] with W = `observation_window_ms`.
- Task snapshot: latest sample with ts <= T (previous-sample policy).
- System/PSI snapshots: latest sample with ts <= T (previous-sample policy).
- Scheduler events: all events for the task with ts in [T - W, T],
  aggregated as counts + last wakeup/switch-in/switch-out timestamps.
- Context: controlled interval containing T; observations without an active
  context are skipped and counted (never forced).
- Derived deltas use delta_or_none(): missing on either side → None;
  negative (wrap/reset/reuse) → None + anomaly count. Missing is NEVER 0.

Separates EVENT frequency (kernel, high) from OBSERVATION frequency
(configurable sampling, default 100ms over a 500ms window).
"""
import bisect
from m1.models.observation import ObservationRecord
from m1.telemetry.features import cpu_util_pct, cs_rate_per_s, delta_or_none, io_rate_bps


def _latest_at(sorted_rows: list[dict], ts: int, key: str = "timestamp_monotonic_ns",
               _cache: dict | None = None) -> dict | None:
    """Find latest row with ts <= given timestamp using bisect on sorted rows."""
    if not sorted_rows:
        return None
    row_id = id(sorted_rows)
    if _cache is None or row_id not in _cache:
        keys = [r.get(key, 0) for r in sorted_rows]
        if _cache is None:
            _cache = {}
        _cache[row_id] = keys
    keys = _cache[row_id]
    idx = bisect.bisect_right(keys, ts) - 1
    return sorted_rows[idx] if idx >= 0 else None


def _workload_for_pid(pid: int | None, tgid: int | None, ts: int,
                      workloads: list[dict]) -> dict | None:
    """Workload membership is NOT pid-only.

    A snapshot belongs to a workload when its pid OR tgid equals the launched
    workload's pid (threads share tgid with the workload process). Membership
    is additionally time-bounded to the workload's nominal lifetime when the
    launch record carries a duration; a later process that reuses a workload's
    pid must never inherit its label. Records without a duration (legacy)
    are left unbounded.
    """
    if pid is None and tgid is None:
        return None
    for w in workloads:
        wpid = w.get("pid")
        if pid != wpid and tgid != wpid:
            continue
        start = w.get("start_monotonic_ns")
        if start is not None and ts < start:
            continue
        end = w.get("end_monotonic_ns")
        if end is None:
            dur = w.get("duration_s")
            if dur is not None:
                end = start + int(float(dur) * 1e9) if start is not None else None
        if end is None or ts <= end:
            return w
    return None


def build_observations(task_rows: list[dict], sched_rows: list[dict],
                       sys_rows: list[dict], psi_rows: list[dict],
                       ctx_events: list[dict], experiment_id: str,
                       scenario_id: str, window_ms: int = 500,
                       sample_ms: int = 100, num_cpus: int = 1,
                       clk_tck: int = 100,
                       workloads: list[dict] | None = None,
                       gen_tracker=None) -> tuple[list[dict], dict]:
    workloads = workloads or []
    anomalies: dict = {"negative_deltas": 0}
    stats = {"ticks": 0, "observations": 0, "skipped_no_task": 0,
             "skipped_no_system": 0, "skipped_no_context": 0,
             "unresolved_sched_events": 0, "sched_events_total": len(sched_rows),
             "sched_events_idle": sum(1 for e in sched_rows
                                      if (e.get("pid") or 0) == 0),
             "unresolved_non_idle": 0}
    if not task_rows:
        return [], stats
    t0 = min(r["timestamp_monotonic_ns"] for r in task_rows)
    t1 = max(r["timestamp_monotonic_ns"] for r in task_rows)
    window_ns = window_ms * 1_000_000
    step_ns = sample_ms * 1_000_000
    # index tasks by task_id
    by_task: dict[str, list[dict]] = {}
    for r in task_rows:
        by_task.setdefault(r["task_id"], []).append(r)
    for v in by_task.values():
        v.sort(key=lambda r: r["timestamp_monotonic_ns"])

    # context intervals (dicts with start_monotonic_ns / end_monotonic_ns / label ...)
    def resolve_ctx(ts: int) -> dict | None:
        for ev in ctx_events:
            end = ev.get("end_monotonic_ns") or ts
            if ev.get("start_monotonic_ns", 0) <= ts <= end:
                return ev
        return None

    out: list[dict] = []
    _cache: dict = {}
    # Pre-resolve scheduler event task_ids via GenerationTracker.
    # Events from eBPF arrive with task_id=""; use tracker to resolve
    # generation-safe identity. Unresolved events are counted, never attributed.
    if gen_tracker is not None:
        for e in sched_rows:
            if not e.get("task_id"):
                ts = e.get("timestamp_monotonic_ns", 0)
                resolved = gen_tracker.resolve(e.get("pid", 0), ts)
                if resolved:
                    e["task_id"] = resolved
                else:
                    stats["unresolved_sched_events"] += 1
                    if (e.get("pid") or 0) != 0:
                        stats["unresolved_non_idle"] += 1
    # Index scheduler events per task_id (primary) and per tid (legacy
    # fallback only for events without a task_id). Each entry is
    # task_key -> (sorted_timestamps, events) so in-window lookups are
    # bisect slices, never full scans.
    def _index_events(events, key_fn):
        groups: dict = {}
        for e in events:
            groups.setdefault(key_fn(e), []).append(e)
        for gkey, v in groups.items():
            v.sort(key=lambda x: x["timestamp_monotonic_ns"])
            yield gkey, (list(sorted(x["timestamp_monotonic_ns"] for x in v)), v)

    sched_by_task: dict[str, tuple] = \
        dict(_index_events([e for e in sched_rows if e.get("task_id")],
                           key_fn=lambda e: e["task_id"]))
    sched_by_tid: dict[int, tuple] = \
        dict(_index_events([e for e in sched_rows
                            if not e.get("task_id") and e.get("tid") is not None],
                           key_fn=lambda e: int(e["tid"])))
    tick = t0
    while tick <= t1:
        stats["ticks"] += 1
        sys_s = _latest_at(sys_rows, tick, _cache=_cache) if sys_rows else None
        psi_s = _latest_at(psi_rows, tick, _cache=_cache) if psi_rows else None
        ctx = resolve_ctx(tick)
        for task_id, rows in by_task.items():
            snap = _latest_at(rows, tick, _cache=_cache)
            if snap is None:
                stats["skipped_no_task"] += 1
                continue
            if sys_s is None:
                stats["skipped_no_system"] += 1
                continue
            if ctx is None:
                stats["skipped_no_context"] += 1
                continue
            # scheduler events for this task in window, via bisect slices.
            win: list[dict] = []
            g = sched_by_task.get(task_id)
            if g:
                keys, evs = g
                lo = bisect.bisect_left(keys, tick - window_ns)
                hi = bisect.bisect_right(keys, tick)
                if lo < hi:
                    win = evs[lo:hi]
            fallback = sched_by_tid.get(snap.get("tid"))
            if fallback:
                fkeys, fevs = fallback
                flo = bisect.bisect_left(fkeys, tick - window_ns)
                fhi = bisect.bisect_right(fkeys, tick)
                if flo < fhi:
                    win = win + fevs[flo:fhi]
            wakeups = [e for e in win if e.get("event_type") == "sched_wakeup"]
            sw_in = [e for e in win if e.get("event_type") == "sched_switch"
                     and e.get("next_pid") == snap.get("pid")]
            sw_out = [e for e in win if e.get("event_type") == "sched_switch"
                      and e.get("prev_pid") == snap.get("pid")]
            # derived cpu over window: first vs last sample of this task in window
            in_win = [r for r in rows if tick - window_ns <= r["timestamp_monotonic_ns"] <= tick]
            cpu_util = recent_ticks = None
            hist = None
            if len(in_win) >= 2:
                a, b = in_win[0], in_win[-1]
                dt = (b["timestamp_monotonic_ns"] - a["timestamp_monotonic_ns"]) / 1e9
                du = delta_or_none(b.get("utime_ticks"), a.get("utime_ticks"), anomalies)
                ds = delta_or_none(b.get("stime_ticks"), a.get("stime_ticks"), anomalies)
                cpu_util = cpu_util_pct(du, ds, dt, num_cpus, clk_tck)
                recent_ticks = (du + ds) if (du is not None and ds is not None) else None
                # Compute cpu_history from consecutive in-window samples.
                # First sample has no predecessor -> None.
                hist = [None]
                for prev, cur in zip(in_win, in_win[1:]):
                    dt_i = (cur["timestamp_monotonic_ns"] - prev["timestamp_monotonic_ns"]) / 1e9
                    du_i = delta_or_none(cur.get("utime_ticks"), prev.get("utime_ticks"), anomalies)
                    ds_i = delta_or_none(cur.get("stime_ticks"), prev.get("stime_ticks"), anomalies)
                    hist.append(cpu_util_pct(du_i, ds_i, dt_i, num_cpus, clk_tck))
            psi_some = (psi_s.get("cpu_some") or {}) if psi_s else {}
            mem_some = (psi_s.get("mem_some") or {}) if psi_s else {}
            io_some = (psi_s.get("io_some") or {}) if psi_s else {}
            # Native runtime counters: present only when BOTH components known.
            ut, st = snap.get("utime_ticks"), snap.get("stime_ticks")
            # Derived rates from native counters over the window.
            cs_val = io_r_val = io_w_val = None
            if len(in_win) >= 2:
                w_a, w_b = in_win[0], in_win[-1]
                w_dt = (w_b["timestamp_monotonic_ns"] - w_a["timestamp_monotonic_ns"]) / 1e9
                if w_dt > 0:
                    d_cs = delta_or_none(
                        (w_b.get("voluntary_ctxt_switches") or 0) + (w_b.get("nonvoluntary_ctxt_switches") or 0),
                        (w_a.get("voluntary_ctxt_switches") or 0) + (w_a.get("nonvoluntary_ctxt_switches") or 0),
                        anomalies)
                    cs_val = cs_rate_per_s(d_cs, w_dt)
                    d_rb = delta_or_none(w_b.get("read_bytes"), w_a.get("read_bytes"), anomalies)
                    d_wb = delta_or_none(w_b.get("write_bytes"), w_a.get("write_bytes"), anomalies)
                    io_r_val = io_rate_bps(d_rb, w_dt)
                    io_w_val = io_rate_bps(d_wb, w_dt)
            wl = _workload_for_pid(snap.get("pid"), snap.get("tgid"), tick,
                                   workloads)
            rec = ObservationRecord(
                observation_id=f"{experiment_id}:{tick}:{task_id}",
                experiment_id=experiment_id, timestamp_monotonic_ns=tick,
                timestamp_wall_ns=snap.get("timestamp_wall_ns"),
                task_id=task_id, pid=snap.get("pid", 0), tid=snap.get("tid", 0),
                tgid=snap.get("tgid"), cpu_id=snap.get("processor"),
                state=snap.get("state", ""), priority=snap.get("priority"),
                nice=snap.get("nice"),
                cpu_runtime_ticks=(ut + st) if (ut is not None and st is not None) else None,
                voluntary_cs=snap.get("voluntary_ctxt_switches"),
                nonvoluntary_cs=snap.get("nonvoluntary_ctxt_switches"),
                read_bytes=snap.get("read_bytes"), write_bytes=snap.get("write_bytes"),
                io_scope=snap.get("io_scope", "process"),
                num_threads=snap.get("num_threads"), cpu_affinity=snap.get("cpu_affinity"),
                recent_cpu_runtime_ticks=recent_ticks, cpu_util_pct=cpu_util,
                cs_rate_per_s=cs_val,
                io_read_bps=io_r_val,
                io_write_bps=io_w_val,
                cpu_history=hist,
                events_in_window=len(win),
                last_wakeup_ns=max((e["timestamp_monotonic_ns"] for e in wakeups), default=None),
                last_switch_in_ns=max((e["timestamp_monotonic_ns"] for e in sw_in), default=None),
                last_switch_out_ns=max((e["timestamp_monotonic_ns"] for e in sw_out), default=None),
                sys_cpu_util_pct=sys_s.get("total_cpu_util_pct"),
                runnable_tasks=sys_s.get("runnable_tasks"),
                cpu_psi_some_10=(psi_some.get("avg10") if isinstance(psi_some, dict) else getattr(psi_some, "avg10", None)),
                mem_psi_some_10=(mem_some.get("avg10") if isinstance(mem_some, dict) else getattr(mem_some, "avg10", None)),
                io_psi_some_10=(io_some.get("avg10") if isinstance(io_some, dict) else getattr(io_some, "avg10", None)),
                user_state=ctx.get("label", ""), foreground_app=ctx.get("foreground_app", ""),
                scenario_id=scenario_id,
                workload_id=(wl.get("workload_id") if wl else None),
                workload_type=(wl.get("type") if wl else None),
            )
            out.append(rec.model_dump())
            stats["observations"] += 1
        tick += step_ns
    stats["anomalies"] = anomalies
    if gen_tracker is not None:
        stats["unresolved_identities"] = gen_tracker.unresolved
    return out, stats
