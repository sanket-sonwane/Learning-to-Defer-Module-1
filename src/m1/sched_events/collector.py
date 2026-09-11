"""libbpf CO-RE ring-buffer consumer for scheduler events.

Architecture (exactly one — see libbpf_loader.py, no BCC):

    sched_collect.bpf.o → libbpf → 5 tracepoints → ring buffer m1_rb
    → decode_record() → SchedulerEvent → raw JSONL

Wire format: see abi.md. Canonical struct: "<Q I I 9i 16s 16s", 84 bytes,
little-endian. Linux-only for live collection; decode_record() is pure Python
and testable on Windows.

Counters (never silent): received / decoded / dropped (ringbuf reserve fail
+ kernel-side m1_drops) / malformed (truncated) / unknown (ev discriminant
out of range).
"""
import struct
from pathlib import Path
from m1.platform_guard import require_linux
from m1.models.sched import SchedulerEvent

EV_NAMES = ("sched_switch", "sched_wakeup", "sched_wakeup_new",
            "sched_process_exec", "sched_process_exit")
REQUIRED_EVENTS = frozenset(EV_NAMES)

BPF_OBJ = Path(__file__).parent / "bpf" / "sched_collect.bpf.o"

# Canonical ABI (must match abi.md and sched_collect.bpf.c):
#   __u64 ts; __u32 cpu, ev; 9x __s32; char comm[16], next_comm[16]
ABI = struct.Struct("<Q I I 9i 16s 16s")
ABI_SIZE = ABI.size
assert ABI_SIZE == 84, f"ABI drift: {ABI_SIZE} != 84 (see abi.md)"


class MalformedEvent(ValueError):
    pass


class UnknownEvent(ValueError):
    def __init__(self, ev: int):
        super().__init__(f"unknown event discriminant: {ev}")
        self.ev = ev


def decode_record(buf: bytes, experiment_id: str = "") -> SchedulerEvent:
    """Decode one 84-byte ringbuf record. Raises MalformedEvent/UnknownEvent."""
    if len(buf) < ABI_SIZE:
        raise MalformedEvent(f"truncated record: {len(buf)} < {ABI_SIZE} bytes")
    (ts, cpu, ev, pid, tid, tgid, _ppid, prio, prev_pid, prev_state,
     next_pid, success, comm, next_comm) = ABI.unpack(buf[:ABI_SIZE])
    if not 0 <= ev < len(EV_NAMES):
        raise UnknownEvent(ev)
    etype = EV_NAMES[ev]
    if etype == "sched_switch":
        comm_s = next_comm.decode(errors="replace").rstrip("\x00")
        kw = dict(prev_pid=prev_pid, prev_state=prev_state,
                  next_pid=next_pid,
                  next_comm=next_comm.decode(errors="replace").rstrip("\x00"))
    else:
        comm_s = comm.decode(errors="replace").rstrip("\x00")
        kw = dict(prio=prio or None,
                  success=success if etype.startswith("sched_wakeup") else None)
    return SchedulerEvent(
        event_type=etype, timestamp_monotonic_ns=int(ts), cpu=int(cpu),  # type: ignore[arg-type]
        pid=int(pid), tid=int(tid), tgid=int(tgid) or None,
        comm=comm_s, experiment_id=experiment_id, **kw)


class SchedCollector:
    """Loads the compiled BPF object via libbpf and streams SchedulerEvents."""

    def __init__(self, experiment_id: str = ""):
        require_linux("Scheduler event collector")
        self.experiment_id = experiment_id
        self.received = 0
        self.decoded = 0
        self.dropped = 0
        self.malformed = 0
        self.unknown = 0
        self.errors = 0
        self._loader = None
        self._pending: list[SchedulerEvent] = []

    def start(self) -> None:
        require_linux("Scheduler event collector")
        from m1.sched_events.libbpf_loader import LibbpfLoader

        def _on_record(buf: bytes) -> None:
            self.received += 1
            try:
                self._pending.append(decode_record(buf, self.experiment_id))
                self.decoded += 1
            except MalformedEvent:
                self.malformed += 1
            except UnknownEvent:
                self.unknown += 1
            except Exception:
                self.errors += 1

        loader = LibbpfLoader(BPF_OBJ, _on_record)
        loader.open_and_load()
        if loader.failed:
            loader.close()
            raise RuntimeError(
                f"Failed to attach required tracepoints: {loader.failed}. "
                "eBPF backend cannot report full fidelity.")
        loader.open_ring_buffer("m1_rb")
        self._loader = loader

    def attached(self) -> list[str]:
        return list(self._loader.attached) if self._loader else []

    def poll(self, timeout_ms: int = 100) -> list[SchedulerEvent]:
        """Poll ring buffer once; returns decoded events (may be empty)."""
        if self._loader is None:
            raise RuntimeError("Collector not started (call start()).")
        self._loader.poll(timeout_ms)
        out, self._pending = self._pending, []
        kernel_drops = self._loader.read_drop_counter()
        if kernel_drops is not None and kernel_drops > self.dropped:
            self.dropped = kernel_drops
        return out

    def stop(self) -> None:
        if self._loader is not None:
            # Preserve attachment stats before closing.
            self._attached_snapshot = list(self._loader.attached)
            self._failed_snapshot = list(self._loader.failed)
            self._loader.close()
            self._loader = None

    def stats(self) -> dict:
        attached = (self._attached_snapshot if not self._loader
                    else self.attached())
        return {"received": self.received, "decoded": self.decoded,
                "dropped": self.dropped, "malformed": self.malformed,
                "unknown": self.unknown, "errors": self.errors,
                "backend": "ebpf", "fidelity": "high",
                "attached": attached}
