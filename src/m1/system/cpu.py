"""System CPU/load collection from /proc/stat and /proc/loadavg.

Utilizations are DERIVED from cumulative counter deltas:
  util = 1 - (Δidle + Δiowait) / Δtotal
runnable_tasks prefers /proc/sched_debug nr_running, falls back to
procs_running from /proc/stat, else None (never fabricated).
"""
from pathlib import Path
from m1 import timebase
from m1.platform_guard import require_linux
from m1.models.system import SystemSnapshot

PROC_STAT = Path("/proc/stat")
PROC_LOADAVG = Path("/proc/loadavg")
PROC_SCHED_DEBUG = Path("/proc/sched_debug")


def parse_stat_counters(text: str) -> dict:
    """Parse /proc/stat cpu lines into {cpu_id: [user,nice,system,idle,iowait,irq,softirq,...]}."""
    cpus: dict = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        name = parts[0]
        try:
            vals = [int(x) for x in parts[1:]]
        except ValueError:
            continue
        cpus[name] = vals
    return cpus


def cpu_util(prev: list[int], cur: list[int]) -> float | None:
    """DERIVED utilization % between two /proc/stat samples for one cpu line."""
    if not prev or not cur or len(prev) < 5 or len(cur) < 5:
        return None
    n = min(len(prev), len(cur))
    d_total = sum(cur[i] - prev[i] for i in range(n))
    if d_total <= 0:
        return None
    d_idle = (cur[3] - prev[3]) + (cur[4] - prev[4] if n > 4 else 0)
    if d_idle < 0:
        return None
    return (1.0 - d_idle / d_total) * 100.0


def parse_loadavg(text: str) -> tuple[float | None, float | None, float | None, str | None]:
    """Returns (load1, load5, load15, running_info like '2/512')."""
    parts = text.split()
    try:
        return float(parts[0]), float(parts[1]), float(parts[2]), parts[3] if len(parts) > 3 else None
    except (ValueError, IndexError):
        return None, None, None, None


def read_runnable() -> tuple[int | None, str | None]:
    """Best-effort runnable task count. Returns (count, missing_reason)."""
    try:
        for line in PROC_SCHED_DEBUG.read_text().splitlines():
            line = line.strip()
            if line.startswith("nr_running"):
                return int(line.split(":")[1].strip().split()[0]), None
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    try:
        for line in PROC_STAT.read_text().splitlines():
            if line.startswith("procs_running"):
                return int(line.split()[1]), None
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        pass
    return None, "nr_running/procs_running unavailable"


class SystemCollector:
    def __init__(self, experiment_id: str = ""):
        self.experiment_id = experiment_id
        self._prev: dict | None = None
        self.errors = 0

    def sample(self) -> SystemSnapshot:
        require_linux("System collector")
        now = timebase.monotonic_ns()
        cur = parse_stat_counters(PROC_STAT.read_text())
        total = per = None
        if self._prev is not None and "cpu" in cur and "cpu" in self._prev:
            total = cpu_util(self._prev["cpu"], cur["cpu"])
            per = []
            i = 0
            while f"cpu{i}" in cur:
                if f"cpu{i}" in self._prev:
                    per.append(cpu_util(self._prev[f"cpu{i}"], cur[f"cpu{i}"]))
                else:
                    per.append(None)
                i += 1
        self._prev = cur
        l1 = l5 = l15 = None
        try:
            l1, l5, l15, _ = parse_loadavg(PROC_LOADAVG.read_text())
        except OSError:
            self.errors += 1
        runnable, missing = read_runnable()
        return SystemSnapshot(
            timestamp_monotonic_ns=now, experiment_id=self.experiment_id,
            total_cpu_util_pct=total, per_cpu_util_pct=per,
            runnable_tasks=runnable, load_1=l1, load_5=l5, load_15=l15,
            missing_reason=missing,
        )
