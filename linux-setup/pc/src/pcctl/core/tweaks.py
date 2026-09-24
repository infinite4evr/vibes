"""System tweaks for a dev laptop. Each one explains itself, shows its current state, and can be undone."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

import psutil

from .run import Step, has, out, read, sh

SYSCTL_DIR = "/etc/sysctl.d"


@dataclass
class Tweak:
    id: str
    group: str
    title: str
    desc: str
    state: str                      # plain-language current state
    applied: bool                   # is the recommended setting already in place
    apply: list[Step] = field(default_factory=list)
    revert: list[Step] = field(default_factory=list)
    note: str = ""


def _sysctl(key: str) -> str:
    return read(f"/proc/sys/{key.replace('.', '/')}").strip()


def _sysctl_steps(fname: str, lines: dict[str, str]) -> tuple[list[Step], list[Step]]:
    body = "".join(f"{k} = {v}\\n" for k, v in lines.items())
    path = f"{SYSCTL_DIR}/{fname}"
    apply = [Step(f"Write {path}", ["bash", "-c", f"printf '{body}' > {path} && sysctl -p {path}"], root=True)]
    revert = [Step(f"Remove {path}", ["bash", "-c", f"rm -f {path} && sysctl --system >/dev/null"], root=True)]
    return apply, revert


def inotify() -> Tweak:
    cur = int(_sysctl("fs.inotify.max_user_watches") or 0)
    inst = int(_sysctl("fs.inotify.max_user_instances") or 0)
    ok = cur >= 524288 and inst >= 512
    a, r = _sysctl_steps("60-pc-inotify.conf", {"fs.inotify.max_user_watches": "524288", "fs.inotify.max_user_instances": "1024"})
    return Tweak("inotify", "Developer", "File-watcher limit",
                 "VS Code, Vite, webpack, Jest and nodemon watch files for changes. When the limit is low they fail with "
                 "'ENOSPC: System limit for number of file watchers reached'.",
                 f"{cur:,} watches · {inst} instances", ok, a, r)


def open_files() -> Tweak:
    soft = out(["bash", "-c", "ulimit -Sn"])
    conf = "/etc/systemd/user.conf.d/60-pc-nofile.conf"
    ok = soft.isdigit() and int(soft) >= 65535 or os.path.exists(conf)
    body = "[Manager]\\nDefaultLimitNOFILE=65535:524288\\n"
    return Tweak("nofile", "Developer", "Open files limit",
                 "Some dev tools (bundlers, databases, test runners) need to open more than 1,024 files at once.",
                 f"soft limit {soft}", ok,
                 [Step("Raise the open-files limit for your apps", ["bash", "-c", f"mkdir -p /etc/systemd/user.conf.d && printf '{body}' > {conf}"], root=True)],
                 [Step("Restore the default", ["rm", "-f", conf], root=True)], note="Takes effect after you log out and in.")


def swappiness() -> Tweak:
    cur = int(_sysctl("vm.swappiness") or 60)
    ram_gb = psutil.virtual_memory().total / 1024**3
    want = 10 if ram_gb >= 12 else 30
    a, r = _sysctl_steps("60-pc-swappiness.conf", {"vm.swappiness": str(want)})
    return Tweak("swappiness", "Performance", "Swappiness",
                 f"How eagerly Linux moves memory to disk. With {ram_gb:.0f} GB RAM, {want} keeps apps snappier than the default 60.",
                 f"currently {cur}", cur <= want, a, r)


def zram() -> Tweak:
    swaps = out(["cat", "/proc/swaps"])
    on = "zram" in swaps
    return Tweak("zram", "Performance", "Compressed memory (zram)",
                 "Keeps swapped memory compressed in RAM instead of on the disk - much faster when memory runs low, and saves SSD wear.",
                 "on" if on else "off", on,
                 [Step("Install zram swap", ["apt-get", "install", "-y", "systemd-zram-generator"], root=True),
                  Step("Configure zram (half of RAM, zstd)", ["bash", "-c", "printf '[zram0]\\nzram-size = ram / 2\\ncompression-algorithm = zstd\\n' > /etc/systemd/zram-generator.conf "
                                                              "&& systemctl daemon-reload && systemctl start systemd-zram-setup@zram0.service"], root=True)],
                 [Step("Remove zram", ["apt-get", "purge", "-y", "systemd-zram-generator"], root=True, optional=True)],
                 note="Active immediately; stays after restart.")


def oomd() -> Tweak:
    active = out(["systemctl", "is-active", "systemd-oomd"]) == "active" or out(["systemctl", "is-active", "earlyoom"]) == "active"
    return Tweak("oomd", "Performance", "Freeze protection when memory runs out",
                 "Stops the single biggest memory hog instead of letting the whole desktop freeze for minutes.",
                 "on" if active else "off", active,
                 [Step("Turn on systemd-oomd", ["systemctl", "enable", "--now", "systemd-oomd"], root=True)],
                 [Step("Turn off systemd-oomd", ["systemctl", "disable", "--now", "systemd-oomd"], root=True)])


def trim() -> Tweak:
    on = out(["systemctl", "is-enabled", "fstrim.timer"]) == "enabled"
    return Tweak("trim", "Performance", "Weekly SSD TRIM", "Tells the SSD which blocks are free so it stays fast and lasts longer.",
                 "on" if on else "off", on,
                 [Step("Turn on weekly TRIM", ["systemctl", "enable", "--now", "fstrim.timer"], root=True)],
                 [Step("Turn off weekly TRIM", ["systemctl", "disable", "--now", "fstrim.timer"], root=True)])


def wait_online() -> Tweak:
    state = out(["systemctl", "is-enabled", "NetworkManager-wait-online.service"])
    off = state in ("disabled", "masked")
    return Tweak("wait-online", "Speed", "Don't wait for the network while booting",
                 "Ubuntu waits (up to 30s) for a network connection before finishing boot. Laptops don't need that.",
                 "waits" if not off else "doesn't wait", off,
                 [Step("Stop waiting for network at boot", ["systemctl", "disable", "NetworkManager-wait-online.service"], root=True)],
                 [Step("Wait for network at boot", ["systemctl", "enable", "NetworkManager-wait-online.service"], root=True)])


def shutdown_timeout() -> Tweak:
    conf = "/etc/systemd/system.conf.d/60-pc-timeout.conf"
    ok = os.path.exists(conf)
    body = "[Manager]\\nDefaultTimeoutStopSec=15s\\n"
    return Tweak("shutdown", "Speed", "Faster shutdown",
                 "When an app hangs during shutdown Linux waits 90 seconds for it. This lowers the wait to 15 seconds.",
                 "15 s" if ok else "90 s (default)", ok,
                 [Step("Shorten the shutdown wait", ["bash", "-c", f"mkdir -p /etc/systemd/system.conf.d && printf '{body}' > {conf} && systemctl daemon-reexec"], root=True)],
                 [Step("Restore the default", ["bash", "-c", f"rm -f {conf} && systemctl daemon-reexec"], root=True)])


def journal_cap() -> Tweak:
    ok = os.path.exists("/etc/systemd/journald.conf.d/99-pc.conf")
    return Tweak("journal", "Speed", "Cap system logs at 300 MB", "Stops logs from slowly eating gigabytes of disk.",
                 "capped" if ok else "not capped (can grow to 4 GB)", ok,
                 [Step("Cap logs", ["bash", "-c", "mkdir -p /etc/systemd/journald.conf.d && printf '[Journal]\\nSystemMaxUse=300M\\n' > /etc/systemd/journald.conf.d/99-pc.conf && systemctl restart systemd-journald"], root=True)],
                 [Step("Remove cap", ["bash", "-c", "rm -f /etc/systemd/journald.conf.d/99-pc.conf && systemctl restart systemd-journald"], root=True)])


def snap_retain() -> Tweak:
    if not has("snap"):
        return Tweak("snap-retain", "Speed", "Keep fewer old snap versions", "", "no snap", True)
    cur = out(["snap", "get", "system", "refresh.retain"]) or "3 (default)"
    ok = cur.strip() == "2"
    return Tweak("snap-retain", "Speed", "Keep only 2 versions of each snap", "Snap keeps 3 copies of every app by default. 2 is enough to roll back.",
                 cur, ok, [Step("Keep 2 versions", ["snap", "set", "system", "refresh.retain=2"], root=True)],
                 [Step("Back to default", ["snap", "unset", "system", "refresh.retain"], root=True)])


def apt_news() -> Tweak:
    if not has("pro"):
        return Tweak("apt-news", "Quiet", "Hide Ubuntu Pro ads in apt", "", "n/a", True)
    m = re.search(r"^apt_news\s+(\S+)", out(["pro", "config", "show"], timeout=10), re.M)
    off = bool(m and m.group(1).lower() == "false")
    return Tweak("apt-news", "Quiet", "Hide Ubuntu Pro ads in apt", "Removes the 'Get more security updates through Ubuntu Pro' messages from updates.",
                 "hidden" if off else "shown", off,
                 [Step("Hide the messages", ["pro", "config", "set", "apt_news=false"], root=True)],
                 [Step("Show them again", ["pro", "config", "set", "apt_news=true"], root=True)])


def ALL() -> list[Callable[[], Tweak]]:  # noqa: N802
    return [inotify, open_files, swappiness, zram, oomd, trim, wait_online, shutdown_timeout, journal_cap, snap_retain, apt_news]


def system_tweaks() -> list[Tweak]:
    res = []
    for fn in ALL():
        try:
            t = fn()
        except Exception as e:  # noqa: BLE001
            t = Tweak(fn.__name__, "Other", fn.__name__, f"Couldn't check: {e}", "?", True)
        if t.apply or not t.applied:
            res.append(t)
    return res


# ---------------------------------------------------------------- desktop switches (instant, no password)

@dataclass
class Switch:
    id: str
    group: str
    title: str
    desc: str
    schema: str
    key: str
    on: str = "true"
    off: str = "false"


DESKTOP = [
    Switch("animations", "Desktop", "Animations", "Turn off to make the desktop feel faster on older hardware.", "org.gnome.desktop.interface", "enable-animations"),
    Switch("hot-corner", "Desktop", "Hot corner", "Opens the Activities overview when the mouse hits the top-left corner.", "org.gnome.desktop.interface", "enable-hot-corners"),
    Switch("battery-pct", "Desktop", "Battery percentage in the top bar", "", "org.gnome.desktop.interface", "show-battery-percentage"),
    Switch("weekday", "Desktop", "Weekday in the clock", "", "org.gnome.desktop.interface", "clock-show-weekday"),
    Switch("seconds", "Desktop", "Seconds in the clock", "", "org.gnome.desktop.interface", "clock-show-seconds"),
    Switch("center", "Desktop", "Open new windows in the center", "", "org.gnome.mutter", "center-new-windows"),
    Switch("night-light", "Desktop", "Night Light", "Warmer screen colours in the evening - easier on the eyes.", "org.gnome.settings-daemon.plugins.color", "night-light-enabled"),
    Switch("overamp", "Desktop", "Allow volume above 100%", "Useful for quiet laptop speakers.", "org.gnome.desktop.sound", "allow-volume-above-100-percent"),
    Switch("tap-click", "Touchpad", "Tap to click", "", "org.gnome.desktop.peripherals.touchpad", "tap-to-click"),
    Switch("natural", "Touchpad", "Natural scrolling", "Content moves with your fingers, like a phone.", "org.gnome.desktop.peripherals.touchpad", "natural-scroll"),
    Switch("typing-off", "Touchpad", "Disable touchpad while typing", "", "org.gnome.desktop.peripherals.touchpad", "disable-while-typing"),
    Switch("dyn-ws", "Workspaces", "Dynamic workspaces", "Adds and removes workspaces as you need them.", "org.gnome.mutter", "dynamic-workspaces"),
    Switch("ws-primary", "Workspaces", "Workspaces only on the main display", "", "org.gnome.mutter", "workspaces-only-on-primary"),
    Switch("attach-modal", "Workspaces", "Attach dialogs to their window", "", "org.gnome.mutter", "attach-modal-dialogs"),
    Switch("auto-brightness", "Power", "Automatic screen brightness", "", "org.gnome.settings-daemon.plugins.power", "ambient-enabled"),
    Switch("dim", "Power", "Dim the screen when idle", "", "org.gnome.settings-daemon.plugins.power", "idle-dim"),
]


def desktop_switches() -> list[tuple[Switch, bool]]:
    if not has("gsettings"):
        return []
    res = []
    for s in DESKTOP:
        if not sh(["gsettings", "writable", s.schema, s.key], timeout=3).ok:
            continue
        res.append((s, out(["gsettings", "get", s.schema, s.key]) == s.on))
    return res


def set_switch(s: Switch, value: bool) -> bool:
    return sh(["gsettings", "set", s.schema, s.key, s.on if value else s.off], timeout=5).ok
