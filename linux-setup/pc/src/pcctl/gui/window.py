"""Main window: sidebar navigation + page stack + toasts."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..core import system  # noqa: E402
from .util import bg, esc, hbox, label, vbox  # noqa: E402

SECTIONS = [
    ("", ["dashboard"]),
    ("Clean & update", ["cleanup", "updates", "apps", "startup"]),
    ("Monitor", ["processes", "storage", "network", "power", "logs"]),
    ("System", ["services", "security", "privacy", "tweaks"]),
    ("Develop", ["dev"]),
    ("Care", ["maintenance"]),
]


def page_classes() -> dict[str, type]:
    """Import every page; a page that fails to import is skipped (and reported) instead of killing the app."""
    import importlib
    import traceback
    res = {}
    for _, ids in SECTIONS:
        for pid in ids:
            try:
                mod = importlib.import_module(f".pages.{pid}", __package__)
                res[mod.PAGE.ID] = mod.PAGE
            except Exception:  # noqa: BLE001
                traceback.print_exc()
    return res


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, start: str | None = None):
        super().__init__(application=app, title="PC Command Center")
        self.set_default_size(1320, 860)
        self.set_size_request(760, 520)
        self.pages: dict = {}
        self.rows: dict[str, Gtk.ListBoxRow] = {}
        self.badges: dict[str, Gtk.Label] = {}
        self.current = ""

        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(230)
        self.split.set_max_sidebar_width(270)

        # ---------- sidebar
        side_tv = Adw.ToolbarView()
        side_hb = Adw.HeaderBar()
        ident = system.identity()
        logo = Gtk.Image.new_from_icon_name("io.github.infinite4evr.PcCommandCenter")
        logo.set_pixel_size(30)
        title = hbox(logo, vbox(label("PC Command Center", "brand-title"), label(ident["host"], "brand-sub"), spacing=0), spacing=10)
        title.set_valign(Gtk.Align.CENTER)
        side_hb.set_title_widget(title)
        menu = Gio.Menu()
        menu.append("Go to or do… (Ctrl+K)", "win.palette")
        menu.append("Keyboard shortcuts", "win.shortcuts")
        menu.append("About PC Command Center", "win.about")
        menu.append("Quit", "app.quit")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu")
        side_hb.pack_end(mb)
        side_tv.add_top_bar(side_hb)
        side_box = vbox(spacing=0)
        classes = page_classes()
        self.classes = classes
        for section, ids in SECTIONS:
            if section:
                side_box.append(label(section.upper(), "nav-section"))
            lb = Gtk.ListBox()
            lb.add_css_class("nav-list")
            lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
            lb.connect("row-activated", self._row_activated)
            for pid in ids:
                cls = classes.get(pid)
                if cls is None:
                    continue
                img = Gtk.Image.new_from_icon_name(cls.ICON)
                badge = label("", "nav-badge", xalign=0.5)
                badge.set_visible(False)
                row = Gtk.ListBoxRow()
                row.set_child(hbox(img, label(cls.TITLE, hexpand=True), badge, spacing=12))
                row._pid = pid
                lb.append(row)
                self.rows[pid] = row
                self.badges[pid] = badge
            side_box.append(lb)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(side_box)
        sw.set_vexpand(True)
        foot = label(f"{ident['os']}\nkernel {ident['kernel']}", ["dim"], wrap=True)
        foot.set_margin_start(18)
        foot.set_margin_bottom(12)
        foot.set_margin_top(8)
        side_tv.set_content(vbox(sw, foot, spacing=0))
        self.split.set_sidebar(Adw.NavigationPage(title="PC Command Center", child=side_tv))

        # ---------- content
        self.content_tv = Adw.ToolbarView()
        self.content_hb = Adw.HeaderBar()
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh (F5)")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_current())
        self.content_hb.pack_end(self.refresh_btn)
        self._header_extra: list[Gtk.Widget] = []
        self.content_tv.add_top_bar(self.content_hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120, hhomogeneous=False, vhomogeneous=False)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)
        self.content_tv.set_content(self.toasts)
        self.content_page = Adw.NavigationPage(title="Dashboard", child=self.content_tv)
        self.split.set_content(self.content_page)

        for pid, cls in classes.items():
            try:
                page = cls(self)
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self.rows[pid].set_visible(False)
                continue
            self.pages[pid] = page
            self.stack.add_named(page, pid)

        # narrow windows: collapse the sidebar
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 820sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)
        self.set_content(self.split)

        self._actions()
        state = load_state()
        if state.get("width") and state.get("height"):
            self.set_default_size(max(760, state["width"]), max(520, state["height"]))
        if state.get("maximized"):
            self.maximize()
        if not start:
            start = state.get("page", "dashboard")
        self.goto(start if start in self.pages else "dashboard")
        self.connect("close-request", self._save_state)
        GLib.timeout_add_seconds(2, lambda: (self.refresh_badges(), False)[1])
        GLib.timeout_add_seconds(600, lambda: (self.refresh_badges(), True)[1])

    def _save_state(self, *_a) -> bool:
        w, h = self.get_default_size()
        save_state({"width": w, "height": h, "maximized": self.is_maximized(), "page": self.current})
        return False

    # ---------------------------------------------------------------- navigation
    def _row_activated(self, _lb, row) -> None:
        self.goto(row._pid)
        self.split.set_show_content(True)

    def goto(self, pid: str) -> None:
        if pid not in self.pages:
            return
        if self.current and self.current != pid:
            self.pages[self.current].deactivate()
        self.current = pid
        page = self.pages[pid]
        self.stack.set_visible_child_name(pid)
        self.content_page.set_title(page.TITLE)
        self.split.set_show_content(True)
        for w in self._header_extra:
            self.content_hb.remove(w)
        self._header_extra = list(page.header_widgets)
        for w in reversed(self._header_extra):
            self.content_hb.pack_end(w)
        for other_pid, row in self.rows.items():
            lb = row.get_parent()
            if other_pid == pid:
                lb.select_row(row)
            elif lb.get_selected_row() is row:
                lb.unselect_row(row)
        page.activate()

    def refresh_current(self) -> None:
        if self.current:
            self.pages[self.current].reload()
            self.toast("Refreshing…", 1)

    def toast(self, text: str, timeout: int = 3) -> None:
        t = Adw.Toast(title=esc(text))
        t.set_timeout(timeout)
        self.toasts.add_toast(t)

    def set_badge(self, pid: str, n: int, bad: bool = False, text: str | None = None) -> None:
        b = self.badges.get(pid)
        if b is None:
            return
        b.set_text(text if text else (str(n) if n < 100 else "99+"))
        b.set_visible(bool(text) or n > 0)
        if bad:
            b.add_css_class("bad")
        else:
            b.remove_css_class("bad")

    def refresh_badges(self) -> None:
        def work():
            from ..core import packages, services
            from ..core.run import out
            ups = packages.parse_apt_upgradable(out(["apt", "list", "--upgradable"], timeout=60))
            failed = services.failed()
            return ups, failed
        bg(work, lambda r: (self.set_badge("updates", sum(u.security for u in r[0]) or len(r[0]), bad=any(u.security for u in r[0])),
                            self.set_badge("services", len(r[1]), bad=True)))

    # ---------------------------------------------------------------- actions
    def _actions(self) -> None:
        def add(name, cb, accels=()):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            self.add_action(a)
            if accels:
                self.get_application().set_accels_for_action(f"win.{name}", list(accels))
        add("refresh", self.refresh_current, ["F5", "<Control>r"])
        add("about", self.about)
        add("shortcuts", self.shortcuts, ["<Control>question"])
        order = [pid for _, ids in SECTIONS for pid in ids if pid in self.pages]
        for i, pid in enumerate(order[:9]):
            add(f"goto-{pid}", lambda p=pid: self.goto(p), [f"<Control>{i + 1}"])
        add("search", self.focus_search, ["<Control>f"])
        add("palette", self.palette, ["<Control>k", "<Control>p"])

    def palette(self) -> None:
        """Ctrl+K: jump to any page or run a common action by typing."""
        from .dialogs import ChoiceDialog
        rows = [(f"page:{pid}", self.classes[pid].TITLE, "Go to page") for _, ids in SECTIONS for pid in ids if pid in self.pages]
        actions = [
            ("cleanup:scan", "Scan for junk", "Cleanup"), ("cleanup:deep", "Deep scan (projects, duplicates, old versions)", "Cleanup"),
            ("updates:all", "Update everything", "Updates"), ("updates:sec", "Install security fixes only", "Updates"),
            ("maintenance:tune", "One-click tune-up", "Maintenance"), ("maintenance:backup", "Back up my settings", "Maintenance"),
            ("storage:big", "Find big files", "Storage"), ("storage:dups", "Find duplicate files", "Storage"),
            ("network:speed", "Internet speed test", "Network"), ("network:diag", "Why is the internet not working?", "Network"),
            ("network:ports", "What's listening on which port", "Network"), ("security:fix", "Fix security issues", "Security"),
            ("tweaks:all", "Apply recommended tweaks", "Tweaks"), ("apps:get", "Install an app", "Apps"),
            ("dev:srv", "Running dev servers", "Developer"), ("power:bios", "Restart into BIOS / UEFI", "Power"),
        ]
        rows += [(k, t, s) for k, t, s in actions if k.split(":")[0] in self.pages]
        ChoiceDialog("Go to or do…", rows, self._palette_pick, explain="Type to filter. Tip: Ctrl+K opens this from anywhere.").present(self)

    def _palette_pick(self, key: str | None) -> None:
        if not key:
            return
        kind, _, what = key.partition(":")
        if kind == "page":
            self.goto(what)
            return
        self.goto(kind)
        page = self.pages[kind]

        def later() -> bool:
            if key == "cleanup:scan":
                page.scan(False)
            elif key == "cleanup:deep":
                page.scan(True)
            elif key == "updates:all":
                page.update_all()
            elif key == "updates:sec":
                page.security_only()
            elif key == "maintenance:tune":
                page.tune_up()
            elif key == "maintenance:backup":
                from ..core import maint
                page.run("Back up settings", maint.backup_settings_steps(), ask=False)
            elif key == "storage:big":
                page.stack.set_visible_child_name("big")
            elif key == "storage:dups":
                page.stack.set_visible_child_name("dups")
                page.find_dups()
            elif key == "network:speed":
                page.stack.set_visible_child_name("diag")
                page.speed()
            elif key == "network:diag":
                page.stack.set_visible_child_name("diag")
                page.diagnose()
            elif key == "network:ports":
                page.stack.set_visible_child_name("ports")
            elif key == "security:fix":
                page.fix_all()
            elif key == "tweaks:all":
                page.apply_all()
            elif key == "apps:get":
                page.stack.set_visible_child_name("get")
                page.get_entry.grab_focus()
            elif key == "dev:srv":
                page.stack.set_visible_child_name("srv")
            elif key == "power:bios":
                from ..core.run import Step
                page.run("Restart into BIOS", [Step("Restart into BIOS/UEFI setup", ["systemctl", "reboot", "--firmware-setup"])],
                         "Save your work first. Open apps will close.", danger=True, ok_label="Restart")
            return False
        GLib.timeout_add(250, later)

    def focus_search(self) -> None:
        page = self.pages.get(self.current)
        entry = getattr(page, "search_entry", None)
        if entry is not None:
            entry.grab_focus()

    def about(self) -> None:
        d = Adw.AboutDialog(application_name="PC Command Center", application_icon="io.github.infinite4evr.PcCommandCenter", version=__version__,
                            developer_name="Made for ashu-pc", comments="Monitor, clean, update, secure and tune your Ubuntu computer.",
                            license_type=Gtk.License.MIT_X11)
        d.present(self)

    def shortcuts(self) -> None:
        from .dialogs import show_text
        order = [pid for _, ids in SECTIONS for pid in ids if pid in self.pages]
        lines = ["Keyboard shortcuts", ""] + [f"  Ctrl+{i + 1}      {self.classes[p].TITLE}" for i, p in enumerate(order[:9])]
        lines += ["", "  Ctrl+K       Go to a page or run an action by typing", "  F5 / Ctrl+R  Refresh this page",
                  "  Ctrl+F       Search (on pages with a search box)", "  Ctrl+Q       Quit",
                  "  Double-click / Enter on a row opens its details"]
        show_text(self, "Keyboard shortcuts", "\n".join(lines))


STATE_FILE = Path.home() / ".config/pc/gui.json"


def load_state() -> dict:
    import json
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(d: dict) -> None:
    import json
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(d))
    except OSError:
        pass


def load_css() -> None:
    import os
    provider = Gtk.CssProvider()
    path = os.path.join(os.path.dirname(__file__), "style.css")
    try:
        provider.load_from_path(path)
    except GLib.Error as e:
        print("CSS error:", e)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
