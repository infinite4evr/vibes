"""The app updating and removing itself.

The installer (`bash setup.sh app` in ubuntu-setup) copies the code from the pc-command-center folder next to it to
~/.local/share/pc-command-center. When that folder has newer code (you pulled a newer vibes), the Maintenance page offers
to update in place.
Uninstall removes everything the installer added and, if you want, your settings.
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
from pathlib import Path

from .. import __version__
from .run import HOME, Step, has, py_step, read

APP_ID = "io.github.infinite4evr.PcCommandCenter"
APP_DIR = HOME / ".local/share/pc-command-center"
LAUNCHER = HOME / ".local/bin/pc-gui"
DESKTOP = HOME / f".local/share/applications/{APP_ID}.desktop"
ICON = HOME / f".local/share/icons/hicolor/scalable/apps/{APP_ID}.svg"
ZSH_COMP = HOME / ".local/share/zsh/site-functions/_pc"
BASH_COMP = HOME / ".local/share/bash-completion/completions/pc"
DBUS_SERVICE = HOME / f".local/share/dbus-1/services/{APP_ID}.SearchProvider.service"
SEARCH_INI = Path(f"/usr/local/share/gnome-shell/search-providers/{APP_ID}.search-provider.ini")
HELPER = Path("/usr/local/libexec/pc-command-center/pc-admin")
POLICY = Path(f"/usr/share/polkit-1/actions/{APP_ID}.policy")
USER_UNITS = ["pc-maintain.service", "pc-maintain.timer", "pc-watch.service", "pc-watch.timer"]
VENV = HOME / ".local/share/pc/venv"
BUS_NAME = f"{APP_ID}.SearchProvider"
OBJECT_PATH = "/io/github/infinite4evr/PcCommandCenter/SearchProvider"
INI = f"""[Shell Search Provider]
DesktopId={APP_ID}.desktop
BusName={BUS_NAME}
ObjectPath={OBJECT_PATH}
Version=2
"""


def service_file(exec_cmd: str) -> str:
    return f"[D-BUS Service]\nName={BUS_NAME}\nExec={exec_cmd} --search-provider\n"


def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"""__version__\s*=\s*["']([\d.]+)""", text)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def vstr(v: tuple[int, ...]) -> str:
    return ".".join(map(str, v)) if v else "?"


def _newest(folder: Path) -> float:
    newest = 0.0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".py", ".css", ".svg")):
                try:
                    newest = max(newest, os.stat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return newest


def _differs(a: Path, b: Path) -> bool:
    """True when the two code folders aren't identical (ignores caches)."""
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pytest_cache"])

    def walk(c) -> bool:
        if c.left_only or c.right_only or c.diff_files or c.funny_files:
            return True
        return any(walk(sub) for sub in c.subdirs.values())
    return walk(cmp)


def source_dir() -> Path | None:
    """The pc-command-center folder next to ubuntu-setup (where updates come from)."""
    from . import maint
    d = maint.setup_dir()
    if not d:
        return None
    # the older layout kept the app inside the setup folder as pc/
    for cand in (d.parent / "pc-command-center", d / "pc"):
        if (cand / "src/pcctl/__init__.py").exists():
            return cand
    return None


def status() -> dict:
    """{installed, running, source, source_version, update, reason, running_from_install}"""
    running = parse_version(f'__version__ = "{__version__}"')
    installed = parse_version(read(APP_DIR / "pcctl/__init__.py"))
    src = source_dir()
    res = {"running": vstr(running), "installed": vstr(installed) if installed else "", "source": str(src) if src else "",
           "source_version": "", "update": False, "reason": "", "installed_app": APP_DIR.exists(),
           "running_from_install": Path(__file__).resolve().is_relative_to(APP_DIR.resolve()) if APP_DIR.exists() else False}
    if not src:
        res["reason"] = "The pc-command-center folder wasn't found, so there's nothing to compare with."
        return res
    sv = parse_version(read(src / "src/pcctl/__init__.py"))
    res["source_version"] = vstr(sv)
    if not APP_DIR.exists():
        res["update"] = True
        res["reason"] = "The app isn't installed as a normal app yet (it runs straight from the folder)."
        return res
    if sv > installed:
        res["update"], res["reason"] = True, f"Version {vstr(sv)} is in your pc-command-center folder (you have {vstr(installed)})."
    elif sv == installed and _differs(src / "src/pcctl", APP_DIR / "pcctl") and _newest(src / "src/pcctl") > _newest(APP_DIR / "pcctl"):
        res["update"], res["reason"] = True, "Your pc-command-center folder has newer fixes for this version."
    else:
        res["reason"] = "You have the newest version from your pc-command-center folder."
    return res


def _copy_code(src: Path) -> str:
    new = APP_DIR.with_name(APP_DIR.name + ".new")
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(src / "src/pcctl", new / "pcctl", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    old = APP_DIR.with_name(APP_DIR.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if APP_DIR.exists():
        APP_DIR.rename(old)
    new.rename(APP_DIR)
    # Keep the immediately previous application tree until the user has launched
    # and validated the replacement. This makes a failed update recoverable.
    return f"copied the new code to {str(APP_DIR).replace(str(HOME), '~')} (previous version kept for rollback)"



def rollback_available() -> bool:
    return APP_DIR.with_name(APP_DIR.name + ".old").is_dir()


def _rollback_code() -> str:
    old = APP_DIR.with_name(APP_DIR.name + ".old")
    if not old.is_dir():
        raise FileNotFoundError("No previous PC Command Center version is available")
    failed = APP_DIR.with_name(APP_DIR.name + ".failed")
    shutil.rmtree(failed, ignore_errors=True)
    if APP_DIR.exists():
        APP_DIR.rename(failed)
    old.rename(APP_DIR)
    return "restored the previous PC Command Center version; restart the app to use it"


def rollback_steps() -> list[Step]:
    return [py_step("Restore the previous version", _rollback_code, "restore ~/.local/share/pc-command-center.old")] if rollback_available() else []

def update_steps() -> list[Step]:
    src = source_dir()
    if not src:
        return []
    steps = [py_step("Copy the new version", lambda: _copy_code(src), f"copy {src}/src/pcctl → ~/.local/share/pc-command-center")]
    if has("uv"):
        steps.append(Step("Update the terminal version (pc)", ["uv", "tool", "install", "--force", "--reinstall", str(src)], optional=True))
    elif (VENV / "bin/pip").exists():
        steps.append(Step("Update the terminal version (pc)", [str(VENV / "bin/pip"), "install", "-q", "--upgrade", str(src)], optional=True))
    steps.append(Step("Refresh Tab completion", ["bash", "-c", f"mkdir -p {ZSH_COMP.parent} {BASH_COMP.parent} && "
                                                              f"pc completions zsh > {ZSH_COMP} && pc completions bash > {BASH_COMP}"], optional=True))
    root = admin_install_steps(src)
    return steps + root


def admin_install_steps(src: Path | None = None) -> list[Step]:
    """(Re)install the password-prompt helper and polkit policy when missing or changed."""
    src = src or source_dir()
    if not src:
        return []
    steps = []
    helper_src, policy_src = src / "data/pc-admin", src / f"data/{APP_ID}.policy"
    if helper_src.exists() and (not HELPER.exists() or read(HELPER) != read(helper_src)):
        steps.append(Step("Install the admin helper", ["install", "-D", "-m", "755", str(helper_src), str(HELPER)], root=True))
    if policy_src.exists() and (not POLICY.exists() or read(POLICY) != read(policy_src)):
        steps.append(Step("Install the password-prompt policy", ["install", "-D", "-m", "644", str(policy_src), str(POLICY)], root=True))
    return steps


def search_provider_on() -> bool:
    return DBUS_SERVICE.exists() and SEARCH_INI.exists()


def search_steps() -> list[Step]:
    """Let GNOME's Activities search find pages and actions (type 'clean', 'battery', 'fix sound'…)."""
    staged = HOME / ".cache/pc/search-provider.ini"

    def write_files() -> str:
        DBUS_SERVICE.parent.mkdir(parents=True, exist_ok=True)
        DBUS_SERVICE.write_text(service_file(str(LAUNCHER) if LAUNCHER.exists() else "pc-gui"))
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(INI)
        return f"wrote {str(DBUS_SERVICE).replace(str(HOME), '~')}"
    return [py_step("Register the search helper", write_files, f"write {str(DBUS_SERVICE).replace(str(HOME), '~')}"),
            Step("Tell GNOME Shell about it", ["install", "-D", "-m", "644", str(staged), str(SEARCH_INI)], root=True)]


def uninstall_steps(keep_settings: bool = True, remove_cli: bool = True) -> list[Step]:
    unit_dir = HOME / ".config/systemd/user"
    timers = [u for u in USER_UNITS if u.endswith(".timer") and (unit_dir / u).exists()]
    steps: list[Step] = []
    if timers:
        steps.append(Step("Stop the weekly checkup and alerts", ["systemctl", "--user", "disable", "--now", *timers], optional=True))
    user_files = [p for p in [*(unit_dir / u for u in USER_UNITS), LAUNCHER, DESKTOP, ICON, ZSH_COMP, BASH_COMP, DBUS_SERVICE] if p.exists()]
    if user_files:
        steps.append(Step("Remove the app's files", ["rm", "-f", *map(str, user_files)]))
    if APP_DIR.exists():
        steps.append(Step("Remove the app", ["rm", "-rf", str(APP_DIR)]))
    if remove_cli:
        if has("uv") and "pc-control" in _uv_tools():
            steps.append(Step("Remove the terminal version (pc)", ["uv", "tool", "uninstall", "pc-control"], optional=True))
        elif VENV.exists():
            steps.append(Step("Remove the terminal version (pc)", ["rm", "-rf", str(VENV.parent), str(HOME / ".local/bin/pc")], optional=True))
    if not keep_settings:
        steps.append(Step("Remove settings and history", ["rm", "-rf", str(HOME / ".config/pc"), str(HOME / ".local/state/pc"),
                                                           str(HOME / ".cache/pc")], optional=True))
    root_files = [str(p) for p in (HELPER, POLICY, SEARCH_INI) if p.exists()]
    if root_files:
        steps.append(Step("Remove the admin helper and search provider", ["rm", "-f", *root_files], root=True, optional=True))
    steps.append(Step("Refresh the app grid", ["update-desktop-database", str(DESKTOP.parent)], optional=True))
    if timers:
        steps.append(Step("Reload schedules", ["systemctl", "--user", "daemon-reload"], optional=True))
    return steps


def _uv_tools() -> str:
    from .run import out
    return out(["uv", "tool", "list"], timeout=10)


def relaunch_cmd() -> list[str]:
    exe = str(LAUNCHER) if LAUNCHER.exists() else "pc-gui"
    return ["bash", "-c", f"sleep 1.2; exec {exe}"]
