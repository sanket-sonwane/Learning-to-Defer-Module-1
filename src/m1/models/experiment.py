"""ExperimentMetadata, MachineMetadata, CollectorConfig."""
from typing import Any, Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION


class CollectorConfig(BaseModel):
    config_version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION
    sampling_interval_ms: int = 100
    observation_window_ms: int = 500
    task_scan_ms: int = 100
    system_scan_ms: int = 100
    psi_scan_ms: int = 100
    psi_interval_ms: int = 100
    scheduler_backend: str = Field(
        default="auto",
        description="Requested backend: 'auto' (ebpf if available else tracefs_fallback), "
                    "'ebpf', or 'no-bpf'. Resolved backend is recorded in ExperimentMetadata.")
    sched_events: list[str] = Field(default_factory=lambda: [
        "sched_switch", "sched_wakeup", "sched_wakeup_new",
        "sched_process_exec", "sched_process_exit"])
    ringbuf_size: int = 8388608
    overhead_target_cpu_pct: float = 2.0
    raw_format: str = "jsonl"
    processed_format: str = "parquet"


class MachineMetadata(BaseModel):
    schema_version: str = SCHEMA_VERSION
    distro: str = ""
    kernel: str = ""
    arch: str = ""
    cpu_model: str = ""
    num_cpus: int = 0
    mem_total_kb: Optional[int] = None
    vm_info: str = ""
    btf_available: bool = False
    bpffs_mounted: bool = False
    psi_available: bool = False
    clk_tck: int = Field(default=100, description="SC_CLK_TCK queried on the collection host")
    tool_versions: dict[str, str] = Field(default_factory=dict)


class CollectorFailure(BaseModel):
    component: str
    failure_time_monotonic_ns: int
    reason: str = ""
    critical: bool = True


class ExperimentMetadata(BaseModel):
    schema_version: str = SCHEMA_VERSION
    experiment_id: str
    scenario: str = ""
    start_wall_ns: Optional[int] = None
    end_wall_ns: Optional[int] = None
    duration_s: float = 0.0
    collector_version: str = "1.0.0"
    config_version: str = "1.0.0"
    git_commit: str = ""
    machine: MachineMetadata = MachineMetadata()
    workload_config: dict[str, Any] = Field(default_factory=dict)
    context_config: dict[str, Any] = Field(default_factory=dict)
    collection_intervals_ms: dict[str, int] = Field(default_factory=dict)
    observation_window_ms: int = 500
    clk_tck: int = Field(default=100, description="SC_CLK_TCK used for all telemetry math")
    num_cpus: int = 1
    scheduler_backend: str = Field(
        default="none",
        description="Resolved backend: 'ebpf' | 'tracefs_fallback' | 'none'")
    scheduler_backend_version: str = ""
    fidelity_level: str = Field(
        default="none", description="'high' (ebpf) | 'reduced' (fallback) | 'none'")
    collector_failures: list[CollectorFailure] = Field(default_factory=list)
    workload_events: list[dict[str, Any]] = Field(
        default_factory=list, description="Workload launch metadata (id, type, pid, start)")
    status: str = "RUNNING"
