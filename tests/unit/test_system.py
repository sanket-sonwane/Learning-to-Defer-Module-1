"""Unit: system stat parsing and derived CPU util."""
from m1.system.cpu import cpu_util, parse_loadavg, parse_stat_counters


def test_parse_stat():
    txt = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0 0 0\nintr 123\n"
    c = parse_stat_counters(txt)
    assert "cpu" in c and "cpu0" in c and "intr" not in c


def test_cpu_util_derived():
    prev = [100, 0, 100, 800, 0, 0, 0]
    cur = [150, 0, 150, 900, 0, 0, 0]
    # d_total=200, d_idle=100 -> 50%
    assert cpu_util(prev, cur) == 50.0
    assert cpu_util(prev, prev) is None  # zero delta -> None


def test_loadavg():
    l1, l5, l15, info = parse_loadavg("1.20 0.90 0.50 2/512 12345\n")
    assert (l1, l5, l15) == (1.2, 0.9, 0.5) and info == "2/512"
