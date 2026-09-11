"""Shared fixtures: synthetic Linux-like records (Windows-safe)."""
import subprocess
import sys
import textwrap
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


@pytest.fixture(scope="session")
def parquet_list_supported():
    """Probe whether pyarrow can decode list<double> parquet columns.

    On some hypervisors (KVM with AVX masked) the arrow wheel executes an
    illegal instruction while decoding nested list columns, SIGILL-ing the
    interpreter — an environment defect, not an M1 code bug. The dangerous
    read runs in a subprocess so a crash is detected (returncode -4/132)
    instead of killing the test run.
    """
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    probe = textwrap.dedent("""
        import pyarrow as pa, pyarrow.parquet as pq, tempfile, os
        f = tempfile.mktemp(suffix=".parquet")
        pq.write_table(pa.Table.from_pylist([{"hist": [0.1, 0.2]}]),
                       f, version="2.6")
        pq.read_table(f, columns=["hist"]).to_pylist()
        os.unlink(f)
    """)
    r = subprocess.run([sys.executable, "-c", probe],
                       capture_output=True, timeout=60)
    # Signal 4 (SIGILL) -> returncode -4 (132 on POSIX wait status).
    return r.returncode == 0


@pytest.fixture
def sim_tasks():
    from m1.sim.generator import make_task_snapshot
    return [make_task_snapshot(pid=1000, tid=1000, i=i) for i in range(12)]


@pytest.fixture
def sim_sched():
    from m1.sim.generator import make_sched_event
    return [make_sched_event(i) for i in range(20)]


@pytest.fixture
def sim_sys():
    from m1.sim.generator import make_system_snapshot
    return [make_system_snapshot(i) for i in range(12)]


@pytest.fixture
def sim_psi():
    from m1.sim.generator import make_psi_snapshot
    return [make_psi_snapshot(i) for i in range(3)]
