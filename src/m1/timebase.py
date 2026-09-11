"""Canonical time base for M1.

All event ordering and observation joins use CLOCK_MONOTONIC nanoseconds.
Wall-clock time is stored separately for human-readable metadata only.
"""
import time


def monotonic_ns() -> int:
    # Linux: CLOCK_MONOTONIC (matches bpf_ktime_get_ns). Windows: no
    # clock_gettime — fall back to monotonic_ns() (also monotonic).
    try:
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    except AttributeError:
        return time.monotonic_ns()


def wall_ns() -> int:
    return time.time_ns()


def monotonic_ms() -> float:
    return monotonic_ns() / 1e6
