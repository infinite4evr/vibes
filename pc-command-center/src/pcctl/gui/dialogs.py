"""Dialogs: confirm (shows exact commands), live task runner, text viewer, input, pick-items, choose-one."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core.run import Step, needs_root  # noqa: E402
from .runner import Runner  # noqa: E402
from .util import button, esc, hbox, label, spacer, vbox  # noqa: E402


def _commands_view(steps: list[Step]) -> Gtk.Widget:
    box = vbox(spacing=6)
    for s in steps:
        box.append(label(esc(s.title), "heading", markup=True, wrap=True))
        cmd = label(("$ " + s.display()), ["mono", "dim"], wrap=True, selectable=True)
        cmd.set_margin_start(10)
        box.append(cmd)
    frame = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    frame.set_max_content_height(260)
    frame.set_propagate_natural_height(True)
    inner = vbox(box, css="cmd-box")
    frame.set_child(inner)
    return frame


def confirm(parent: Gtk.Widget, title: str, steps: list[Step], explain: str = "", danger: bool = False, ok_label: str = "Run",
            on_done: Callable[[bool], None] | None = None) -> None:
    d = Adw.AlertDialog(heading=title, body=explain or "")
    if hasattr(d, "set_prefer_wide_layout"):  # libadwaita 1.6+
        d.set_prefer_wide_layout(True)
    extra = vbox(spacing=10)
    extra.append(_commands_view(steps))
    if needs_root(steps):
        extra.append(label("Ubuntu will ask for your password once.", ["warn-text"], wrap=True))
    d.set_extra_child(extra)
    d.add_response("cancel", "Cancel")
    d.add_response("run", ok_label)
    d.set_response_appearance("run", Adw.ResponseAppearance.DESTRUCTIVE if danger else Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("run")
    d.set_close_response("cancel")
    d.connect("response", lambda _d, r: on_done and on_done(r == "run"))
    d.present(parent)


class TaskDialog(Adw.Dialog):
    """Runs steps with a live log. Calls on_done(success) when closed."""

    def __init__(self, title: str, steps: list[Step], on_done: Callable[[bool], None] | None = None):
        super().__init__()
        self.set_title(title)
        self.set_content_width(760)
        self.set_content_height(560)
        self.steps, self.on_done_cb = steps, on_done
        self.success = False
        self.finished = False
        self._all_lines: list[str] = []
        import time as _t
        self._t0 = _t.monotonic()
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        body = vbox(spacing=12)
        body.set_margin_top(6)
        body.set_margin_bottom(14)
        body.set_margin_start(18)
        body.set_margin_end(18)
        self.step_rows: list[tuple[Gtk.Image, Gtk.Label, Gtk.Spinner]] = []
        steps_box = vbox(spacing=2)
        for s in steps:
            img = Gtk.Image.new_from_icon_name("content-loading-symbolic")
            img.add_css_class("dim")
            sp = Gtk.Spinner()
            sp.set_visible(False)
            lb = label(s.title, wrap=True, hexpand=True)
            steps_box.append(hbox(img, sp, lb, spacing=10, css="step-row"))
            self.step_rows.append((img, lb, sp))
        ssw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        ssw.set_max_content_height(160)
        ssw.set_propagate_natural_height(True)
        ssw.set_child(steps_box)
        body.append(ssw)
        self.progress = Gtk.ProgressBar()
        body.append(self.progress)
        self.buffer = Gtk.TextBuffer()
        self.view = Gtk.TextView(buffer=self.buffer, editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.add_css_class("log-view")
        self.view.set_left_margin(10)
        self.view.set_top_margin(8)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(self.view)
        self.sw = sw
        body.append(sw)
        self.result = label("", "heading", wrap=True)
        self.close_btn = button("Close", css="pill")
        self.close_btn.set_sensitive(False)
        self.close_btn.connect("clicked", lambda *_: self.close())
        self.bg_btn = button("Hide", icon="go-down-symbolic", css="pill", tooltip="Keep this running and manage it from Background tasks")
        self.bg_btn.connect("clicked", lambda *_: self.set_visible(False))
        self.stop_btn = button("Stop", css="pill")
        self.stop_btn.connect("clicked", lambda *_: self.runner.cancel())
        self.report_btn = button("Create GitHub issue", icon="mail-send-symbolic", css="pill",
                                 tooltip="Open a pre-filled GitHub issue with the (redacted) output", on_click=self._report)
        self.report_btn.set_visible(False)
        body.append(hbox(self.result, spacer(), self.report_btn, self.bg_btn, self.stop_btn, self.close_btn))
        tv.set_content(body)
        self.set_child(tv)
        self.set_can_close(False)
        self.connect("closed", lambda *_: self.on_done_cb and self.on_done_cb(self.success))
        self._lines = 0
        self.runner = Runner(steps, self._on_step, self._on_line, self._on_done, title=title)

    def start(self, parent: Gtk.Widget) -> None:
        self.present(parent)
        self.runner.start()
        GLib.timeout_add(120, self._pulse)

    def _pulse(self) -> bool:
        if self.finished:
            return False
        done = sum(1 for img, *_ in self.step_rows if img.get_icon_name() in ("emblem-ok-symbolic", "action-unavailable-symbolic"))
        if done:
            self.progress.set_fraction(done / max(1, len(self.step_rows)))
        else:
            self.progress.pulse()
        return True

    def _on_step(self, i: int, state: str, code) -> None:
        GLib.idle_add(self._set_step, i, state, code)

    def _set_step(self, i: int, state: str, code) -> bool:
        if i >= len(self.step_rows):
            return False
        img, lb, sp = self.step_rows[i]
        for c in ("dim", "lvl-ok", "lvl-bad", "lvl-warn"):
            img.remove_css_class(c)
        if state == "running":
            img.set_visible(False)
            sp.set_visible(True)
            sp.start()
            lb.add_css_class("heading")
        else:
            sp.stop()
            sp.set_visible(False)
            img.set_visible(True)
            lb.remove_css_class("heading")
            icon, css = {"ok": ("emblem-ok-symbolic", "lvl-ok"), "failed": ("dialog-error-symbolic", "lvl-bad"),
                         "skipped": ("action-unavailable-symbolic", "lvl-warn")}[state]
            img.set_from_icon_name(icon)
            img.add_css_class(css)
            if state != "ok" and code is not None:
                lb.set_text(f"{self.steps[i].title}  (exit {code}{', skipped' if state == 'skipped' else ''})")
        return False

    def _on_line(self, line: str) -> None:
        self._all_lines.append(line)
        if len(self._all_lines) > 2000:
            del self._all_lines[:500]
        GLib.idle_add(self._append, line)

    def _append(self, line: str) -> bool:
        if self._lines > 5000:
            start = self.buffer.get_start_iter()
            res = self.buffer.get_iter_at_line(1000)
            cut = res[1] if isinstance(res, tuple) else res
            self.buffer.delete(start, cut)
            self._lines -= 1000
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, line + "\n")
        self._lines += 1
        adj = self.sw.get_vadjustment()
        GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
        return False

    def _on_done(self, ok: bool, note: str) -> None:
        GLib.idle_add(self._finish, ok, note)

    def _finish(self, ok: bool, note: str) -> bool:
        self.finished = True
        self.success = ok
        self.progress.set_fraction(1.0 if ok else self.progress.get_fraction())
        self.result.set_text("Done ✓" if ok else (note or "Something went wrong - see the output above."))
        self.result.remove_css_class("heading")
        self.result.add_css_class("ok-text" if ok else "bad-text")
        self.close_btn.set_sensitive(True)
        self.close_btn.add_css_class("suggested-action")
        self.bg_btn.set_visible(False)
        self.stop_btn.set_visible(False)
        self.set_can_close(True)
        self.close_btn.grab_focus()
        self.report_btn.set_visible(not ok and not self.runner.cancelled)
        self._notify(ok, note)
        try:
            import time as _t

            from .activity import record
            record(self.get_title(), [s.display() for s in self.steps], ok, note, self._all_lines,
                   root=needs_root(self.steps), duration=_t.monotonic() - self._t0)
        except Exception:  # noqa: BLE001 - history is best effort
            pass
        return False

    def _report(self) -> None:
        from ..core import bugreport
        from .errors import open_uri
        failed = [s.title for (img, _lb, _sp), s in zip(self.step_rows, self.steps) if img.get_icon_name() == "dialog-error-symbolic"]
        error = (f"Action failed: {self.get_title()}\n" + (f"Failed step: {', '.join(failed)}\n" if failed else "")
                 + (f"Result: {self.result.get_text()}\n" if self.result.get_text() else "")
                 + "\nLast output:\n" + "\n".join(self._all_lines[-80:]))
        context = "Commands:\n" + "\n".join(f"  {s.display()}" for s in self.steps)
        open_uri(self, bugreport.Report(error, f"Action: {self.get_title()}", context).url())

    def _notify(self, ok: bool, note: str) -> None:
        """A desktop notification when a task finishes while you're in another window."""
        from gi.repository import Gio
        win = self.get_root()
        app = Gio.Application.get_default()
        if app is None or (isinstance(win, Gtk.Window) and win.is_active()):
            return
        n = Gio.Notification.new(f"{self.get_title()}: {'done' if ok else 'failed'}")
        n.set_body("Finished without problems." if ok else (note or "Open PC Command Center to see what went wrong."))
        app.send_notification("task-finished", n)


def run_steps(parent: Gtk.Widget, title: str, steps: list[Step], explain: str = "", danger: bool = False, ok_label: str = "Run",
              on_done: Callable[[bool], None] | None = None, ask: bool = True) -> None:
    if not steps:
        toast(parent, "Nothing to do.")
        return

    def go(yes: bool) -> None:
        if yes:
            TaskDialog(title, steps, on_done).start(parent)
        elif on_done:
            on_done(False)
    from . import prefs
    if ask and not danger and not needs_root(steps) and not prefs.get("confirm_safe"):
        ask = False  # the user chose to skip confirmations for harmless actions
    if ask:
        confirm(parent, title, steps, explain, danger, ok_label, go)
    else:
        go(True)


def toast(parent: Gtk.Widget, text: str, timeout: int = 3) -> None:
    from .errors import is_error_text, report_text
    if is_error_text(text):
        report_text(text, where="PC Command Center")
        return
    root = parent.get_root() if parent else None
    overlay = getattr(root, "toasts", None)
    if overlay is not None:
        t = Adw.Toast(title=text)
        t.set_timeout(timeout)
        overlay.add_toast(t)


class TextDialog(Adw.Dialog):
    def __init__(self, title: str, text: str):
        super().__init__()
        self.set_title(title)
        self.set_content_width(900)
        self.set_content_height(620)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        copy = button(icon="edit-copy-symbolic", tooltip="Copy all")
        copy.connect("clicked", lambda *_: self.get_clipboard().set(text))
        hb.pack_start(copy)
        tv.add_top_bar(hb)
        buf = Gtk.TextBuffer()
        buf.set_text(text or "(nothing to show)")
        view = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.add_css_class("log-view")
        view.set_left_margin(12)
        view.set_top_margin(10)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(view)
        tv.set_content(sw)
        self.set_child(tv)


def show_text(parent: Gtk.Widget, title: str, text: str) -> None:
    TextDialog(title, text).present(parent)


def ask_text(parent: Gtk.Widget, title: str, body: str, placeholder: str = "", on_done: Callable[[str | None], None] | None = None,
             password: bool = False, ok_label: str = "OK", initial: str = "") -> None:
    d = Adw.AlertDialog(heading=title, body=body)
    entry = Gtk.PasswordEntry(show_peek_icon=True) if password else Gtk.Entry(placeholder_text=placeholder, text=initial)
    entry.set_activates_default(True)
    d.set_extra_child(entry)
    d.add_response("cancel", "Cancel")
    d.add_response("ok", ok_label)
    d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("ok")
    d.set_close_response("cancel")
    d.connect("response", lambda _d, r: on_done and on_done(entry.get_text().strip() if r == "ok" and entry.get_text().strip() else None))
    d.present(parent)
    entry.grab_focus()


class PickDialog(Adw.Dialog):
    """Tick items. on_done(list of keys) or None if cancelled."""

    def __init__(self, title: str, explain: str, items: list[tuple[str, str, str, bool]], on_done: Callable[[list[str] | None], None]):
        super().__init__()
        self.set_title(title)
        self.set_content_width(720)
        self.set_content_height(620)
        self.on_done_cb = on_done
        self.checks: list[tuple[str, Gtk.CheckButton]] = []
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_end_title_buttons(False)
        hb.set_show_start_title_buttons(False)
        cancel = button("Cancel")
        cancel.connect("clicked", lambda *_: self._finish(None))
        ok = button("Done", css="suggested-action")
        ok.connect("clicked", lambda *_: self._finish([k for k, c in self.checks if c.get_active()]))
        hb.pack_start(cancel)
        hb.pack_end(ok)
        tv.add_top_bar(hb)
        box = vbox(spacing=10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(16)
        if explain:
            box.append(label(explain, "dim", wrap=True))
        allb, noneb = button("Select all"), button("Select none")
        allb.connect("clicked", lambda *_: [c.set_active(True) for _, c in self.checks])
        noneb.connect("clicked", lambda *_: [c.set_active(False) for _, c in self.checks])
        box.append(hbox(allb, noneb))
        lst = Gtk.ListBox()
        lst.add_css_class("boxed-list")
        lst.set_selection_mode(Gtk.SelectionMode.NONE)
        for key, title_, sub, active in items:
            row = Adw.ActionRow(title=esc(title_), subtitle=esc(sub))
            cb = Gtk.CheckButton(active=active)
            row.add_prefix(cb)
            row.set_activatable_widget(cb)
            lst.append(row)
            self.checks.append((key, cb))
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(lst)
        box.append(sw)
        tv.set_content(box)
        self.set_child(tv)
        self._done = False

    def _finish(self, res) -> None:
        if not self._done:
            self._done = True
            self.on_done_cb(res)
        self.close()


class ChoiceDialog(Adw.Dialog):
    """Pick one row. rows: (key, title, subtitle)."""

    def __init__(self, title: str, rows: list[tuple[str, str, str]], on_done: Callable[[str | None], None], explain: str = "",
                 search: bool = True):
        super().__init__()
        self.set_title(title)
        self.set_content_width(720)
        self.set_content_height(640)
        self.on_done_cb = on_done
        self._done = False
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        box = vbox(spacing=10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(16)
        if explain:
            box.append(label(explain, "dim", wrap=True))
        self.lst = Gtk.ListBox()
        self.lst.add_css_class("boxed-list")
        self.rows = []
        for key, t, sub in rows:
            r = Adw.ActionRow(title=esc(t), subtitle=esc(sub), activatable=True)
            r.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            r.connect("activated", lambda _r, k=key: self._finish(k))
            r._search = f"{t} {sub}".lower()
            self.lst.append(r)
            self.rows.append(r)
        if search:
            entry = Gtk.SearchEntry(placeholder_text="Search…")
            entry.connect("search-changed", self._filter)
            entry.connect("activate", lambda *_: self._first())
            box.append(entry)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(self.lst)
        box.append(sw)
        tv.set_content(box)
        self.set_child(tv)
        self.connect("closed", lambda *_: self._finish(None, close=False))

    def _first(self) -> None:
        """Enter in the search box picks the first row that's still visible."""
        for r in self.rows:
            if r.get_visible():
                r.emit("activated")
                return

    def _filter(self, entry: Gtk.SearchEntry) -> None:
        q = entry.get_text().lower()
        for r in self.rows:
            r.set_visible(q in r._search)

    def _finish(self, key, close: bool = True) -> None:
        if not self._done:
            self._done = True
            self.on_done_cb(key)
        if close:
            self.close()


class ActivityDialog(Adw.Dialog):
    """Everything the app ran: when, what, the exact commands, the result and the output."""

    def __init__(self):
        super().__init__()
        from . import activity
        from ..core.fmt import ago
        self.set_title("Activity history")
        self.set_content_width(820)
        self.set_content_height(640)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        clear_btn = button("Clear", css="flat", tooltip="Forget the history (doesn't undo anything)")
        hb.pack_start(clear_btn)
        tv.add_top_bar(hb)
        entries = activity.entries()
        box = vbox(spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(16)
        ok_n = sum(1 for e in entries if e.get("ok"))
        box.append(label(f"{len(entries)} actions · {ok_n} succeeded · {len(entries) - ok_n} failed or cancelled. Newest first.", "dim", wrap=True))
        lb = Gtk.ListBox()
        lb.add_css_class("boxed-list")
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        for e in entries:
            from .util import status_icon
            import time as _t
            when = _t.strftime("%d %b %H:%M", _t.localtime(e["ts"]))
            row = Adw.ExpanderRow(title=esc(e["title"]), subtitle=esc(f"{when} ({ago(e['ts'])}) · " + ("done" if e.get("ok") else (e.get("note") or "failed"))
                                                                     + (" · admin" if e.get("root") else "") + (f" · {e['duration']}s" if e.get("duration") else "")))
            row.add_prefix(status_icon("ok" if e.get("ok") else "bad"))
            cmds = "\n".join("$ " + c for c in e.get("commands", []))
            r = Adw.ActionRow(title="Commands", subtitle=esc(cmds[:2000]))
            r.set_subtitle_selectable(True)
            r.set_subtitle_lines(12)
            row.add_row(r)
            out_btn = button("Show output", css="flat")
            out_btn.connect("clicked", lambda _b, ee=e: show_text(self, ee["title"], "\n".join(ee.get("output", [])) or "(no output)"))
            copy_btn = button("Copy commands", css="flat")
            copy_btn.connect("clicked", lambda _b, c=cmds: self.get_clipboard().set(c))
            acts = hbox(out_btn, copy_btn, spacing=6)
            acts.set_margin_top(6)
            acts.set_margin_bottom(6)
            acts.set_margin_start(12)
            row.add_row(acts)
            lb.append(row)
        if not entries:
            box.append(label("Nothing yet. Every cleanup, update, fix or change you run from the app shows up here.", "dim", wrap=True))
        else:
            box.append(lb)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(box)
        tv.set_content(sw)
        self.set_child(tv)

        def do_clear(*_a) -> None:
            activity.clear()
            self.close()
        clear_btn.connect("clicked", do_clear)


class ChecksDialog(Adw.Dialog):
    """Runs a check function in the background and lists what it found, each with a Fix button.

    checks_fn() -> list of Check (id, title, level, detail, fix_label, steps, goto). page is used to run fixes."""

    def __init__(self, title: str, intro: str, checks_fn, page, again_label: str = "Check again", busy: str = "Checking…"):
        super().__init__()
        self.busy_text = busy
        self.set_title(title)
        self.set_content_width(720)
        self.set_content_height(600)
        self.checks_fn, self.page = checks_fn, page
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.again = button(again_label, icon="view-refresh-symbolic", css="flat")
        self.again.connect("clicked", lambda *_: self.start())
        hb.pack_start(self.again)
        tv.add_top_bar(hb)
        self.box = vbox(spacing=12)
        self.box.set_margin_start(18)
        self.box.set_margin_end(18)
        self.box.set_margin_bottom(18)
        self.intro = label(intro, "dim", wrap=True)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        self.list_box = vbox(spacing=10)
        sw.set_child(vbox(self.intro, self.list_box, spacing=12, css=None))
        self.box.append(sw)
        tv.set_content(self.box)
        self.set_child(tv)

    def start(self) -> None:
        from .util import bg, clear
        clear(self.list_box)
        sp = Gtk.Spinner()
        sp.start()
        self.list_box.append(hbox(sp, label(self.busy_text, "dim")))
        self.again.set_sensitive(False)
        bg(self.checks_fn, self._show, error=lambda e: self._show([]))

    def _show(self, checks) -> None:
        from .util import clear, status_icon
        clear(self.list_box)
        self.again.set_sensitive(True)
        lb = Gtk.ListBox()
        lb.add_css_class("boxed-list")
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        for c in checks:
            row = Adw.ActionRow(title=esc(c.title), subtitle=esc(c.detail))
            row.set_subtitle_lines(4)
            row.add_prefix(status_icon(c.level))
            if c.fix_label and (c.steps or c.goto):
                b = button(c.fix_label, css="suggested-action" if c.level == "bad" else "flat")
                b.set_valign(Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, ch=c: self._fix(ch))
                row.add_suffix(b)
            lb.append(row)
        self.list_box.append(lb)

    def _fix(self, c) -> None:
        if c.goto.startswith("settings:"):  # a GNOME Settings panel, e.g. settings:sound
            from .util import launch
            launch(["gnome-control-center", c.goto.split(":", 1)[1]])
        elif c.goto:
            self.close()
            self.page.win.goto(c.goto)
        else:
            self.page.run(c.fix_label, c.steps, c.detail, ok_label=c.fix_label, reload=False, done=lambda ok: ok and self.start())

    def present_and_start(self, parent) -> None:
        self.present(parent)
        self.start()
