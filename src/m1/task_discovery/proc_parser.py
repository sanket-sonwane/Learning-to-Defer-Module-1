"""Parsing of Linux /proc task interfaces.

Correctness notes:
- /proc/<pid>/stat: comm is "(...)" and MAY contain spaces/parens. Parse by
  finding the LAST ')' then splitting the remainder. Field 22 (1-indexed over
  the full record) is starttime; we recompute indexes after comm.
- /proc/<pid>/status: voluntary_ctxt_switches / nonvoluntary_ctxt_switches.
- /proc/<pid>/io: rchar/wchar/read_bytes/write_bytes (cumulative counters).
- Threads: /proc/<pid>/task/<tid>/stat mirrors the same layout.
- Tasks may exit between readdir and read (FileNotFoundError) — caller treats
  that as EXIT, never a crash.
"""
import os
from pathlib import Path

PROC = Path("/proc")


def parse_stat_text(text: str) -> dict:
    """Parse one /proc stat line into named fields.

    Returns dict with: pid, comm, state, ppid, pgrp, session, tty_nr, tpgid,
    flags, minflt..cstime (raw ints), priority, nice, num_threads, starttime,
    vsize, rss, processor, ... See proc(5).
    """
    text = text.strip()
    lparen = text.index("(")
    rparen = text.rindex(")")
    pid = int(text[:lparen].strip())
    comm = text[lparen + 1:rparen]
    rest = text[rparen + 1:].split()
    # rest[0] = state (field 3), rest[1] = ppid (field 4), ...
    if len(rest) < 38:
        raise ValueError(f"short /proc stat record: {text[:120]!r}")
    get = lambda i: rest[i]  # noqa: E731
    return {
        "pid": pid,
        "comm": comm,
        "state": get(0),
        "ppid": int(get(1)),
        "pgrp": int(get(2)),
        "priority": int(get(15)),       # field 18
        "nice": int(get(16)),           # field 19
        "num_threads": int(get(17)),    # field 20
        "starttime": int(get(19)),      # field 22
        "vsize": int(get(20)),          # field 23
        "rss": int(get(21)),            # field 24
        "processor": int(get(36)),      # field 39
        "utime": int(get(11)),          # field 14
        "stime": int(get(12)),          # field 15
    }


def parse_status_text(text: str) -> dict:
    """Extract voluntary/nonvoluntary ctxt switches and VmRSS from status text."""
    out: dict = {"voluntary_ctxt_switches": None, "nonvoluntary_ctxt_switches": None,
                 "VmRSS_kb": None, "TGID": None, "State": None}
    for line in text.splitlines():
        if line.startswith("voluntary_ctxt_switches:"):
            out["voluntary_ctxt_switches"] = int(line.split()[1])
        elif line.startswith("nonvoluntary_ctxt_switches:"):
            out["nonvoluntary_ctxt_switches"] = int(line.split()[1])
        elif line.startswith("VmRSS:"):
            out["VmRSS_kb"] = int(line.split()[1])
        elif line.startswith("TGID:"):
            out["TGID"] = int(line.split()[1])
        elif line.startswith("State:"):
            out["State"] = line.split()[1]
    return out


def parse_io_text(text: str) -> dict:
    """Parse /proc/<pid>/io cumulative counters (all optional)."""
    out: dict = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        if k in ("rchar", "wchar", "read_bytes", "write_bytes",
                 "syscr", "syscw", "cancelled_write_bytes"):
            try:
                out[k] = int(v.strip())
            except ValueError:
                pass
    return out


def read_affinity(pid: int) -> list[int] | None:
    """CPU affinity via os.sched_affinity (Linux only); None when unavailable."""
    try:
        return sorted(os.sched_affinity(pid))
    except (AttributeError, OSError, PermissionError):
        return None
