"""Durable, redacted audit trail for machine changes made by PC Command Center."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import debug
from .run import Step
from .state import append_private, atomic_write_text

FILE = Path.home() / ".local/state/pc/config-changes.jsonl"
KEEP = 1000
SCHEMA = 2

# Fallback for older Step declarations. New actions can set Step.mutates explicitly.
_MUTATORS = {
    "gsettings", "systemctl", "timedatectl", "hostnamectl", "nmcli", "ufw", "firewall-cmd",
    "apt", "apt-get", "dpkg", "snap", "flatpak", "update-grub", "grub-set-default", "pro",
    "loginctl", "rfkill", "swapoff", "swapon", "sysctl", "tee", "install", "rm", "mv", "cp",
    "sed", "chmod", "chown", "mount", "umount",
}


@dataclass(frozen=True, slots=True)
class AuditEntry:
    ts: float
    action: str
    step: str
    command: str
    root: bool
    interface: str
    event_id: str = ""
    config_key: str = ""
    schema: int = SCHEMA


def is_configuration_step(step: Step) -> bool:
    explicit = getattr(step, "mutates", None)
    if explicit is not None:
        return bool(explicit)
    if getattr(step, "_func", None) is not None:
        return True
    if not step.cmd:
        return False
    return Path(str(step.cmd[0])).name in _MUTATORS


def record_steps(action: str, steps: Iterable[Step], *, interface: str = "desktop") -> None:
    """Persist successful mutating steps only; callers invoke this after success."""
    rows = []
    now = time.time()
    for step in steps:
        if not is_configuration_step(step):
            continue
        rows.append({
            "schema": SCHEMA, "event_id": uuid.uuid4().hex, "ts": now,
            "action": debug.redact_text(action), "step": debug.redact_text(step.title),
            "command": step.display(), "root": bool(step.root), "interface": interface,
            "config_key": str(getattr(step, "config_key", "") or ""),
        })
    if not rows:
        return
    try:
        for row in rows:
            append_private(FILE, json.dumps(row, ensure_ascii=False) + "\n", mode=0o600)
        _trim()
    except OSError:
        pass


def entries(limit: int = KEEP) -> list[dict]:
    """Return newest first, tolerating old/corrupt records."""
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    result: list[dict] = []
    for line in lines[-max(0, limit):]:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                result.append(row)
        except (TypeError, ValueError):
            continue
    return list(reversed(result))


def _trim() -> None:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > KEEP + 100:
        atomic_write_text(FILE, "\n".join(lines[-KEEP:]) + "\n", mode=0o600)
