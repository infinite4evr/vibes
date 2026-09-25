"""Care: one-click tune-up, troubleshooters, weekly checkup with health history, system report, backups and snapshots, setup scripts."""

from __future__ import annotations

import os
import time
from pathlib import Path

from gi.repository import Adw, Gdk, Gtk

from ... import __version__
from ...core import junk, maint, packages, report, troubleshoot, watch
from ...core.fmt import ago, human
from ...core.run import HOME, Step, has, py_step
from ..dialogs import ChecksDialog, ask_text
from ..runner import capture
from ..util import button, clear, esc, flow, hbox, label, launch, open_in_terminal, open_path, vbox
from ..widgets import card, rgb
from .base import Page, action_row, banner, group, switch_row, tabs


class HistoryChart(Gtk.DrawingArea):
    """Health score (0-100) per day, as a line with dots. Colours follow the light/dark theme."""

    def __init__(self, height: int = 170):
        super().__init__()
        self.points: list[dict] = []
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_points(self, points: list[dict]) -> None:
        self.points = points[-120:]
        self.queue_draw()

    def _draw(self, _a, cr, w: int, h: int) -> None:
        left, right, top, bottom = 34, 10, 10, 22
        pw, ph = max(1, w - left - right), max(1, h - top - bottom)
        cr.select_font_face("sans")
        cr.set_font_size(10)
        for v in (0, 50, 75, 100):
            y = top + ph * (1 - v / 100)
            cr.set_source_rgba(*rgb("overlay0", 0.35))
            cr.set_line_width(1)
            cr.move_to(left, y + 0.5)
            cr.line_to(w - right, y + 0.5)
            cr.stroke()
            cr.set_source_rgba(*rgb("overlay1", 1))
            cr.move_to(4, y + 4)
            cr.show_text(str(v))
        pts = self.points
        if not pts:
            return
        n = len(pts)

        def xy(i: int, score: float) -> tuple[float, float]:
            x = left + (pw * i / (n - 1) if n > 1 else pw / 2)
            return x, top + ph * (1 - max(0, min(100, score)) / 100)
        cr.set_source_rgba(*rgb("mauve", 0.14))
        cr.move_to(*xy(0, 0))
        for i, p in enumerate(pts):
            cr.line_to(*xy(i, p["score"]))
        cr.line_to(*xy(n - 1, 0))
        cr.close_path()
        cr.fill()
        cr.set_source_rgba(*rgb("mauve", 1))
        cr.set_line_width(2.2)
        for i, p in enumerate(pts):
            (cr.line_to if i else cr.move_to)(*xy(i, p["score"]))
        cr.stroke()
        for i, p in enumerate(pts):
            x, y = xy(i, p["score"])
            col = "green" if p["score"] >= 85 else "yellow" if p["score"] >= 60 else "red"
            cr.set_source_rgba(*rgb(col, 1))
            cr.arc(x, y, 3.2 if n < 40 else 2.2, 0, 6.2832)
            cr.fill()
        cr.set_source_rgba(*rgb("overlay1", 1))
        first, last = pts[0]["day"], pts[-1]["day"]
        cr.move_to(left, h - 6)
        cr.show_text(first)
        if n > 1:
            ext = cr.text_extents(last)
            cr.move_to(w - right - ext.width, h - 6)
            cr.show_text(last)


class MaintenancePage(Page):
    ID = "maintenance"
    TITLE = "Maintenance"
    ICON = "emblem-system-symbolic"
    SUBTITLE = "Fix common problems, keep the PC in shape on a schedule, make a report when you need help, and keep backups to roll back to."
    PALETTE = [("report", "Create a system report"), ("report-share", "Create a report to share (names hidden)"),
               ("history", "Health score history"), ("snapshots", "System snapshots (Timeshift)")] + \
              [(f"fix-{t.id}", t.palette or t.title) for t in troubleshoot.TROUBLESHOOTERS if t.id != "slow"]

    def build(self) -> None:
        self.header()
        img = Gtk.Image.new_from_icon_name("starred-symbolic")
        img.set_pixel_size(56)
        img.add_css_class("accent-text")
        self.tune_btn = button("Run tune-up", icon="media-playback-start-symbolic", css=["suggested-action", "pill"], on_click=self.tune_up)
        self.tune_sub = label("Installs all updates, cleans recommended junk (caches, old logs, leftovers) and removes unused packages. "
                              "You see every command first.", "subtle", wrap=True)
        t = vbox(label("One-click tune-up", "mid-num"), self.tune_sub, hbox(self.tune_btn), spacing=6)
        t.set_hexpand(True)
        hero = card(hbox(img, t, spacing=22))
        hero.add_css_class("hero")
        self.body.append(hero)
        self.fix_box = vbox(spacing=14)
        self.check_box = vbox(spacing=18)
        self.report_box = vbox(spacing=18)
        self.backup_box = vbox(spacing=18)
        self.setup_box = vbox(spacing=18)
        sw, self.stack = tabs(("fix", "Fix problems", "applications-engineering-symbolic", self.fix_box),
                              ("checkup", "Checkups", "emblem-default-symbolic", self.check_box),
                              ("report", "Report", "x-office-document-symbolic", self.report_box),
                              ("backup", "Backups", "drive-harddisk-symbolic", self.backup_box),
                              ("setup", "Setup", "preferences-other-symbolic", self.setup_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", lambda *_a: self._load_tab())
        self.last_report: Path | None = None
        self._build_fix()
        self._build_report()

    def load(self) -> None:
        self.loaded: set[str] = set()
        self._load_tab()

    def _load_tab(self) -> None:
        name = self.stack.get_visible_child_name()
        if name in getattr(self, "loaded", set()):
            return
        self.loaded.add(name)
        if name == "checkup":
            clear(self.check_box)
            self.check_box.append(self._history_group())
            self.check_box.append(self._schedule_group())
        elif name == "backup":
            clear(self.backup_box)
            self.backup_box.append(self._backup_group())
            self.backup_box.append(self._snapshot_group())
        elif name == "setup":
            clear(self.setup_box)
            self.setup_box.append(self._app_group())
            self.setup_box.append(self._setup_group())
            self.setup_box.append(self._prefs_group())
            self.setup_box.append(group("About", "", action_row("PC Command Center", f"version {__version__} · also available in the terminal as `pc`",
                                                                button("Open terminal version", css="flat", on_click=lambda: open_in_terminal(["pc"]))),
                                        action_row("Keyboard shortcuts", "Ctrl+K finds anything, Ctrl+1…9 switch pages, F5 refreshes.",
                                                   button("Show", css="flat", on_click=self.win.shortcuts))))

    def palette_action(self, key: str) -> None:
        if key.startswith("fix-"):
            self.stack.set_visible_child_name("fix")
            self.troubleshoot(key[4:])
        elif key in ("report", "report-share"):
            self.stack.set_visible_child_name("report")
            self.make_report(key == "report-share")
        elif key == "history":
            self.stack.set_visible_child_name("checkup")
        elif key == "snapshots":
            self.stack.set_visible_child_name("backup")
            if maint.snapshot_tools()["timeshift"]:
                self.list_snapshots()

    # ---------------------------------------------------------------- troubleshooters
    def _build_fix(self) -> None:
        self.fix_box.append(label("Pick what's wrong. Each one checks the usual causes, tells you what it found in plain words, and offers a fix. "
                                  "Nothing changes until you press a button.", "dim", wrap=True))
        tiles = []
        for t in troubleshoot.TROUBLESHOOTERS:
            icon = Gtk.Image.new_from_icon_name(t.icon)
            icon.set_pixel_size(28)
            icon.add_css_class("accent-text")
            text = vbox(label(t.title, "heading"), label(t.description, "dim", wrap=True), spacing=2)
            text.set_hexpand(True)
            b = Gtk.Button()
            b.add_css_class("card")
            b.add_css_class("tile")
            inner = hbox(icon, text, spacing=14)
            inner.set_margin_top(6)
            inner.set_margin_bottom(6)
            b.set_child(inner)
            b.connect("clicked", lambda _b, tid=t.id: self.troubleshoot(tid))
            b.update_property([Gtk.AccessibleProperty.LABEL], [f"{t.title}: {t.description}"])
            tiles.append(b)
        self.fix_box.append(flow(*tiles, spacing=12, min_per_line=2, max_per_line=3, homogeneous=True))
        self.fix_box.append(label("Still stuck? Make a report (Report tab) and share it when you ask for help. Names and addresses are hidden.",
                                  "dim", wrap=True))

    def troubleshoot(self, tid: str) -> None:
        t = troubleshoot.BY_ID.get(tid)
        if not t:
            return
        busy = "Measuring for a couple of seconds…" if tid == "slow" else "Checking…"
        ChecksDialog(t.title, t.description, t.checks, self, busy=busy).present_and_start(self.win)

    # ---------------------------------------------------------------- tune-up
    def tune_up(self) -> None:
        self.tune_btn.set_sensitive(False)
        self.tune_sub.set_text("Looking for updates and junk…")

        def work():
            found = junk.scan(deep=False)
            steps = packages.update_all_steps()
            freed = 0
            titles = []
            for j in found:
                if j.default and not j.pick and j.id not in ("apt-cache",):
                    s = j.steps_for()
                    if s:
                        steps += s
                        freed += j.size or 0
                        titles.append(j.title)
            steps.append(Step("Clean package download cache", ["apt-get", "clean"], root=True, optional=True))
            return steps, freed, titles

        def ready(res) -> None:
            steps, freed, titles = res
            self.tune_btn.set_sensitive(True)
            self.tune_sub.set_text("Installs all updates, cleans recommended junk (caches, old logs, leftovers) and removes unused packages. "
                                   "You see every command first.")
            self.run("Tune-up", steps, f"Updates everything, then frees about {human(freed)} from: {', '.join(titles) or 'nothing extra'}. "
                     "Takes a few minutes; keep the laptop plugged in.", ok_label="Start tune-up")
        self.bg(work, ready)

    # ---------------------------------------------------------------- health history
    def _history_group(self) -> Gtk.Widget:
        hist = watch.health_history()
        chart = HistoryChart()
        chart.set_points(hist)
        box = vbox(spacing=10)
        if len(hist) >= 2:
            first, last = hist[0], hist[-1]
            change = last["score"] - first["score"]
            trend = "steady" if abs(change) < 5 else ("better" if change > 0 else "worse")
            free_txt = ""
            if first.get("free") and last.get("free"):
                d = last["free"] - first["free"]
                free_txt = f" Free space on / went {'up' if d >= 0 else 'down'} by {human(abs(d))}."
            box.append(label(f"{len(hist)} days recorded since {first['day']}. Today {last['score']}/100, {trend} overall.{free_txt}", "dim", wrap=True))
            worst = min(hist, key=lambda h: h["score"])
            if worst["score"] < 60:
                box.append(label(f"Lowest: {worst['score']} on {worst['day']}.", "dim"))
        else:
            box.append(label("The app saves one health score per day (the day's worst) whenever it checks. Keep the background alerts on "
                             "(Preferences → Alerts) to record days you don't open the app.", "dim", wrap=True))
        box.append(card(chart))
        return group("Health over time", "", box)

    # ---------------------------------------------------------------- report
    def _build_report(self) -> None:
        self.report_status = label("A single web page with this PC's specs, health, disks, updates and recent errors. Open it in any browser, "
                                   "print it, or send it to someone helping you.", "dim", wrap=True)
        self.report_box.append(self.report_status)
        me = button("Create report", icon="x-office-document-symbolic", css=["suggested-action", "pill"], on_click=lambda: self.make_report(False))
        share = button("Create a copy to share", icon="send-to-symbolic", css="pill", on_click=lambda: self.make_report(True))
        self.report_box.append(hbox(me, share, spacing=10))
        self.report_quick = Adw.SwitchRow(title="Quick report", subtitle="Skip the update check and the error log (takes a second instead of ~20).")
        self.report_box.append(group("", "", self.report_quick))
        self.report_result = vbox(spacing=10)
        self.report_box.append(self.report_result)
        self.report_box.append(group("What the shared copy hides", "",
                                     action_row("Hidden", "Computer name, your user name, IP addresses (shows only the first half of home-network "
                                                "ones like 192.168.x.x), MAC addresses and IPv6 addresses."),
                                     action_row("Kept", "Model, processor, memory, graphics, disk sizes, Ubuntu version, health checks and error messages.")))

    def make_report(self, shared: bool) -> None:
        clear(self.report_result)
        sp = Gtk.Spinner()
        sp.start()
        self.report_result.append(hbox(sp, label("Collecting… (checks updates and the last day of errors)" if not self.report_quick.get_active()
                                                 else "Collecting…", "dim")))
        quick = self.report_quick.get_active()

        def work():
            data = report.collect(quick=quick)
            path = report.save(redacted=shared, data=data)
            return path, report.text(data, redacted=True), report.summary_line(data)
        self.bg(work, lambda res: self._report_done(res, shared))

    def _report_done(self, res, shared: bool) -> None:
        path, txt, summary = res
        self.last_report = path
        clear(self.report_result)

        def copy_text() -> None:
            Gdk.Display.get_default().get_clipboard().set(txt)
            self.toast("Copied as text (names hidden). Paste it into a chat or forum post.")
        self.report_result.append(group("Your report" if not shared else "Report to share", summary,
                                        action_row(path.name, str(path).replace(str(HOME), "~"),
                                                   button("Open", css="suggested-action", on_click=lambda: launch(report.open_cmd(path))),
                                                   button("Show in folder", css="flat", on_click=lambda: open_path(str(path.parent)))),
                                        action_row("Copy as text", "Plain text with names hidden, for a chat or a forum post.",
                                                   button("Copy", css="flat", on_click=copy_text))))
        self.toast("Report saved to " + str(path.parent).replace(str(HOME), "~"))

    # ---------------------------------------------------------------- schedule
    def _schedule_group(self):
        st = maint.timer_status()

        def toggle(on: bool, settle) -> None:
            self.run("Weekly checkup", maint.enable_timer_steps() if on else maint.disable_timer_steps(),
                     "Every Sunday (or the next time the PC is on) it clears safe caches, then sends a notification if anything needs you." if on else "",
                     ok_label="Turn on" if on else "Turn off", ask=on, done=settle)
        log = maint.STATE_DIR / "maintain.log"
        sub = (f"Next: {st['next']}" if st["next"] else "Sundays at 11:00") + (f" · last ran {st['last']}" if st["last"] else "")
        return group("Weekly checkup", "Runs in the background. Never needs your password, never removes anything you'd miss.",
                     switch_row("Automatic weekly checkup", sub, st["enabled"], toggle),
                     action_row("Run it now", "Clears safe caches and checks disks, updates and services.",
                                button("Run", css="flat", on_click=lambda: self.run("Weekly checkup", [py_step("Run checkup", maint.maintain_auto, "pc maintain --auto")],
                                                                                     ask=False))),
                     action_row("Past results", "What the checkup did each week.",
                                button("View", css="flat", on_click=lambda: self.text("Checkup history", log.read_text() if log.exists() else "No runs yet."))))

    # ---------------------------------------------------------------- backups
    def _backup_group(self):
        rows = [action_row("Back up settings now", "Shell, git, editor (VS Code, Zed), terminal, GNOME settings, fonts and SSH config into ~/Backups.",
                           button("Back up", css="suggested-action", on_click=lambda: self.run("Back up settings", maint.backup_settings_steps(), ask=False)))]
        for b in maint.settings_backups()[:6]:
            rows.append(action_row(b["name"], f"{ago(b['time'])} · {human(b['size'])}",
                                   button("Restore…", css="flat", on_click=lambda p=b["path"]: self.run(
                                       "Restore settings", maint.restore_settings_steps(p), "Overwrites your current settings files with the ones in this backup. "
                                       "Tip: back up first so you can go back.", danger=True, ok_label="Restore")),
                                   button(icon="user-trash-symbolic", css="flat", tooltip="Delete backup", on_click=lambda p=b["path"]: self.run(
                                       "Delete backup", [Step("Delete backup", ["rm", "-f", p])], os.path.basename(p), danger=True, ok_label="Delete"))))
        return group("Settings backups", "Copy the files to a USB stick or cloud drive to move your setup to a new PC.", *rows,
                     suffix=button("Open folder", css="flat", on_click=lambda: open_path(str(maint.BACKUP_DIR)) if maint.BACKUP_DIR.exists() else self.toast("No backups yet.")))

    # ---------------------------------------------------------------- snapshots
    def _snapshot_group(self):
        tools = maint.snapshot_tools()
        rows = []
        if tools["timeshift"]:
            rows.append(action_row("Create a system snapshot", "Saves the system (not your files) so you can roll back a bad update or driver.",
                                   button("Create", css="suggested-action", on_click=lambda: self.run("System snapshot", maint.timeshift_steps(),
                                                                                                       "Takes a few minutes the first time.", ok_label="Create"))))
            rows.append(action_row("Snapshots", "See, and delete, the snapshots you have. Reading the list needs your password.",
                                   button("Show", css="flat", on_click=self.list_snapshots)))
            rows.append(action_row("Timeshift app", "Restore a snapshot, set a schedule, choose the disk.",
                                   button("Open", css="flat", on_click=self._open_timeshift)))
        else:
            rows.append(action_row("Timeshift isn't installed", "System snapshots let you undo a bad update in minutes. Highly recommended.",
                                   button("Install", css="suggested-action", on_click=lambda: self.run("Install Timeshift", maint.timeshift_steps(), ok_label="Install"))))
        if tools["deja-dup"]:
            rows.append(action_row("Backups of your files", "Ubuntu's Backups app (Déjà Dup) copies your home folder to a drive or the cloud.",
                                   button("Open", css="flat", on_click=lambda: launch(["deja-dup"]))))
        self.snap_list = vbox(spacing=8)
        return vbox(group("System snapshots", "", *rows), self.snap_list, spacing=10)

    def list_snapshots(self) -> None:
        if not hasattr(self, "snap_list"):
            return
        clear(self.snap_list)
        sp = Gtk.Spinner()
        sp.start()
        self.snap_list.append(hbox(sp, label("Reading the snapshot list (needs your password)…", "dim")))
        capture(maint.timeshift_list_steps(), self._snapshots_loaded)

    def _snapshots_loaded(self, ok: bool, lines: list[str]) -> None:
        clear(self.snap_list)
        if not ok and not lines:
            self.snap_list.append(label("Couldn't read the list (password cancelled?).", "dim"))
            return
        info = maint.parse_timeshift_list("\n".join(lines))
        if not info["configured"] or not info["device"]:
            self.snap_list.append(banner("Timeshift isn't set up yet. Open the Timeshift app once to pick the disk for snapshots.", "info",
                                         button("Open Timeshift", css="flat", on_click=self._open_timeshift)))
            return
        snaps = info["snapshots"]
        head = f"{len(snaps)} snapshot{'s' if len(snaps) != 1 else ''} on {info['device']}" + (f" · {info['free']} free" if info["free"] else "")
        self.snap_list.append(label(head, "dim"))
        if not snaps:
            return
        lb = Gtk.ListBox()
        lb.add_css_class("boxed-list")
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        for sn in snaps:
            when = time.strftime("%a %d %b %Y, %H:%M", time.localtime(sn["time"])) if sn["time"] else sn["name"]
            sub = ", ".join(sn["kinds"]) + (f" · {sn['comment']}" if sn["comment"] else "") + (f" · {ago(sn['time'])}" if sn["time"] else "")
            row = Adw.ActionRow(title=esc(when), subtitle=esc(sub))
            b = button(icon="user-trash-symbolic", css="flat", tooltip="Delete this snapshot")
            b.set_valign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, n=sn["name"], w=when: self.run(
                "Delete snapshot", maint.timeshift_delete_steps([n]), f"Deletes the snapshot from {w}. You can't roll back to it afterwards; "
                "newer snapshots are not affected.", danger=True, ok_label="Delete", reload=False, done=lambda ok: ok and self.list_snapshots()))
            row.add_suffix(b)
            lb.append(row)
        self.snap_list.append(lb)
        old = [s["name"] for s in snaps if s["time"] and time.time() - s["time"] > 90 * 86400 and "O" not in s["tags"]]
        if len(old) >= 2:
            self.snap_list.append(hbox(button(f"Delete {len(old)} automatic snapshots older than 3 months", css="flat", on_click=lambda: self.run(
                "Delete old snapshots", maint.timeshift_delete_steps(old), "Keeps the newer ones and the ones you made by hand.", danger=True,
                ok_label="Delete", reload=False, done=lambda ok: ok and self.list_snapshots()))))

    def _open_timeshift(self) -> None:
        launch(["timeshift-launcher"]) if has("timeshift-launcher") else launch(["pkexec", "timeshift-gtk"])

    # ---------------------------------------------------------------- this app: update, extras, uninstall
    def _app_group(self) -> Gtk.Widget:
        from ...core import selfupdate
        st = selfupdate.status()
        rows = []
        ver = action_row(f"PC Command Center {st['running']}", st["reason"])
        if st["update"]:
            ver.add_suffix(button("Update", css="suggested-action", on_click=self.update_app))
        rows.append(ver)
        if not (selfupdate.HELPER.exists() and selfupdate.POLICY.exists()):
            rows.append(action_row("Nicer password prompt", "The password pop-up says “PC Command Center” and remembers your password for "
                                   "a few minutes, so several fixes in a row ask only once.",
                                   button("Set up", css="flat", on_click=lambda: self.run("Password prompt", selfupdate.admin_install_steps(),
                                                                                         ok_label="Set up", reload=True))))
        if not selfupdate.search_provider_on():
            rows.append(action_row("Find pages from GNOME search", "Type “clean”, “battery” or “fix sound” in the Activities overview to jump "
                                   "straight there.", button("Turn on", css="flat", on_click=lambda: self.run(
                                       "GNOME search", selfupdate.search_steps(), "Takes effect after you log out and back in.", ok_label="Turn on"))))
        rows.append(action_row("Welcome and quick setup", "The first-run screen: weekly checkup, alerts and the Ctrl+Shift+Esc shortcut.",
                               button("Show", css="flat", on_click=self.win.welcome)))
        rows.append(action_row("Uninstall", "Removes the app, its schedules, shortcuts in the app grid and the terminal version. "
                               "Scripts you made on the Services page keep working.", button("Uninstall…", css="destructive-action", on_click=self.uninstall)))
        return group("This app", "", *rows)

    def update_app(self) -> None:
        from ...core import selfupdate

        def done(ok: bool) -> None:
            if not ok:
                return
            d = Adw.AlertDialog(heading="Updated", body="Restart the app to use the new version?")
            d.add_response("later", "Later")
            d.add_response("restart", "Restart now")
            d.set_response_appearance("restart", Adw.ResponseAppearance.SUGGESTED)
            d.connect("response", lambda _d, r: r == "restart" and self._relaunch())
            d.present(self.win)
        self.run("Update PC Command Center", selfupdate.update_steps(), "Copies the newer version from your linux-setup folder. "
                 "Your settings and history stay.", ok_label="Update", reload=False, done=done)

    def _relaunch(self) -> None:
        from ...core import selfupdate
        launch(selfupdate.relaunch_cmd())
        self.win.get_application().quit()

    def uninstall(self) -> None:
        from ...core import selfupdate
        d = Adw.AlertDialog(heading="Uninstall PC Command Center?",
                            body="Keep your settings (Preferences, history, never-clean list) in case you install it again?")
        d.add_response("cancel", "Cancel")
        d.add_response("keep", "Uninstall, keep settings")
        d.add_response("all", "Uninstall everything")
        d.set_response_appearance("keep", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_response_appearance("all", Adw.ResponseAppearance.DESTRUCTIVE)
        if hasattr(d, "set_prefer_wide_layout"):
            d.set_prefer_wide_layout(True)

        def pick(_d, r: str) -> None:
            if r in ("keep", "all"):
                self.run("Uninstall", selfupdate.uninstall_steps(keep_settings=(r == "keep")), "The app closes when it's done. To install it "
                         "again later: bash setup.sh app (in your linux-setup folder).", danger=True, ok_label="Uninstall", reload=False,
                         done=lambda ok: ok and self.win.get_application().quit())
        d.connect("response", pick)
        d.present(self.win)

    # ---------------------------------------------------------------- setup scripts
    def _setup_group(self):
        d = maint.setup_dir()
        if not d:
            return group("Setup scripts", "The linux-setup folder wasn't found.",
                         action_row("Where is linux-setup?", "Point to the folder that contains setup.sh.",
                                    button("Choose…", css="flat", on_click=self.choose_setup)))
        sh_path = str(d / "setup.sh")

        def term(*args: str) -> None:
            open_in_terminal(["bash", sh_path, *args])
        return group("Setup scripts", f"From {str(d).replace(str(HOME), '~')}. They run in a terminal because they ask questions.",
                     action_row("Re-apply the setup", "Theme, fonts, terminal, editors and tools. Safe to run again.", button("Run", css="flat", on_click=lambda: term("setup"))),
                     action_row("Scan report", "A text report of disk use and junk.", button("Run", css="flat", on_click=lambda: term("scan"))),
                     action_row("Tips", "Your cheat sheet: aliases, shortcuts, commands.", button("Show", css="flat", on_click=lambda: term("tips"))),
                     action_row("Undo the look", "Puts GNOME's theme, fonts and terminal back the way they were before the setup.",
                                button("Undo…", css="flat", on_click=lambda: term("undo"))),
                     suffix=button("Open folder", css="flat", on_click=lambda: open_path(str(d))))

    def choose_setup(self) -> None:
        def got(p: str | None) -> None:
            if p and (Path(p).expanduser() / "setup.sh").exists():
                maint.save_config(setup_dir=p)
                self.load()
            elif p:
                self.toast("No setup.sh in that folder.")
        ask_text(self.win, "linux-setup folder", "Full path of the folder containing setup.sh", "~/Documents/Vibes/linux-setup", got)

    # ---------------------------------------------------------------- preferences
    def _prefs_group(self):
        roots = maint.config()["projects"]
        rows = []
        for r in roots:
            exists = Path(r).expanduser().is_dir()
            rows.append(action_row(r, "found" if exists else "doesn't exist (skipped)",
                                   button(icon="list-remove-symbolic", css="flat", tooltip="Remove", on_click=lambda rr=r: self._set_roots([x for x in roots if x != rr]))))

        def add() -> None:
            def got(p: str | None) -> None:
                if p and p not in roots:
                    self._set_roots(roots + [p])
            ask_text(self.win, "Add a project folder", "Where you keep code, e.g. ~/code or ~/Documents/Vibes", "~/code", got, ok_label="Add")
        return group("Project folders", "Where the Developer page and the deep cleanup look for your code.", *rows,
                     suffix=button("Add…", icon="list-add-symbolic", css="flat", on_click=add))

    def _set_roots(self, roots: list[str]) -> None:
        maint.save_config(projects=roots)
        self.toast("Saved.")
        self.load()


PAGE = MaintenancePage
