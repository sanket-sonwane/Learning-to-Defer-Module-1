# Linux Setup (BlackArch VM)

1. `git pull`
2. `./scripts/check_environment.sh` — read-only, never installs. Probes are
   tagged `[REQUIRED]` (any collection), `[EBPF]` (eBPF backend), `[OPTIONAL]`,
   `[FALLBACK]`. First run typically shows WARNs; fix FAILs before proceeding.
3. `sudo ./scripts/install_linux.sh` — Arch-aware (`pacman -Sy clang llvm
   bpftool libbpf python base-devel linux-headers` + `requirements-linux.txt`
   incl. pyarrow). Debian/Fedora handled; unknown distros install pip deps
   only + print the manual list.
4. `./scripts/build_bpf.sh` — reproducible BPF build, hard-fails (no silent
   fallback):
   - verifies `/sys/kernel/btf/vmlinux` (needs `CONFIG_DEBUG_INFO_BTF=y`),
   - generates `vmlinux.h` via `bpftool btf dump file … format c`
     (generated file, gitignored — never commit machine-specific copies),
   - compiles with `clang -O2 -g -target bpf -D__TARGET_ARCH_<x86|arm64>`,
   - verifies the `.o` exists.
   - Failure remediation: boot a BTF-enabled kernel, or run with `--no-bpf`
     (tracefs fallback, reduced fidelity, non-authoritative).
5. Re-run the checker until FAILs are gone. Remaining WARNs are actionable:
   - No BTF → CO-RE unavailable; `--no-bpf` fallback (fidelity recorded).
   - Privileges → `sudo` or `setcap cap_bpf,cap_perfmon+ep`.
6. Verify: `uname -r; ls /sys/kernel/btf/vmlinux; cat /proc/pressure/cpu; bpftool --version`.

VM note: VM timing/PSI/topology are NOT equivalent to native; `vm_info`
(detect-virt + hypervisor flag) is recorded per experiment — never claim
otherwise. `SC_CLK_TCK` is queried via `os.sysconf` on the host and stored
in `machine.json` + `collector_config.json`; all telemetry math uses that
exact value.
