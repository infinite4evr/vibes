"""Task Centre: visibility and control for work started by PC Command Center."""

from __future__ import annotations

import time

from gi.repository import Adw, GLib, Gtk

from ..core import maint, power, tasks, watch
from ..core.fmt import ago
from .util import button, clear, hbox, label, pill, spacer, vbox


class TaskCenterDialog(Adw.Dialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_title("Background tasks")
        self.set_content_width(820)
        self.set_content_height(660)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.clear_btn = button("Clear finished", css="flat", on_click=self._clear_finished)
        hb.pack_start(self.clear_btn)
        tv.add_top_bar(hb)

        root = vbox(spacing=18)
        root.set_margin_top(8)
        root.set_margin_bottom(18)
        root.set_margin_start(18)
        root.set_margin_end(18)

        intro = vbox(label("Work started by PC Command Center", "page-title"),
                     label("See what is running, inspect recent output, and stop command tasks safely. System-critical package, boot and filesystem steps finish their current operation before stopping.", "page-sub", wrap=True),
                     spacing=5)
        root.append(intro)

        self.active_title = label("RUNNING", "nav-section")
        self.active_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.active_box.add_css_class("boxed-list")
        root.append(vbox(self.active_title, self.active_box, spacing=6))

        scheduled_title = label("SCHEDULED BY PC COMMAND CENTER", "nav-section")
        self.scheduled = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.scheduled.add_css_class("boxed-list")
        root.append(vbox(scheduled_title, self.scheduled, spacing=6))

        recent_title = label("RECENT", "nav-section")
        self.recent_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recent_box.add_css_class("boxed-list")
        root.append(vbox(recent_title, self.recent_box, spacing=6))

        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(root)
        tv.set_content(sw)
        self.set_child(tv)
        self._refresh()
        self._timer = GLib.timeout_add(700, self._tick)
        self.connect("closed", self._closed)

    def _closed(self, *_a) -> None:
        if getattr(self, "_timer", 0):
            try:
                GLib.source_remove(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = 0

    def _tick(self) -> bool:
        self._refresh()
        return True

    def _clear_finished(self) -> None:
        tasks.clear_finished()
        self._refresh()

    def _refresh(self) -> None:
        rows = tasks.snapshots()
        active = [t for t in rows if t.active]
        recent = [t for t in rows if not t.active][:20]
        self.active_title.set_text(f"RUNNING  ·  {len(active)}")
        clear(self.active_box)
        if not active:
            self.active_box.append(self._empty("Nothing is running in the background."))
        else:
            for task in active:
                self.active_box.append(self._task_row(task, active=True))
        clear(self.recent_box)
        if not recent:
            self.recent_box.append(self._empty("No recent background work in this session."))
        else:
            for task in recent:
                self.recent_box.append(self._task_row(task, active=False))
        self.clear_btn.set_sensitive(bool(recent))
        self._scheduled_rows()

    def _empty(self, text: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=text)
        row.set_sensitive(False)
        return row

    def _task_row(self, task, *, active: bool) -> Adw.ActionRow:
        status = {"running": "Running", "cancelling": "Stopping", "done": "Done", "failed": "Failed", "cancelled": "Stopped"}.get(task.status, task.status.title())
        when = ago(task.started) if task.started else ""
        sub = " · ".join(x for x in [status, task.kind.title(), when, f"PID {task.pid}" if task.pid else "", task.detail] if x)
        row = Adw.ActionRow(title=task.title, subtitle=sub)
        icon = Gtk.Image.new_from_icon_name({"running": "content-loading-symbolic", "cancelling": "process-stop-symbolic", "done": "emblem-ok-symbolic",
                                             "failed": "dialog-error-symbolic", "cancelled": "action-unavailable-symbolic"}.get(task.status, "system-run-symbolic"))
        row.add_prefix(icon)
        if task.lines:
            view = button("Output", css="flat", on_click=lambda t=task: self._show_output(t))
            view.set_valign(Gtk.Align.CENTER)
            row.add_suffix(view)
        if active:
            stop = button("Stop", icon="process-stop-symbolic", css="flat", on_click=lambda tid=task.id: tasks.cancel(tid))
            stop.set_valign(Gtk.Align.CENTER)
            stop.set_sensitive(task.cancellable and task.status == "running")
            stop.set_tooltip_text("Stop this task" if task.cancellable else "This Python worker cannot be force-stopped safely")
            row.add_suffix(stop)
        else:
            kind = "ok" if task.status == "done" else "warn" if task.status == "cancelled" else "bad"
            row.add_suffix(pill(status, kind))
        return row

    def _show_output(self, task) -> None:
        from .dialogs import show_text
        show_text(self, task.title, "\n".join(task.lines) or "(no output)")

    def _scheduled_rows(self) -> None:
        clear(self.scheduled)
        # These are the persistent jobs that PC Command Center itself creates.
        try:
            w_on = bool(watch.settings().get("enabled") and watch.timer_enabled())
        except Exception:  # noqa: BLE001
            w_on = False
        try:
            m = maint.timer_status()
            m_on = bool(m.get("enabled"))
            m_extra = f"Next: {m.get('next')}" if m.get("next") else "Runs weekly when enabled"
        except Exception:  # noqa: BLE001
            m_on, m_extra = False, "Weekly safe cleanup and health check"
        self.scheduled.append(self._schedule_row("Background alerts", "Checks every 30 minutes and notifies only when something needs attention.",
                                                w_on, watch.enable_steps, watch.disable_steps))
        self.scheduled.append(self._schedule_row("Weekly checkup", m_extra, m_on, maint.enable_timer_steps, maint.disable_timer_steps))
        try:
            awake = power.keep_awake_status()
        except Exception:  # noqa: BLE001
            awake = None
        if awake:
            left = awake.get("left")
            detail = f"PID {awake.get('pid')} · " + (f"about {max(1, int(left // 60))} min left" if left is not None else "until you stop it")
            row = Adw.ActionRow(title="Keep Awake", subtitle=detail)
            row.add_prefix(Gtk.Image.new_from_icon_name("weather-clear-night-symbolic"))
            row.add_suffix(pill("On", "ok"))
            stop = button("Stop", icon="process-stop-symbolic", css="flat", on_click=self._stop_keep_awake)
            stop.set_valign(Gtk.Align.CENTER)
            row.add_suffix(stop)
            self.scheduled.append(row)

    def _stop_keep_awake(self) -> None:
        if power.stop_keep_awake():
            self.win.toast("Keep Awake stopped")
        self._refresh()

    def _schedule_row(self, title: str, subtitle: str, enabled: bool, enable_steps, disable_steps) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.add_prefix(Gtk.Image.new_from_icon_name("alarm-symbolic"))
        status = pill("On" if enabled else "Off", "ok" if enabled else "neutral")
        row.add_suffix(status)
        b = button("Turn off" if enabled else "Turn on", css="flat")
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", lambda *_a, on=enabled, en=enable_steps, dis=disable_steps, name=title: self._toggle_schedule(name, dis() if on else en()))
        row.add_suffix(b)
        return row

    def _toggle_schedule(self, name: str, steps) -> None:
        from .dialogs import run_steps
        run_steps(self.win, name, steps, ask=False, on_done=lambda _ok: self._refresh())
