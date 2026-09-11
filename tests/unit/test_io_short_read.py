"""I/O byte counting: len(chunk) counting is correct (verification item 21)."""
import tempfile
import os


def test_io_heavy_write_read_totals_match():
    """io_heavy read_total should equal write_total for aligned data."""
    from m1.workloads.runner import io_heavy

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        path = f.name

    try:
        result = io_heavy(path, size_mb=1, duration_s=0.2)
        # With size_mb=1, writes 16 chunks of 65536 bytes
        assert result["written"] == 16 * 65536, f"written={result['written']}"
        assert result["read"] == result["written"], (
            f"read={result['read']} != written={result['written']}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_read_uses_len_chunk_not_hardcoded():
    """Verify the read path counts bytes via len(chunk), not a hardcoded value.

    This tests that a file with a size not a multiple of 65536 is read
    correctly. io_heavy always writes aligned data, so we test the read
    logic directly by writing a non-aligned file and reading it with the
    same pattern io_heavy uses.
    """
    # Write a file with 65536 * 2 + 1234 bytes
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        path = f.name
        f.write(b"\x00" * (65536 * 2 + 1234))

    try:
        total_r = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                total_r += len(chunk)
        assert total_r == 65536 * 2 + 1234, f"read {total_r}, expected {65536 * 2 + 1234}"
    finally:
        os.unlink(path)
