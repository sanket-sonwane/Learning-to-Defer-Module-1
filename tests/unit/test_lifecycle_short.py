"""Short-lived task lifecycle: tasks between scans don't false-positive orphan (item 16)."""
from m1.qa.checks import check_lifecycle


def test_short_lived_task_not_orphan():
    """A task seen in one scan and gone in the next is NOT an orphan exit."""
    # Task exists in task_rows at a single timestamp (short-lived).
    tasks = [
        {"task_id": "50:999", "pid": 50, "tid": 50, "tgid": 50,
         "timestamp_monotonic_ns": 1_000_000_000, "simulated": True},
    ]
    # A sched_process_exit for pid=50 at a LATER time — NOT an orphan.
    sched = [
        {"event_type": "sched_process_exit", "timestamp_monotonic_ns": 1_500_000_000,
         "pid": 50, "tid": 50, "cpu": 0, "task_id": "50:999", "simulated": True},
    ]
    result = check_lifecycle(tasks, sched)
    assert result.passed is True, f"short-lived exit should PASS, got {result.detail}"


def test_exit_without_any_task_snapshot_is_orphan():
    """Exit event for PID never in task_rows → orphan (warning, not critical)."""
    tasks = [
        {"task_id": "10:100", "pid": 10, "tid": 10, "tgid": 10,
         "timestamp_monotonic_ns": 1_000_000_000, "simulated": True},
    ]
    sched = [
        {"event_type": "sched_process_exit", "timestamp_monotonic_ns": 2_000_000_000,
         "pid": 999, "tid": 999, "cpu": 0, "simulated": True},
    ]
    result = check_lifecycle(tasks, sched)
    # Orphan exit is severity=warning, not critical. passed=True but with warning.
    assert result.passed is True, "orphan exit should be warning, not FAIL"
    assert "orphan_exits=1" in result.detail


def test_exit_before_create_is_critical():
    """Exit timestamped BEFORE the task was first seen → FAIL."""
    tasks = [
        {"task_id": "20:200", "pid": 20, "tid": 20, "tgid": 20,
         "timestamp_monotonic_ns": 2_000_000_000, "simulated": True},
    ]
    sched = [
        {"event_type": "sched_process_exit", "timestamp_monotonic_ns": 1_000_000_000,
         "pid": 20, "tid": 20, "cpu": 0, "task_id": "20:200", "simulated": True},
    ]
    result = check_lifecycle(tasks, sched)
    assert result.passed is False, "exit-before-create must FAIL"
    assert result.severity == "critical"
