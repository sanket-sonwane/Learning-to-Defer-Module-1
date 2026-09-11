"""F12: PSI avg values must be in range 0-100."""
import pytest
from m1.models.psi import PSIDirection, PSISnapshot


def test_psi_valid_range():
    d = PSIDirection(avg10=50.0, avg60=30.0, avg300=10.0, total_us=1000)
    assert d.avg10 == 50.0


def test_psi_none_allowed():
    d = PSIDirection()
    assert d.avg10 is None and d.avg60 is None and d.avg300 is None


def test_psi_zero_allowed():
    d = PSIDirection(avg10=0.0, avg60=0.0, avg300=0.0)
    assert d.avg10 == 0.0


def test_psi_100_allowed():
    d = PSIDirection(avg10=100.0, avg60=100.0, avg300=100.0)
    assert d.avg10 == 100.0


def test_psi_negative_rejected():
    with pytest.raises(Exception):
        PSIDirection(avg10=-1.0)


def test_psi_over_100_rejected():
    with pytest.raises(Exception):
        PSIDirection(avg10=101.0)


def test_psi_malformed_string_rejected():
    with pytest.raises(Exception):
        PSIDirection(avg10="high")


def test_psi_full_snapshot():
    snap = PSISnapshot(
        timestamp_monotonic_ns=1000,
        cpu_some=PSIDirection(avg10=5.0, avg60=3.0, avg300=1.0),
        mem_some=PSIDirection(avg10=10.0),
    )
    assert snap.cpu_some.avg10 == 5.0
    assert snap.mem_some.avg10 == 10.0
    assert snap.io_some.avg10 is None
