"""Guard for Linux-only functionality.

Authoritative M1 collection requires Linux (/proc, PSI, tracepoints, eBPF).
Windows may only run unit tests with mocks/fixtures and the sim layer.
"""
import platform


def is_linux() -> bool:
    return platform.system() == "Linux"


class LinuxOnlyError(RuntimeError):
    pass


def require_linux(component: str) -> None:
    """Raise a clear error when a Linux-only collector runs on non-Linux."""
    if not is_linux():
        raise LinuxOnlyError(
            f"{component} requires Linux /proc interfaces "
            f"(running on {platform.system()}). "
            "Use the sim layer (m1.sim.generator) for Windows development/tests only."
        )
