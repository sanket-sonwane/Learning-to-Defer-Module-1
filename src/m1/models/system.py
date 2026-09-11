"""SystemSnapshot — machine-wide CPU/load state.

Utilizations are DERIVED from /proc/stat deltas (native counters -> derived rates).
"""
from typing import Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION


class SystemSnapshot(BaseModel):
    schema_version: str = SCHEMA_VERSION
    timestamp_monotonic_ns: int
    timestamp_wall_ns: Optional[int] = None
    experiment_id: str = ""
    # Derived (from /proc/stat deltas)
    total_cpu_util_pct: Optional[float] = None
    per_cpu_util_pct: Optional[list[Optional[float]]] = None
    # Native / load
    runnable_tasks: Optional[int] = Field(
        default=None, description="nr_running / procs_running where available")
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    missing_reason: Optional[str] = None
