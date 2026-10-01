"""How hard TG Drive's background work may push the computer (Settings → General → Background work).

The background jobs (the meaning index, subject tagging, the duplicate finder, the search index
upgrade) are CPU work that nobody waits for. They run:
  * at a low priority (nice 10), so anything you do on the computer comes first;
  * "gentle" (the default): after each batch they rest three times as long as the batch took, so
    together they use at most about a quarter of one core;
  * "full": as fast as they can (a first big index finishes sooner);
  * "paused": not at all (search keeps working with what's already built; new files are tagged and
    indexed for meaning when you switch back).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("tgdrive.pace")

MODES = ("gentle", "full", "paused")
GENTLE_REST = 3.0      # rest this many times as long as the work took
MAX_REST = 30.0


_forced: Optional[str] = None
_quiet_until = 0.0
_foreground_until = 0.0
FOREGROUND_HOLD = 0.6   # after a request someone is waiting on, background work steps aside this long
MAX_YIELD = 10.0        # but never waits more than this per batch (it must still get done)


def foreground() -> None:
    """Someone is waiting on an answer (a list, a search, a picture): background jobs pause between
    their batches for a moment, so they don't compete with it for Python (one thread runs at a time)."""
    global _foreground_until
    _foreground_until = time.monotonic() + FOREGROUND_HOLD


def _yield_left(start: float) -> float:
    now = time.monotonic()
    return 0.0 if now - start >= MAX_YIELD else max(0.0, _foreground_until - now)


def force(m: Optional[str]) -> None:
    """Override the setting for this run (Android's background sync holds the CPU jobs: "paused"
    while nobody is looking, so a sync wakes the phone briefly; None goes back to the setting)."""
    global _forced
    _forced = m if m in MODES else None


def quiet_for(seconds: float) -> None:
    """Hold the CPU jobs for the first moments after starting (phones: the first screens load first)."""
    global _quiet_until
    _quiet_until = time.monotonic() + seconds


def quiet_left() -> float:
    """Seconds left of the quiet start (0 when there is none, as on the desktop)."""
    return max(0.0, _quiet_until - time.monotonic()) if _quiet_until else 0.0


def mode() -> str:
    if _forced:
        return _forced
    if _quiet_until and time.monotonic() < _quiet_until:
        return "paused"
    from .settings import settings
    m = settings.get("background_work") or "gentle"
    return m if m in MODES else "gentle"


def lower_priority() -> None:
    """Make the calling thread yield to everything else on the computer (Linux: per-thread nice)."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError, PermissionError):
        pass


def rest_for(elapsed: float) -> float:
    if mode() != "gentle" or elapsed <= 0:
        return 0.0
    return min(MAX_REST, elapsed * GENTLE_REST)


def rest(elapsed: float, stop: Optional[threading.Event] = None) -> None:
    """Call after a batch of background work that took `elapsed` seconds of CPU."""
    wait = rest_for(elapsed)
    if wait:
        stop.wait(wait) if stop is not None else time.sleep(wait)
    start = time.monotonic()
    while (left := _yield_left(start)) > 0 and not (stop is not None and stop.is_set()):
        stop.wait(min(left, 0.25)) if stop is not None else time.sleep(min(left, 0.25))


def wait_while_paused(stop: Optional[threading.Event] = None, state_cb=None) -> None:
    """Block (in a worker thread) while background work is paused."""
    while mode() == "paused" and not (stop is not None and stop.is_set()):
        if state_cb:
            state_cb()
        stop.wait(5) if stop is not None else time.sleep(5)


async def arest(elapsed: float) -> None:
    wait = rest_for(elapsed)
    if wait:
        await asyncio.sleep(wait)
    start = time.monotonic()
    while (left := _yield_left(start)) > 0:
        await asyncio.sleep(min(left, 0.25))
    while mode() == "paused":
        await asyncio.sleep(5)
