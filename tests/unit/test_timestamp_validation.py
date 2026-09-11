"""F2: Timestamp validation groups by task_id, not globally sorted."""
from m1.qa.checks import check_timestamps


def _row(task_id, pid, ts):
    return {"task_id": task_id, "pid": pid, "timestamp_monotonic_ns": ts,
            "schema_version": "1.0.0"}


def test_interleaved_pids_no_false_retrograde():
    """Interleaved PIDs with valid per-task monotonicity must PASS."""
    rows = [
        _row("100:1", 100, 1_000), _row("200:1", 200, 1_100),
        _row("100:1", 100, 1_200), _row("200:1", 200, 1_300),
        _row("100:1", 100, 1_400), _row("200:1", 200, 1_500),
    ]
    check = check_timestamps(rows, [])
    assert check.passed, f"should pass: {check.detail}"


def test_out_of_order_within_one_task():
    """Out-of-order timestamps within one task generation must FAIL."""
    rows = [
        _row("100:1", 100, 2_000_000_000),
        _row("100:1", 100, 500_000_000),  # retrograde > 1s
    ]
    check = check_timestamps(rows, [])
    assert not check.passed
    assert "retrograde=1" in check.detail


def test_valid_global_interleaving():
    """Valid global interleaving of multiple tasks must PASS."""
    rows = [
        _row("100:1", 100, 1_000), _row("200:1", 200, 1_050),
        _row("300:1", 300, 1_100), _row("100:1", 100, 1_150),
        _row("200:1", 200, 1_200), _row("300:1", 300, 1_250),
    ]
    check = check_timestamps(rows, [])
    assert check.passed


def test_missing_timestamp():
    """Missing timestamp_monotonic_ns must be counted."""
    rows = [{"task_id": "100:1", "pid": 100}]  # no timestamp
    check = check_timestamps(rows, [])
    assert not check.passed
    assert "missing=1" in check.detail


def test_nonpositive_timestamp():
    """Zero or negative timestamps must be detected."""
    rows = [_row("100:1", 100, 0), _row("100:1", 100, -100)]
    check = check_timestamps(rows, [])
    assert not check.passed
    assert "nonpositive=2" in check.detail


def test_observation_negative_duration():
    """Negative recent_cpu_runtime_ticks in observations must FAIL."""
    obs = [{"timestamp_monotonic_ns": 1000, "recent_cpu_runtime_ticks": -5}]
    check = check_timestamps([], obs)
    assert not check.passed


def test_duplicate_timestamps_allowed():
    """Duplicate timestamps within a task are allowed (same tick)."""
    rows = [
        _row("100:1", 100, 1_000),
        _row("100:1", 100, 1_000),  # duplicate OK
    ]
    check = check_timestamps(rows, [])
    assert check.passed
