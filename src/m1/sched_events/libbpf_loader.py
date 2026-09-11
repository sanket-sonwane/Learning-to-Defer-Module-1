"""ctypes wrapper around the system libbpf.so for loading the M1 BPF object.

Architecture (exactly one, no BCC mixing):

    sched_collect.bpf.o
            ↓  bpf_object__open_file / bpf_object__load
    BPF programs (on_switch, on_wakeup, on_wakeup_new, on_exec, on_exit)
            ↓  bpf_program__attach_tracepoint (all 5 required)
    tracepoints → BPF ring buffer (m1_rb) + drop counter map (m1_drops)
            ↓  ring_buffer__new / ring_buffer__poll
    Python callback → decode_record() → SchedulerEvent

Requires on the Linux VM: libbpf shared library (pacman: libbpf),
compiled sched_collect.bpf.o (scripts/build_bpf.sh), BTF, and privileges
(root or CAP_BPF/CAP_PERFMON). Import-safe on Windows (load failure is a
clear RuntimeError, never silent).
"""
import ctypes
import ctypes.util
from pathlib import Path
from typing import Callable

TRACEPOINTS: tuple[tuple[str, str], ...] = (
    ("sched", "sched_switch", "on_switch"),
    ("sched", "sched_wakeup", "on_wakeup"),
    ("sched", "sched_wakeup_new", "on_wakeup_new"),
    ("sched", "sched_process_exec", "on_exec"),
    ("sched", "sched_process_exit", "on_exit"),
)

_RING_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)


class LibbpfError(RuntimeError):
    pass


def _load_libbpf() -> ctypes.CDLL:
    for name in ("bpf",):
        path = ctypes.util.find_library(name)
        if path:
            return ctypes.CDLL(path)
    # Fallback to common sonames when find_library fails.
    for soname in ("libbpf.so.1", "libbpf.so.0", "libbpf.so"):
        try:
            return ctypes.CDLL(soname)
        except OSError:
            continue
    raise LibbpfError(
        "system libbpf.so not found. Run scripts/install_linux.sh (package: libbpf).")


class LibbpfLoader:
    """Loads a compiled .o via libbpf and polls its ring buffer."""

    def __init__(self, obj_path: Path, on_record: Callable[[bytes], None]):
        self.obj_path = Path(obj_path)
        if not self.obj_path.exists():
            raise FileNotFoundError(
                f"BPF object not found: {self.obj_path}. "
                "Build on the Linux VM with ./scripts/build_bpf.sh "
                "(or use the tracefs fallback with --no-bpf).")
        self._on_record = on_record
        self._lib: ctypes.CDLL | None = None
        self._obj: ctypes.c_void_p | None = None
        self._links: list[ctypes.c_void_p] = []
        self._ring: ctypes.c_void_p | None = None
        self._cb_ref: ctypes._CFuncPtr | None = None
        self.attached: list[str] = []
        self.failed: list[str] = []

    # -- lifecycle ---------------------------------------------------------
    def open_and_load(self) -> None:
        lib = _load_libbpf()
        self._lib = lib
        lib.bpf_object__open_file.restype = ctypes.c_void_p
        lib.bpf_object__open_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        lib.bpf_object__load.restype = ctypes.c_int
        lib.bpf_object__load.argtypes = [ctypes.c_void_p]
        lib.bpf_object__find_program_by_name.restype = ctypes.c_void_p
        lib.bpf_object__find_program_by_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.bpf_program__attach_tracepoint.restype = ctypes.c_void_p
        lib.bpf_program__attach_tracepoint.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.bpf_object__close.argtypes = [ctypes.c_void_p]

        obj = lib.bpf_object__open_file(str(self.obj_path).encode(), None)
        if not obj:
            raise LibbpfError(f"bpf_object__open_file failed for {self.obj_path}")
        self._obj = ctypes.c_void_p(obj)
        if lib.bpf_object__load(self._obj) != 0:
            self.close()
            raise LibbpfError(f"bpf_object__load failed for {self.obj_path} "
                              "(kernel too old? missing BTF? no privileges?)")
        for tp_cat, tp_name, prog_name in TRACEPOINTS:
            prog = lib.bpf_object__find_program_by_name(self._obj, prog_name.encode())
            if not prog:
                self.failed.append(prog_name)
                continue
            link = lib.bpf_program__attach_tracepoint(prog, tp_cat.encode(), tp_name.encode())
            # libbpf returns error-encoded pointers (large unsigned values) on failure.
            # A valid link is a small positive address; ERR_PTR values are very large.
            if not link or (isinstance(link, int) and link > 0x7FFFFFFFFFFFFFFF):
                self.failed.append(f"{prog_name}:{tp_name}")
                continue
            self._links.append(ctypes.c_void_p(link))
            self.attached.append(tp_name)

    def open_ring_buffer(self, map_name: str = "m1_rb") -> None:
        assert self._lib is not None and self._obj is not None, "call open_and_load() first"
        lib = self._lib
        lib.bpf_object__find_map_by_name.restype = ctypes.c_void_p
        lib.bpf_object__find_map_by_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.bpf_map__fd.restype = ctypes.c_int
        lib.bpf_map__fd.argtypes = [ctypes.c_void_p]
        lib.ring_buffer__new.restype = ctypes.c_void_p
        lib.ring_buffer__new.argtypes = [ctypes.c_int, _RING_CB, ctypes.c_void_p, ctypes.c_void_p]
        lib.ring_buffer__poll.restype = ctypes.c_int
        lib.ring_buffer__poll.argtypes = [ctypes.c_void_p, ctypes.c_int]

        m = lib.bpf_object__find_map_by_name(self._obj, map_name.encode())
        if not m:
            raise LibbpfError(f"ring buffer map {map_name!r} not found in {self.obj_path}")
        fd = lib.bpf_map__fd(ctypes.c_void_p(m))
        if fd < 0:
            raise LibbpfError(f"bad fd for map {map_name!r}")

        @_RING_CB
        def _cb(_ctx: object, data: int, size: int) -> int:
            try:
                buf = ctypes.string_at(data, size)
            except Exception:
                return 0
            try:
                self._on_record(buf)
            except Exception:
                pass
            return 0

        self._cb_ref = _cb  # keep alive
        ring = lib.ring_buffer__new(fd, _cb, None, None)
        if not ring:
            raise LibbpfError("ring_buffer__new failed")
        self._ring = ctypes.c_void_p(ring)

    def poll(self, timeout_ms: int = 100) -> int:
        """Poll ring buffer. Returns number of records processed, or raises on error."""
        assert self._lib is not None and self._ring is not None, "ring buffer not opened"
        ret = self._lib.ring_buffer__poll(self._ring, int(timeout_ms))
        if ret < 0:
            raise LibbpfError(f"ring_buffer__poll returned error: {ret}")
        return ret

    def read_drop_counter(self) -> int | None:
        """Best-effort read of m1_drops[0] via bpf_map lookup; None if unavailable."""
        try:
            lib = self._lib
            assert lib is not None and self._obj is not None
            lib.bpf_object__find_map_by_name.restype = ctypes.c_void_p
            lib.bpf_object__find_map_by_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.bpf_map__fd.restype = ctypes.c_int
            lib.bpf_map__fd.argtypes = [ctypes.c_void_p]
            lib.bpf_map_lookup_elem.restype = ctypes.c_int
            lib.bpf_map_lookup_elem.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
            m = lib.bpf_object__find_map_by_name(self._obj, b"m1_drops")
            if not m:
                return None
            fd = lib.bpf_map__fd(ctypes.c_void_p(m))
            key = ctypes.c_uint32(0)
            val = ctypes.c_uint64(0)
            if lib.bpf_map_lookup_elem(fd, ctypes.byref(key), ctypes.byref(val)) != 0:
                return None
            return int(val.value)
        except Exception:
            return None

    def close(self) -> None:
        """Close the loader. Attachment stats are preserved for post-stop reporting."""
        try:
            if self._lib is not None:
                self._lib.bpf_object__close.argtypes = [ctypes.c_void_p]
                if self._obj is not None:
                    self._lib.bpf_object__close(self._obj)
        except Exception:
            pass
        finally:
            self._obj = None
            self._links.clear()
            self._ring = None
            # Note: self.attached and self.failed are preserved for post-stop stats.
