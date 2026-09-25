"""Processes: live table grouped by app, end / force quit / pause / priority / details."""

from __future__ import annotations

import os
import signal
import time

import psutil
from gi.repository import Gtk

from ...core import system
from ...core.fmt import human
from ...core.run import Step
from ..util import button, flow, hbox, label, open_path, vbox
from ..widgets import Column, DataTable, MiniBar, card
from .base import Page

ME = os.environ.get("USER") or psutil.Process().username()


class ProcessesPage(Page):
    ID = "processes"
    TITLE = "Processes"
    ICON = "view-list-bullet-symbolic"
    SUBTITLE = "Everything running right now. Helpers are grouped under their app."
    AUTO_REFRESH = 2.0
    SCROLL = False

    def build(self) -> None:
        self.watcher = system.ProcessWatcher()
        self.paused = False
        self.mode = 0
        self.header()

        # stats strip
        self.cpu_bar, self.mem_bar, self.swap_bar = MiniBar(warn=60, crit=85), MiniBar(warn=75, crit=90), MiniBar(warn=40, crit=80)
        self.cpu_txt, self.mem_txt, self.swap_txt, self.count_txt = (label("", "mid-num", ellipsize=True) for _ in range(4))
        self.threads_txt = label("", "dim")
        tiles = []
        for title, txt, bar in (("CPU", self.cpu_txt, self.cpu_bar), ("MEMORY", self.mem_txt, self.mem_bar), ("SWAP", self.swap_txt, self.swap_bar),
                                ("RUNNING", self.count_txt, self.threads_txt)):
            c = card(txt, bar, title=title, spacing=4)
            c.set_hexpand(True)
            tiles.append(c)
        self.body.append(flow(*tiles, spacing=12, min_per_line=2, homogeneous=True))

        # toolbar
        self.search_entry = Gtk.SearchEntry(placeholder_text="Find a process… (Ctrl+F)")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.table.set_filter(e.get_text()))
        self.mode_dd = Gtk.DropDown.new_from_strings(["Apps (grouped)", "All processes", "Only mine", "Tree (who started what)"])
        self.mode_dd.connect("notify::selected", self._mode)
        self.pause_btn = Gtk.ToggleButton(icon_name="media-playback-pause-symbolic", tooltip_text="Freeze the list")
        self.pause_btn.connect("toggled", lambda b: setattr(self, "paused", b.get_active()))
        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="More actions")
        pop = Gtk.Popover()
        items = vbox(spacing=2)
        for text, fn in (("Efficiency mode (lowest priority)", self.efficiency),
                         ("Pause (freeze) app", lambda: self.signal(signal.SIGSTOP)), ("Resume app", lambda: self.signal(signal.SIGCONT)),
                         ("Lower priority (be nice)", lambda: self.renice(10)), ("Normal priority", lambda: self.renice(0)),
                         ("Higher priority", lambda: self.renice(-5)), ("Open its folder", self.open_folder), ("Copy command", self.copy_cmd)):
            b = button(text, css="flat")
            b.connect("clicked", lambda _b, f=fn: (pop.popdown(), f()))
            items.append(b)
        pop.set_child(items)
        more.set_popover(pop)
        self.body.append(hbox(self.search_entry, self.mode_dd, self.pause_btn,
                              button("Details", icon="dialog-information-symbolic", on_click=self.details),
                              button("End", icon="window-close-symbolic", tooltip="Ask it to close (Delete)", on_click=lambda: self.signal(signal.SIGTERM)),
                              button("Force quit", icon="process-stop-symbolic", css="destructive-action", tooltip="Kill it now; unsaved work is lost",
                                     on_click=lambda: self.signal(signal.SIGKILL)), more, spacing=8))

        self.table = DataTable([
            Column("name", "Name", "bold", width=230),
            Column("count", "#", "num", width=48, fmt=lambda v, d: str(v) if v and v > 1 else ""),
            Column("cpu", "CPU", "bar", width=130, fmt=lambda v, d: f"{(v or 0) * 100:.1f}%"),
            Column("mem", "Memory", "size", width=96),
            Column("io", "Disk", "num", width=86, fmt=lambda v, d: (human(v) + "/s") if v and v >= 1024 else ""),
            Column("user", "User", "muted", width=110),
            Column("pid", "PID", "num", width=74, fmt=lambda v, d: str(v) if v else ""),
            Column("cmd", "Command", "mono", expand=True),
        ], on_activate=lambda r: self.details(), empty="No processes match.", sort="cpu",
            search=lambda d, q: q in d["name"].lower() or q in d["cmd"].lower() or q == str(d.get("pid")))
        self.table.set_vexpand(True)
        self.table.set_context(self._row_menu, "processes")
        self.body.append(self.table)
        self.hint = label("Double-click a row for details. End asks nicely; Force quit doesn't wait.", "dim")
        self.body.append(self.hint)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._key)
        self.table.add_controller(key)

    def _row_menu(self, _row: dict) -> list:
        return [("Details", lambda r: self.details()), ("End", lambda r: self.signal(signal.SIGTERM)),
                ("Force quit", lambda r: self.signal(signal.SIGKILL)), ("Efficiency mode (lowest priority)", lambda r: self.efficiency()),
                ("Pause (freeze)", lambda r: self.signal(signal.SIGSTOP)), ("Resume", lambda r: self.signal(signal.SIGCONT)),
                ("Open its folder", lambda r: self.open_folder()), ("Copy command", lambda r: self.copy_cmd())]

    def efficiency(self) -> None:
        from ...core.diagnose import efficiency_steps
        r = self._sel()
        if not r:
            return
        pids = [p for p in r["pids"] if p not in (0, 1, 2, os.getpid())]
        if not pids:
            return
        self.run(f"Efficiency mode for {r['name']}", efficiency_steps(r["name"], pids, r["users"]),
                 "It keeps running, but only gets the CPU and disk when nothing else needs them - like Windows' efficiency mode. "
                 "Lasts until it's restarted.", ok_label="Turn on", reload=False, ask=any(u not in (ME, "?") for u in r["users"]),
                 done=lambda ok: ok and self.toast(f"{r['name']} is in efficiency mode."))

    def _key(self, _c, keyval, _code, _state) -> bool:
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Delete:
            self.signal(signal.SIGTERM)
            return True
        return False

    def _mode(self, dd, _p) -> None:
        self.mode = dd.get_selected()
        if self.mode == 3:  # keep tree order until the user clicks a column header
            self.table.view.sort_by_column(None, Gtk.SortType.ASCENDING)
        self.collect(force=True)

    def load(self) -> None:
        self.watcher.list()  # prime cpu counters
        self.collect(force=True)

    def tick(self) -> bool:
        self.collect()
        return True

    def collect(self, force: bool = False) -> None:
        if self.paused and not force:
            return
        self.bg(self.watcher.list, self.show)

    def show(self, procs: list[system.Proc]) -> None:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        cpu = sum(p.cpu for p in procs)
        self.cpu_txt.set_text(f"{min(cpu, 100):.0f}%")
        self.cpu_bar.set(cpu / 100)
        self.mem_txt.set_text(f"{human(vm.total - vm.available)} / {human(vm.total)}")
        self.mem_bar.set(vm.percent / 100)
        self.swap_txt.set_text(f"{human(sw.used)} / {human(sw.total)}" if sw.total else "no swap")
        self.swap_bar.set(sw.percent / 100 if sw.total else 0)
        self.count_txt.set_text(f"{len(procs)} processes")
        self.threads_txt.set_text(f"{sum(p.threads for p in procs)} threads")
        rows = []
        if self.mode == 0:
            by_pid = {p.pid: p for p in procs}
            for g in system.app_groups(procs):
                first = by_pid.get(g["pids"][0])
                users = {by_pid[p].user for p in g["pids"] if p in by_pid}
                rows.append({"key": f"g:{g['name']}", "name": g["name"], "count": g["count"], "cpu": g["cpu"] / 100, "mem": g["mem"],
                             "io": sum(by_pid[p].io for p in g["pids"] if p in by_pid),
                             "user": ", ".join(sorted(users))[:30], "pid": g["pids"][0] if g["count"] == 1 else 0,
                             "cmd": first.cmd if first else "", "pids": g["pids"], "users": users})
        elif self.mode == 3:
            rows = self._tree_rows(procs)
        else:
            for p in procs:
                if self.mode == 2 and p.user != ME:
                    continue
                rows.append({"key": f"p:{p.pid}", "name": p.name, "count": 1, "cpu": p.cpu / 100, "mem": p.mem, "user": p.user, "pid": p.pid,
                             "io": p.io, "cmd": p.cmd, "pids": [p.pid], "users": {p.user}})
        self.table.set_rows(rows)

    def _tree_rows(self, procs: list[system.Proc]) -> list[dict]:
        """Parent → children order with indented names. Sorting by a column header flattens it again."""
        by_pid = {p.pid: p for p in procs}
        kids: dict[int, list] = {}
        for p in procs:
            kids.setdefault(p.ppid if p.ppid in by_pid else 0, []).append(p)
        rows: list[dict] = []

        def walk(pid: int, depth: int) -> None:
            for c in sorted(kids.get(pid, []), key=lambda x: -x.mem):
                prefix = ("    " * (depth - 1) + "└─ ") if depth else ""
                sub = self._subtree(c.pid, kids)
                rows.append({"key": f"t:{c.pid}", "name": prefix + c.name, "count": len(sub), "cpu": c.cpu / 100, "mem": c.mem, "io": c.io,
                             "user": c.user, "pid": c.pid, "cmd": c.cmd, "pids": [c.pid], "users": {c.user}})
                walk(c.pid, depth + 1)
        walk(0, 0)
        return rows

    @staticmethod
    def _subtree(pid: int, kids: dict) -> list[int]:
        out, stack = [pid], [pid]
        while stack:
            for c in kids.get(stack.pop(), []):
                out.append(c.pid)
                stack.append(c.pid)
        return out

    # ---------------------------------------------------------------- actions
    def _sel(self) -> dict | None:
        r = self.table.selected()
        if not r:
            self.toast("Select a process first.")
        return r

    def signal(self, sig: signal.Signals) -> None:
        r = self._sel()
        if not r:
            return
        pids = [p for p in r["pids"] if p not in (0, 1, 2, os.getpid())]
        if not pids or r["name"] in ("systemd", "kthreadd", "gnome-shell", "Xwayland", "gdm-wayland-session", "gnome-session-binary"):
            self.toast("That's part of Ubuntu itself and shouldn't be stopped.")
            return
        others = any(u not in (ME, "?") for u in r["users"])
        force = sig == signal.SIGKILL
        verb = {signal.SIGTERM: "End", signal.SIGKILL: "Force quit", signal.SIGSTOP: "Pause", signal.SIGCONT: "Resume"}[sig]
        n = len(pids)
        explain = {signal.SIGTERM: "The app gets a chance to close cleanly.", signal.SIGKILL: "Stops it immediately. Unsaved work is lost.",
                   signal.SIGSTOP: "Freezes it (uses no CPU) until you resume it. Handy for a runaway build.",
                   signal.SIGCONT: "Lets a paused app continue."}[sig]
        explain = f"{verb} {r['name']} ({n} process{'es' if n != 1 else ''}). {explain}" + (" It belongs to another user, so your password is needed." if others else "")
        cmd = ["kill", f"-{int(sig)}", *map(str, pids)]
        self.run(f"{verb} {r['name']}", [Step(f"{verb} {r['name']}", cmd, root=others, ok_codes=(0, 1))], explain, danger=force,
                 ok_label=verb, reload=False, done=lambda ok: self.collect(force=True), ask=sig in (signal.SIGKILL,) or others or n > 1)

    def renice(self, value: int) -> None:
        r = self._sel()
        if not r:
            return
        root = value < 0 or any(u not in (ME, "?") for u in r["users"])
        cmd = ["renice", "-n", str(value), "-p", *map(str, r["pids"])]
        self.run(f"Set priority of {r['name']}", [Step(f"Priority {value:+d} for {r['name']}", cmd, root=root, ok_codes=(0, 1))],
                 "Lower priority means it only gets the CPU when others don't need it. Raising priority needs your password.",
                 ok_label="Change", reload=False)

    def open_folder(self) -> None:
        r = self._sel()
        if not r:
            return
        try:
            open_path(psutil.Process(r["pids"][0]).cwd())
        except psutil.Error:
            self.toast("Can't see that process's folder.")

    def copy_cmd(self) -> None:
        r = self._sel()
        if r:
            self.get_clipboard().set(r["cmd"])
            self.toast("Command copied.")

    def details(self) -> None:
        r = self._sel()
        if not r:
            return

        def work() -> str:
            lines = []
            for pid in r["pids"][:40]:
                try:
                    p = psutil.Process(pid)
                    with p.oneshot():
                        lines.append(f"PID {pid}  {p.name()}  ({p.status()})")
                        lines.append(f"  command : {' '.join(p.cmdline()) or '-'}")
                        try:
                            lines.append(f"  folder  : {p.cwd()}")
                        except psutil.AccessDenied:
                            pass
                        lines.append(f"  user    : {p.username()}   parent: {p.ppid()}   threads: {p.num_threads()}   nice: {p.nice()}")
                        lines.append(f"  memory  : {human(p.memory_info().rss)}   started: {time.strftime('%d %b %H:%M', time.localtime(p.create_time()))}")
                        try:
                            listening = sorted({c.laddr.port for c in p.net_connections(kind="inet") if c.status == "LISTEN"})
                            if listening:
                                lines.append(f"  ports   : {', '.join(map(str, listening))}")
                        except (psutil.AccessDenied, AttributeError):
                            pass
                        try:
                            io = p.io_counters()
                            lines.append(f"  disk    : read {human(io.read_bytes)}  written {human(io.write_bytes)}")
                        except (psutil.AccessDenied, AttributeError):
                            pass
                        try:
                            lines.append(f"  files   : {p.num_fds()} open")
                        except psutil.AccessDenied:
                            pass
                    lines.append("")
                except psutil.Error:
                    continue
            if len(r["pids"]) > 40:
                lines.append(f"… and {len(r['pids']) - 40} more processes")
            return "\n".join(lines)
        self.bg(work, lambda t: self.text(f"{r['name']}: details", t))


PAGE = ProcessesPage
