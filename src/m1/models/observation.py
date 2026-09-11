"""ObservationRecord — synchronized decision-time record for downstream modules.

Joins task snapshot + scheduler activity in window + system + PSI + context
+ temporal history. All ordering on monotonic ns. Missing values are None.
"""
from typing import Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION


class ObservationRecord(BaseModel):
    schema_version: str = SCHEMA_VERSION
    observation_id: str
    experiment_id: str = ""
    timestamp_monotonic_ns: int
    timestamp_wall_ns: Optional[int] = None
    # Task identity
    task_id: str
    pid: int
    tid: int
    tgid: Optional[int] = None
    cpu_id: Optional[int] = None
    state: str = ""
    priority: Optional[int] = None
    nice: Optional[int] = None
    # Native counters at observation time
    cpu_runtime_ticks: Optional[int] = None
    voluntary_cs: Optional[int] = None
    nonvoluntary_cs: Optional[int] = None
    read_bytes: Optional[int] = None
    write_bytes: Optional[int] = None
    io_scope: str = Field(
        default="process",
        description="Scope of read/write_bytes: /proc/<pid>/io is PROCESS-level "
                    "(see TaskSnapshot.io_scope). Never per-thread.")
    num_threads: Optional[int] = None
    cpu_affinity: Optional[list[int]] = None
    # Derived features (computed from deltas/events over the window)
    recent_cpu_runtime_ticks: Optional[int] = None
    cpu_util_pct: Optional[float] = None
    cs_rate_per_s: Optional[float] = None
    io_read_bps: Optional[float] = None
    io_write_bps: Optional[float] = None
    run_sleep_info: Optional[dict] = Field(
        default=None,
        description="RESERVED / unavailable in M1 v1 (Option B). Wake-to-run and "
                    "run-duration derivation from scheduler events is deferred; "
                    "downstream code must treat None as missing, never fabricate.")
    cpu_history: Optional[list[Optional[float]]] = Field(
        default=None, description="Derived cpu_util at t-1, t-2, ... within window (None where underivable)")
    # Scheduler activity in window
    events_in_window: int = 0
    last_wakeup_ns: Optional[int] = None
    last_switch_in_ns: Optional[int] = None
    last_switch_out_ns: Optional[int] = None
    # System (derived + native)
    sys_cpu_util_pct: Optional[float] = None
    runnable_tasks: Optional[int] = None
    # PSI
    cpu_psi_some_10: Optional[float] = None
    mem_psi_some_10: Optional[float] = None
    io_psi_some_10: Optional[float] = None
    # Controlled context
    user_state: str = ""
    foreground_app: str = ""
    scenario_id: str = ""
    workload_id: Optional[str] = Field(
        default=None, description="Workload that generated this task's activity "
                    "(pid match against raw/workload_events), else None")
    workload_type: Optional[str] = None
    context_source: str = "controlled_ground_truth"
    missing_reason: Optional[str] = None
