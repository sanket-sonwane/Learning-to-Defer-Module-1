"""Sampling cadence: absolute-deadline stats + QA gate (fix doc #17, item 5)."""
import statistics

from m1.qa.checks import (
    check_sampling_cadence,
    CADENCE_MAX_MISSED_RATIO,
    CADENCE_MIN_FREQ_RATIO,
)
from m1.experiment.controller import _cadence_stats


def _intervals_points(mean_ms, n=100, jitter_ms=10.0):
    """Synthetic stable intervals around mean_ms with mild jitter."""
    rng = list(range(n))
    return [mean_ms + (jitter_ms * ((i * 2654435761) % 17) / 17.0 - jitter_ms / 2)
            for i in rng]


def test_cadence_stats_stable():
    """A stable 100ms cadence reports ~100ms mean with no missed deadlines."""
    intervals = _intervals_points(100.0, n=100, jitter_ms=5.0)
    s = _cadence_stats(intervals, requested_period_ns=100_000_000)
    assert s["requested_ms"] == 100.0
    assert s["samples"] == 100
    assert abs(s["mean_ms"] - 100.0) < 3.0, s["mean_ms"]
    assert s["missed_deadlines"] == 0
    assert s["missed_deadline_ratio"] == 0.0
    assert 9.0 < s["effective_freq_hz"] < 11.0, s["effective_freq_hz"]


def test_cadence_stats_collapse():
    """A 1-second effective cadence (the historical bug) is NOT laundered."""
    intervals = _intervals_points(1000.0, n=50, jitter_ms=50.0)
    s = _cadence_stats(intervals, requested_period_ns=100_000_000)
    assert abs(s["mean_ms"] - 1000.0) < 20.0
    # Every interval > 150ms -> 100% missed
    assert s["missed_deadlines"] == 50
    assert s["missed_deadline_ratio"] == 1.0
    assert s["effective_freq_hz"] < 1.1


def test_cadence_stats_empty():
    s = _cadence_stats([], requested_period_ns=100_000_000)
    assert s["samples"] == 0
    assert s["effective_freq_hz"] is None


def test_cadence_gate_ok():
    s = _cadence_stats(_intervals_points(100.0), requested_period_ns=100_000_000)
    check = check_sampling_cadence(s)
    assert check.passed is True
    assert check.severity == "info"


def test_cadence_gate_misses_ratio():
    s = _cadence_stats(_intervals_points(500.0, n=20),
                       requested_period_ns=100_000_000)
    assert s["missed_deadline_ratio"] > CADENCE_MAX_MISSED_RATIO
    check = check_sampling_cadence(s)
    assert check.passed is False
    assert check.severity == "warning"
    assert "missed deadline" in check.detail


def test_cadence_gate_low_freq_warning():
    """Effective freq below half the requested rate must be flagged.

    Bimodal: 70% of ticks at 145ms (inside the 1.5x deadline), 30% at ~330ms
    (exactly at the 0.30 miss ratio edge). Mean 200.5ms -> 4.99Hz, under the
    5Hz (half of 10Hz) threshold -> freq gate trips, miss gate does not.
    """
    intervals = [145.0] * 70 + [330.0] * 30
    s = _cadence_stats(intervals, requested_period_ns=100_000_000)
    assert s["missed_deadline_ratio"] == 0.30  # not above the miss gate
    assert s["effective_freq_hz"] < 5.0, s["effective_freq_hz"]
    check = check_sampling_cadence(s)
    assert check.passed is False
    assert check.severity == "warning"
    assert "effective frequency" in check.detail


def test_cadence_gate_missing_data():
    check = check_sampling_cadence(None)
    assert check.passed is True
    assert check.severity == "warning"
    check2 = check_sampling_cadence({"samples": 0, "requested_ms": 100.0})
    assert check2.passed is True
    assert check2.severity == "warning"


def test_cadence_gate_thresholds_are_documented_constants():
    from m1.qa import checks
    doc = checks.__dict__.get("CADENCE_MAX_MISSED_RATIO")
    assert doc == 0.30
    assert checks.CADENCE_MIN_FREQ_RATIO == 0.50