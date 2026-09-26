"""Services: everything systemd runs (system + your user) with plain explanations, memory/CPU, start/stop/boot/block, logs;
your own scripts kept running or scheduled (pm2-like), timers, and cron jobs in plain English."""

from __future__ import annotations

import os
import time

from gi.repository import Adw, GLib, Gtk

from ...core import services
from ...core.fmt import ago, duration, human
from ...core.run import Step, out
from ..util import button, clear, esc, flow, hbox, label, open_in_terminal, pill, spacer, status_icon, vbox
from ..widgets import Column, DataTable
from .base import Page, action_row, banner, group, tabs

STATE = {"active": ("running", "ok"), "failed": ("failed", "bad"), "inactive": ("stopped", "neutral"), "activating": ("starting", "info"),
         "deactivating": ("stopping", "info"), "reloading": ("reloading", "info")}
BOOT = {"enabled": ("at boot", "accent"), "disabled": ("manual", "neutral"), "static": ("as needed", "neutral"), "masked": ("blocked", "bad"),
        "masked-runtime": ("blocked", "bad"), "indirect": ("as needed", "neutral"), "generated": ("auto", "neutral"), "alias": ("alias", "neutral"),
        "enabled-runtime": ("this boot", "info")}
CRITICAL = {"dbus", "systemd-logind", "gdm", "gdm3", "NetworkManager", "polkit", "systemd-journald", "systemd-udevd", "accounts-daemon",
            "gnome-shell", "pipewire", "wireplumber", "user@1000", "snapd", "udisks2", "upower", "systemd-resolved", "dbus-broker",
            "systemd-timesyncd", "chrony", "chronyd", "apparmor", "ufw", "wpa_supplicant", "gnome-session-manager", "xdg-desktop-portal"}
FILTERS = ["All", "Running", "Failed", "Stopped", "Start at boot", "Blocked"]
SCHED_KINDS = [("minutes", "Every few minutes"), ("hours", "Every few hours"), ("daily", "Every day"), ("weekly", "Every week")]
MODE_KEYS = list(services.MODES)
BLOCK_WARNING = ("Blocking means nothing can start this service any more: not you, not other programs, not Ubuntu itself, until you unblock it. "
                 "If Ubuntu or one of your apps needs it, that part of your PC stops working (block the wrong thing and you can lose Wi-Fi, sound "
                 "or even the login screen). Only block things you're sure you don't use. You can undo it here with Unblock.")


def _cpu_text(v, _d=None) -> str:
    if v is None:
        return ""
    return "<1s" if v < 1 else duration(v)


class ScriptDialog(Adw.Dialog):
    """Add or edit one of your scripts: name, command, folder, when (keep running / schedule / at login)."""

    def __init__(self, page: "ServicesPage", spec: services.ScriptSpec | None = None, existing: set[str] | None = None):
        super().__init__()
        self.page, self.editing, self.existing = page, spec is not None, existing or set()
        spec = spec or services.ScriptSpec(name="", command="")
        self.set_title("Edit script" if self.editing else "Add a script")
        self.set_content_width(620)
        self.set_content_height(620)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_end_title_buttons(False)
        hb.set_show_start_title_buttons(False)
        hb.pack_start(button("Cancel", on_click=self.close))
        self.ok = button("Save" if self.editing else "Create", css="suggested-action", on_click=self._create)
        hb.pack_end(self.ok)
        tv.add_top_bar(hb)
        box = vbox(spacing=18)
        for m in ("top", "bottom"):
            getattr(box, f"set_margin_{m}")(12)
        box.set_margin_start(18)
        box.set_margin_end(18)

        self.name = Adw.EntryRow(title="Name (e.g. my-bot)")
        self.name.set_text(spec.name)
        self.name.set_sensitive(not self.editing)
        self.name.connect("changed", lambda *_: self._update())
        self.command = Adw.EntryRow(title="Command (what you'd type in a terminal)")
        self.command.set_text(spec.command)
        self.command.connect("changed", lambda *_: self._update())
        pick = button(icon="document-open-symbolic", css="flat", tooltip="Pick a script file", on_click=self._pick_file)
        pick.set_valign(Gtk.Align.CENTER)
        self.command.add_suffix(pick)
        self.folder_path = spec.folder
        self.folder = Adw.ActionRow(title="Folder it runs in")
        choose = button("Choose…", css="flat", on_click=self._pick_folder)
        choose.set_valign(Gtk.Align.CENTER)
        self.folder.add_suffix(choose)
        box.append(group("What to run", "", self.name, self.command, self.folder))

        self.mode = Adw.ComboRow(title="When", model=Gtk.StringList.new(list(services.MODES.values())))
        self.mode.set_selected(MODE_KEYS.index(spec.mode) if spec.mode in MODE_KEYS else 0)
        self.mode.connect("notify::selected", lambda *_: self._update())
        self.restart = Adw.SwitchRow(title="Restart it if it crashes", subtitle="Tries again after 5 seconds (gives up after 10 crashes in 5 minutes).")
        self.restart.set_active(spec.restart)
        self.kind = Adw.ComboRow(title="How often", model=Gtk.StringList.new([t for _, t in SCHED_KINDS]))
        self.kind.set_selected(next((i for i, (k, _t) in enumerate(SCHED_KINDS) if k == spec.kind), 0))
        self.kind.connect("notify::selected", lambda *_: self._update())
        self.every = Adw.SpinRow.new_with_range(1, 1440, 1)
        self.every.set_value(spec.every)
        self.every.connect("notify::value", lambda *_: self._update())
        self.at = Adw.EntryRow(title="At what time (HH:MM, 24-hour)")
        self.at.set_text(spec.at)
        self.at.connect("changed", lambda *_: self._update())
        self.day = Adw.ComboRow(title="On", model=Gtk.StringList.new([services.WEEKDAY_NAMES[d] for d in services.WEEKDAYS]))
        self.day.set_selected(services.WEEKDAYS.index(spec.weekday) if spec.weekday in services.WEEKDAYS else 0)
        self.day.connect("notify::selected", lambda *_: self._update())
        self.boot = Adw.SwitchRow(title="Also when I'm not logged in",
                                  subtitle="Starts when the PC boots, even before anyone logs in (turns on 'lingering' for your account).")
        self.boot.set_active(spec.boot)
        self.boot.connect("notify::active", lambda *_: self._update())
        box.append(group("When it runs", "", self.mode, self.restart, self.kind, self.every, self.at, self.day, self.boot))

        self.preview = label("", ["heading"], wrap=True)
        self.error = label("", "bad-text", wrap=True)
        box.append(vbox(self.preview, self.error, spacing=4))
        box.append(label("It runs in a login shell (bash -l) in that folder, so it behaves like in a terminal and ~/.local/bin works. "
                         "If a command isn't found (for example node from nvm), use its full path: type `which node` in a terminal to see it. "
                         "Its output goes to the log (the Logs button).", "dim", wrap=True))
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(box)
        tv.set_content(sw)
        self.set_child(tv)
        self._update()

    def spec(self) -> services.ScriptSpec:
        return services.ScriptSpec(
            name=services.slugify(self.name.get_text()) if not self.editing else self.name.get_text(), command=self.command.get_text().strip(),
            folder=self.folder_path, mode=MODE_KEYS[self.mode.get_selected()], restart=self.restart.get_active(),
            kind=SCHED_KINDS[self.kind.get_selected()][0], every=int(self.every.get_value()), at=self.at.get_text().strip(),
            weekday=services.WEEKDAYS[self.day.get_selected()], boot=self.boot.get_active())

    def _update(self) -> None:
        s = self.spec()
        sched = s.mode == "schedule"
        self.restart.set_visible(s.mode == "always")
        self.kind.set_visible(sched)
        self.every.set_visible(sched and s.kind in ("minutes", "hours"))
        self.every.set_title("Every how many minutes" if s.kind == "minutes" else "Every how many hours")
        self.at.set_visible(sched and s.kind in ("daily", "weekly"))
        self.day.set_visible(sched and s.kind == "weekly")
        self.folder.set_subtitle(esc(self.folder_path or "Your home folder"))
        raw = self.name.get_text()
        slug = services.slugify(raw)
        self.name.set_title("Name (e.g. my-bot)" if not raw else f"Name · saved as pc-{slug or '…'}")
        try:
            when = services.schedule_text(s)
        except ValueError:  # half-typed time
            when = ""
        self.preview.set_text(when + "." if when else "")
        self.error.set_text("")

    def _pick_file(self) -> None:
        d = Gtk.FileDialog(title="Pick a script")

        def done(dlg, res) -> None:
            try:
                f = dlg.open_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                path = f.get_path()
                self.command.set_text(services.guess_command(path))
                if not self.folder_path:
                    self.folder_path = os.path.dirname(path)
                if not self.name.get_text() and not self.editing:
                    self.name.set_text(services.slugify(os.path.splitext(os.path.basename(path))[0]))
                self._update()
        d.open(self.get_root(), None, done)

    def _pick_folder(self) -> None:
        d = Gtk.FileDialog(title="Folder the script runs in")

        def done(dlg, res) -> None:
            try:
                f = dlg.select_folder_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                self.folder_path = f.get_path()
                self._update()
        d.select_folder(self.get_root(), None, done)

    def _create(self) -> None:
        s = self.spec()
        err = services.validate_spec(s, self.existing, self.editing)
        if err:
            self.error.set_text(err)
            return
        self.close()
        verb = "Update" if self.editing else "Add"
        self.page.run(f"{verb} script {s.name}", services.create_script_steps(s, editing=self.editing),
                      f"{services.schedule_text(s)}. It's saved as a service of your account (no admin rights needed); "
                      "you can stop or remove it any time under My scripts.", ok_label="Save" if self.editing else "Create",
                      reload=False, done=lambda ok: self.page.load_scripts())


class ServicesPage(Page):
    ID = "services"
    TITLE = "Services"
    ICON = "system-run-symbolic"
    SUBTITLE = "Background programs managed by systemd, your own scripts, and scheduled jobs. Explained in plain words; the important ones are protected."
    SCROLL = False
    PALETTE = [("script", "Keep a script running / run it on a schedule (like pm2)"), ("cron", "Cron jobs explained"),
               ("blocked", "Blocked (masked) services"), ("memory", "Which services use the most memory")]

    def build(self) -> None:
        self.items: list[services.Service] = []
        self.header()
        self.svc_box = vbox(spacing=10)
        self.svc_box.set_vexpand(True)
        self.scripts_box = vbox(spacing=16)
        self.timers_box = vbox(spacing=10)
        self.timers_box.set_vexpand(True)
        self.cron_box = vbox(spacing=16)
        sw, self.stack = tabs(("services", "Services", "system-run-symbolic", self.svc_box),
                              ("scripts", "My scripts", "utilities-terminal-symbolic", self._scroller(self.scripts_box)),
                              ("timers", "Timers", "alarm-symbolic", self.timers_box),
                              ("cron", "Cron jobs", "x-office-calendar-symbolic", self._scroller(self.cron_box)))
        self.stack.set_vexpand(True)
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()

        # services tab
        self.search_entry = Gtk.SearchEntry(placeholder_text="Find a service…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.table.set_filter(e.get_text()))
        self.scope = Gtk.DropDown.new_from_strings(["System services", "Your services"])
        self.scope.connect("notify::selected", lambda *_: self.load_services())
        self.state = Gtk.DropDown.new_from_strings(FILTERS)
        self.state.connect("notify::selected", lambda *_: self.render())
        self.svc_box.append(flow(self.search_entry, self.scope, self.state, spacing=8, max_per_line=3))
        self.banner = vbox()
        self.svc_box.append(self.banner)
        self.table = DataTable([
            Column("st", "State", "pill", width=96, sort="active"),
            Column("name", "Service", "bold", width=210),
            Column("what", "What it does", "text", expand=True),
            Column("mem", "Memory", "size", width=86),
            Column("cpu", "CPU time", "num", width=82, fmt=_cpu_text),
            Column("boot", "Starts", "pill", width=104, sort="enabled"),
        ], on_activate=lambda r: self.details(), on_select=lambda r: self._selection(r), empty="No services match.", sort="active",
            descending=False, search=lambda d, q: q in d["name"].lower() or q in d["what"].lower())
        self.table.set_vexpand(True)
        self.table.set_context(lambda r: [("Logs", lambda _r: self.show_logs()), ("Details", lambda _r: self.details())], "services")
        self.svc_box.append(self.table)
        self.block_btn = button("Block…", icon="action-unavailable-symbolic", tooltip="Stop it and never let anything start it (mask)",
                                on_click=self.toggle_block)
        self.actions = flow(
            button("Start", icon="media-playback-start-symbolic", on_click=lambda: self.act("start")),
            button("Stop", icon="media-playback-stop-symbolic", on_click=lambda: self.act("stop")),
            button("Restart", icon="view-refresh-symbolic", on_click=lambda: self.act("restart")),
            button("On at boot", tooltip="Start automatically at every boot", on_click=lambda: self.act("enable")),
            button("Off at boot", tooltip="Don't start it at boot (you can still start it by hand)", on_click=lambda: self.act("disable")),
            self.block_btn,
            button(icon="text-x-generic-symbolic", tooltip="Logs", on_click=self.show_logs),
            button(icon="dialog-information-symbolic", tooltip="Details", on_click=self.details), spacing=6, max_per_line=8)
        self.svc_box.append(self.actions)
        self.svc_box.append(label("Memory and CPU time are for running services (CPU time = total processor time used since it started). "
                                  "Click a column title to sort.", "dim", wrap=True))

        # timers tab
        self.timers_box.append(label("Jobs that systemd runs on a schedule (like cron). Most come with Ubuntu and keep it healthy.", "dim", wrap=True))
        self.timers = DataTable([
            Column("unit", "Timer", "bold", width=200),
            Column("what", "What it does", "text", expand=True),
            Column("next", "Next run", "text", width=150, sort="next_sort"),
            Column("left", "In", "muted", width=90),
            Column("last", "Last run", "muted", width=150),
        ], on_activate=self.timer_details, empty="No timers.", sort="next", descending=False,
            search=lambda d, q: q in d["unit"].lower() or q in d["what"].lower())
        self.timers.set_vexpand(True)
        self.timers_box.append(self.timers)

    def _scroller(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(child)
        child.set_margin_end(4)
        return sw

    # ---------------------------------------------------------------- lifecycle
    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()
        if self.stack.get_visible_child_name() != "services":
            self.bg(services.failed, lambda f: self.win.set_badge("services", len([s for s in f if not s.user]), bad=True))

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"services": self.load_services, "scripts": self.load_scripts, "timers": self.load_timers, "cron": self.load_cron}[name]()

    # ---------------------------------------------------------------- services
    def load_services(self) -> None:
        self.table.set_empty("Loading services…")
        user = self.scope.get_selected() == 1
        self.bg(lambda: services.services_full(user=user), self.show)

    def show(self, items: list[services.Service]) -> None:
        self.items = items
        clear(self.banner)
        failed = [s for s in items if s.active == "failed"]
        if failed:
            text = f"{len(failed)} service{'s' if len(failed) != 1 else ''} failed: " + ", ".join(s.name for s in failed[:6])
            show = button("Show", css="flat", on_click=lambda: self.state.set_selected(2))
            reset = button("Clear failed state", css="flat", on_click=lambda: self.run(
                "Clear failed services", [Step("Reset failed services", ["systemctl", *(["--user"] if self.scope.get_selected() == 1 else []), "reset-failed"],
                                               root=self.scope.get_selected() == 0)],
                "Forgets that they failed (they aren't restarted). Useful after you've fixed or removed the cause."))
            self.banner.append(banner(text, "bad", show, reset))
        self.banner.set_visible(bool(failed))
        self.render()
        if self.scope.get_selected() == 0:
            self.win.set_badge("services", len(failed), bad=True)

    def render(self) -> None:
        f = self.state.get_selected()
        rows = []
        for s in self.items:
            blocked = s.enabled.startswith("masked") or s.load == "masked"
            if f == 1 and s.active != "active" or f == 2 and s.active != "failed" or f == 3 and s.active not in ("inactive", "failed") \
                    or f == 4 and s.enabled != "enabled" or f == 5 and not blocked:
                continue
            what = services.explain(s.unit) or s.description
            st = STATE.get(s.active, (s.active, "neutral"))
            if s.active == "active" and s.sub == "exited":
                st = ("finished", "neutral")
            rows.append({"key": s.unit, "st": st, "active": s.active, "name": s.name, "what": what,
                         "boot": BOOT.get(s.enabled, (s.enabled or "-", "neutral")), "enabled": s.enabled, "sub": s.sub,
                         "mem": getattr(s, "mem", None), "cpu": getattr(s, "cpu", None), "_s": s})
        self.table.set_rows(rows)
        self.table.set_empty("No blocked services. (Blocking = masking: nothing can start them.)" if f == 5 else "No services match.")
        self._selection(self.table.selected())

    def _selection(self, r: dict | None) -> None:
        s = r["_s"] if r else None
        blocked = bool(s) and (s.enabled.startswith("masked") or s.load == "masked")
        child = self.block_btn.get_child()
        if isinstance(child, Adw.ButtonContent):
            child.set_label("Unblock" if blocked else "Block…")

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
                 danger=action in ("stop", "disable"), ok_label=action.capitalize(), reload=False, done=lambda ok: self.load_services())

    def toggle_block(self) -> None:
        s = self._sel()
        if not s:
            return
        blocked = s.enabled.startswith("masked") or s.load == "masked"
        if blocked:
            self.run(f"Unblock {s.name}", services.mask_steps(s, False), "Programs (and you) can start it again. It doesn't start it right now; "
                     "use Start or On at boot for that.", ok_label="Unblock", reload=False, done=lambda ok: self.load_services())
            return
        if s.name.split("@")[0] in CRITICAL or s.name.startswith(("systemd-", "dbus", "user@", "getty", "gdm", "gnome-")):
            self.toast(f"{s.name} is part of Ubuntu itself; blocking it could stop the PC from working. It's protected.", 6)
            return
        what = services.explain(s.unit) or s.description
        self.run(f"Block {s.name}?", services.mask_steps(s, True), (f"{s.name}: {what}.\n\n" if what else "") + BLOCK_WARNING,
                 danger=True, ok_label="Block it", reload=False, done=lambda ok: self.load_services())

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

    # ---------------------------------------------------------------- my scripts (L1)
    def load_scripts(self) -> None:
        self.loading(self.scripts_box, "Looking for your scripts…")
        self.bg(lambda: (services.script_jobs(), services.user_manager_ok()), self.show_scripts)

    def show_scripts(self, res) -> None:
        jobs, ok = res
        self.jobs = jobs
        clear(self.scripts_box)
        add = button("Add a script…", icon="list-add-symbolic", css="suggested-action", on_click=self.add_script)
        again = button(icon="view-refresh-symbolic", css="flat", tooltip="Refresh", on_click=self.load_scripts)
        intro = label("Keep a script or program running in the background, start it when you log in, or run it on a schedule. "
                      "Like pm2, but built on Ubuntu's own service manager, so it survives crashes and restarts. No admin rights needed.",
                      "dim", wrap=True, hexpand=True)
        self.scripts_box.append(flow(intro, again, add, spacing=10, max_per_line=3))
        for w in (add, again):
            w.set_valign(Gtk.Align.CENTER)
        if not ok:
            self.scripts_box.append(hbox(status_icon("warn"), label(
                "Your account's service manager isn't running here, so scripts can't be started right now. This happens in containers and "
                "remote shells; in a normal desktop login it always runs.", None, wrap=True, hexpand=True), spacing=10, css="banner-warn"))
        if not jobs:
            ex = group("Nothing here yet", "Some ideas:",
                       action_row("Keep a bot or small server running", "e.g. python3 bot.py, restarted automatically if it crashes.",
                                  prefix=Gtk.Image.new_from_icon_name("media-playlist-repeat-symbolic")),
                       action_row("Back up a folder every night", "e.g. rsync -a ~/Documents /media/usb/backup, every day at 22:00.",
                                  prefix=Gtk.Image.new_from_icon_name("x-office-calendar-symbolic")),
                       action_row("Start a dev server when you log in", "e.g. npm run dev in your project folder.",
                                  prefix=Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")))
            self.scripts_box.append(ex)
            return
        g = group("Your scripts", f"{len(jobs)} script{'s' if len(jobs) != 1 else ''}, saved in ~/.config/systemd/user as pc-<name>.")
        for j in jobs:
            g.add(self._script_row(j))
        self.scripts_box.append(g)

    def _script_row(self, j: dict) -> Adw.ExpanderRow:
        spec: services.ScriptSpec = j["spec"]
        text, kind = j["state"]
        bits = [j["when"]]
        now = time.time()
        if spec.mode == "always":
            if j["active"] == "active" and j["since"]:
                bits.append(f"running for {duration(now - j['since'])}")
            if j["restarts"]:
                bits.append(f"restarted {j['restarts']} time{'s' if j['restarts'] != 1 else ''}")
        else:
            if j["last_exit"]:
                res = "OK" if j["exit_code"] == 0 else f"failed (exit code {j['exit_code']})"
                bits.append(f"last run {ago(j['last_exit'])}: {res}")
            if spec.mode == "schedule" and j["on"] and (j["next"] or j["next_text"]):
                bits.append(f"next {power_clock(j['next'])}" if j["next"] else f"next in {j['next_text']}")
        if j["mem"]:
            bits.append(f"{human(j['mem'])} memory")
        row = Adw.ExpanderRow(title=esc(j["name"]), subtitle=esc(" · ".join(bits)))
        row.set_subtitle_lines(3)
        row.add_prefix(status_icon({"ok": "ok", "bad": "bad", "warn": "warn"}.get(kind, "info")))
        p = pill(text, kind)
        row.add_suffix(p)
        cmd = Adw.ActionRow(title="Command", subtitle=esc(spec.command))
        cmd.set_subtitle_selectable(True)
        cmd.set_subtitle_lines(4)
        row.add_row(cmd)
        row.add_row(Adw.ActionRow(title="Folder", subtitle=esc(spec.folder or "Your home folder")))
        sched = spec.mode == "schedule"
        act_buttons = []
        if j["on"]:
            act_buttons.append(button("Pause schedule" if sched else "Stop", icon="media-playback-stop-symbolic", css="flat",
                                      on_click=lambda: self.script_act(j, "stop")))
        else:
            act_buttons.append(button("Turn on" if sched else "Start", icon="media-playback-start-symbolic", css="flat",
                                      on_click=lambda: self.script_act(j, "start")))
        if spec.mode != "always":
            act_buttons.append(button("Run now", css="flat", on_click=lambda: self.script_act(j, "run")))
        elif j["on"]:
            act_buttons.append(button("Restart", css="flat", on_click=lambda: self.script_act(j, "restart")))
        act_buttons.append(button("Logs", icon="text-x-generic-symbolic", css="flat", on_click=lambda: self.bg(
            lambda: services.script_logs(j["name"]), lambda t: self.text(f"Log: {j['name']}", t or "No output yet."))))
        act_buttons.append(button("Edit", icon="document-edit-symbolic", css="flat", on_click=lambda: self.edit_script(j)))
        act_buttons.append(button("Remove", icon="user-trash-symbolic", css="flat", on_click=lambda: self.remove_script(j)))
        acts = flow(*act_buttons, min_per_line=1, max_per_line=5, column_spacing=6, row_spacing=6)
        for m in ("top", "bottom", "start"):
            getattr(acts, f"set_margin_{m}")(8)
        row.add_row(acts)
        return row

    def add_script(self, spec: services.ScriptSpec | None = None) -> None:
        ScriptDialog(self, None, {j["name"] for j in getattr(self, "jobs", [])}).present(self.win)

    def edit_script(self, j: dict) -> None:
        ScriptDialog(self, j["spec"], {x["name"] for x in getattr(self, "jobs", [])}).present(self.win)

    def script_act(self, j: dict, action: str) -> None:
        sched = j["spec"].mode == "schedule"
        self.run(f"{action.capitalize()} {j['name']}", services.script_action_steps(j["name"], action, sched), ask=False, reload=False,
                 done=lambda ok: GLib.timeout_add(600, lambda: (self.load_scripts(), False)[1]))

    def remove_script(self, j: dict) -> None:
        self.run(f"Remove script {j['name']}", services.remove_script_steps(j["name"]),
                 "Stops it and deletes its service files. Your script file itself isn't touched.", danger=True, ok_label="Remove",
                 reload=False, done=lambda ok: self.load_scripts())

    # ---------------------------------------------------------------- timers
    def load_timers(self) -> None:
        self.timers.set_empty("Loading timers…")
        self.bg(services.timers, self.show_timers)

    def show_timers(self, rows: list[dict]) -> None:
        data = []
        for r in rows:
            data.append({**r, "key": f"{r['user']}{r['unit']}", "unit": r["unit"].removesuffix(".timer") + (" (you)" if r["user"] else ""),
                         "raw": r["unit"], "what": services.explain_timer(r["unit"]), "next": services.short_time(r["next"]) or "not scheduled",
                         "next_sort": _iso(r["next"]) or "~", "last": services.short_time(r["last"]) or "never"})
        self.timers.set_rows(data)
        self.timers.set_empty("No timers (systemd isn't answering here).")

    def timer_details(self, r: dict) -> None:
        scope = ["--user"] if r["user"] else []
        self.bg(lambda: "\n".join([out(["systemctl", *scope, "status", r["raw"], "--no-pager", "-n", "0"], timeout=10), "", "── Timer ──",
                                   out(["systemctl", *scope, "cat", r["raw"]], timeout=10), "", "── What it runs ──",
                                   out(["systemctl", *scope, "cat", r["activates"]], timeout=10)]),
                lambda t: self.text(r["unit"], t))

    # ---------------------------------------------------------------- cron (L2)
    def load_cron(self) -> None:
        self.loading(self.cron_box, "Reading cron jobs…")
        self.bg(services.cron_jobs, self.show_cron)

    def show_cron(self, c: dict) -> None:
        clear(self.cron_box)
        self.cron_box.append(label("Cron is the classic way to run commands on a schedule. Each schedule is translated into plain English. "
                                   "For new jobs, My scripts is easier (and shows logs).", "dim", wrap=True))
        if not c["installed"]:
            left = " Jobs listed below were left behind by packages and don't run." if c["system"] or any(c["periodic"].values()) else ""
            self.cron_box.append(hbox(status_icon("info"), label("Cron isn't installed on this PC; Ubuntu uses systemd timers for its own jobs "
                                                                 "(see the Timers tab)." + left, None, wrap=True, hexpand=True), spacing=10))
        edit = button("Edit in terminal", icon="utilities-terminal-symbolic", css="flat", tooltip="Opens crontab -e in a terminal",
                      on_click=lambda: open_in_terminal(["crontab", "-e"]) or self.toast("No terminal app found.")) if c.get("has_crontab") else None
        rows = [self._cron_row(j, False) for j in c["user"]]
        if not rows:
            rows = [action_row("No cron jobs in your account", "That's normal. Use My scripts to run something on a schedule.")]
        self.cron_box.append(group(f"Your cron jobs ({c['me']})", "", *rows, suffix=edit))
        if c["system"]:
            self.cron_box.append(group("System cron jobs", "Set up by Ubuntu and installed apps (from /etc/crontab and /etc/cron.d).",
                                       *[self._cron_row(j, True) for j in c["system"]]))
        per = c["periodic"]
        if any(per.values()):
            g = group("Periodic scripts", "Scripts dropped into /etc/cron.hourly, daily, weekly and monthly.")
            for key, title, desc in services.PERIODIC:
                items = per.get(key, [])
                if not items:
                    continue
                ex = Adw.ExpanderRow(title=esc(f"{title} ({len(items)})"), subtitle=esc(desc))
                for name, expl in items:
                    ex.add_row(Adw.ActionRow(title=esc(name), subtitle=esc(expl or "Added by an installed package")))
                g.add(ex)
            self.cron_box.append(g)

    def _cron_row(self, j: services.CronJob, system: bool) -> Adw.ActionRow:
        when = j.when[:1].upper() + j.when[1:]
        expl = services.cron_explain(j.source.rsplit("/", 1)[-1]) if system else ""
        sub = j.command + (f"\nruns as {j.user} · {j.source}" if system else "") + (f"\n{expl}" if expl else "")
        r = action_row(when, sub, prefix=Gtk.Image.new_from_icon_name("x-office-calendar-symbolic"))
        r.set_subtitle_lines(4)
        r.set_tooltip_text(j.line)
        return r

    # ---------------------------------------------------------------- command palette
    def palette_action(self, key: str) -> None:
        if key == "script":
            self.stack.set_visible_child_name("scripts")
            self.add_script()
        elif key == "cron":
            self.stack.set_visible_child_name("cron")
        elif key == "blocked":
            self.stack.set_visible_child_name("services")
            self.state.set_selected(5)
        elif key == "memory":
            self.stack.set_visible_child_name("services")
            self.state.set_selected(1)
            self.table.view.sort_by_column(self.table._cols["mem"], Gtk.SortType.DESCENDING)


def _iso(text: str) -> str:
    import re
    m = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text or "")
    return m.group(0) if m else ""


def power_clock(ts: float) -> str:
    t = time.localtime(ts)
    return time.strftime("today %H:%M" if t[:3] == time.localtime()[:3] else "%a %d %b %H:%M", t)


PAGE = ServicesPage
