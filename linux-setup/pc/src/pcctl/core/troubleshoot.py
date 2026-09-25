"""Troubleshooters, like Windows' "Fix problems": each one checks the usual suspects and offers a fix for what it finds.

Every check is read-only. Fixes are Steps the app shows before running. Parsers take text so they can be tested.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from typing import Callable

from .fmt import human
from .run import HOME, Step, has, out, sh
from .security import Check

USER_ENV_OK = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("XDG_RUNTIME_DIR"))


@dataclass
class Troubleshooter:
    id: str
    title: str
    icon: str
    description: str
    checks: Callable[[], list[Check]]
    palette: str = ""


def _user_active(unit: str) -> str:
    return out(["systemctl", "--user", "is-active", unit], timeout=5) or "inactive"


def _sys_active(unit: str) -> str:
    return out(["systemctl", "is-active", unit], timeout=5) or "inactive"


def _finish(found: list[Check], ok_text: str, extra: list[Check]) -> list[Check]:
    """Problems first; if there are none say so, then the always-available 'reset' fixes."""
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    found.sort(key=lambda c: order[c.level])
    if not any(c.level in ("bad", "warn") for c in found):
        found.insert(0, Check("fine", "No problem found", "ok", ok_text))
    return found + extra


# ---------------------------------------------------------------- sound

def parse_wpctl_volume(text: str) -> dict:
    """'Volume: 0.40 [MUTED]' -> {'volume': 0.4, 'muted': True}. Empty dict if no device."""
    m = re.search(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?", text)
    if not m:
        return {}
    return {"volume": float(m.group(1)), "muted": bool(m.group(2))}


def parse_wpctl_status(text: str) -> dict:
    """Pick the Sinks (speakers/headphones) and Sources (microphones) out of `wpctl status`, marking the default (*)."""
    res: dict[str, list[dict]] = {"sinks": [], "sources": []}
    section = ""
    in_audio = False
    for raw in text.splitlines():
        line = raw.replace("│", " ").replace("├", " ").replace("└", " ").replace("─", " ")
        s = line.strip()
        if s.startswith("Audio"):
            in_audio = True
            continue
        if s.startswith(("Video", "Settings")):
            in_audio = False
        if not in_audio:
            continue
        if s.rstrip(":") in ("Sinks", "Sources", "Devices", "Filters", "Streams", "Sink endpoints", "Source endpoints"):
            section = s.rstrip(":").lower()
            continue
        m = re.match(r"(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:\s*([\d.]+)(\s+MUTED)?\])?$", s)
        if m and section in ("sinks", "sources"):
            res[section].append({"default": bool(m.group(1)), "id": int(m.group(2)), "name": m.group(3).strip(),
                                 "volume": float(m.group(4)) if m.group(4) else None, "muted": bool(m.group(5))})
    return res


def sound_checks() -> list[Check]:
    found: list[Check] = []
    restart = [Step("Restart the sound system", ["systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"])]
    down = [u for u in ("pipewire", "pipewire-pulse", "wireplumber") if _user_active(u) != "active"]
    if down and USER_ENV_OK:
        found.append(Check("sound-service", "The sound system isn't running", "bad", f"Not running: {', '.join(down)}. Without it no app can play sound.",
                           "Start it", restart))
    if has("wpctl"):
        st = parse_wpctl_status(out(["wpctl", "status"], timeout=5))
        sinks = st["sinks"]
        if not sinks or all("dummy" in s["name"].lower() for s in sinks):
            found.append(Check("no-output", "No speakers or headphones found", "bad",
                               "Ubuntu only sees a 'Dummy Output'. Usually the sound driver didn't start: restart the sound system; if that doesn't help, "
                               "restart the PC. On some laptops the sound firmware package (sof-firmware / linux-firmware) needs an update.",
                               "Restart sound", restart))
        spk = parse_wpctl_volume(out(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=5))
        if spk.get("muted"):
            found.append(Check("muted", "Your speakers are muted", "bad", "The main output is on mute.", "Unmute",
                               [Step("Unmute the speakers", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])]))
        elif spk and spk.get("volume", 1) < 0.05:
            found.append(Check("volume", "Volume is at zero", "warn", f"The main output is at {spk['volume'] * 100:.0f}%.", "Set to 50%",
                               [Step("Set volume to 50%", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.5"])]))
        default = next((s for s in sinks if s["default"]), None)
        if default and len(sinks) > 1:
            found.append(Check("which-output", f"Sound goes to: {default['name']}", "info",
                               f"{len(sinks)} outputs exist. If you hear nothing, the sound may be going to another one (e.g. a monitor's HDMI).",
                               "Choose output", goto="settings:sound"))
        mic = parse_wpctl_volume(out(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], timeout=5))
        if mic.get("muted"):
            found.append(Check("mic-muted", "Your microphone is muted", "warn", "Others can't hear you in calls.", "Unmute mic",
                               [Step("Unmute the microphone", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"])]))
    elif not has("pactl"):
        found.append(Check("no-tools", "Sound tools not found", "info", "Can't look inside the sound system (wpctl is missing)."))
    state = HOME / ".local/state/wireplumber"
    extra = [Check("restart", "Restart the sound system", "info", "Fixes crackling, a missing device or an app with no sound, without restarting the PC.",
                   "Restart", restart)]
    if state.exists():
        extra.append(Check("reset", "Forget saved sound settings", "info", "Clears remembered volumes and chosen devices (safe, they come back as default).",
                           "Reset", [Step("Remove saved sound settings", ["rm", "-rf", str(state)]), *restart]))
    return _finish(found, "The sound system runs and nothing is muted.", extra)


# ---------------------------------------------------------------- internet

def parse_rfkill(text: str) -> list[dict]:
    """`rfkill list` -> [{'type': 'wlan', 'soft': True, 'hard': False}, ...]"""
    res: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = re.match(r"\d+:\s*(\S+):\s*(.+)", line)
        if m:
            cur = {"name": m.group(1), "type": m.group(2).strip().lower(), "soft": False, "hard": False}
            res.append(cur)
            continue
        m = re.match(r"\s*(Soft|Hard) blocked:\s*(yes|no)", line)
        if m and cur is not None:
            cur[m.group(1).lower()] = m.group(2) == "yes"
    return res


def _blocked(kind: str) -> dict:
    """kind 'wireless lan' or 'bluetooth' -> {'soft': bool, 'hard': bool} (either of any matching device)."""
    devs = [d for d in parse_rfkill(out(["rfkill", "list"], timeout=5)) if kind in d["type"]]
    return {"soft": any(d["soft"] for d in devs), "hard": any(d["hard"] for d in devs), "any": bool(devs)}


def internet_checks() -> list[Check]:
    found: list[Check] = []
    restart_nm = [Step("Restart networking", ["systemctl", "restart", "NetworkManager"], root=True)]
    if has("nmcli") and _sys_active("NetworkManager") != "active":
        found.append(Check("nm", "The network service isn't running", "bad", "NetworkManager handles Wi-Fi and cable connections.", "Start it",
                           [Step("Start networking", ["systemctl", "start", "NetworkManager"], root=True)]))
    w = _blocked("wireless lan")
    if w["hard"]:
        found.append(Check("wifi-hard", "Wi-Fi is switched off by a key or switch", "bad",
                           "Look for an airplane-mode key (often Fn + a key with an antenna) or a switch on the side of the laptop."))
    elif w["soft"] or (has("nmcli") and out(["nmcli", "radio", "wifi"], timeout=5) == "disabled"):
        found.append(Check("wifi-off", "Wi-Fi is turned off", "bad", "Airplane mode or the Wi-Fi switch is off.", "Turn on Wi-Fi",
                           [Step("Turn on Wi-Fi", ["nmcli", "radio", "wifi", "on"]), Step("Unblock the radio", ["rfkill", "unblock", "wifi"], root=True, optional=True)]))
    route = out(["ip", "route", "show", "default"], timeout=5)
    gw = (re.search(r"default via (\S+)", route) or [None, ""])[1]
    if not route:
        found.append(Check("no-net", "Not connected to any network", "bad", "Pick a Wi-Fi network or plug in a cable.", "Network page", goto="network"))
    else:
        conn = out(["nmcli", "networking", "connectivity", "check"], timeout=12) if has("nmcli") else ""
        if conn == "portal":
            found.append(Check("portal", "This Wi-Fi wants you to sign in", "warn", "Hotels, cafés and airports show a sign-in page first.",
                               "Open sign-in page", [Step("Open the sign-in page", ["xdg-open", "http://connectivity-check.ubuntu.com/"])]))
        router_ok = bool(gw) and sh(["ping", "-c", "1", "-W", "2", gw], timeout=5).ok
        net_ok = sh(["ping", "-c", "1", "-W", "3", "1.1.1.1"], timeout=6).ok or sh(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=6).ok
        dns_ok = sh(["getent", "hosts", "ubuntu.com"], timeout=8).ok
        if gw and not router_ok and not net_ok:
            found.append(Check("router", "Can't reach your router", "bad", f"The router ({gw}) doesn't answer. Move closer, reconnect, or restart the router.",
                               "Reconnect", restart_nm))
        elif not net_ok and conn != "portal":
            found.append(Check("upstream", "Your router has no internet", "bad", "The PC reaches the router but the router can't reach the internet. "
                               "Restart the router, or check with your provider."))
        elif not dns_ok:
            found.append(Check("dns", "Websites can't be found (DNS)", "bad", "The internet works but names like ubuntu.com don't turn into addresses.",
                               "Fix DNS", [Step("Clear the DNS cache", ["resolvectl", "flush-caches"], optional=True),
                                           Step("Restart the name service", ["systemctl", "restart", "systemd-resolved"], root=True)]))
    extra = [Check("restart", "Restart networking", "info", "Reconnects everything. Fixes most 'connected but nothing loads' problems.", "Restart",
                   restart_nm),
             Check("more", "Speed test and more checks", "info", "The Network page has a speed test, DNS switcher and open-ports list.",
                   "Network page", goto="network")]
    return _finish(found, "Connected, the router answers, the internet and website names work.", extra)


# ---------------------------------------------------------------- bluetooth

def bluetooth_checks() -> list[Check]:
    found: list[Check] = []
    restart = [Step("Restart Bluetooth", ["systemctl", "restart", "bluetooth"], root=True)]
    adapters = glob.glob("/sys/class/bluetooth/hci*")
    if not adapters:
        return [Check("none", "No Bluetooth adapter found", "bad", "This PC has no Bluetooth, or its driver didn't load. A cheap USB Bluetooth "
                      "dongle works if the PC has none.")]
    b = _blocked("bluetooth")
    if b["hard"]:
        found.append(Check("hard", "Bluetooth is switched off by a key or switch", "bad", "Look for an airplane-mode key or switch."))
    elif b["soft"]:
        found.append(Check("soft", "Bluetooth is turned off", "bad", "It's blocked (airplane mode or the Bluetooth switch in Settings).",
                           "Turn on", [Step("Unblock Bluetooth", ["rfkill", "unblock", "bluetooth"], root=True)]))
    if _sys_active("bluetooth") != "active":
        found.append(Check("service", "The Bluetooth service isn't running", "bad", "", "Start it",
                           [Step("Start Bluetooth", ["systemctl", "start", "bluetooth"], root=True)]))
    elif has("bluetoothctl"):
        show = out(["bluetoothctl", "show"], timeout=6)
        if re.search(r"Powered:\s*no", show):
            found.append(Check("power", "Bluetooth is powered off", "warn", "", "Turn on", [Step("Power on Bluetooth", ["bluetoothctl", "power", "on"])]))
    extra = [Check("restart", "Restart Bluetooth", "info", "Fixes headphones that won't connect or keep dropping.", "Restart", restart),
             Check("settings", "Pair a device", "info", "Open GNOME's Bluetooth settings.", "Open", goto="settings:bluetooth")]
    return _finish(found, "Bluetooth is on and its service runs.", extra)


# ---------------------------------------------------------------- clock

def parse_timedatectl(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def clock_checks() -> list[Check]:
    found: list[Check] = []
    t = parse_timedatectl(out(["timedatectl", "show"], timeout=5))
    if not t:
        return [Check("na", "Can't read the clock settings", "info", "timedatectl isn't available here.")]
    if t.get("NTP") == "no":
        found.append(Check("ntp", "Automatic time is off", "warn", "The clock drifts over time and some websites refuse to load when it's wrong.",
                           "Turn on", [Step("Turn on automatic time", ["timedatectl", "set-ntp", "true"], root=True)]))
    elif t.get("NTPSynchronized") == "no":
        svc = "chrony" if has("chronyc") else "systemd-timesyncd"
        steps = [Step("Restart the time service", ["systemctl", "restart", svc], root=True)]
        if has("chronyc"):
            steps.append(Step("Set the clock now", ["chronyc", "makestep"], root=True, optional=True))
        found.append(Check("sync", "The clock hasn't synced with the internet", "warn", "It may be a few seconds or minutes off.", "Sync now", steps))
    if t.get("LocalRTC") == "yes":
        found.append(Check("rtc", "The hardware clock uses local time", "info", "Common when Windows is also installed. If the time jumps by hours after "
                           "switching between Windows and Ubuntu, this is why. Leave it if you dual-boot.",
                           "Use UTC", [Step("Store the hardware clock in UTC", ["timedatectl", "set-local-rtc", "0"], root=True)]))
    tz = t.get("Timezone", "")
    extra = [Check("tz", f"Time zone: {tz or 'unknown'}", "info", "Wrong time zone? Change it on the Tweaks page.", "Change", goto="tweaks")]
    return _finish(found, "Automatic time is on and the clock is in sync.", extra)


# ---------------------------------------------------------------- packages

def parse_dpkg_broken(text: str) -> list[str]:
    """Packages in a half-done state from `dpkg -l` (status letters other than ii/rc/un/hi)."""
    res = []
    for line in text.splitlines():
        m = re.match(r"^([a-z])([A-Z])([A-Z ]?)\s+(\S+)", line)
        if not m:
            continue
        st, err = m.group(2), m.group(3).strip()
        if err or st in ("U", "F", "H", "W", "T"):
            res.append(m.group(4))
    return res


def apt_checks() -> list[Check]:
    found: list[Check] = []
    repair = [Step("Finish half-done installs", ["dpkg", "--configure", "-a"], root=True),
              Step("Fix missing pieces", ["apt-get", "-f", "install", "-y"], root=True)]
    busy = out(["pgrep", "-a", "-f", r"^(/usr/bin/)?(apt|apt-get|dpkg|unattended-upgr)"], timeout=5)
    if busy:
        names = sorted({os.path.basename(line.split()[1]) for line in busy.splitlines() if len(line.split()) > 1})
        found.append(Check("busy", "Another install is running", "warn", f"{', '.join(names)} is working. Installs fail with 'could not get lock' "
                           "until it finishes. Usually it's automatic security updates: wait a few minutes."))
    audit = out(["dpkg", "--audit"], timeout=20)
    broken = parse_dpkg_broken(out(["dpkg", "-l"], timeout=20))
    if audit or broken:
        what = ", ".join(broken[:6]) + ("…" if len(broken) > 6 else "")
        found.append(Check("broken", "Some packages are half-installed", "bad", f"An install was interrupted. {what}".strip(), "Repair", repair))
    chk = sh(["apt-get", "check", "-q"], timeout=30)
    if not chk.ok and "lock" not in (chk.err or "").lower() and "permission" not in (chk.err or "").lower():
        found.append(Check("deps", "Missing or conflicting dependencies", "bad", (chk.err or chk.out).strip().splitlines()[-1][:200] if (chk.err or chk.out).strip() else "",
                           "Repair", repair))
    lists = glob.glob("/var/lib/apt/lists/partial/*")
    if len(lists) > 20:
        found.append(Check("partial", "Leftover partial downloads", "info", f"{len(lists)} half-downloaded package lists.", "Clean",
                           [Step("Remove partial downloads", ["apt-get", "clean"], root=True)]))
    extra = [Check("repair", "Repair the package system", "info", "Safe to run any time: finishes interrupted installs and fixes dependencies.",
                   "Repair", repair),
             Check("refresh", "Reload the list of software sources", "info", "Shows errors from broken PPAs or mirrors in the output.", "Reload",
                   [Step("Reload package lists", ["apt-get", "update"], root=True)])]
    return _finish(found, "No interrupted installs and all dependencies are fine.", extra)


# ---------------------------------------------------------------- desktop

def _dir_size(path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def desktop_checks() -> list[Check]:
    found: list[Check] = []
    try:
        from . import extensions
        data = extensions.extensions()
        broken = [e for e in data.get("items", []) if e.state in ("ERROR", "OUT_OF_DATE") and e.enabled]
        if broken:
            found.append(Check("ext", f"{len(broken)} extension(s) broken", "warn", ", ".join(e.name for e in broken[:4]) +
                               ". Broken extensions are the #1 cause of a glitchy desktop after an Ubuntu upgrade.", "Extensions", goto="tweaks"))
    except Exception:  # noqa: BLE001
        pass
    thumbs = HOME / ".cache/thumbnails"
    size = _dir_size(thumbs) if thumbs.exists() else 0
    if size > 0:
        found.append(Check("thumbs", "Refresh file previews", "info" if size < 1024 ** 3 else "warn",
                           f"{human(size)} of saved previews. Clearing fixes wrong or missing thumbnails in Files.", "Clear",
                           [Step("Clear thumbnail cache", ["rm", "-rf", str(thumbs)])]))
    extra = [Check("fonts", "Fonts look wrong or a new font doesn't show", "info", "Rebuilds the font list.", "Rebuild",
                   [Step("Rebuild the font cache", ["fc-cache", "-f"])]),
             Check("grid", "App grid scrambled", "info", "Puts the app grid (Show Apps) back in alphabetical order. Folders you made are kept.",
                   "Reset grid", [Step("Reset the app grid layout", ["gsettings", "reset", "org.gnome.shell", "app-picker-layout"])]),
             Check("backup", "Save all desktop settings to a file", "info", "A safety copy before you try bigger resets.", "Save",
                   [Step("Save desktop settings", ["bash", "-c", 'mkdir -p ~/Backups && dconf dump / > ~/Backups/gnome-settings-$(date +%F-%H%M).ini'])]),
             Check("logout", "Still glitchy?", "info", "On Wayland the desktop can't restart itself. Log out and back in; that restarts GNOME Shell "
                   "without closing the PC.", "Log out", [Step("Log out", ["gnome-session-quit", "--logout"])])]
    return _finish(found, "No broken extensions found.", extra)


# ---------------------------------------------------------------- printer

def printer_checks() -> list[Check]:
    found: list[Check] = []
    if not has("lpstat"):
        return [Check("none", "Printing isn't installed", "warn", "CUPS (the printing system) is missing.", "Install",
                      [Step("Install printing support", ["apt-get", "install", "-y", "cups"], root=True)])]
    if _sys_active("cups") != "active":
        found.append(Check("cups", "The printing service isn't running", "bad", "", "Start it", [Step("Start printing", ["systemctl", "start", "cups"], root=True)]))
    printers = out(["lpstat", "-p"], timeout=6)
    if not printers:
        found.append(Check("noprinter", "No printer added", "warn", "Most network printers are found automatically; USB ones appear when plugged in.",
                           "Add a printer", goto="settings:printers"))
    for m in re.finditer(r"printer (\S+) disabled", printers):
        found.append(Check(f"off-{m.group(1)}", f"Printer {m.group(1)} is paused", "bad", "It stopped after an error. Resume it to print again.", "Resume",
                           [Step(f"Resume {m.group(1)}", ["cupsenable", m.group(1)], root=True)]))
    jobs = [j for j in out(["lpstat", "-o"], timeout=6).splitlines() if j.strip()]
    if jobs:
        found.append(Check("jobs", f"{len(jobs)} print job(s) waiting", "warn", "A stuck job blocks everything behind it.", "Cancel all",
                           [Step("Cancel waiting print jobs", ["cancel", "-a"])]))
    extra = [Check("restart", "Restart printing", "info", "", "Restart", [Step("Restart printing", ["systemctl", "restart", "cups"], root=True)])]
    return _finish(found, "Printing runs and nothing is stuck.", extra)


# ---------------------------------------------------------------- screen sharing

def sharing_checks() -> list[Check]:
    found: list[Check] = []
    units = ["xdg-desktop-portal", "xdg-desktop-portal-gnome", "pipewire"]
    down = [u for u in units if _user_active(u) != "active"] if USER_ENV_OK else []
    restart = [Step("Restart screen-sharing services", ["systemctl", "--user", "restart", *units])]
    if down:
        found.append(Check("portal", "Screen-sharing services aren't running", "bad", ", ".join(down), "Start them", restart))
    session = os.environ.get("XDG_SESSION_TYPE", "")
    extra = [Check("wayland", "Sharing works differently on Wayland", "info" if session == "wayland" else "ok",
                   "Apps must ask through a pop-up where you pick the screen or window. Old versions of Zoom, Slack or Discord and "
                   "some Electron apps can't; update them (the Flatpak or Snap versions usually work).", ""),
             Check("restart", "Restart screen-sharing services", "info", "Fixes a black screen or a share button that does nothing.", "Restart", restart)]
    return _finish(found, "The sharing services run.", extra)


def slow_checks() -> list[Check]:
    from . import diagnose
    return diagnose.run()


TROUBLESHOOTERS: list[Troubleshooter] = [
    Troubleshooter("internet", "Internet & Wi-Fi", "network-wireless-symbolic", "Connected but nothing loads, Wi-Fi missing, DNS errors.",
                   internet_checks, "Fix Wi-Fi / internet"),
    Troubleshooter("sound", "Sound", "audio-volume-high-symbolic", "No sound, wrong speakers, muted mic, crackling.", sound_checks, "Fix sound"),
    Troubleshooter("bluetooth", "Bluetooth", "bluetooth-active-symbolic", "Headphones won't connect or keep dropping.", bluetooth_checks, "Fix Bluetooth"),
    Troubleshooter("slow", "Slow PC", "power-profile-performance-symbolic", "What's using the CPU, memory or disk right now.", slow_checks, "Why is my PC slow?"),
    Troubleshooter("apt", "Installing software", "package-x-generic-symbolic", "'Could not get lock', broken packages, failed updates.",
                   apt_checks, "Fix broken installs / apt"),
    Troubleshooter("desktop", "Desktop acting weird", "video-display-symbolic", "Glitches, broken extensions, wrong previews or fonts.",
                   desktop_checks, "Fix desktop glitches"),
    Troubleshooter("clock", "Clock & time", "alarm-symbolic", "Wrong time, time jumps after using Windows.", clock_checks, "Fix the clock"),
    Troubleshooter("printer", "Printer", "printer-symbolic", "Printer missing, paused or stuck jobs.", printer_checks, "Fix printing"),
    Troubleshooter("sharing", "Screen sharing", "video-joined-displays-symbolic", "Black screen or no share button in calls.", sharing_checks,
                   "Fix screen sharing"),
]

BY_ID = {t.id: t for t in TROUBLESHOOTERS}

def text_report(tid: str) -> str:
    """Plain-text result for the CLI."""
    t = BY_ID[tid]
    lines = [t.title, "=" * len(t.title)]
    for c in t.checks():
        mark = {"ok": "✓", "info": "·", "warn": "!", "bad": "✗"}[c.level]
        lines.append(f"{mark} {c.title}" + (f"  - {c.detail}" if c.detail else ""))
        if c.steps and c.level in ("bad", "warn"):
            lines += [f"    fix: {s.display()}" for s in c.steps]
    return "\n".join(lines)
