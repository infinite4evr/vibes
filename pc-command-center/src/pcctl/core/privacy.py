"""Privacy: GNOME privacy settings, telemetry, and what is using your camera / microphone right now."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

from .run import Step, has, out, read, sh


@dataclass
class Setting:
    id: str
    title: str
    desc: str
    schema: str
    key: str
    kind: str = "bool"          # bool | int
    invert: bool = False        # switch ON means gsettings value false
    value: object = None
    options: list = field(default_factory=list)  # for int: [(label, value)]

    def read(self) -> "Setting":
        raw = out(["gsettings", "get", self.schema, self.key])
        if self.kind == "bool":
            v = raw == "true"
            self.value = (not v) if self.invert else v
        else:
            m = re.search(r"-?\d+$", raw.strip())  # values look like "uint32 300"
            self.value = int(m.group()) if m else None
        return self

    def available(self) -> bool:
        return sh(["gsettings", "writable", self.schema, self.key], timeout=3).ok

    def set_step(self, value) -> Step:
        if self.kind == "bool":
            real = (not value) if self.invert else value
            v = "true" if real else "false"
        else:
            v = str(value)
        return Step(f"{self.title}: {'on' if value is True else 'off' if value is False else value}", ["gsettings", "set", self.schema, self.key, v])


SETTINGS = [
    Setting("remove-old-trash", "Empty old Trash automatically", "Files stay in the Trash for the number of days below, then GNOME deletes them.",
            "org.gnome.desktop.privacy", "remove-old-trash-files"),
    Setting("remove-old-temp", "Delete old temporary files automatically", "Clears your old temp files on the same schedule.",
            "org.gnome.desktop.privacy", "remove-old-temp-files"),
    Setting("old-files-age", "Keep Trash and temp files for", "Days before they're deleted automatically.",
            "org.gnome.desktop.privacy", "old-files-age", kind="int", options=[("1 day", 1), ("7 days", 7), ("14 days", 14), ("30 days", 30), ("60 days", 60)]),
    Setting("remember-recent", "Remember recently opened files", "Shows recent files in Files and in file pickers.",
            "org.gnome.desktop.privacy", "remember-recent-files"),
    Setting("recent-age", "Remember recent files for", "How long the recent list keeps entries.",
            "org.gnome.desktop.privacy", "recent-files-max-age", kind="int", options=[("1 day", 1), ("7 days", 7), ("30 days", 30), ("Forever", -1)]),
    Setting("remember-app-usage", "Remember which apps you use", "Used to sort the app grid's frequent apps.",
            "org.gnome.desktop.privacy", "remember-app-usage"),
    Setting("report-problems", "Send crash reports automatically", "Ubuntu/GNOME technical problem reports.",
            "org.gnome.desktop.privacy", "report-technical-problems"),
    Setting("usage-stats", "Send software usage statistics", "Anonymous app usage stats to GNOME.",
            "org.gnome.desktop.privacy", "send-software-usage-stats"),
    Setting("location", "Location services", "Lets apps ask for your approximate location.",
            "org.gnome.system.location", "enabled"),
    Setting("camera", "Allow apps to use the camera", "Turn off to block every app from the webcam.",
            "org.gnome.desktop.privacy", "disable-camera", invert=True),
    Setting("microphone", "Allow apps to use the microphone", "Turn off to block every app from the microphone.",
            "org.gnome.desktop.privacy", "disable-microphone", invert=True),
    Setting("notif-lock", "Show notifications on the lock screen", "Message previews can be read by anyone at your desk when this is on.",
            "org.gnome.desktop.notifications", "show-in-lock-screen"),
    Setting("lock-enabled", "Lock the screen when it goes blank", "", "org.gnome.desktop.screensaver", "lock-enabled"),
    Setting("idle-delay", "Blank the screen after", "", "org.gnome.desktop.session", "idle-delay", kind="int",
            options=[("1 minute", 60), ("3 minutes", 180), ("5 minutes", 300), ("10 minutes", 600), ("15 minutes", 900), ("Never", 0)]),
]


def settings() -> list[Setting]:
    if not has("gsettings"):
        return []
    return [s.read() for s in SETTINGS if s.available()]


# ---------------------------------------------------------------- telemetry

@dataclass
class Telemetry:
    id: str
    title: str
    desc: str
    active: bool
    off_steps: list[Step]
    on_steps: list[Step]


def telemetry() -> list[Telemetry]:
    res = []
    if has("ubuntu-insights"):
        state = out(["ubuntu-insights", "consent"], timeout=5).lower()
        active = "true" in state or "consent: true" in state
        res.append(Telemetry("insights", "Ubuntu Insights", "Sends hardware and usage reports to Canonical.", active,
                             [Step("Turn off Ubuntu Insights", ["ubuntu-insights", "consent", "--state=false"], optional=True)],
                             [Step("Turn on Ubuntu Insights", ["ubuntu-insights", "consent", "--state=true"], optional=True)]))
    for unit, title, desc in (("apport.service", "Crash reporter (apport)", "Collects crash data and asks to send it to Ubuntu."),
                              ("whoopsie.service", "Error reporter (whoopsie)", "Uploads crash reports to Ubuntu's error tracker.")):
        if out(["systemctl", "list-unit-files", unit, "--no-legend"]):
            active = out(["systemctl", "is-enabled", unit]) == "enabled"
            res.append(Telemetry(unit, title, desc, active,
                                 [Step(f"Turn off {title}", ["systemctl", "disable", "--now", unit], root=True)],
                                 [Step(f"Turn on {title}", ["systemctl", "enable", "--now", unit], root=True)]))
    if os.path.exists("/etc/popularity-contest.conf"):
        active = bool(re.search(r'^PARTICIPATE="yes"', read("/etc/popularity-contest.conf"), re.M))
        res.append(Telemetry("popcon", "Popularity contest", "Weekly list of installed packages sent to Ubuntu.", active,
                             [Step("Turn off popularity contest", ["sed", "-i", 's/^PARTICIPATE=.*/PARTICIPATE="no"/', "/etc/popularity-contest.conf"], root=True)],
                             [Step("Turn on popularity contest", ["sed", "-i", 's/^PARTICIPATE=.*/PARTICIPATE="yes"/', "/etc/popularity-contest.conf"], root=True)]))
    if has("pro"):
        news = out(["pro", "config", "show"], timeout=10)
        m = re.search(r"^apt_news\s+(\S+)", news, re.M)
        if m:
            active = m.group(1).lower() != "false"
            res.append(Telemetry("apt-news", "Ubuntu Pro ads in apt", "The 'Get more security updates through Ubuntu Pro' messages when updating.", active,
                                 [Step("Hide Ubuntu Pro ads", ["pro", "config", "set", "apt_news=false"], root=True)],
                                 [Step("Show Ubuntu Pro news", ["pro", "config", "set", "apt_news=true"], root=True)]))
    return res


# ---------------------------------------------------------------- camera / mic in use

def camera_users() -> list[dict]:
    devs = glob.glob("/dev/video*")
    if not devs:
        return []
    users = []
    for pid_dir in glob.glob("/proc/[0-9]*"):
        try:
            for fd in os.listdir(f"{pid_dir}/fd"):
                target = os.readlink(f"{pid_dir}/fd/{fd}")
                if target.startswith("/dev/video"):
                    name = read(f"{pid_dir}/comm").strip()
                    users.append({"pid": int(os.path.basename(pid_dir)), "name": name, "device": target})
                    break
        except OSError:
            continue
    return users


def microphone_users() -> list[dict]:
    if not has("pactl"):
        return []
    text = out(["pactl", "list", "source-outputs"], timeout=5)
    res = []
    for block in text.split("Source Output #")[1:]:
        app = re.search(r'application\.name = "([^"]+)"', block)
        pid = re.search(r'application\.process\.id = "(\d+)"', block)
        binary = re.search(r'application\.process\.binary = "([^"]+)"', block)
        if app or binary:
            res.append({"name": (app.group(1) if app else binary.group(1)), "pid": int(pid.group(1)) if pid else None})
    return res


def screen_sharing() -> bool:
    return bool(out(["pgrep", "-f", "xdg-desktop-portal.*screencast"]))


# ---------------------------------------------------------------- history files

def shell_histories() -> list[dict]:
    from .run import HOME
    res = []
    for name in (".bash_history", ".zsh_history", ".python_history", ".node_repl_history", ".lesshst", ".wget-hsts", ".psql_history", ".mysql_history", ".sqlite_history"):
        p = HOME / name
        if p.exists():
            try:
                lines = sum(1 for _ in open(p, "rb"))
            except OSError:
                lines = 0
            res.append({"path": str(p), "name": name, "lines": lines, "size": p.stat().st_size})
    return res
