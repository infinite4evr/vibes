from __future__ import annotations

import os
import signal
import time

import psutil
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, Switch

from ...core import system
from ...core.fmt import C, duration, human, level_color
from ...core.run import Step
from ..widgets import Btn, Panel, SearchInput, SortTable, muted, plain


class ProcessesPanel(Panel):
    PANEL_ID = "processes"
    TITLE = "Processes"
    ICON = "󰍛"
    PLAIN_ICON = "≡"
    HELP = "What's running. Select a row, then End (k) or Force quit (K)"
    AUTO_REFRESH = 2.5

    BINDINGS = [
        Binding("k", "end", "End"),
        Binding("K", "kill", "Force quit"),
        Binding("space", "pause", "Pause"),
        Binding("slash", "search", "Search", show=False),
    ]

    DEFAULT_CSS = """
    ProcessesPanel .toolbar Label { margin: 0 1 0 2; }
        """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.watcher = system.ProcessWatcher()
        self.paused = False
        self.grouped = True
        self.procs: list[system.Proc] = []

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(classes="toolbar"):
            yield SearchInput(placeholder="Search by name or command…", id="filter")
            yield Label("Group by app")
            yield Switch(value=True, id="group")
            yield Btn("End", id="end")
            yield Btn("Force quit", id="kill", variant="error")
            yield Btn("Details", id="details")
        yield SortTable([("name", "Name"), ("count", "#"), ("cpu", "CPU"), ("mem", "Memory"), ("user", "User"),
                         ("pid", "PID"), ("age", "Running"), ("cmd", "Command")], sort="cpu")
        yield Label("", id="status", classes="hint")

    def load(self) -> None:
        self.tick()

    def tick(self) -> None:
        if not self.paused:
            self.collect()

    @work(thread=True, exclusive=True, group="procs")
    def collect(self) -> None:
        procs = self.watcher.list()
        self.app.call_from_thread(self.render_rows, procs)

    def render_rows(self, procs: list[system.Proc]) -> None:
        self.procs = procs
        q = self.query_one("#filter", Input).value.strip().lower()
        me = os.environ.get("USER", "")
        now = time.time()
        rows = []
        if self.grouped:
            groups: dict[str, dict] = {}
            for p in procs:
                if q and q not in p.name.lower() and q not in p.cmd.lower():
                    continue
                gname = "Linux kernel" if p.cmd.startswith("[") and p.user == "root" else p.name
                g = groups.setdefault(gname, {"name": gname, "cpu": 0.0, "mem": 0, "count": 0, "pids": [], "user": p.user, "start": p.started, "cmd": p.cmd})
                g["cpu"] += p.cpu
                g["mem"] += p.mem
                g["count"] += 1
                g["pids"].append(p.pid)
                g["start"] = min(g["start"], p.started)
            for g in groups.values():
                vals = {"name": g["name"].lower(), "count": g["count"], "cpu": g["cpu"], "mem": g["mem"], "user": g["user"],
                        "pid": g["pids"][0], "age": -g["start"], "cmd": g["cmd"], "pids": g["pids"], "label": g["name"]}
                rows.append((f"g:{g['name']}", vals, [
                    Text(g["name"], style="bold" if g["user"] == me else ""), muted(g["count"] if g["count"] > 1 else ""),
                    Text(f"{g['cpu']:5.1f}%", style=level_color(g["cpu"], 30, 70)), Text(human(g["mem"]), style=level_color(g["mem"] / 2**30 * 25, 50, 90)),
                    muted(g["user"]), muted(g["pids"][0]), muted(duration(now - g["start"]) if g["start"] else ""), plain(g["cmd"][:120])]))
        else:
            for p in procs:
                if q and q not in p.name.lower() and q not in p.cmd.lower():
                    continue
                vals = {"name": p.name.lower(), "count": 1, "cpu": p.cpu, "mem": p.mem, "user": p.user, "pid": p.pid,
                        "age": -p.started, "cmd": p.cmd, "pids": [p.pid], "label": p.name}
                rows.append((f"p:{p.pid}", vals, [
                    Text(p.name, style="bold" if p.user == me else ""), muted(""), Text(f"{p.cpu:5.1f}%", style=level_color(p.cpu, 30, 70)),
                    Text(human(p.mem)), muted(p.user), muted(p.pid), muted(duration(now - p.started) if p.started else ""), plain(p.cmd[:160])]))
        self.query_one(SortTable).set_rows(rows)
        total_cpu = sum(p.cpu for p in procs)
        self.query_one("#status", Label).update(
            f"{len(procs)} processes · {total_cpu:.0f}% CPU in use" + (" · paused (space to resume)" if self.paused else "") +
            " · click a column title to sort")

    @on(Input.Changed, "#filter")
    def _filter(self) -> None:
        self.render_rows(self.procs)

    @on(Switch.Changed, "#group")
    def _group(self, e: Switch.Changed) -> None:
        self.grouped = e.value
        self.render_rows(self.procs)

    @on(Button.Pressed, "#end")
    def _b_end(self) -> None:
        self.action_end()

    @on(Button.Pressed, "#kill")
    def _b_kill(self) -> None:
        self.action_kill()

    @on(Button.Pressed, "#details")
    @on(SortTable.RowSelected)
    def _b_details(self) -> None:
        self.action_details()

    def action_search(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.render_rows(self.procs)

    def action_end(self) -> None:
        self._signal(signal.SIGTERM)

    def action_kill(self) -> None:
        self._signal(signal.SIGKILL)

    @work
    async def _signal(self, sig: signal.Signals) -> None:
        sel = self.query_one(SortTable).selected()
        if not sel:
            return
        pids = [p for p in sel["pids"] if p not in (1, os.getpid())]
        if sel["label"] == "Linux kernel" or not pids:
            self.app.notify("That's part of Linux itself and can't be stopped.", severity="warning")
            return
        me = os.environ.get("USER", "")
        others = sel["user"] not in (me, "?")
        name = sel["label"]
        force = sig == signal.SIGKILL
        verb = "Force quit" if force else "End"
        explain = (f"{verb} {name} ({len(pids)} process{'es' if len(pids) != 1 else ''})."
                   + (" Force quit doesn't let the app save anything." if force else " The app gets a chance to close cleanly.")
                   + (" It belongs to another user, so admin rights are needed." if others else ""))
        cmd = ["kill", "-9" if force else "-15", *map(str, pids)]
        await self.run(f"{verb} {name}", [Step(f"{verb} {name}", cmd, root=others, ok_codes=(0, 1))], explain, danger=force, reload=False)
        self.collect()

    @work
    async def action_details(self) -> None:
        sel = self.query_one(SortTable).selected()
        if not sel:
            return
        lines = []
        for pid in sel["pids"][:30]:
            try:
                p = psutil.Process(pid)
                with p.oneshot():
                    lines.append(f"PID {pid}  {p.name()}  ({p.status()})")
                    lines.append(f"  command : {' '.join(p.cmdline()) or '-'}")
                    try:
                        lines.append(f"  folder  : {p.cwd()}")
                    except psutil.AccessDenied:
                        pass
                    lines.append(f"  user    : {p.username()}   parent: {p.ppid()}   threads: {p.num_threads()}")
                    lines.append(f"  memory  : {human(p.memory_info().rss)}   started: {time.strftime('%d %b %H:%M', time.localtime(p.create_time()))}")
                    try:
                        conns = p.net_connections(kind="inet")
                        listening = [f"{c.laddr.port}" for c in conns if c.status == "LISTEN"]
                        if listening:
                            lines.append(f"  ports   : {', '.join(sorted(set(listening)))}")
                    except (psutil.AccessDenied, AttributeError):
                        pass
                    try:
                        lines.append(f"  files   : {p.num_fds()} open")
                    except psutil.AccessDenied:
                        pass
                lines.append("")
            except psutil.Error:
                continue
        self.show_text(f"{sel['label']} - details", "\n".join(lines))
