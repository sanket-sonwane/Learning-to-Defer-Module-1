"""Blocker 8: missing counters are never zero; deltas are generation-safe."""
from m1.telemetry.features import cpu_util_pct, cs_rate_per_s, delta_or_none, io_rate_bps


def test_missing_counter_semantics():
    a: dict = {}
    # 1. valid -> valid
    assert delta_or_none(150, 100, a) == 50
    # 2. missing -> valid
    assert delta_or_none(150, None, a) is None
    # 3. valid -> missing
    assert delta_or_none(None, 100, a) is None
    # 4. missing -> missing
    assert delta_or_none(None, None, a) is None
    # 5. negative delta (wrap/reuse) -> None + anomaly, never a rate
    assert delta_or_none(90, 100, a) is None
    assert a["negative_deltas"] == 1
    assert io_rate_bps(delta_or_none(90, 100), 1.0) is None
    # 6. counter reset to zero (e.g. task restart) -> None + anomaly
    assert delta_or_none(0, 10_000, a) is None
    assert a["negative_deltas"] == 2
    # Derived math honors the same semantics end to end.
    assert cpu_util_pct(80, 20, 1.0, 1, 100) == 100.0
    assert cpu_util_pct(None, 20, 1.0, 1, 100) is None
    assert cpu_util_pct(-5, 20, 1.0, 1, 100) is None
    assert cs_rate_per_s(None, 1.0) is None
