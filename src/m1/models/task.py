"""TaskSnapshot — native task fields observed from /proc.

Research-integrity rules:
- task_id = "<pid>:<starttime>" (starttime = /proc stat field 22, clock ticks).
  PID alone is NEVER a persistent identity (PID reuse).
- Fields unavailable on a given kernel are None (never fabricated, never 0-filled).
- Derived quantities (cpu utilization, rates) live in telemetry/features, NOT here.
"""
from typing import Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION


class TaskSnapshot(BaseModel):
    schema_version: str = SCHEMA_VERSION
    # Identity
    task_id: str = Field(description="Persistent identity '<pid>:<starttime_ticks>'")
    pid: int
    tid: int
    tgid: int
    ppid: Optional[int] = None
    comm: str = ""
    # Native state
    state: str = Field(description="Single-letter task state from /proc stat (R/S/D/Z/T/...)")
    priority: Optional[int] = None
    nice: Optional[int] = None
    num_threads: Optional[int] = None
    starttime_ticks: Optional[int] = Field(
        default=None, description="/proc stat field 22: start time in clock ticks since boot")
    processor: Optional[int] = Field(default=None, description="Last CPU the task ran on (field 39)")
    cpu_affinity: Optional[list[int]] = None
    # Native cumulative counters (NOT rates)
    utime_ticks: Optional[int] = None
    stime_ticks: Optional[int] = None
    voluntary_ctxt_switches: Optional[int] = None
    nonvoluntary_ctxt_switches: Optional[int] = None
    read_bytes: Optional[int] = Field(default=None, description="Cumulative from /proc/<pid>/io rchar or read_bytes")
    write_bytes: Optional[int] = None
    io_scope: str = Field(
        default="process",
        description="Scope of read_bytes/write_bytes: /proc/<pid>/io is PROCESS-level. "
                    "Thread snapshots repeat the process counters with this label — "
                    "never interpret them as per-thread I/O.")
    rss_pages: Optional[int] = None
    # Timestamps
    timestamp_monotonic_ns: int
    timestamp_wall_ns: Optional[int] = None
    experiment_id: str = ""
    missing_reason: Optional[str] = Field(
        default=None, description="Why a field is null, if systematically missing")
