"""Desktop integration on Linux: applications-menu entry and icons, autostart, and a
“Send to TG Drive” item in file managers' right-click menus (GNOME Files, Nemo,
Caja, Dolphin, Thunar). Everything goes into your home folder; nothing needs root.
"""
from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from . import config

APP_ID = "tgdrive"
MARK = "Added by TG Drive"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def launcher_argv() -> list[str]:
    """The command that starts this TG Drive (AppImage, installed launcher, or this source folder)."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [appimage]
    exe = os.environ.get("TGDRIVE_LAUNCHER")
    if exe:
        return shlex.split(exe) if " " in exe and not Path(exe).exists() else [exe]
    installed = Path.home() / ".local/bin/tgdrive"
    if installed.exists():
        return [str(installed)]
    return ["env", f"PYTHONPATH={config.ROOT}", sys.executable, "-m", "desktop"]


def launcher_command() -> str:
    return " ".join(shlex.quote(a) if a != "%F" else a for a in launcher_argv())


def _exec(extra: str = "") -> str:
    # Desktop-entry Exec lines quote with double quotes only.
    parts = []
    for a in launcher_argv():
        parts.append(f'"{a}"' if (" " in a or '"' in a) else a)
    return " ".join(parts) + (f" {extra}" if extra else "")


def icon_source() -> Path:
    for p in (config.ROOT / "packaging" / "icons" / "tgdrive-256.png", config.ROOT / "web" / "icon.svg"):
        if p.exists():
            return p
    return config.ROOT / "web" / "icon.svg"


def desktop_entry_text(extra_args: str = "") -> str:
    return f"""[Desktop Entry]
Type=Application
Name=TG Drive
GenericName=Telegram file manager
Comment=Browse, search, stream and organise every file in your Telegram
Exec={_exec((extra_args + " %U").strip())}
Icon={APP_ID}
Terminal=false
Categories=Network;FileTransfer;FileManager;Utility;
Keywords=telegram;files;drive;search;cloud;
StartupWMClass={APP_ID}
StartupNotify=true
Actions=search;upload;

[Desktop Action search]
Name=Search TG Drive
Exec={_exec('--open search')}

[Desktop Action upload]
Name=Upload files…
Exec={_exec('--open upload')}
"""


def _refresh_caches() -> None:
    apps = _data_home() / "applications"
    icons = _data_home() / "icons/hicolor"
    for cmd in (["update-desktop-database", str(apps)], ["gtk-update-icon-cache", "-f", "-t", str(icons)],
                ["kbuildsycoca6"], ["kbuildsycoca5"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass


def install_menu() -> Path:
    apps = _data_home() / "applications"
    icons = _data_home() / "icons/hicolor"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / f"{APP_ID}.desktop"
    entry.write_text(desktop_entry_text())
    icon_dir = config.ROOT / "packaging" / "icons"
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        src = icon_dir / f"tgdrive-{size}.png"
        if src.exists():
            d = icons / f"{size}x{size}/apps"
            d.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, d / f"{APP_ID}.png")
    svg = config.ROOT / "web" / "icon.svg"
    if svg.exists():
        d = icons / "scalable/apps"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(svg, d / f"{APP_ID}.svg")
    _refresh_caches()
    return entry


def uninstall_menu() -> None:
    base = _data_home()
    (base / "applications" / f"{APP_ID}.desktop").unlink(missing_ok=True)
    for p in (base / "icons/hicolor").glob(f"*/apps/{APP_ID}.*"):
        p.unlink(missing_ok=True)
    (_config_home() / "autostart" / f"{APP_ID}.desktop").unlink(missing_ok=True)
    _refresh_caches()


def menu_installed() -> bool:
    f = _data_home() / "applications" / f"{APP_ID}.desktop"
    return f.exists()


def set_autostart(on: bool) -> None:
    d = _config_home() / "autostart"
    f = d / f"{APP_ID}.desktop"
    if on:
        d.mkdir(parents=True, exist_ok=True)
        text = desktop_entry_text("--minimized ").replace("%U", "")
        text = text.split("\n\n[Desktop Action")[0].rstrip() + "\nX-GNOME-Autostart-enabled=true\n"
        f.write_text(text)
    else:
        f.unlink(missing_ok=True)


# ------------------------------------------------------ file manager menus
def _script() -> str:
    return f"""#!/bin/sh
# {MARK}: uploads the selected files and folders.
exec {launcher_command()} --send "$@"
"""


def _targets() -> dict[str, dict]:
    dh, ch = _data_home(), _config_home()
    return {
        "nautilus": {"label": "GNOME Files", "exe": "nautilus",
                     "file": dh / "nautilus/scripts/Send to TG Drive", "kind": "script"},
        "caja": {"label": "Caja", "exe": "caja", "file": ch / "caja/scripts/Send to TG Drive", "kind": "script"},
        "nemo": {"label": "Nemo", "exe": "nemo", "file": dh / "nemo/actions/tgdrive-send.nemo_action", "kind": "nemo"},
        "dolphin": {"label": "Dolphin", "exe": "dolphin", "file": dh / "kio/servicemenus/tgdrive-send.desktop",
                    "file5": dh / "kservices5/ServiceMenus/tgdrive-send.desktop", "kind": "kde"},
        "thunar": {"label": "Thunar", "exe": "thunar", "file": ch / "Thunar/uca.xml", "kind": "thunar"},
    }


def file_manager_status() -> list[dict]:
    out = []
    for key, t in _targets().items():
        present = bool(shutil.which(t["exe"]))
        f: Path = t["file"]
        if t["kind"] == "thunar":
            installed = f.exists() and "tgdrive-send" in f.read_text(errors="ignore")
        else:
            installed = f.exists()
        out.append({"id": key, "label": t["label"], "present": present, "installed": installed})
    return out


def install_file_manager_actions(only_present: bool = True) -> list[str]:
    done = []
    for key, t in _targets().items():
        if only_present and not shutil.which(t["exe"]):
            continue
        f: Path = t["file"]
        f.parent.mkdir(parents=True, exist_ok=True)
        kind = t["kind"]
        if kind == "script":
            f.write_text(_script())
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        elif kind == "nemo":
            f.write_text(f"""[Nemo Action]
# {MARK}
Active=true
Name=Send to TG Drive
Comment=Upload the selection to TG Drive
Exec={_exec('--send %F')}
Icon-Name={APP_ID}
Selection=notnone
Extensions=any;
Quote=double
""")
        elif kind == "kde":
            text = f"""[Desktop Entry]
# {MARK}
Type=Service
MimeType=all/all;inode/directory;
Actions=sendToTGDrive;
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel

[Desktop Action sendToTGDrive]
Name=Send to TG Drive
Icon={APP_ID}
Exec={_exec('--send %F')}
"""
            for target in (f, t["file5"]):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
                target.chmod(target.stat().st_mode | stat.S_IXUSR)
        elif kind == "thunar":
            action = f"""<action>
	<icon>{APP_ID}</icon>
	<name>Send to TG Drive</name>
	<submenu></submenu>
	<unique-id>tgdrive-send</unique-id>
	<command>{_exec('--send %F').replace('&', '&amp;').replace('<', '&lt;')}</command>
	<description>{MARK}</description>
	<range></range>
	<patterns>*</patterns>
	<directories/>
	<audio-files/>
	<image-files/>
	<other-files/>
	<text-files/>
	<video-files/>
</action>
"""
            if f.exists():
                xml = f.read_text(errors="ignore")
                if "tgdrive-send" not in xml and "</actions>" in xml:
                    f.with_suffix(".xml.tgdrive-backup").write_text(xml)
                    f.write_text(xml.replace("</actions>", action + "</actions>", 1))
            else:
                f.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<actions>\n{action}</actions>\n')
        done.append(t["label"])
    _refresh_caches()
    return done


def uninstall_file_manager_actions() -> None:
    for t in _targets().values():
        f: Path = t["file"]
        if t["kind"] == "thunar":
            if f.exists():
                xml = f.read_text(errors="ignore")
                start = xml.find("<unique-id>tgdrive-send</unique-id>")
                if start >= 0:
                    a = xml.rfind("<action>", 0, start)
                    b = xml.find("</action>", start)
                    if a >= 0 and b >= 0:
                        f.write_text(xml[:a] + xml[b + len("</action>"):].lstrip("\n"))
            continue
        for target in (f, t.get("file5")):
            if target and target.exists() and MARK in target.read_text(errors="ignore"):
                target.unlink()


def status() -> dict:
    return {"menu": menu_installed(), "launcher": launcher_command(), "file_managers": file_manager_status(),
            "autostart": (_config_home() / "autostart" / f"{APP_ID}.desktop").exists()}
