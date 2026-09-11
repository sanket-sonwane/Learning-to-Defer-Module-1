"""Streaming JSONL raw writer (one record per line, never overwritten).

Design:
  - open-once: file handle kept open for the lifetime of the writer
  - write/write_many append and flush appropriately
  - close() must be called to release the file handle
  - context manager support for automatic cleanup
  - Crash semantics: last flush may lose at most one batch of unflushed records
  - Concurrent access: each RawWriter instance owns its file; no shared writes
"""
import json
from pathlib import Path
from pydantic import BaseModel


class RawWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self._fh = None

    def _open(self) -> None:
        if self._fh is None or self._fh.closed:
            self._fh = self.path.open("a")

    def write(self, record: BaseModel | dict) -> None:
        data = record.model_dump() if isinstance(record, BaseModel) else record
        self._open()
        self._fh.write(json.dumps(data, default=str) + "\n")
        self.count += 1

    def write_many(self, records: list) -> None:
        self._open()
        for r in records:
            data = r.model_dump() if isinstance(r, BaseModel) else r
            self._fh.write(json.dumps(data, default=str) + "\n")
            self.count += 1
        self._fh.flush()

    def flush(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.flush()

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
