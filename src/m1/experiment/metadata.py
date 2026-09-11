"""Machine/experiment metadata capture for reproducibility."""
import os
import platform
import subprocess
from pathlib import Path
from m1.models.experiment import MachineMetadata


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def detect_vm() -> str:
    info = _run(["systemd-detect-virt"]).lower()
    if info and info != "none":
        return info
    # Fallback hints
    try:
        if "hypervisor" in Path("/proc/cpuinfo").read_text().lower():
            return "hypervisor-flag-present"
    except OSError:
        pass
    return ""


def get_clk_tck() -> tuple[int, str]:
    """Query SC_CLK_TCK on Linux. Returns (value, source).

    source is 'sysconf' on Linux, 'default-100-nonlinux' elsewhere (Windows
    dev never produces authoritative telemetry, so the fallback is safe).
    """
    if hasattr(os, "sysconf") and "SC_CLK_TCK" in os.sysconf_names:
        try:
            return int(os.sysconf("SC_CLK_TCK")), "sysconf"
        except (ValueError, OSError):
            pass
    return 100, "default-100-nonlinux"


def collect_machine_metadata() -> MachineMetadata:
    mem_kb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    except OSError:
        pass
    cpu_model = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    distro = ""
    try:
        distro = Path("/etc/os-release").read_text().splitlines()[0]
    except OSError:
        distro = platform.platform()
    return MachineMetadata(
        distro=distro, kernel=platform.release(), arch=platform.machine(),
        cpu_model=cpu_model, num_cpus=os.cpu_count() or 0, mem_total_kb=mem_kb,
        vm_info=detect_vm(),
        btf_available=Path("/sys/kernel/btf/vmlinux").exists(),
        bpffs_mounted=Path("/sys/fs/bpf").exists(),
        psi_available=Path("/proc/pressure/cpu").exists(),
        clk_tck=get_clk_tck()[0],
        tool_versions={
            "python": platform.python_version(),
            "clang": _run(["clang", "--version"]).splitlines()[0] if _run(["clang", "--version"]) else "",
            "bpftool": _run(["bpftool", "--version"]),
            "git": _run(["git", "--rev-parse", "HEAD"])[:12],
        },
    )


def git_commit(repo: Path) -> str:
    return _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
