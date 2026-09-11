"""Unit: task identity and PID reuse."""
from m1.models.task import TaskSnapshot
from m1.task_discovery.identity import is_same_task, make_task_id


def _snap(pid, start, tid=None):
    return TaskSnapshot(task_id=make_task_id(pid, start), pid=pid, tid=tid or pid,
                        tgid=pid, state="R", starttime_ticks=start,
                        timestamp_monotonic_ns=1)


def test_pid_reuse_distinct_ids():
    old = _snap(1234, 999111)
    new = _snap(1234, 555222)
    assert old.task_id != new.task_id
    assert not is_same_task(old, new)


def test_same_task_equal():
    a = _snap(1234, 999111)
    b = _snap(1234, 999111)
    assert is_same_task(a, b)


def test_unknown_starttime_marked():
    assert make_task_id(42, None) == "42:unknown"
