"""Background services (systemd) and apps that start when you log in."""

from __future__ import annotations

import glob
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .run import HOME, Step, out, read, sh

# Plain-language explanations for services people commonly wonder about.
EXPLAIN = {
    "NetworkManager": "Keeps you connected to Wi-Fi and wired networks",
    "bluetooth": "Bluetooth devices",
    "cups": "Printing",
    "cups-browsed": "Finds network printers automatically",
    "avahi-daemon": "Finds devices on your network (printers, Chromecast)",
    "ssh": "Lets other computers log in to this one",
    "sshd": "Lets other computers log in to this one",
    "docker": "Docker containers",
    "containerd": "Container runtime (used by Docker)",
    "snapd": "Snap apps and their updates",
    "fwupd": "Firmware updates",
    "power-profiles-daemon": "Power modes (balanced / performance / saver)",
    "thermald": "Keeps Intel CPUs from overheating",
    "ufw": "Firewall",
    "unattended-upgrades": "Installs security updates automatically",
    "gdm": "Login screen",
    "gdm3": "Login screen",
    "systemd-resolved": "Looks up website names (DNS)",
    "systemd-timesyncd": "Keeps the clock right",
    "ModemManager": "Mobile broadband modems (safe to disable if you have none)",
    "kerneloops": "Sends kernel crash reports",
    "whoopsie": "Sends crash reports to Ubuntu",
    "apport": "Crash report collector",
    "tracker-miner-fs-3": "Indexes files for search",
    "pipewire": "Sound and screen sharing",
    "wireplumber": "Sound device manager",
    "cloudflare-warp": "Cloudflare WARP VPN",
    "warp-svc": "Cloudflare WARP VPN",
    "virtualbox": "VirtualBox kernel drivers",
    "libvirtd": "Virtual machines (KVM)",
    "postgresql": "PostgreSQL database",
    "mysql": "MySQL database",
    "redis-server": "Redis database",
    "nginx": "Nginx web server",
    "apache2": "Apache web server",
    "anacron": "Runs missed scheduled jobs",
    "cron": "Scheduled jobs",
    "rsyslog": "System log files",
    "colord": "Screen color profiles",
    "switcheroo-control": "Switches between graphics cards",
    "packagekit": "Software updates for the App Center",
    "accounts-daemon": "User accounts",
    "udisks2": "USB drives and disks",
    "upower": "Battery information",
    "polkit": "Asks for your password for admin actions",
    "ubuntu-insights": "Ubuntu usage reports",
}


def explain(unit: str) -> str:
    base = unit.removesuffix(".service").split("@")[0]
    return EXPLAIN.get(base, "")


@dataclass
class Service:
    unit: str
    load: str
    active: str
    sub: str
    description: str
    enabled: str = ""
    user: bool = False

    @property
    def name(self) -> str:
        return self.unit.removesuffix(".service")


def parse_units(text: str) -> list[Service]:
    res = []
    for line in text.splitlines():
        line = line.lstrip("● ").strip()
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service"):
            res.append(Service(parts[0], parts[1], parts[2], parts[3], parts[4] if len(parts) > 4 else ""))
    return res


def parse_unit_files(text: str) -> dict[str, str]:
    res = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(".service"):
            res[parts[0]] = parts[1]
    return res


def services(user: bool = False) -> list[Service]:
    scope = ["--user"] if user else []
    units = parse_units(out(["systemctl", *scope, "list-units", "--type=service", "--all", "--plain", "--no-legend", "--no-pager"], timeout=15))
    files = parse_unit_files(out(["systemctl", *scope, "list-unit-files", "--type=service", "--plain", "--no-legend", "--no-pager"], timeout=15))
    known = {s.unit for s in units}
    for s in units:
        s.enabled = files.get(s.unit, files.get(re.sub(r"@.+\.service$", "@.service", s.unit), ""))
        s.user = user
    # Enabled-but-not-loaded units (e.g. disabled at boot) still matter
    for unit, state in files.items():
        if unit not in known and state in ("enabled", "disabled") and "@" not in unit:
            units.append(Service(unit, "loaded", "inactive", "dead", "", state, user))
    units = [s for s in units if s.load != "not-found"]
    units.sort(key=lambda s: (s.active != "failed", s.active != "active", s.unit))
    return units


def failed() -> list[Service]:
    return [s for s in services() + services(user=True) if s.active == "failed"]


def action_steps(svc: Service, action: str) -> list[Step]:
    scope = ["--user"] if svc.user else []
    labels = {"start": "Start", "stop": "Stop", "restart": "Restart", "enable": "Start at boot", "disable": "Don't start at boot",
              "enable --now": "Turn on (now and at boot)", "disable --now": "Turn off (now and at boot)", "reset-failed": "Clear failed state"}
    return [Step(f"{labels.get(action, action)}: {svc.name}", ["systemctl", *scope, *action.split(), svc.unit], root=not svc.user)]


def logs(svc: Service, lines: int = 200) -> str:
    scope = ["--user-unit"] if svc.user else ["-u"]
    r = sh(["journalctl", *scope, svc.unit, "-n", str(lines), "--no-pager", "-o", "short-iso"], timeout=15)
    if not r.out.strip() and not svc.user:
        r = sh(["journalctl", "-u", svc.unit, "-n", str(lines), "--no-pager", "-o", "short-iso"], root=True, timeout=15)
    return r.out or r.err


def status_text(svc: Service) -> str:
    scope = ["--user"] if svc.user else []
    return sh(["systemctl", *scope, "status", svc.unit, "--no-pager", "-n", "0"], timeout=10).out


# ---------------------------------------------------------------- login apps (autostart)

USER_AUTOSTART = HOME / ".config/autostart"
SYSTEM_AUTOSTART = [Path("/etc/xdg/autostart"), Path("/usr/share/gnome/autostart")]


@dataclass
class StartupApp:
    id: str  # desktop file name
    name: str
    comment: str
    exec: str
    enabled: bool
    system: bool  # comes from /etc/xdg/autostart
    user_file: str  # path in ~/.config/autostart if any
    source_file: str


def _parse_desktop(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    section = ""
    for line in read(path).splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        data.setdefault(k.strip(), v.strip())
    return data


def _is_enabled(d: dict[str, str]) -> bool:
    return not (d.get("Hidden", "").lower() == "true" or d.get("X-GNOME-Autostart-enabled", "").lower() == "false")


def _for_this_desktop(d: dict[str, str]) -> bool:
    desk = os.environ.get("XDG_CURRENT_DESKTOP", "GNOME").split(":")
    only = [x for x in d.get("OnlyShowIn", "").split(";") if x]
    notin = [x for x in d.get("NotShowIn", "").split(";") if x]
    if only and not set(only) & set(desk):
        return False
    return not set(notin) & set(desk)


def startup_apps(show_system: bool = True) -> list[StartupApp]:
    res: dict[str, StartupApp] = {}
    if show_system:
        for d in SYSTEM_AUTOSTART:
            for f in glob.glob(str(d / "*.desktop")):
                data = _parse_desktop(f)
                if data.get("NoDisplay", "").lower() == "true" or not _for_this_desktop(data):
                    continue  # GNOME hides these too (core desktop parts)
                fid = os.path.basename(f)
                res[fid] = StartupApp(fid, data.get("Name", fid), data.get("Comment", ""), data.get("Exec", ""), _is_enabled(data), True, "", f)
    for f in glob.glob(str(USER_AUTOSTART / "*.desktop")):
        data = _parse_desktop(f)
        fid = os.path.basename(f)
        base = res.get(fid)
        res[fid] = StartupApp(fid, data.get("Name", base.name if base else fid), data.get("Comment", base.comment if base else ""),
                              data.get("Exec", base.exec if base else ""), _is_enabled(data), base.system if base else False, f,
                              base.source_file if base else f)
    return sorted(res.values(), key=lambda a: a.name.lower())


def set_startup_enabled(app: StartupApp, enabled: bool) -> str:
    USER_AUTOSTART.mkdir(parents=True, exist_ok=True)
    target = USER_AUTOSTART / app.id
    if not target.exists():
        shutil.copy(app.source_file, target)
    lines = [ln for ln in read(target).splitlines() if not ln.startswith(("Hidden=", "X-GNOME-Autostart-enabled="))]
    out_lines, inserted = [], False
    for ln in lines:
        out_lines.append(ln)
        if ln.strip() == "[Desktop Entry]" and not inserted:
            out_lines.append(f"X-GNOME-Autostart-enabled={'true' if enabled else 'false'}")
            if not enabled:
                out_lines.append("Hidden=true")
            inserted = True
    target.write_text("\n".join(out_lines) + "\n")
    return f"{'enabled' if enabled else 'disabled'} {app.name}"


def add_startup(desktop_file: str) -> str:
    USER_AUTOSTART.mkdir(parents=True, exist_ok=True)
    dest = USER_AUTOSTART / os.path.basename(desktop_file)
    shutil.copy(desktop_file, dest)
    return f"added {dest.name}"


def remove_startup(app: StartupApp) -> str:
    if app.system:
        return set_startup_enabled(app, False)
    if app.user_file and os.path.exists(app.user_file):
        os.unlink(app.user_file)
    return f"removed {app.name}"


def launchable_apps() -> list[tuple[str, str]]:
    """(name, desktop file) for apps you could add to startup."""
    dirs = ["/usr/share/applications", str(HOME / ".local/share/applications"), "/var/lib/snapd/desktop/applications",
            "/var/lib/flatpak/exports/share/applications", str(HOME / ".local/share/flatpak/exports/share/applications")]
    res = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.desktop")):
            data = _parse_desktop(f)
            if data.get("NoDisplay", "").lower() == "true" or data.get("Type", "Application") != "Application":
                continue
            res[data.get("Name", os.path.basename(f))] = f
    return sorted(res.items(), key=lambda x: x[0].lower())
