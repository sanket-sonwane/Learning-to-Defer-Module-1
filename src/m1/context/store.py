"""Controlled context store: start/end timestamped ground-truth events.

resolve(ts) returns the active context at monotonic time T (or None).
Overlapping intervals are rejected at insert; QA separately flags any
invalid/overlapping states found in stored raw data.
"""
from m1 import timebase
from m1.context.labels import validate_label
from m1.models.context import CONTEXT_SOURCE, ContextEvent


class ContextStore:
    def __init__(self, experiment_id: str = "", scenario_id: str = ""):
        self.experiment_id = experiment_id
        self.scenario_id = scenario_id
        self.events: list[ContextEvent] = []
        self._open: ContextEvent | None = None

    def start(self, label: str, foreground_app: str = "", app_state: str = "",
              now_ns: int | None = None) -> ContextEvent:
        validate_label(label)
        if self._open is not None:
            raise RuntimeError("A context is already open; end it before starting another.")
        ev = ContextEvent(
            experiment_id=self.experiment_id, label=label,  # type: ignore[arg-type]
            scenario_id=self.scenario_id, foreground_app=foreground_app,
            app_state=app_state, source=CONTEXT_SOURCE,
            start_monotonic_ns=now_ns if now_ns is not None else timebase.monotonic_ns())
        self._open = ev
        self.events.append(ev)
        return ev

    def end(self, now_ns: int | None = None) -> ContextEvent:
        if self._open is None:
            raise RuntimeError("No open context to end.")
        self._open.end_monotonic_ns = now_ns if now_ns is not None else timebase.monotonic_ns()
        if self._open.end_monotonic_ns < self._open.start_monotonic_ns:
            raise ValueError("Context end precedes start (clock error).")
        ev, self._open = self._open, None
        return ev

    def resolve(self, ts_ns: int) -> ContextEvent | None:
        """Context active at monotonic time T."""
        for ev in reversed(self.events):
            end = ev.end_monotonic_ns if ev.end_monotonic_ns is not None else ts_ns
            if ev.start_monotonic_ns <= ts_ns <= end:
                return ev
        return None
