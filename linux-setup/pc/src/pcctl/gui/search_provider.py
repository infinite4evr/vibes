"""GNOME Activities search provider: type "clean", "ports" or "battery" in the overview to jump to that page or action.

GNOME Shell starts this on demand over D-Bus (`pc-gui --search-provider`, see the .service and .ini files the installer
writes) and it quits by itself after a minute of no searches. It only lists things; picking a result opens the app.
"""

from __future__ import annotations

import os
import subprocess
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from ..core.selfupdate import BUS_NAME, OBJECT_PATH  # noqa: E402
IDLE_QUIT_S = 60

IFACE = """
<node>
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet"><arg type="as" name="terms" direction="in"/><arg type="as" name="results" direction="out"/></method>
    <method name="GetSubsearchResultSet"><arg type="as" name="previous_results" direction="in"/><arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/></method>
    <method name="GetResultMetas"><arg type="as" name="identifiers" direction="in"/><arg type="aa{sv}" name="metas" direction="out"/></method>
    <method name="ActivateResult"><arg type="s" name="identifier" direction="in"/><arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/></method>
    <method name="LaunchSearch"><arg type="as" name="terms" direction="in"/><arg type="u" name="timestamp" direction="in"/></method>
  </interface>
</node>
"""

# extra words people type that don't appear in titles
SYNONYMS = {
    "cleanup": "junk cache free space delete trash clean",
    "updates": "upgrade apt snap flatpak security patch driver kernel",
    "processes": "task manager kill cpu ram memory hog frozen",
    "storage": "disk space big files duplicates usb drive",
    "network": "wifi internet dns ports speed vpn hotspot",
    "power": "battery sleep awake shutdown timer temperature cpu hardware",
    "logs": "errors crash journal dmesg kernel",
    "services": "systemd daemon cron timer script",
    "security": "firewall ssh secrets virus password",
    "privacy": "telemetry history tracking indexing",
    "tweaks": "settings gnome dock extensions shortcut",
    "dev": "developer git github docker node python path",
    "maintenance": "fix troubleshoot report backup snapshot timeshift",
    "startup": "boot login grub autostart",
    "apps": "install uninstall appimage flatpak snap",
}


class Index:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def build(self) -> None:
        if self.items:
            return
        from .window import SECTIONS, all_actions, page_classes, setting_rows
        classes = page_classes()
        order = [pid for _, ids in SECTIONS for pid in ids if pid in classes]
        for pid in order:
            cls = classes[pid]
            self.items[f"page:{pid}"] = {"name": cls.TITLE, "description": getattr(cls, "SUBTITLE", ""), "icon": getattr(cls, "ICON", ""),
                                         "words": f"{cls.TITLE} {getattr(cls, 'SUBTITLE', '')} {SYNONYMS.get(pid, '')}".lower()}
        for key, title, sub in all_actions(classes):
            if key.startswith("app:") and key not in ("app:preferences", "app:activity"):
                continue
            pid = key.split(":")[0]
            icon = getattr(classes.get(pid), "ICON", "") if pid in classes else "preferences-system-symbolic"
            self.items[f"do:{key}"] = {"name": title, "description": sub, "icon": icon, "words": f"{title} {sub}".lower()}
        for key, title, sub in setting_rows():
            pid = key.split(":")[1]
            self.items[key] = {"name": title, "description": sub, "icon": getattr(classes.get(pid), "ICON", ""), "words": f"{title} {sub}".lower()}

    def search(self, terms: list[str], within: list[str] | None = None) -> list[str]:
        self.build()
        terms = [t.lower() for t in terms if t.strip()]
        if not terms or len("".join(terms)) < 2:
            return []
        pool = within if within is not None else list(self.items)
        hits = []
        for rid in pool:
            it = self.items.get(rid)
            if it and all(t in it["words"] for t in terms):
                name = it["name"].lower()
                rank = 0 if name.startswith(terms[0]) else 1 if terms[0] in name else 2
                rank += 0 if rid.startswith("page:") else 1
                hits.append((rank, rid))
        return [rid for _, rid in sorted(hits)[:10]]

    def metas(self, ids: list[str]) -> list[dict]:
        self.build()
        res = []
        for rid in ids:
            it = self.items.get(rid)
            if not it:
                continue
            meta = {"id": GLib.Variant("s", rid), "name": GLib.Variant("s", it["name"]), "description": GLib.Variant("s", it["description"])}
            if it["icon"]:
                meta["gicon"] = GLib.Variant("s", Gio.ThemedIcon.new(it["icon"]).to_string())
            res.append(meta)
        return res


def app_command() -> list[str]:
    """How to open the app: the same Python and code this provider runs from."""
    exe = os.path.expanduser("~/.local/bin/pc-gui")
    return [exe] if os.path.exists(exe) else [sys.executable, "-m", "pcctl.gui"]


def launch_for(rid: str) -> list[str]:
    if rid.startswith("page:"):
        return [*app_command(), "--page", rid.split(":", 1)[1]]
    if rid.startswith("do:"):
        return [*app_command(), "--action", rid.split(":", 1)[1]]
    if rid.startswith("setting:"):
        return [*app_command(), "--action", rid]
    return app_command()


class Provider:
    def __init__(self, loop: GLib.MainLoop):
        self.loop = loop
        self.index = Index()
        self.timer = 0
        self._touch()

    def _touch(self) -> None:
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(IDLE_QUIT_S, self._quit)

    def _quit(self) -> bool:
        self.loop.quit()
        return False

    def call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        self._touch()
        try:
            args = params.unpack()
            if method == "GetInitialResultSet":
                invocation.return_value(GLib.Variant("(as)", (self.index.search(args[0]),)))
            elif method == "GetSubsearchResultSet":
                invocation.return_value(GLib.Variant("(as)", (self.index.search(args[1], list(args[0])),)))
            elif method == "GetResultMetas":
                invocation.return_value(GLib.Variant("(aa{sv})", (self.index.metas(args[0]),)))
            elif method == "ActivateResult":
                subprocess.Popen(launch_for(args[0]), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                invocation.return_value(None)
            elif method == "LaunchSearch":
                subprocess.Popen([*app_command(), "--action", "app:palette"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception as e:  # noqa: BLE001
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", str(e))


def main() -> int:
    loop = GLib.MainLoop()
    provider = Provider(loop)
    info = Gio.DBusNodeInfo.new_for_xml(IFACE)

    def on_bus(conn, _name) -> None:
        conn.register_object(OBJECT_PATH, info.interfaces[0], provider.call, None, None)

    owner = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_bus, None, lambda *_a: loop.quit())
    try:
        loop.run()
    finally:
        Gio.bus_unown_name(owner)
    return 0
