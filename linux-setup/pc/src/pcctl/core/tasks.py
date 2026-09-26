"""In-process task registry used by the GTK background-process controller.

It tracks work PC Command Center itself starts.  Command tasks can expose a safe
cancel callback; generic Python worker threads are visible but intentionally cannot be
force-killed because terminating Python threads is unsafe.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable

from . import debug


@dataclass
class Task:
    id: str
    title: str
    kind: str = "background"
    status: str = "running"  # running | cancelling | done | failed | cancelled
    detail: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    cancellable: bool = False
    pid: int | None = None
    lines: list[str] = field(default_factory=list)
    _cancel: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    @property
    def active(self) -> bool:
        return self.status in ("running", "cancelling")


_lock = threading.RLock()
_tasks: dict[str, Task] = {}
_KEEP = 100


def start(title: str, *, kind: str = "background", cancellable: bool = False,
          cancel: Callable[[], None] | None = None, detail: str = "", pid: int | None = None) -> str:
    task_id = uuid.uuid4().hex[:12]
    task = Task(task_id, title or "Background task", kind=kind, cancellable=bool(cancellable and cancel), _cancel=cancel,
                detail=detail, pid=pid)
    with _lock:
        _tasks[task_id] = task
        _trim_locked()
    debug.event("task.start", task_id=task_id, title=title, kind=kind, cancellable=task.cancellable)
    return task_id


def set_cancel(task_id: str, callback: Callable[[], None] | None) -> None:
    with _lock:
        t = _tasks.get(task_id)
        if t:
            t._cancel = callback
            t.cancellable = callback is not None


def update(task_id: str, *, detail: str | None = None, pid: int | None = None, status: str | None = None) -> None:
    with _lock:
        t = _tasks.get(task_id)
        if not t:
            return
        if detail is not None:
            t.detail = detail
        if pid is not None:
            t.pid = pid
        if status is not None:
            t.status = status


def log(task_id: str, line: str) -> None:
    safe = debug.redact_text(line)
    with _lock:
        t = _tasks.get(task_id)
        if not t:
            return
        t.lines.append(safe)
        if len(t.lines) > 120:
            del t.lines[:-120]


def finish(task_id: str, ok: bool, *, cancelled: bool = False, detail: str = "") -> None:
    with _lock:
        t = _tasks.get(task_id)
        if not t:
            return
        t.status = "cancelled" if cancelled else ("done" if ok else "failed")
        t.finished = time.time()
        t.pid = None
        if detail:
            t.detail = detail
    debug.event("task.finish", task_id=task_id, ok=ok, cancelled=cancelled, detail=detail)


def cancel(task_id: str) -> bool:
    with _lock:
        t = _tasks.get(task_id)
        if not t or not t.active or not t.cancellable or t._cancel is None:
            return False
        cb = t._cancel
        t.status = "cancelling"
        t.detail = "Stopping safely…"
    debug.event("task.cancel", task_id=task_id)
    try:
        cb()
        return True
    except Exception as e:  # noqa: BLE001
        debug.exception("task cancel", e)
        update(task_id, status="failed", detail=f"Could not stop: {e}")
        return False


def snapshots(*, include_finished: bool = True) -> list[Task]:
    with _lock:
        rows = [replace(t, lines=list(t.lines), _cancel=None) for t in _tasks.values() if include_finished or t.active]
    return sorted(rows, key=lambda t: (not t.active, -t.started))


def active_count() -> int:
    with _lock:
        return sum(1 for t in _tasks.values() if t.active)


def clear_finished() -> None:
    with _lock:
        for k in [k for k, t in _tasks.items() if not t.active]:
            _tasks.pop(k, None)


def _trim_locked() -> None:
    if len(_tasks) <= _KEEP:
        return
    finished = sorted((t for t in _tasks.values() if not t.active), key=lambda t: t.finished or t.started)
    for t in finished[:max(0, len(_tasks) - _KEEP)]:
        _tasks.pop(t.id, None)
