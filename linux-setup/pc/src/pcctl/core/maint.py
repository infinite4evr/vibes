"""Maintenance: weekly automatic checkup, backups of your settings, snapshots, setup script integration."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path

from . import junk, packages, services, system
from .fmt import human
from .run import HOME, Step, has, out, py_step, sh, which

CONFIG_DIR = HOME / ".config/pc"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = HOME / ".local/state/pc"
UNIT_DIR = HOME / ".config/systemd/user"
TIMER = "pc-maintain.timer"
BACKUP_DIR = HOME / "Backups"

DEFAULTS = {"theme": "catppuccin-mocha", "icons": "auto", "setup_dir": "", "projects": ["~/Documents", "~/Projects", "~/code", "~/dev"],
            "auto_clean_trash_days": 0}


def config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    return {**DEFAULTS, **data}


def save_config(**changes) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = config()
    data.update(changes)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def setup_dir() -> Path | None:
    cands = [config().get("setup_dir"), str(HOME / "Documents/Vibes/linux-setup")]
    for c in cands:
        if c and (Path(c).expanduser() / "setup.sh").exists():
            return Path(c).expanduser()
    return None


def project_roots() -> list[Path]:
    roots = [Path(p).expanduser() for p in config()["projects"]]
    return [r for r in roots if r.is_dir()] or [HOME]


# ---------------------------------------------------------------- weekly checkup timer

def pc_command() -> str:
    exe = which("pc")
    if exe:
        return exe
    return f"{sys.executable} -m pcctl.cli"


def timer_status() -> dict:
    enabled = out(["systemctl", "--user", "is-enabled", TIMER]) == "enabled"
    nxt = ""
    if enabled:
        line = out(["systemctl", "--user", "list-timers", TIMER, "--no-legend", "--no-pager"])
        nxt = " ".join(line.split()[:4]) if line else ""
    last = ""
    log = STATE_DIR / "maintain.log"
    if log.exists():
        last = time.strftime("%d %b %H:%M", time.localtime(log.stat().st_mtime))
    return {"enabled": enabled, "next": nxt, "last": last}


def enable_timer_steps() -> list[Step]:
    def write_units() -> str:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        (UNIT_DIR / "pc-maintain.service").write_text(
            "[Unit]\nDescription=pc weekly checkup (safe cleanup + health report)\n\n"
            f"[Service]\nType=oneshot\nExecStart={pc_command()} maintain --auto\nNice=15\nIOSchedulingClass=idle\n")
        (UNIT_DIR / TIMER).write_text(
            "[Unit]\nDescription=Run pc weekly checkup\n\n"
            "[Timer]\nOnCalendar=Sun 11:00\nPersistent=true\nRandomizedDelaySec=30min\n\n[Install]\nWantedBy=timers.target\n")
        return f"wrote {UNIT_DIR}/pc-maintain.service and {TIMER}"
    return [py_step("Create weekly checkup schedule", write_units, "write ~/.config/systemd/user/pc-maintain.{service,timer}"),
            Step("Reload schedules", ["systemctl", "--user", "daemon-reload"]),
            Step("Turn on weekly checkup (Sundays 11:00)", ["systemctl", "--user", "enable", "--now", TIMER])]


def disable_timer_steps() -> list[Step]:
    return [Step("Turn off weekly checkup", ["systemctl", "--user", "disable", "--now", TIMER])]


def notify(title: str, body: str, urgency: str = "normal") -> None:
    if has("notify-send"):
        sh(["notify-send", "-a", "PC Command Center", "-u", urgency, "-i", "utilities-system-monitor", title, body], timeout=5)


def maintain_auto() -> str:
    """What the weekly timer runs: only safe user-level cleanup, then a short health report."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lines = [time.strftime("== %Y-%m-%d %H:%M ==")]
    before = shutil.disk_usage(HOME).free
    found = junk.auto_candidates()
    for step in junk.safe_user_steps(found):
        func = getattr(step, "_func", None)
        try:
            msg = func() if func else sh(step.argv(), timeout=300).out
            lines.append(f"{step.title}: ok")
            if msg:
                lines.append(str(msg)[:500])
        except Exception as e:  # noqa: BLE001
            lines.append(f"{step.title}: {e}")
    freed = max(shutil.disk_usage(HOME).free - before, 0)
    notes = []
    for m in system.mounts():
        if m.pct >= 90:
            notes.append(f"{m.mountpoint} is {m.pct:.0f}% full")
    ups = packages.parse_apt_upgradable(out(["apt", "list", "--upgradable"], timeout=60))
    if ups:
        sec = sum(u.security for u in ups)
        notes.append(f"{len(ups)} updates waiting" + (f" ({sec} security)" if sec else ""))
    bad = services.failed()
    if bad:
        notes.append(f"{len(bad)} service(s) failing")
    if system.reboot_required() is not None:
        notes.append("restart needed to finish updates")
    summary = f"Freed {human(freed)}." + (" " + "; ".join(notes) + "." if notes else " Everything looks healthy.")
    lines.append(summary)
    with open(STATE_DIR / "maintain.log", "a") as f:
        f.write("\n".join(lines) + "\n")
    notify("Weekly checkup", summary + ("\nRun `pc` to take care of it." if notes else ""), "normal")
    return summary


# ---------------------------------------------------------------- settings backup

DOTFILES = [
    ".bashrc", ".zshrc", ".zshrc.local", ".profile", ".gitconfig", ".bash_aliases",
    ".config/shell", ".config/zsh", ".config/starship.toml", ".config/ghostty", ".config/btop/btop.conf",
    ".config/lazygit/config.yml", ".config/Code/User/settings.json", ".config/Code/User/keybindings.json",
    ".config/Code/User/snippets", ".config/zed/settings.json", ".config/zed/keymap.json", ".config/autostart",
    ".config/pc", ".ssh/config", ".config/gtk-3.0/bookmarks", ".local/share/fonts",
]


def backup_settings_steps() -> list[Step]:
    stamp = time.strftime("%Y%m%d-%H%M")
    target = BACKUP_DIR / f"pc-settings-{stamp}.tar.gz"

    def run() -> str:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dconf = STATE_DIR / "gnome-settings.dconf"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        dconf.write_text(out(["dconf", "dump", "/"]) + "\n")
        if has("code"):
            (STATE_DIR / "vscode-extensions.txt").write_text(out(["code", "--list-extensions"], timeout=30) + "\n")
        count = 0
        with tarfile.open(target, "w:gz") as tar:
            for rel in DOTFILES + [str(dconf.relative_to(HOME)), str((STATE_DIR / "vscode-extensions.txt").relative_to(HOME))]:
                p = HOME / rel
                if p.exists():
                    tar.add(p, arcname=rel)
                    count += 1
        return f"saved {count} items to {target} ({human(target.stat().st_size)})"
    return [py_step("Back up your settings", run, f"tar czf ~/Backups/{target.name} (dotfiles, editor settings, GNOME settings, VS Code extension list)")]


def settings_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    res = [{"path": str(p), "name": p.name, "size": p.stat().st_size, "time": p.stat().st_mtime} for p in BACKUP_DIR.glob("pc-settings-*.tar.gz")]
    return sorted(res, key=lambda b: -b["time"])


def restore_settings_steps(path: str) -> list[Step]:
    def run() -> str:
        with tarfile.open(path) as tar:
            members = [m for m in tar.getmembers() if not m.name.startswith(("/", "..")) and ".." not in m.name.split("/")]
            try:
                tar.extractall(HOME, members=members, filter="data")
            except TypeError:  # Python < 3.12
                tar.extractall(HOME, members=members)
        dconf = STATE_DIR / "gnome-settings.dconf"
        if dconf.exists() and has("dconf"):
            sh(["dconf", "load", "/"], input=dconf.read_text())
        return f"restored {len(members)} files from {os.path.basename(path)}"
    return [py_step("Restore settings", run, f"tar xzf {path} -C ~  &&  dconf load / < gnome-settings.dconf")]


# ---------------------------------------------------------------- system snapshots

def snapshot_tools() -> dict:
    return {"timeshift": has("timeshift"), "deja-dup": has("deja-dup")}


def timeshift_steps() -> list[Step]:
    if not has("timeshift"):
        return [Step("Install Timeshift (system snapshots)", ["apt-get", "install", "-y", "timeshift"], root=True)]
    return [Step("Create a system snapshot", ["timeshift", "--create", "--comments", "pc snapshot", "--scripted"], root=True)]


def timeshift_list() -> str:
    return sh(["timeshift", "--list", "--scripted"], root=True, timeout=30).out if has("timeshift") else ""
