"""F3: Impossible-timestamp QA is mode-aware (live vs replay)."""
from m1.qa.checks import check_impossible_timestamps, run_all


def _row(ts):
    return {"task_id": "100:1", "pid": 100, "timestamp_monotonic_ns": ts,
            "schema_version": "1.0.0"}


def test_replay_mode_uses_data_bounds():
    """Replay mode derives horizon from data, not wall-clock."""
    old_ts = 1_000_000_000_000  # 1000s -- plausible for a past experiment
    rows = [_row(old_ts), _row(old_ts + 1_000_000_000)]
    check = check_impossible_timestamps(rows, [], [], mode="replay")
    assert check.passed, f"replay should not flag old data: {check.detail}"
    assert "mode=replay" in check.detail


def test_live_mode_flags_far_future():
    """Live mode flags timestamps far in the future."""
    import time
    future = time.monotonic_ns() + 10 * 3_600_000_000_000  # 10h ahead
    rows = [_row(future)]
    check = check_impossible_timestamps(rows, [], [], mode="live")
    assert not check.passed
    assert "far_future=1" in check.detail


def test_run_all_forwards_mode():
    """run_all forwards mode to check_impossible_timestamps."""
    rows = [_row(1_000_000_000)]
    rep = run_all("EXP-T", rows, [], [], [], [], [], mode="replay")
    for c in rep.checks:
        if c.name == "impossible_timestamps":
            assert "mode=replay" in c.detail
            break
    else:
        assert False, "impossible_timestamps check not found"
