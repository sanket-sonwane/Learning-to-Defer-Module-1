"""Blocker 11: /proc/<pid>/io is process-level — labeled, never per-thread."""
from m1.models.observation import ObservationRecord
from m1.models.task import TaskSnapshot


def test_io_scope():
    s = TaskSnapshot(task_id="1:100", pid=1, tid=2, tgid=1, state="R",
                     read_bytes=4096, write_bytes=1024,
                     timestamp_monotonic_ns=1)
    assert s.io_scope == "process"
    # Same process counters on a sibling thread carry the same scope label.
    t = TaskSnapshot(task_id="1:100", pid=1, tid=3, tgid=1, state="R",
                     read_bytes=4096, write_bytes=1024,
                     timestamp_monotonic_ns=1)
    assert (t.read_bytes, t.write_bytes) == (s.read_bytes, s.write_bytes)
    assert t.io_scope == "process"
    # Observation schema propagates the scope instead of implying per-thread I/O.
    o = ObservationRecord(observation_id="o", task_id="1:100", pid=1, tid=2,
                          timestamp_monotonic_ns=1, read_bytes=4096)
    assert o.io_scope == "process"
