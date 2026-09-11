"""Unit: derived feature math (native vs derived separation)."""
from m1.telemetry.features import HistoryWindow, cpu_util_pct, cs_rate_per_s, io_rate_bps


def test_cpu_util_basic():
    # 100 ticks user+sys on 1 cpu over 1s at 100Hz => 100%
    assert cpu_util_pct(80, 20, 1.0, 1) == 100.0
    # 4 cpus => 25%
    assert cpu_util_pct(80, 20, 1.0, 4) == 25.0


def test_cpu_util_missing_and_negative():
    assert cpu_util_pct(None, 10, 1.0, 1) is None
    assert cpu_util_pct(10, 10, 0.0, 1) is None
    assert cpu_util_pct(-5, 10, 1.0, 1) is None  # counter wrap / reuse -> None, not 0


def test_rates():
    assert io_rate_bps(1000, 2.0) == 500.0
    assert io_rate_bps(None, 2.0) is None
    assert cs_rate_per_s(10, 2.0) == 5.0


def test_history_window_bounded():
    h = HistoryWindow(3)
    for v in (1.0, 2.0, 3.0, 4.0):
        h.push(v)
    assert h.values() == [2.0, 3.0, 4.0]
