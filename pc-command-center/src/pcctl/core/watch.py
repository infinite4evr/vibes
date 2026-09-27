"""Background alerts: a small check every 30 minutes (user systemd timer) that sends a desktop notification when
something needs you. Each alert is sent at most once per day (security updates: every 3 days) so it never nags.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from . import maint, packages, services, system
from .fmt import human
from .run import HOME, Step, has, out, py_step, sh
from .state import atomic_write_text

STATE = HOME / ".local/state/pc/alerts.json"
UNIT_DIR = HOME / ".config/systemd/user"
TIMER = "pc-watch.timer"
APP_ID = "io.github.infinite4evr.PcCommandCenter"

DEFAULTS = {"enabled": False, "disk_pct": 90, "security_updates": True, "failed_services": True, "restart_pending_days": 3,
            "trash_gb": 5, "battery_health": 60, "temperature": 90}


def settings() -> dict:
    return {**DEFAULTS, **(maint.config().get("alerts") or {})}


def save_settings(**changes) -> None:
    cur = settings()
    cur.update(changes)
    maint.save_config(alerts=cur)


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(d: dict) -> None:
    try:
        atomic_write_text(STATE, json.dumps(d) + "\n", mode=0o600)
    except OSError:
        pass


def notify(title: str, body: str, page: str = "dashboard", urgency: str = "normal") -> None:
    """Desktop notification tied to the app (GNOME shows its icon). Clicking it opens the app on the right page."""
    if not has("notify-send"):
        return
    args = ["notify-send", "-a", "PC Command Center", "-u", urgency, "-i", APP_ID, "--hint", f"string:desktop-entry:{APP_ID}"]
    gui = HOME / ".local/bin/pc-gui"
    if gui.exists():
        # wait for the click in a detached helper, so this check (and the timer) can finish right away
        cmd = shlex.join([*args, "--action=default=Open", "--wait", title, body])
        script = f'r=$({cmd}); [ "$r" = default ] && exec {shlex.quote(str(gui))} --page {shlex.quote(page)}'
        try:
            subprocess.Popen(["bash", "-c", script], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    sh([*args, title, body], timeout=5)


def checks(cfg: dict | None = None) -> list[dict]:
    """Everything worth telling you about right now: [{key, title, body, page, every_hours}]."""
    cfg = cfg or settings()
    found: list[dict] = []
    for m in system.mounts():
        if m.pct >= cfg["disk_pct"]:
            found.append({"key": f"disk:{m.mountpoint}", "title": f"Disk {m.mountpoint} is {m.pct:.0f}% full",
                          "body": f"Only {human(m.free)} left. Open Cleanup to free space.", "page": "cleanup", "every": 24})
    if cfg["security_updates"]:
        ups = packages.parse_apt_upgradable(out(["apt", "list", "--upgradable"], timeout=60))
        sec = [u for u in ups if u.security]
        if sec:
            found.append({"key": "security-updates", "title": f"{len(sec)} security update{'s' if len(sec) != 1 else ''} waiting",
                          "body": ", ".join(u.name for u in sec[:5]) + ("…" if len(sec) > 5 else ""), "page": "updates", "every": 72})
    if cfg["failed_services"]:
        bad = services.failed()
        if bad:
            found.append({"key": "failed:" + ",".join(sorted(s.unit for s in bad))[:120], "title": f"{len(bad)} background service(s) failing",
                          "body": ", ".join(s.name for s in bad[:4]), "page": "services", "every": 24})
    rb = system.reboot_required()
    if rb is not None:
        try:
            age_days = (time.time() - Path("/var/run/reboot-required").stat().st_mtime) / 86400
        except OSError:
            age_days = 0
        if age_days >= cfg["restart_pending_days"]:
            found.append({"key": "reboot", "title": "Restart needed", "body": f"Updates have been waiting {int(age_days)} days for a restart.",
                          "page": "updates", "every": 24})
    trash = HOME / ".local/share/Trash"
    if trash.is_dir() and cfg["trash_gb"]:
        size = 0
        trash_files = trash / "files"
        if trash_files.is_dir():
            try:
                entries = trash_files.rglob("*")
                for f in entries:
                    try:
                        if f.is_file():
                            size += f.stat().st_size
                    except OSError:
                        # Trash changes while we scan it (and may contain
                        # unreadable entries).  Alerts are best-effort.
                        continue
            except OSError:
                size = 0
        if size >= cfg["trash_gb"] * 1024 ** 3:
            found.append({"key": "trash", "title": f"Trash holds {human(size)}", "body": "Empty it in Cleanup to get the space back.",
                          "page": "cleanup", "every": 24 * 7})
    b = system.battery()
    if b and b.get("health") and b["health"] < cfg["battery_health"]:
        found.append({"key": "battery", "title": "Battery is worn", "body": f"It holds {b['health']:.0f}% of its original charge.",
                      "page": "power", "every": 24 * 30})
    t = system.cpu_temp()
    if t and t >= cfg["temperature"]:
        found.append({"key": "hot", "title": f"CPU is hot ({t:.0f}°C)", "body": "Check what's using the CPU, and the vents.",
                      "page": "processes", "every": 6})
    return found


def run(force: bool = False) -> list[dict]:
    """One pass: send notifications that are due. Returns what was sent."""
    cfg = settings()
    if not cfg["enabled"] and not force:
        return []
    st = _state()
    now = time.time()
    sent = []
    found = checks(cfg)
    for a in found:
        last = st.get(a["key"], 0)
        if force or now - last >= a["every"] * 3600:
            notify(a["title"], a["body"], a["page"])
            st[a["key"]] = now
            sent.append(a)
    # forget alerts that cleared up, so they can fire again if the problem comes back
    live = {a["key"] for a in found}
    st = {k: v for k, v in st.items() if k in live}
    _save_state(st)
    _log_health()
    return sent


def _log_health() -> None:
    """Keep one health score per day for the history graph (Maintenance)."""
    from . import health
    if any(h.get("day") == time.strftime("%Y-%m-%d") for h in health_history()[-1:]):
        return
    try:
        record_health(health.score(health.run_all()))
    except Exception:  # noqa: BLE001
        return


def record_health(score: int) -> None:
    """Store today's score (the app calls this whenever it computes one, the background alerts once a day)."""
    f = HOME / ".local/state/pc/health-history.json"
    hist = health_history()
    day = time.strftime("%Y-%m-%d")
    try:
        free = shutil.disk_usage("/").free
    except OSError:
        free = 0
    point = {"day": day, "score": int(score), "free": free}
    if hist and hist[-1].get("day") == day:
        hist[-1] = {**hist[-1], "score": min(int(score), hist[-1].get("score", 100)), "free": free}  # keep the day's worst score
    else:
        hist.append(point)
    try:
        atomic_write_text(f, json.dumps(hist[-400:]) + "\n", mode=0o600)
    except OSError:
        pass


def health_history() -> list[dict]:
    try:
        return json.loads((HOME / ".local/state/pc/health-history.json").read_text())
    except (OSError, ValueError):
        return []


def timer_enabled() -> bool:
    return out(["systemctl", "--user", "is-enabled", TIMER]) == "enabled"


def enable_steps() -> list[Step]:
    def write_units() -> str:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(UNIT_DIR / "pc-watch.service",
            "[Unit]\nDescription=PC Command Center background alerts\n\n"
            f"[Service]\nType=oneshot\nExecStart={services.exec_line(maint.pc_command() + ' watch')}\nNice=19\nIOSchedulingClass=idle\n"
            "# keep the little 'click to open' helpers alive after the check itself finishes\nKillMode=process\n", mode=0o600)
        atomic_write_text(UNIT_DIR / TIMER,
            "[Unit]\nDescription=PC Command Center alerts every 30 minutes\n\n"
            "[Timer]\nOnBootSec=10min\nOnUnitActiveSec=30min\nRandomizedDelaySec=2min\n\n[Install]\nWantedBy=timers.target\n", mode=0o600)
        save_settings(enabled=True)
        return "wrote ~/.config/systemd/user/pc-watch.{service,timer}"
    return [py_step("Create the alert schedule", write_units, "write ~/.config/systemd/user/pc-watch.{service,timer}"),
            Step("Reload schedules", ["systemctl", "--user", "daemon-reload"]),
            Step("Turn on alerts (every 30 minutes)", ["systemctl", "--user", "enable", "--now", TIMER])]


def disable_steps() -> list[Step]:
    def off() -> str:
        save_settings(enabled=False)
        return "alerts off"
    return [Step("Turn off background alerts", ["systemctl", "--user", "disable", "--now", TIMER], optional=True),
            py_step("Remember the choice", off, "alerts.enabled = false")]
