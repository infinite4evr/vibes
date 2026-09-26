"""Main window: sidebar navigation + page stack + toasts."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import __version__  # noqa: E402
from ..core import debug, system, tasks  # noqa: E402
from . import prefs, theme  # noqa: E402
from .util import bg, esc, hbox, label, scrolled, vbox  # noqa: E402

SIDEBAR_MIN = 205
SIDEBAR_DEFAULT = 235
SIDEBAR_MAX = 300
CONTENT_MIN_WHILE_SIDEBAR_VISIBLE = 650
COMPACT_HEADER_AT = 760


SECTIONS = [
    ("", ["dashboard"]),
    ("Clean & update", ["cleanup", "updates", "apps", "startup"]),
    ("Monitor", ["processes", "storage", "network", "power", "logs"]),
    ("System", ["services", "security", "privacy", "tweaks"]),
    ("Develop", ["dev"]),
    ("Care", ["maintenance"]),
]


PALETTE_ACTIONS = [
    ("cleanup:scan", "Scan for junk", "Cleanup"), ("cleanup:deep", "Deep scan (projects, duplicates, old versions)", "Cleanup"),
    ("updates:all", "Update everything", "Updates"), ("updates:sec", "Install security fixes only", "Updates"),
    ("maintenance:tune", "One-click tune-up", "Maintenance"), ("maintenance:backup", "Back up my settings", "Maintenance"),
    ("storage:big", "Find big files", "Storage"), ("storage:dups", "Find duplicate files", "Storage"),
    ("network:speed", "Internet speed test", "Network"), ("network:diag", "Why is the internet not working?", "Network"),
    ("network:ports", "What's listening on which port", "Network"), ("security:fix", "Fix security issues", "Security"),
    ("tweaks:all", "Apply recommended tweaks", "Tweaks"), ("apps:get", "Install an app", "Apps"),
    ("dev:srv", "Running dev servers", "Developer"), ("power:bios", "Restart into BIOS / UEFI", "Power"),
    ("app:preferences", "Preferences", "App"), ("app:activity", "Activity history: everything this app did", "App"),
    ("app:tasks", "Background tasks", "App"),
    ("app:light", "Switch to light style", "App"), ("app:dark", "Switch to dark style", "App"),
    ("app:system", "Follow the system's light/dark style", "App"), ("app:welcome", "Welcome & quick setup", "App"),
]


def all_actions(classes: dict[str, type]) -> list[tuple[str, str, str]]:
    """Every action the palette (and GNOME search) can run: built-in ones plus each page's PALETTE."""
    rows = [(k, t, s) for k, t, s in PALETTE_ACTIONS if k.split(":")[0] in classes or k.startswith("app:")]
    known = {r[0] for r in rows}
    for pid, cls in classes.items():
        rows += [(f"{pid}:{k}", t, cls.TITLE) for k, t in getattr(cls, "PALETTE", []) if f"{pid}:{k}" not in known]
    return rows


def setting_rows() -> list[tuple[str, str, str]]:
    """Individual settings, so typing e.g. 'hot corner' or 'tap to click' finds the page that has it."""
    rows = []
    try:
        from ..core import privacy, tweaks
        for sw in tweaks.DESKTOP:
            rows.append((f"setting:tweaks:{sw.title}", sw.title, f"Setting · Tweaks · {sw.group}"))
        for st in privacy.SETTINGS:
            rows.append((f"setting:privacy:{st.title}", st.title, "Setting · Privacy"))
    except Exception:  # noqa: BLE001
        pass
    return rows


def page_classes(include_errors: bool = False) -> dict[str, type] | tuple[dict[str, type], dict[str, tuple[Exception, str]]]:
    """Import every page while preserving failures for an in-app fallback.

    A broken optional dependency or page module must not silently erase its
    navigation row.  Callers receive both successfully imported page classes
    and import errors so every declared page can still be represented.
    """
    import importlib
    import traceback
    res: dict[str, type] = {}
    errors: dict[str, tuple[Exception, str]] = {}
    for _, ids in SECTIONS:
        for pid in ids:
            try:
                mod = importlib.import_module(f".pages.{pid}", __package__)
                res[mod.PAGE.ID] = mod.PAGE
            except Exception as exc:  # noqa: BLE001
                trace = traceback.format_exc()
                traceback.print_exc()
                debug.exception(f"page import failed: {pid}", exc)
                errors[pid] = (exc, trace)
    return (res, errors) if include_errors else res


class _UnavailablePage(Gtk.Box):
    """Visible fallback for a page that failed to construct.

    A page bug must never make its navigation item silently disappear.  Keeping
    the row visible makes the failure obvious and gives the user a useful error
    to include with a support bundle.
    """

    def __init__(self, win, pid: str, cls: type, exc: Exception, trace: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.ID = pid
        self.TITLE = getattr(cls, "TITLE", pid.replace("_", " ").title())
        self.SUBTITLE = getattr(cls, "SUBTITLE", "")
        self.ICON = getattr(cls, "ICON", "dialog-error-symbolic")
        self.header_widgets: list[Gtk.Widget] = []
        self.loaded = True
        self._trace = trace

        body = vbox(spacing=12)
        body.set_margin_top(28)
        body.set_margin_bottom(28)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.append(label(f"{self.TITLE} could not be loaded", "page-title"))
        body.append(label(
            "This page hit an unexpected interface error. The rest of PC Command Center is still available. "
            "Turn on detailed debug logs in Preferences and export a support bundle if this keeps happening.",
            "page-sub", wrap=True))
        detail = label(f"{type(exc).__name__}: {exc}", ["dim", "mono"], wrap=True, selectable=True)
        body.append(detail)
        copy = Gtk.Button(label="Copy diagnostic details")
        copy.set_halign(Gtk.Align.START)
        copy.connect("clicked", lambda *_: (self.get_clipboard().set(self._trace), win.toast("Diagnostic details copied.")))
        body.append(copy)
        self.append(scrolled(body, 900))

    def activate(self) -> None:
        return

    def deactivate(self) -> None:
        return

    def reload(self) -> None:
        self.win.toast("Restart PC Command Center after applying an update to retry this page.")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, start: str | None = None):
        super().__init__(application=app, title="PC Command Center")
        self.set_default_size(1320, 860)
        self.set_size_request(760, 520)
        self.pages: dict = {}
        self.rows: dict[str, Gtk.ListBoxRow] = {}
        self.badges: dict[str, Gtk.Label] = {}
        self.current = ""

        # A Gtk.Paned gives the desktop app a genuinely user-resizable sidebar.
        # The sidebar itself is wrapped in a Revealer so it can be hidden with a
        # smooth animation instead of permanently consuming horizontal space.
        self.split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.split.set_wide_handle(False)
        self.split.set_resize_start_child(False)
        self.split.set_resize_end_child(True)
        self.split.set_shrink_start_child(True)
        self.split.set_shrink_end_child(False)
        stored_sidebar_width = int(prefs.get("sidebar_width", SIDEBAR_DEFAULT) or SIDEBAR_DEFAULT)
        self._sidebar_width = max(SIDEBAR_MIN, min(SIDEBAR_MAX, stored_sidebar_width))
        self._sidebar_visible = bool(prefs.get("sidebar_visible", True))

        # ---------- sidebar
        side_tv = Adw.ToolbarView()
        side_hb = Adw.HeaderBar()
        side_hb.add_css_class("side-header")
        ident = system.identity()
        logo = Gtk.Image.new_from_icon_name("io.github.infinite4evr.PcCommandCenter")
        logo.set_pixel_size(28)
        brand = label("PC Command Center", "brand-title", ellipsize=True)
        brand_host = label(ident["host"], "brand-sub", ellipsize=True)
        title = hbox(logo, vbox(brand, brand_host, spacing=0), spacing=10)
        title.set_valign(Gtk.Align.CENTER)
        side_hb.set_title_widget(title)
        side_hb.set_show_title(True)
        hide_side = Gtk.Button(icon_name="sidebar-hide-symbolic", tooltip_text="Hide sidebar (Ctrl+Shift+S)")
        hide_side.add_css_class("flat")
        hide_side.connect("clicked", lambda *_: self.set_sidebar_visible(False))
        side_hb.pack_start(hide_side)
        menu = Gio.Menu()
        style = Gio.Menu()
        style.append("Follow system style", "win.appearance::system")
        style.append("Light", "win.appearance::light")
        style.append("Dark", "win.appearance::dark")
        menu.append_section(None, style)
        main = Gio.Menu()
        main.append("Go to or do…", "win.palette")
        main.append("Background tasks", "win.tasks")
        main.append("Activity history", "win.activity")
        main.append("Preferences", "win.preferences")
        menu.append_section(None, main)
        more = Gio.Menu()
        more.append("Keyboard shortcuts", "win.shortcuts")
        more.append("About PC Command Center", "win.about")
        more.append("Quit", "app.quit")
        menu.append_section(None, more)
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu")
        side_hb.pack_end(mb)
        side_tv.add_top_bar(side_hb)
        side_box = vbox(spacing=0)
        side_box.append(self._quick_button())
        classes, import_errors = page_classes(include_errors=True)
        # Keep a metadata entry for every declared route, even if importing its
        # page module failed. This prevents empty section headers in the sidebar.
        self.classes = dict(classes)
        for _section, ids in SECTIONS:
            for pid in ids:
                if pid not in self.classes:
                    title = pid.replace("_", " ").title()
                    self.classes[pid] = type(
                        f"Unavailable_{pid}", (),
                        {"TITLE": title, "SUBTITLE": "This page failed to load.", "ICON": "dialog-error-symbolic", "PALETTE": []},
                    )
        for section, ids in SECTIONS:
            if section:
                side_box.append(label(section.upper(), "nav-section"))
            lb = Gtk.ListBox()
            lb.add_css_class("nav-list")
            lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
            lb.connect("row-activated", self._row_activated)
            for pid in ids:
                cls = self.classes[pid]
                img = Gtk.Image.new_from_icon_name(cls.ICON)
                badge = label("", "nav-badge", xalign=0.5)
                badge.set_visible(False)
                row = Gtk.ListBoxRow()
                nav_title = label(cls.TITLE, "nav-title", hexpand=True, ellipsize=True)
                nav_title.set_tooltip_text(cls.TITLE)
                row.set_child(hbox(img, nav_title, badge, spacing=12))
                row.set_tooltip_text(getattr(cls, "SUBTITLE", "") or None)
                row._pid = pid
                lb.append(row)
                self.rows[pid] = row
                self.badges[pid] = badge
            side_box.append(lb)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(side_box)
        sw.set_vexpand(True)
        self.status_card = self._status_card()
        body = vbox(sw, self.status_card, spacing=0)
        body.add_css_class("side-body")
        side_tv.set_content(body)
        self.sidebar_revealer = Gtk.Revealer()
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.sidebar_revealer.set_child(side_tv)
        self.sidebar_revealer.set_size_request(SIDEBAR_MIN, -1)
        self.sidebar_revealer.set_reveal_child(self._sidebar_visible)
        self.sidebar_revealer.set_visible(self._sidebar_visible)
        self.split.set_start_child(self.sidebar_revealer)

        # ---------- content
        self.content_tv = Adw.ToolbarView()
        self.content_hb = Adw.HeaderBar()
        self.content_hb.add_css_class("main-header")
        self.sidebar_btn = Gtk.Button(icon_name="sidebar-hide-symbolic" if self._sidebar_visible else "sidebar-show-symbolic",
                                      tooltip_text=("Hide sidebar (Ctrl+Shift+S)" if self._sidebar_visible else "Show sidebar (Ctrl+Shift+S)"))
        self.sidebar_btn.add_css_class("flat")
        self.sidebar_btn.connect("clicked", lambda *_: self.toggle_sidebar())
        self.content_hb.pack_start(self.sidebar_btn)
        self.search_shell = self._search_box()
        self.content_hb.set_title_widget(self.search_shell)
        self.search_compact_btn = Gtk.Button(icon_name="system-search-symbolic", tooltip_text="Search pages and actions (Ctrl+K)")
        self.search_compact_btn.add_css_class("flat")
        self.search_compact_btn.set_visible(False)
        self.search_compact_btn.connect("clicked", lambda *_: self.palette())
        self.content_hb.pack_start(self.search_compact_btn)
        self.task_badge = label("", "nav-badge", xalign=0.5)
        self.task_badge.set_visible(False)
        self.task_btn = Gtk.Button(tooltip_text="Background tasks")
        self.task_btn.set_child(hbox(Gtk.Image.new_from_icon_name("system-run-symbolic"), self.task_badge, spacing=5))
        self.task_btn.add_css_class("flat")
        self.task_btn.connect("clicked", lambda *_: self.task_center())
        self.content_hb.pack_end(self.task_btn)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh (F5)")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_current())
        self.content_hb.pack_end(self.refresh_btn)
        self._header_extra: list[Gtk.Widget] = []
        self.content_tv.add_top_bar(self.content_hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180,
                               hhomogeneous=False, vhomogeneous=False)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)
        self.content_tv.set_content(self.toasts)
        self.split.set_end_child(self.content_tv)
        self._sidebar_clamping = False
        self.split.connect("notify::position", self._sidebar_resized)
        self.connect("notify::width", self._sidebar_resized)
        self.connect("notify::width", self._adapt_shell)

        for _section, ids in SECTIONS:
            for pid in ids:
                cls = classes.get(pid)
                if cls is None:
                    exc, trace = import_errors[pid]
                    page = _UnavailablePage(self, pid, self.classes[pid], exc, trace)
                else:
                    try:
                        page = cls(self)
                    except Exception as exc:  # noqa: BLE001
                        import traceback
                        trace = traceback.format_exc()
                        traceback.print_exc()
                        debug.exception(f"page construction failed: {pid}", exc)
                        page = _UnavailablePage(self, pid, cls, exc, trace)
                self.pages[pid] = page
                self.stack.add_named(page, pid)

        self.set_content(self.split)
        self.split.set_position(self._sidebar_width if self._sidebar_visible else 0)
        self.apply_motion()
        GLib.idle_add(lambda: (self._adapt_shell(), False)[1])

        self._actions()
        w, h = prefs.get("width"), prefs.get("height")
        if w and h:
            self.set_default_size(max(760, w), max(520, h))
        if prefs.get("maximized"):
            self.maximize()
        if not start:
            sp = prefs.get("start_page")
            start = prefs.get("page", "dashboard") if sp == "last" else sp
        self.goto(start if start in self.pages else "dashboard")
        self.connect("close-request", self._save_state)
        theme.on_change(lambda _dark: theme.redraw_tree(self))
        self._hidden = False
        self.connect("realize", self._watch_surface)
        GLib.timeout_add_seconds(2, lambda: (self.refresh_badges(), False)[1])
        GLib.timeout_add_seconds(1, lambda: (self._update_status_card(), False)[1])
        GLib.timeout_add_seconds(20, lambda: (self._update_status_card(), True)[1])
        GLib.timeout_add_seconds(600, lambda: (self.refresh_badges(), True)[1])
        GLib.timeout_add(700, self._update_task_badge)

    def _save_state(self, *_a) -> bool:
        if getattr(self, "search_pop", None) is not None and self.search_pop.get_parent() is not None:
            self.search_pop.unparent()
        w, h = self.get_default_size()
        if self._sidebar_visible and self.split.get_position() > 120:
            self._sidebar_width = self.split.get_position()
        prefs.update(width=w, height=h, maximized=self.is_maximized(), page=self.current,
                     sidebar_visible=self._sidebar_visible, sidebar_width=self._sidebar_width)
        return False

    # ---------------------------------------------------------------- window chrome
    def motion_ms(self) -> int:
        return {"full": 180, "reduced": 90, "off": 0}.get(prefs.get("motion", "full"), 180)

    def apply_motion(self) -> None:
        ms = self.motion_ms()
        self.stack.set_transition_duration(ms)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE if not ms else Gtk.StackTransitionType.CROSSFADE)
        self.sidebar_revealer.set_transition_duration(ms)
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.NONE if not ms else Gtk.RevealerTransitionType.CROSSFADE)

    def _sidebar_resized(self, *_a) -> None:
        """Keep the sidebar useful without letting it dominate the application.

        The width preference can come from an older release or a differently
        scaled monitor, so always clamp it against both an absolute range and
        the window's current content budget.
        """
        if not self._sidebar_visible or self._sidebar_clamping:
            return
        pos = self.split.get_position()
        width = self.get_width()
        if width <= 0:
            max_width = SIDEBAR_MAX
        else:
            # Never allow navigation to consume more than ~28% of the real
            # window width, and preserve a useful content viewport. This makes
            # the splitter behave sensibly on 1366x768 / fractional-scale
            # laptops instead of using a desktop-sized fixed allowance.
            proportional = int(width * 0.28)
            content_limited = width - CONTENT_MIN_WHILE_SIDEBAR_VISIBLE
            max_width = max(SIDEBAR_MIN, min(SIDEBAR_MAX, proportional, content_limited))
        clamped = max(SIDEBAR_MIN, min(max_width, pos))
        if clamped != pos:
            self._sidebar_clamping = True
            self.split.set_position(clamped)
            self._sidebar_clamping = False
        self._sidebar_width = clamped

    def _adapt_shell(self, *_a) -> None:
        """Keep global header controls usable when the content pane is narrow.

        Adw.HeaderBar may otherwise squeeze its title widget until the search
        entry effectively disappears. At compact content widths we replace the
        wide search field with an explicit search button; Ctrl+K remains
        available in both modes.
        """
        width = self.get_width()
        if width <= 0:
            return
        side = self.split.get_position() if self._sidebar_visible else 0
        content_width = max(0, width - side)
        compact = content_width < COMPACT_HEADER_AT
        if getattr(self, "search_shell", None) is not None:
            self.search_shell.set_visible(not compact)
        if getattr(self, "search_compact_btn", None) is not None:
            self.search_compact_btn.set_visible(compact)

    def toggle_sidebar(self) -> None:
        self.set_sidebar_visible(not self._sidebar_visible)

    def set_sidebar_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._sidebar_visible:
            return
        if not visible and self.split.get_position() > 120:
            self._sidebar_width = self.split.get_position()
        self._sidebar_visible = visible
        prefs.set("sidebar_visible", visible)
        self.sidebar_btn.set_icon_name("sidebar-hide-symbolic" if visible else "sidebar-show-symbolic")
        self.sidebar_btn.set_tooltip_text(("Hide" if visible else "Show") + " sidebar (Ctrl+Shift+S)")
        ms = self.motion_ms()
        if visible:
            self.sidebar_revealer.set_visible(True)
            self.split.set_position(max(SIDEBAR_MIN, min(SIDEBAR_MAX, self._sidebar_width)))
            self.sidebar_revealer.set_reveal_child(True)
        else:
            self.sidebar_revealer.set_reveal_child(False)

            def finish_hide() -> bool:
                if not self._sidebar_visible:
                    self.sidebar_revealer.set_visible(False)
                    self.split.set_position(0)
                return False
            GLib.timeout_add(max(1, ms + 20), finish_hide)
        self._adapt_shell()
        debug.event("ui.sidebar", visible=visible, width=self._sidebar_width)

    def _update_task_badge(self) -> bool:
        n = tasks.active_count()
        self.task_badge.set_text(str(n) if n < 100 else "99+")
        self.task_badge.set_visible(n > 0)
        self.task_btn.set_tooltip_text(f"Background tasks ({n} running)" if n else "Background tasks")
        return True

    # ---------------------------------------------------------------- sidebar extras
    QUICK = [("cleanup:scan", "Scan for junk", "edit-clear-all-symbolic"), ("updates:all", "Update everything", "software-update-available-symbolic"),
             ("maintenance:fix-slow", "Why is my PC slow?", "power-profile-performance-symbolic"),
             ("maintenance:tune", "One-click tune-up", "starred-symbolic"), ("page:maintenance", "Fix a problem…", "applications-engineering-symbolic"),
             ("storage:big", "Find big files", "drive-harddisk-symbolic"), ("network:speed", "Internet speed test", "network-wireless-symbolic"),
             ("maintenance:report", "Create a system report", "x-office-document-symbolic")]

    def _quick_button(self) -> Gtk.Widget:
        """The big button at the top of the sidebar: the things people come here to do, one click away."""
        pop = Gtk.Popover()
        pop.add_css_class("ctx")
        pop.set_has_arrow(False)
        box = vbox(spacing=1)
        for key, text, icon in self.QUICK:
            inner = hbox(Gtk.Image.new_from_icon_name(icon), label(text, hexpand=True), spacing=12)
            b = Gtk.Button()
            b.set_child(inner)
            b.add_css_class("flat")
            b.add_css_class("ctx-item")
            b.connect("clicked", lambda _b, k=key: (pop.popdown(), self.run_action(k)))
            box.append(b)
        box.set_size_request(230, -1)
        pop.set_child(box)
        mb = Gtk.MenuButton(popover=pop)
        mb.set_child(hbox(Gtk.Image.new_from_icon_name("list-add-symbolic"), label("Quick actions"), spacing=10))
        mb.add_css_class("quick-btn")
        mb.set_halign(Gtk.Align.FILL)
        mb.set_hexpand(True)
        mb.set_tooltip_text("Scan, update, fix and more")
        return mb

    def _status_card(self) -> Gtk.Widget:
        from .widgets import MiniBar
        self.sc_title = label("This PC", "side-card-title", hexpand=True)
        self.sc_score = label("", "pill")
        self.sc_disk = label("Main disk", "side-card-sub", wrap=True)
        self.sc_bar = MiniBar(height=6, warn=80, crit=90)
        self.sc_mem = label("", "side-card-sub", wrap=True)
        btn = Gtk.Button(label="Free up space →")
        btn.add_css_class("flat")
        btn.add_css_class("side-link")
        btn.connect("clicked", lambda *_: self.goto("cleanup"))
        self.sc_mem.set_hexpand(True)
        btn.set_halign(Gtk.Align.START)
        box = vbox(hbox(self.sc_title, self.sc_score, spacing=6), self.sc_disk, self.sc_bar, self.sc_mem, btn, spacing=5)
        box.add_css_class("side-card")
        return box

    def _update_status_card(self) -> None:
        import psutil
        try:
            root = next((m for m in system.mounts() if m.mountpoint == "/"), None)
            vm = psutil.virtual_memory()
        except Exception:  # noqa: BLE001
            return
        from ..core.fmt import human
        if root:
            self.sc_disk.set_text(f"Main disk · {human(root.free)} free of {human(root.total)}")
            self.sc_bar.set(root.pct / 100)
        self.sc_mem.set_text(f"Memory {vm.percent:.0f}%")
        score = getattr(self, "_last_score", None)
        if score is not None:
            self.sc_score.set_text(f"Health {score}")
            for c in ("pill-ok", "pill-warn", "pill-bad"):
                self.sc_score.remove_css_class(c)
            self.sc_score.add_css_class("pill-ok" if score >= 85 else "pill-warn" if score >= 60 else "pill-bad")
        self.sc_score.set_visible(score is not None)

    def set_health(self, score: int) -> None:
        self._last_score = score
        self._update_status_card()

    # ---------------------------------------------------------------- search in the header
    def _search_box(self) -> Gtk.Widget:
        """A wide search field in the header: finds pages, actions and single settings as you type."""
        self.search = Gtk.SearchEntry(placeholder_text="Search pages, actions and settings…   Ctrl+K")
        self.search.add_css_class("top-search")
        self.search.set_hexpand(True)
        self.search.set_size_request(160, -1)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=400)
        clamp.set_child(self.search)
        clamp.set_hexpand(True)
        self.results = Gtk.ListBox()
        self.results.add_css_class("search-results")
        self.results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results.set_can_focus(False)
        self.results.connect("row-activated", lambda _l, r: self._search_pick(r))
        box = vbox(label("", "search-hint"), self.results, spacing=2)
        self.search_hint = box.get_first_child()
        self.search_pop = Gtk.Popover()
        self.search_pop.add_css_class("search-pop")
        self.search_pop.set_has_arrow(False)
        self.search_pop.set_autohide(False)
        self.search_pop.set_can_focus(False)
        self.search_pop.set_position(Gtk.PositionType.BOTTOM)
        self.search_pop.set_child(box)
        self.search_pop.set_parent(self.search)
        self.search.connect("search-changed", lambda *_: self._search_update())
        self.search.connect("activate", lambda *_: self._search_pick(self.results.get_selected_row() or self.results.get_row_at_index(0)))
        self.search.connect("stop-search", lambda *_: self._search_close())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._search_keys)
        self.search.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: GLib.timeout_add(150, lambda: (self._search_close(clear=False), False)[1]))
        self.search.add_controller(focus)
        return clamp

    def _search_rows(self) -> list[tuple[str, str, str, str]]:
        """(key, title, subtitle, icon) for everything searchable."""
        if getattr(self, "_search_cache", None) is None:
            rows = [(f"page:{pid}", self.classes[pid].TITLE, self.classes[pid].SUBTITLE, self.classes[pid].ICON)
                    for _, ids in SECTIONS for pid in ids if pid in self.pages]
            icon_of = {pid: self.classes[pid].ICON for pid in self.pages}
            rows += [(k, t, sub, icon_of.get(k.split(":")[0], "preferences-system-symbolic"))
                     for k, t, sub in all_actions({pid: self.classes[pid] for pid in self.pages})]
            rows += [(k, t, sub, icon_of.get(k.split(":")[1], "emblem-system-symbolic")) for k, t, sub in self.extra_palette_rows()]
            self._search_cache = rows
        return self._search_cache

    def _search_update(self) -> None:
        q = self.search.get_text().strip().lower()
        while (r := self.results.get_row_at_index(0)) is not None:
            self.results.remove(r)
        if not q:
            self.search_pop.popdown()
            return
        words = q.split()
        hits = []
        for key, title, sub, icon in self._search_rows():
            hay = f"{title} {sub}".lower()
            if all(w in hay for w in words):
                rank = (0 if title.lower().startswith(words[0]) else 1 if words[0] in title.lower() else 2, 0 if key.startswith("page:") else 1)
                hits.append((rank, key, title, sub, icon))
        hits.sort(key=lambda h: h[0])
        for _rank, key, title, sub, icon in hits[:9]:
            kind = "Page" if key.startswith("page:") else "Setting" if key.startswith("setting:") else "Action"
            text = vbox(label(title, "heading" if kind == "Page" else None, hexpand=True), label(sub, "dim", wrap=False), spacing=0)
            text.get_last_child().set_ellipsize(Pango.EllipsizeMode.END)
            row = Gtk.ListBoxRow()
            row.set_can_focus(False)
            row.set_child(hbox(Gtk.Image.new_from_icon_name(icon), text, label(kind, "result-kind"), spacing=12))
            row._key = key
            self.results.append(row)
        self.search_hint.set_text(f"{len(hits)} result{'s' if len(hits) != 1 else ''} · Enter to open · ↑↓ to choose" if hits
                                  else "Nothing found. Try another word, e.g. “clean”, “battery”, “ports”.")
        if hits:
            self.results.select_row(self.results.get_row_at_index(0))
        # Keep the results inside compact windows / a wide resized sidebar.
        root_w = self.get_width() or 760
        w = max(300, min(620, self.search.get_width(), root_w - 48))
        self.search_pop.set_size_request(w, -1)
        self.search_pop.popup()

    def _search_keys(self, _c, keyval, _code, _state) -> bool:
        from gi.repository import Gdk as _Gdk
        if keyval in (_Gdk.KEY_Down, _Gdk.KEY_Up):
            cur = self.results.get_selected_row()
            i = cur.get_index() if cur else -1
            nxt = self.results.get_row_at_index(i + (1 if keyval == _Gdk.KEY_Down else -1))
            if nxt is not None:
                self.results.select_row(nxt)
            return True
        return False

    def _search_pick(self, row) -> None:
        if row is None or not hasattr(row, "_key"):
            return
        key = row._key
        self._search_close()
        self.run_action(key)

    def _search_close(self, clear: bool = True) -> None:
        self.search_pop.popdown()
        if clear:
            self.search.set_text("")

    # ---------------------------------------------------------------- pause while hidden
    def _watch_surface(self, *_a) -> None:
        surface = self.get_surface()
        if surface is not None:
            surface.connect("notify::state", self._surface_state)

    def _surface_state(self, surface, _p) -> None:
        st = surface.get_state()
        hidden_flags = Gdk.ToplevelState.MINIMIZED
        if hasattr(Gdk.ToplevelState, "SUSPENDED"):  # GTK 4.12+: compositor says the window can't be seen
            hidden_flags |= Gdk.ToplevelState.SUSPENDED
        hidden = bool(st & hidden_flags)
        if hidden == self._hidden or not prefs.get("pause_hidden"):
            return
        self._hidden = hidden
        page = self.pages.get(self.current)
        if page is None:
            return
        if hidden:
            page.deactivate()
        else:
            page.activate()

    def restart_timers(self) -> None:
        page = self.pages.get(self.current)
        if page is not None:
            page.deactivate()
            page.activate()

    def sync_appearance_action(self, mode: str) -> None:
        a = self.lookup_action("appearance")
        if a is not None:
            a.set_state(GLib.Variant("s", mode))

    # ---------------------------------------------------------------- navigation
    def _row_activated(self, _lb, row) -> None:
        self.goto(row._pid)

    def goto(self, pid: str) -> None:
        if pid not in self.pages:
            return
        debug.event("ui.navigate", from_page=self.current or "", to_page=pid)
        if self.current and self.current != pid:
            self.pages[self.current].deactivate()
        self.current = pid
        page = self.pages[pid]
        self.stack.set_visible_child_name(pid)
        self.set_title(f"{page.TITLE} · PC Command Center")
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
        add("preferences", self.preferences, ["<Control>comma"])
        add("activity", self.activity, ["<Control>h"])
        add("tasks", self.task_center, ["<Control><Shift>t"])
        add("sidebar", self.toggle_sidebar, ["<Control><Shift>s"])
        mode = prefs.get("appearance")
        app_action = Gio.SimpleAction.new_stateful("appearance", GLib.VariantType.new("s"), GLib.Variant("s", mode))

        def set_mode(action, value) -> None:
            action.set_state(value)
            prefs.set("appearance", value.get_string())
            theme.set_mode(value.get_string())
        app_action.connect("change-state", set_mode)
        self.add_action(app_action)

    def preferences(self) -> None:
        from .preferences import PreferencesDialog
        PreferencesDialog(self).present(self)

    def activity(self) -> None:
        from .dialogs import ActivityDialog
        ActivityDialog().present(self)

    def task_center(self) -> None:
        from .taskcenter import TaskCenterDialog
        TaskCenterDialog(self).present(self)

    def welcome(self) -> None:
        from .welcome import WelcomeDialog
        WelcomeDialog(self).present(self)

    def palette(self) -> None:
        """Ctrl+K: jump to any page or run a common action by typing (the search field in the header)."""
        if getattr(self, "search", None) is not None and self.search.get_mapped():
            self.search.grab_focus()
            return
        self.palette_dialog()

    def palette_dialog(self) -> None:
        from .dialogs import ChoiceDialog
        rows = [(f"page:{pid}", self.classes[pid].TITLE, "Go to page") for _, ids in SECTIONS for pid in ids if pid in self.pages]
        rows += all_actions({pid: self.classes[pid] for pid in self.pages})
        rows += self.extra_palette_rows()
        ChoiceDialog("Go to or do…", rows, self._palette_pick, explain="Type to filter. Tip: Ctrl+K opens this from anywhere.").present(self)

    def run_action(self, key: str) -> None:
        """Run a palette action by key (used by --action from GNOME search and the dock menu)."""
        debug.event("ui.action", key=key)
        self._palette_pick(key)

    def _palette_pick(self, key: str | None) -> None:
        if not key:
            return
        kind, _, what = key.partition(":")
        if kind == "page":
            self.goto(what)
            return
        if kind == "app":
            if what == "palette":
                self.palette()
            elif what == "welcome":
                self.welcome()
            elif what == "preferences":
                self.preferences()
            elif what == "activity":
                self.activity()
            elif what == "tasks":
                self.task_center()
            else:
                self.lookup_action("appearance").change_state(GLib.Variant("s", what))
            return
        if kind == "setting":
            page_id, _, name = what.partition(":")
            self.goto(page_id)
            self.toast(f"“{name}” is on this page.")
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
            elif hasattr(page, "palette_action"):
                page.palette_action(key.partition(":")[2])
            return False
        GLib.timeout_add(250, later)

    def extra_palette_rows(self) -> list[tuple[str, str, str]]:
        return [r for r in setting_rows() if r[0].split(":")[1] in self.pages]

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
        lines += ["", "  Ctrl+K       Go to a page or run an action by typing", "  Ctrl+,       Preferences",
                  "  Ctrl+H       Activity history", "  Ctrl+Shift+T Background tasks", "  Ctrl+Shift+S Show/hide sidebar",
                  "  F5 / Ctrl+R  Refresh this page",
                  "  Ctrl+F       Search (on pages with a search box)", "  Ctrl+Q       Quit",
                  "  Double-click / Enter on a row opens its details"]
        show_text(self, "Keyboard shortcuts", "\n".join(lines))


def load_css() -> None:
    """Kept for older callers; the theme module owns the stylesheet now."""
    theme.setup(prefs.get("appearance"))
