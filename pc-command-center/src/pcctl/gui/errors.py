"""The error dialog: every unexpected error in the desktop app ends up here.

It shows what went wrong in one line, the exact (redacted) text that would be
posted, and one click to open a pre-filled GitHub issue. Repeats of the same
error are folded into the open dialog instead of stacking pop-ups.
"""

from __future__ import annotations

import time
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..core import bugreport, debug  # noqa: E402
from .util import button, hbox, label, spacer, vbox  # noqa: E402

REPEAT_WINDOW = 120  # seconds: the same error again within this time doesn't open another dialog

_open: ErrorDialog | None = None
_recent: dict[str, float] = {}


def report_exception(exc: BaseException, where: str = "", context: str = "") -> None:
    report_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), where, context)


def report_text(error: str, where: str = "", context: str = "") -> None:
    """Show the error dialog for `error` (a traceback or a message). Safe to call from any thread."""
    if GLib.main_depth() == 0 or not _on_main_thread():
        GLib.idle_add(lambda: (_show(error, where, context), False)[1])
    else:
        _show(error, where, context)


def _on_main_thread() -> bool:
    import threading
    return threading.current_thread() is threading.main_thread()


def _show(error: str, where: str, context: str) -> None:
    global _open
    try:
        rep = bugreport.Report(error, where, context)
    except Exception as e:  # noqa: BLE001 - the error reporter must never raise
        debug.exception("building error report", e)
        return
    key = rep.title
    now = time.monotonic()
    if _open is not None:
        _open.add_repeat(rep)
        return
    if now - _recent.get(key, -1e9) < REPEAT_WINDOW:
        return
    _recent[key] = now
    _open = ErrorDialog(rep)
    _open.show_for(_parent())


def _parent() -> Gtk.Widget | None:
    app = Gio.Application.get_default()
    win = app.props.active_window if isinstance(app, Gtk.Application) else None
    if win is None and isinstance(app, Gtk.Application):
        wins = app.get_windows()
        win = wins[0] if wins else None
    return win


def open_uri(parent: Gtk.Widget | None, uri: str) -> None:
    root = parent.get_root() if parent is not None else None
    try:
        Gtk.UriLauncher.new(uri).launch(root if isinstance(root, Gtk.Window) else None, None, None, None)
    except (AttributeError, GLib.Error):  # GTK < 4.10
        Gio.AppInfo.launch_default_for_uri(uri, None)


class ErrorDialog(Adw.Dialog):
    def __init__(self, rep: bugreport.Report):
        super().__init__()
        self.rep = rep
        self.others: list[bugreport.Report] = []
        self.set_title("Something went wrong")
        self.set_content_width(620)
        # Natural height: compact while the details are collapsed, grows when expanded.
        self._window: Adw.Window | None = None

        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        body = vbox(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18 if side != "top" else 4)
        head = hbox(Gtk.Image.new_from_icon_name("dialog-error-symbolic"), label(rep.where, "heading", wrap=True, hexpand=True), spacing=10)
        body.append(head)
        body.append(label(bugreport.summary(rep.error), ["mono"], wrap=True, selectable=True))
        body.append(label("PC Command Center hit an error. Reporting it on GitHub opens a pre-filled issue in your browser; "
                          "you can read and edit everything before you submit. Names, your home folder, network addresses and "
                          "secrets are already removed.", ["dim"], wrap=True))
        self.repeats = label("", ["dim"], wrap=True)
        self.repeats.set_visible(False)
        body.append(self.repeats)

        exp = Gtk.Expander(label="What will be reported")
        self.buffer = Gtk.TextBuffer(text=rep.full_text())
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.add_css_class("log-view")
        view.set_left_margin(8)
        view.set_top_margin(6)
        sw = Gtk.ScrolledWindow(vexpand=True, min_content_height=240, max_content_height=420, propagate_natural_height=True)
        sw.set_child(view)
        exp.set_child(sw)
        body.append(exp)

        report = button("Report on GitHub", icon="mail-send-symbolic", css=["suggested-action", "pill"], on_click=self._report)
        copy = button("Copy details", icon="edit-copy-symbolic", css="pill", on_click=self._copy)
        save = button("Save full log", icon="document-save-symbolic", css="pill", on_click=self._save)
        close = button("Close", css="pill", on_click=self._close)
        close.set_valign(Gtk.Align.CENTER)
        row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8, max_children_per_line=4,
                          homogeneous=False)
        for b in (report, copy, save):
            row.append(b)
        row.set_valign(Gtk.Align.CENTER)
        body.append(hbox(row, spacer(), close))
        self.status = label("", ["dim"], wrap=True)
        body.append(self.status)
        tv.set_content(body)
        self.set_child(tv)
        self.connect("closed", lambda *_: _closed())
        GLib.idle_add(lambda: (report.grab_focus(), False)[1])

    # -- presentation: inside the main window when there is one, otherwise standalone (startup crash)
    def show_for(self, parent: Gtk.Widget | None) -> None:
        if parent is not None:
            self.present(parent)
            return
        win = Adw.Window(title=self.get_title(), default_width=620, default_height=520)
        app = Gio.Application.get_default()
        if isinstance(app, Gtk.Application):
            win.set_application(app)
        child = self.get_child()
        self.set_child(None)
        win.set_content(child)
        win.connect("close-request", lambda *_: (_closed(), False)[1])
        self._window = win
        win.present()

    def _close(self) -> None:
        if self._window is not None:
            self._window.close()
        else:
            self.close()

    def add_repeat(self, rep: bugreport.Report) -> None:
        if rep.title == self.rep.title or any(o.title == rep.title for o in self.others):
            return
        self.others.append(rep)
        self.repeats.set_text(f"{len(self.others)} more error{'s' if len(self.others) != 1 else ''} happened since; "
                              "they are included in the details below.")
        self.repeats.set_visible(True)
        self.buffer.set_text(self._text())

    def _text(self) -> str:
        parts = [self.rep.full_text()]
        for o in self.others:
            parts.append(f"\n\n---\n## Also: {o.title}\n\n```text\n{o.error}\n```")
        return "".join(parts)

    def _report(self) -> None:
        rep = self.rep
        if self.others:
            # Keep the link short: the extra errors are named, and the full text is one click away (Copy details).
            extra = "; ".join(o.title for o in self.others)[:500]
            rep = bugreport.Report.__new__(bugreport.Report)
            rep.__dict__.update(self.rep.__dict__)
            rep.context = (self.rep.context + "\n\n" if self.rep.context else "") + f"Also happened right after: {extra}"
        open_uri(self, rep.url())
        self.status.set_text("Opened GitHub in your browser. If the log was trimmed to fit the link, use “Copy details” and paste it into the issue.")

    def _copy(self) -> None:
        self.get_clipboard().set(self._text())
        self.status.set_text("Copied. Paste it into the GitHub issue (or anywhere else).")

    def _save(self) -> None:
        try:
            path = self.rep.save()
        except OSError as e:
            self.status.set_text(f"Couldn't save: {e}")
            return
        self.status.set_text(f"Saved to {str(path).replace(str(path.home()), '~')}")


def _closed() -> None:
    global _open
    _open = None
