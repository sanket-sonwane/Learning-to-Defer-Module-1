"""Processed Parquet writer (pyarrow required on Linux).

On platforms without pyarrow (e.g. minimal Windows dev), raises a clear
error; callers fall back to JSONL export so unit tests still run.

Missing (None) values inside list columns are stored as NaN in Parquet:
pyarrow 25.x's parquet reader SIGILLs when decoding list<double> columns
that contain nested nulls. Raw JSONL remains authoritative and keeps true
nulls; the parquet is a derived ML-consumption artifact where NaN is the
standard float-missing marker.
"""
import math
from pathlib import Path

_NESTED_NULL_COLUMNS = ("cpu_history",)


def _sanitize(row: dict) -> dict:
    """Replace None inside list columns with NaN (see module docstring)."""
    out = dict(row)
    hist = out.get("cpu_history")
    if isinstance(hist, list):
        out["cpu_history"] = [float("nan") if v is None else v for v in hist]
    return out


def write_observations_parquet(rows: list[dict], path: Path) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise RuntimeError(
            "pyarrow is required for Parquet output (Linux). "
            "Install requirements-linux.txt or export JSONL instead.") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([_sanitize(r) for r in rows])
    pq.write_table(table, path)
    return len(rows)


def read_observations_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq
    rows = pq.read_table(path).to_pylist()
    for r in rows:
        h = r.get("cpu_history")
        if isinstance(h, list):
            r["cpu_history"] = [None if (v is not None and math.isnan(v)) else v
                                for v in h]
    return rows