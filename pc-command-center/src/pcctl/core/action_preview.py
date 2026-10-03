"""Side-effect-free action review shared by the GTK and terminal confirmations."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from .run import Step


# Package tools: a step running one of these with "install" can provide the commands later steps use.
INSTALLERS = {"apt-get", "apt", "dpkg", "snap", "flatpak", "pipx", "pip", "pip3", "ubuntu-drivers", "npm", "gem", "cargo"}


def _installs(step: Step) -> bool:
    return bool(step.cmd) and os.path.basename(step.cmd[0]) in INSTALLERS and "install" in step.cmd[1:]


def review(steps: list[Step]) -> dict:
    checks, changes, rollback = [], [], []
    installed_earlier = False
    for step in steps:
        command = step.cmd[0] if step.cmd else ""
        found = callable(getattr(step, "_func", None)) or bool(command and (os.access(command, os.X_OK) if '/' in command else shutil.which(command)))
        if found:
            checks.append({"label": f"Command available: {command}", "ok": True})
        elif installed_earlier and command:
            # e.g. "Install ufw" then "ufw enable": the action itself provides it.
            checks.append({"label": f"Command available: {command} (installed by an earlier step)", "ok": None})
        else:
            checks.append({"label": f"Command available: {command or '(empty)'}", "ok": None if step.optional else False})
        installed_earlier = installed_earlier or _installs(step)
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
