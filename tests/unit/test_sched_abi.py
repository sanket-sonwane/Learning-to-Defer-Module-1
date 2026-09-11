"""Blocker 1: BPF event ABI — canonical 84-byte record decode + malformed input."""
import struct
import pytest
from m1.sched_events.collector import (
    ABI, ABI_SIZE, EV_NAMES, MalformedEvent, UnknownEvent, decode_record)


def _pack(ts=1_000, cpu=2, ev=0, pid=111, tid=111, tgid=100, ppid=0, prio=20,
          prev_pid=110, prev_state=1, next_pid=111, success=1,
          comm=b"prev_task", nxt=b"next_task"):
    return struct.pack("<Q I I 9i 16s 16s", ts, cpu, ev, pid, tid, tgid, ppid,
                       prio, prev_pid, prev_state, next_pid, success,
                       comm.ljust(16, b"\x00")[:16], nxt.ljust(16, b"\x00")[:16])


def test_bpf_event_abi():
    assert ABI_SIZE == 84
    # sched_switch: keyed on next, comm=prev_comm, next_comm preserved.
    e = decode_record(_pack(ev=0), "EXP-T")
    assert e.event_type == "sched_switch"
    assert (e.timestamp_monotonic_ns, e.cpu, e.pid, e.tid) == (1_000, 2, 111, 111)
    assert e.prev_pid == 110 and e.prev_state == 1 and e.next_pid == 111
    assert e.comm == "next_task" and e.next_comm == "next_task"  # comm = subject
    # sched_wakeup: prio/success/comm from the woken task.
    w = decode_record(_pack(ev=1, comm=b"woken"), "EXP-T")
    assert w.event_type == "sched_wakeup" and w.prio == 20 and w.success == 1
    assert w.comm == "woken"
    # Remaining discriminants map in order.
    for ev_id, name in ((2, "sched_wakeup_new"), (3, "sched_process_exec"),
                        (4, "sched_process_exit")):
        assert decode_record(_pack(ev=ev_id), "EXP-T").event_type == name
    assert len(EV_NAMES) == 5
    # Trailing surplus bytes are tolerated (extension room).
    assert decode_record(_pack() + b"\x00" * 16).event_type == "sched_switch"


def test_bpf_event_truncated():
    for bad in (b"", b"\x00" * 10, _pack()[:83]):
        with pytest.raises(MalformedEvent):
            decode_record(bad)
    # Unknown discriminant is rejected, never mislabeled.
    with pytest.raises(UnknownEvent):
        decode_record(_pack(ev=9))
