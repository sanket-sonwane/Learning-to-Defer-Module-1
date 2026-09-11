"""Task identity: task_id = "<pid>:<starttime_ticks>".

starttime is /proc/<pid>/stat field 22 (clock ticks since boot) and does not
change across the lifetime of the task, so PID reuse creates a distinct id.
"""
from m1.models.task import TaskSnapshot


def make_task_id(pid: int, starttime_ticks: int | None) -> str:
    if starttime_ticks is None:
        # Explicitly mark unknown generation — QA must flag systematic unknowns.
        return f"{pid}:unknown"
    return f"{pid}:{starttime_ticks}"


def snapshot_task_id(snap: TaskSnapshot) -> str:
    return make_task_id(snap.pid, snap.starttime_ticks)


def is_same_task(a: TaskSnapshot, b: TaskSnapshot) -> bool:
    """True only if both pid and generation match.

    Compares task_id (which embeds the starttime generation) rather than the
    raw starttime field, so tasks with unknown generation ("pid:unknown") are
    never silently merged: unequal ids -> different tasks.
    """
    return a.pid == b.pid and a.task_id == b.task_id
