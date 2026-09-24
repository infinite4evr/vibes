"""Logs: problems grouped by app, the full journal with search, crash reports, and past boots."""

from __future__ import annotations

import os

from gi.repository import Adw, Gtk

from ...core import logs, services
from ...core.fmt import ago, human
from ...core.run import Step, out
from ..util import button, clear, esc, hbox, label, pill, spacer, vbox
from ..widgets import Column, DataTable
from .base import Page, action_row, boxed_list, group, tabs

RANGES = [("This boot", "boot"), ("Previous boot (before the last restart/crash)", "previous"), ("Last hour", "1 hour ago"),
          ("Last 24 hours", "24 hours ago"), ("Last 7 days", "7 days ago")]
LEVELS = [("Errors", 3), ("Warnings and errors", 4), ("Everything", 6)]
PRIO = {0: ("emergency", "bad"), 1: ("alert", "bad"), 2: ("critical", "bad"), 3: ("error", "bad"), 4: ("warning", "warn"), 5: ("notice", "info"),
        6: ("info", "neutral"), 7: ("debug", "neutral")}


class LogsPage(Page):
    ID = "logs"
    TITLE = "Logs"
    ICON = "text-x-generic-symbolic"
    SUBTITLE = "What went wrong and when. Most messages are harmless; repeated errors from one app are worth a look."

    def build(self) -> None:
        self.header()
        self.range_dd = Gtk.DropDown.new_from_strings([r[0] for r in RANGES])
        self.level_dd = Gtk.DropDown.new_from_strings([lv[0] for lv in LEVELS])
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search messages (e.g. usb, wifi, nvidia)…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", lambda *_: self.load())
        self.noise = Gtk.CheckButton(label="Hide harmless noise", active=True)
        for w, sig in ((self.range_dd, "notify::selected"), (self.level_dd, "notify::selected"), (self.noise, "toggled")):
            w.connect(sig, lambda *_: self.load())
        self.body.append(hbox(self.range_dd, self.level_dd, self.search_entry, self.noise, spacing=8))
        self.summary = label("", "subtle", wrap=True)
        self.body.append(self.summary)

        self.problems = vbox(spacing=10)
        self.all_box = vbox(spacing=10)
        self.crash_box = vbox(spacing=10)
        self.boots_box = vbox(spacing=10)
        sw, self.stack = tabs(("problems", "Problems by app", "dialog-warning-symbolic", self.problems),
                              ("all", "All messages", "view-list-symbolic", self.all_box),
                              ("crashes", "Crashes", "computer-fail-symbolic", self.crash_box),
                              ("boots", "Restarts", "system-reboot-symbolic", self.boots_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()

        self.table = DataTable([
            Column("when", "Time", "muted", width=110, sort="time"),
            Column("lvl", "Level", "pill", width=90, sort="prio"),
            Column("source", "From", "bold", width=170),
            Column("message", "Message", "text", expand=True),
        ], on_activate=lambda r: self.text(f"{r['source']} at {r['when']}", r["message"] + (f"\n\nunit: {r['unit']}  pid: {r['pid']}" if r["unit"] else "")),
            empty="No messages.", sort="time")
        self.table.set_size_request(-1, 480)
        self.all_box.append(self.table)
        self.all_box.append(label("Double-click a message to read all of it.", "dim"))

    def _query(self) -> dict:
        return {"since": RANGES[self.range_dd.get_selected()][1], "max_priority": LEVELS[self.level_dd.get_selected()][1],
                "grep": self.search_entry.get_text().strip(), "limit": 3000}

    def load(self) -> None:
        self.summary.set_text("Reading the system journal…")
        q = self._query()
        self.loading(self.problems, "Reading logs…")
        self.table.set_empty("Reading logs…")
        self.bg(lambda: logs.entries(**q), self.show)
        for t in ("crashes", "boots"):
            self.tab_loaded.discard(t)
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "crashes":
            self.load_crashes()
        elif name == "boots":
            self.load_boots()

    def show(self, lines: list[logs.LogLine]) -> None:
        hide = self.noise.get_active()
        shown = [ln for ln in lines if not (hide and logs.is_noise(ln.message))]
        groups = logs.grouped(lines, hide_noise=hide)
        errs = sum(1 for ln in shown if ln.priority <= 3)
        self.summary.set_text(f"{len(shown)} messages from {len(groups)} sources" + (f", {errs} errors" if errs else "") +
                              (f" ({len(lines) - len(shown)} harmless ones hidden)" if hide and len(lines) > len(shown) else "") + ".")
        # grouped
        clear(self.problems)
        if not groups:
            self.problems.append(label("Nothing to report for this time range.", "dim"))
        lb = boxed_list()
        by_src: dict[str, list[logs.LogLine]] = {}
        for ln in shown:
            by_src.setdefault(ln.source, []).append(ln)
        for g in groups[:80]:
            name, kind = PRIO.get(g["worst"], ("?", "neutral"))
            expl = services.explain(g["unit"]) if g["unit"] else ""
            row = Adw.ExpanderRow(title=esc(g["source"]), subtitle=esc((expl + "\n" if expl else "") + f"last {ago(g['last'])}: {g['message'][:160]}"))
            row.set_subtitle_lines(3)
            suffix = hbox(pill(f"{g['count']}×", "neutral"), pill(name, kind), spacing=6)
            suffix.set_valign(Gtk.Align.CENTER)
            row.add_suffix(suffix)
            msgs = sorted(by_src.get(g["source"], []), key=lambda m: -m.time)
            for m in msgs[:12]:
                r = Adw.ActionRow(title=esc(m.message[:300]), subtitle=esc(f"{logs.fmt_time(m.time)} · {PRIO.get(m.priority, ('?',))[0]}"))
                r.set_title_lines(3)
                r.set_title_selectable(True)
                row.add_row(r)
            actions = hbox(spacing=6)
            actions.set_margin_top(6)
            actions.set_margin_bottom(6)
            actions.set_margin_start(12)
            if g["unit"]:
                actions.append(button("Full log of this service", css="flat", on_click=lambda u=g["unit"]: self.unit_log(u)))
                actions.append(button("Open in Services", css="flat", on_click=lambda: self.win.goto("services")))
            actions.append(button("Search the web", css="flat", on_click=lambda m=g["message"], s=g["source"]: self.web(s, m)))
            row.add_row(actions)
            lb.append(row)
        if groups:
            self.problems.append(lb)
        # table
        rows = []
        for n, ln in enumerate(shown):
            rows.append({"key": n, "time": ln.time, "when": logs.fmt_time(ln.time), "prio": ln.priority, "lvl": PRIO.get(ln.priority, ("?", "neutral")),
                         "source": ln.source, "message": ln.message, "unit": ln.unit, "pid": ln.pid})
        self.table.set_rows(rows)
        self.table.set_empty("No messages for this time range.")
        errs_boot = sum(1 for g in groups if g["worst"] <= 3)
        self.win.set_badge("logs", 0)
        page = self.stack.get_page(self.problems)
        page.set_badge_number(errs_boot)

    def unit_log(self, unit: str) -> None:
        self.bg(lambda: out(["journalctl", "--no-pager", "-u", unit, "-n", "400", "-b"], timeout=20) or out(["journalctl", "--user", "--no-pager", "-u", unit, "-n", "400", "-b"], timeout=20),
                lambda t: self.text(f"Log: {unit}", t))

    def web(self, source: str, msg: str) -> None:
        import re
        from urllib.parse import quote

        from ..util import launch
        clean = re.sub(r"\b[0-9a-f]{8,}\b|\d+", "", msg)[:120]
        launch(["xdg-open", f"https://duckduckgo.com/?q={quote(f'ubuntu {source} {clean}')}"])

    # ---------------------------------------------------------------- crashes
    def load_crashes(self) -> None:
        self.loading(self.crash_box)
        self.bg(logs.crashes, self.show_crashes)

    def show_crashes(self, items: list[dict]) -> None:
        clear(self.crash_box)
        if not items:
            self.crash_box.append(label("No crash reports. Apps haven't crashed recently (or reports were cleaned up).", "dim", wrap=True))
            return
        rows = []
        for c in items:
            btns = []
            if c["file"]:
                btns.append(button("View", css="flat", on_click=lambda f=c["file"]: self.bg(lambda: open(f, errors="replace").read(200_000),
                                                                                           lambda t: self.text(os.path.basename(f), t))))
                btns.append(button(icon="user-trash-symbolic", css="flat", tooltip="Delete report", on_click=lambda f=c["file"]: self.run(
                    "Delete crash report", [Step("Delete report", ["rm", "-f", f], root=not os.access(os.path.dirname(f), os.W_OK))], reload=False,
                    done=lambda ok: self.load_crashes())))
            rows.append(action_row(c["app"], (f"{ago(c['time'])} · {human(c['size'])}" if c["time"] else c.get("raw", "")), *btns,
                                   prefix=Gtk.Image.new_from_icon_name("computer-fail-symbolic")))
        g = group("Crash reports", "Saved when an app crashes. Useful for bug reports; safe to delete.", *rows,
                  suffix=button("Delete all", css="flat", on_click=self.clear_crashes) if any(c["file"] for c in items) else None)
        self.crash_box.append(g)

    def clear_crashes(self) -> None:
        self.run("Delete all crash reports", [Step("Delete /var/crash/*.crash", ["bash", "-c", "rm -f /var/crash/*.crash /var/crash/*.upload /var/crash/*.uploaded"], root=True)],
                 "They're only useful for bug reports.", ok_label="Delete", reload=False, done=lambda ok: self.load_crashes())

    # ---------------------------------------------------------------- boots
    def load_boots(self) -> None:
        self.loading(self.boots_box)
        self.bg(lambda: (logs.boots(), out(["last", "-x", "-n", "30", "shutdown", "reboot"], timeout=10)), self.show_boots)

    def show_boots(self, res) -> None:
        boots, last = res
        clear(self.boots_box)
        rows = []
        for b in reversed(boots):
            idx = b["index"]
            rows.append(action_row("Current session" if idx == 0 else f"{-idx} restart{'s' if idx != -1 else ''} ago", f"{b['start']} → {b['end']}",
                                   button("Errors", css="flat", on_click=lambda i=idx: self.boot_errors(i)),
                                   prefix=Gtk.Image.new_from_icon_name("system-reboot-symbolic")))
        self.boots_box.append(group("Recent starts", "Each time the PC started. If it froze or crashed, check the errors of the start before.", *rows)
                              if rows else label("Boot history isn't kept on this system (the journal is stored in memory only).", "dim", wrap=True))
        if last.strip():
            self.boots_box.append(group("Shutdown record", "", action_row("Restarts and shutdowns", "From the login records (last -x).",
                                                                         button("View", css="flat", on_click=lambda: self.text("Restarts and shutdowns", last)))))

    def boot_errors(self, idx: int) -> None:
        self.bg(lambda: out(["journalctl", "--no-pager", "-b", str(idx), "-p", "3", "-n", "500"], timeout=30),
                lambda t: self.text(f"Errors from boot {idx}", t or "No errors (or no permission to read them)."))


PAGE = LogsPage
