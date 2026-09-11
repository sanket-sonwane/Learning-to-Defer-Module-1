"""Task registry: discovery, existence, exit, lifecycle continuity.

Linux-only collection; Windows raises LinuxOnlyError via platform_guard.
"""
from pathlib import Path
from m1 import timebase
from m1.platform_guard import require_linux
from m1.models.task import TaskSnapshot
from m1.task_discovery import proc_parser
from m1.task_discovery.identity import make_task_id

PROC = Path("/proc")


class TaskRegistry:
    """Tracks live tasks keyed by persistent task_id.

    Lifecycle: DISCOVERED -> ACTIVE -> (state changes) -> EXITED.
    PID reuse yields a different task_id, so old and new lifetimes never merge.
    """

    def __init__(self, experiment_id: str = ""):
        self.experiment_id = experiment_id
        self.live: dict[str, TaskSnapshot] = {}
        self.seen: dict[str, TaskSnapshot] = {}
        self.exited: set[str] = set()
        self.errors: int = 0

    # -- one-shot discovery -------------------------------------------------
    def scan(self) -> tuple[list[TaskSnapshot], list[str]]:
        """Scan /proc once. Returns (snapshots, exited_task_ids)."""
        require_linux("Task collector")
        now_mono = timebase.monotonic_ns()
        now_wall = timebase.wall_ns()
        snaps: list[TaskSnapshot] = []
        for entry in PROC.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            snap = self._read_task(pid, pid, now_mono, now_wall)
            if snap is None:
                continue
            snaps.append(snap)
            # thread-level discovery
            task_dir = PROC / str(pid) / "task"
            try:
                tids = [t.name for t in task_dir.iterdir() if t.name.isdigit()]
            except FileNotFoundError:
                continue
            for tname in tids:
                tid = int(tname)
                if tid == pid:
                    continue
                tsnap = self._read_task(pid, tid, now_mono, now_wall)
                if tsnap is not None:
                    snaps.append(tsnap)
        new_ids = {s.task_id for s in snaps}
        exited = [tid for tid in self.live if tid not in new_ids]
        for tid in exited:
            self.exited.add(tid)
            del self.live[tid]
        for s in snaps:
            self.live[s.task_id] = s
            self.seen[s.task_id] = s
        return snaps, exited

    def _read_task(self, pid: int, tid: int, now_mono: int, now_wall: int) -> TaskSnapshot | None:
        base = PROC / str(pid) / ("stat" if tid == pid else f"task/{tid}/stat")
        try:
            stat = proc_parser.parse_stat_text(base.read_text())
        except (FileNotFoundError, ProcessLookupError, ValueError):
            self.errors += 1
            return None  # task exited or unreadable between readdir and read
        vol = nonvol = None
        tgid = pid
        try:
            st = proc_parser.parse_status_text(
                (PROC / str(pid) / ("status" if tid == pid else f"task/{tid}/status")).read_text())
            vol = st["voluntary_ctxt_switches"]
            nonvol = st["nonvoluntary_ctxt_switches"]
            if st["TGID"] is not None:
                tgid = st["TGID"]
        except (FileNotFoundError, ProcessLookupError):
            pass
        read_b = write_b = None
        try:
            # NOTE: /proc/<pid>/io is PROCESS-level accounting. Thread snapshots
            # repeat these counters with io_scope="process" (see models/task.py).
            io = proc_parser.parse_io_text((PROC / str(pid) / "io").read_text())
            read_b, write_b = io.get("read_bytes"), io.get("write_bytes")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
        task_id = make_task_id(tid, stat.get("starttime"))
        return TaskSnapshot(
            task_id=task_id, pid=pid, tid=tid, tgid=tgid,
            ppid=stat.get("ppid"), comm=stat.get("comm", ""),
            state=stat.get("state", "?"),
            priority=stat.get("priority"), nice=stat.get("nice"),
            num_threads=stat.get("num_threads"),
            starttime_ticks=stat.get("starttime"),
            processor=stat.get("processor"),
            cpu_affinity=proc_parser.read_affinity(pid),
            utime_ticks=stat.get("utime"), stime_ticks=stat.get("stime"),
            voluntary_ctxt_switches=vol, nonvoluntary_ctxt_switches=nonvol,
            read_bytes=read_b, write_bytes=write_b,
            rss_pages=stat.get("rss"),
            timestamp_monotonic_ns=now_mono, timestamp_wall_ns=now_wall,
            experiment_id=self.experiment_id,
        )
