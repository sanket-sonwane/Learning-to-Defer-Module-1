"""Deterministic, self-identifying controlled workloads.

Every workload marks its own processes (argv tag M1_WORKLOAD=<name>) so QA
never mistakes arbitrary system processes for experimental labels.
Linux-only for actual execution; import-safe on Windows.
"""
import os
import subprocess
import sys
import time

TAG = "M1_WORKLOAD"


def _tagged_env(kind: str) -> dict:
    env = dict(os.environ)
    env[TAG] = kind
    return env


def cpu_intensive(duration_s: float) -> None:
    """Busy-loop with periodic yield (deterministic seed-free arithmetic)."""
    end = time.monotonic() + duration_s
    x = 1.0
    while time.monotonic() < end:
        for _ in range(20000):
            x = (x * 1.000001) % 1000.0


def io_heavy(path: str, size_mb: int = 256, duration_s: float = 50.0) -> dict:
    """Sequential write/read cycles of a temp file. Returns byte counts."""
    total_w = total_r = 0
    chunk = b"\x00" * 65536
    end = time.monotonic() + duration_s
    n_chunks = max(1, size_mb * 1024 * 1024 // 65536)
    while time.monotonic() < end:
        with open(path, "wb") as f:
            for _ in range(n_chunks):
                f.write(chunk)
                total_w += len(chunk)
                if time.monotonic() >= end:
                    break
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                total_r += len(chunk)
    return {"written": total_w, "read": total_r}


def mixed(duration_s: float, path: str = "") -> None:
    if not path:
        import tempfile
        fd, path = tempfile.mkstemp(prefix="m1_mixed_", suffix=".bin")
        os.close(fd)
    end = time.monotonic() + duration_s
    x = 1.0
    with open(path, "wb") as f:
        while time.monotonic() < end:
            for _ in range(2000):
                x = (x * 1.000001) % 1000.0
            f.write(b"\x01" * 4096)
            f.flush()


def bursty(duration_s: float, burst_s: float = 2.0, idle_s: float = 3.0,
           io_bytes: int = 65536, path: str = "") -> dict:
    """Deterministic ON-OFF interactive-style workload.

    Browser-like pattern: a short CPU burst (with one small paced I/O write)
    followed by a genuine idle/sleep interval, repeated. The idle gaps leave
    cores unused — unlike the steady cpu_intensive / mixed loops — which is
    what distinguishes interactive from compile-style load. Returns phase
    counts.
    """
    if not path:
        import tempfile
        fd, path = tempfile.mkstemp(prefix="m1_bursty_", suffix=".bin")
        os.close(fd)
    chunk = b"\x02" * max(0, min(io_bytes, 65536))
    end = time.monotonic() + duration_s
    bursts = writes = 0
    x = 1.0
    while time.monotonic() < end:
        burst_end = min(time.monotonic() + burst_s, end)
        while time.monotonic() < burst_end:
            for _ in range(20000):
                x = (x * 1.000001) % 1000.0
        with open(path, "ab") as f:
            f.write(chunk)
        writes += 1
        bursts += 1
        remaining = end - time.monotonic()
        if remaining > 0:
            time.sleep(min(idle_s, remaining))
    return {"bursts": bursts, "writes": writes}


def fork_churn(duration_s: float, spawn_rate_per_s: float = 20.0,
               max_children: int = 32) -> dict:
    """Rapid short-lived children (bounded). Returns spawn/exit counts."""
    from m1.platform_guard import require_linux
    require_linux("fork_churn workload")
    end = time.monotonic() + duration_s
    spawned = reaped = 0
    children: list[int] = []
    gap = 1.0 / max(1.0, spawn_rate_per_s)
    while time.monotonic() < end:
        while children and len(children) >= max_children:
            pid, _ = os.waitpid(-1, 0) if hasattr(os, "waitpid") else (0, 0)
            if pid:
                children.remove(pid)
                reaped += 1
            else:
                break
        if children and len(children) >= max_children:
            time.sleep(gap)
            continue
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        children.append(pid)
        spawned += 1
        time.sleep(gap)
    for pid in children:
        try:
            os.waitpid(pid, 0)
            reaped += 1
        except ChildProcessError:
            pass
    return {"spawned": spawned, "reaped": reaped}


class WorkloadRunner:
    """Launch configured workloads as subprocesses tagged with M1_WORKLOAD.

    Every launch returns a metadata record {workload_id, type, pid,
    start_monotonic_ns, ...} persisted to raw/workload_events/ so observations
    can be attributed without relying on the env tag alone. The tag remains
    as a secondary in-`ps` marker.
    """

    def __init__(self, experiment_id: str = ""):
        from m1 import timebase as _tb
        self._tb = _tb
        self.experiment_id = experiment_id
        self.procs: list[subprocess.Popen] = []
        self.launched: list[dict] = []

    def launch(self, kind: str, duration_s: float, workload_id: str | None = None,
               **kw) -> dict:
        code = {
            "cpu_intensive": f"from m1.workloads.runner import cpu_intensive; cpu_intensive({duration_s})",
        }.get(kind)
        if code is None and kind == "bursty":
            code = (f"from m1.workloads.runner import bursty; "
                    f"bursty({duration_s}, {kw.get('burst_s', 2.0)}, "
                    f"{kw.get('idle_s', 3.0)}, {kw.get('io_bytes', 65536)})")
        if code is None and kind == "mixed":
            import tempfile as _tmp
            fd, mp = _tmp.mkstemp(prefix="m1_mixed_", suffix=".bin")
            os.close(fd)
            code = (f"from m1.workloads.runner import mixed; "
                    f"mixed({duration_s}, {mp!r})")
        if code is None and kind == "io_heavy":
            p = kw.get("path", "/tmp/m1_io.bin")
            code = (f"from m1.workloads.runner import io_heavy; "
                    f"io_heavy({p!r}, {kw.get('size_mb', 64)}, {duration_s})")
        if code is None and kind == "fork_churn":
            code = (f"from m1.workloads.runner import fork_churn; "
                    f"fork_churn({duration_s}, {kw.get('spawn_rate_per_s', 20.0)}, "
                    f"{kw.get('max_children', 32)})")
        if code is None:
            raise ValueError(f"Unknown workload {kind!r}")
        proc = subprocess.Popen([sys.executable, "-c", code], env=_tagged_env(kind))
        self.procs.append(proc)
        rec = {"workload_id": workload_id or f"{kind}-{proc.pid}",
               "type": kind, "pid": proc.pid,
               "start_monotonic_ns": self._tb.monotonic_ns(),
               "end_monotonic_ns": self._tb.monotonic_ns()
               + int(float(duration_s) * 1e9),
               "experiment_id": self.experiment_id,
               "duration_s": duration_s,
               "params": {k: v for k, v in kw.items() if k != "count"}}
        self.launched.append(rec)
        return rec

    def stop_all(self) -> None:
        """Graceful terminate -> timeout -> SIGKILL -> liveness verification."""
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        # Wait with timeout for graceful shutdown.
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        # Final liveness check: SIGKILL any survivors.
        for p in self.procs:
            if p.poll() is None:
                try:
                    p.kill()
                    p.wait(timeout=5)
                except Exception:
                    pass
