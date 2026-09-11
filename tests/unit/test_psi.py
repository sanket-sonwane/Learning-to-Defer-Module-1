"""Unit: PSI parsing; CPU full must never appear."""
from m1.psi.reader import parse_psi_line, read_resource


def test_parse_some_line():
    d = parse_psi_line("some avg10=1.23 avg60=0.45 avg300=0.12 total=6789")
    assert d.avg10 == 1.23 and d.avg60 == 0.45 and d.avg300 == 0.12
    assert d.total_us == 6789


def test_cpu_full_ignored(tmp_path, monkeypatch):
    import m1.psi.reader as R
    fake = tmp_path / "cpu"
    fake.write_text("some avg10=1.0 avg60=0.5 avg300=0.1 total=100\n"
                    "full avg10=0.0 avg60=0.0 avg300=0.0 total=0\n")
    monkeypatch.setattr(R, "PRESSURE", tmp_path)
    out, reason = read_resource("cpu")
    assert "some" in out
    assert "full" not in out  # undefined system-wide -> never collected


def test_missing_file_reports_reason(tmp_path, monkeypatch):
    import m1.psi.reader as R
    monkeypatch.setattr(R, "PRESSURE", tmp_path)
    out, reason = read_resource("cpu")
    assert out == {} and reason
