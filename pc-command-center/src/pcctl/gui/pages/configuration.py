"""Configuration inventory and auditable change history."""
from __future__ import annotations

import time

from gi.repository import Gtk

from ...core import config_audit, configuration
from ..util import button, clear, flow, label, pill, vbox
from .base import Page, action_row, group, tabs


class ConfigurationPage(Page):
    ID = "configuration"
    TITLE = "Configuration"
    ICON = "emblem-system-symbolic"
    SUBTITLE = "See what this PC is configured to do and what PC Command Center changed."
    PALETTE = [("refresh", "Refresh configuration inventory")]

    def build(self) -> None:
        refresh = button("Refresh", icon="view-refresh-symbolic", css="flat", on_click=self.reload)
        self.header("Live settings, system tuning and a redacted audit trail — collected without hiding partial failures.", refresh)

        self.stats = flow(spacing=10, min_per_line=2, max_per_line=4, homogeneous=True, css="config-stats")
        self.body.append(self.stats)
        self.notice = vbox(spacing=6)
        self.body.append(self.notice)

        self.current_box = vbox(spacing=16)
        self.history_box = vbox(spacing=16)
        self.current_search = self._search("Search settings, values or sources…", self._render_current)
        self.history_search = self._search("Search actions, commands or dates…", self._render_history)
        current = vbox(self.current_search, self.current_box, spacing=12)
        history = vbox(self.history_search, self.history_box, spacing=12)
        switcher, self.stack = tabs(
            ("current", "Current settings", "emblem-system-symbolic", current),
            ("history", "Change history", "document-open-recent-symbolic", history),
        )
        self.body.append(switcher)
        self.body.append(self.stack)
        self._snapshot = configuration.ConfigSnapshot(())
        self._history: list[dict] = []

    @staticmethod
    def _search(placeholder: str, callback) -> Gtk.SearchEntry:
        entry = Gtk.SearchEntry(placeholder_text=placeholder)
        entry.add_css_class("search")
        entry.set_hexpand(True)
        entry.connect("search-changed", lambda *_: callback())
        return entry

    def palette_action(self, key: str) -> None:
        if key == "refresh":
            self.reload()

    def load(self) -> None:
        self.loading(self.current_box, "Reading configuration providers…")
        self.bg(self._collect, self._show)

    @staticmethod
    def _collect() -> tuple[configuration.ConfigSnapshot, list[dict]]:
        return configuration.snapshot(), config_audit.entries()

    def _show(self, result) -> None:
        self._snapshot, self._history = result
        self._render_stats()
        self._render_notice()
        self._render_current()
        self._render_history()

    def _render_stats(self) -> None:
        clear(self.stats)
        values = (
            (str(len(self._snapshot.items)), "Managed settings"),
            (str(self._snapshot.sections), "Configuration groups"),
            (str(len(self._history)), "Recorded changes"),
            (str(self._snapshot.unknown), "Unknown values"),
        )
        for value, title in values:
            box = vbox(label(value, "stat-num"), label(title, "stat-label"), spacing=2, css="config-stat")
            self.stats.append(box)

    def _render_notice(self) -> None:
        clear(self.notice)
        if self._snapshot.provider_errors:
            box = vbox(label("Some configuration could not be read", "section-title"),
                       label(" · ".join(self._snapshot.provider_errors), "subtle", wrap=True), spacing=3, css="banner-warn")
            self.notice.append(box)
        else:
            self.notice.append(vbox(label("Inventory is current", "section-title"),
                                    label("All available configuration providers completed successfully.", "subtle", wrap=True),
                                    spacing=3, css="banner-ok"))

    def _render_current(self) -> None:
        clear(self.current_box)
        query = self.current_search.get_text().strip().casefold()
        items = [i for i in self._snapshot.items if not query or query in " ".join(
            (i.section, i.title, i.value, i.source, i.description)).casefold()]
        grouped: dict[str, list] = {}
        for item in items:
            state = "ok" if item.recommended is True else "warn" if item.recommended is False else "neutral"
            value = pill(item.value, state)
            subtitle = item.source + (f"\n{item.description}" if item.description else "")
            grouped.setdefault(item.section, []).append(action_row(item.title, subtitle, value))
        if not grouped:
            self.current_box.append(group("No matching settings", "Try a broader search." if query else "No supported settings were detected."))
            return
        for section, rows in grouped.items():
            self.current_box.append(group(section, f"{len(rows)} detected setting{'s' if len(rows) != 1 else ''}.", *rows))

    def _render_history(self) -> None:
        clear(self.history_box)
        query = self.history_search.get_text().strip().casefold()
        rows = []
        for item in self._history:
            stamp = time.strftime("%d %b %Y, %H:%M", time.localtime(float(item.get("ts", 0))))
            origin = str(item.get("interface", "app")).capitalize()
            cmd = str(item.get("command", ""))
            haystack = " ".join((stamp, origin, str(item.get("action", "")), str(item.get("step", "")), cmd)).casefold()
            if query and query not in haystack:
                continue
            access = pill("Admin" if item.get("root") else "User", "warn" if item.get("root") else "neutral")
            title = str(item.get("step") or item.get("action") or "Configuration change")
            subtitle = f"{stamp} · {origin}" + (f"\n{cmd}" if cmd else "")
            rows.append(action_row(title, subtitle, access))
        if rows:
            self.history_box.append(group("Successful changes", f"Showing {len(rows)} of {len(self._history)} recorded changes. Commands are redacted before storage.", *rows[:250]))
        else:
            text = "No matching recorded changes." if query else "No configuration changes have been recorded yet. Older changes may predate this audit trail."
            self.history_box.append(group("Change history", text))


PAGE = ConfigurationPage
