"""Background tasks that nobody awaits.

asyncio keeps only a weak reference to a task, so a fire-and-forget task can be garbage collected
mid-way, and its exception is otherwise only reported (if at all) when it is collected. spawn() keeps
a reference until the task ends and logs any failure with a full traceback and the task's name, so
crash logs say what was running."""
from __future__ import annotations

import asyncio
import logging
from typing import Coroutine, Optional

log = logging.getLogger("tgdrive.tasks")

_live: set[asyncio.Task] = set()


def spawn(coro: Coroutine, name: str, loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Task:
    task = (loop or asyncio.get_running_loop()).create_task(coro, name=name)
    _live.add(task)
    task.add_done_callback(_finished)
    return task


def _finished(task: asyncio.Task) -> None:
    _live.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background task %r failed", task.get_name(), exc_info=exc)
        try:
            from . import diagnostics
            diagnostics.record_exception("background", exc, {"task": task.get_name()})
        except Exception:
            pass


def running() -> list[str]:
    """Names of the background tasks still running (for diagnostics)."""
    return sorted(t.get_name() for t in _live if not t.done())
