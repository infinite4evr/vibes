"""Startup: login apps (on/off, open later), optional services at boot, your own services at login, what makes booting slow
(critical chain, boot chart, recent boots) and the boot menu (GRUB) settings."""

from __future__ import annotations

import time

from gi.repository import Adw, Gtk

from ...core import boot, services
from ...core.run import Step, out, read
from ..dialogs import ChoiceDialog
from ..util import button, clear, esc, flow, hbox, label, open_path, pill, spacer, vbox
from ..widgets import HBars, card
from .base import Page, action_row, banner, group, stat, switch_row, tabs

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

PARTS = [("firmware", "PC firmware (BIOS/UEFI)"), ("loader", "Boot menu (GRUB)"), ("kernel", "Linux kernel"),
         ("initrd", "Early startup (initrd)"), ("userspace", "Ubuntu's services")]


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


def secs(v: float) -> str:
    if v >= 60:
        return f"{int(v // 60)} min {v % 60:.0f} s"
    return f"{v:.1f} s" if v >= 0.1 else f"{v * 1000:.0f} ms"


class StartupPage(Page):
    ID = "startup"
    TITLE = "Startup"
    ICON = "system-reboot-symbolic"
    SUBTITLE = "What opens when you log in, what starts at boot, what makes starting slow, and the boot menu."
    PALETTE = [("grub", "Boot menu (GRUB) settings: countdown, default system, quiet start"),
               ("chart", "Draw a boot chart picture"),
               ("chain", "What makes starting slow (critical chain)"),
               ("usersvc", "Your services that start at login"),
               ("delay", "Open a login app a bit later (delay)")]

    def build(self) -> None:
        self.header()
        self.analysis: dict = {}
        self.boot_total = label("…", "huge-num")
        self.boot_sub = label("Measuring the last boot…", "subtle", wrap=True)
        self.parts = {k: stat("…", k) for k in ("firmware", "loader", "kernel", "initrd", "userspace")}
        left = vbox(label("LAST BOOT", "tile-title"), self.boot_total, self.boot_sub, spacing=2)
        left.set_hexpand(True)
        parts = flow(*self.parts.values(), spacing=22, min_per_line=3)
        parts.set_valign(Gtk.Align.CENTER)
        self.blame = HBars("peach", row=24, label_width=300)
        self.blame_title = label("SLOWEST TO START", "tile-title")
        hero = card(flow(left, parts, spacing=18, min_per_line=1, max_per_line=2), self.blame_title, self.blame, spacing=12)
        hero.add_css_class("hero")
        self.body.append(hero)
        self.tip_box = vbox()
        self.body.append(self.tip_box)

        self.login_box = vbox(spacing=12)
        self.svc_holder = vbox(spacing=12)
        self.user_box = vbox(spacing=12)
        self.services_box = vbox(self.user_box, self.svc_holder, spacing=26)
        self.speed_box = vbox(spacing=18)
        self.menu_box = vbox(spacing=18)
        sw, self.stack = tabs(("login", "Login apps", "view-app-grid-symbolic", self.login_box),
                              ("services", "Services", "system-run-symbolic", self.services_box),
                              ("speed", "Boot speed", "preferences-system-time-symbolic", self.speed_box),
                              ("menu", "Boot menu", "view-list-symbolic", self.menu_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()

        self.apps_group = group("Apps that open when you log in", "Switch them off to log in faster. No password needed.")
        self.login_box.append(self.apps_group)
        self.login_box.append(label("Tip: the clock button opens an app a little after you log in, so your desktop is ready sooner.",
                                    "dim", wrap=True))

    def load(self) -> None:
        self.render_apps()
        self.bg(boot.analyze, self.show_boot)
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "services":
            self.load_user()
            self.loading(self.svc_holder)
            self.bg(optional_states, self.show_services)
        elif name == "speed":
            self.load_speed()
        elif name == "menu":
            self.load_menu()

    # ---------------------------------------------------------------- hero
    def show_boot(self, b: dict) -> None:
        self.analysis = b
        clear(self.tip_box)
        if not b.get("total"):
            self.boot_total.set_text("?")
            self.boot_sub.set_text("Boot timing isn't available on this system.")
            for w in self.parts.values():
                w._value.set_text("-")
            self.blame.set_visible(False)
            self.blame_title.set_visible(False)
        else:
            total = b["total"]
            self.boot_total.set_text(f"{total:.1f} s")
            self.boot_total.set_css_classes(["huge-num", "ok-text" if total < 20 else ("warn-text" if total < 45 else "bad-text")])
            self.boot_sub.set_text("from power button to login screen" + (": nice and quick." if total < 20 else "."))
            for k, w in self.parts.items():
                w._value.set_text(f"{b[k]:.1f}s" if k in b else "-")
                w.set_visible(k in b or k != "initrd")
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
        if "speed" in self.tab_loaded:
            self.show_speed((b, getattr(self, "_history", [])))

    # ---------------------------------------------------------------- login apps (+ F2 delay)
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
            delay = boot.autostart_delay(read(a.user_file or a.source_file))
            sub = (a.comment or a.exec)[:120] + ("   ·   comes with Ubuntu" if a.system else "   ·   added by you or an app")
            if delay:
                sub += f"   ·   opens {delay} s after login"

            def change(on: bool, settle, app=a) -> None:
                try:
                    services.set_startup_enabled(app, on)
                    self.toast(f"{app.name} will {'open' if on else 'no longer open'} at login.")
                    settle(True)
                except OSError as e:
                    self.toast(f"Couldn't change it: {e}")
                    settle(False)
            row = switch_row(a.name, sub, a.enabled, change)
            later = button(icon="preferences-system-time-symbolic", css="flat" if not delay else ["flat", "accent-text"],
                           tooltip=f"Open it later (now: {delay} s after login)" if delay else "Open it a little after you log in",
                           on_click=lambda app=a, d=delay: self.ask_delay(app, d))
            later.set_valign(Gtk.Align.CENTER)
            row.add_suffix(later)
            if not a.system:
                rm = button(icon="user-trash-symbolic", css="flat", tooltip="Remove from startup",
                            on_click=lambda app=a: (services.remove_startup(app), self.toast(f"Removed {app.name}"), self.render_apps()))
                rm.set_valign(Gtk.Align.CENTER)
                row.add_suffix(rm)
            g.add(row)
        on = sum(a.enabled for a in apps)
        self.win.set_badge("startup", 0)
        g.set_description(esc(f"{on} of {len(apps)} switched on. Switch them off to log in faster. No password needed."))

    def ask_delay(self, app, current: int) -> None:
        d = Adw.AlertDialog(heading=f"Open {app.name} later",
                            body="Wait this many seconds after you log in before opening it. Good for things that aren't urgent "
                                 "(chat, cloud sync, updaters), so your desktop is ready sooner. 0 opens it right away.")
        spin = Gtk.SpinButton.new_with_range(0, 60, 5)
        spin.set_value(current or 15)
        row = hbox(spin, label("seconds after login", "dim"), spacing=10)
        row.set_halign(Gtk.Align.CENTER)
        d.set_extra_child(row)
        d.add_response("cancel", "Cancel")
        d.add_response("save", "Save")
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")

        def resp(_d, r) -> None:
            if r != "save":
                return
            try:
                msg = boot.set_autostart_delay(app.id, app.user_file or app.source_file, int(spin.get_value()))
                self.toast(f"{app.name}: {msg}.")
            except OSError as e:
                self.toast(f"Couldn't change it: {e}")
            self.render_apps()
        d.connect("response", resp)
        d.present(self.win)

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

            def change(on: bool, settle, u=unit, t=title, st=state) -> None:
                if on:
                    steps = [Step(f"Start {t} now and at boot", ["systemctl", "enable", "--now", u], root=True)]
                    if st == "masked":
                        steps.insert(0, Step(f"Unmask {t}", ["systemctl", "unmask", u], root=True))
                else:
                    steps = [Step(f"Stop {t} and don't start it at boot", ["systemctl", "disable", "--now", u], root=True)]
                self.run(("Turn on " if on else "Turn off ") + t, steps, reload=False, done=settle)
            sub = desc + f"\n{unit} · {'running' if active else 'not running'} · {state}"
            g.add(switch_row(title, sub, enabled, change))
        self.svc_holder.append(g)
        self.svc_holder.append(label("Core parts of Ubuntu that must start are hidden here. Everything else is on the Services page.",
                                     "dim", wrap=True))

    # ---------------------------------------------------------------- F4: your services
    def load_user(self) -> None:
        self.loading(self.user_box, "Asking your session which services start at login…")
        self.bg(boot.user_services, self.show_user)

    def show_user(self, res: dict) -> None:
        box = self.user_box
        clear(box)
        box.append(label("Your helpers at login", "section-title"))
        box.append(label("Small background helpers that run as you, not as the whole system, so changing them needs no password. "
                         "Switching one off stops it now and at every login.", "dim", wrap=True))
        if not res.get("available"):
            box.append(banner(f"Couldn't reach your session's service manager ({res.get('error') or 'not running'}). "
                              "This works when you're logged in to the desktop normally.", "info"))
            return
        units = res["units"]
        g = group("", f"{sum(u['state'] == 'enabled' for u in units)} of {len(units)} start when you log in.")
        if not units:
            g.add(action_row("Nothing extra", "No services of your own start at login."))
        for u in units:
            g.add(self._user_row(u))
        box.append(g)


    def _user_row(self, u: dict) -> Adw.ActionRow:
        running = u["active"] in ("active", "activating", "reloading")
        if u["active"] == "failed":
            word, kind = "failed", "bad"
        elif u["kind"] == "timer" and running:
            word, kind = "scheduled", "ok"
        elif u["sub"] == "running":
            word, kind = "running", "ok"
        else:
            word, kind = ("ready", "ok") if running else ("stopped", "neutral")
        how = {"timer": "runs on a schedule", "socket": "starts when something asks for it", "path": "starts when a file changes"}.get(u["kind"], "")
        sub = " · ".join(x for x in [u["what"] or u["description"], u["unit"], how, "set up by you or an app you use" if u["mine"] else "",
                                     "keep this on" if u["keep"] else ""] if x)
        act = "stop" if running else "start"
        sb = button(icon="media-playback-stop-symbolic" if running else "media-playback-start-symbolic", css="flat",
                    tooltip="Stop it for now" if running else "Start it now",
                    on_click=lambda: self.run(f"{act.capitalize()} {u['name']}", boot.user_unit_steps(u["unit"], act), ask=False,
                                              reload=False, done=lambda ok: self.load_user()))
        lb = button(icon="text-x-generic-symbolic", css="flat", tooltip="Show its log",
                    on_click=lambda: self.bg(lambda: boot.user_unit_logs(u["unit"]), lambda t: self.text(f"Log of {u['name']}", t)))
        sw = Gtk.Switch(active=u["state"] == "enabled", tooltip_text="Start at every login")
        sw._guard = False

        def toggled(w, _p) -> None:
            if w._guard:
                return
            on = w.get_active()

            def settle(ok: bool) -> None:
                if not ok:
                    w._guard = True
                    w.set_active(not on)
                    w._guard = False
                else:
                    self.load_user()
            explain = ("Starts it now and at every login." if on else
                       "Stops it now and at every login." + (f" Careful: {u['what'].rstrip('.')} stops working." if u["keep"] else ""))
            self.run(("Turn on " if on else "Turn off ") + u["name"], boot.user_unit_steps(u["unit"], "enable --now" if on else "disable --now"),
                     explain, danger=u["keep"] and not on, ok_label="Turn on" if on else "Turn off", reload=False, done=settle)
        sw.connect("notify::active", toggled)
        return action_row(u.get("title") or u["name"], sub, pill(word, kind), sb, lb, sw)

    # ---------------------------------------------------------------- F3: boot speed
    def load_speed(self) -> None:
        self.loading(self.speed_box, "Measuring…")

        def work():
            b = self.analysis or boot.analyze()
            return b, boot.boot_history()
        self.bg(work, self.show_speed)

    def show_speed(self, res) -> None:
        b, hist = res
        self._history = hist
        box = self.speed_box
        clear(box)
        if not b.get("total"):
            box.append(banner("Boot timing isn't available here. It needs a PC that started normally with systemd "
                              + (f"({b['error']})." if b.get("error") else "."), "info"))
            return
        bars = HBars("mauve", row=26, label_width=200)
        bars.set_items([(title, b[k], secs(b[k])) for k, title in PARTS if b.get(k)])
        chart = button("Draw a boot chart", icon="x-office-drawing-symbolic", css="suggested-action",
                       tooltip="A picture of everything that started, in order", on_click=self.boot_chart)
        full = button("Every item's time", icon="view-list-symbolic",
                      on_click=lambda: self.bg(lambda: out(["systemd-analyze", "blame", "--no-pager"], timeout=15),
                                               lambda t: self.text("How long each part took to start", t)))
        box.append(card(label("WHERE THE TIME WENT", "tile-title"), bars,
                        label(f"Total {secs(b['total'])}" + (f"; the desktop was ready {secs(b['target_at'])} after the kernel handed over."
                                                              if b.get("target_at") else "."), "dim", wrap=True),
                        hbox(chart, full, spacer()), spacing=10))
        chain = b.get("chain", [])
        if chain:
            g = group("The chain that decided how long it took",
                      "Read it from the bottom up: each item waited for the one below it. “took” is how long that item itself needed; "
                      "the big ones are worth a look.")
            for c in chain:
                sub = f"ready {secs(c['at'])} after start" + (f" · took {secs(c['took'])}" if c["took"] else "")
                why = boot.explain_unit(c["unit"])
                if why:
                    sub += f"\n{why}"
                suffix = [pill("slow", "warn")] if c["took"] >= 2 else []
                row = action_row(("  " * min(c["depth"], 6)) + c["unit"], sub, *suffix)
                g.add(row)
            box.append(g)
        if len(hist) >= 2:
            hb = HBars("teal", row=22, label_width=180)
            hb.set_items([(time.strftime("%a %d %b, %H:%M", time.localtime(h["when"])), h["total"], secs(h["total"])) for h in reversed(hist)])
            box.append(card(label("RECENT BOOTS", "tile-title"), label("Newest first. A sudden jump usually means a new service or an update.",
                                                                       "dim", wrap=True), hb, spacing=8))

    def boot_chart(self) -> None:
        steps, dest = boot.plot_steps()
        self.run("Draw a boot chart", steps, f"Saves a picture of the last boot to {dest} and opens it. Each bar is one thing that started; "
                 "long red bars are slow.", ok_label="Draw", ask=False, reload=False, done=lambda ok: ok and open_path(str(dest)))

    # ---------------------------------------------------------------- F1: boot menu (GRUB)
    def load_menu(self) -> None:
        self.loading(self.menu_box, "Reading the boot menu settings…")
        self.bg(boot.grub_info, self.show_menu)

    def show_menu(self, info: dict) -> None:
        self.grub = info
        box = self.menu_box
        clear(box)
        loader = info["loader"]
        box.append(label("The boot menu (GRUB) is the list you can see right after switching the PC on, before Ubuntu starts. "
                         "It lets you pick another system (like Windows), an older kernel, or a recovery mode.", "dim", wrap=True))
        if loader["name"] == "systemd-boot":
            box.append(banner("This PC starts with systemd-boot, not GRUB, so these settings don't apply. systemd-boot's menu is set in "
                              "loader.conf on the EFI partition.", "info"))
            return
        if not loader["grub_file"]:
            box.append(banner("GRUB's settings file (/etc/default/grub) isn't on this PC, so there's no boot menu to change here.", "info"))
            return
        s = info["settings"]
        entries = [e for e in info["entries"] if e["kind"] == "menuentry"]
        if info["dropins"]:
            files = sorted(set(info["dropins"].values()))
            box.append(banner("Some of these settings are also set in " + ", ".join(files) + ", which wins over the changes made here ("
                              + ", ".join(sorted(info["dropins"])) + ").", "warn"))

        # style
        self.m_style = Adw.ComboRow(title="Menu", model=Gtk.StringList.new([t for _, t, _ in boot.STYLES]))
        keys = [k for k, _, _ in boot.STYLES]
        self.m_style.set_selected(keys.index(s["style"]) if s["style"] in keys else 0)
        # countdown
        self.m_wait = Adw.SwitchRow(title="Wait until I choose", subtitle="No countdown: the menu stays until you pick something.")
        self.m_wait.set_active(s["timeout"] < 0)
        self.m_timeout = Adw.SpinRow.new_with_range(0, 60, 1)
        self.m_timeout.set_title("Seconds before it starts the default")
        self.m_timeout.set_value(max(0, s["timeout"]))
        self.m_timeout.set_sensitive(s["timeout"] >= 0)
        # default entry
        self._default_keys = ["0", "saved"]
        names = ["The first one (normally Ubuntu)", "The one I picked last time"]
        for e in entries:
            if e["index"] == "0":
                continue
            self._default_keys.append(e["path"])
            names.append((e["parent"] + " › " if e["parent"] else "") + e["title"])
        if s["remember"]:
            cur_key = "saved"
        else:
            hit = boot.find_entry(s["default"], entries)
            cur_key = "0" if s["default"] == "0" or (hit and hit["index"] == "0") else (hit["path"] if hit else s["default"])
            if cur_key not in self._default_keys:
                self._default_keys.append(cur_key)
                names.append(f"Set by hand: {cur_key}")
        self.m_default = Adw.ComboRow(title="Start by default", model=Gtk.StringList.new(names))
        self.m_default.set_selected(self._default_keys.index(cur_key))
        if not entries and info["cfg_from"] in ("denied", "missing"):
            self.m_default.set_subtitle(esc("Load the menu list below to pick a specific entry."))
        # quiet + os-prober
        self.m_quiet = Adw.SwitchRow(title="Quiet start with the Ubuntu logo",
                                     subtitle=esc("Off shows the text messages while starting: handy when something goes wrong at boot."))
        self.m_quiet.set_active(s["quiet"] and s["splash"])
        self.m_osp = Adw.SwitchRow(title="Look for other systems (like Windows)",
                                   subtitle=esc("Adds Windows or other Linux installs on this PC to the menu when it's rebuilt."))
        self.m_osp.set_active(s["os_prober"] is True)
        self._menu_initial = self._menu_state()
        for w in (self.m_style, self.m_default):
            w.connect("notify::selected", self._menu_changed)
        for w in (self.m_wait, self.m_quiet, self.m_osp):
            w.connect("notify::active", self._menu_changed)
        self.m_timeout.connect("notify::value", self._menu_changed)
        self._style_sub()
        box.append(group("Boot menu", "", self.m_style, self.m_wait, self.m_timeout, self.m_default, self.m_quiet, self.m_osp))

        self.m_pending = label("No changes yet.", "dim")
        self.m_apply = button("Review and apply…", icon="emblem-ok-symbolic", css="suggested-action", on_click=self.apply_menu)
        self.m_apply.set_sensitive(False)
        undo = button("Undo my changes", on_click=self.load_menu)
        extra = [button("Show the file", icon="text-x-generic-symbolic", on_click=lambda: self.text("/etc/default/grub", info["text"]))]
        if info["backup"]:
            extra.append(button("Restore the backup…", icon="edit-undo-symbolic",
                                on_click=lambda: self.run("Restore the previous boot menu settings", boot.grub_restore_steps(),
                                                          "Puts back /etc/default/grub as it was before the last change made here, and rebuilds "
                                                          "the menu.", ok_label="Restore", reload=False, done=lambda ok: ok and self.load_menu())))
        box.append(flow(self.m_apply, undo, *extra, spacing=8, min_per_line=2))
        box.append(self.m_pending)

        # the menu itself
        eg = group("What's in the boot menu", "")
        saved = info.get("saved")
        default_entry = entries[0] if entries and cur_key == "0" else (saved if cur_key == "saved" else boot.find_entry(cur_key, entries))
        if info["cfg_from"] in ("denied", "missing"):
            if info["cfg_from"] == "denied":
                eg.add(action_row("Only admins can read the menu list on this PC", "Load it once with your password to see the entries and pick one.",
                                  button("Load it…", css="flat", on_click=self.copy_cfg)))
            else:
                eg.add(action_row("The menu list (/boot/grub/grub.cfg) wasn't found", "It's created the first time the menu is rebuilt."))
        else:
            if info["cfg_from"] == "stale-copy":
                eg.set_description(esc("This is an older copy; the menu changed since."))
                eg.set_header_suffix(button("Refresh", icon="view-refresh-symbolic", css="flat", on_click=self.copy_cfg))
            for e in info["entries"]:
                hint = self._entry_hint(e)
                pills = []
                if default_entry is e:
                    pills.append(pill("starts by default", "accent"))
                if saved is e and cur_key == "saved":
                    pills.append(pill("picked last time", "info"))
                title = ("    " * e["depth"]) + e["title"]
                eg.add(action_row(title, hint, *pills))
            if not info["entries"]:
                eg.add(action_row("No entries found", "The menu list looks empty."))
        box.append(eg)
        box.append(label("Changes are saved to /etc/default/grub (the old file is kept as /etc/default/grub.pc-backup) and take effect "
                         "the next time the PC starts. Tip: to see a hidden menu, hold Shift or tap Esc right after switching on.",
                         "dim", wrap=True))

    @staticmethod
    def _entry_hint(e: dict) -> str:
        t = e["title"].lower()
        if e["kind"] == "submenu":
            return "A folder with older kernels and recovery mode."
        if "recovery mode" in t:
            return "Safe mode with a repair menu. Use it when Ubuntu doesn't start normally."
        if "windows" in t:
            return "Starts Windows."
        if "uefi firmware" in t:
            return "Opens your PC's BIOS / UEFI settings."
        if "memory test" in t or "memtest" in t:
            return "Checks your RAM for faults (takes a while)."
        if "linux" in t and e["depth"]:
            return "Ubuntu with this specific kernel version."
        return ""

    def _menu_state(self) -> dict:
        return {"style": boot.STYLES[self.m_style.get_selected()][0], "wait": self.m_wait.get_active(),
                "timeout": int(self.m_timeout.get_value()), "default": self._default_keys[self.m_default.get_selected()],
                "quiet": self.m_quiet.get_active(), "os_prober": self.m_osp.get_active()}

    def _style_sub(self) -> None:
        self.m_style.set_subtitle(esc(boot.STYLES[self.m_style.get_selected()][2]))

    def _menu_changed(self, *_a) -> None:
        self._style_sub()
        self.m_timeout.set_sensitive(not self.m_wait.get_active())
        now = self._menu_state()
        if now["style"] == "menu" and now["timeout"] == 0 and not now["wait"] and self._menu_initial["style"] != "menu":
            self.m_timeout.set_value(5)   # a menu shown for 0 seconds is no menu at all
            return
        n = sum(1 for k in now if now[k] != self._menu_initial[k] and not (k == "timeout" and now["wait"]))
        self.m_pending.set_text(f"{n} change{'s' if n != 1 else ''} not applied yet." if n else "No changes yet.")
        self.m_apply.set_sensitive(n > 0)

    def _menu_want(self) -> dict:
        now, init = self._menu_state(), self._menu_initial
        want: dict = {}
        if now["style"] != init["style"]:
            want["style"] = now["style"]
        if now["wait"] != init["wait"] or (not now["wait"] and now["timeout"] != init["timeout"]):
            want["timeout"] = -1 if now["wait"] else now["timeout"]
        if now["default"] != init["default"]:
            want["remember"] = now["default"] == "saved"
            if now["default"] != "saved":
                want["default"] = now["default"]
        if now["quiet"] != init["quiet"]:
            want["quiet"] = want["splash"] = now["quiet"]
        if now["os_prober"] != init["os_prober"]:
            want["os_prober"] = now["os_prober"]
        return want

    def apply_menu(self) -> None:
        info = self.grub
        changes = boot.settings_changes(info["vals"], self._menu_want())
        if not changes:
            self.toast("Nothing to change.")
            return
        new = boot.grub_edit(info["text"], changes)
        diff = boot.grub_diff(info["text"], new)
        explain = ("\n".join("• " + x for x in boot.describe_changes(changes)) +
                   "\n\nThe exact lines are shown below. The old file is kept as /etc/default/grub.pc-backup, then the menu is rebuilt. "
                   "Takes effect the next time the PC starts.")
        self.run("Change the boot menu", boot.grub_apply_steps(new, refresh_copy=info["cfg_from"] in ("copy", "stale-copy"), diff=diff),
                 explain, ok_label="Apply", reload=False, done=lambda ok: ok and self.load_menu())

    def copy_cfg(self) -> None:
        self.run("Read the boot menu list", boot.copy_grub_cfg_steps(),
                 "The list of boot menu entries can only be read by admins on this PC. This makes a private copy for this app.",
                 ok_label="Read it", reload=False, done=lambda ok: ok and self.load_menu())

    # ---------------------------------------------------------------- command palette
    def palette_action(self, key: str) -> None:
        tab = {"grub": "menu", "chart": "speed", "chain": "speed", "usersvc": "services", "delay": "login"}.get(key)
        if tab:
            self.stack.set_visible_child_name(tab)
        if key == "chart":
            self.boot_chart()
        elif key == "delay":
            self.toast("Click the clock button next to an app to open it later.", 5)


PAGE = StartupPage
