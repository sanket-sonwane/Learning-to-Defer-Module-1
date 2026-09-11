"""SchedulerEvent — one scheduler tracepoint record.

Every event carries monotonic ns, event type, CPU, and task identity
sufficient to correlate with TaskSnapshot.task_id.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION

SchedEventType = Literal[
    "sched_switch", "sched_wakeup", "sched_wakeup_new",
    "sched_process_exec", "sched_process_exit",
]


class SchedulerEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_type: SchedEventType
    timestamp_monotonic_ns: int
    cpu: int
    pid: int
    tid: int
    tgid: Optional[int] = None
    comm: str = ""
    task_id: Optional[str] = Field(
        default=None, description="Resolved '<pid>:<starttime>' when known, else None")
    # Event-specific native fields
    prev_pid: Optional[int] = None
    prev_comm: Optional[str] = None
    prev_state: Optional[int] = None
    next_pid: Optional[int] = None
    next_comm: Optional[str] = None
    prio: Optional[int] = None
    success: Optional[int] = None
    experiment_id: str = ""
