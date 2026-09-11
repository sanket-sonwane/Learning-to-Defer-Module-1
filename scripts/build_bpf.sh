#!/usr/bin/env bash
# build_bpf.sh — reproducible BPF object build. Hard-fails, never falls back.
#
#   Linux kernel BTF → vmlinux.h → clang → sched_collect.bpf.o
#
# vmlinux.h is GENERATED (gitignored), never committed machine-specific.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BPF_DIR="$ROOT/src/m1/sched_events/bpf"
SRC="$BPF_DIR/sched_collect.bpf.c"
OBJ="$BPF_DIR/sched_collect.bpf.o"
VMH="$BPF_DIR/vmlinux.h"

[ "$(uname -s)" = "Linux" ] || { echo "FAIL: build_bpf.sh requires Linux" >&2; exit 1; }
[ -f /sys/kernel/btf/vmlinux ] || {
  echo "FAIL: no /sys/kernel/btf/vmlinux (kernel needs CONFIG_DEBUG_INFO_BTF=y)." >&2
  echo "Remediation: boot a BTF-enabled kernel, or run with --no-bpf (fallback, reduced fidelity)." >&2
  exit 1; }
command -v bpftool >/dev/null || { echo "FAIL: bpftool missing. Run scripts/install_linux.sh" >&2; exit 1; }
command -v clang >/dev/null || { echo "FAIL: clang missing. Run scripts/install_linux.sh" >&2; exit 1; }
command -v llvm-objdump >/dev/null || { echo "FAIL: llvm-objdump missing. Run scripts/install_linux.sh" >&2; exit 1; }

echo "== generating vmlinux.h from BTF =="
bpftool btf dump file /sys/kernel/btf/vmlinux format c > "$VMH"
[ -s "$VMH" ] || { echo "FAIL: vmlinux.h generation produced empty output" >&2; exit 1; }

echo "== compiling BPF object =="
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) TARGET_ARCH="x86";; aarch64) TARGET_ARCH="arm64";;
  *) echo "FAIL: unsupported arch $ARCH for -D__TARGET_ARCH_" >&2; exit 1;;
esac
clang -O2 -g -target bpf -D__TARGET_ARCH_${TARGET_ARCH} -Wall -c "$SRC" -o "$OBJ"
[ -f "$OBJ" ] || { echo "FAIL: clang produced no object file" >&2; exit 1; }

echo "== verifying sections =="
# Validate EXACT ELF sections: tracepoint/<category>/<name> must be present.
# (Program FUNCTIONS are on_switch etc., but the ELF SECTION is the tracepoint.)
miss=0
objdump="$(llvm-objdump -h "$OBJ" 2>/dev/null || true)"
for sec in \
  "tracepoint/sched/sched_switch" \
  "tracepoint/sched/sched_wakeup" \
  "tracepoint/sched/sched_wakeup_new" \
  "tracepoint/sched/sched_process_exec" \
  "tracepoint/sched/sched_process_exit"; do
  if ! printf '%s\n' "$objdump" | grep -Fq "$sec"; then
    echo "FAIL: section '$sec' not found in $OBJ" >&2
    miss=1
  fi
done
if [ "$miss" -ne 0 ]; then
  echo "FAIL: BPF object missing required tracepoint sections" >&2
  exit 1
fi
echo "OK: all 5 tracepoint sections verified in $OBJ"
echo "OK: $OBJ ($(stat -c%s "$OBJ") bytes), vmlinux.h ($(stat -c%s "$VMH") bytes)"
