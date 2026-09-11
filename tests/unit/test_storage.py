"""Unit: storage round-trip (JSONL raw preserved; parquet optional)."""
from m1.models.task import TaskSnapshot
from m1.storage.layout import ExperimentLayout
from m1.storage.raw_writer import RawWriter, read_jsonl


def test_raw_jsonl_roundtrip(tmp_path):
    layout = ExperimentLayout(tmp_path, "EXP-20260101-001")
    layout.create()
    assert (layout.raw_tasks / "").exists() or layout.raw_tasks.exists()
    w = RawWriter(layout.raw_tasks / "tasks.jsonl")
    snap = TaskSnapshot(task_id="1:100", pid=1, tid=1, tgid=1, state="S",
                        timestamp_monotonic_ns=123)
    w.write(snap)
    w.close()
    rows = read_jsonl(layout.raw_tasks / "tasks.jsonl")
    assert len(rows) == 1 and rows[0]["task_id"] == "1:100"


def test_parquet_optional(tmp_path):
    import pytest
    pa = pytest.importorskip("pyarrow", reason="pyarrow optional on Windows dev")
    from m1.storage.parquet_writer import write_observations_parquet, read_observations_parquet
    rows = [{"a": 1}]
    p = tmp_path / "o.parquet"
    assert write_observations_parquet(rows, p) == 1
    assert read_observations_parquet(p) == rows


def test_parquet_observation_roundtrip(tmp_path, parquet_list_supported):
    """Full observation rows (incl. cpu_history list) survive parquet.

    None entries inside the list column are stored as NaN (parquet cannot
    hold nested nulls in list<double> on this toolchain without crashing the
    reader — see conftest probe) and are restored to None on read, so X
    semantics is None-identical round trip.
    """
    import pytest
    pa = pytest.importorskip("pyarrow", reason="pyarrow optional on Windows dev")
    if not parquet_list_supported:
        pytest.skip("pyarrow list<double> parquet decode SIGILLs on this "
                    "hypervisor (AVX masked); environment defect, not M1.")
    from m1.storage.parquet_writer import write_observations_parquet, read_observations_parquet
    rows = [
        {"schema_version": "1.0.0", "observation_id": "EXP-1:1:2:3",
         "cpu_history": [30.0, None, 12.5], "pid": 2},
        {"schema_version": "1.0.0", "observation_id": "EXP-1:1:3:4",
         "cpu_history": None, "pid": 3},
    ]
    p = tmp_path / "obs.parquet"
    assert write_observations_parquet(rows, p) == 2
    out = read_observations_parquet(p)
    assert out[0]["cpu_history"] == [30.0, None, 12.5]
    assert out[0]["observation_id"] == "EXP-1:1:2:3"
    assert out[1]["cpu_history"] is None
