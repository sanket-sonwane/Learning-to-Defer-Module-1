"""Unit: timestamps, config, platform guard, context store."""
import pytest
from m1 import timebase
from m1.config import load_config
from m1.context.store import ContextStore
from m1.platform_guard import LinuxOnlyError


def test_monotonic_non_negative():
    assert timebase.monotonic_ns() > 0


def test_default_config_loads():
    from pathlib import Path
    cfg = load_config(Path(__file__).resolve().parents[2] / "configs" / "default.yaml")
    assert cfg.observation_window_ms == 2500
    assert "sched_switch" in cfg.sched_events


def test_linux_guard_on_windows():
    import m1.platform_guard as pg
    if pg.is_linux():
        pytest.skip("Linux host — guard passes")
    with pytest.raises(LinuxOnlyError):
        pg.require_linux("Test collector")


def test_context_start_end_resolve():
    store = ContextStore("EXP-T", "scn")
    e = store.start("USER_COMPILING", foreground_app="make", now_ns=1_000)
    store.end(now_ns=2_000)
    assert store.resolve(1_500) is e
    assert store.resolve(3_000) is None


def test_context_overlap_rejected():
    store = ContextStore("EXP-T", "scn")
    store.start("USER_IDLE", now_ns=1_000)
    with pytest.raises(RuntimeError):
        store.start("USER_ACTIVE", now_ns=1_100)


def test_context_bad_label():
    store = ContextStore("EXP-T", "scn")
    with pytest.raises(ValueError):
        store.start("USER_FLYING", now_ns=1_000)
