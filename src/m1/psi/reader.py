"""PSI reader for /proc/pressure/{cpu,memory,io}.

Captures `some avg10/avg60/avg300 total` per resource, plus `full` for
memory and io. CPU `full` is undefined system-wide and is NEVER collected.
Parse failures are explicit (missing_reason), never silent, never invented.
"""
from pathlib import Path
from m1 import timebase
from m1.platform_guard import require_linux
from m1.models.psi import PSIDirection, PSISnapshot

PRESSURE = Path("/proc/pressure")


def parse_psi_line(line: str) -> PSIDirection:
    """Parse one PSI line like 'some avg10=1.23 avg60=0.45 avg300=0.12 total=6789'."""
    d = PSIDirection()
    for tok in line.split()[1:]:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        try:
            if k == "avg10":
                d.avg10 = float(v)
            elif k == "avg60":
                d.avg60 = float(v)
            elif k == "avg300":
                d.avg300 = float(v)
            elif k == "total":
                d.total_us = int(v)
        except ValueError:
            continue
    return d


def read_resource(name: str) -> tuple[dict[str, PSIDirection], str | None]:
    """Read /proc/pressure/<name>. Returns ({direction: PSIDirection}, missing_reason)."""
    out: dict[str, PSIDirection] = {}
    try:
        text = (PRESSURE / name).read_text()
    except (FileNotFoundError, PermissionError) as e:
        return {}, f"{name}: {e}"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("some "):
            out["some"] = parse_psi_line(line)
        elif line.startswith("full ") and name in ("memory", "io"):
            # NOTE: cpu full is intentionally ignored (undefined system-wide).
            out["full"] = parse_psi_line(line)
    if "some" not in out:
        return out, f"{name}: no 'some' line found"
    return out, None


class PSIReader:
    def __init__(self, experiment_id: str = ""):
        self.experiment_id = experiment_id
        self.errors = 0

    def sample(self) -> PSISnapshot:
        require_linux("PSI collector")
        now = timebase.monotonic_ns()
        reasons: list[str] = []
        cpu, r = read_resource("cpu")
        if r:
            reasons.append(r)
        mem, r = read_resource("memory")
        if r:
            reasons.append(r)
        io, r = read_resource("io")
        if r:
            reasons.append(r)
        if reasons:
            self.errors += 1
        return PSISnapshot(
            timestamp_monotonic_ns=now, experiment_id=self.experiment_id,
            cpu_some=cpu.get("some", PSIDirection()),
            mem_some=mem.get("some", PSIDirection()),
            mem_full=mem.get("full", PSIDirection()),
            io_some=io.get("some", PSIDirection()),
            io_full=io.get("full", PSIDirection()),
            missing_reason="; ".join(reasons) if reasons else None,
        )
