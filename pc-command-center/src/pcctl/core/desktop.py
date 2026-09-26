"""Desktop options backed by GNOME settings (dock, Files app, windows) plus computer name, time zone and clock sync.

Each option knows where GNOME keeps it. Options whose schema or key doesn't exist on this PC are skipped, so the page
only shows what really works here. Changes are ordinary per-user `gsettings set` commands (no password), except the
computer name and time zone, which are system-wide.
"""

from __future__ import annotations

import os
import re
import shlex
import socket
from dataclasses import dataclass, field
from pathlib import Path

from .run import Step, has, out, read, sh
from .shortcuts import parse_list_recursively

DOCK = "org.gnome.shell.extensions.dash-to-dock"
NAUTILUS = "org.gnome.nautilus.preferences"
NAUTILUS_LIST = "org.gnome.nautilus.list-view"
GTK4_FC = "org.gtk.gtk4.Settings.FileChooser"
GTK3_FC = "org.gtk.Settings.FileChooser"
WM = "org.gnome.desktop.wm.preferences"
DATETIME = "org.gnome.desktop.datetime"
LOCATION = "org.gnome.system.location"


@dataclass
class Opt:
    """One option. kind: switch | choice | number.

    switch: `on`/`off` are GVariant texts for the key.
    choice: options = [(label, {key: value, ...})] - one option may set several keys of the same schema.
    number: lo/hi/step, value written as a plain number.
    `also` lists other (schema, key) places that mirror the same switch (e.g. GTK 3 and GTK 4 file choosers)."""
    id: str
    group: str
    title: str
    desc: str
    schema: str
    key: str
    kind: str = "switch"
    on: str = "true"
    off: str = "false"
    options: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    lo: float = 0
    hi: float = 100
    step: float = 1
    unit: str = ""
    also: list[tuple[str, str]] = field(default_factory=list)

    def places(self) -> list[tuple[str, str]]:
        return [(self.schema, self.key), *self.also]


def one(label: str, key: str, value: str) -> tuple[str, dict[str, str]]:
    return (label, {key: value})


# ---------------------------------------------------------------- the options

DOCK_OPTS = [
    Opt("dock-pos", "Dock", "Where the dock sits", "", DOCK, "dock-position", "choice",
        options=[one("Bottom", "dock-position", "'BOTTOM'"), one("Left", "dock-position", "'LEFT'"), one("Right", "dock-position", "'RIGHT'")]),
    Opt("dock-size", "Dock", "Icon size", "Bigger icons are easier to hit; smaller ones fit more apps.", DOCK, "dash-max-icon-size", "number",
        lo=16, hi=64, step=4, unit="px"),
    Opt("dock-hide", "Dock", "Hide the dock", "“When a window is near” hides it only when a window would overlap it. A hidden dock comes back when you push the mouse against that screen edge.", DOCK, "dock-fixed", "choice",
        options=[("Never - always visible", {"dock-fixed": "true"}),
                 ("When a window is near", {"dock-fixed": "false", "autohide": "true", "intellihide": "true"}),
                 ("Always", {"dock-fixed": "false", "autohide": "true", "intellihide": "false"})]),
    Opt("dock-extend", "Dock", "Stretch across the whole edge", "On: a full-length panel (Ubuntu's default). Off: a compact floating dock in the middle.",
        DOCK, "extend-height"),
    Opt("dock-click", "Dock", "Clicking an app that's already open", "", DOCK, "click-action", "choice",
        options=[one("Minimise it (like Windows)", "click-action", "'minimize'"),
                 one("Minimise, or show previews if it has several windows", "click-action", "'minimize-or-previews'"),
                 one("Bring it forward, or show previews", "click-action", "'focus-or-previews'"),
                 one("Switch between its windows", "click-action", "'cycle-windows'"),
                 one("Show all its windows side by side", "click-action", "'focus-or-appspread'")]),
    Opt("dock-scroll", "Dock", "Scrolling on an app's icon", "", DOCK, "scroll-action", "choice",
        options=[one("Does nothing", "scroll-action", "'do-nothing'"), one("Switches between its windows", "scroll-action", "'cycle-windows'"),
                 one("Switches workspace", "scroll-action", "'switch-workspace'")]),
    Opt("dock-trash", "Dock", "Show the Trash", "", DOCK, "show-trash"),
    Opt("dock-mounts", "Dock", "Show USB sticks and other drives", "Handy for ejecting them with a right-click.", DOCK, "show-mounts"),
    Opt("dock-apps-top", "Dock", "Put the Show Apps button first", "At the top of a side dock, or at the left end of a bottom dock.", DOCK, "show-apps-at-top"),
    Opt("dock-dots", "Dock", "Open-app markers", "The little marks under apps that are running.", DOCK, "running-indicator-style", "choice",
        options=[one("Ubuntu's default", "running-indicator-style", "'DEFAULT'"), one("Dots", "running-indicator-style", "'DOTS'"),
                 one("Dashes", "running-indicator-style", "'DASHES'"), one("Squares", "running-indicator-style", "'SQUARES'"),
                 one("Segmented bar", "running-indicator-style", "'SEGMENTED'"), one("Solid bar", "running-indicator-style", "'SOLID'")]),
    Opt("dock-monitors", "Dock", "Show the dock on every screen", "With more than one monitor.", DOCK, "multi-monitor"),
    Opt("dock-isolate", "Dock", "Only show apps from the current workspace", "", DOCK, "isolate-workspaces"),
    Opt("dock-hotkeys", "Dock", "Super + number opens dock apps", "Super+1 opens (or switches to) the first app in the dock, Super+2 the second…",
        DOCK, "hot-keys"),
]

FILES_OPTS = [
    Opt("files-hidden", "Files", "Show hidden files", "Files and folders whose names start with a dot (.env, .git, .config). Ctrl+H switches this in Files too.",
        GTK4_FC, "show-hidden", also=[(NAUTILUS, "show-hidden-files"), (GTK3_FC, "show-hidden")]),
    Opt("files-dirs-first", "Files", "Folders before files", "Sort folders to the top, like Windows Explorer.", GTK4_FC, "sort-directories-first",
        also=[(NAUTILUS, "sort-directories-first"), (GTK3_FC, "sort-directories-first")]),
    Opt("files-perm-delete", "Files", "“Delete Permanently” in the right-click menu", "Skips the Trash. Shift+Delete does the same.", NAUTILUS,
        "show-delete-permanently"),
    Opt("files-link", "Files", "“Create Link” in the right-click menu", "Makes a shortcut (symlink) to a file or folder.", NAUTILUS, "show-create-link"),
    Opt("files-view", "Files", "Show folders as", "", NAUTILUS, "default-folder-viewer", "choice",
        options=[one("Grid of icons", "default-folder-viewer", "'icon-view'"), one("List with details", "default-folder-viewer", "'list-view'")]),
    Opt("files-tree", "Files", "Expandable folders in list view", "Adds a little arrow to open folders in place, like a tree.", NAUTILUS_LIST,
        "use-tree-view"),
    Opt("files-click", "Files", "Open items with", "", NAUTILUS, "click-policy", "choice",
        options=[one("Double-click (like Windows)", "click-policy", "'double'"), one("Single click (like a web page)", "click-policy", "'single'")]),
    Opt("files-thumbs", "Files", "Picture and video previews", "Previews on network folders and USB drives can be slow.", NAUTILUS,
        "show-image-thumbnails", "choice",
        options=[one("Only for files on this computer", "show-image-thumbnails", "'local-only'"),
                 one("Everywhere (also network folders)", "show-image-thumbnails", "'always'"),
                 one("Never", "show-image-thumbnails", "'never'")]),
    Opt("files-thumb-limit", "Files", "No previews for files bigger than", "Very large files take a while to preview.", NAUTILUS, "thumbnail-limit",
        "number", lo=1, hi=4096, step=10, unit="MB"),
    Opt("files-count", "Files", "Count the items in folders", "Shown in list view. Counting on network folders can be slow.", NAUTILUS,
        "show-directory-item-counts", "choice",
        options=[one("Only on this computer", "show-directory-item-counts", "'local-only'"), one("Everywhere", "show-directory-item-counts", "'always'"),
                 one("Never", "show-directory-item-counts", "'never'")]),
    Opt("files-search", "Files", "Search inside sub-folders", "", NAUTILUS, "recursive-search", "choice",
        options=[one("Only on this computer (faster)", "recursive-search", "'local-only'"), one("Everywhere", "recursive-search", "'always'"),
                 one("Never", "recursive-search", "'never'")]),
    Opt("files-dates", "Files", "Dates", "", NAUTILUS, "date-time-format", "choice",
        options=[one("Friendly (Yesterday, 10:32)", "date-time-format", "'simple'"), one("Exact date and time", "date-time-format", "'detailed'")]),
]

WINDOW_OPTS = [
    Opt("win-buttons", "Windows", "Title-bar buttons", "Minimise, maximise and close buttons in each window's top corner. GNOME shows only close; Windows shows all three on the right.", WM, "button-layout", "choice",
        options=[one("All three, on the right", "button-layout", "'appmenu:minimize,maximize,close'"),
                 one("Minimise and close", "button-layout", "'appmenu:minimize,close'"),
                 one("Close only", "button-layout", "'appmenu:close'"),
                 one("All three, on the left (Mac style)", "button-layout", "'close,minimize,maximize:appmenu'")]),
    Opt("win-dblclick", "Windows", "Double-clicking a title bar", "", WM, "action-double-click-titlebar", "choice",
        options=[one("Maximises / restores", "action-double-click-titlebar", "'toggle-maximize'"),
                 one("Minimises it", "action-double-click-titlebar", "'minimize'"),
                 one("Does nothing", "action-double-click-titlebar", "'none'")]),
    Opt("win-midclick", "Windows", "Middle-clicking a title bar", "", WM, "action-middle-click-titlebar", "choice",
        options=[one("Does nothing", "action-middle-click-titlebar", "'none'"), one("Sends it to the back", "action-middle-click-titlebar", "'lower'"),
                 one("Minimises it", "action-middle-click-titlebar", "'minimize'")]),
    Opt("win-resize", "Windows", "Resize with Super + right-drag", "Hold the Super (Windows) key and drag with the right mouse button to resize a "
        "window from anywhere; the left button moves it.", WM, "resize-with-right-button"),
]

ALL_OPTS = DOCK_OPTS + FILES_OPTS + WINDOW_OPTS


# ---------------------------------------------------------------- reading

def norm(v: str) -> str:
    """Compare GVariant texts loosely: 'uint32 48' == '48', 0.80000000000000004 == 0.8."""
    v = v.strip()
    v = re.sub(r"^(u?int(16|32|64)|byte|double)\s+", "", v)
    try:
        f = float(v)
        return repr(round(f, 6))
    except ValueError:
        return v


def read_values(schemas: list[str]) -> dict[tuple[str, str], str]:
    """One `gsettings list-recursively` per schema (fast), missing schemas are simply absent."""
    res: dict[tuple[str, str], str] = {}
    if not has("gsettings"):
        return res
    for schema in dict.fromkeys(schemas):
        r = sh(["gsettings", "list-recursively", schema], timeout=5)
        if r.ok:
            res.update(parse_list_recursively(r.out))
    return res


def present(o: Opt, values: dict[tuple[str, str], str]) -> list[tuple[str, str]]:
    """The places this option exists on this PC (empty list -> skip the option)."""
    if o.kind == "choice":
        keys = {k for _, d in o.options for k in d}
        return [(o.schema, o.key)] if all((o.schema, k) in values for k in keys) else []
    return [p for p in o.places() if p in values]


def current(o: Opt, values: dict[tuple[str, str], str]):
    """switch -> bool | None, choice -> option index or -1, number -> float | None"""
    places = present(o, values)
    if not places:
        return None
    v = values[places[0]]
    if o.kind == "switch":
        return True if norm(v) == norm(o.on) else (False if norm(v) == norm(o.off) else None)
    if o.kind == "choice":
        for i, (_, d) in enumerate(o.options):
            if all(norm(values.get((o.schema, k), "")) == norm(val) for k, val in d.items()):
                return i
        return -1
    try:
        return float(norm(v))
    except ValueError:
        return None


def options(opts: list[Opt]) -> list[tuple[Opt, object]]:
    """[(option, current value)] for the options that exist here."""
    values = read_values([s for o in opts for s, _ in o.places()])
    return [(o, current(o, values)) for o in opts if present(o, values)]


def dock_available() -> bool:
    return has("gsettings") and sh(["gsettings", "list-keys", DOCK], timeout=5).ok


# ---------------------------------------------------------------- writing

def gv(value: str) -> str:
    """'BOTTOM' -> BOTTOM: gsettings accepts plain words for string keys, and the command reads better."""
    m = re.fullmatch(r"'([A-Za-z0-9_:,.+-]+)'", value)
    return m.group(1) if m else value


def set_steps(o: Opt, value, values: dict[tuple[str, str], str] | None = None) -> list[Step]:
    """Steps that set option `o` to `value` (bool for switches, option index for choices, number for numbers)."""
    places = present(o, values) if values is not None else o.places()
    if o.kind == "switch":
        v = o.on if value else o.off
        return [Step(f"{o.title}: {'on' if value else 'off'}", ["gsettings", "set", s, k, gv(v)]) for s, k in places]
    if o.kind == "choice":
        label, d = o.options[int(value)]
        return [Step(f"{o.title}: {label}", ["gsettings", "set", o.schema, k, gv(v)]) for k, v in d.items()]
    num = max(o.lo, min(o.hi, float(value)))
    text = str(int(num)) if float(num).is_integer() else str(num)
    return [Step(f"{o.title}: {text}{(' ' + o.unit) if o.unit else ''}", ["gsettings", "set", s, k, text]) for s, k in places]


def reset_steps(opts: list[Opt]) -> list[Step]:
    """Put every key these options touch back to GNOME/Ubuntu defaults."""
    seen: dict[tuple[str, str], None] = {}
    for o in opts:
        keys = [(o.schema, k) for _, d in o.options for k in d] if o.kind == "choice" else o.places()
        for p in keys:
            seen[p] = None
    return [Step(f"Reset {k}", ["gsettings", "reset", s, k], optional=True) for s, k in seen]


def run_quiet(steps: list[Step]) -> tuple[bool, list[str]]:
    """Run small per-user steps (gsettings, git config…) without a dialog. Returns (ok, output lines). Refuses admin steps."""
    lines: list[str] = []
    for s in steps:
        if s.root:
            return False, ["needs admin rights - run it through the normal confirm dialog"]
        func = getattr(s, "_func", None)
        if func is not None:
            try:
                msg = func()
                if msg:
                    lines += str(msg).splitlines()
            except Exception as e:  # noqa: BLE001
                lines.append(f"error: {e}")
                if not s.optional:
                    return False, lines
            continue
        r = sh(s.argv(), timeout=30, cwd=s.cwd)
        lines += [ln for ln in (r.out + r.err).splitlines() if ln.strip()]
        if r.code not in s.ok_codes and not s.optional:
            return False, lines
    return True, lines


# ---------------------------------------------------------------- computer name

def hostname_info() -> dict:
    static = out(["hostnamectl", "--static"], timeout=5) or read("/etc/hostname").strip() or socket.gethostname()
    pretty = out(["hostnamectl", "--pretty"], timeout=5)
    return {"static": static, "pretty": pretty, "current": socket.gethostname()}


def hostname_problem(name: str) -> str:
    """'' if `name` is a valid computer name, else why not (plain English)."""
    if not name:
        return "Type a name."
    if len(name) > 63:
        return "Keep it under 64 characters."
    if not re.fullmatch(r"[A-Za-z0-9-]+", name):
        return "Use only letters, numbers and dashes (no spaces, dots or underscores)."
    if name.startswith("-") or name.endswith("-"):
        return "It can't start or end with a dash."
    if name.isdigit():
        return "It needs at least one letter."
    return ""


def suggest_hostname(text: str) -> str:
    """'Ashu's Laptop 2' -> 'ashus-laptop-2'"""
    s = text.strip().lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:63].strip("-")


def hosts_cmd(new: str, path: str = "/etc/hosts") -> list[str]:
    """Point the 127.0.1.1 line of /etc/hosts at the new name (so sudo and local tools don't complain)."""
    if hostname_problem(new):
        raise ValueError(f"invalid hostname: {new!r}")
    p = shlex.quote(path)
    script = (f"if grep -q '^127\\.0\\.1\\.1[[:space:]]' {p}; then "
              f"sed -i 's/^127\\.0\\.1\\.1[[:space:]].*/127.0.1.1\\t{new}/' {p}; "
              f"else printf '127.0.1.1\\t{new}\\n' >> {p}; fi")
    return ["bash", "-c", script]


def hostname_steps(new: str) -> list[Step]:
    if hostname_problem(new):
        return []
    return [Step(f"Rename this computer to {new}", ["hostnamectl", "set-hostname", new], root=True),
            Step("Update /etc/hosts to the new name", hosts_cmd(new), root=True)]


# ---------------------------------------------------------------- time zone and clock sync

def parse_kv(text: str) -> dict[str, str]:
    res = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            res[k.strip()] = v.strip()
    return res


def parse_zone_tab(text: str) -> list[str]:
    """zone1970.tab / zone.tab: 'CC<TAB>coords<TAB>Zone/Name<TAB>comment'"""
    zones = set()
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and "/" in parts[2]:
            zones.add(parts[2].strip())
    return sorted(zones)


def local_timezone() -> str:
    tz = read("/etc/timezone").strip()
    if tz:
        return tz
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        return ""
    m = re.search(r"zoneinfo/(.+)$", link)
    return m.group(1) if m else ""


def timezones() -> list[str]:
    zones = [z for z in out(["timedatectl", "list-timezones", "--no-pager"], timeout=10).splitlines() if z.strip()]
    if zones:
        return zones
    for f in ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab"):
        if Path(f).exists():
            zones = parse_zone_tab(read(f))
            if zones:
                return sorted(set(zones) | {"UTC"})
    return ["UTC"]


def parse_chrony_tracking(text: str) -> dict:
    """`chronyc tracking` -> {'source', 'offset', 'leap', 'synced', 'stratum'}"""
    kv = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        if sep:
            kv[k.strip()] = v.strip()
    ref = kv.get("Reference ID", "")
    m = re.search(r"\(([^)]+)\)", ref)
    source = m.group(1) if m else ref
    offset = ""
    m = re.match(r"([\d.]+) seconds (fast|slow)", kv.get("System time", ""))
    if m:
        secs = float(m.group(1))
        offset = (f"{secs * 1000:.1f} ms" if secs < 1 else f"{secs:.1f} s") + f" {m.group(2)}"
    leap = kv.get("Leap status", "")
    synced = bool(ref) and not ref.startswith("00000000") and leap.lower() != "not synchronised"
    return {"source": source, "offset": offset, "leap": leap, "synced": synced, "stratum": kv.get("Stratum", "")}


def time_info() -> dict:
    kv = parse_kv(out(["timedatectl", "show"], timeout=5))
    info = {"timezone": kv.get("Timezone") or local_timezone() or "UTC", "ntp": None, "synced": None, "service": "",
            "chrony": {}, "auto_tz": None, "location_on": None, "timedated": bool(kv)}
    if kv:
        info["ntp"] = kv.get("NTP") == "yes"
        info["synced"] = kv.get("NTPSynchronized") == "yes"
    if has("chronyc"):
        info["service"] = "Chrony"
        tr = sh(["chronyc", "-n", "tracking"], timeout=5)
        if tr.ok:
            info["chrony"] = parse_chrony_tracking(tr.out)
            if info["synced"] is None:
                info["synced"] = info["chrony"]["synced"]
    elif kv:
        info["service"] = "systemd-timesyncd"
    vals = read_values([DATETIME, LOCATION])
    if (DATETIME, "automatic-timezone") in vals:
        info["auto_tz"] = vals[(DATETIME, "automatic-timezone")] == "true"
    if (LOCATION, "enabled") in vals:
        info["location_on"] = vals[(LOCATION, "enabled")] == "true"
    return info


def timezone_steps(zone: str) -> list[Step]:
    return [Step(f"Set the time zone to {zone}", ["timedatectl", "set-timezone", zone], root=True)]


def ntp_steps(on: bool) -> list[Step]:
    return [Step(f"{'Turn on' if on else 'Turn off'} automatic time", ["timedatectl", "set-ntp", "true" if on else "false"], root=True)]


def auto_tz_steps(on: bool) -> list[Step]:
    return [Step(f"{'Turn on' if on else 'Turn off'} automatic time zone", ["gsettings", "set", DATETIME, "automatic-timezone", "true" if on else "false"])]
