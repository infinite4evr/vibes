"""Your own keyboard shortcuts (GNOME "custom shortcuts"), e.g. Ctrl+Shift+Esc opens Processes like on Windows.

GNOME keeps them as a list of dconf paths in org.gnome.settings-daemon.plugins.media-keys custom-keybindings; each path
holds name / command / binding. We only ever append our own paths and only ever remove our own, so shortcuts you made
in GNOME Settings are never touched.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
from dataclasses import dataclass

from .extensions import parse_strv
from .run import HOME, Step, has, out, sh, which

MK = "org.gnome.settings-daemon.plugins.media-keys"
CK = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
TASKMGR_ID = "pc-taskmgr"

# Where GNOME's built-in shortcuts live (to warn about clashes).
BUILTIN_SCHEMAS = ["org.gnome.desktop.wm.keybindings", "org.gnome.shell.keybindings", "org.gnome.mutter.keybindings",
                   "org.gnome.mutter.wayland.keybindings", MK, "org.gnome.shell.extensions.dash-to-dock"]

_MODS = {"control": "Ctrl", "ctrl": "Ctrl", "primary": "Ctrl", "shift": "Shift", "alt": "Alt", "mod1": "Alt", "super": "Super",
         "mod4": "Super", "meta": "Meta", "hyper": "Hyper"}
_ORDER = ["Super", "Ctrl", "Alt", "Shift", "Meta", "Hyper"]
_KEYNAMES = {"escape": "Esc", "return": "Enter", "kp_enter": "Enter", "delete": "Delete", "backspace": "Backspace", "space": "Space",
             "print": "Print Screen", "tab": "Tab", "up": "↑", "down": "↓", "left": "←", "right": "→", "page_up": "Page Up",
             "page_down": "Page Down", "home": "Home", "end": "End", "insert": "Insert", "pause": "Pause"}


@dataclass
class Shortcut:
    path: str
    name: str
    command: str
    binding: str

    @property
    def id(self) -> str:
        return self.path.rstrip("/").rsplit("/", 1)[-1]

    @property
    def ours(self) -> bool:
        return self.id.startswith("pc-")

    @property
    def keys(self) -> str:
        return pretty(self.binding) or "no key set"


# ---------------------------------------------------------------- accelerators

def split_accel(accel: str) -> tuple[frozenset[str], str]:
    """'<Control><Shift>Escape' -> ({'Ctrl', 'Shift'}, 'escape')"""
    mods = set()
    rest = accel.strip()
    while True:
        m = re.match(r"^<([A-Za-z0-9_]+)>", rest)
        if not m:
            break
        mods.add(_MODS.get(m.group(1).lower(), m.group(1).title()))
        rest = rest[m.end():]
    return frozenset(mods), rest.strip().lower()


def pretty(accel: str) -> str:
    """'<Control><Shift>Escape' -> 'Ctrl+Shift+Esc'"""
    if not accel or accel.lower() == "disabled":
        return ""
    mods, key = split_accel(accel)
    if not key:
        return ""
    name = _KEYNAMES.get(key) or (key.upper() if len(key) == 1 else key.replace("_", " ").title())
    return "+".join([m for m in _ORDER if m in mods] + sorted(m for m in mods if m not in _ORDER) + [name])


def valid_accel(accel: str) -> bool:
    """A GTK accelerator like <Super>t or <Primary><Alt>Delete: modifiers in <>, then one key name."""
    return bool(re.fullmatch(r"(<[A-Za-z0-9_]+>)*[A-Za-z0-9_]+", accel.strip())) and bool(split_accel(accel)[1])


def same_accel(a: str, b: str) -> bool:
    return bool(a and b) and split_accel(a) == split_accel(b)


def parse_list_recursively(text: str) -> dict[tuple[str, str], str]:
    """`gsettings list-recursively` lines 'schema key value' -> {(schema, key): value}"""
    res = {}
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            res[(parts[0], parts[1])] = parts[2].strip()
    return res


def accels_in(value: str) -> list[str]:
    """A gsettings value holding one accelerator ('<Super>e') or a list (['<Super>e', '<Alt>F2'])."""
    v = value.strip()
    if v.startswith(("[", "@as")):
        return [a for a in parse_strv(v) if a]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        s = gv_string(v)
        return [s] if s else []
    return []


def find_conflicts(binding: str, settings: dict[tuple[str, str], str], custom: list[Shortcut], skip_path: str = "") -> list[str]:
    """Names of other shortcuts already using this key combination."""
    res = []
    for (_schema, key), value in settings.items():
        if key == "custom-keybindings":
            continue
        if any(same_accel(binding, a) for a in accels_in(value)):
            res.append(f"GNOME: {key.replace('-', ' ')}")
    for s in custom:
        if s.path != skip_path and same_accel(binding, s.binding):
            res.append(f"Your shortcut “{s.name}”")
    return res


# ---------------------------------------------------------------- reading

def available() -> bool:
    return has("gsettings") and sh(["gsettings", "list-keys", MK], timeout=5).ok


def custom_paths() -> list[str]:
    return parse_strv(out(["gsettings", "get", MK, "custom-keybindings"], timeout=5))


def read_shortcut(path: str) -> Shortcut:
    vals = parse_list_recursively(out(["gsettings", "list-recursively", f"{CK}:{path}"], timeout=5))

    def g(k: str) -> str:
        return gv_string(vals.get((CK, k), "''"))
    return Shortcut(path, g("name"), g("command"), g("binding"))


def gv_string(v: str) -> str:
    """GVariant text of a string ('abc' or "it's") -> the string."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        try:
            res = ast.literal_eval(v)
            return res if isinstance(res, str) else v
        except (ValueError, SyntaxError):
            return v[1:-1]
    return v


def custom_shortcuts() -> list[Shortcut]:
    if not available():
        return []
    return [read_shortcut(p) for p in custom_paths()]


def builtin_settings() -> dict[tuple[str, str], str]:
    res: dict[tuple[str, str], str] = {}
    for schema in BUILTIN_SCHEMAS:
        r = sh(["gsettings", "list-recursively", schema], timeout=5)
        if r.ok:
            res.update(parse_list_recursively(r.out))
    return res


# ---------------------------------------------------------------- commands we suggest

def app_command(page: str | None = None) -> str:
    """The same launcher the app's .desktop file uses (~/.local/bin/pc-gui), with an absolute path because
    GNOME runs shortcut commands without your terminal's PATH."""
    exe = which("pc-gui")
    if not exe and (HOME / ".local/bin/pc-gui").exists():
        exe = str(HOME / ".local/bin/pc-gui")
    exe = exe or "pc-gui"
    return f"{exe} --page {page}" if page else exe


def terminal_command() -> tuple[str, str]:
    """(name, command) for the user's terminal: Ghostty if installed."""
    for name, cmd in (("Ghostty", "ghostty"), ("Ptyxis", "ptyxis"), ("GNOME Terminal", "gnome-terminal"), ("Console", "kgx")):
        exe = which(cmd)
        if exe:
            return name, exe
    return "Terminal", "x-terminal-emulator"


def presets() -> list[dict]:
    """Ready-made shortcuts the page offers with one click."""
    term, term_cmd = terminal_command()
    return [
        {"id": TASKMGR_ID, "name": "Open Processes (task manager)", "command": app_command("processes"), "binding": "<Control><Shift>Escape",
         "why": "Like Windows: see what's slowing the PC down and stop a frozen app."},
        {"id": "pc-terminal", "name": f"Open a terminal ({term})", "command": term_cmd, "binding": "<Super>Return",
         "why": "Ctrl+Alt+T also works; this one is a single reach with your thumb."},
        {"id": "pc-app", "name": "Open PC Command Center", "command": app_command(), "binding": "<Control><Alt>p",
         "why": "Jump straight to this app from anywhere."},
    ]


# ---------------------------------------------------------------- actions

def _q(s: str) -> str:
    """A string value for `gsettings set`. gsettings takes plain text for string keys when it isn't GVariant syntax,
    so only values starting with a quote or @ need GVariant quoting (keeps the commands we show readable)."""
    if s and not s.startswith(("'", '"', "@")):
        return s
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _gq(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def strv(items: list[str]) -> str:
    return "[" + ", ".join(_gq(i) for i in items) + "]" if items else "@as []"


def new_id(paths: list[str], stem: str = "pc-custom") -> str:
    used = {p.rstrip("/").rsplit("/", 1)[-1] for p in paths}
    i = 0
    while f"{stem}{i}" in used:
        i += 1
    return f"{stem}{i}"


def add_steps(paths: list[str], sid: str, name: str, command: str, binding: str) -> list[Step]:
    """Create (or update) shortcut `sid` and add it to GNOME's list without touching the others."""
    path = f"{BASE}{sid}/"
    loc = f"{CK}:{path}"
    steps = [Step(f"Name it “{name}”", ["gsettings", "set", loc, "name", _q(name)]),
             Step("Set the command", ["gsettings", "set", loc, "command", _q(command)]),
             Step(f"Set the keys: {pretty(binding)}", ["gsettings", "set", loc, "binding", _q(binding)])]
    if path not in paths:
        steps.append(Step("Add it to your shortcuts", ["gsettings", "set", MK, "custom-keybindings", strv([*paths, path])]))
    return steps


def remove_steps(paths: list[str], path: str) -> list[Step]:
    """Remove one shortcut from the list (others stay exactly as they are), then clear its settings."""
    rest = [p for p in paths if p != path]
    loc = f"{CK}:{path}"
    return [Step("Remove it from your shortcuts", ["gsettings", "set", MK, "custom-keybindings", strv(rest)])] + [
        Step(f"Clear its {k}", ["gsettings", "reset", loc, k], optional=True) for k in ("name", "command", "binding")]


def command_ok(command: str) -> str:
    """'' if the command's program can be found, else a plain-English warning."""
    try:
        prog = shlex.split(command)[0] if command.strip() else ""
    except ValueError:
        return "The command has an unmatched quote."
    if not prog:
        return "Type a command to run."
    if os.path.isabs(prog):
        return "" if os.access(prog, os.X_OK) else f"{prog} doesn't exist or can't be run."
    return "" if which(prog) else f"“{prog}” wasn't found. Use the full path (e.g. /usr/bin/{prog}) if it lives somewhere unusual."
