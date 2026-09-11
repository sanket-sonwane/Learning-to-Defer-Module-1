"""Adversarial: corruption detected beyond sample den/slice 500 (verification item 15)."""
import copy
from m1.qa.checks import run_all


def _large_dataset(n_rows=600):
    """Generate a large synthetically-valid dataset (500+ task rows)."""
    ts_base = 10**9
    tasks = []
    sched = []
    sys_rows = []
    psi_rows = []
    obs = []
    n_tasks = 10
    for i in range(n_rows):
        tid = (i % n_tasks) + 1
        ts = ts_base + i * 10_000_000
        tasks.append({
            "schema_version": "1.0.0", "task_id": f"{tid}:{tid}",
            "pid": tid, "tid": tid, "tgid": tid, "ppid": 1, "comm": "t",
            "state": "R", "priority": 20, "nice": 0, "num_threads": 1,
            "starttime_ticks": tid, "processor": 0, "cpu_affinity": [0],
            "utime_ticks": 1000 + i, "stime_ticks": 100,
            "voluntary_ctxt_switches": 0, "nonvoluntary_ctxt_switches": 0,
            "read_bytes": 0, "write_bytes": 0, "rss_pages": 512,
            "timestamp_monotonic_ns": ts, "timestamp_wall_ns": None,
            "experiment_id": "BIG", "simulated": True})
        sched.append({
            "schema_version": "1.0.0", "event_type": "sched_switch",
            "timestamp_monotonic_ns": ts - 5_000_000, "cpu": 0,
            "pid": tid, "tid": tid, "tgid": tid, "comm": "t",
            "experiment_id": "BIG", "simulated": True, "task_id": f"{tid}:{tid}",
            "prev_pid": 999, "next_pid": tid, "prev_state": 0, "next_comm": "t"})
        if i % 10 == 0:
            sys_rows.append({
                "schema_version": "1.0.0", "timestamp_monotonic_ns": ts,
                "experiment_id": "BIG", "total_cpu_util_pct": 40.0,
                "per_cpu_util_pct": [40.0], "simulated": True})
            psi_rows.append({
                "schema_version": "1.0.0", "timestamp_monotonic_ns": ts,
                "experiment_id": "BIG", "cpu_some": {"avg10": 1.0},
                "mem_some": {"avg10": 1.0}, "mem_full": {"avg10": 1.0},
                "io_some": {"avg10": 1.0}, "io_full": {"avg10": 1.0},
                "simulated": True})
        obs.append({
            "schema_version": "1.0.0",
            "observation_id": f"BIG:{ts}:{tid}:{tid}",
            "experiment_id": "BIG", "timestamp_monotonic_ns": ts,
            "task_id": f"{tid}:{tid}", "pid": tid, "tid": tid, "tgid": tid,
            "cpu_history": [1.0], "simulated": True})
    ctx = [{"label": "USER_ACTIVE", "foreground_app": "a", "scenario_id": "s",
            "start_monotonic_ns": ts_base - 10**9,
            "end_monotonic_ns": ts_base + 10**15}]
    return tasks, sched, sys_rows, psi_rows, ctx, obs


def test_corruption_detected_after_row_500():
    """Inject negative runtime after row 500; must FAIL, never PASS."""
    tasks, sched, sys_rows, psi_rows, ctx, obs = _large_dataset()
    report = run_all("BIG", tasks, sched, sys_rows, psi_rows, ctx, obs,
                     backend="tracefs_fallback")
    # baseline should be QUARANTINE (tracefs_fallback = warning), not FAIL
    assert report.verdict in ("PASS", "QUARANTINE"), "baseline should not FAIL"

    # Corrupt a row 600 rows in (index 550): negative runtime delta.
    corrupt = copy.deepcopy(obs)
    corrupt[550]["recent_cpu_runtime_ticks"] = -50
    report2 = run_all("BIG", tasks, sched, sys_rows, psi_rows, ctx, corrupt,
                      backend="tracefs_fallback")
    assert report2.verdict == "FAIL", "corruption after row 500 must FAIL"

    # Corrupt a task row after index 500: impossible future timestamp.
    corrupt2 = copy.deepcopy(tasks)
    corrupt2[530]["timestamp_monotonic_ns"] = 2**63 - 1
    report3 = run_all("BIG", corrupt2, sched, sys_rows, psi_rows, ctx, obs,
                      backend="tracefs_fallback")
    assert report3.verdict == "FAIL", "future timestamp after row 500 must FAIL"


def test_pydantic_parse_checks_beyond_200_rows():
    """pydantic_parse must not be limited to rows[:200] on large corruption."""
    tasks, sched, sys_rows, psi_rows, ctx, obs = _large_dataset(600)
    # Introduce a schema-violating row at index 350 in task_rows (still >200 sample cap).
    bad = copy.deepcopy(tasks)
    bad[350]["pid"] = "not-an-int"
    report = run_all("BIG", bad, sched, sys_rows, psi_rows, ctx, obs,
                     backend="tracefs_fallback")
    assert report.verdict == "FAIL", "schema violation after row 200 must FAIL"
    failure = [c for c in report.checks if c.name == "pydantic_parse"]
    assert failure and failure[0].passed is False