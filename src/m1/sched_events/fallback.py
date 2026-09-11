"""Tracefs fallback when eBPF is unavailable (lower fidelity, higher overhead).

Reads /sys/kernel/tracing/events/sched/<event>/trace_pipe and parses trace
lines into canonical SchedulerEvent records. Used only when BPF capabilities
are missing; the experiment metadata records transport="tracefs-fallback" so
downstream analysis knows the fidelity differs. Linux-only.
"""
import re
import threading
from pathlib import Path
from m1 import timebase
from m1.platform_guard import require_linux
from m1.sched_events.collector import SchedulerEvent

TRACE = Path("/sys/kernel/tracing")

# trace_pipe line format:
#   <comm>-<pid> [<cpu>] .... <timestamp>: <event_name>: <fields>
_TRACE_RE = re.compile(
    r"^(?P<comm>.+?)-(?P<pid>\d+)\s+\[(?P<cpu>\d+)\]\s+"
    r"[\w.]+\s+(?P<ts>[\d.]+):\s+(?P<event>\w+):\s+(?P<fields>.+)$")

# sched_switch fields:  prev_comm=X prev_pid=N ... ==> next_comm=Y next_pid=N ...
_SWITCH_RE = re.compile(
    r"prev_comm=(?P<prev_comm>.+?)\s+prev_pid=(?P<prev_pid>\d+)\s+"
    r"prev_prio=(?P<prev_prio>\d+)\s+prev_state=(?P<prev_state>\S+)"
    r"\s+==>\s+next_comm=(?P<next_comm>.+?)\s+next_pid=(?P<next_pid>\d+)\s+"
    r"next_prio=(?P<next_prio>\d+)")

# sched_wakeup fields:  comm=X pid=N prio=N target_cpu=N
_WAKEUP_RE = re.compile(
    r"comm=(?P<comm>.+?)\s+pid=(?P<pid>\d+)\s+"
    r"prio=(?P<prio>\d+).*?target_cpu=(?P<target_cpu>\d+)")

_EVENT_MAP = {
    "sched_switch": "sched_switch",
    "sched_wakeup": "sched_wakeup",
    "sched_wakeup_new": "sched_wakeup_new",
    "sched_process_exec": "sched_process_exec",
    "sched_process_exit": "sched_process_exit",
}


class TracefsFallback:
    def __init__(self, experiment_id: str = "", events: tuple[str, ...] = (
            "sched_switch", "sched_wakeup", "sched_wakeup_new",
            "sched_process_exec", "sched_process_exit")):
        require_linux("Tracefs fallback collector")
        self.experiment_id = experiment_id
        self.events = events
        self.received = 0
        self.parsed = 0
        self.malformed = 0
        self.unknown = 0
        self.errors = 0
        self._pipe_fd = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._events_buf: list[SchedulerEvent] = []
        self._lock = threading.Lock()

    def available(self) -> bool:
        return (TRACE / "events" / "sched").exists()

    def start(self) -> None:
        require_linux("Tracefs fallback collector")
        if not self.available():
            raise RuntimeError("tracefs sched events directory not found")
        self.enable()
        # Open trace_pipe for reading (blocking reads in a background thread).
        pipe_path = TRACE / "trace_pipe"
        if not pipe_path.exists():
            raise RuntimeError(f"trace_pipe not found at {pipe_path}")
        self._pipe_fd = pipe_path.open("r", buffering=1)  # line-buffered
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        """Background thread: read trace_pipe lines and parse events."""
        while self._running:
            try:
                line = self._pipe_fd.readline()
            except Exception:
                self.errors += 1
                break
            if not line:
                break
            self.received += 1
            self._parse_line(line.strip())

    def _parse_line(self, line: str) -> None:
        m = _TRACE_RE.match(line)
        if not m:
            self.malformed += 1
            return
        event_raw = m.group("event")
        event_type = _EVENT_MAP.get(event_raw)
        if not event_type:
            self.unknown += 1
            return
        try:
            ts_ns = int(float(m.group("ts")) * 1e9)
            cpu = int(m.group("cpu"), 10)  # handles zero-padded like "001"
            fields = m.group("fields")
            ev = self._build_event(event_type, ts_ns, cpu, fields, m)
            if ev:
                with self._lock:
                    self._events_buf.append(ev)
                self.parsed += 1
            else:
                self.malformed += 1
        except Exception:
            self.malformed += 1

    def _build_event(self, event_type: str, ts_ns: int, cpu: int,
                     fields: str, m: re.Match) -> SchedulerEvent | None:
        try:
            if event_type == "sched_switch":
                sm = _SWITCH_RE.search(fields)
                if not sm:
                    return None
                next_pid = int(sm.group("next_pid"))
                # prev_state in trace_pipe is a char (S/R/D/etc); convert to int.
                state_char = sm.group("prev_state")
                state_map = {"S": 1, "R": 0, "D": 2, "T": 4, "Z": 8, "X": 16,
                             "x": 32, "K": 64, "W": 128, "P": 256}
                prev_state = state_map.get(state_char, 0)
                return SchedulerEvent(
                    event_type=event_type, timestamp_monotonic_ns=ts_ns,
                    cpu=cpu, pid=next_pid, tid=next_pid, tgid=next_pid,
                    comm=sm.group("next_comm"), task_id="",
                    experiment_id=self.experiment_id,
                    prev_pid=int(sm.group("prev_pid")),
                    prev_state=prev_state,
                    next_pid=next_pid,
                    prev_comm=sm.group("prev_comm"),
                    next_comm=sm.group("next_comm"),
                    prio=int(sm.group("next_prio")),
                )
            elif event_type in ("sched_wakeup", "sched_wakeup_new"):
                wm = _WAKEUP_RE.search(fields)
                if not wm:
                    return None
                pid = int(wm.group("pid"))
                return SchedulerEvent(
                    event_type=event_type, timestamp_monotonic_ns=ts_ns,
                    cpu=cpu, pid=pid, tid=pid, tgid=pid,
                    comm=wm.group("comm"), task_id="",
                    experiment_id=self.experiment_id,
                    prio=int(wm.group("prio")),
                )
            else:
                # sched_process_exec / sched_process_exit: minimal info
                pid = int(m.group("pid"))
                return SchedulerEvent(
                    event_type=event_type, timestamp_monotonic_ns=ts_ns,
                    cpu=cpu, pid=pid, tid=pid, tgid=pid,
                    comm=m.group("comm"), task_id="",
                    experiment_id=self.experiment_id,
                )
        except Exception:
            return None

    def poll(self, timeout_ms: int = 100) -> list[SchedulerEvent]:
        """Return buffered events parsed since last poll."""
        with self._lock:
            events = list(self._events_buf)
            self._events_buf.clear()
        return events

    def stop(self) -> None:
        self._running = False
        self.disable()
        if self._pipe_fd and not self._pipe_fd.closed:
            self._pipe_fd.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def enable(self) -> None:
        require_linux("Tracefs fallback collector")
        for ev in self.events:
            en = TRACE / "events" / "sched" / ev / "enable"
            try:
                en.write_text("1")
            except OSError:
                self.errors += 1

    def disable(self) -> None:
        for ev in self.events:
            en = TRACE / "events" / "sched" / ev / "enable"
            try:
                en.write_text("0")
            except OSError:
                pass

    def stats(self) -> dict:
        return {
            "backend": "tracefs_fallback",
            "fidelity": "reduced",
            "received": self.received,
            "parsed": self.parsed,
            "malformed": self.malformed,
            "unknown": self.unknown,
            "dropped": None,
            "errors": self.errors,
            "transport": "tracefs-fallback",
            "attached": list(self.events),
        }
