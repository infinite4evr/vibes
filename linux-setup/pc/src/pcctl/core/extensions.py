"""GNOME Shell extensions: list them, switch them on/off, open their settings, remove the ones you installed.

The `gnome-extensions` tool talks to the running GNOME Shell. When the Shell isn't reachable (another desktop, a remote
session, a test box) we fall back to reading the extension folders so the list still shows what's installed.
"""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .run import HOME, Step, has, out, read, sh

SHELL_SCHEMA = "org.gnome.shell"
USER_DIR = HOME / ".local/share/gnome-shell/extensions"
SYSTEM_DIRS = [Path("/usr/share/gnome-shell/extensions"), Path("/usr/local/share/gnome-shell/extensions")]
MODES_DIR = Path("/usr/share/gnome-shell/modes")
WEBSITE = "https://extensions.gnome.org"

# Ubuntu's own extensions, switched on by the Ubuntu session itself. Plain-English names for what they do.
BUILTIN = {
    "ubuntu-dock@ubuntu.com": "Ubuntu's dock (the app bar). Its options are on the Dock tab.",
    "ding@rastersoft.com": "Shows files and folders on the desktop background.",
    "ubuntu-appindicators@ubuntu.com": "Tray icons in the top bar for apps like Discord, Dropbox, Steam or VPNs.",
    "tiling-assistant@ubuntu.com": "Snap windows to halves and quarters of the screen by dragging them to an edge.",
    "snapd-prompting@canonical.com": "Asks you before a snap app can use your files, camera or microphone.",
    "web-search-provider@ubuntu.com": "Web search suggestions in the Activities search.",
}

STATES = {
    # GNOME 45+ names, then the older ones
    "ACTIVE": ("on", "ok"), "ACTIVATING": ("turning on", "info"), "INACTIVE": ("off", "neutral"), "DEACTIVATING": ("turning off", "info"),
    "ENABLED": ("on", "ok"), "ENABLING": ("turning on", "info"), "DISABLED": ("off", "neutral"), "DISABLING": ("turning off", "info"),
    "INITIALIZED": ("off", "neutral"), "ERROR": ("error", "bad"), "OUT OF DATE": ("needs an update", "warn"),
    "DOWNLOADING": ("downloading", "info"), "UNINSTALLED": ("removed", "neutral"), "UNKNOWN": ("unknown", "neutral"),
}


@dataclass
class Extension:
    uuid: str
    name: str = ""
    description: str = ""
    path: str = ""
    url: str = ""
    version: str = ""
    enabled: bool = False
    state: str = "UNKNOWN"
    has_prefs: bool = False
    user: bool = False          # installed in your home folder -> removable here
    builtin: bool = False       # part of Ubuntu
    extra: dict = field(default_factory=dict)

    @property
    def state_text(self) -> str:
        return STATES.get(self.state, (self.state.lower(), "neutral"))[0]

    @property
    def state_kind(self) -> str:
        return STATES.get(self.state, ("", "neutral"))[1]

    @property
    def problem(self) -> str:
        """A plain-English problem, or ''."""
        if self.state == "ERROR":
            return "It crashed while starting. Try turning it off and on, update it, or remove it."
        if self.state == "OUT OF DATE":
            return "It wasn't made for this GNOME version, so GNOME won't run it. Look for an update in Extension Manager."
        if self.enabled and self.state in ("INACTIVE", "DISABLED", "INITIALIZED"):
            return "Switched on, but not running yet - log out and back in (Wayland loads new extensions at login)."
        return ""

    @property
    def friendly(self) -> str:
        return BUILTIN.get(self.uuid) or self.description.split("\n")[0].strip()


# ---------------------------------------------------------------- parsing

_FIELD = re.compile(r"^  (Name|Description|Path|URL|Original author|Version|Enabled|State): ?(.*)$")


def parse_details(text: str) -> list[Extension]:
    """Parse `gnome-extensions list --details` (C locale).

    uuid
      Name: …
      Description: …        (may continue over several lines)
      Path: …
      URL: …
      Original author: …
      Version: 12  (or "Version: 1.2 (12)")
      Enabled: Yes
      State: ACTIVE
    """
    lines = text.splitlines()
    res: list[Extension] = []
    cur: Extension | None = None
    last = ""
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line and not line.startswith(" ") and nxt.startswith("  Name:"):
            cur = Extension(uuid=line.strip())
            res.append(cur)
            last = ""
            continue
        if cur is None:
            continue
        m = _FIELD.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            last = key
            if key == "Name":
                cur.name = val
            elif key == "Description":
                cur.description = val
            elif key == "Path":
                cur.path = val
            elif key == "URL":
                cur.url = val
            elif key == "Original author":
                cur.extra["author"] = val
            elif key == "Version":
                cur.version = val
            elif key == "Enabled":
                cur.enabled = val.lower() in ("yes", "true")
            elif key == "State":
                cur.state = val.upper()
        elif last == "Description":
            cur.description += "\n" + line
    for e in res:
        e.description = e.description.strip()
        _classify(e)
    return res


def _classify(e: Extension) -> None:
    home = str(HOME)
    e.user = bool(e.path) and (e.path.startswith(home + "/") or e.path.startswith("~") or "/.local/share/gnome-shell/extensions/" in e.path)
    e.builtin = e.uuid in BUILTIN and not e.user
    if not e.has_prefs and e.path:
        e.has_prefs = os.path.exists(os.path.join(e.path, "prefs.js"))
    if not e.name:
        e.name = e.uuid.split("@")[0].replace("-", " ").title()


def parse_strv(text: str) -> list[str]:
    """GVariant string list as printed by gsettings: "@as []" or "['a', 'b']"."""
    t = text.strip()
    if t.startswith("@as"):
        t = t[3:].strip()
    try:
        v = ast.literal_eval(t) if t else []
    except (ValueError, SyntaxError):
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def mode_extensions(modes_dir: Path = MODES_DIR) -> set[str]:
    """Extensions the Ubuntu session turns on by itself (ubuntu.json: enabledExtensions)."""
    res: set[str] = set()
    for f in sorted(modes_dir.glob("*.json")) if modes_dir.is_dir() else []:
        try:
            data = json.loads(read(f) or "{}")
        except ValueError:
            continue
        res.update(data.get("enabledExtensions", []))
    return res


def scan_dirs(user_dir: Path, system_dirs: list[Path], enabled: set[str], disabled: set[str], mode: set[str],
              user_off: bool = False) -> list[Extension]:
    """Fallback when GNOME Shell doesn't answer: read metadata.json from the extension folders."""
    seen: dict[str, Extension] = {}
    for base, is_user in [(user_dir, True)] + [(d, False) for d in system_dirs]:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            meta = d / "metadata.json"
            if not meta.is_file() or d.name in seen:
                continue
            try:
                m = json.loads(read(meta) or "{}")
            except ValueError:
                m = {}
            uuid = m.get("uuid") or d.name
            on = (uuid in enabled or uuid in mode) and uuid not in disabled
            if is_user and user_off and uuid not in mode:
                on = False
            e = Extension(uuid=uuid, name=m.get("name", ""), description=m.get("description", ""), path=str(d), url=m.get("url", ""),
                          version=str(m.get("version-name") or m.get("version") or ""), enabled=on, state="ACTIVE" if on else "INACTIVE",
                          has_prefs=(d / "prefs.js").exists())
            _classify(e)
            e.user = is_user
            e.builtin = uuid in BUILTIN and not is_user
            seen[d.name] = e
    return list(seen.values())


# ---------------------------------------------------------------- reading state

def _gget(key: str) -> str:
    return out(["gsettings", "get", SHELL_SCHEMA, key], timeout=5)


def extensions() -> dict:
    """{'available', 'live', 'reason', 'items': [Extension], 'user_extensions_on', 'manager'}"""
    res: dict = {"available": False, "live": False, "reason": "", "items": [], "user_extensions_on": True,
                 "manager": manager_app()}
    if not has("gnome-extensions") and not has("gsettings"):
        res["reason"] = "GNOME's extension tools aren't installed, so there's nothing to manage here."
        return res
    if has("gsettings"):
        res["user_extensions_on"] = _gget("disable-user-extensions") != "true"
    items: list[Extension] = []
    if has("gnome-extensions"):
        r = sh(["gnome-extensions", "list", "--details"], timeout=10)
        if r.ok and r.out.strip():
            items = parse_details(r.out)
            prefs = sh(["gnome-extensions", "list", "--prefs"], timeout=10)
            if prefs.ok:
                have = {ln.strip() for ln in prefs.out.splitlines() if ln.strip()}
                for e in items:
                    e.has_prefs = e.uuid in have or e.has_prefs
            res["live"] = True
    if not items:
        enabled = set(parse_strv(_gget("enabled-extensions"))) if has("gsettings") else set()
        disabled = set(parse_strv(_gget("disabled-extensions"))) if has("gsettings") else set()
        items = scan_dirs(USER_DIR, SYSTEM_DIRS, enabled, disabled, mode_extensions(), not res["user_extensions_on"])
        if items:
            res["reason"] = ("GNOME Shell isn't answering (you may not be in a GNOME desktop session), so this list comes from the "
                             "extension folders. Changes take effect the next time you log in to GNOME.")
        else:
            res["reason"] = "No GNOME Shell extensions found. Extensions only work in a GNOME desktop session."
    items.sort(key=lambda e: (not e.builtin, not e.user, e.name.lower()))
    res["items"] = items
    res["available"] = bool(items)
    return res


def manager_app() -> list[str] | None:
    """Command that opens the Extension Manager app (to browse and install new extensions), if it's installed."""
    if has("extension-manager"):
        return ["extension-manager"]
    if has("flatpak") and sh(["flatpak", "info", "com.mattjakeman.ExtensionManager"], timeout=5).ok:
        return ["flatpak", "run", "com.mattjakeman.ExtensionManager"]
    return None


# ---------------------------------------------------------------- actions

def toggle_steps(e: Extension | str, on: bool) -> list[Step]:
    uuid = e if isinstance(e, str) else e.uuid
    return [Step(f"{'Turn on' if on else 'Turn off'} {uuid}", ["gnome-extensions", "enable" if on else "disable", uuid])]


def prefs_cmd(e: Extension | str) -> list[str]:
    """Opens the extension's own settings window (not a system change, so not a Step)."""
    return ["gnome-extensions", "prefs", e if isinstance(e, str) else e.uuid]


def remove_steps(e: Extension) -> list[Step]:
    """Only extensions in your home folder can be removed here; system ones come from Ubuntu packages."""
    if not e.user:
        return []
    return [Step(f"Turn off {e.name}", ["gnome-extensions", "disable", e.uuid], optional=True),
            Step(f"Remove {e.name}", ["gnome-extensions", "uninstall", e.uuid])]


def remove_blocker(e: Extension) -> str:
    if e.user:
        return ""
    if e.builtin:
        return "This one is part of Ubuntu and can't be removed - you can switch it off instead."
    return "Installed for everyone by an Ubuntu package (in /usr/share), so it can't be removed here. Switch it off, or remove its package on the Apps page."


def global_steps(on: bool) -> list[Step]:
    """The master switch for all extensions you installed (Ubuntu's built-in ones keep working)."""
    return [Step(f"{'Allow' if on else 'Pause'} your extensions",
                 ["gsettings", "set", SHELL_SCHEMA, "disable-user-extensions", "false" if on else "true"])]
