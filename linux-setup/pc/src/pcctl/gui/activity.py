"""Activity history: every action the app ran, with its commands, result and output (~/.local/state/pc/activity.jsonl)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..core import debug
from ..core.state import append_private, atomic_write_text

FILE = Path.home() / ".local/state/pc/activity.jsonl"
ERRORS = Path.home() / ".local/state/pc/gui-errors.log"
KEEP = 300


def record(title: str, commands: list[str], ok: bool, note: str = "", output: list[str] | None = None, root: bool = False,
           duration: float = 0.0) -> None:
    entry = {"ts": time.time(), "title": debug.redact_text(title),
             "commands": [debug.redact_text(c) for c in commands], "ok": ok,
             "note": debug.redact_text(note), "root": root, "duration": round(duration, 1),
             "output": [debug.redact_text(x) for x in (output or [])[-400:]]}
    try:
        append_private(FILE, json.dumps(entry) + "\n", mode=0o600)
        _trim()
    except OSError:
        pass


def _trim() -> None:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > KEEP + 50:
        try:
            atomic_write_text(FILE, "\n".join(lines[-KEEP:]) + "\n", mode=0o600)
        except OSError:
            pass


def entries(limit: int = KEEP) -> list[dict]:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    res = []
    for ln in lines[-limit:]:
        try:
            res.append(json.loads(ln))
        except ValueError:
            continue
    return list(reversed(res))


def clear() -> None:
    try:
        FILE.unlink()
    except OSError:
        pass


def log_error(text: str) -> None:
    try:
        append_private(ERRORS, time.strftime("== %Y-%m-%d %H:%M:%S ==\n") + debug.redact_text(text).rstrip() + "\n", mode=0o600)
    except OSError:
        pass
