#!/usr/bin/env bash
# run_collector.sh — THIN orchestration layer only (no collector implementation here).
#
# Flow:
#   parse args
#   -> resolve project root
#   -> validate scenario
#   -> run environment preflight through bash
#   -> optional dry-run exit
#   -> launch the project Python interpreter
#   -> controller handles collection, teardown, QA, and summary
#
# Authoritative M1 collection is Linux-only.
#
# This script does not install packages or modify the host environment.

set -u

SCENARIO="cpu_intensive"
DURATION="60"
NO_BPF=""
DRY_RUN=""

# ---------------------------------------------------------------------------
# Resolve project root and script directory
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Prefer the project's virtual environment for deterministic Python execution.
if [ -x "$ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "FAIL: python3 not found and project .venv does not exist." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --scenario)
            if [ $# -lt 2 ]; then
                echo "FAIL: --scenario requires a scenario name." >&2
                exit 2
            fi
            SCENARIO="$2"
            shift 2
            ;;
        --duration)
            if [ $# -lt 2 ]; then
                echo "FAIL: --duration requires seconds." >&2
                exit 2
            fi
            DURATION="$2"
            shift 2
            ;;
        --no-bpf)
            NO_BPF="--no-bpf"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 --scenario NAME --duration SECS [--no-bpf] [--dry-run]"
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Basic validation
# ---------------------------------------------------------------------------

if [ "$(uname -s)" != "Linux" ]; then
    echo "FAIL: run_collector.sh requires Linux (authoritative collection)." >&2
    exit 1
fi

SCENARIO_FILE="$ROOT/configs/scenarios/${SCENARIO}.yaml"

if [ ! -f "$SCENARIO_FILE" ]; then
    echo "FAIL: unknown scenario '$SCENARIO'. Valid scenarios:" >&2
    if [ -d "$ROOT/configs/scenarios" ]; then
        ls "$ROOT/configs/scenarios" | sed 's/\.yaml$//' >&2
    else
        echo "  <scenario directory missing>" >&2
    fi
    exit 2
fi

# Validate duration is numeric and positive.
if ! "$PYTHON_BIN" - "$DURATION" <<'PY'
import sys

try:
    value = float(sys.argv[1])
except (TypeError, ValueError):
    raise SystemExit(1)

if value <= 0:
    raise SystemExit(1)
PY
then
    echo "FAIL: duration must be a positive number of seconds; got '$DURATION'." >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# M1 preflight
# ---------------------------------------------------------------------------

echo "== M1 preflight =="

# IMPORTANT:
# Invoke the checker through bash instead of executing it directly.
# This avoids dependence on the executable bit of check_environment.sh and
# also works correctly on environments where direct script execution is
# restricted.
bash "$ROOT/scripts/check_environment.sh" || {
    echo "Environment FAIL — fix issues above first." >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

if [ -n "$DRY_RUN" ]; then
    echo "DRY RUN ok: scenario=$SCENARIO duration=$DURATION no_bpf=${NO_BPF:-no}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

cleanup() {
    echo
    echo "Interrupted — controller handles safe teardown."
}

trap cleanup INT TERM

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Make project root explicit for the controller. Do not depend on the caller's
# current working directory.
cd "$ROOT"

# ---------------------------------------------------------------------------
# Launch ExperimentController
# ---------------------------------------------------------------------------

"$PYTHON_BIN" - "$SCENARIO" "$DURATION" $NO_BPF <<'PY'
import sys
from pathlib import Path

from m1.experiment.controller import ExperimentController

scenario = sys.argv[1]
duration = float(sys.argv[2])
no_bpf = "--no-bpf" in sys.argv[3:]

root = Path.cwd()

ctl = ExperimentController(
    root,
    scenario,
    duration,
    no_bpf=no_bpf,
)

summary = ctl.run()

print(
    "Experiment:",
    summary["experiment_id"],
    "Verdict:",
    summary["verdict"],
)
PY
