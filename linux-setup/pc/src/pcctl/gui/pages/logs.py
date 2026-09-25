"""Logs: problems grouped by app, the full journal with search and live follow, kernel messages, crash reports,
past boots, and how much space the logs take."""

from __future__ import annotations

import os
import subprocess
import threading

from gi.repository import Adw, GLib, Gtk

from ...core import logs, services
from ...core.fmt import ago, human
from ...core.run import C_ENV, Step, out
from ..util import button, clear, esc, hbox, label, pill, status_icon, vbox
from ..widgets import Column, DataTable, Row
from .base import Page, action_row, boxed_list, group, tabs

RANGES = [("This boot", "boot"), ("Previous boot (before the last restart/crash)", "previous"), ("Last hour", "1 hour ago"),
          ("Last 24 hours", "24 hours ago"), ("Last 7 days", "7 days ago")]
LEVELS = [("Errors", 3), ("Warnings and errors", 4), ("Everything", 6)]
PRIO = {0: ("emergency", "bad"), 1: ("alert", "bad"), 2: ("critical", "bad"), 3: ("error", "bad"), 4: ("warning", "warn"), 5: ("notice", "info"),
        6: ("info", "neutral"), 7: ("debug", "neutral")}
KERNEL_LEVELS = [("Warnings and errors", 4), ("Everything", 6)]
KEEP_SIZES = [(100, "100 MB"), (250, "250 MB"), (500, "500 MB"), (1024, "1 GB")]
KEEP_DAYS = [(3, "3 days"), (7, "1 week"), (14, "2 weeks"), (30, "1 month")]
LIMITS = [(0, "Ubuntu's default"), (200, "200 MB"), (500, "500 MB"), (1024, "1 GB"), (2048, "2 GB")]
LIVE_CAP = 2000


class LogsPage(Page):
    ID = "logs"
    TITLE = "Logs"
    ICON = "text-x-generic-symbolic"
    SUBTITLE = "What went wrong and when. Most messages are harmless; repeated errors from one app are worth a look."
    PALETTE = [("kernel", "Kernel messages: hardware, drivers, USB (like dmesg)"), ("live", "Watch the logs live as messages arrive"),
               ("size", "How much space logs use / keep them small")]

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
        self.search_entry.set_size_request(200, -1)
        filters = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8, min_children_per_line=1, max_children_per_line=4)
        for w in (self.range_dd, self.level_dd, self.search_entry, self.noise):
            filters.append(w)
        self.body.append(filters)
        self.summary = label("", "subtle", wrap=True)
        self.body.append(self.summary)

        self.problems = vbox(spacing=10)
        self.all_box = vbox(spacing=10)
        self.kernel_box = vbox(spacing=12)
        self.crash_box = vbox(spacing=10)
        self.boots_box = vbox(spacing=10)
        self.size_box = vbox(spacing=18)
        sw, self.stack = tabs(("problems", "Problems", "dialog-warning-symbolic", self.problems),
                              ("all", "Messages", "view-list-symbolic", self.all_box),
                              ("kernel", "Kernel", "application-x-firmware-symbolic", self.kernel_box),
                              ("crashes", "Crashes", "computer-fail-symbolic", self.crash_box),
                              ("boots", "Restarts", "system-reboot-symbolic", self.boots_box),
                              ("size", "Log size", "drive-harddisk-symbolic", self.size_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()

        # all messages + live follow (K2)
        self.live_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.live_switch.connect("notify::active", lambda *_: self._live_toggled())
        self.live_status = label("", "dim", wrap=True, hexpand=True)
        self.all_box.append(hbox(self.live_switch, label("Live", "heading"), self.live_status, spacing=10))
        self.table = DataTable([
            Column("when", "Time", "muted", width=110, sort="time"),
            Column("lvl", "Level", "pill", width=90, sort="prio"),
            Column("source", "From", "bold", width=170),
            Column("message", "Message", "text", expand=True),
        ], on_activate=lambda r: self.text(f"{r['source']} at {r['when']}", r["message"] + (f"\n\nunit: {r['unit']}  pid: {r['pid']}" if r["unit"] else "")),
            empty="No messages.", sort="time")
        self.table.set_size_request(-1, 480)
        self.table.set_context(lambda r: [("Search the web for this", lambda rr: self.web(rr["source"], rr["message"]))], "logs")
        self.all_box.append(self.table)
        self.all_box.append(label("Double-click a message to read all of it. Newest first.", "dim"))
        self._follow: subprocess.Popen | None = None
        self._pending: list[logs.LogLine] = []
        self._lock = threading.Lock()
        self._flush_id: int | None = None
        self._live_n = 0

        # kernel (K1)
        self.k_level = Gtk.DropDown.new_from_strings([k[0] for k in KERNEL_LEVELS])
        self.k_level.connect("notify::selected", lambda *_: self.load_kernel())
        self.k_raw = button("Show as plain text", icon="text-x-generic-symbolic", css="flat", on_click=self.kernel_raw)
        self.k_summary = label("", "dim", wrap=True, hexpand=True)
        self.k_list = vbox(spacing=10)
        self.kernel_box.append(label("Messages from the core of Linux (the kernel): hardware, drivers, USB, disks, Wi-Fi, graphics. "
                                     "Most are harmless chatter; the ones worth a look are explained.", "dim", wrap=True))
        self.kernel_box.append(hbox(self.k_level, self.k_summary, self.k_raw, spacing=10))
        self.kernel_box.append(self.k_list)

    def _query(self) -> dict:
        return {"since": RANGES[self.range_dd.get_selected()][1], "max_priority": LEVELS[self.level_dd.get_selected()][1],
                "grep": self.search_entry.get_text().strip(), "limit": 3000}

    def load(self) -> None:
        self.summary.set_text("Reading the system journal…")
        q = self._query()
        self.loading(self.problems, "Reading logs…")
        self.table.set_empty("Reading logs…")
        self.bg(lambda: logs.entries(**q), self.show)
        for t in ("crashes", "boots", "kernel", "size"):
            self.tab_loaded.discard(t)
        self._tab()
        if self._follow is not None:  # filters changed: follow with the new ones
            self._stop_follow()
            self._start_follow()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "crashes":
            self.load_crashes()
        elif name == "boots":
            self.load_boots()
        elif name == "kernel":
            self.load_kernel()
        elif name == "size":
            self.load_size()

    def _row(self, n, ln: logs.LogLine) -> dict:
        return {"key": n, "time": ln.time, "when": logs.fmt_time(ln.time), "prio": ln.priority, "lvl": PRIO.get(ln.priority, ("?", "neutral")),
                "source": ln.source, "message": ln.message, "unit": ln.unit, "pid": ln.pid}

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
        self.table.set_rows([self._row(n, ln) for n, ln in enumerate(shown)])
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

    # ---------------------------------------------------------------- live follow (K2)
    def activate(self) -> None:
        super().activate()
        if self.live_switch.get_active() and self._follow is None:
            self._start_follow()

    def deactivate(self) -> None:
        super().deactivate()
        self._stop_follow()  # leaving the page or hiding the window: stop reading (the switch stays on and resumes)

    def _live_toggled(self) -> None:
        if self.live_switch.get_active():
            self.stack.set_visible_child_name("all")
            self._start_follow()
        else:
            self._stop_follow()
            self.live_status.set_text("")

    def _start_follow(self) -> None:
        if self._follow is not None:
            return
        q = self._query()
        cmd = logs.follow_cmd(q["max_priority"], grep=q["grep"])
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                    errors="replace", env=C_ENV)
        except OSError as e:
            self.live_status.set_text(f"Can't follow the journal: {e}")
            self.live_switch.set_active(False)
            return
        self._follow = proc
        self._live_n = 0
        self.live_status.set_text("Watching: new messages appear at the top as they happen.")
        threading.Thread(target=self._follow_reader, args=(proc,), daemon=True).start()
        self._flush_id = GLib.timeout_add(700, self._flush_follow)

    def _follow_reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                got = logs.parse_journal_json(line)
                if got:
                    with self._lock:
                        self._pending.extend(got)
                        del self._pending[:-LIVE_CAP]
        except (OSError, ValueError):
            pass
        code = proc.wait()
        GLib.idle_add(lambda: (self._follow_ended(proc, code), False)[1])

    def _follow_ended(self, proc: subprocess.Popen, code: int) -> None:
        if self._follow is not proc:
            return  # we stopped it ourselves
        self._stop_follow()
        self.live_status.set_text("Stopped: the journal can't be followed here (no permission or no journal)." if code else "Stopped.")
        self.live_switch.set_active(False)

    def _flush_follow(self) -> bool:
        with self._lock:
            new, self._pending = self._pending, []
        if new:
            hide = self.noise.get_active()
            store = self.table.store
            for ln in new:
                if hide and logs.is_noise(ln.message):
                    continue
                self._live_n += 1
                store.append(Row(self._row(f"live{self._live_n}-{ln.time}", ln)))
            extra = store.get_n_items() - LIVE_CAP
            if extra > 0:
                store.splice(0, extra, [])
            self.table.refilter()
            self.live_status.set_text(f"Watching: {self._live_n} new message{'s' if self._live_n != 1 else ''} so far (newest at the top).")
        return self._follow is not None

    def _stop_follow(self) -> None:
        proc, self._follow = self._follow, None
        if self._flush_id is not None:
            GLib.source_remove(self._flush_id)
            self._flush_id = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    # ---------------------------------------------------------------- kernel (K1)
    def load_kernel(self) -> None:
        self.loading(self.k_list, "Reading kernel messages…")
        q = self._query()
        prio = KERNEL_LEVELS[self.k_level.get_selected()][1]
        self.bg(lambda: logs.kernel_entries(q["since"], prio, 3000, q["grep"]), self.show_kernel)

    def show_kernel(self, lines: list[logs.LogLine]) -> None:
        clear(self.k_list)
        hide = self.noise.get_active()
        groups = logs.kernel_groups(lines, hide_harmless=hide)
        shown = sum(g["count"] for g in groups)
        hidden = len(lines) - shown
        worth = sum(1 for g in groups for _ln, ex in g["lines"] if not (ex and ex[1]))
        if hidden:
            self.k_summary.set_text(f"{shown} worth a look, {hidden} harmless one{'s' if hidden != 1 else ''} hidden.")
        else:
            self.k_summary.set_text(f"{shown} message{'s' if shown != 1 else ''}, {worth} worth a look.")
        self.stack.get_page(self.kernel_box).set_badge_number(sum(1 for g in groups if g["worst"] <= 3))
        if not lines:
            self.k_list.append(label("No kernel messages for this time range and level (or no permission to read them: your account needs to be in the "
                                     "'adm' group, which it is by default on Ubuntu).", "dim", wrap=True))
            return
        if not groups:
            self.k_list.append(hbox(status_icon("ok"), label("Only harmless messages. Nothing here needs your attention.", None, wrap=True)))
            return
        lb = boxed_list()
        for g in groups:
            name, kind = PRIO.get(g["worst"], ("?", "neutral"))
            first = g["lines"][0]
            row = Adw.ExpanderRow(title=esc(g["name"]), subtitle=esc(f"last {ago(g['last'])}: {first[0].message[:150]}"))
            row.set_subtitle_lines(2)
            row.add_prefix(Gtk.Image.new_from_icon_name(g["icon"]))
            suffix = hbox(pill(f"{g['count']}×", "neutral"), pill(name, kind), spacing=6)
            suffix.set_valign(Gtk.Align.CENTER)
            row.add_suffix(suffix)
            seen: set[str] = set()
            n = 0
            for ln, ex in g["lines"]:
                if n >= 15:
                    break
                n += 1
                sub = f"{logs.fmt_time(ln.time)} · {PRIO.get(ln.priority, ('?',))[0]}"
                if ex and ex[0] not in seen:
                    sub += "\n" + ex[0]
                    seen.add(ex[0])
                r = Adw.ActionRow(title=esc(ln.message[:300]), subtitle=esc(sub))
                r.set_title_lines(3)
                r.set_subtitle_lines(4)
                r.set_title_selectable(True)
                if ex and ex[1]:
                    r.add_suffix(pill("harmless", "ok"))
                elif ex:
                    r.add_suffix(pill("worth a look", "warn"))
                row.add_row(r)
            if len(g["lines"]) > n:
                row.add_row(Adw.ActionRow(title=esc(f"…and {len(g['lines']) - n} more (use “Show as plain text”)")))
            lb.append(row)
        self.k_list.append(lb)

    def kernel_raw(self) -> None:
        q = self._query()
        args = ["journalctl", "-k", "--no-pager", "-o", "short-iso", "-n", "3000", "-p", str(KERNEL_LEVELS[self.k_level.get_selected()][1])]
        args += ["-b"] if q["since"] == "boot" else (["-b", "-1"] if q["since"] == "previous" else ["--since", q["since"]])
        self.bg(lambda: out(args, timeout=30), lambda t: self.text("Kernel messages", t or "No kernel messages (or no permission to read them)."))

    # ---------------------------------------------------------------- journal size (K3)
    def load_size(self) -> None:
        self.loading(self.size_box, "Measuring…")
        self.bg(logs.journal_info, self.show_size)

    def show_size(self, info: dict) -> None:
        clear(self.size_box)
        size = info.get("size")
        where = ("Kept on disk (/var/log/journal), so you can look back at earlier boots." if info["persistent"] else
                 "Kept in memory only, so they're lost at every restart.")
        limit = info.get("max_use")
        lim_text = (f"Kept under {limit}" + (" (set by PC Command Center)" if info.get("ours") else "") if limit else
                    "Ubuntu's default: up to 10% of the disk, never more than 4 GB")
        if info.get("max_age"):
            lim_text += f"; deleted after {info['max_age']}"
        big = size is not None and size > 1024 ** 3
        self.size_box.append(group("Space used by system logs", "",
                                   action_row(f"Logs take up {human(size)}" if size is not None else "Size unknown",
                                              where if size is not None else "Couldn't measure (journalctl isn't answering).",
                                              prefix=status_icon("warn" if big else "ok")),
                                   action_row("Limit", lim_text)))
        # clean up now
        size_dd = Gtk.DropDown.new_from_strings([t for _, t in KEEP_SIZES])
        size_dd.set_selected(2)
        days_dd = Gtk.DropDown.new_from_strings([t for _, t in KEEP_DAYS])
        days_dd.set_selected(1)
        clean1 = button("Clean up", css="flat", on_click=lambda: self.vacuum(size_mb=KEEP_SIZES[size_dd.get_selected()][0]))
        clean2 = button("Clean up", css="flat", on_click=lambda: self.vacuum(days=KEEP_DAYS[days_dd.get_selected()][0]))
        self.size_box.append(group("Clean up now", "Deletes older log messages. Only history is lost; nothing on your PC stops working.",
                                   action_row("Keep only the newest", "Everything older than that goes.", size_dd, clean1),
                                   action_row("Or keep only the last", "Messages older than this are deleted.", days_dd, clean2)))
        # limit from now on
        cur = next((i for i, (mb, _t) in enumerate(LIMITS) if mb and limit and limit.upper().rstrip("B") in (f"{mb}M", f"{mb // 1024}G")), 0)
        lim_dd = Gtk.DropDown.new_from_strings([t for _, t in LIMITS])
        lim_dd.set_selected(cur)
        apply = button("Apply", css="suggested-action", on_click=lambda: self.set_limit(LIMITS[lim_dd.get_selected()][0]))
        r = action_row("Keep logs under", "Ubuntu's default is up to 10% of the disk (max 4 GB). Saved in "
                       "/etc/systemd/journald.conf.d/pc-size.conf, so it lasts.", lim_dd, apply)
        self.size_box.append(group("Always keep logs small", "Old messages are deleted automatically once the logs reach this size. "
                                   "500 MB keeps a few weeks of history on most PCs.", r))

    def vacuum(self, size_mb: int | None = None, days: int | None = None) -> None:
        what = f"the newest {size_mb} MB" if size_mb else f"the last {days} days"
        self.run("Clean up old logs", logs.vacuum_steps(size_mb, days), f"Keeps {what} of system logs and deletes the rest.", ok_label="Clean up",
                 reload=False, done=lambda ok: self.load_size())

    def set_limit(self, mb: int) -> None:
        if mb:
            self.run(f"Keep logs under {mb} MB", logs.limit_steps(mb), "The log service restarts for a second (nothing else is affected).",
                     ok_label="Apply", reload=False, done=lambda ok: self.load_size())
        else:
            self.run("Back to Ubuntu's default log size", logs.limit_steps(None), "Removes the limit this app added.", ok_label="Apply",
                     reload=False, done=lambda ok: self.load_size())

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

    # ---------------------------------------------------------------- command palette
    def palette_action(self, key: str) -> None:
        if key == "kernel":
            self.stack.set_visible_child_name("kernel")
        elif key == "live":
            self.stack.set_visible_child_name("all")
            self.live_switch.set_active(True)
        elif key == "size":
            self.stack.set_visible_child_name("size")


PAGE = LogsPage
