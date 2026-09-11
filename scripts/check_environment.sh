#!/usr/bin/env bash
# check_environment.sh — inspect the actual Linux environment. Read-only.
# Reports PASS / WARN / FAIL with actionable explanations. NEVER installs.
#
# Probe levels:
#   [REQUIRED]  required for authoritative M1 collection
#   [EBPF]      required for the libbpf/eBPF backend
#   [OPTIONAL]  useful but not required
#   [FALLBACK]  only relevant to a reduced-fidelity fallback mode
#
# Exit status:
#   0 = no FAIL conditions (WARN is allowed)
#   1 = one or more FAIL conditions
#
# This script intentionally does not modify the machine.

set -u

PASS=0
WARN=0
FAIL=0

say() {
    local lvl="$1"
    shift
    echo "[$lvl] $*"

    case "$lvl" in
        PASS) PASS=$((PASS + 1)) ;;
        WARN) WARN=$((WARN + 1)) ;;
        FAIL) FAIL=$((FAIL + 1)) ;;
    esac
}

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

TRACEFS="/sys/kernel/tracing"
DEBUG_TRACING="/sys/kernel/debug/tracing"

BPF_OBJECT="$PROJECT_ROOT/src/m1/sched_events/bpf/sched_collect.bpf.o"

# Prefer the project virtual environment whenever it exists.
if [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    PYTHON_BIN=""
fi

# Required scheduler tracepoints for M1.3.
REQUIRED_SCHED_EVENTS=(
    sched_switch
    sched_wakeup
    sched_wakeup_new
    sched_process_exec
    sched_process_exit
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check_command() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1
}

have_root_or_bpf_caps() {
    if [ "$(id -u)" -eq 0 ]; then
        return 0
    fi

    if ! check_command capsh; then
        return 1
    fi

    capsh --print 2>/dev/null |
        grep -qiE 'cap_bpf|cap_sys_admin|cap_perfmon'
}

# Run a read-only test through non-interactive sudo when available.
# Never prompts for a password.
sudo_readonly_test() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return $?
    fi

    if ! check_command sudo; then
        return 127
    fi

    sudo -n "$@"
}

# ---------------------------------------------------------------------------
# Operating system / base filesystem
# ---------------------------------------------------------------------------

if [ "$(uname -s)" != "Linux" ]; then
    say FAIL "[REQUIRED] Not Linux ($(uname -s)). M1 collection requires Linux."
else
    say PASS "[REQUIRED] Linux: $(uname -r)"
fi

if [ -d /proc ]; then
    say PASS "[REQUIRED] /proc present"
else
    say FAIL "[REQUIRED] /proc missing — cannot collect tasks (remediation: boot a standard Linux kernel with procfs)"
fi

if [ -d /sys ]; then
    say PASS "[REQUIRED] /sys present"
else
    say FAIL "[REQUIRED] /sys missing — kernel capability detection unavailable"
fi

# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------

if [ -f /proc/pressure/cpu ] &&
   [ -f /proc/pressure/memory ] &&
   [ -f /proc/pressure/io ]; then
    say PASS "[REQUIRED] PSI available"
else
    say FAIL "[REQUIRED] PSI missing (need CPU/memory/io pressure files; authoritative M1 requires PSI)"
fi

# ---------------------------------------------------------------------------
# BTF / bpffs / compiler / bpftool / objdump
# ---------------------------------------------------------------------------

if [ -f /sys/kernel/btf/vmlinux ]; then
    say PASS "[EBPF] BTF present (CO-RE ok)"
else
    say FAIL "[EBPF] BTF missing at /sys/kernel/btf/vmlinux (remediation: boot a BTF-enabled kernel)"
fi

if mountpoint -q /sys/fs/bpf 2>/dev/null; then
    say PASS "[EBPF] bpffs mounted"
elif [ -d /sys/fs/bpf ]; then
    say FAIL "[EBPF] /sys/fs/bpf exists but bpffs is not mounted (remediation: mount -t bpf bpf /sys/fs/bpf)"
else
    say FAIL "[EBPF] /sys/fs/bpf missing (remediation: mount -t bpf bpf /sys/fs/bpf)"
fi

if check_command clang; then
    say PASS "[EBPF] clang: $(clang --version 2>/dev/null | head -1)"
else
    say FAIL "[EBPF] clang missing (remediation: scripts/install_linux.sh)"
fi

if check_command bpftool; then
    say PASS "[EBPF] bpftool: $(bpftool --version 2>/dev/null | head -1)"
else
    say FAIL "[EBPF] bpftool missing (remediation: scripts/install_linux.sh)"
fi

if check_command llvm-objdump; then
    say PASS "[OPTIONAL] llvm-objdump present"
else
    say WARN "[OPTIONAL] llvm-objdump missing (only used for optional object inspection)"
fi

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------

if [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ]; then
    PYTHON_VERSION="$("$PYTHON_BIN" --version 2>/dev/null || true)"
    say PASS "[REQUIRED] python3: $PYTHON_VERSION"
else
    say FAIL "[REQUIRED] python3 missing (remediation: create/install the M1 .venv)"
fi

if [ -n "$PYTHON_BIN" ] &&
   "$PYTHON_BIN" -c "import yaml, pydantic" >/dev/null 2>&1; then
    say PASS "[REQUIRED] python deps (yaml, pydantic)"
else
    say FAIL "[REQUIRED] python deps missing (remediation: $PROJECT_ROOT/.venv/bin/python3 -m pip install -r requirements-base.txt)"
fi

if [ -n "$PYTHON_BIN" ] &&
   "$PYTHON_BIN" -c "import pyarrow" >/dev/null 2>&1; then
    say PASS "[REQUIRED] pyarrow (Parquet)"
else
    say FAIL "[REQUIRED] pyarrow missing (remediation: $PROJECT_ROOT/.venv/bin/python3 -m pip install -r requirements-linux.txt; JSONL fallback is not the authoritative Parquet path)"
fi

# ---------------------------------------------------------------------------
# libbpf
# ---------------------------------------------------------------------------

if [ -n "$PYTHON_BIN" ] &&
   "$PYTHON_BIN" -c "import ctypes.util; raise SystemExit(0 if ctypes.util.find_library('bpf') else 1)" \
       >/dev/null 2>&1; then
    say PASS "[EBPF] libbpf.so found"
else
    say FAIL "[EBPF] libbpf.so not found (remediation: install libbpf / libbpf-dev)"
fi

# ---------------------------------------------------------------------------
# Scheduler tracepoints
# ---------------------------------------------------------------------------

check_sched_tracepoints() {
    local base=""
    local event=""
    local missing=0

    if [ -d "$TRACEFS" ]; then
        base="$TRACEFS"
    elif [ -d "$DEBUG_TRACING" ]; then
        base="$DEBUG_TRACING"
        say WARN "[FALLBACK] canonical tracefs path unavailable; tracing hierarchy found under debugfs"
    else
        say FAIL "[REQUIRED] tracefs/debugfs tracing hierarchy unavailable (remediation: ensure tracefs is mounted)"
        return
    fi

    # Direct access: normal privileged case or a user with suitable tracefs ACLs.
    if [ -d "$base/events/sched" ]; then
        for event in "${REQUIRED_SCHED_EVENTS[@]}"; do
            if [ ! -f "$base/events/sched/$event/format" ]; then
                missing=1
                say FAIL "[REQUIRED] missing scheduler tracepoint: sched:$event"
            fi
        done

        if [ "$missing" -eq 0 ]; then
            say PASS "[REQUIRED] all five scheduler tracepoints present"
        fi
        return
    fi

    # A root-only tracefs tree can look absent to an unprivileged shell.
    # Probe it read-only via non-interactive sudo when possible.
    if sudo_readonly_test test -d "$base/events/sched" >/dev/null 2>&1; then
        for event in "${REQUIRED_SCHED_EVENTS[@]}"; do
            if ! sudo_readonly_test test -f "$base/events/sched/$event/format" >/dev/null 2>&1; then
                missing=1
                say FAIL "[REQUIRED] missing scheduler tracepoint: sched:$event"
            fi
        done

        if [ "$missing" -eq 0 ]; then
            say WARN "[REQUIRED] all five scheduler tracepoints present, but tracefs requires elevated access; run authoritative collection with sudo"
        fi
        return
    fi

    if [ -d "$base" ]; then
        say WARN "[REQUIRED] tracefs is mounted but scheduler events are inaccessible to the current user; run authoritative checker/collector with sudo"
    else
        say FAIL "[REQUIRED] tracing hierarchy unavailable"
    fi
}

check_sched_tracepoints

# ---------------------------------------------------------------------------
# BPF object
# ---------------------------------------------------------------------------

if [ -f "$BPF_OBJECT" ]; then
    say PASS "[EBPF] BPF object built: $BPF_OBJECT"
else
    say WARN "[EBPF] BPF object missing (remediation: ./scripts/build_bpf.sh on this machine)"
fi

# ---------------------------------------------------------------------------
# Privileges
# ---------------------------------------------------------------------------

if have_root_or_bpf_caps; then
    say PASS "[EBPF] privileges ok (root or suitable BPF/admin capability)"
else
    say WARN "[EBPF] current shell lacks root/BPF capabilities; use sudo for authoritative BPF collection"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "---"

KERNEL="$(uname -r 2>/dev/null || echo unknown)"
CPUS="$(nproc 2>/dev/null || echo '?')"

if check_command systemd-detect-virt; then
    VIRT="$(systemd-detect-virt 2>/dev/null || echo unknown)"
else
    VIRT="unknown"
fi

echo "Kernel: $KERNEL | CPUs: $CPUS | Virt: $VIRT"
echo "Python: $PYTHON_BIN"
echo "Result: PASS=$PASS WARN=$WARN FAIL=$FAIL"

if [ "$FAIL" -gt 0 ]; then
    echo "OVERALL: FAIL"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo "OVERALL: WARN"
    exit 0
else
    echo "OVERALL: PASS"
    exit 0
fi
