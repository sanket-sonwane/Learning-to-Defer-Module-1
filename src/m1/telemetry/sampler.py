"""Periodic task sampler: repeated /proc scans with delta computation.

Streaming, bounded memory; disappearing tasks are recorded as exits, not crashes.
"""
import time
from m1 import timebase
from m1.platform_guard import require_linux
from m1.models.task import TaskSnapshot
from m1.task_discovery.registry import TaskRegistry
from m1.telemetry import features


class TaskSampler:
    def __init__(self, experiment_id: str = "", interval_ms: int = 100, num_cpus: int = 1,
                 clk_tck: int | None = None):
        self.registry = TaskRegistry(experiment_id)
        self.interval_ms = interval_ms
        self.num_cpus = num_cpus
        # Experiment's recorded SC_CLK_TCK (None → queried once via get_clk_tck).
        self.clk_tck = clk_tck if clk_tck is not None else features.get_clk_tck()
        self._prev: dict[str, TaskSnapshot] = {}
        self._prev_ts: dict[str, int] = {}
        self.samples = 0
        self.errors = 0
        self.anomalies: dict = {"negative_deltas": 0}

    def sample_once(self) -> list[dict]:
        require_linux("Task sampler")
        snaps, exited_ids = self.registry.scan()
        now = timebase.monotonic_ns()
        self.exited_ids = exited_ids
        out: list[dict] = []
        for s in snaps:
            prev = self._prev.get(s.task_id)
            row = s.model_dump()
            row["derived"] = {}
            if prev is not None:
                dt_s = (s.timestamp_monotonic_ns - prev.timestamp_monotonic_ns) / 1e9
                du = features.delta_or_none(s.utime_ticks, prev.utime_ticks, self.anomalies)
                ds = features.delta_or_none(s.stime_ticks, prev.stime_ticks, self.anomalies)
                row["derived"]["cpu_util_pct"] = features.cpu_util_pct(
                    du, ds, dt_s, self.num_cpus, self.clk_tck)
                drb = features.delta_or_none(s.read_bytes, prev.read_bytes, self.anomalies)
                dwb = features.delta_or_none(s.write_bytes, prev.write_bytes, self.anomalies)
                row["derived"]["io_read_bps"] = features.io_rate_bps(drb, dt_s)
                row["derived"]["io_write_bps"] = features.io_rate_bps(dwb, dt_s)
                dv = features.delta_or_none(
                    s.voluntary_ctxt_switches, prev.voluntary_ctxt_switches, self.anomalies)
                dnv = features.delta_or_none(
                    s.nonvoluntary_ctxt_switches, prev.nonvoluntary_ctxt_switches,
                    self.anomalies)
                tot = (dv + dnv) if (dv is not None and dnv is not None) else None
                row["derived"]["cs_rate_per_s"] = features.cs_rate_per_s(tot, dt_s)
            self._prev[s.task_id] = s
            out.append(row)
        self.samples += 1
        return out

    def run(self, duration_s: float, sink) -> dict:
        """Run for duration_s, calling sink(rows) per interval. Returns stats."""
        require_linux("Task sampler")
        end = time.monotonic() + duration_s
        while time.monotonic() < end:
            try:
                sink(self.sample_once())
            except Exception:
                self.errors += 1
            time.sleep(self.interval_ms / 1000.0)
        return {"samples": self.samples, "errors": self.errors}
