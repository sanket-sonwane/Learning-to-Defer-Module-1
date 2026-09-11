"""Blocker 9: task identity survives PID/TID reuse via starttime generation."""
from m1.sched_events.correlate import GenerationTracker
from m1.task_discovery.identity import is_same_task, make_task_id
from m1.models.task import TaskSnapshot


def _snap(pid, start):
    return TaskSnapshot(task_id=make_task_id(pid, start), pid=pid, tid=pid,
                        tgid=pid, state="R", starttime_ticks=start,
                        timestamp_monotonic_ns=1)


def test_pid_reuse_generation():
    assert make_task_id(123, 111) == "123:111"
    assert make_task_id(123, 222) == "123:222"
    assert make_task_id(123, 111) != make_task_id(123, 222)
    assert not is_same_task(_snap(123, 111), _snap(123, 222))
    assert is_same_task(_snap(123, 111), _snap(123, 111))


def test_event_correlation_across_reuse():
    g = GenerationTracker()
    g.observe(123, "123:A", 111, ts_ns=1_000)   # first generation
    assert g.resolve(123, 1_500) == "123:A"
    g.close(123, ts_ns=2_000)                    # exit
    assert g.resolve(123, 2_500) is None         # gap: unresolved, counted
    assert g.unresolved == 1
    g.observe(123, "123:B", 222, ts_ns=3_000)   # PID reused
    assert g.resolve(123, 3_500) == "123:B"
    # Old-generation lookup range still resolves to A, never B.
    assert g.resolve(123, 1_800) == "123:A"
