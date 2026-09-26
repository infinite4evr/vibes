"""Maintenance: weekly automatic checkup, backups of your settings, snapshots, setup script integration."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tarfile
import time
from pathlib import Path

from . import junk, packages, services, system
from .fmt import human
from .run import HOME, Step, has, out, py_step, sh, which
from .state import append_private, atomic_write_text

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
    data = config()
    data.update(changes)
    atomic_write_text(CONFIG_FILE, json.dumps(data, indent=2) + "\n", mode=0o600)


def setup_dir() -> Path | None:
    """The ubuntu-setup folder (setup.sh). "linux-setup" was its name before the vibes repo split it out."""
    cands = [config().get("setup_dir"), str(HOME / "Documents/Vibes/ubuntu-setup"), str(HOME / "Documents/Vibes/linux-setup")]
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
        atomic_write_text(UNIT_DIR / "pc-maintain.service",
            "[Unit]\nDescription=pc weekly checkup (safe cleanup + health report)\n\n"
            f"[Service]\nType=oneshot\nExecStart={pc_command()} maintain --auto\nNice=15\nIOSchedulingClass=idle\n", mode=0o600)
        atomic_write_text(UNIT_DIR / TIMER,
            "[Unit]\nDescription=Run pc weekly checkup\n\n"
            "[Timer]\nOnCalendar=Sun 11:00\nPersistent=true\nRandomizedDelaySec=30min\n\n[Install]\nWantedBy=timers.target\n", mode=0o600)
        return f"wrote {UNIT_DIR}/pc-maintain.service and {TIMER}"
    return [py_step("Create weekly checkup schedule", write_units, "write ~/.config/systemd/user/pc-maintain.{service,timer}"),
            Step("Reload schedules", ["systemctl", "--user", "daemon-reload"]),
            Step("Turn on weekly checkup (Sundays 11:00)", ["systemctl", "--user", "enable", "--now", TIMER])]


def disable_timer_steps() -> list[Step]:
    return [Step("Turn off weekly checkup", ["systemctl", "--user", "disable", "--now", TIMER])]


def notify(title: str, body: str, urgency: str = "normal") -> None:
    if has("notify-send"):
        app = "io.github.infinite4evr.PcCommandCenter"
        sh(["notify-send", "-a", "PC Command Center", "-u", urgency, "-i", app, "--hint", f"string:desktop-entry:{app}", title, body], timeout=5)


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
    append_private(STATE_DIR / "maintain.log", "\n".join(lines) + "\n", mode=0o600)
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
        atomic_write_text(dconf, out(["dconf", "dump", "/"]) + "\n", mode=0o600)
        if has("code"):
            atomic_write_text(STATE_DIR / "vscode-extensions.txt", out(["code", "--list-extensions"], timeout=30) + "\n", mode=0o600)
        count = 0
        with tarfile.open(target, "w:gz") as tar:
            for rel in DOTFILES + [str(dconf.relative_to(HOME)), str((STATE_DIR / "vscode-extensions.txt").relative_to(HOME))]:
                p = HOME / rel
                if p.exists():
                    tar.add(p, arcname=rel)
                    count += 1
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return f"saved {count} items to {target} ({human(target.stat().st_size)})"
    return [py_step("Back up your settings", run, f"tar czf ~/Backups/{target.name} (dotfiles, editor settings, GNOME settings, VS Code extension list)")]


def settings_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    res = [{"path": str(p), "name": p.name, "size": p.stat().st_size, "time": p.stat().st_mtime} for p in BACKUP_DIR.glob("pc-settings-*.tar.gz")]
    return sorted(res, key=lambda b: -b["time"])


def restore_settings_steps(path: str) -> list[Step]:
    def safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
        members = tar.getmembers()
        if len(members) > 50_000:
            raise ValueError("Backup has an unreasonable number of files")
        total = 0
        good: list[tarfile.TarInfo] = []
        for m in members:
            parts = Path(m.name).parts
            if not m.name or m.name.startswith("/") or ".." in parts:
                raise ValueError(f"Unsafe path in backup: {m.name!r}")
            # Settings backups never need links, devices, sockets or FIFOs. Rejecting
            # them also makes extraction safe on Python 3.10/3.11 where tar filters
            # were not consistently available.
            if not (m.isdir() or m.isfile()):
                raise ValueError(f"Unsupported file type in backup: {m.name!r}")
            if m.isfile():
                total += max(0, m.size)
                if total > 2 * 1024 ** 3:
                    raise ValueError("Backup expands beyond the 2 GiB safety limit")
            good.append(m)
        return good

    def pre_restore_backup(members: list[tarfile.TarInfo]) -> Path | None:
        existing: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for m in members:
            # Back up top-level archive entries once; tar.add recurses where needed.
            top = m.name.split("/", 1)[0] if not m.name.startswith(".") else "/".join(m.name.split("/")[:2])
            if top in seen:
                continue
            seen.add(top)
            p = HOME / top
            if p.exists() and p != BACKUP_DIR:
                existing.append((p, top))
        if not existing:
            return None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target = BACKUP_DIR / f"pc-before-restore-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        with tarfile.open(target, "w:gz") as old:
            for p, arc in existing:
                old.add(p, arcname=arc)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def extract_regular(tar: tarfile.TarFile, members: list[tarfile.TarInfo]) -> None:
        # Manual extraction: no link traversal and no special files, independent of
        # the Python version's tarfile filter support. Also reject *pre-existing*
        # symlinked parent directories under HOME; otherwise a safe-looking archive
        # path such as .config/app could be redirected outside HOME by a local symlink.
        home_real = HOME.resolve()

        def safe_dir(parts: tuple[str, ...]) -> Path:
            cur = HOME
            for part in parts:
                nxt = cur / part
                if nxt.is_symlink():
                    raise ValueError(f"Restore path crosses a symlink: {nxt}")
                if nxt.exists() and not nxt.is_dir():
                    raise ValueError(f"Restore path is not a directory: {nxt}")
                nxt.mkdir(exist_ok=True)
                try:
                    nxt.resolve().relative_to(home_real)
                except ValueError as exc:
                    raise ValueError(f"Restore path escapes your home folder: {nxt}") from exc
                cur = nxt
            return cur

        for m in members:
            parts = Path(m.name).parts
            if m.isdir():
                safe_dir(parts)
                continue
            parent = safe_dir(parts[:-1])
            dest = parent / parts[-1]
            src = tar.extractfile(m)
            if src is None:
                raise ValueError(f"Could not read {m.name!r} from backup")
            tmp = dest.with_name(f".{dest.name}.pc-restore-{os.getpid()}")
            try:
                with open(tmp, "wb") as out_f:
                    shutil.copyfileobj(src, out_f, length=1024 * 1024)
                    out_f.flush()
                    os.fsync(out_f.fileno())
                # Never restore setuid/setgid/sticky bits from an archive.
                os.chmod(tmp, m.mode & 0o777)
                os.replace(tmp, dest)
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def run() -> str:
        with tarfile.open(path) as tar:
            members = safe_members(tar)
            rollback = pre_restore_backup(members)
            extract_regular(tar, members)
        dconf = STATE_DIR / "gnome-settings.dconf"
        if dconf.exists() and has("dconf"):
            sh(["dconf", "load", "/"], input=dconf.read_text())
        extra = f"; previous files saved to {rollback}" if rollback else ""
        return f"restored {len(members)} files from {os.path.basename(path)}{extra}"
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


TS_TAGS = {"O": "made by hand", "B": "at start-up", "H": "hourly", "D": "daily", "W": "weekly", "M": "monthly"}


def parse_timeshift_list(text: str) -> dict:
    """`timeshift --list --scripted` -> {'device', 'status', 'free', 'snapshots': [{'name', 'tags', 'kinds', 'comment', 'time'}]}."""
    info: dict = {"device": "", "status": "", "free": "", "mode": "", "snapshots": [], "configured": "First run mode" not in text}
    for line in text.splitlines():
        m = re.match(r"^(Device|Status|Mode)\s*:\s*(.+)$", line.strip())
        if m:
            info[m.group(1).lower()] = m.group(2).strip()
            continue
        m = re.match(r"^(\d+) snapshots?, (.+?) free", line.strip())
        if m:
            info["free"] = m.group(2)
            continue
        m = re.match(r"^\s*\d+\s+>\s+(\S+)\s*([OBHDWM]*)\s*(.*)$", line)
        if m:
            name, tags = m.group(1), m.group(2)
            t = None
            try:
                t = time.mktime(time.strptime(name, "%Y-%m-%d_%H-%M-%S"))
            except ValueError:
                pass
            info["snapshots"].append({"name": name, "tags": tags, "kinds": [TS_TAGS[c] for c in tags if c in TS_TAGS],
                                      "comment": m.group(3).strip(), "time": t})
    info["snapshots"].sort(key=lambda s: s["name"], reverse=True)
    return info


def timeshift_delete_steps(names: list[str]) -> list[Step]:
    return [Step(f"Delete snapshot {n}", ["timeshift", "--delete", "--snapshot", n, "--scripted"], root=True) for n in names]


def timeshift_list_steps() -> list[Step]:
    return [Step("List snapshots", ["timeshift", "--list", "--scripted"], root=True)]

