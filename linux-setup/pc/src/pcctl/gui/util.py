"""GTK helpers: background work, small widget builders, formatting."""

from __future__ import annotations

import subprocess
import threading
import traceback
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from ..core.run import which  # noqa: E402


def esc(s: Any) -> str:
    return GLib.markup_escape_text(str(s))


def bg(fn: Callable[[], Any], done: Callable[[Any], None] | None = None, error: Callable[[Exception], None] | None = None) -> None:
    """Run fn in a thread; deliver its result to done() on the GTK main loop."""

    def work() -> None:
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001
            if error is None:  # unexpected: keep a record. Expected failures are handled by the caller's error callback.
                traceback.print_exc()
                try:
                    from .activity import log_error
                    log_error(traceback.format_exc())
                except Exception:  # noqa: BLE001
                    pass
            err = e  # `e` is cleared when the except block ends; keep our own reference for the callback
            if error:
                GLib.idle_add(lambda: (error(err), False)[1])
            return
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])

    threading.Thread(target=work, daemon=True).start()


def idle(fn: Callable, *args) -> None:
    GLib.idle_add(lambda: (fn(*args), False)[1])


def label(text: str = "", css: str | list[str] | None = None, xalign: float = 0.0, wrap: bool = False, markup: bool = False,
          ellipsize: bool = False, selectable: bool = False, hexpand: bool = False, lines: int = 0) -> Gtk.Label:
    lb = Gtk.Label(xalign=xalign)
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    if wrap:
        lb.set_wrap(True)
        lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    if lines:
        lb.set_lines(lines)
    if selectable:
        lb.set_selectable(True)
    lb.set_hexpand(hexpand)
    for c in ([css] if isinstance(css, str) else (css or [])):
        lb.add_css_class(c)
    return lb


def button(text: str = "", icon: str | None = None, css: str | list[str] | None = None, tooltip: str = "",
           on_click: Callable | None = None) -> Gtk.Button:
    if icon and text:
        b = Gtk.Button()
        content = Adw.ButtonContent(icon_name=icon, label=text)
        b.set_child(content)
    elif icon:
        b = Gtk.Button(icon_name=icon)
    else:
        b = Gtk.Button(label=text)
    for c in ([css] if isinstance(css, str) else (css or [])):
        b.add_css_class(c)
    if tooltip:
        b.set_tooltip_text(tooltip)
        if icon and not text:  # screen readers read this instead of the icon name
            b.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b


def hbox(*children: Gtk.Widget, spacing: int = 8, css: str | None = None, homogeneous: bool = False) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, homogeneous=homogeneous)
    for c in children:
        if c is not None:
            b.append(c)
    if css:
        b.add_css_class(css)
    return b


def vbox(*children: Gtk.Widget, spacing: int = 8, css: str | None = None) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in children:
        if c is not None:
            b.append(c)
    if css:
        b.add_css_class(css)
    return b


def flow(*children: Gtk.Widget, spacing: int = 12, min_per_line: int = 1, max_per_line: int = 0, homogeneous: bool = False) -> Gtk.FlowBox:
    """A row that wraps onto more lines when the window is narrow."""
    f = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=homogeneous, column_spacing=spacing, row_spacing=spacing,
                    min_children_per_line=min_per_line, max_children_per_line=max_per_line or max(1, len(children)))
    for c in children:
        f.append(c)
    c = f.get_first_child()
    while c is not None:
        c.set_focusable(False)
        c = c.get_next_sibling()
    return f


def clear(box: Gtk.Widget) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def spacer() -> Gtk.Box:
    b = Gtk.Box()
    b.set_hexpand(True)
    return b


def scrolled(child: Gtk.Widget, clamp: int | None = 1180) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_vexpand(True)
    if clamp:
        c = Adw.Clamp(maximum_size=clamp, tightening_threshold=clamp - 200)
        c.set_child(child)
        sw.set_child(c)
    else:
        sw.set_child(child)
    return sw


def launch(args: list[str]) -> None:
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        pass


def open_path(path: str) -> None:
    launch(["xdg-open", path])


def open_in_terminal(cmd: list[str]) -> bool:
    """Run an interactive command in the user's terminal (Ghostty, Ptyxis, GNOME Terminal…)."""
    for term, args in (("ghostty", ["-e"]), ("ptyxis", ["--"]), ("gnome-terminal", ["--"]), ("kgx", ["--"]),
                       ("x-terminal-emulator", ["-e"]), ("xdg-terminal-exec", [])):
        path = which(term)
        if path:
            wrapped = ["bash", "-c", " ".join(_q(c) for c in cmd) + "; echo; read -rp 'Press Enter to close…'"]
            launch([path, *args, *wrapped])
            return True
    return False


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def status_icon(level: str) -> Gtk.Image:
    names = {"ok": "emblem-ok-symbolic", "info": "dialog-information-symbolic", "warn": "dialog-warning-symbolic", "bad": "dialog-error-symbolic"}
    img = Gtk.Image.new_from_icon_name(names.get(level, "dialog-information-symbolic"))
    img.add_css_class(f"lvl-{level}")
    return img


def pill(text: str, kind: str = "neutral") -> Gtk.Label:
    lb = label(text, ["pill", f"pill-{kind}"])
    lb.set_valign(Gtk.Align.CENTER)
    return lb
