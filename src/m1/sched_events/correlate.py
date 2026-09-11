"""PID/TID → persistent task_id correlation for scheduler events.

The ring-buffer event carries PID/TID but no starttime generation. Resolve it
against the task lifecycle registry: the generation whose [first_seen, exit)
interval contains the event timestamp wins. Events arriving after an exit and
before a reuse are `unresolved` (counted, never attributed to the wrong
generation). Old events must never be attributed to a reused PID's new task.
"""
from m1.task_discovery.identity import make_task_id


class GenerationTracker:
    """Intervals of (pid_or_tid -> task_id) keyed by monotonic time."""

    def __init__(self):
        # pid -> list of (start_seen_ns, end_seen_ns|None, task_id, starttime)
        self._intervals: dict[int, list[tuple[int, int | None, str, int | None]]] = {}
        self.unresolved = 0

    def observe(self, pid: int, task_id: str, starttime: int | None, ts_ns: int,
                tid: int | None = None) -> None:
        # Scheduler events carry the thread-level identity (a TID), never the
        # process pid, so the tracker must be keyed on the same id space as the
        # events. For a thread row (tid != pid) the task_id already embeds the
        # tid — keying by the process pid would multiplex every thread of a
        # process under one key and leak the wrong generation. Fall back to pid
        # only for rows without an explicit tid (single-threaded / legacy).
        key = tid if tid is not None else pid
        runs = self._intervals.setdefault(key, [])
        if runs and runs[-1][2] == task_id and runs[-1][1] is None:
            return  # same generation still alive
        if runs and runs[-1][1] is None:
            runs[-1] = (runs[-1][0], ts_ns, runs[-1][2], runs[-1][3])
        runs.append((ts_ns, None, task_id, starttime))

    def close(self, pid: int, ts_ns: int, tid: int | None = None) -> None:
        key = tid if tid is not None else pid
        runs = self._intervals.get(key, [])
        if runs and runs[-1][1] is None:
            runs[-1] = (runs[-1][0], ts_ns, runs[-1][2], runs[-1][3])

    def resolve(self, pid: int, ts_ns: int) -> str | None:
        """task_id of the generation alive at ts_ns, else None (unresolved)."""
        for start, end, task_id, _st in self._intervals.get(pid, []):
            if start <= ts_ns and (end is None or ts_ns < end):
                return task_id
        self.unresolved += 1
        return None

    @staticmethod
    def expected_task_id(pid: int, starttime: int | None) -> str:
        return make_task_id(pid, starttime)
