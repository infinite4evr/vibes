"""Apps and updates across apt, snap, flatpak and AppImages."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .run import HOME, Step, has, out, read, sh

APT_ENV = {"DEBIAN_FRONTEND": "noninteractive"}


# ---------------------------------------------------------------- updates

@dataclass
class Update:
    source: str  # apt | snap | flatpak | firmware
    name: str
    current: str
    new: str
    security: bool = False


def parse_apt_upgradable(text: str) -> list[Update]:
    res = []
    for line in text.splitlines():
        m = re.match(r"^(\S+?)/(\S+)\s+(\S+)\s+\S+\s+\[upgradable from: ([^\]]+)\]", line)
        if m:
            res.append(Update("apt", m.group(1), m.group(4), m.group(3), "-security" in m.group(2)))
    return res


def parse_snap_refresh(text: str) -> list[Update]:
    res = []
    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith("Name"):
        return res
    for line in lines[1:]:
        cols = line.split()
        if len(cols) >= 2:
            res.append(Update("snap", cols[0], "", cols[1]))
    return res


def parse_flatpak_updates(text: str) -> list[Update]:
    res = []
    for line in text.splitlines():
        cols = line.split("\t")
        if cols and cols[0].strip() and "." in cols[0]:
            res.append(Update("flatpak", cols[0].strip(), "", cols[1].strip() if len(cols) > 1 else ""))
    return res


def pending_updates() -> list[Update]:
    ups = parse_apt_upgradable(out(["apt", "list", "--upgradable"], timeout=60))
    if has("snap"):
        ups += parse_snap_refresh(out(["snap", "refresh", "--list"], timeout=60))
    if has("flatpak"):
        ups += parse_flatpak_updates(out(["flatpak", "remote-ls", "--updates", "--columns=application,version"], timeout=60))
    return ups


def last_apt_update() -> float | None:
    for p in ("/var/lib/apt/periodic/update-success-stamp", "/var/lib/apt/lists/partial", "/var/cache/apt/pkgcache.bin"):
        try:
            return os.path.getmtime(p)
        except OSError:
            continue
    return None


def refresh_steps() -> list[Step]:
    return [Step("Check for new apt updates", ["apt-get", "update"], root=True)]


def update_all_steps(include_firmware: bool = False) -> list[Step]:
    steps = [
        Step("Check for updates", ["apt-get", "update"], root=True),
        Step("Install system updates", ["apt-get", "full-upgrade", "-y", "-o", "Dpkg::Options::=--force-confold"], root=True, env=APT_ENV),
        Step("Remove packages no longer needed", ["apt-get", "autoremove", "--purge", "-y"], root=True, env=APT_ENV, optional=True),
    ]
    if has("snap"):
        steps.append(Step("Update snaps", ["snap", "refresh"], root=True, optional=True))
    if has("flatpak"):
        steps.append(Step("Update Flatpak apps", ["flatpak", "update", "-y", "--noninteractive"], optional=True))
    if include_firmware and has("fwupdmgr"):
        steps.append(Step("Update firmware", ["fwupdmgr", "update", "-y", "--no-reboot-check"], root=True, optional=True))
    return steps


def security_only_steps() -> list[Step]:
    if has("unattended-upgrade"):
        return [Step("Check for updates", ["apt-get", "update"], root=True),
                Step("Install security updates only", ["unattended-upgrade", "-v"], root=True)]
    return update_all_steps()


def firmware_updates() -> list[str]:
    if not has("fwupdmgr"):
        return []
    text = out(["fwupdmgr", "get-updates", "--json"], timeout=40)
    return re.findall(r'"Name"\s*:\s*"([^"]+)"', text)[:10]


def auto_updates_enabled() -> bool:
    text = "".join(read(p) for p in glob.glob("/etc/apt/apt.conf.d/*auto-upgrades*"))
    return bool(re.search(r'APT::Periodic::Unattended-Upgrade\s+"1"', text))


# ---------------------------------------------------------------- installed apps

@dataclass
class App:
    source: str  # apt | snap | flatpak | appimage | manual
    id: str
    name: str
    version: str = ""
    size: int = 0
    summary: str = ""
    location: str = ""  # flatpak: user/system
    desktop: str = ""


def _desktop_name(path: str) -> tuple[str, bool]:
    text = read(path)
    name = re.search(r"^Name=(.*)$", text, re.M)
    hidden = bool(re.search(r"^(NoDisplay|Hidden)=true", text, re.M))
    return (name.group(1).strip() if name else os.path.basename(path)), hidden


def apt_apps() -> list[App]:
    """apt packages that put an app in your app grid."""
    files = [f for f in glob.glob("/usr/share/applications/*.desktop")]
    visible = {}
    for f in files:
        name, hidden = _desktop_name(f)
        if not hidden:
            visible[f] = name
    if not visible:
        return []
    r = sh(["dpkg", "-S", *visible.keys()], timeout=30)
    owners: dict[str, list[str]] = {}
    for line in r.out.splitlines():
        pkg, _, path = line.partition(": ")
        for p in pkg.split(", "):
            owners.setdefault(p.split(":")[0], []).append(path.strip())
    if not owners:
        return []
    info = sh(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Installed-Size}\t${binary:Summary}\n", *owners.keys()], timeout=30)
    apps = []
    for line in info.out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        pkg, ver, kb, summary = parts[0].split(":")[0], parts[1], parts[2], parts[3]
        paths = owners.get(pkg, [])
        label = visible.get(paths[0], pkg) if paths else pkg
        apps.append(App("apt", pkg, label, ver, int(kb) * 1024 if kb.isdigit() else 0, summary, desktop=paths[0] if paths else ""))
    return apps


def apt_manual() -> list[App]:
    """Every package you (or the installer) explicitly asked for."""
    names = out(["apt-mark", "showmanual"], timeout=30).split()
    if not names:
        return []
    info = sh(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Installed-Size}\t${binary:Summary}\n", *names], timeout=60)
    res = []
    for line in info.out.splitlines():
        p = line.split("\t")
        if len(p) >= 4:
            res.append(App("apt", p[0], p[0], p[1], int(p[2]) * 1024 if p[2].isdigit() else 0, p[3]))
    return res


def parse_snap_list(text: str) -> list[App]:
    res = []
    lines = text.strip().splitlines()
    for line in lines[1:]:
        cols = line.split()
        if len(cols) >= 4:
            notes = cols[5] if len(cols) > 5 else ""
            if notes in ("base", "core", "snapd") or cols[0] in ("snapd", "bare") or cols[0].startswith(("core", "gnome-", "gtk-common", "kf5-", "kf6-", "mesa-")):
                continue
            res.append(App("snap", cols[0], cols[0], cols[1]))
    return res


def snap_apps() -> list[App]:
    if not has("snap"):
        return []
    apps = parse_snap_list(out(["snap", "list"], timeout=30))
    for a in apps:
        f = glob.glob(f"/var/lib/snapd/snaps/{a.id}_*.snap")
        a.size = max((os.path.getsize(x) for x in f), default=0)
        d = glob.glob(f"/var/lib/snapd/desktop/applications/{a.id}_*.desktop")
        if d:
            a.name, _ = _desktop_name(d[0])
    return apps


def parse_flatpak_list(text: str) -> list[App]:
    res = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 5:
            res.append(App("flatpak", cols[0], cols[1], cols[2], _parse_size(cols[3]), location=cols[4].strip()))
    return res


def _parse_size(text: str) -> int:
    m = re.match(r"([\d.,]+)\s*([kMGT]?B)", text.strip().replace("\xa0", " "))
    if not m:
        return 0
    mult = {"B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}.get(m.group(2), 1)
    return int(float(m.group(1).replace(",", ".")) * mult)


def flatpak_apps() -> list[App]:
    if not has("flatpak"):
        return []
    return parse_flatpak_list(out(["flatpak", "list", "--app", "--columns=application,name,version,size,installation"], timeout=30))


def appimages() -> list[App]:
    res = []
    for d in (HOME / "Apps", HOME / "Applications", HOME / "AppImages", HOME / "Downloads"):
        for f in glob.glob(str(d / "**/*.AppImage"), recursive=True) + glob.glob(str(d / "*.appimage")):
            res.append(App("appimage", f, Path(f).stem, size=os.path.getsize(f), location=f.replace(str(HOME), "~")))
    for d in (HOME / "Apps",):
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir() and not any(a.id.startswith(str(sub)) for a in res):
                    res.append(App("manual", str(sub), sub.name, location=str(sub).replace(str(HOME), "~")))
    return res


def all_apps() -> list[App]:
    apps = apt_apps() + snap_apps() + flatpak_apps() + appimages()
    apps.sort(key=lambda a: a.name.lower())
    return apps


def remove_steps(app: App) -> list[Step]:
    if app.source == "apt":
        return [Step(f"Uninstall {app.name}", ["apt-get", "purge", "-y", app.id], root=True, env=APT_ENV),
                Step("Remove leftovers it pulled in", ["apt-get", "autoremove", "--purge", "-y"], root=True, env=APT_ENV, optional=True)]
    if app.source == "snap":
        return [Step(f"Uninstall {app.name}", ["snap", "remove", "--purge", app.id], root=True)]
    if app.source == "flatpak":
        system = app.location == "system"
        return [Step(f"Uninstall {app.name}", ["flatpak", "uninstall", "-y", "--noninteractive", "--delete-data", "--system" if system else "--user", app.id], root=system)]
    if app.source in ("appimage", "manual"):
        return [Step(f"Move {app.name} to Trash", ["gio", "trash", app.id])]
    return []


# ---------------------------------------------------------------- search + install

def search(query: str) -> list[App]:
    q = query.strip()
    if not q:
        return []
    res: list[App] = []
    for line in out(["apt-cache", "search", "--names-only", q], timeout=20).splitlines()[:40]:
        name, _, summary = line.partition(" - ")
        res.append(App("apt", name.strip(), name.strip(), summary=summary.strip()))
    if has("snap"):
        lines = out(["snap", "find", q], timeout=25).splitlines()
        for line in lines[1:15]:
            cols = line.split(None, 4)
            if len(cols) >= 4:
                res.append(App("snap", cols[0], cols[0], cols[1], summary=cols[-1] if len(cols) == 5 else "", location=cols[3]))
    if has("flatpak"):
        for line in out(["flatpak", "search", "--columns=application,name,version,description", q], timeout=25).splitlines()[:15]:
            cols = line.split("\t")
            if len(cols) >= 2 and "." in cols[0]:
                res.append(App("flatpak", cols[0].strip(), cols[1].strip(), cols[2].strip() if len(cols) > 2 else "", summary=cols[3].strip() if len(cols) > 3 else ""))
    installed = {(a.source, a.id) for a in all_apps()}
    ql = q.lower()
    res.sort(key=lambda a: (a.name.lower() != ql and a.id.lower() != ql, not a.name.lower().startswith(ql), a.source != "apt"))
    for a in res:
        if (a.source, a.id) in installed:
            a.location = "installed"
    return res


def install_steps(app: App) -> list[Step]:
    if app.source == "apt":
        return [Step(f"Install {app.name}", ["apt-get", "install", "-y", app.id], root=True, env=APT_ENV)]
    if app.source == "snap":
        extra = ["--classic"] if "classic" in app.location else []
        return [Step(f"Install {app.name}", ["snap", "install", app.id, *extra], root=True)]
    if app.source == "flatpak":
        return [Step("Make sure Flathub is set up", ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
                                                     "https://dl.flathub.org/repo/flathub.flatpakrepo"], optional=True),
                Step(f"Install {app.name}", ["flatpak", "install", "-y", "--noninteractive", "--user", "flathub", app.id])]
    return []


# ---------------------------------------------------------------- history

def parse_apt_history(text: str) -> list[dict]:
    """Entries from /var/log/apt/history.log: when, what command, and which packages changed."""
    res = []
    for block in text.split("\n\n"):
        start = re.search(r"^Start-Date: (.+)$", block, re.M)
        if not start:
            continue
        entry = {"date": start.group(1).strip(), "cmd": "", "installed": [], "upgraded": [], "removed": []}
        cmd = re.search(r"^Commandline: (.+)$", block, re.M)
        req = re.search(r"^Requested-By: (\S+)", block, re.M)
        entry["cmd"] = (cmd.group(1).strip() if cmd else "automatic (unattended-upgrades)") + (f"  [{req.group(1)}]" if req else "")
        for key, field_ in (("Install", "installed"), ("Upgrade", "upgraded"), ("Remove", "removed"), ("Purge", "removed")):
            m = re.search(rf"^{key}: (.+)$", block, re.M)
            if m:
                entry[field_] += [p.split(":")[0] for p in re.findall(r"(\S+?) \(", m.group(1) + " ")]
        res.append(entry)
    return res


def apt_history(limit: int = 60) -> list[dict]:
    import gzip
    texts = [read("/var/log/apt/history.log")]
    for f in sorted(glob.glob("/var/log/apt/history.log.*.gz"))[:3]:
        try:
            texts.append(gzip.open(f, "rt", errors="replace").read())
        except OSError:
            pass
    entries = []
    for t in texts:
        entries += parse_apt_history(t)
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]


def obsolete_packages() -> list[str]:
    """Installed packages that no repository offers anymore (often leftovers from old Ubuntu versions)."""
    return [ln.split("/")[0] for ln in out(["apt", "list", "?obsolete"], timeout=60).splitlines() if "/" in ln]
