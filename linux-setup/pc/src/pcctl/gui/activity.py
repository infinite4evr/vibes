"""Activity history: every action the app ran, with its commands, result and output (~/.local/state/pc/activity.jsonl)."""

from __future__ import annotations

import json
import time
from pathlib import Path

FILE = Path.home() / ".local/state/pc/activity.jsonl"
ERRORS = Path.home() / ".local/state/pc/gui-errors.log"
KEEP = 300


def record(title: str, commands: list[str], ok: bool, note: str = "", output: list[str] | None = None, root: bool = False,
           duration: float = 0.0) -> None:
    entry = {"ts": time.time(), "title": title, "commands": commands, "ok": ok, "note": note, "root": root,
             "duration": round(duration, 1), "output": (output or [])[-400:]}
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _trim()
    except OSError:
        pass


def _trim() -> None:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > KEEP + 50:
        FILE.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")


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
        ERRORS.parent.mkdir(parents=True, exist_ok=True)
        with open(ERRORS, "a", encoding="utf-8") as f:
            f.write(time.strftime("== %Y-%m-%d %H:%M:%S ==\n") + text.rstrip() + "\n")
    except OSError:
        pass
