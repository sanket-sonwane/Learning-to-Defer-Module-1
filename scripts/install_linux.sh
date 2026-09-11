#!/usr/bin/env bash
# install_linux.sh — install ONLY M1 dependencies. Distribution-aware.
# BlackArch (Arch) -> pacman. Debian/Ubuntu -> apt. Fedora -> dnf. Else fail safe.
set -u
if [ "$(uname -s)" != "Linux" ]; then echo "FAIL: not Linux" >&2; exit 1; fi
if [ "$(id -u)" != "0" ] && ! command -v sudo >/dev/null; then echo "FAIL: need root or sudo" >&2; exit 1; fi
SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo"
APT_PKGS="clang llvm bpftool libbpf-dev python3 python3-pip linux-headers-generic"
PAC_PKGS="clang llvm bpftool libbpf python python-pip base-devel linux-headers"
DNF_PKGS="clang llvm bpftool libbpf-devel python3 python3-pip kernel-headers kernel-devel"
if [ -f /etc/os-release ]; then . /etc/os-release; fi
ID_LIKE="${ID_LIKE:-} ${ID:-}"
echo "Detected: ${NAME:-unknown} (ID=${ID:-?})"
install_pip() { "$SUDO" python3 -m pip install --requirement requirements-linux.txt || python3 -m pip install --user --requirement requirements-linux.txt; }
case "$ID_LIKE" in
  *arch*) "$SUDO" pacman -Sy --needed --noconfirm $PAC_PKGS && install_pip ;;
  *debian*|*ubuntu*) "$SUDO" apt-get update && "$SUDO" apt-get install -y $APT_PKGS && install_pip ;;
  *fedora*|*rhel*) "$SUDO" dnf install -y $DNF_PKGS && install_pip ;;
  *) echo "WARN: unknown distro; installing pip deps only. Install clang/llvm/bpftool/libbpf manually." >&2; install_pip ;;
esac
echo "Done. Re-run ./scripts/check_environment.sh"
