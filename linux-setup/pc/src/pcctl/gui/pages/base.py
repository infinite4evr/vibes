"""Base class for every page in the app."""

from __future__ import annotations

from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core.run import Step  # noqa: E402
from .. import dialogs  # noqa: E402
from ..util import bg, button, clear, hbox, label, scrolled, spacer, vbox  # noqa: E402


class Page(Gtk.Box):
    ID = ""
    TITLE = ""
    ICON = "applications-system-symbolic"
    SECTION = ""
    SUBTITLE = ""
    AUTO_REFRESH = 0      # seconds, only while visible
    CLAMP: int | None = 1240
    SCROLL = True         # wrap content in a scrolled window

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.loaded = False
        self._timer = None
        self.header_widgets: list[Gtk.Widget] = []
        self.body = vbox(spacing=18)
        self.body.set_margin_top(20)
        self.body.set_margin_bottom(28)
        self.body.set_margin_start(24)
        self.body.set_margin_end(24)
        if self.SCROLL:
            self.append(scrolled(self.body, self.CLAMP))
        else:
            self.body.set_vexpand(True)
            self.append(self.body)
        self.build()

    # -- lifecycle
    def build(self) -> None:
        pass

    def load(self) -> None:
        pass

    def tick(self) -> bool:
        return True

    def reload(self) -> None:
        self.load()

    def activate(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.load()
        if self.AUTO_REFRESH and self._timer is None:
            self._timer = GLib.timeout_add(int(self.AUTO_REFRESH * 1000), self._tick)

    def deactivate(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        try:
            self.tick()
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
        return True

    # -- helpers
    def header(self, subtitle: str | None = None, *actions: Gtk.Widget) -> Gtk.Box:
        """Big title + subtitle + right-aligned actions."""
        t = vbox(label(self.TITLE, "page-title"), label(subtitle if subtitle is not None else self.SUBTITLE, ["page-sub"], wrap=True), spacing=2)
        t.set_hexpand(True)
        row = hbox(t, *actions, spacing=8)
        for a in actions:
            a.set_valign(Gtk.Align.CENTER)
        self.body.append(row)
        return row

    def bg(self, fn: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        bg(fn, done, error=lambda e: self.toast(f"Error: {e}"))

    def toast(self, text: str, timeout: int = 3) -> None:
        self.win.toast(text, timeout)

    def run(self, title: str, steps: list[Step], explain: str = "", danger: bool = False, ok_label: str = "Run",
            reload: bool = True, done: Callable[[bool], None] | None = None, ask: bool = True) -> None:
        def finished(ok: bool) -> None:
            if ok and reload:
                self.reload()
            if done:
                done(ok)
            self.win.refresh_badges()
        dialogs.run_steps(self.win, title, steps, explain, danger, ok_label, finished, ask)

    def run_make(self, title: str, make: Callable[[], list[Step]], explain: str = "", **kw) -> None:
        self.bg(make, lambda steps: self.run(title, steps, explain, **kw))

    def text(self, title: str, text: str) -> None:
        dialogs.show_text(self.win, title, text)

    def loading(self, box: Gtk.Box, text: str = "Loading…") -> None:
        clear(box)
        sp = Gtk.Spinner()
        sp.start()
        row = hbox(sp, label(text, "dim"))
        row.set_margin_top(12)
        row.set_margin_bottom(12)
        box.append(row)


def group(title: str = "", description: str = "", *rows: Gtk.Widget, suffix: Gtk.Widget | None = None) -> Adw.PreferencesGroup:
    g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title), description=GLib.markup_escape_text(description))
    if suffix is not None:
        g.set_header_suffix(suffix)
    for r in rows:
        g.add(r)
    return g


def action_row(title: str, subtitle: str = "", *suffixes: Gtk.Widget, prefix: Gtk.Widget | None = None,
               on_activate: Callable | None = None) -> Adw.ActionRow:
    from gi.repository import GLib as _G
    r = Adw.ActionRow(title=_G.markup_escape_text(title), subtitle=_G.markup_escape_text(subtitle))
    r.set_subtitle_lines(3)
    if prefix is not None:
        r.add_prefix(prefix)
    for s in suffixes:
        s.set_valign(Gtk.Align.CENTER)
        r.add_suffix(s)
    if on_activate:
        r.set_activatable(True)
        r.connect("activated", lambda *_: on_activate())
    return r


def tabs(*pages: tuple[str, str, str, Gtk.Widget]) -> tuple[Gtk.Widget, Adw.ViewStack]:
    """(name, title, icon, child) -> (switcher, stack). Use stack.get_page(child) to set badges."""
    stack = Adw.ViewStack()
    stack.set_vhomogeneous(False)
    stack.set_hhomogeneous(False)
    for name, title, icon, child in pages:
        stack.add_titled_with_icon(child, name, title, icon)
    sw = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
    sw.set_halign(Gtk.Align.START)
    sw.add_css_class("page-tabs")
    return sw, stack


def boxed_list() -> Gtk.ListBox:
    lb = Gtk.ListBox()
    lb.add_css_class("boxed-list")
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    return lb


def switch_row(title: str, subtitle: str, active: bool, on_change: Callable[[bool, Callable[[bool], None]], None]) -> Adw.SwitchRow:
    """A switch that asks on_change(new_state, revert) - call revert(ok) when done; if not ok the switch flips back."""
    from gi.repository import GLib as _G
    row = Adw.SwitchRow(title=_G.markup_escape_text(title), subtitle=_G.markup_escape_text(subtitle))
    row.set_active(active)
    row._guard = False

    def changed(r, _p) -> None:
        if r._guard:
            return
        new = r.get_active()

        def settle(ok: bool) -> None:
            if not ok:
                r._guard = True
                r.set_active(not new)
                r._guard = False
        on_change(new, settle)
    row.connect("notify::active", changed)
    return row


def set_switch_quiet(row: Adw.SwitchRow, active: bool) -> None:
    row._guard = True
    row.set_active(active)
    row._guard = False


def banner(text: str, kind: str = "warn", *buttons: Gtk.Widget, icon: str | None = None) -> Gtk.Box:
    icons = {"warn": "dialog-warning-symbolic", "bad": "dialog-error-symbolic", "ok": "emblem-ok-symbolic", "info": "dialog-information-symbolic"}
    img = Gtk.Image.new_from_icon_name(icon or icons.get(kind, icons["info"]))
    img.add_css_class(f"lvl-{kind}")
    lb = label(text, None, wrap=True, hexpand=True)
    b = hbox(img, lb, *buttons, spacing=12, css=f"banner-{kind if kind in ('warn', 'bad', 'ok') else 'warn'}")
    for w in buttons:
        w.set_valign(Gtk.Align.CENTER)
    b._label = lb
    return b


def stat(value: str, name: str, css: str | None = None) -> Gtk.Box:
    v = label(value, ["stat-num"] + ([css] if css else []))
    b = vbox(v, label(name.upper(), "stat-label"), spacing=0)
    b._value = v
    return b


def toolbar(*widgets: Gtk.Widget) -> Gtk.Box:
    b = hbox(*widgets, spacing=8, css="toolbar-row")
    return b


def small_button(text: str, on_click: Callable, css: str | None = None, icon: str | None = None, tooltip: str = "") -> Gtk.Button:
    b = button(text, icon=icon, css=css, tooltip=tooltip)
    b.connect("clicked", lambda *_: on_click())
    return b


__all__ = ["Page", "group", "action_row", "toolbar", "small_button", "tabs", "boxed_list", "banner", "stat", "switch_row", "set_switch_quiet", "spacer", "clear", "hbox", "vbox", "label", "button"]
