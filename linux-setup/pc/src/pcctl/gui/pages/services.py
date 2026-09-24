"""Services: everything systemd runs (system + your user), with plain explanations, start/stop/boot, logs; plus timers."""

from __future__ import annotations

import re

from gi.repository import Gtk

from ...core import services
from ...core.run import Step, out
from ..util import button, clear, hbox, label, spacer, vbox
from ..widgets import Column, DataTable
from .base import Page

STATE = {"active": ("running", "ok"), "failed": ("failed", "bad"), "inactive": ("stopped", "neutral"), "activating": ("starting", "info"),
         "deactivating": ("stopping", "info"), "reloading": ("reloading", "info")}
BOOT = {"enabled": ("at boot", "accent"), "disabled": ("manual", "neutral"), "static": ("as needed", "neutral"), "masked": ("blocked", "bad"),
        "indirect": ("as needed", "neutral"), "generated": ("auto", "neutral"), "alias": ("alias", "neutral"), "enabled-runtime": ("this boot", "info")}
CRITICAL = {"dbus", "systemd-logind", "gdm", "gdm3", "NetworkManager", "polkit", "systemd-journald", "systemd-udevd", "accounts-daemon",
            "gnome-shell", "pipewire", "wireplumber", "user@1000", "snapd", "udisks2", "upower"}


class ServicesPage(Page):
    ID = "services"
    TITLE = "Services"
    ICON = "system-run-symbolic"
    SUBTITLE = "Background programs managed by systemd. Explanations in plain words; the important ones are protected."
    SCROLL = False

    def build(self) -> None:
        self.items: list[services.Service] = []
        self.header()
        self.search_entry = Gtk.SearchEntry(placeholder_text="Find a service…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.table.set_filter(e.get_text()))
        self.scope = Gtk.DropDown.new_from_strings(["System services", "Your services", "Scheduled timers"])
        self.scope.connect("notify::selected", lambda *_: self.load())
        self.state = Gtk.DropDown.new_from_strings(["All", "Running", "Failed", "Stopped", "Start at boot"])
        self.state.connect("notify::selected", lambda *_: self.render())
        self.body.append(hbox(self.search_entry, self.scope, self.state, spacing=8))
        self.banner = vbox()
        self.body.append(self.banner)

        self.stack = Gtk.Stack()
        self.table = DataTable([
            Column("st", "State", "pill", width=96, sort="active"),
            Column("name", "Service", "bold", width=250),
            Column("what", "What it does", "text", expand=True),
            Column("boot", "Starts", "pill", width=110, sort="enabled"),
            Column("sub", "Detail", "muted", width=90),
        ], on_activate=lambda r: self.details(), empty="No services match.", sort="active", descending=False,
            search=lambda d, q: q in d["name"].lower() or q in d["what"].lower())
        self.table.set_vexpand(True)
        self.timers = DataTable([
            Column("unit", "Timer", "bold", width=260),
            Column("next", "Next run", "text", width=200),
            Column("left", "In", "muted", width=100),
            Column("last", "Last run", "muted", width=200),
            Column("activates", "Runs", "mono", expand=True),
        ], empty="No timers.", sort="next", descending=False)
        self.timers.set_vexpand(True)
        self.stack.add_named(self.table, "services")
        self.stack.add_named(self.timers, "timers")
        self.stack.set_vexpand(True)
        self.body.append(self.stack)
        self.actions = hbox(
            button("Start", icon="media-playback-start-symbolic", on_click=lambda: self.act("start")),
            button("Stop", icon="media-playback-stop-symbolic", on_click=lambda: self.act("stop")),
            button("Restart", icon="view-refresh-symbolic", on_click=lambda: self.act("restart")),
            button("On at boot", tooltip="Start automatically at every boot", on_click=lambda: self.act("enable")),
            button("Off at boot", tooltip="Don't start it at boot (you can still start it by hand)", on_click=lambda: self.act("disable")),
            spacer(),
            button(icon="text-x-generic-symbolic", tooltip="Logs", on_click=self.show_logs),
            button(icon="dialog-information-symbolic", tooltip="Details", on_click=self.details), spacing=6)
        self.body.append(self.actions)

    def load(self) -> None:
        sc = self.scope.get_selected()
        self.stack.set_visible_child_name("timers" if sc == 2 else "services")
        self.actions.set_visible(sc != 2)
        self.state.set_visible(sc != 2)
        if sc == 2:
            self.bg(self._timers, self.show_timers)
            return
        self.table.set_empty("Loading services…")
        self.bg(lambda: services.services(user=sc == 1), self.show)

    def show(self, items: list[services.Service]) -> None:
        self.items = items
        clear(self.banner)
        failed = [s for s in items if s.active == "failed"]
        if failed:
            b = hbox(label(f"{len(failed)} service{'s' if len(failed) != 1 else ''} failed: " + ", ".join(s.name for s in failed[:6]),
                           None, wrap=True, hexpand=True), css="banner-bad")
            show = button("Show", css="flat", on_click=lambda: self.state.set_selected(2))
            reset = button("Clear failed state", css="flat", on_click=lambda: self.run(
                "Clear failed services", [Step("Reset failed services", ["systemctl", *(["--user"] if self.scope.get_selected() == 1 else []), "reset-failed"],
                                               root=self.scope.get_selected() == 0)],
                "Forgets that they failed (they aren't restarted). Useful after you've fixed or removed the cause."))
            for w in (show, reset):
                w.set_valign(Gtk.Align.CENTER)
                b.append(w)
            self.banner.append(b)
        self.banner.set_visible(bool(failed))
        self.render()
        if self.scope.get_selected() == 0:
            self.win.set_badge("services", len(failed), bad=True)

    def render(self) -> None:
        f = self.state.get_selected()
        rows = []
        for s in self.items:
            if f == 1 and s.active != "active" or f == 2 and s.active != "failed" or f == 3 and s.active not in ("inactive", "failed") \
                    or f == 4 and s.enabled != "enabled":
                continue
            what = services.explain(s.unit) or s.description
            rows.append({"key": s.unit, "st": STATE.get(s.active, (s.active, "neutral")), "active": s.active, "name": s.name, "what": what,
                         "boot": BOOT.get(s.enabled, (s.enabled or "-", "neutral")), "enabled": s.enabled, "sub": s.sub, "_s": s})
        self.table.set_rows(rows)
        self.table.set_empty("No services match.")

    def _sel(self) -> services.Service | None:
        r = self.table.selected()
        if not r:
            self.toast("Select a service first.")
            return None
        return r["_s"]

    def act(self, action: str) -> None:
        s = self._sel()
        if not s:
            return
        base = s.name.split("@")[0]
        if action in ("stop", "disable") and base in CRITICAL:
            self.toast(f"{s.name} is needed by Ubuntu itself; stopping it could break your desktop.", 5)
            return
        explain = services.explain(s.unit) or s.description
        warn = {"stop": "It stops now but may start again at boot.", "disable": "It keeps running now but won't start after the next restart.",
                "enable": "It will start at every boot.", "restart": "Stops and starts it again.", "start": ""}.get(action, "")
        self.run(f"{action.capitalize()} {s.name}", services.action_steps(s, action), f"{explain}. {warn}".strip(". ") + ".",
                 danger=action in ("stop", "disable"), ok_label=action.capitalize())

    def show_logs(self) -> None:
        s = self._sel()
        if s:
            self.bg(lambda: services.logs(s, 400), lambda t: self.text(f"Log: {s.name}", t or "No log messages."))

    def details(self) -> None:
        s = self._sel()
        if not s:
            return

        def work() -> str:
            scope = ["--user"] if s.user else []
            parts = [services.status_text(s), "", "── Unit file ──", out(["systemctl", *scope, "cat", s.unit], timeout=10)]
            deps = out(["systemctl", *scope, "list-dependencies", "--reverse", "--plain", "--no-pager", s.unit], timeout=10)
            if deps:
                parts += ["", "── Needed by ──", deps]
            return "\n".join(parts)
        self.bg(work, lambda t: self.text(s.name, t))

    # ---------------------------------------------------------------- timers
    def _timers(self) -> list[dict]:
        rows = []
        for scope in ([], ["--user"]):
            text = out(["systemctl", *scope, "list-timers", "--all", "--no-pager", "--no-legend"], timeout=10)
            for line in text.splitlines():
                m = re.match(r"^(.{0,30}?\S.*?)\s{2,}(\S.*?)\s{2,}(.*?)\s{2,}(\S.*?)\s{2,}(\S+\.timer)\s+(\S+)\s*$", line)
                if m:
                    nxt, left, last, _passed, unit, act = m.groups()
                    rows.append({"key": f"{scope}{unit}", "unit": unit.removesuffix(".timer") + (" (you)" if scope else ""), "next": nxt.strip(),
                                 "left": left.strip(), "last": last.strip(), "activates": act})
                else:
                    cols = line.split()
                    if cols and cols[-2:-1] and cols[-2].endswith(".timer"):
                        rows.append({"key": f"{scope}{cols[-2]}", "unit": cols[-2].removesuffix(".timer"), "next": "-", "left": "", "last": "", "activates": cols[-1]})
        return rows

    def show_timers(self, rows: list[dict]) -> None:
        self.timers.set_rows(rows)


PAGE = ServicesPage
