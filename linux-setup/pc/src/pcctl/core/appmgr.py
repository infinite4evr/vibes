"""App management beyond install/remove: install from a file, AppImage integration, uninstall several at once,
app permissions (Snap + Flatpak), the same app installed twice, apps you never open, and the default terminal.

No GTK here: the desktop page, the terminal UI and the CLI can all use these.
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .packages import APT_ENV, App
from .run import HOME, Step, has, out, py_step, read, sh

# ---------------------------------------------------------------- small helpers


def parse_desktop_entry(text: str) -> dict[str, str]:
    """Keys of the [Desktop Entry] section (first value wins, localized keys like Name[de] are kept separately)."""
    data: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        data.setdefault(k.strip(), v.strip())
    return data


def exec_target(exec_line: str) -> str:
    """The program an Exec= line runs (skips `env VAR=x` prefixes and field codes)."""
    try:
        parts = shlex.split(exec_line.replace("%%", "%"))
    except ValueError:
        parts = exec_line.split()
    while parts and (parts[0] == "env" or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[0])):
        parts.pop(0)
    return parts[0] if parts else ""


def desktop_quote(arg: str) -> str:
    """Quote one argument for an Exec= line (desktop entry spec: quoting rules, then string escaping, then %%)."""
    arg = arg.replace("%", "%%")
    if not re.search(r"[\s\"'\\><~|&;$*?#()`]", arg):
        return arg
    inner = re.sub(r'(["`$\\])', r"\\\1", arg)
    inner = inner.replace("\\", "\\\\")
    return f'"{inner}"'


def _home_short(p: str) -> str:
    h = str(HOME)
    return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p


# ---------------------------------------------------------------- E1: install from a file

FILE_KINDS = {".deb": "deb", ".flatpakref": "flatpakref", ".flatpak": "flatpak", ".appimage": "appimage", ".snap": "snap"}
FILE_PATTERNS = ["*.deb", "*.flatpakref", "*.flatpak", "*.AppImage", "*.appimage", "*.snap"]
KIND_TITLE = {"deb": "Ubuntu package (.deb)", "flatpakref": "Flatpak link (.flatpakref)", "flatpak": "Flatpak bundle (.flatpak)",
              "appimage": "AppImage", "snap": "Snap file (.snap)"}


def file_kind(path: str | Path) -> str | None:
    p = str(path).lower()
    for ext, kind in FILE_KINDS.items():
        if p.endswith(ext):
            return kind
    return None


def parse_deb_fields(text: str) -> dict[str, str]:
    """`dpkg-deb -f file.deb` → {Package, Version, Description, Installed-Size, Depends, ...}."""
    fields: dict[str, str] = {}
    key = None
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] += "\n" + line.strip()
            continue
        k, sep, v = line.partition(":")
        if sep and k and " " not in k:
            key = k.strip()
            fields[key] = v.strip()
    return fields


def parse_apt_simulate(text: str) -> dict[str, list[tuple[str, str]]]:
    """`apt-get -s install ./x.deb`: what would be installed, upgraded and removed as (package, version)."""
    res: dict[str, list[tuple[str, str]]] = {"install": [], "upgrade": [], "remove": []}
    for line in text.splitlines():
        m = re.match(r"^Inst (\S+) (\[([^\]]+)\] )?\((\S+)", line)
        if m:
            res["upgrade" if m.group(2) else "install"].append((m.group(1), m.group(4)))
            continue
        m = re.match(r"^Remv (\S+)(?: \[([^\]]+)\])?", line)
        if m:
            res["remove"].append((m.group(1), m.group(2) or ""))
    return res


def deb_preview(path: str) -> dict:
    """What installing a .deb would do, without changing anything."""
    path = os.path.abspath(os.path.expanduser(path))
    fields = parse_deb_fields(out(["dpkg-deb", "-f", path], timeout=20)) if has("dpkg-deb") else {}
    r = sh(["apt-get", "-s", "-q", "install", path], timeout=60)
    sim = parse_apt_simulate(r.out)
    err = ""
    if not r.ok:
        err = "\n".join(ln for ln in (r.out + "\n" + r.err).splitlines() if ln.startswith(("E:", " ", "The following packages have unmet"))).strip()
        err = err or r.err.strip() or "apt could not work out how to install this file."
    return {"path": path, "fields": fields, "error": err, **sim}


def parse_flatpakref(text: str) -> dict[str, str]:
    """[Flatpak Ref] Name=, Title=, Url=, Branch=, IsRuntime= (also works for .flatpakrepo)."""
    data: dict[str, str] = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep and not line.startswith(("#", "[")):
            data.setdefault(k.strip(), v.strip())
    return data


def describe_file(path: str) -> dict:
    """Name, kind and size of an installable file, for the confirmation text."""
    kind = file_kind(path) or ""
    info = {"path": path, "kind": kind, "file": os.path.basename(path), "name": os.path.basename(path), "size": 0, "extra": {}}
    try:
        info["size"] = os.path.getsize(path)
    except OSError:
        pass
    if kind == "flatpakref":
        ref = parse_flatpakref(read(path))
        info["extra"] = ref
        info["name"] = (ref.get("Title") or ref.get("Name") or info["name"]).removesuffix(" from flathub")
    elif kind == "appimage":
        info["name"] = appimage_name(path)
    elif kind in ("snap", "flatpak", "deb"):
        info["name"] = re.split(r"[_]", Path(path).stem)[0] or info["name"]
    return info


def install_file_steps(path: str, kind: str | None = None, name: str = "") -> list[Step]:
    """Steps that install a downloaded file. AppImages go through integrate_steps() instead."""
    path = os.path.abspath(os.path.expanduser(path))
    kind = kind or file_kind(path)
    name = name or os.path.basename(path)
    if kind == "deb":
        return [Step(f"Install {name}", ["apt-get", "install", "-y", path], root=True, env=APT_ENV)]
    if kind in ("flatpakref", "flatpak"):
        steps = []
        if not has("flatpak"):
            steps.append(Step("Install Flatpak support", ["apt-get", "install", "-y", "flatpak"], root=True, env=APT_ENV))
        steps.append(Step(f"Install {name}", ["flatpak", "install", "--user", "-y", "--noninteractive",
                                              "--from" if kind == "flatpakref" else "--bundle", path]))
        return steps
    if kind == "snap":
        steps = []
        if not has("snap"):
            steps.append(Step("Install Snap support", ["apt-get", "install", "-y", "snapd"], root=True, env=APT_ENV))
        steps.append(Step(f"Install {name} (not checked by the Snap Store)", ["snap", "install", "--dangerous", path], root=True))
        return steps
    if kind == "appimage":
        return integrate_steps(path, "keep")
    return []


# ---------------------------------------------------------------- E2: AppImages

APPS_DIR = HOME / "Applications"
DESKTOP_DIR = HOME / ".local/share/applications"
ICON_DIR = HOME / ".local/share/icons/pc-appimages"
LOOSE_DIRS = [HOME / "Downloads", HOME / "Applications", HOME / "Apps", HOME / "AppImages", HOME / "Desktop", HOME / ".local/bin"]
GENERIC_ICON = "application-x-executable"


@dataclass
class AppImage:
    path: str
    name: str
    size: int = 0
    mtime: float = 0.0
    executable: bool = False
    desktop: str = ""     # the .desktop file that puts it in the app grid ("" = not in the grid)
    icon: str = ""
    ours: bool = False    # added by PC Command Center
    exists: bool = True

    @property
    def short(self) -> str:
        return _home_short(self.path)


def appimage_name(filename: str) -> str:
    """'LM-Studio-0.3.5-2-x64.AppImage' → 'LM Studio', 'cursor-0.42.3-x86_64.AppImage' → 'Cursor'."""
    stem = re.sub(r"\.appimage$", "", os.path.basename(filename), flags=re.I)
    stem = re.sub(r"[-_.](x86[-_]64|amd64|aarch64|arm64|x64|i386|i686|armhf)(?=[-_.]|$)", "", stem, flags=re.I)
    base = re.sub(r"[-_ ]v?\d+(\.\d+)+.*$", "", stem) or stem
    words = [w for w in re.split(r"[-_ ]+", base) if w]
    name = " ".join(w[:1].upper() + w[1:] if w.islower() else w for w in words)
    return name or stem


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def appimage_type(path: str) -> int:
    """2 for modern AppImages (can be unpacked safely), 1 for very old ones, 0 if it isn't an AppImage."""
    try:
        with open(path, "rb") as f:
            head = f.read(11)
    except OSError:
        return 0
    if len(head) < 11 or head[:4] != b"\x7fELF" or head[8:10] != b"AI":
        return 0
    return head[10]


def _is_image(path: str) -> str:
    """'png' / 'svg' / '' by looking at the file's first bytes."""
    try:
        with open(path, "rb") as f:
            head = f.read(256)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG"):
        return "png"
    if b"<svg" in head or head.lstrip().startswith(b"<?xml"):
        return "svg"
    return ""


def pick_icon(root: str | Path, icon_name: str = "") -> str:
    """Best icon file inside an unpacked AppImage (squashfs-root): .DirIcon, then <Icon>.png/.svg, then any top-level image."""
    root = Path(root)
    cands: list[Path] = [root / ".DirIcon"]
    if icon_name:
        cands += [root / f"{icon_name}.png", root / f"{icon_name}.svg"]
        cands += sorted(root.glob(f"usr/share/icons/hicolor/*/apps/{icon_name}.png"), key=lambda p: _icon_px(p), reverse=True)
    cands += sorted(root.glob("*.png")) + sorted(root.glob("*.svg"))
    for c in cands:
        try:
            real = c.resolve()
        except OSError:
            continue
        if real.is_file() and str(real).startswith(str(root.resolve())) and _is_image(str(real)):
            return str(real)
    return ""


def _icon_px(p: Path) -> int:
    m = re.search(r"/(\d+)x\d+/", str(p))
    return int(m.group(1)) if m else 0


def unpack_meta(appimage: str, timeout: float = 30) -> tuple[dict[str, str], str, str]:
    """Unpack only the .desktop file and icon of an AppImage into a temp folder.
    Returns (desktop entry keys, icon file path, temp folder to delete afterwards)."""
    tmp = tempfile.mkdtemp(prefix="pc-appimage-")
    if appimage_type(appimage) != 2:
        return {}, "", tmp

    def ex(pattern: str) -> None:
        try:
            subprocess.run([appimage, "--appimage-extract", pattern], cwd=tmp, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            pass
    ex("*.desktop")
    ex(".DirIcon")
    root = Path(tmp) / "squashfs-root"
    # .DirIcon is often a link to the real icon file: unpack its target too
    link = root / ".DirIcon"
    for _ in range(3):
        if not link.is_symlink():
            break
        target = os.readlink(link)
        ex(target.lstrip("/"))
        link = (link.parent / target)
    desks = sorted(root.glob("*.desktop")) or sorted(root.glob("**/*.desktop"))
    entry = parse_desktop_entry(read(desks[0])) if desks else {}
    icon = pick_icon(root, entry.get("Icon", ""))
    if not icon and entry.get("Icon"):
        for ext in ("png", "svg"):
            ex(f"{entry['Icon']}.{ext}")
        icon = pick_icon(root, entry.get("Icon", ""))
    return entry, icon, tmp


def desktop_text(appimage: str, name: str, icon: str, meta: dict[str, str] | None = None) -> str:
    meta = meta or {}
    lines = ["[Desktop Entry]", "Type=Application", f"Name={meta.get('Name') or name}"]
    for k in ("GenericName", "Comment", "Categories", "MimeType", "StartupWMClass", "Keywords"):
        if meta.get(k):
            lines.append(f"{k}={meta[k]}")
    if not meta.get("Comment"):
        lines.append(f"Comment={name} (AppImage)")
    lines += [f"Exec={desktop_quote(appimage)} %U", f"TryExec={appimage}", f"Icon={icon or GENERIC_ICON}", "Terminal=false",
              f"X-AppImage-Path={appimage}", "X-PC-AppImage=true"]
    return "\n".join(lines) + "\n"


def write_integration(appimage: str, desktop_dir: Path | None = None, icon_dir: Path | None = None, unpack: bool = True) -> str:
    """Put an AppImage in the app grid: a .desktop file plus its own icon when one can be unpacked."""
    desktop_dir = desktop_dir or DESKTOP_DIR
    icon_dir = icon_dir or ICON_DIR
    name = appimage_name(appimage)
    s = slug(name)
    meta, icon_src, tmp = unpack_meta(appimage) if unpack else ({}, "", "")
    icon = ""
    try:
        if icon_src:
            icon_dir.mkdir(parents=True, exist_ok=True)
            icon = str(icon_dir / f"{s}.{_is_image(icon_src) or 'png'}")
            shutil.copyfile(icon_src, icon)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    desktop_dir.mkdir(parents=True, exist_ok=True)
    dest = desktop_dir / f"appimage-{s}.desktop"
    dest.write_text(desktop_text(appimage, name, icon, meta))
    return f"wrote {_home_short(str(dest))}" + (f" and its icon {_home_short(icon)}" if icon else " (no icon found inside, using a generic one)")


def free_name(folder: Path, filename: str) -> Path:
    target = folder / filename
    n = 2
    while target.exists():
        p = Path(filename)
        target = folder / f"{p.stem}-{n}{p.suffix}"
        n += 1
    return target


def integrate_steps(path: str, place: str = "move") -> list[Step]:
    """place: 'move' or 'copy' into ~/Applications, or 'keep' it where it is."""
    src = Path(os.path.abspath(os.path.expanduser(path)))
    name = appimage_name(src.name)
    steps: list[Step] = []
    target = src
    if place in ("move", "copy") and src.parent != APPS_DIR:
        target = free_name(APPS_DIR, src.name)
        steps.append(Step("Make the Applications folder in your home", ["mkdir", "-p", str(APPS_DIR)]))
        if place == "move":
            steps.append(Step(f"Move {name} to ~/Applications", ["mv", "-n", str(src), str(target)]))
        else:
            steps.append(Step(f"Copy {name} to ~/Applications", ["cp", "-n", str(src), str(target)]))
    steps.append(Step("Allow it to run as a program", ["chmod", "+x", str(target)]))
    steps.append(py_step(f"Add {name} to the app grid", lambda t=str(target): write_integration(t),
                         f"write ~/.local/share/applications/appimage-{slug(name)}.desktop and its icon"))
    if has("update-desktop-database"):
        steps.append(Step("Refresh the app grid", ["update-desktop-database", str(DESKTOP_DIR)], optional=True))
    return steps


def integrated_appimages(desktop_dir: Path | None = None) -> list[AppImage]:
    """AppImages that have a launcher in ~/.local/share/applications (ours, AppImageLauncher's or Gear Lever's)."""
    desktop_dir = desktop_dir or DESKTOP_DIR
    res = []
    for f in sorted(glob.glob(str(desktop_dir / "*.desktop"))):
        d = parse_desktop_entry(read(f))
        target = d.get("X-AppImage-Path") or exec_target(d.get("Exec", ""))
        if not target.lower().endswith(".appimage"):
            continue
        exists = os.path.isfile(target)
        st = os.stat(target) if exists else None
        icon = d.get("Icon", "")
        res.append(AppImage(target, d.get("Name", appimage_name(target)), st.st_size if st else 0, st.st_mtime if st else 0,
                            os.access(target, os.X_OK) if exists else False, f, icon if icon.startswith("/") else "",
                            d.get("X-PC-AppImage", "").lower() == "true", exists))
    return res


def loose_appimages(integrated: list[AppImage] | None = None, dirs: list[Path] | None = None) -> list[AppImage]:
    """AppImage files lying in Downloads, ~/Applications and similar folders that aren't in the app grid yet."""
    done = {os.path.realpath(a.path) for a in (integrated if integrated is not None else integrated_appimages())}
    seen: set[str] = set()
    res = []
    for d in dirs or LOOSE_DIRS:
        files = glob.glob(str(d / "*")) + glob.glob(str(d / "*" / "*"))
        for f in files:
            if not f.lower().endswith(".appimage") or not os.path.isfile(f):
                continue
            real = os.path.realpath(f)
            if real in done or real in seen:
                continue
            seen.add(real)
            st = os.stat(f)
            res.append(AppImage(f, appimage_name(f), st.st_size, st.st_mtime, os.access(f, os.X_OK)))
    res.sort(key=lambda a: -a.mtime)
    return res


def remove_integration_steps(a: AppImage, delete_file: bool = False) -> list[Step]:
    steps = []
    if a.desktop:
        steps.append(Step(f"Remove {a.name} from the app grid", ["rm", "-f", a.desktop]))
    if a.icon and a.icon.startswith(str(HOME / ".local/share/icons")):
        steps.append(Step("Remove its icon", ["rm", "-f", a.icon], optional=True))
    if delete_file and a.exists:
        steps.append(Step(f"Move {os.path.basename(a.path)} to the Trash", ["gio", "trash", a.path]))
    if a.desktop and has("update-desktop-database"):
        steps.append(Step("Refresh the app grid", ["update-desktop-database", str(DESKTOP_DIR)], optional=True))
    return steps


FUSE2_GLOBS = ["/usr/lib/*/libfuse.so.2*", "/lib/*/libfuse.so.2*", "/usr/lib/libfuse.so.2*", "/usr/lib64/libfuse.so.2*"]


def fuse2_installed() -> bool:
    """Most AppImages need the old FUSE 2 library to start. Ubuntu 24.04+ doesn't install it by default."""
    return any(glob.glob(p) for p in FUSE2_GLOBS)


def fuse2_package() -> str:
    return "libfuse2t64" if sh(["apt-cache", "show", "libfuse2t64"], timeout=15).ok else "libfuse2"


def fuse2_steps(pkg: str | None = None) -> list[Step]:
    pkg = pkg or fuse2_package()
    return [Step(f"Install {pkg} (lets AppImages start)", ["apt-get", "install", "-y", pkg], root=True, env=APT_ENV)]


# ---------------------------------------------------------------- E3: uninstall several at once

PROTECTED = {"gnome-shell", "gdm3", "ubuntu-desktop", "ubuntu-desktop-minimal", "nautilus", "gnome-control-center", "snapd",
             "network-manager", "systemd", "apt", "gnome-session", "ubuntu-session", "gnome-settings-daemon", "xdg-desktop-portal",
             "xdg-desktop-portal-gnome", "ptyxis", "gnome-terminal", "yelp", "update-manager", "software-properties-gtk", "bare",
             "snap-store", "firmware-updater", "desktop-security-center", "prompting-client", "snapd-desktop-integration"}


def is_protected(a: App) -> bool:
    return a.source in ("apt", "snap") and a.id in PROTECTED


def remove_many_steps(apps: list[App], keep_data: bool = False) -> list[Step]:
    """One set of steps for several apps from any source: one apt call, one snap call, one flatpak call per scope."""
    apps = [a for a in apps if not is_protected(a)]
    steps: list[Step] = []
    apt = sorted({a.id for a in apps if a.source == "apt"})
    snaps = sorted({a.id for a in apps if a.source == "snap"})
    flat_user = sorted({a.id for a in apps if a.source == "flatpak" and a.location != "system"})
    flat_sys = sorted({a.id for a in apps if a.source == "flatpak" and a.location == "system"})
    files = [a for a in apps if a.source in ("appimage", "manual")]
    if apt:
        steps.append(Step(f"Uninstall {len(apt)} system app{'s' if len(apt) != 1 else ''}",
                          ["apt-get", "remove" if keep_data else "purge", "-y", *apt], root=True, env=APT_ENV))
        steps.append(Step("Remove leftovers they pulled in", ["apt-get", "autoremove", "-y"] if keep_data else
                          ["apt-get", "autoremove", "--purge", "-y"], root=True, env=APT_ENV, optional=True))
    if snaps:
        steps.append(Step(f"Uninstall {len(snaps)} snap{'s' if len(snaps) != 1 else ''}",
                          ["snap", "remove", *([] if keep_data else ["--purge"]), *snaps], root=True))
    for ids, scope in ((flat_user, "--user"), (flat_sys, "--system")):
        if ids:
            steps.append(Step(f"Uninstall {len(ids)} Flatpak app{'s' if len(ids) != 1 else ''}" + (" (for all users)" if scope == "--system" else ""),
                              ["flatpak", "uninstall", "-y", "--noninteractive", *([] if keep_data else ["--delete-data"]), scope, *ids],
                              root=scope == "--system"))
    if files:
        integ = {os.path.realpath(x.path): x for x in integrated_appimages()}
        for a in files:
            steps.append(Step(f"Move {a.name} to the Trash", ["gio", "trash", a.id]))
            hit = integ.get(os.path.realpath(a.id))
            if hit:
                steps += [s for s in remove_integration_steps(hit) if s.cmd[0] == "rm"]
    return steps


# ---------------------------------------------------------------- E4: permissions

# Snap interfaces people meet most, in plain words: (title, what it allows)
SNAP_IFACES = {
    "home": ("Your home folder", "Open and save your files (not hidden files or folders)."),
    "camera": ("Camera", "Use your webcam."),
    "audio-record": ("Microphone", "Record sound from your microphone."),
    "audio-playback": ("Play sound", "Play audio through your speakers or headphones."),
    "pulseaudio": ("Sound (old way)", "Play and record sound through the older PulseAudio system."),
    "removable-media": ("USB drives and SD cards", "Read and write files on drives you plug in (/media and /mnt)."),
    "network": ("Internet", "Go online."),
    "network-bind": ("Accept connections", "Run a server that other programs or computers can connect to."),
    "network-observe": ("See network settings", "Look at your network setup and connections."),
    "network-manager": ("Change network settings", "Manage Wi-Fi and network connections."),
    "desktop": ("Desktop basics", "Show windows, fonts and themes."),
    "desktop-legacy": ("Desktop (older parts)", "Accessibility and input methods; lets it see other X11 windows."),
    "x11": ("X11 windows", "Draw windows the old way. Can see keystrokes in other X11 apps."),
    "wayland": ("Wayland windows", "Draw windows the modern, safer way."),
    "opengl": ("Graphics card", "Use your GPU for fast graphics."),
    "unity7": ("Old desktop integration", "Tray icons and menus the old way."),
    "gsettings": ("Desktop settings", "Read and change GNOME settings."),
    "browser-support": ("Browser sandbox", "Needed by web browsers and Electron apps."),
    "password-manager-service": ("Saved passwords", "Read and save passwords in your keyring."),
    "ssh-keys": ("SSH keys", "Read your SSH keys (~/.ssh)."),
    "ssh-public-keys": ("SSH public keys", "Read your public SSH keys."),
    "personal-files": ("Some hidden files", "Read or write specific hidden files in your home folder."),
    "system-files": ("Some system files", "Read or write specific system files."),
    "u2f-devices": ("Security keys", "Use hardware security keys like a YubiKey."),
    "joystick": ("Game controllers", "Use joysticks and gamepads."),
    "bluez": ("Bluetooth devices", "Talk to Bluetooth devices."),
    "bluetooth-control": ("Bluetooth settings", "Change Bluetooth settings."),
    "cups-control": ("Printers", "Manage printers and print jobs."),
    "cups": ("Print", "Print documents."),
    "screen-inhibit-control": ("Keep the screen on", "Stop the screen from turning off (for videos, calls)."),
    "mount-observe": ("See drives", "See which drives are mounted."),
    "system-observe": ("See running programs", "See other programs and system details."),
    "process-control": ("Control programs", "Change priority of or stop other programs."),
    "hardware-observe": ("See hardware", "Read details about your hardware."),
    "raw-usb": ("Raw USB access", "Talk to USB devices directly."),
    "hostname-control": ("Computer name", "Change the computer's name."),
    "shutdown": ("Shut down", "Restart or shut down the PC."),
    "upower-observe": ("Battery info", "Read battery and power status."),
    "location-observe": ("Location", "Know where you are."),
    "screencast-legacy": ("Record the screen", "Take screenshots and record the screen."),
    "docker": ("Docker", "Control Docker containers."),
    "kvm": ("Virtual machines", "Run virtual machines with hardware acceleration."),
    "content": ("Shared parts", "Shared libraries or themes from another snap."),
}


# Plumbing the app needs to draw windows or run at all: shown apart, as "technical"
SNAP_TECHNICAL = {"browser-support", "desktop", "desktop-legacy", "x11", "wayland", "opengl", "unity7", "gsettings", "content", "dbus"}


def parse_snap_connections(text: str, snap: str) -> list[dict]:
    """`snap connections <snap>` → plugs of that snap: interface, plug, slot, connected, notes."""
    res = []
    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith("Interface"):
        return res
    for line in lines[1:]:
        cols = line.split()
        if len(cols) < 3:
            continue
        iface, plug, slot = cols[0], cols[1], cols[2]
        notes = cols[3] if len(cols) > 3 else "-"
        if not plug.startswith(f"{snap}:"):
            continue  # a slot this snap offers to others
        base = iface.split("[")[0]
        title, what = SNAP_IFACES.get(base, (base.replace("-", " ").capitalize(), ""))
        res.append({"interface": iface, "base": base, "plug": plug, "slot": slot, "connected": slot != "-", "notes": notes,
                    "title": title, "what": what, "manual": "manual" in notes, "technical": base in SNAP_TECHNICAL})
    return res


def snap_connections(snap: str) -> list[dict]:
    if not has("snap"):
        return []
    return parse_snap_connections(out(["snap", "connections", snap], timeout=20), snap)


def snap_plug_steps(plug: str, connect: bool) -> list[Step]:
    title = ("Allow " if connect else "Block ") + plug
    return [Step(title, ["snap", "connect" if connect else "disconnect", plug], root=True)]


# Common Flatpak permissions with a simple on/off: (context key, value, title, explanation, flag on, flag off)
FLATPAK_TOGGLES = [
    ("filesystems", "home", "Your home folder", "Open and save files anywhere in your home folder without asking each time.",
     "--filesystem=home", "--nofilesystem=home"),
    ("devices", "all", "Cameras, USB and game controllers", "Use every device: webcams, USB gadgets, game controllers.",
     "--device=all", "--nodevice=all"),
    ("sockets", "x11", "Old-style windows (X11)", "Needed by some older apps. X11 apps can see what you type in other X11 apps.",
     "--socket=x11", "--nosocket=x11"),
    ("shared", "network", "Internet", "Go online.", "--share=network", "--unshare=network"),
]

FLATPAK_WORDS = {
    ("filesystems", "host"): "every file on this PC", ("filesystems", "host-os"): "system programs", ("filesystems", "host-etc"): "system settings",
    ("filesystems", "home"): "your home folder", ("filesystems", "xdg-download"): "Downloads", ("filesystems", "xdg-documents"): "Documents",
    ("filesystems", "xdg-pictures"): "Pictures", ("filesystems", "xdg-music"): "Music", ("filesystems", "xdg-videos"): "Videos",
    ("filesystems", "xdg-desktop"): "Desktop", ("devices", "dri"): "graphics card", ("devices", "all"): "all devices",
    ("devices", "kvm"): "virtual machines", ("sockets", "wayland"): "Wayland windows", ("sockets", "x11"): "X11 windows",
    ("sockets", "fallback-x11"): "X11 if needed", ("sockets", "pulseaudio"): "sound", ("sockets", "cups"): "printing",
    ("sockets", "ssh-auth"): "SSH keys agent", ("sockets", "pcsc"): "smart cards", ("sockets", "session-bus"): "whole session bus",
    ("sockets", "system-bus"): "whole system bus", ("sockets", "gpg-agent"): "GPG agent", ("shared", "network"): "internet",
    ("shared", "ipc"): "shared memory",
}


def parse_flatpak_permissions(text: str) -> dict[str, dict[str, list[str]]]:
    """INI-like output of `flatpak info --show-permissions` / `flatpak override --show` → {section: {key: [values]}}."""
    res: dict[str, dict[str, list[str]]] = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            res.setdefault(section, {})
            continue
        k, sep, v = line.partition("=")
        if sep and section:
            res[section][k.strip()] = [x for x in v.strip().split(";") if x]
    return res


def flatpak_has(perms: dict, key: str, value: str) -> bool:
    """Is a permission on? Handles '!home' (taken away), 'home:ro' (read-only still counts) and 'host' (includes home)."""
    vals = perms.get("Context", {}).get(key, [])
    base = [v.split(":")[0] for v in vals]
    if f"!{value}" in base:
        return False
    if value in base:
        return True
    return key == "filesystems" and value == "home" and "host" in base


def flatpak_summary(perms: dict) -> list[str]:
    """Plain-language list of what an app may do."""
    res = []
    ctx = perms.get("Context", {})
    for key in ("shared", "sockets", "devices", "filesystems"):
        for v in ctx.get(key, []):
            neg = v.startswith("!")
            base, _, mode = v.lstrip("!").partition(":")
            word = FLATPAK_WORDS.get((key, base), base)
            if neg:
                res.append(f"blocked: {word}")
            else:
                res.append(word + (" (read-only)" if mode == "ro" else ""))
    return res


def flatpak_permissions(app_id: str) -> tuple[dict, dict]:
    """(effective permissions, your own overrides)."""
    if not has("flatpak"):
        return {}, {}
    eff = parse_flatpak_permissions(out(["flatpak", "info", "--show-permissions", app_id], timeout=20))
    mine = parse_flatpak_permissions(out(["flatpak", "override", "--user", "--show", app_id], timeout=20))
    return eff, mine


def flatpak_override_steps(app_id: str, flag: str, title: str = "") -> list[Step]:
    return [Step(title or f"Change a permission of {app_id}", ["flatpak", "override", "--user", flag, app_id])]


def flatpak_reset_steps(app_id: str) -> list[Step]:
    return [Step(f"Reset {app_id} to its own permissions", ["flatpak", "override", "--user", "--reset", app_id])]


# ---------------------------------------------------------------- E5: same app installed twice

# (key, title, {source: ids}, preferred source, why that one)
FAMILIES: list[tuple[str, str, dict[str, list[str]], str | None, str]] = [
    ("firefox", "Firefox", {"apt": ["firefox", "firefox-esr"], "snap": ["firefox"], "flatpak": ["org.mozilla.firefox"]}, "snap",
     "Ubuntu sets up the Snap version by default and Mozilla updates it directly."),
    ("thunderbird", "Thunderbird", {"apt": ["thunderbird"], "snap": ["thunderbird"], "flatpak": ["org.mozilla.Thunderbird"]}, "snap",
     "Ubuntu's default version, updated by Mozilla."),
    ("chromium", "Chromium", {"apt": ["chromium", "chromium-browser"], "snap": ["chromium"], "flatpak": ["org.chromium.Chromium"]}, "snap",
     "Ubuntu's own build of Chromium."),
    ("chrome", "Google Chrome", {"apt": ["google-chrome-stable", "google-chrome-beta"], "flatpak": ["com.google.Chrome"]}, "apt",
     "Google's own package, updated by Google."),
    ("brave", "Brave", {"apt": ["brave-browser"], "snap": ["brave"], "flatpak": ["com.brave.Browser"]}, "apt",
     "Brave's own package, updated by Brave."),
    ("vscode", "Visual Studio Code", {"apt": ["code"], "snap": ["code"], "flatpak": ["com.visualstudio.code"]}, "apt",
     "Microsoft's .deb can see all your developer tools and terminals; the Flatpak is boxed in and often can't."),
    ("vscodium", "VSCodium", {"apt": ["codium"], "snap": ["codium"], "flatpak": ["com.vscodium.codium"]}, "apt",
     "The .deb version can see all your developer tools."),
    ("sublime", "Sublime Text", {"apt": ["sublime-text"], "snap": ["sublime-text"], "flatpak": ["com.sublimetext.three"]}, "apt",
     "Sublime's own package, updated by Sublime HQ."),
    ("cursor", "Cursor", {"apt": ["cursor"], "appimage": ["cursor"]}, "apt", "The .deb version updates with your system."),
    ("spotify", "Spotify", {"apt": ["spotify-client"], "snap": ["spotify"], "flatpak": ["com.spotify.Client"]}, "snap",
     "Spotify publishes the Snap itself."),
    ("vlc", "VLC", {"apt": ["vlc"], "snap": ["vlc"], "flatpak": ["org.videolan.VLC"]}, "apt", "The Ubuntu version starts fastest."),
    ("discord", "Discord", {"apt": ["discord"], "snap": ["discord"], "flatpak": ["com.discordapp.Discord"]}, "flatpak",
     "The Flatpak updates itself; the .deb needs a new download for every update."),
    ("slack", "Slack", {"apt": ["slack-desktop"], "snap": ["slack"], "flatpak": ["com.slack.Slack"]}, "snap",
     "Slack publishes the Snap itself."),
    ("telegram", "Telegram", {"apt": ["telegram-desktop"], "snap": ["telegram-desktop"], "flatpak": ["org.telegram.desktop"]}, "flatpak",
     "The Flatpak is the most up to date."),
    ("signal", "Signal", {"apt": ["signal-desktop"], "snap": ["signal-desktop"], "flatpak": ["org.signal.Signal"]}, "apt",
     "Signal's own package, updated by Signal."),
    ("zoom", "Zoom", {"apt": ["zoom"], "snap": ["zoom-client"], "flatpak": ["us.zoom.Zoom"]}, "apt", "Zoom's own package."),
    ("obs", "OBS Studio", {"apt": ["obs-studio"], "snap": ["obs-studio"], "flatpak": ["com.obsproject.Studio"]}, "flatpak",
     "OBS recommends the Flatpak on Linux."),
    ("gimp", "GIMP", {"apt": ["gimp"], "snap": ["gimp"], "flatpak": ["org.gimp.GIMP"]}, "flatpak", "GIMP publishes the Flatpak itself."),
    ("inkscape", "Inkscape", {"apt": ["inkscape"], "snap": ["inkscape"], "flatpak": ["org.inkscape.Inkscape"]}, "flatpak",
     "The Flatpak is the most up to date."),
    ("libreoffice", "LibreOffice", {"apt": ["libreoffice", "libreoffice-writer", "libreoffice-calc", "libreoffice-impress",
                                            "libreoffice-draw", "libreoffice-math", "libreoffice-base", "libreoffice-common"],
                                    "snap": ["libreoffice"], "flatpak": ["org.libreoffice.LibreOffice"], "appimage": ["libreoffice"]}, "apt",
     "The Ubuntu version fits in best and gets security fixes with your system."),
    ("postman", "Postman", {"snap": ["postman"], "flatpak": ["com.getpostman.Postman"]}, "snap", "Postman publishes the Snap itself."),
    ("bruno", "Bruno", {"apt": ["bruno"], "snap": ["bruno"], "flatpak": ["com.usebruno.Bruno"]}, None, ""),
    ("obsidian", "Obsidian", {"apt": ["obsidian"], "snap": ["obsidian"], "flatpak": ["md.obsidian.Obsidian"], "appimage": ["obsidian"]},
     "flatpak", "The Flatpak updates itself."),
    ("bitwarden", "Bitwarden", {"apt": ["bitwarden"], "snap": ["bitwarden"], "flatpak": ["com.bitwarden.desktop"]}, "snap",
     "Bitwarden publishes the Snap itself."),
    ("steam", "Steam", {"apt": ["steam", "steam-installer", "steam-launcher"], "snap": ["steam"], "flatpak": ["com.valvesoftware.Steam"]},
     "apt", "Valve's own package works best with games and controllers."),
    ("dbeaver", "DBeaver", {"apt": ["dbeaver-ce"], "snap": ["dbeaver-ce"], "flatpak": ["io.dbeaver.DBeaverCommunity"]}, None, ""),
    ("intellij", "IntelliJ IDEA", {"snap": ["intellij-idea-community", "intellij-idea-ultimate"],
                                   "flatpak": ["com.jetbrains.IntelliJ-IDEA-Community", "com.jetbrains.IntelliJ-IDEA-Ultimate"]}, "snap",
     "JetBrains publishes the Snap itself; the Flatpak can't see your tools."),
    ("pycharm", "PyCharm", {"snap": ["pycharm-community", "pycharm-professional"],
                            "flatpak": ["com.jetbrains.PyCharm-Community", "com.jetbrains.PyCharm-Professional"]}, "snap",
     "JetBrains publishes the Snap itself; the Flatpak can't see your tools."),
    ("android-studio", "Android Studio", {"snap": ["android-studio"], "flatpak": ["com.google.AndroidStudio"]}, "snap", ""),
    ("ghostty", "Ghostty", {"apt": ["ghostty"], "snap": ["ghostty"], "flatpak": ["com.mitchellh.ghostty"]}, None, ""),
    ("missioncenter", "Mission Center", {"snap": ["mission-center"], "flatpak": ["io.missioncenter.MissionCenter"]}, "flatpak", ""),
]

SOURCE_WORDS = {"apt": "Ubuntu package (apt)", "snap": "Snap", "flatpak": "Flatpak", "appimage": "AppImage", "manual": "manual install"}
SOURCE_WHY = {"apt": "Ubuntu packages start fastest and update with the rest of your system.",
              "flatpak": "Flatpaks are sandboxed and update themselves.",
              "snap": "Snaps are sandboxed and update themselves.",
              "appimage": "", "manual": ""}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def app_key(a: App) -> str:
    return f"{a.source}:{a.id}"


def _transitional(a: App) -> bool:
    """Ubuntu's firefox/chromium/thunderbird .debs are empty shells that install the Snap: not a real second copy."""
    return a.source == "apt" and ("snap" in a.version.lower() or "transitional" in a.summary.lower())


def _family_match(a: App, ids: list[str]) -> bool:
    if a.source in ("appimage", "manual"):
        n = _norm(appimage_name(a.id) if a.source == "appimage" else a.name)
        return any(n == _norm(i) for i in ids)
    return a.id in ids


def find_duplicates(apps: list[App], last_used: dict[str, float | None] | None = None) -> list[dict]:
    """Apps installed more than once from different sources.
    Each group: {key, title, copies: [{source, apps, size, last}], keep: source, why}."""
    last_used = last_used or {}
    groups: list[dict] = []
    taken: set[str] = set()
    real = [a for a in apps if not _transitional(a)]
    for key, title, ids, pref, why in FAMILIES:
        by: dict[str, list[App]] = {}
        for src, names in ids.items():
            for a in real:
                if (a.source == src or (src == "appimage" and a.source == "manual")) and _family_match(a, names):
                    by.setdefault(a.source, []).append(a)
        if len(by) >= 2:
            groups.append(_group(key, title, by, pref, why, last_used))
            taken |= {app_key(a) for lst in by.values() for a in lst}
    # Same visible name from different sources (apps not in the list above)
    by_name: dict[str, dict[str, list[App]]] = {}
    for a in real:
        if app_key(a) in taken:
            continue
        name = appimage_name(a.id) if a.source == "appimage" else a.name
        n = _norm(name)
        if len(n) < 3:
            continue
        by_name.setdefault(n, {}).setdefault(a.source, []).append(a)
    for n, by in by_name.items():
        if len(by) >= 2:
            first = next(iter(by.values()))[0]
            groups.append(_group(n, appimage_name(first.id) if first.source == "appimage" else first.name, by, None, "", last_used))
    groups.sort(key=lambda g: g["title"].lower())
    return groups


def _group(key: str, title: str, by: dict[str, list[App]], pref: str | None, why: str, last_used: dict[str, float | None]) -> dict:
    copies = []
    for src, lst in by.items():
        times = [t for t in (last_used.get(app_key(a)) for a in lst) if t]
        copies.append({"source": src, "apps": lst, "size": sum(a.size for a in lst), "last": max(times) if times else None,
                       "label": SOURCE_WORDS.get(src, src), "ids": [a.id for a in lst]})
    keep, reason = _pick_keep(copies, pref, why)
    return {"key": key, "title": title, "copies": copies, "keep": keep, "why": reason}


def _pick_keep(copies: list[dict], pref: str | None, why: str) -> tuple[str, str]:
    known = sorted((c for c in copies if c["last"]), key=lambda c: -c["last"])
    if known:
        best = known[0]
        others = [c["last"] or 0 for c in copies if c is not best]
        if all(best["last"] - t > 7 * 86400 for t in others):
            return best["source"], "You opened this one most recently."
    sources = [c["source"] for c in copies]
    if pref in sources:
        return pref, why or SOURCE_WHY.get(pref, "")
    for s in ("apt", "flatpak", "snap", "appimage", "manual"):
        if s in sources:
            return s, SOURCE_WHY.get(s, "")
    return sources[0], ""


def remove_copy_steps(copy: dict) -> list[Step]:
    """Remove one copy of a duplicated app but keep your settings and data (they're shared or backed up)."""
    src, apps = copy["source"], copy["apps"]
    ids = sorted({a.id for a in apps})
    if src == "apt":
        return [Step(f"Remove the Ubuntu package{'s' if len(ids) > 1 else ''}", ["apt-get", "remove", "-y", *ids], root=True, env=APT_ENV),
                Step("Remove leftovers it pulled in", ["apt-get", "autoremove", "-y"], root=True, env=APT_ENV, optional=True)]
    if src == "snap":
        return [Step("Remove the Snap (a backup of its data is kept for 31 days)", ["snap", "remove", *ids], root=True)]
    if src == "flatpak":
        steps = []
        user = sorted({a.id for a in apps if a.location != "system"})
        system = sorted({a.id for a in apps if a.location == "system"})
        if user:
            steps.append(Step("Remove the Flatpak (its data in ~/.var/app is kept)", ["flatpak", "uninstall", "-y", "--noninteractive", "--user", *user]))
        if system:
            steps.append(Step("Remove the Flatpak (its data in ~/.var/app is kept)", ["flatpak", "uninstall", "-y", "--noninteractive", "--system", *system],
                              root=True))
        return steps
    return remove_many_steps(apps, keep_data=True)


# ---------------------------------------------------------------- E6: last used

APP_STATE = HOME / ".local/share/gnome-shell/application_state"
SNAP_DESKTOP = Path("/var/lib/snapd/desktop/applications")


def parse_app_state(text: str) -> dict[str, dict]:
    """GNOME Shell's usage file: {desktop id: {score, last_seen (unix time)}}."""
    res: dict[str, dict] = {}
    for m in re.finditer(r"<application\b([^>]*?)/?>", text):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        aid = attrs.get("id")
        if not aid:
            continue
        try:
            last = int(float(attrs.get("last-seen", "0") or 0))
        except ValueError:
            last = 0
        try:
            score = float(attrs.get("score", "0") or 0)
        except ValueError:
            score = 0.0
        prev = res.get(aid)
        if prev is None or last > prev["last_seen"]:
            res[aid] = {"score": score, "last_seen": last}
    return res


def desktop_ids(a: App) -> list[str]:
    if a.source == "apt":
        return [os.path.basename(a.desktop)] if a.desktop else []
    if a.source == "snap":
        return [os.path.basename(f) for f in glob.glob(str(SNAP_DESKTOP / f"{a.id}_*.desktop"))] or [f"{a.id}_{a.id}.desktop"]
    if a.source == "flatpak":
        return [f"{a.id}.desktop"]
    if a.source == "appimage":
        real = os.path.realpath(a.id)
        return [os.path.basename(x.desktop) for x in integrated_appimages() if x.desktop and os.path.realpath(x.path) == real]
    return []


def _mtime_max(paths: list[str]) -> float | None:
    best = None
    for p in paths:
        try:
            t = os.stat(p).st_mtime
        except OSError:
            continue
        best = t if best is None or t > best else best
    return best


def file_last_used(a: App) -> float | None:
    """Rough guess when an app was last opened, from file times, when GNOME has no record."""
    try:
        if a.source == "apt" and a.desktop:
            prog = exec_target(parse_desktop_entry(read(a.desktop)).get("Exec", ""))
            path = prog if prog.startswith("/") else (shutil.which(prog) or "")
            return os.stat(os.path.realpath(path)).st_atime if path else None
        if a.source == "appimage":
            return os.stat(a.id).st_atime
        if a.source == "flatpak":
            d = HOME / ".var/app" / a.id
            return _mtime_max([str(d), *[str(d / s) for s in ("config", "cache", "data", ".local/state")]])
        if a.source == "snap":
            d = HOME / "snap" / a.id
            return _mtime_max([str(d / "current"), str(d / "common"), *glob.glob(str(d / "current" / ".*"))])
        if a.source == "manual":
            return os.stat(a.id).st_atime
    except OSError:
        return None
    return None


def last_used(apps: list[App], state_text: str | None = None) -> dict[str, tuple[float | None, str]]:
    """{app key: (unix time or None, how we know: 'gnome' | 'files' | '')}."""
    text = read(APP_STATE) if state_text is None else state_text
    state = parse_app_state(text)
    res: dict[str, tuple[float | None, str]] = {}
    for a in apps:
        best = None
        for d in desktop_ids(a):
            s = state.get(d)
            if s and s["last_seen"] and (best is None or s["last_seen"] > best):
                best = s["last_seen"]
        if best:
            res[app_key(a)] = (float(best), "gnome")
            continue
        t = file_last_used(a)
        res[app_key(a)] = (t, "files" if t else "")
    return res


def parse_apt_depends(text: str, recommends_of: set[str] | None = None) -> set[str]:
    """Package names from `apt-cache depends`: every Depends (with alternatives), and Recommends only of the packages in
    `recommends_of` (all of them when None)."""
    res = set()
    cur = ""
    for line in text.splitlines():
        if line and not line[0].isspace() and line[0] != "|":
            cur = line.strip()
            continue
        m = re.match(r"^\s*\|?((?:Pre)?Depends|Recommends):\s*<?([^\s>]+)>?", line)
        if m and (m.group(1) != "Recommends" or recommends_of is None or cur in recommends_of):
            res.add(m.group(2).split(":")[0])
    return res


def desktop_core_packages() -> set[str]:
    """Apps that are part of the basic Ubuntu desktop (Files, Settings, the terminal…), so we never suggest removing them.
    Extras the full desktop adds (LibreOffice, Thunderbird, games) are fair game."""
    text = out(["apt-cache", "depends", "--no-suggests", "--no-conflicts", "--no-breaks", "--no-replaces", "--no-enhances",
                "ubuntu-desktop-minimal", "ubuntu-desktop"], timeout=20)
    return parse_apt_depends(text, {"ubuntu-desktop-minimal"}) | PROTECTED


def unused_apps(apps: list[App], used: dict[str, tuple[float | None, str]], days: int = 90, core: set[str] | None = None,
                now: float | None = None) -> list[dict]:
    """Apps not opened for `days` days, biggest first: {app, last, how, days}."""
    now = now or time.time()
    core = core if core is not None else set()
    res = []
    for a in apps:
        if a.source in ("apt", "snap") and a.id in core:
            continue
        if is_protected(a):
            continue
        t, how = used.get(app_key(a), (None, ""))
        if t is None or now - t < days * 86400:
            continue
        res.append({"app": a, "last": t, "how": how, "days": int((now - t) // 86400)})
    res.sort(key=lambda r: (-r["app"].size, -r["days"]))
    return res


# ---------------------------------------------------------------- E7: default terminal

# desktop id → (name, program, what it's like, "run this" argument for GNOME's old setting)
TERMINALS = {
    "org.gnome.Ptyxis.desktop": ("Ptyxis", "ptyxis", "Ubuntu's default terminal. Tabs, profiles and container support.", "--"),
    "com.mitchellh.ghostty.desktop": ("Ghostty", "ghostty", "Very fast terminal that uses your graphics card. Native tabs and splits.", "-e"),
    "ghostty_ghostty.desktop": ("Ghostty", "ghostty", "Very fast terminal that uses your graphics card. Native tabs and splits.", "-e"),
    "org.gnome.Terminal.desktop": ("GNOME Terminal", "gnome-terminal", "The classic GNOME terminal.", "--"),
    "org.gnome.Console.desktop": ("Console", "kgx", "Simple terminal from GNOME.", "--"),
    "kitty.desktop": ("kitty", "kitty", "Fast GPU terminal with lots of features.", "--"),
    "Alacritty.desktop": ("Alacritty", "alacritty", "Minimal, very fast GPU terminal.", "-e"),
    "org.wezfurlong.wezterm.desktop": ("WezTerm", "wezterm", "GPU terminal you configure with Lua. Tabs and splits.", "start --"),
    "com.gexperts.Tilix.desktop": ("Tilix", "tilix", "Split one window into several terminals.", "-e"),
    "org.kde.konsole.desktop": ("Konsole", "konsole", "KDE's terminal.", "-e"),
    "foot.desktop": ("foot", "foot", "Lightweight terminal for Wayland.", ""),
    "com.raggesilver.BlackBox.desktop": ("Black Box", "blackbox", "Good-looking GTK terminal.", "--"),
    "terminator.desktop": ("Terminator", "terminator", "Split one window into several terminals.", "-x"),
    "debian-xterm.desktop": ("XTerm", "xterm", "The very old X terminal.", "-e"),
    "xterm.desktop": ("XTerm", "xterm", "The very old X terminal.", "-e"),
}
UBUNTU_DEFAULT_TERMINAL = "org.gnome.Ptyxis.desktop"
APP_DIRS = [Path("/usr/share/applications"), Path("/usr/local/share/applications"), HOME / ".local/share/applications",
            SNAP_DESKTOP, Path("/var/lib/flatpak/exports/share/applications"), HOME / ".local/share/flatpak/exports/share/applications"]


def installed_terminals(dirs: list[Path] | None = None) -> list[dict]:
    """Terminal apps on this PC (desktop files in the TerminalEmulator category, which xdg-terminal-exec uses)."""
    res: dict[str, dict] = {}
    for d in dirs or APP_DIRS:
        for f in sorted(glob.glob(str(Path(d) / "*.desktop"))):
            did = os.path.basename(f)
            if did in res:
                continue
            e = parse_desktop_entry(read(f))
            cats = e.get("Categories", "").split(";")
            if "TerminalEmulator" not in cats and did not in TERMINALS:
                continue
            if e.get("Type", "Application") != "Application" or e.get("Hidden", "").lower() == "true":
                continue
            known = TERMINALS.get(did)
            res[did] = {"id": did, "name": known[0] if known else e.get("Name", did), "note": known[2] if known else e.get("Comment", ""),
                        "exec": exec_target(e.get("Exec", "")), "program": known[1] if known else exec_target(e.get("Exec", "")),
                        "arg": known[3] if known else "", "file": f}
    return sorted(res.values(), key=lambda t: (t["id"] != UBUNTU_DEFAULT_TERMINAL, t["name"].lower()))


def _desktop_names(env: str | None = None) -> list[str]:
    env = os.environ.get("XDG_CURRENT_DESKTOP", "ubuntu:GNOME") if env is None else env
    return [d.lower() for d in env.split(":") if d]


def terminal_list_files(config_home: Path | None = None, config_dirs: list[Path] | None = None, desktop: str | None = None) -> list[Path]:
    """xdg-terminals.list files in the order xdg-terminal-exec reads them (yours first, desktop-specific before generic)."""
    config_home = config_home or Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    config_dirs = config_dirs or [Path(p) for p in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if p]
    names = _desktop_names(desktop)
    res = []
    for d in [config_home, *config_dirs]:
        res += [d / f"{n}-xdg-terminals.list" for n in names]
        res.append(d / "xdg-terminals.list")
    return res


def parse_terminal_list(text: str) -> list[str]:
    """Entries of an xdg-terminals.list (desktop ids; '-id' lines exclude a terminal and are skipped here)."""
    res = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        res.append(line.lstrip("+").split(":")[0].strip())
    return res


def default_terminal(installed: list[dict] | None = None, files: list[Path] | None = None) -> tuple[str | None, str]:
    """(desktop id of the default terminal, the file that says so or '')."""
    installed = installed if installed is not None else installed_terminals()
    have = {t["id"] for t in installed}
    for f in files or terminal_list_files():
        for tid in parse_terminal_list(read(f)):
            if tid in have:
                return tid, str(f)
    if UBUNTU_DEFAULT_TERMINAL in have:
        return UBUNTU_DEFAULT_TERMINAL, ""
    return (installed[0]["id"] if installed else None), ""


def put_first(text: str, tid: str) -> str:
    """Rewrite an xdg-terminals.list so `tid` comes first (other lines kept, old mentions of it removed)."""
    keep = []
    for line in text.splitlines():
        s = line.strip()
        bare = s.lstrip("+-").split(":")[0].strip()
        if s and not s.startswith("#") and bare == tid:
            continue
        keep.append(line)
    comments = []
    while keep and (keep[0].strip().startswith("#") or not keep[0].strip()):
        comments.append(keep.pop(0))
    body = [tid] + [ln for ln in keep if ln.strip()]
    return "\n".join(comments + body) + "\n"


def gnome_terminal_schema() -> bool:
    return has("gsettings") and sh(["gsettings", "writable", "org.gnome.desktop.default-applications.terminal", "exec"], timeout=5).ok


def set_terminal_steps(term: dict, config_home: Path | None = None, with_gsettings: bool | None = None) -> list[Step]:
    """Make `term` the terminal that opens for 'Open in Terminal', Ctrl+Alt+T and apps that need a terminal."""
    config_home = config_home or Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    user_files = [f for f in terminal_list_files(config_home=config_home) if f.parent == config_home]
    targets = [f for f in user_files if f.exists()]
    generic = config_home / "xdg-terminals.list"
    if generic not in targets:
        targets.append(generic)

    def write() -> str:
        done = []
        for f in targets:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(put_first(read(f), term["id"]))
            done.append(_home_short(str(f)))
        return "wrote " + ", ".join(done)
    steps = [py_step(f"Make {term['name']} the default terminal", write,
                     "put " + term["id"] + " first in " + ", ".join(_home_short(str(f)) for f in targets))]
    if with_gsettings is None:
        with_gsettings = gnome_terminal_schema()
    if with_gsettings and term.get("program"):
        steps.append(Step("Tell GNOME too (older setting some apps still read)",
                          ["gsettings", "set", "org.gnome.desktop.default-applications.terminal", "exec", term["program"]], optional=True))
        if term.get("arg"):
            steps.append(Step("…and how to pass it a command", ["gsettings", "set", "org.gnome.desktop.default-applications.terminal",
                                                               "exec-arg", term["arg"]], optional=True))
    return steps


# ---------------------------------------------------------------- default browser / editor quick switches

def default_browser() -> str:
    return out(["xdg-settings", "get", "default-web-browser"], timeout=5) if has("xdg-settings") else ""


def default_for_mime(mime: str) -> str:
    return out(["xdg-mime", "query", "default", mime], timeout=5) if has("xdg-mime") else ""


def set_browser_steps(desktop_id: str, name: str = "") -> list[Step]:
    return [Step(f"Make {name or desktop_id} the default web browser", ["xdg-settings", "set", "default-web-browser", desktop_id])]


EDITOR_MIMES = ["text/plain", "text/markdown", "application/json", "text/x-python", "application/x-shellscript", "text/x-csrc",
                "application/javascript", "application/x-yaml", "application/toml"]


def set_editor_steps(desktop_id: str, name: str = "") -> list[Step]:
    return [Step(f"Open text and code files with {name or desktop_id}", ["xdg-mime", "default", desktop_id, *EDITOR_MIMES])]

