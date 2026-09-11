"""Experiment ID generation: EXP-YYYYMMDD-NNN per data directory."""
import re
from datetime import datetime, timezone
from pathlib import Path

EXP_RE = re.compile(r"^EXP-\d{8}-\d{3}$")


def generate_experiment_id(data_root: Path, when: datetime | None = None) -> str:
    day = (when or datetime.now(timezone.utc)).strftime("%Y%m%d")
    taken = set()
    if data_root.exists():
        for child in data_root.iterdir():
            if child.is_dir() and EXP_RE.match(child.name) and day in child.name:
                taken.add(child.name)
    n = 1
    while f"EXP-{day}-{n:03d}" in taken:
        n += 1
    return f"EXP-{day}-{n:03d}"


def validate_experiment_id(exp_id: str) -> None:
    if not EXP_RE.match(exp_id):
        raise ValueError(f"Invalid experiment id: {exp_id!r} (expected EXP-YYYYMMDD-NNN)")
