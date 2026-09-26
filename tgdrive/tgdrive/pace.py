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


def mode() -> str:
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
    while mode() == "paused":
        await asyncio.sleep(5)
