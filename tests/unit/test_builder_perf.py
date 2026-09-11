"""Builder performance: bisect-optimized lookup vs correctness (item 23)."""
import time


def test_bisect_lookup_correctness():
    """_latest_at with bisect matches linear scan on random data."""
    from m1.builder.sync import _latest_at

    # Sorted rows by timestamp
    rows = [{"timestamp_monotonic_ns": i * 1000, "val": i} for i in range(1000)]

    # Linear reference
    def linear_latest(rows, ts):
        best = None
        for r in rows:
            if r["timestamp_monotonic_ns"] <= ts and (best is None or r["timestamp_monotonic_ns"] > best["timestamp_monotonic_ns"]):
                best = r
        return best

    # Test across query points
    cache = {}
    for ts in [0, 500, 999, 1000, 5000, 999000, 1000000]:
        bisect_result = _latest_at(rows, ts, _cache=cache)
        linear_result = linear_latest(rows, ts)
        assert (bisect_result or {}).get("val") == (linear_result or {}).get("val"), \
            f"ts={ts}: bisect={bisect_result}, linear={linear_result}"


def test_bisect_lookup_performance():
    """Bisect should handle 10k rows with 1000 queries in well under 1 second."""
    from m1.builder.sync import _latest_at

    rows = [{"timestamp_monotonic_ns": i * 100, "val": i} for i in range(10_000)]
    queries = [i * 100 for i in range(1000)]

    cache = {}
    start = time.perf_counter()
    for ts in queries:
        _latest_at(rows, ts, _cache=cache)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"10k rows x 1k queries took {elapsed:.3f}s (threshold: 1.0s)"
    print(f"  bisect: 10k rows x 1k queries in {elapsed:.4f}s")


def test_bisect_lookup_empty_and_single():
    """Edge cases: empty list and single-element list."""
    from m1.builder.sync import _latest_at
    cache = {}
    assert _latest_at([], 100, _cache=cache) is None
    single = [{"timestamp_monotonic_ns": 50, "val": 0}]
    cache2 = {}
    assert _latest_at(single, 100, _cache=cache2)["val"] == 0
    assert _latest_at(single, 30, _cache=cache2) is None
