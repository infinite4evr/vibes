"""Side-effect-free action review shared by the GTK and terminal confirmations."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from .run import Step


def review(steps: list[Step]) -> dict:
    checks, changes, rollback = [], [], []
    for step in steps:
        command = step.cmd[0] if step.cmd else ""
        found = callable(getattr(step, "_func", None)) or bool(command and (os.access(command, os.X_OK) if '/' in command else shutil.which(command)))
        checks.append({"label": f"Command available: {command or '(empty)'}", "ok": (found or None) if step.optional else found})
        if step.cwd:
            checks.append({"label": f"Working folder exists: {step.cwd}", "ok": Path(step.cwd).is_dir()})
        checks.extend({"label": p, "ok": None} for p in step.prerequisites)
        changes.append(step.expected_change or step.title)
        rollback.append(step.rollback or ("Read-only step; no rollback needed." if step.mutates is False else
                                          "No automatic rollback is declared. Review backups before proceeding."))
    return {"checks": checks, "changes": changes, "rollback": list(dict.fromkeys(rollback)),
            "admin": any(s.root for s in steps), "ready": all(c["ok"] is not False for c in checks)}


def describe(steps: list[Step]) -> str:
    r = review(steps)
    checks = '\n'.join(f"{'OK' if c['ok'] else 'CHECK' if c['ok'] is None else 'MISSING'}: {c['label']}" for c in r['checks'])
    return ("Expected changes\n" + '\n'.join(f"• {c}" for c in r['changes']) +
            "\n\nPrerequisites\n" + checks +
            ("\nAdministrator permission required." if r['admin'] else "") +
            "\n\nRecovery / rollback\n" + '\n'.join(r['rollback']))
