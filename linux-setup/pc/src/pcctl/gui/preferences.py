"""Preferences window: appearance, behaviour, background alerts, cleanup exclusions and weekly auto-clean."""

from __future__ import annotations

from typing import Callable

from gi.repository import Adw, Gtk

from ..core import junk, maint, watch
from . import prefs, theme
from .util import button, esc

APPEARANCE = [("system", "Follow the system"), ("light", "Light"), ("dark", "Dark")]
LOOKS = [("modern", "Modern"), ("catppuccin", "Catppuccin")]
REFRESH = [("fast", "Fast (every second)"), ("normal", "Normal"), ("slow", "Battery saver (slower graphs)")]


def _combo(title: str, subtitle: str, options: list[tuple[str, str]], current: str, on_pick: Callable[[str], None]) -> Adw.ComboRow:
    row = Adw.ComboRow(model=Gtk.StringList.new([t for _, t in options]))
    row.set_use_markup(False)  # plain text on every libadwaita version (their markup defaults differ)
    row.set_title(title)
    row.set_subtitle(subtitle)
    keys = [k for k, _ in options]
    if current in keys:
        row.set_selected(keys.index(current))
    row.connect("notify::selected", lambda r, _p: on_pick(keys[r.get_selected()]))
    return row


def _switch(title: str, subtitle: str, active: bool, on_change: Callable[[bool], None]) -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=esc(title), subtitle=esc(subtitle))
    row.set_active(active)
    row.connect("notify::active", lambda r, _p: on_change(r.get_active()))
    return row


def _spin(title: str, subtitle: str, value: float, lo: float, hi: float, step: float, on_change: Callable[[float], None]) -> Adw.SpinRow:
    row = Adw.SpinRow.new_with_range(lo, hi, step)
    row.set_title(esc(title))
    row.set_subtitle(esc(subtitle))
    row.set_value(value)
    row.connect("notify::value", lambda r, _p: on_change(r.get_value()))
    return row


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_title("Preferences")
        self.set_search_enabled(True)
        self.add(self._general())
        self.add(self._alerts())
        self.add(self._cleanup())

    # ---------------------------------------------------------------- general
    def _general(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        look = Adw.PreferencesGroup(title="Look")

        def appearance(mode: str) -> None:
            prefs.set("appearance", mode)
            theme.set_mode(mode)
            self.win.sync_appearance_action(mode)
        look.add(_combo("Style", "Light or dark. “Follow the system” switches together with GNOME.",
                        APPEARANCE, prefs.get("appearance"), appearance))

        def colours(name: str) -> None:
            prefs.set("look", name)
            theme.set_look(name)
            from . import theme as _t
            _t.redraw_tree(self.win)
        look.add(_combo("Colours", "Modern: clean and neutral, with GNOME's accent colour. Catppuccin: the soft pastel theme of your desktop setup.",
                        LOOKS, prefs.get("look"), colours))
        page.add(look)

        beh = Adw.PreferencesGroup(title="Behaviour")
        pages = [("last", "The page I had open last")] + [(pid, cls.TITLE) for pid, cls in self.win.classes.items()]
        beh.add(_combo("Open on", "Which page shows when the app starts.", pages, prefs.get("start_page"), lambda v: prefs.set("start_page", v)))

        def refresh(v: str) -> None:
            prefs.set("refresh", v)
            self.win.restart_timers()
        beh.add(_combo("Live graphs", "How often the live numbers update. Slower saves battery.", REFRESH, prefs.get("refresh"), refresh))
        beh.add(_switch("Pause when hidden", "Stop live updates while the window is minimised or in the background.", prefs.get("pause_hidden"),
                        lambda v: prefs.set("pause_hidden", v)))
        beh.add(_switch("Show commands before simple actions", "Admin and risky actions always ask first. Turn this off to skip the "
                        "confirmation for harmless ones (like clearing your own caches).", prefs.get("confirm_safe"),
                        lambda v: prefs.set("confirm_safe", v)))
        beh.add(_spin("Extra warning above (GB)", "Ask twice before deleting more than this at once.", prefs.get("big_delete_gb"), 1, 500, 1,
                      lambda v: prefs.set("big_delete_gb", int(v))))
        page.add(beh)
        return page

    # ---------------------------------------------------------------- alerts
    def _alerts(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Alerts", icon_name="preferences-system-notifications-symbolic")
        cfg = watch.settings()
        main = Adw.PreferencesGroup(title="Background alerts", description="A tiny check every 30 minutes, even when the app is closed. "
                                    "Each alert repeats at most once a day.")
        self.alert_row = Adw.SwitchRow(title="Tell me when something needs attention")
        self.alert_row.set_active(cfg["enabled"] and watch.timer_enabled())
        self.alert_row.connect("notify::active", self._toggle_alerts)
        main.add(self.alert_row)
        test = Adw.ActionRow(title="Check now", subtitle="Runs the check once and shows any alerts that apply right now.")
        b = button("Check", css="flat", on_click=self._test_alerts)
        b.set_valign(Gtk.Align.CENTER)
        test.add_suffix(b)
        main.add(test)
        page.add(main)

        what = Adw.PreferencesGroup(title="What to watch")
        what.add(_spin("Disk almost full (%)", "Alert when any disk is at least this full.", cfg["disk_pct"], 50, 99, 1,
                       lambda v: watch.save_settings(disk_pct=int(v))))
        what.add(_switch("Security updates waiting", "Reminds you every 3 days.", cfg["security_updates"],
                         lambda v: watch.save_settings(security_updates=v)))
        what.add(_switch("Services failing", "A background program keeps crashing.", cfg["failed_services"],
                         lambda v: watch.save_settings(failed_services=v)))
        what.add(_spin("Restart pending (days)", "Alert when updates have waited this long for a restart.", cfg["restart_pending_days"], 1, 30, 1,
                       lambda v: watch.save_settings(restart_pending_days=int(v))))
        what.add(_spin("Trash bigger than (GB)", "0 turns this off.", cfg["trash_gb"], 0, 500, 1, lambda v: watch.save_settings(trash_gb=int(v))))
        what.add(_spin("CPU hotter than (°C)", "", cfg["temperature"], 60, 110, 1, lambda v: watch.save_settings(temperature=int(v))))
        what.add(_spin("Battery health below (%)", "Tells you (once a month) when the battery is worn.", cfg["battery_health"], 10, 100, 5,
                       lambda v: watch.save_settings(battery_health=int(v))))
        page.add(what)
        return page

    def _toggle_alerts(self, row, _p) -> None:
        on = row.get_active()
        if on == (watch.settings()["enabled"] and watch.timer_enabled()):
            return
        from .dialogs import run_steps
        run_steps(self.win, "Background alerts", watch.enable_steps() if on else watch.disable_steps(), ask=False,
                  on_done=lambda ok: ok or row.set_active(not on))

    def _test_alerts(self) -> None:
        from .util import bg
        bg(lambda: watch.run(force=True), lambda sent: self.add_toast(Adw.Toast(title=f"{len(sent)} alert(s) sent" if sent else "Nothing needs attention right now")))

    # ---------------------------------------------------------------- cleanup
    def _cleanup(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Cleanup", icon_name="edit-clear-all-symbolic")
        auto = Adw.PreferencesGroup(title="Weekly automatic cleanup", description="What the weekly checkup (Maintenance page) may clean "
                                    "by itself. Only things that never need a password or a decision are offered.")
        chosen = set(junk.auto_ids())
        for jid, (title, _fn) in junk.AUTO_SAFE.items():
            def change(v: bool, j=jid) -> None:
                cur = set(junk.auto_ids())
                (cur.add if v else cur.discard)(j)
                maint.save_config(auto_clean=[k for k in junk.AUTO_SAFE if k in cur])
            auto.add(_switch(title, "", jid in chosen, change))
        page.add(auto)

        self.ex_group = Adw.PreferencesGroup(title="Never clean", description="Categories and items you excluded. Right-click (or use the "
                                             "⋯ button) on anything in Cleanup to add it here.")
        page.add(self.ex_group)
        self._fill_exclusions()
        return page

    def _fill_exclusions(self) -> None:
        for r in getattr(self, "_ex_rows", []):
            self.ex_group.remove(r)
        self._ex_rows = []
        ex = sorted(junk.exclusions())
        if not ex:
            r = Adw.ActionRow(title="Nothing excluded yet")
            self.ex_group.add(r)
            self._ex_rows.append(r)
            return
        for key in ex:
            jid, _, item = key.partition("|")
            r = Adw.ActionRow(title=esc(item.replace(str(maint.HOME), "~") if item else f"Whole category: {jid}"),
                              subtitle=esc(jid if item else ""))
            b = button(icon="edit-delete-symbolic", css="flat", tooltip="Allow cleaning it again")
            b.set_valign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, k=key: (junk.set_excluded(k, False), self._fill_exclusions()))
            r.add_suffix(b)
            self.ex_group.add(r)
            self._ex_rows.append(r)
