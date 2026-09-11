"""F7: TracefsFallback -- trace line parsing and stats."""
import pytest
from m1.sched_events.fallback import (
    TracefsFallback, _TRACE_RE, _SWITCH_RE, _WAKEUP_RE, _EVENT_MAP)


def test_trace_re_matches_switch():
    line = ("python3-1234 [001] .... 12345.678901: sched_switch: "
            "prev_comm=bash prev_pid=1234 prev_prio=120 prev_state=S "
            "==> next_comm=python3 next_pid=1235 next_prio=120")
    m = _TRACE_RE.match(line)
    assert m is not None
    assert m.group("comm") == "python3"
    assert m.group("pid") == "1234"
    assert m.group("cpu") == "001"
    assert m.group("event") == "sched_switch"
    assert "prev_comm=bash" in m.group("fields")


def test_switch_fields_parsed():
    fields = ("prev_comm=bash prev_pid=1234 prev_prio=120 prev_state=S "
              "==> next_comm=python3 next_pid=1235 next_prio=120")
    m = _SWITCH_RE.search(fields)
    assert m is not None
    assert m.group("prev_comm") == "bash"
    assert m.group("prev_pid") == "1234"
    assert m.group("next_comm") == "python3"
    assert m.group("next_pid") == "1235"


def test_wakeup_fields_parsed():
    fields = "comm=task1 pid=5678 prio=120 target_cpu=003"
    m = _WAKEUP_RE.search(fields)
    assert m is not None
    assert m.group("comm") == "task1"
    assert m.group("pid") == "5678"
    assert m.group("prio") == "120"


def test_event_map_completeness():
    expected = {"sched_switch", "sched_wakeup", "sched_wakeup_new",
                "sched_process_exec", "sched_process_exit"}
    assert set(_EVENT_MAP.keys()) == expected


def test_parse_line_switch():
    fb = TracefsFallback.__new__(TracefsFallback)
    fb.experiment_id = "EXP-T"
    fb.events = ("sched_switch",)
    fb.received = fb.parsed = fb.malformed = fb.unknown = fb.errors = 0
    fb._events_buf = []
    fb._lock = __import__("threading").Lock()
    line = ("python3-1234 [001] .... 12345.678901: sched_switch: "
            "prev_comm=bash prev_pid=1234 prev_prio=120 prev_state=S "
            "==> next_comm=python3 next_pid=1235 next_prio=120")
    fb._parse_line(line)
    assert fb.parsed == 1
    assert len(fb._events_buf) == 1
    ev = fb._events_buf[0]
    assert ev.event_type == "sched_switch"
    assert ev.next_pid == 1235
    assert ev.prev_pid == 1234


def test_parse_line_malformed():
    fb = TracefsFallback.__new__(TracefsFallback)
    fb.experiment_id = "EXP-T"
    fb.events = ()
    fb.received = fb.parsed = fb.malformed = fb.unknown = fb.errors = 0
    fb._events_buf = []
    fb._lock = __import__("threading").Lock()
    fb._parse_line("not a valid trace line")
    assert fb.malformed == 1


def test_parse_line_unknown_event():
    fb = TracefsFallback.__new__(TracefsFallback)
    fb.experiment_id = "EXP-T"
    fb.events = ()
    fb.received = fb.parsed = fb.malformed = fb.unknown = fb.errors = 0
    fb._events_buf = []
    fb._lock = __import__("threading").Lock()
    line = ("task-1 [000] .... 1.0: sched_unknown_event: foo=bar")
    fb._parse_line(line)
    assert fb.unknown == 1


def test_stats_structure():
    fb = TracefsFallback.__new__(TracefsFallback)
    fb.experiment_id = "EXP-T"
    fb.events = ("sched_switch", "sched_wakeup")
    fb.received = 10
    fb.parsed = 8
    fb.malformed = 1
    fb.unknown = 1
    fb.errors = 0
    s = fb.stats()
    assert s["backend"] == "tracefs_fallback"
    assert s["fidelity"] == "reduced"
    assert s["received"] == 10
    assert s["parsed"] == 8
    assert s["transport"] == "tracefs-fallback"
