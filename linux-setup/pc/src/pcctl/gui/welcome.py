"""First-run welcome: what the app does, and the handful of background helpers worth turning on, in one place."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from . import prefs
from .util import button, esc, flow, hbox, label, vbox

TOUR = [
    ("user-trash-symbolic", "Clean & update", "Free space safely and keep Ubuntu, snaps and flatpaks up to date. You always see the commands first."),
    ("power-profile-performance-symbolic", "See what's going on", "Live CPU, memory, disk, network and battery, and a one-click “Why is my PC slow?”."),
    ("applications-engineering-symbolic", "Fix problems", "Troubleshooters for Wi-Fi, sound, Bluetooth, printing and broken installs (Maintenance)."),
    ("utilities-terminal-symbolic", "Made for coding", "Dev servers, ports, Docker, git and GitHub, PATH problems, leaked API keys."),
]


class WelcomeDialog(Adw.Dialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_title("Welcome")
        self.set_content_width(620)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        tv.add_top_bar(hb)
        box = vbox(spacing=16)
        for m in ("start", "end"):
            getattr(box, f"set_margin_{m}")(24)
        box.set_margin_bottom(22)
        icon = Gtk.Image.new_from_icon_name("io.github.infinite4evr.PcCommandCenter")
        icon.set_pixel_size(72)
        box.append(icon)
        t = label("Welcome to PC Command Center", "title-1", xalign=0.5, wrap=True)
        box.append(t)
        box.append(label("Everything to keep this PC fast, clean, safe and ready for coding, in plain words.", "dim", xalign=0.5, wrap=True))

        tour = Gtk.ListBox()
        tour.add_css_class("boxed-list")
        tour.set_selection_mode(Gtk.SelectionMode.NONE)
        for ic, title, sub in TOUR:
            r = Adw.ActionRow(title=esc(title), subtitle=esc(sub))
            r.set_subtitle_lines(3)
            img = Gtk.Image.new_from_icon_name(ic)
            img.add_css_class("accent-text")
            r.add_prefix(img)
            tour.append(r)
        box.append(tour)

        box.append(label("Turn on now? (you can change these any time in Preferences)", "heading", wrap=True))
        opts = Gtk.ListBox()
        opts.add_css_class("boxed-list")
        opts.set_selection_mode(Gtk.SelectionMode.NONE)
        self.weekly = Adw.SwitchRow(title="Weekly checkup", subtitle="Every Sunday: clears safe caches and tells you if something needs you.")
        self.alerts = Adw.SwitchRow(title="Background alerts", subtitle="A notification when a disk is almost full, security updates wait, "
                                    "or a service keeps crashing, even with the app closed.")
        self.taskmgr = Adw.SwitchRow(title="Ctrl+Shift+Esc opens Processes", subtitle="Like Task Manager on Windows.")
        self.weekly.set_active(True)
        self.alerts.set_active(True)
        self.taskmgr.set_active(True)
        self._prefill()
        for r in (self.weekly, self.alerts, self.taskmgr):
            opts.append(r)
        box.append(opts)
        tip = flow(label("Tip:", "dim"), label("Ctrl+K", "kbd"), label("finds any page, action or setting by typing.", "dim", wrap=True),
                   min_per_line=1, max_per_line=3, column_spacing=6, row_spacing=4, halign=Gtk.Align.CENTER)
        box.append(tip)
        skip = button("Not now", css="pill", on_click=self._skip)
        go = button("Start", css=["suggested-action", "pill"], on_click=self._start)
        row = hbox(skip, go, spacing=12)
        row.set_halign(Gtk.Align.CENTER)
        box.append(row)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        sw.set_child(box)
        tv.set_content(sw)
        self.set_child(tv)
        self.set_content_height(640)

    def _prefill(self) -> None:
        """Show what's already on (e.g. the setup script turned the weekly checkup on)."""
        try:
            from ..core import maint, watch
            if maint.timer_status().get("enabled"):
                self.weekly.set_active(True)
                self.weekly.set_sensitive(False)
                self.weekly.set_subtitle("Already on.")
            if watch.settings().get("enabled") and watch.timer_enabled():
                self.alerts.set_active(True)
                self.alerts.set_sensitive(False)
                self.alerts.set_subtitle("Already on.")
            from ..core import shortcuts
            if not shortcuts.available():
                self.taskmgr.set_active(False)
                self.taskmgr.set_sensitive(False)
                self.taskmgr.set_subtitle("Needs GNOME's keyboard settings, which aren't available here.")
            elif any(s.id == shortcuts.TASKMGR_ID for s in shortcuts.custom_shortcuts()):
                self.taskmgr.set_sensitive(False)
                self.taskmgr.set_subtitle("Already set up.")
        except Exception:  # noqa: BLE001 - the welcome must always open
            pass

    def steps(self) -> list:
        from ..core import maint, watch
        steps = []
        if self.weekly.get_active() and self.weekly.get_sensitive():
            steps += maint.enable_timer_steps()
        if self.alerts.get_active() and self.alerts.get_sensitive():
            steps += watch.enable_steps()
        if self.taskmgr.get_active() and self.taskmgr.get_sensitive():
            from ..core import shortcuts
            p = next((p for p in shortcuts.presets() if p["id"] == shortcuts.TASKMGR_ID), None)
            if p:
                steps += shortcuts.add_steps(shortcuts.custom_paths(), p["id"], p["name"], p["command"], p["binding"])
        return steps

    def _skip(self) -> None:
        prefs.set("welcomed", True)
        self.close()

    def _start(self) -> None:
        prefs.set("welcomed", True)
        steps = self.steps()
        self.close()
        if steps:
            from .dialogs import run_steps
            run_steps(self.win, "Getting started", steps, "Sets up the helpers you picked. Nothing needs your password.", ask=False)
