"""Derived telemetry features.

Classification (never mislabel):
- NATIVE: counters/fields straight from /proc (utime, stime, io bytes, cs counts).
- DERIVED: cpu_util, io rates, cs rates, history windows — computed from deltas.

Rules: missing -> None (never 0-fill); negative deltas (counter wrap / PID
reuse) -> None + reason.
"""
from collections import deque
import os

CLK_TCK_DEFAULT = 100


def get_clk_tck() -> int:
    """Authoritative clock-tick frequency: os.sysconf on Linux.

    Never hardcode: callers must pass the experiment's recorded value into
    cpu_util_pct(). This helper is the single query point (mockable in tests).
    """
    if hasattr(os, "sysconf") and "SC_CLK_TCK" in os.sysconf_names:
        try:
            return int(os.sysconf("SC_CLK_TCK"))
        except (ValueError, OSError):
            pass
    return CLK_TCK_DEFAULT


# Backwards-compatible alias (do NOT use as an authoritative assumption).
CLK_TCK = CLK_TCK_DEFAULT


def delta_or_none(cur: int | float | None, prev: int | float | None,
                  anomalies: dict | None = None) -> int | float | None:
    """Generation-safe counter delta.

    valid + valid      → cur - prev (or None + anomaly if negative = wrap/reset)
    missing either side → None (missing is NEVER 0)
    """
    if cur is None or prev is None:
        return None
    d = cur - prev
    if d < 0:
        if anomalies is not None:
            anomalies["negative_deltas"] = anomalies.get("negative_deltas", 0) + 1
        return None
    return d


def _rate(delta: int | float | None, dt_s: float) -> float | None:
    if delta is None or dt_s <= 0:
        return None
    if delta < 0:
        return None
    return delta / dt_s


def cpu_util_pct(delta_utime: int | None, delta_stime: int | None,
                 dt_s: float, num_cpus: int = 1, clk_tck: int | None = None) -> float | None:
    """DERIVED: CPU utilization % over the interval.

    clk_tck must be the experiment's recorded SC_CLK_TCK (None → queried once
    via get_clk_tck(); tests should inject explicitly).
    """
    if delta_utime is None or delta_stime is None or dt_s <= 0 or num_cpus <= 0:
        return None
    if delta_utime < 0 or delta_stime < 0:
        # A negative component means counter wrap or PID reuse with a stale
        # baseline — the delta is invalid, report None (never 0-fill).
        return None
    if clk_tck is None:
        clk_tck = get_clk_tck()
    d = delta_utime + delta_stime
    return (d / clk_tck) / (dt_s * num_cpus) * 100.0


def io_rate_bps(delta_bytes: int | None, dt_s: float) -> float | None:
    """DERIVED: bytes/sec from cumulative /proc/<pid>/io counters."""
    return _rate(delta_bytes, dt_s)


def cs_rate_per_s(delta_cs: int | None, dt_s: float) -> float | None:
    """DERIVED: context switches/sec from cumulative counters."""
    return _rate(delta_cs, dt_s)


class HistoryWindow:
    """Rolling derived history, e.g. CPU(t-1..t-N) for temporal features."""

    def __init__(self, size: int = 10):
        self._buf: deque[float | None] = deque(maxlen=size)

    def push(self, v: float | None) -> None:
        self._buf.append(v)

    def values(self) -> list[float | None]:
        return list(self._buf)
