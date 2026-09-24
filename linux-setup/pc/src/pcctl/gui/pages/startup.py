"""Startup: login apps (on/off switches), boot time breakdown, and optional services that start at boot."""

from __future__ import annotations

from gi.repository import Gtk

from ...core import services, system
from ...core.run import Step, out
from ..dialogs import ChoiceDialog
from ..util import button, clear, hbox, label, vbox
from ..widgets import HBars, card
from .base import Page, action_row, banner, group, stat, switch_row

# Services that are often not needed and start at every boot. (unit, title, what it does / when you can turn it off)
OPTIONAL = [
    ("docker.service", "Docker", "Starts the Docker engine at boot. Turn off if you only use it sometimes; it starts when you run docker (socket)."),
    ("containerd.service", "containerd", "Container runtime used by Docker."),
    ("postgresql.service", "PostgreSQL", "Database server. Uses RAM all the time; start it only when you work on a project that needs it."),
    ("mysql.service", "MySQL", "Database server."),
    ("mariadb.service", "MariaDB", "Database server."),
    ("mongod.service", "MongoDB", "Database server."),
    ("redis-server.service", "Redis", "In-memory database."),
    ("nginx.service", "nginx", "Web server."),
    ("apache2.service", "Apache", "Web server."),
    ("cups.service", "Printing", "Printer support. Off is fine if you never print."),
    ("cups-browsed.service", "Printer discovery", "Finds network printers automatically."),
    ("bluetooth.service", "Bluetooth", "Needed for Bluetooth headphones, mice and keyboards."),
    ("ModemManager.service", "Mobile broadband", "Only needed for 4G/5G modems or SIM cards."),
    ("avahi-daemon.service", "Network discovery", "Finds printers, Chromecasts and shared folders on your network."),
    ("kerneloops.service", "Kernel crash reporter", "Sends kernel error reports to Ubuntu."),
    ("whoopsie.service", "Crash reporter", "Sends crash reports to Ubuntu."),
    ("apport.service", "Crash catcher", "Saves crash reports when apps crash."),
    ("virtualbox.service", "VirtualBox drivers", "Loads VirtualBox kernel modules at boot."),
    ("vboxweb.service", "VirtualBox web service", "Remote control for VirtualBox. Rarely needed."),
    ("teamviewerd.service", "TeamViewer", "Remote access daemon."),
    ("anydesk.service", "AnyDesk", "Remote access daemon."),
    ("snap.lxd.daemon.service", "LXD", "Container manager (snap)."),
]


def optional_states() -> list[tuple[str, str, str, str, bool]]:
    units = [u for u, _, _ in OPTIONAL]
    text = out(["systemctl", "list-unit-files", "--no-legend", "--no-pager", *units], timeout=15)
    states = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) >= 2:
            states[cols[0]] = cols[1]
    res = []
    for unit, title, desc in OPTIONAL:
        st = states.get(unit)
        if st is None or st in ("static", "generated", "transient", "alias", "indirect"):
            continue
        active = out(["systemctl", "is-active", unit]) == "active"
        res.append((unit, title, desc, st, active))
    return res


class StartupPage(Page):
    ID = "startup"
    TITLE = "Startup"
    ICON = "system-reboot-symbolic"
    SUBTITLE = "What opens when you log in, what starts at boot, and what makes starting slow."

    def build(self) -> None:
        self.header()
        self.boot_total = label("…", "huge-num")
        self.boot_sub = label("Measuring the last boot…", "subtle", wrap=True)
        self.parts = {k: stat("…", k) for k in ("firmware", "loader", "kernel", "userspace")}
        left = vbox(label("LAST BOOT", "tile-title"), self.boot_total, self.boot_sub, spacing=2)
        left.set_hexpand(True)
        parts = hbox(*self.parts.values(), spacing=26)
        parts.set_valign(Gtk.Align.CENTER)
        self.blame = HBars("peach", row=24, label_width=300)
        self.blame_title = label("SLOWEST TO START", "tile-title")
        hero = card(hbox(left, parts, spacing=18), self.blame_title, self.blame, spacing=12)
        hero.add_css_class("hero")
        self.body.append(hero)
        self.tip_box = vbox()
        self.body.append(self.tip_box)

        self.apps_group = group("Apps that open when you log in", "Switch them off to log in faster. No password needed.",
                                suffix=button("Add app…", icon="list-add-symbolic", css="flat", on_click=self.add))
        self.body.append(self.apps_group)
        self.svc_holder = vbox()
        self.body.append(self.svc_holder)
        self.body.append(label("Core parts of Ubuntu that must start are hidden here. Everything else is in Services.", "dim", wrap=True))

    def load(self) -> None:
        self.render_apps()
        self.bg(system.boot, self.show_boot)
        self.bg(optional_states, self.show_services)

    # ---------------------------------------------------------------- boot
    def show_boot(self, b: dict) -> None:
        clear(self.tip_box)
        if not b.get("total"):
            self.boot_total.set_text("?")
            self.boot_sub.set_text("Boot timing isn't available on this system.")
            for w in self.parts.values():
                w._value.set_text("-")
            self.blame.set_visible(False)
            self.blame_title.set_visible(False)
            return
        total = b["total"]
        self.boot_total.set_text(f"{total:.1f} s")
        self.boot_total.set_css_classes(["huge-num", "ok-text" if total < 20 else ("warn-text" if total < 45 else "bad-text")])
        self.boot_sub.set_text("from power button to login screen" + (": nice and quick." if total < 20 else "."))
        for k, w in self.parts.items():
            w._value.set_text(f"{b[k]:.1f}s" if k in b else "-")
        blame = b.get("blame", [])[:10]
        self.blame.set_items([(u.replace(".service", ""), s, f"{s:.1f}s") for s, u in blame])
        units = {u for _, u in blame}
        if "NetworkManager-wait-online.service" in units:
            self.tip_box.append(banner("“NetworkManager-wait-online” makes boot wait for the network. On a laptop it's safe to turn off.", "warn",
                                       button("Turn off", on_click=lambda: self.run(
                                           "Don't wait for the network at boot",
                                           [Step("Disable wait-online", ["systemctl", "disable", "NetworkManager-wait-online.service"], root=True)],
                                           "Boot won't wait for Wi-Fi. Network still connects as usual right after."))))
        if b.get("firmware", 0) > 15:
            self.tip_box.append(banner(f"Your BIOS/UEFI takes {b['firmware']:.0f}s before Ubuntu even starts. Turning on “Fast Boot” in the "
                                       "BIOS settings usually helps.", "info"))

    # ---------------------------------------------------------------- login apps
    def render_apps(self) -> None:
        g = group("Apps that open when you log in", "Switch them off to log in faster. No password needed.",
                  suffix=button("Add app…", icon="list-add-symbolic", css="flat", on_click=self.add))
        parent = self.apps_group.get_parent()
        if parent is not None:
            parent.insert_child_after(g, self.apps_group)
            parent.remove(self.apps_group)
        self.apps_group = g
        apps = services.startup_apps()
        if not apps:
            g.add(action_row("Nothing starts at login", "Add an app with the button above."))
        for a in apps:
            sub = (a.comment or a.exec)[:120] + ("   ·   comes with Ubuntu" if a.system else "   ·   added by you or an app")

            def change(on: bool, settle, app=a) -> None:
                try:
                    services.set_startup_enabled(app, on)
                    self.toast(f"{app.name} will {'open' if on else 'no longer open'} at login.")
                    settle(True)
                except OSError as e:
                    self.toast(f"Couldn't change it: {e}")
                    settle(False)
            row = switch_row(a.name, sub, a.enabled, change)
            if not a.system:
                rm = button(icon="user-trash-symbolic", css="flat", tooltip="Remove from startup",
                            on_click=lambda app=a: (services.remove_startup(app), self.toast(f"Removed {app.name}"), self.render_apps()))
                rm.set_valign(Gtk.Align.CENTER)
                row.add_suffix(rm)
            g.add(row)
        on = sum(a.enabled for a in apps)
        self.win.set_badge("startup", 0)
        g.set_description(f"{on} of {len(apps)} switched on. Switch them off to log in faster. No password needed.")

    def add(self) -> None:
        def got(apps):
            def done(f):
                if f:
                    self.toast(services.add_startup(f).capitalize())
                    self.render_apps()
            ChoiceDialog("Open an app when you log in", [(f, name, f) for name, f in apps], done).present(self.win)
        self.bg(services.launchable_apps, got)

    # ---------------------------------------------------------------- boot services
    def show_services(self, items) -> None:
        clear(self.svc_holder)
        g = group("Optional services that start at boot", "Things installed on this PC that run all the time. Switching one off stops it now "
                  "and at every boot; you can still start it by hand. Needs your password.")
        if not items:
            g.add(action_row("None found", "No optional background services are installed."))
        for unit, title, desc, state, active in items:
            enabled = state == "enabled"

            def change(on: bool, settle, u=unit, t=title) -> None:
                if on:
                    steps = [Step(f"Start {t} now and at boot", ["systemctl", "enable", "--now", u], root=True)]
                    if state == "masked":
                        steps.insert(0, Step(f"Unmask {t}", ["systemctl", "unmask", u], root=True))
                else:
                    steps = [Step(f"Stop {t} and don't start it at boot", ["systemctl", "disable", "--now", u], root=True)]
                self.run(("Turn on " if on else "Turn off ") + t, steps, reload=False, done=settle)
            sub = desc + f"\n{unit} · {'running' if active else 'not running'} · {state}"
            g.add(switch_row(title, sub, enabled, change))
        self.svc_holder.append(g)


PAGE = StartupPage
