"""Background services (systemd) and apps that start when you log in."""

from __future__ import annotations

import glob
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .run import HOME, Step, has, out, py_step, read, sh

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


# ================================================================ extras (2.1)
# Batched `systemctl show`, memory/CPU per service, blocking (mask), your own scripts as user services/timers (pm2-like),
# timers and cron jobs explained in plain English.

import json  # noqa: E402

UINT64_MAX = 2 ** 64 - 1


def parse_show(text: str) -> list[dict[str, str]]:
    """`systemctl show a b c -p …` -> one dict per unit (blocks are separated by blank lines)."""
    res: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                res.append(cur)
                cur = {}
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur[k] = v
    if cur:
        res.append(cur)
    return res


def show_num(v: str | None) -> int | None:
    """A number from `systemctl show`, or None for '[not set]', '' or the 'unknown' marker (2^64-1)."""
    if not v or not v.strip().isdigit():
        return None
    n = int(v)
    return None if n >= UINT64_MAX else n


def show_time(v: str | None) -> float | None:
    """'@1727280000' (with --timestamp=unix) -> unix time; anything else -> None."""
    if v and v.startswith("@"):
        try:
            t = float(v[1:])
            return t if t > 0 else None
        except ValueError:
            return None
    return None


def show_units(units: list[str], props: list[str], user: bool = False, chunk: int = 200) -> dict[str, dict[str, str]]:
    """One `systemctl show` call per `chunk` units -> {unit: {prop: value}}."""
    res: dict[str, dict[str, str]] = {}
    scope = ["--user"] if user else []
    props = list(dict.fromkeys(["Id", *props]))
    for i in range(0, len(units), chunk):
        part = units[i:i + chunk]
        text = out(["systemctl", *scope, "show", "--timestamp=unix", "-p", ",".join(props), "--", *part], timeout=20)
        for d in parse_show(text):
            if d.get("Id"):
                res[d["Id"]] = d
    return res


def resource_usage(units: list[str], user: bool = False) -> dict[str, dict]:
    """Memory (bytes) and CPU time (seconds) used by each running unit: {unit: {"mem", "cpu", "tasks", "pid"}}."""
    data = show_units(units, ["MemoryCurrent", "CPUUsageNSec", "TasksCurrent", "MainPID"], user)
    res = {}
    for unit, d in data.items():
        cpu = show_num(d.get("CPUUsageNSec"))
        res[unit] = {"mem": show_num(d.get("MemoryCurrent")), "cpu": cpu / 1e9 if cpu is not None else None,
                     "tasks": show_num(d.get("TasksCurrent")), "pid": show_num(d.get("MainPID"))}
    return res


def masked(user: bool = False) -> list[str]:
    """Service units that are blocked (masked): nothing can start them."""
    scope = ["--user"] if user else []
    text = out(["systemctl", *scope, "list-unit-files", "--type=service", "--state=masked", "--plain", "--no-legend", "--no-pager"], timeout=15)
    return sorted(u for u, st in parse_unit_files(text).items() if st.startswith("masked"))


def services_full(user: bool = False, usage: bool = True) -> list[Service]:
    """services() plus blocked units that aren't loaded, with .mem/.cpu set on running ones (for the desktop app)."""
    items = services(user)
    known = {s.unit for s in items}
    for unit in masked(user):
        if unit not in known:
            items.append(Service(unit, "masked", "inactive", "dead", "", "masked", user))
    for s in items:
        s.mem, s.cpu = None, None  # type: ignore[attr-defined]
        if s.load == "masked":
            s.enabled = "masked"
    if usage:
        running = [s.unit for s in items if s.active in ("active", "reloading", "activating") and s.sub != "exited"]
        use = resource_usage(running, user) if running else {}
        for s in items:
            u = use.get(s.unit)
            if u:
                s.mem, s.cpu = u["mem"], u["cpu"]  # type: ignore[attr-defined]
    return items


def mask_steps(svc: Service, block: bool) -> list[Step]:
    """Block (mask) or unblock (unmask) a service. Blocking also stops it now."""
    scope = ["--user"] if svc.user else []
    if block:
        return [Step(f"Block {svc.name} (stop it and never let it start)", ["systemctl", *scope, "mask", "--now", svc.unit], root=not svc.user)]
    return [Step(f"Unblock {svc.name}", ["systemctl", *scope, "unmask", svc.unit], root=not svc.user)]


# ---------------------------------------------------------------- timers

TIMER_EXPLAIN = {
    "apt-daily": "Downloads the list of available updates",
    "apt-daily-upgrade": "Installs security updates automatically",
    "fstrim": "Keeps SSDs fast (tells them which blocks are free)",
    "logrotate": "Compresses and removes old log files",
    "man-db": "Refreshes the manual-page index",
    "e2scrub_all": "Checks ext4 disks for errors in the background",
    "motd-news": "Fetches Ubuntu news for the terminal login message",
    "update-notifier-download": "Downloads data for updates that failed to install",
    "update-notifier-motd": "Checks for a new Ubuntu release",
    "fwupd-refresh": "Checks for firmware (BIOS/device) updates",
    "snapd.snap-repair": "Checks for fixes to the snap system",
    "systemd-tmpfiles-clean": "Deletes old temporary files",
    "dpkg-db-backup": "Backs up the list of installed packages",
    "anacron": "Runs daily/weekly jobs that were missed while the PC was off",
    "sysstat-collect": "Collects performance statistics",
    "sysstat-summary": "Summarises performance statistics",
    "plocate-updatedb": "Updates the file-name index for 'locate'",
    "ua-timer": "Ubuntu Pro status checks",
    "launchpadlib-cache-clean": "Cleans a developer-tools cache",
    "phpsessionclean": "Removes old PHP sessions",
    "certbot": "Renews HTTPS certificates",
    "pc-suspend-timer": "Sleep timer set in PC Command Center",
}


def explain_timer(unit: str) -> str:
    base = unit.removesuffix(".timer")
    if base.startswith("pc-") and base != "pc-suspend-timer":
        return "Your script (added in PC Command Center)"
    return TIMER_EXPLAIN.get(base, "")


TS = re.compile(r"[A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?: [A-Za-z+\-0-9]+)?")


def parse_list_timers(text: str, user: bool = False) -> list[dict]:
    """`systemctl list-timers --all --no-legend` -> [{unit, next, left, last, passed, activates, user}].

    Read from the right (UNIT and ACTIVATES are the last two words); NEXT and LAST are found by their timestamp shape,
    so it works however the columns are padded."""
    rows = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 2 or not cols[-2].endswith(".timer"):
            continue
        unit, act = cols[-2], cols[-1]
        head = line[:line.rindex(unit)].strip()
        stamps = list(TS.finditer(head))
        nxt = left = last = passed = ""
        if len(stamps) >= 2:
            nxt, last = stamps[0].group(0), stamps[1].group(0)
            left = head[stamps[0].end():stamps[1].start()].strip()
            passed = head[stamps[1].end():].strip()
        elif len(stamps) == 1:  # only NEXT (never ran yet) or only LAST (nothing scheduled any more)
            st = stamps[0]
            before, after = head[:st.start()].strip(), head[st.end():].strip()
            if before:
                last, passed = st.group(0), after
            else:
                nxt, left = st.group(0), after
        rows.append({"unit": unit, "next": nxt, "left": left, "last": last, "passed": passed, "activates": act, "user": user})
    for r in rows:
        for k in ("next", "last", "left", "passed"):
            r[k] = " ".join(w for w in r[k].split() if w not in ("-", "n/a"))
    return rows


def short_time(text: str) -> str:
    """'Fri 2026-09-25 14:30:00 CEST' -> 'Fri 25 Sep 14:30' (what list-timers prints, made shorter)."""
    m = re.match(r"(\w{3}) (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})", text or "")
    if not m:
        return text or ""
    return f"{m.group(1)} {int(m.group(4))} {MONTHS[int(m.group(3)) - 1][:3]} {m.group(5)}:{m.group(6)}"


def timers() -> list[dict]:
    rows = []
    for user in (False, True):
        scope = ["--user"] if user else []
        rows += parse_list_timers(out(["systemctl", *scope, "list-timers", "--all", "--no-pager", "--no-legend"], timeout=10), user)
    return rows


# ---------------------------------------------------------------- your scripts as user services / timers (pm2-like)

USER_UNITS = HOME / ".config/systemd/user"
PREFIX = "pc-"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
MODES = {"always": "Keep it running", "schedule": "Run it on a schedule", "login": "Run once each time I log in"}
EVERY_UNITS = {"minutes": "min", "hours": "h"}
RESERVED = {"suspend-timer"}


@dataclass
class ScriptSpec:
    name: str                 # short id (slug); the unit is pc-<name>
    command: str
    folder: str = ""          # working folder ("" = your home folder)
    mode: str = "always"      # always | schedule | login
    restart: bool = True      # always: restart if it crashes
    kind: str = "minutes"     # schedule: minutes | hours | daily | weekly
    every: int = 15           # schedule: every N minutes/hours
    at: str = "09:00"         # schedule: daily/weekly time HH:MM
    weekday: str = "Mon"      # schedule: weekly day
    boot: bool = False        # also run when nobody is logged in (loginctl enable-linger)

    @property
    def unit(self) -> str:
        return f"{PREFIX}{self.name}"


def slugify(text: str) -> str:
    """'My Discord Bot!' -> 'my-discord-bot' (letters, digits and dashes; max 40)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:40].strip("-")


def valid_time(text: str) -> bool:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60


def validate_spec(spec: ScriptSpec, existing: set[str] | None = None, editing: bool = False) -> str:
    """'' if fine, else a plain sentence saying what to fix."""
    if not spec.name or spec.name != slugify(spec.name):
        return "Give it a short name using letters, numbers and dashes (e.g. my-bot)."
    if spec.name in RESERVED:
        return "That name is used by the app itself; pick another one."
    if existing is not None and spec.name in existing and not editing:
        return f"You already have a script called {spec.name}."
    if not spec.command.strip():
        return "Type the command to run (the same thing you'd type in a terminal)."
    if spec.folder and not os.path.isdir(os.path.expanduser(spec.folder)):
        return f"The folder {spec.folder} doesn't exist."
    if spec.mode not in MODES:
        return "Pick when it should run."
    if spec.mode == "schedule":
        if spec.kind not in ("minutes", "hours", "daily", "weekly"):
            return "Pick how often it runs."
        if spec.kind in EVERY_UNITS and not (1 <= int(spec.every) <= (1440 if spec.kind == "minutes" else 720)):
            return "Pick how often it runs."
        if spec.kind in ("daily", "weekly") and not valid_time(spec.at):
            return "Type the time as HH:MM, for example 09:30."
        if spec.kind == "weekly" and spec.weekday not in WEEKDAYS:
            return "Pick a day of the week."
    return ""


def schedule_text(spec: ScriptSpec) -> str:
    """Plain English for when a script runs."""
    if spec.mode == "always":
        return "Keeps running" + (" and restarts if it crashes" if spec.restart else "") + (" (starts at boot)" if spec.boot else " (starts when you log in)")
    if spec.mode == "login":
        return "Runs once each time " + ("the PC starts" if spec.boot else "you log in")
    n = int(spec.every)
    if spec.kind == "minutes":
        return "Runs every minute" if n == 1 else f"Runs every {n} minutes"
    if spec.kind == "hours":
        return "Runs every hour" if n == 1 else f"Runs every {n} hours"
    hh, mm = (int(x) for x in spec.at.split(":"))
    if spec.kind == "daily":
        return f"Runs every day at {hh:02d}:{mm:02d}"
    return f"Runs every {WEEKDAY_NAMES.get(spec.weekday, spec.weekday)} at {hh:02d}:{mm:02d}"


def systemd_quote(arg: str) -> str:
    """Quote one ExecStart= argument for systemd: backslashes, quotes and newlines escaped; % and $ doubled."""
    s = arg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("\r", "")
    s = s.replace("%", "%%").replace("$", "$$")
    return f'"{s}"'


def exec_line(command: str) -> str:
    """Run the command through a login bash so PATH additions from ~/.profile (like ~/.local/bin) work."""
    return "/bin/bash -lc " + systemd_quote(command.strip())


def _plain_value(v: str) -> str:
    return v.replace("%", "%%").replace("\n", " ")


def unit_files(spec: ScriptSpec) -> dict[str, str]:
    """{file name: contents} for the service (and timer) of a script."""
    meta = json.dumps({k: getattr(spec, k) for k in ("name", "command", "folder", "mode", "restart", "kind", "every", "at", "weekday", "boot")})
    folder = os.path.abspath(os.path.expanduser(spec.folder.strip())) if spec.folder.strip() else "~"  # systemd only knows a bare "~"
    svc = [f"# pc-spec: {meta}", "# Made by PC Command Center. Edit or remove it there (Services > My scripts).", "[Unit]",
           f"Description={_plain_value(spec.name)} (your script, added by PC Command Center)"]
    if spec.mode == "always" and spec.restart:
        svc += ["StartLimitIntervalSec=300", "StartLimitBurst=10"]
    svc += ["", "[Service]", "Type=simple" if spec.mode == "always" else "Type=oneshot", f"WorkingDirectory={_plain_value(folder)}",
            f"ExecStart={exec_line(spec.command)}"]
    if spec.mode == "always" and spec.restart:
        svc += ["Restart=on-failure", "RestartSec=5"]
    if spec.mode in ("always", "login"):
        svc += ["", "[Install]", "WantedBy=default.target"]
    files = {f"{spec.unit}.service": "\n".join(svc) + "\n"}
    if spec.mode == "schedule":
        tm = ["# Made by PC Command Center (Services > My scripts).", "[Unit]",
              f"Description=Schedule for {_plain_value(spec.name)} ({schedule_text(spec)})", "", "[Timer]"]
        if spec.kind in EVERY_UNITS:
            tm += ["OnActiveSec=1min", f"OnUnitActiveSec={int(spec.every)}{EVERY_UNITS[spec.kind]}"]
        else:
            hh, mm = (int(x) for x in spec.at.split(":"))
            day = f"{spec.weekday} " if spec.kind == "weekly" else ""
            tm += [f"OnCalendar={day}*-*-* {hh:02d}:{mm:02d}:00", "Persistent=true"]
        tm += ["", "[Install]", "WantedBy=timers.target"]
        files[f"{spec.unit}.timer"] = "\n".join(tm) + "\n"
    return files


def parse_spec(text: str) -> ScriptSpec | None:
    m = re.search(r"^# pc-spec: (\{.*\})\s*$", text, re.M)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        return ScriptSpec(**{k: v for k, v in d.items() if k in ScriptSpec.__dataclass_fields__})
    except (ValueError, TypeError):
        return None


def _write_units(spec: ScriptSpec, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    files = unit_files(spec)
    for name, text in files.items():
        (folder / name).write_text(text)
    if spec.mode != "schedule":  # switching away from a schedule: drop the old timer
        try:
            (folder / f"{spec.unit}.timer").unlink()
        except OSError:
            pass
    return "wrote " + ", ".join(files)


def _short(p: Path) -> str:
    return f"~/{p.relative_to(HOME)}" if str(p).startswith(str(HOME) + "/") else str(p)


def create_script_steps(spec: ScriptSpec, editing: bool = False, folder: Path | None = None) -> list[Step]:
    folder = folder or USER_UNITS
    files = unit_files(spec)
    shown = "\n\n".join(f"write {_short(folder / n)}:\n{t.rstrip()}" for n, t in files.items())
    steps: list[Step] = []
    if editing:
        steps.append(Step("Stop the old version", ["systemctl", "--user", "disable", "--now", f"{spec.unit}.service", f"{spec.unit}.timer"],
                          optional=True, ok_codes=(0, 1, 5)))
    steps.append(py_step("Save the service files", lambda: _write_units(spec, folder), shown))
    steps.append(Step("Tell systemd about them", ["systemctl", "--user", "daemon-reload"]))
    if spec.mode == "schedule":
        steps.append(Step("Turn on the schedule", ["systemctl", "--user", "enable", "--now", f"{spec.unit}.timer"]))
    elif spec.mode == "login":
        steps.append(Step("Run it at every login (and once now)", ["systemctl", "--user", "enable", "--now", "--no-block", f"{spec.unit}.service"]))
    else:
        steps.append(Step("Start it now and at every login", ["systemctl", "--user", "enable", "--now", f"{spec.unit}.service"]))
    if spec.boot:
        steps.append(Step("Keep your scripts running when you're logged out", ["loginctl", "enable-linger", _username()]))
    return steps


def _username() -> str:
    import pwd
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get("USER", "")


def remove_script_steps(name: str, folder: Path | None = None) -> list[Step]:
    folder = folder or USER_UNITS
    unit = f"{PREFIX}{name}"
    paths = [folder / f"{unit}.service", folder / f"{unit}.timer"]

    def delete() -> str:
        gone = []
        for p in paths:
            try:
                p.unlink()
                gone.append(p.name)
            except OSError:
                pass
        return "deleted " + (", ".join(gone) or "nothing")
    return [Step("Stop it and turn it off", ["systemctl", "--user", "disable", "--now", f"{unit}.service", f"{unit}.timer"], optional=True,
                 ok_codes=(0, 1, 5)),
            py_step("Delete its files", delete, "rm " + " ".join(_short(p) for p in paths)),
            Step("Tell systemd", ["systemctl", "--user", "daemon-reload"]),
            Step("Forget its old state", ["systemctl", "--user", "reset-failed", f"{unit}.service"], optional=True, ok_codes=(0, 1, 5))]


def script_action_steps(name: str, action: str, scheduled: bool = False) -> list[Step]:
    unit = f"{PREFIX}{name}"
    if action == "run":
        return [Step(f"Run {name} now", ["systemctl", "--user", "start", "--no-block", f"{unit}.service"])]
    if action == "start":
        return [Step(f"Turn on {name}", ["systemctl", "--user", "enable", "--now", f"{unit}.timer" if scheduled else f"{unit}.service"])]
    if action == "stop":
        target = [f"{unit}.timer", f"{unit}.service"] if scheduled else [f"{unit}.service"]
        return [Step(f"Stop {name}" + (" and pause its schedule" if scheduled else ""), ["systemctl", "--user", "disable", "--now", *target])]
    if action == "restart":
        return [Step(f"Restart {name}", ["systemctl", "--user", "restart", f"{unit}.service"])]
    raise ValueError(action)


def user_manager_ok() -> bool:
    """True when your account's systemd is running (it always is in a normal desktop login)."""
    r = sh(["systemctl", "--user", "is-system-running"], timeout=5)
    return r.out.strip() in ("running", "degraded", "starting", "initializing")


def script_state(spec: ScriptSpec, svc: dict[str, str], tmr: dict[str, str]) -> tuple[tuple[str, str], bool]:
    """((pill text, kind), on?) for a script from its `systemctl show` properties."""
    active, sub = svc.get("ActiveState", ""), svc.get("SubState", "")
    if spec.mode == "schedule":
        on = tmr.get("ActiveState") == "active"
        if active in ("activating", "active") and sub in ("start", "running"):
            return ("running now", "info"), on
        if active == "failed":
            return ("last run failed", "bad"), on
        return (("scheduled", "ok") if on else ("paused", "neutral")), on
    on = active in ("active", "activating", "reloading")
    if active == "failed":
        return ("crashed", "bad"), False
    if sub == "auto-restart":
        return ("restarting", "warn"), True
    if on and sub == "running":
        return ("running", "ok"), True
    if on:
        return (("starting", "info") if active == "activating" else ("done", "ok")), True
    return ("stopped", "neutral"), False


def script_jobs(folder: Path | None = None) -> list[dict]:
    """Your pc-* scripts with their state: [{name, spec, when, state, on, since, last_exit, exit_code, restarts, mem, next_text, …}]."""
    folder = folder or USER_UNITS
    specs: dict[str, ScriptSpec] = {}
    for f in sorted(glob.glob(str(folder / f"{PREFIX}*.service"))):
        name = os.path.basename(f)[len(PREFIX):-len(".service")]
        text = read(f)
        spec = parse_spec(text)
        if spec is None:
            m = re.search(r"^ExecStart=(.*)$", text, re.M)
            spec = ScriptSpec(name=name, command=m.group(1) if m else "?", mode="schedule" if os.path.exists(f[:-8] + ".timer") else "always")
        spec.name = name
        specs[name] = spec
    if not specs:
        return []
    units = [f"{PREFIX}{n}.service" for n in specs] + [f"{PREFIX}{n}.timer" for n, s in specs.items() if s.mode == "schedule"]
    data = show_units(units, ["ActiveState", "SubState", "Result", "UnitFileState", "ExecMainStatus", "ExecMainStartTimestamp",
                              "ExecMainExitTimestamp", "ActiveEnterTimestamp", "NRestarts", "MemoryCurrent", "MainPID",
                              "LastTriggerUSec", "NextElapseUSecRealtime"], user=True)
    tm = {t["unit"]: t for t in parse_list_timers(out(["systemctl", "--user", "list-timers", "--all", "--no-pager", "--no-legend"], timeout=10), True)}
    res = []
    for name, spec in specs.items():
        s = data.get(f"{PREFIX}{name}.service", {})
        t = data.get(f"{PREFIX}{name}.timer", {})
        state, on = script_state(spec, s, t)
        tinfo = tm.get(f"{PREFIX}{name}.timer", {})
        res.append({"name": name, "unit": f"{PREFIX}{name}", "spec": spec, "when": schedule_text(spec), "state": state, "on": on,
                    "active": s.get("ActiveState", ""), "sub": s.get("SubState", ""), "result": s.get("Result", ""),
                    "exit_code": show_num(s.get("ExecMainStatus")), "last_start": show_time(s.get("ExecMainStartTimestamp")),
                    "last_exit": show_time(s.get("ExecMainExitTimestamp")), "since": show_time(s.get("ActiveEnterTimestamp")),
                    "restarts": show_num(s.get("NRestarts")) or 0, "mem": show_num(s.get("MemoryCurrent")),
                    "pid": show_num(s.get("MainPID")) or None, "next": show_time(t.get("NextElapseUSecRealtime")),
                    "next_text": tinfo.get("left") or tinfo.get("next", ""), "last_trigger": show_time(t.get("LastTriggerUSec"))})
    return res


def script_logs(name: str, lines: int = 300) -> str:
    unit = f"{PREFIX}{name}.service"
    r = sh(["journalctl", "--user", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"], timeout=15)
    text = r.out.strip()
    if not text or text.startswith("-- No entries --"):
        r2 = sh(["journalctl", f"_SYSTEMD_USER_UNIT={unit}", "-n", str(lines), "--no-pager", "-o", "short-iso"], timeout=15)
        text = r2.out.strip() or text
    return text


def guess_command(path: str) -> str:
    """A command line that runs a script file you picked."""
    import shlex
    q = shlex.quote(path)
    ext = os.path.splitext(path)[1].lower()
    runner = {".py": "python3", ".sh": "bash", ".js": "node", ".mjs": "node", ".ts": "npx tsx", ".rb": "ruby", ".pl": "perl", ".php": "php"}.get(ext)
    if runner:
        return f"{runner} {q}"
    if os.access(path, os.X_OK):
        return q
    return f"bash {q}"


# ---------------------------------------------------------------- cron jobs in plain English

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
CRON_SPECIAL = {"@reboot": "every time the PC starts", "@yearly": "once a year (1 January at 00:00)", "@annually": "once a year (1 January at 00:00)",
                "@monthly": "once a month (the 1st at 00:00)", "@weekly": "once a week (Sunday at 00:00)", "@daily": "every day at 00:00",
                "@midnight": "every day at 00:00", "@hourly": "every hour, on the hour"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _names(field: str, names: list[str], offset: int) -> str:
    low = [n[:3].lower() for n in names]

    def sub(m: re.Match) -> str:
        return str(low.index(m.group(0).lower()) + offset)
    return re.sub(r"[A-Za-z]{3}", sub, field)


def cron_values(field: str, lo: int, hi: int) -> list[int]:
    """Expand one cron field ('*/15', '1-5', '0,30', '10-20/5') into its values."""
    vals: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step <= 0:
                raise ValueError(field)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = int(part)
            b = hi if step > 1 else a
        if a < lo or b > hi or a > b:
            raise ValueError(field)
        vals.update(range(a, b + 1, step))
    return sorted(vals)


def _hours_window(hr: str) -> str:
    m = re.fullmatch(r"(\d+)-(\d+)", hr)
    if m:
        return f"from {int(m.group(1)):02d}:00 to {int(m.group(2)):02d}:59"
    m = re.fullmatch(r"\*/(\d+)", hr)
    if m:
        return f"during every {_ordinal(int(m.group(1)))} hour"
    hours = cron_values(hr, 0, 23)
    if len(hours) == 1:
        return f"from {hours[0]:02d}:00 to {hours[0]:02d}:59"
    return "during the " + _join([f"{h:02d}:00" for h in hours]) + " hours"


def _cron_time(mi: str, hr: str) -> tuple[str, bool]:
    """(text, is_specific_times)."""
    ms = re.fullmatch(r"\*/(\d+)", mi)
    hs = re.fullmatch(r"\*/(\d+)", hr)
    if mi == "*" or ms:
        n = int(ms.group(1)) if ms else 1
        base = "every minute" if n == 1 else f"every {n} minutes"
        return (base, False) if hr == "*" else (f"{base} {_hours_window(hr)}", False)
    mins = cron_values(mi, 0, 59)
    if hr == "*":
        step = mins[1] - mins[0] if len(mins) > 1 else 0
        if len(mins) > 1 and mins[0] == 0 and 60 % step == 0 and mins == list(range(0, 60, step)):
            return f"every {step} minutes", False
        if len(mins) == 1:
            return ("every hour, on the hour" if mins[0] == 0 else f"every hour at {mins[0]} minutes past"), False
        return f"every hour at {_join([str(m) for m in mins])} minutes past", False
    if hs and len(mins) == 1:
        n = int(hs.group(1))
        every = "every hour" if n == 1 else f"every {n} hours"
        return (f"{every}, on the hour" if mins[0] == 0 else f"{every} at {mins[0]} minutes past"), False
    hours = cron_values(hr, 0, 23)
    times = [f"{h:02d}:{m:02d}" for h in hours for m in mins]
    if len(times) <= 6:
        return "at " + _join(times), True
    rng = re.fullmatch(r"(\d+)-(\d+)", hr)
    if rng and len(mins) == 1:
        return f"every hour from {int(rng.group(1)):02d}:{mins[0]:02d} to {int(rng.group(2)):02d}:{mins[0]:02d}", False
    return f"{len(times)} times a day", False


def _dow_text(dow: str) -> str:
    days = sorted({d % 7 for d in cron_values(dow, 0, 7)})
    if days == [1, 2, 3, 4, 5]:
        return "on weekdays (Mon–Fri)"
    if days == [0, 6]:
        return "on weekends"
    if len(days) == 1:
        return f"every {DAYS[days[0]]}"
    if len(days) == 7:
        return ""
    return "on " + _join([DAYS[d][:3] for d in (days[1:] + days[:1] if days[0] == 0 else days)])


def _dom_text(dom: str, every_month: bool) -> str:
    m = re.fullmatch(r"\*/(\d+)", dom)
    if m:
        return f"every {int(m.group(1))} days"
    days = cron_values(dom, 1, 31)
    tail = " of every month" if every_month else ""
    if len(days) <= 4:
        return "on the " + _join([_ordinal(d) for d in days]) + tail
    return f"on days {dom}{tail}"


def _mon_text(mon: str) -> str:
    m = re.fullmatch(r"\*/(\d+)", mon)
    if m:
        return f"every {int(m.group(1))} months"
    months = cron_values(mon, 1, 12)
    if len(months) == 1:
        return f"in {MONTHS[months[0] - 1]}"
    return "in " + _join([MONTHS[x - 1][:3] for x in months])


def cron_to_english(expr: str) -> str:
    """'*/15 * * * *' -> 'every 15 minutes'; '0 9 * * 1-5' -> 'on weekdays (Mon–Fri) at 09:00'."""
    expr = expr.strip()
    if expr.startswith("@"):
        return CRON_SPECIAL.get(expr.split()[0].lower(), expr)
    parts = expr.split()
    if len(parts) != 5:
        return expr
    mi, hr, dom, mon, dow = parts
    try:
        mon = _names(mon, MONTHS, 1)
        dow = _names(dow, DAYS, 0)
        time_txt, specific = _cron_time(mi, hr)
        if dom != "*" and mon != "*" and dow == "*" and dom.isdigit() and mon.isdigit():
            if not (1 <= int(mon) <= 12 and 1 <= int(dom) <= 31):
                raise ValueError(expr)
            day_txt = f"every year on {int(dom)} {MONTHS[int(mon) - 1]}"
        else:
            days = []
            if dom != "*":
                days.append(_dom_text(dom, mon == "*"))
            if dow != "*":
                d = _dow_text(dow)
                if d:
                    days.append(d)
            day_txt = " or ".join(days)
            if mon != "*":
                day_txt = (day_txt + " " if day_txt else "") + _mon_text(mon)
    except (ValueError, IndexError):
        return f"cron schedule “{expr}”"
    if specific:
        if not day_txt or day_txt.startswith("in "):
            day_txt = "every day" + (" " + day_txt if day_txt else "")
        return f"{day_txt} {time_txt}"
    return time_txt + (f", {day_txt}" if day_txt else "")


@dataclass
class CronJob:
    source: str
    schedule: str
    when: str
    user: str
    command: str
    line: str


def parse_crontab(text: str, system: bool = False, source: str = "", owner: str = "") -> list[CronJob]:
    """User crontab (5 fields + command) or system crontab (5 fields + user + command). Comments and VAR=value lines are skipped."""
    res = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            continue
        if line.startswith("@"):
            parts = line.split(None, 2 if system else 1)
            if len(parts) < (3 if system else 2):
                continue
            sched = parts[0]
            user, cmd = (parts[1], parts[2]) if system else (owner, parts[1])
        else:
            parts = line.split(None, 6 if system else 5)
            if len(parts) < (7 if system else 6):
                continue
            sched = " ".join(parts[:5])
            user, cmd = (parts[5], parts[6]) if system else (owner, parts[5])
        res.append(CronJob(source, sched, cron_to_english(sched), user, cmd.strip(), line))
    return res


CRON_SCRIPTS = {
    "apt-compat": "Starts the daily check for software updates", "dpkg": "Backs up the list of installed packages",
    "logrotate": "Compresses and removes old log files", "man-db": "Refreshes the manual-page index",
    "popularity-contest": "Sends anonymous package-usage statistics (only if you opted in)", "bsdmainutils": "Old calendar reminders (harmless)",
    "apport": "Cleans up old crash reports", "plocate": "Updates the file-name index for 'locate'", "mlocate": "Updates the file-name index for 'locate'",
    "sysstat": "Collects performance statistics", "0anacron": "Notes that the periodic jobs ran (for anacron)",
    "e2scrub_all": "Checks ext4 disks for errors in the background", "google-chrome": "Keeps the Google Chrome software source set up",
    "microsoft-edge": "Keeps the Microsoft Edge software source set up", "code": "Keeps the VS Code software source set up",
    "update-notifier-common": "Checks for updates to show notifications", "chkrootkit": "Scans for rootkits", "rkhunter": "Scans for rootkits",
    "anacron": "Runs daily/weekly jobs that were missed while the PC was off", "php": "Removes old PHP sessions", "certbot": "Renews HTTPS certificates",
    "zfsutils-linux": "Checks ZFS pools", "exim4-base": "Mail server housekeeping", "spamassassin": "Updates spam rules",
    "brave-browser": "Keeps the Brave software source set up", "opera-stable": "Keeps the Opera software source set up",
}
PERIODIC = [("hourly", "Every hour", "Run at 17 minutes past each hour (from /etc/crontab)."),
            ("daily", "Every day", "Around 06:25, or soon after the PC starts if it was off then."),
            ("weekly", "Every week", "Sunday around 06:47, or later if the PC was off."),
            ("monthly", "Every month", "The 1st around 06:52, or later if the PC was off.")]


def cron_explain(name: str) -> str:
    return CRON_SCRIPTS.get(os.path.basename(name), "")


def cron_jobs(etc: str = "/etc") -> dict:
    """Your crontab, the system crontabs and the periodic script folders, with plain-English schedules."""
    me = _username()
    installed = has("crontab") or os.path.exists("/usr/sbin/cron") or os.path.exists(os.path.join(etc, "crontab"))
    user: list[CronJob] = []
    if has("crontab"):
        r = sh(["crontab", "-l"], timeout=5)
        if r.ok:
            user = parse_crontab(r.out, False, "Your crontab", me)
    system = parse_crontab(read(os.path.join(etc, "crontab")), True, "/etc/crontab")
    for f in sorted(glob.glob(os.path.join(etc, "cron.d", "*"))):
        if os.path.basename(f).startswith(".") or f.endswith((".dpkg-old", ".dpkg-dist", "~")):
            continue
        system += parse_crontab(read(f), True, f"/etc/cron.d/{os.path.basename(f)}")
    periodic = {}
    for key, _t, _d in PERIODIC:
        d = os.path.join(etc, f"cron.{key}")
        try:
            names = sorted(n for n in os.listdir(d) if not n.startswith(".") and "." not in n)
        except OSError:
            names = []
        periodic[key] = [(n, cron_explain(n)) for n in names]
    return {"installed": installed, "user": user, "system": system, "periodic": periodic, "me": me, "has_crontab": has("crontab")}
