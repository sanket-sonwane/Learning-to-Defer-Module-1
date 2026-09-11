"""F14: RawWriter open-once pattern, context manager, flush, close."""
import json
from pathlib import Path
from m1.storage.raw_writer import RawWriter, read_jsonl


def test_write_and_close(tmp_path):
    p = tmp_path / "test.jsonl"
    w = RawWriter(p)
    w.write({"a": 1})
    w.write({"b": 2})
    w.close()
    rows = read_jsonl(p)
    assert len(rows) == 2
    assert rows[0]["a"] == 1 and rows[1]["b"] == 2


def test_write_many_and_close(tmp_path):
    p = tmp_path / "test.jsonl"
    with RawWriter(p) as w:
        w.write_many([{"i": i} for i in range(5)])
    rows = read_jsonl(p)
    assert len(rows) == 5


def test_context_manager(tmp_path):
    p = tmp_path / "test.jsonl"
    with RawWriter(p) as w:
        w.write({"x": 10})
    assert p.exists()
    rows = read_jsonl(p)
    assert len(rows) == 1


def test_append(tmp_path):
    p = tmp_path / "test.jsonl"
    with RawWriter(p) as w:
        w.write({"a": 1})
    with RawWriter(p) as w:
        w.write({"a": 2})
    rows = read_jsonl(p)
    assert len(rows) == 2


def test_count(tmp_path):
    p = tmp_path / "test.jsonl"
    w = RawWriter(p)
    w.write({"i": 0})
    w.write_many([{"i": i} for i in range(1, 4)])
    assert w.count == 4
    w.close()
