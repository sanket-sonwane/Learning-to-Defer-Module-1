"""PSISnapshot — Pressure Stall Information from /proc/pressure/{cpu,memory,io}.

Semantics: avg10/avg60/avg300 are the percentage of time (0-100) some tasks
were stalled over the window; total is cumulative stall microseconds.
CPU `full` is undefined system-wide — we never collect or invent it.
"""
from typing import Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION


class PSIDirection(BaseModel):
    avg10: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    avg60: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    avg300: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    total_us: Optional[int] = Field(default=None, description="Cumulative stall time, microseconds")


class PSISnapshot(BaseModel):
    schema_version: str = SCHEMA_VERSION
    timestamp_monotonic_ns: int
    experiment_id: str = ""
    cpu_some: PSIDirection = PSIDirection()
    mem_some: PSIDirection = PSIDirection()
    mem_full: PSIDirection = PSIDirection()
    io_some: PSIDirection = PSIDirection()
    io_full: PSIDirection = PSIDirection()
    missing_reason: Optional[str] = None
