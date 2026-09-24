from __future__ import annotations

import asyncio
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, LoadingIndicator, Select, Switch, TabbedContent, TabPane

from ...core import logs
from ...core.fmt import C, human
from ..widgets import Btn, Choice, Panel, SearchInput, SortTable, muted, plain

PRIO_STYLE = {0: C["red"], 1: C["red"], 2: C["red"], 3: C["maroon"], 4: C["peach"], 5: C["yellow"]}


class LogsPanel(Panel):
    PANEL_ID = "logs"
    TITLE = "Logs"
    ICON = "󰌱"
    PLAIN_ICON = "¶"
    HELP = "Errors grouped by where they came from. Enter shows the full messages"

    DEFAULT_CSS = """
    LogsPanel .toolbar Select { width: 24; }
    LogsPanel .toolbar Label { margin: 0 1; }
    LogsPanel TabbedContent { height: 1fr; }
    LogsPanel TabPane { padding: 0; }
    LogsPanel LoadingIndicator { height: 3; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lines: list[logs.LogLine] = []

    def compose(self) -> ComposeResult:
        yield from self.head()
        with TabbedContent():
            with TabPane("Errors", id="t-err"):
                with Horizontal(classes="toolbar"):
                    yield Choice([("Since this boot", "boot"), ("Previous boot", "previous"), ("Last hour", "-1h"), ("Today", "today"), ("Last 7 days", "-7d")],
                                 value="boot", allow_blank=False, id="since")
                    yield Choice([("Errors", "3"), ("Errors + warnings", "4"), ("Critical only", "2")], value="3", allow_blank=False, id="prio")
                    yield SearchInput(placeholder="Search messages…", id="grep")
                    yield Label("Hide noise")
                    yield Switch(value=True, id="noise")
                yield LoadingIndicator()
                yield SortTable([("worst", "Level"), ("source", "Source"), ("count", "Count"), ("last", "Last seen"), ("msg", "Latest message")],
                                sort="count", id="groups", empty="No errors ✓")
                yield Label("", id="foot", classes="hint")
            with TabPane("Crash reports", id="t-crash"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Show report", id="show-crash", variant="primary")
                    yield Btn("Refresh", id="ref-crash")
                yield SortTable([("app", "App"), ("time", "When"), ("size", "Size")], sort="time", id="crashes", empty="No crash reports ✓")
            with TabPane("Restarts", id="t-boots"):
                yield SortTable([("index", "#"), ("start", "Started"), ("end", "Ended")], sort="index", id="boots", empty="Restart history isn't available")

    def load(self) -> None:
        self.fetch()
        self.fetch_crashes()

    def _args(self) -> tuple[str, int, str]:
        since = self.query_one("#since", Select).value
        if since == "today":
            since = time.strftime("%Y-%m-%d 00:00")
        return since, int(self.query_one("#prio", Select).value), self.query_one("#grep", Input).value.strip()

    def fetch(self) -> None:
        self.query_one(LoadingIndicator).display = True
        since, prio, grep = self._args()
        self._fetch(since, prio, grep)

    @work(thread=True, exclusive=True, group="logs")
    def _fetch(self, since: str, prio: int, grep: str) -> None:
        lines = logs.entries(since=since, max_priority=prio, grep=grep)
        self.app.call_from_thread(self.show, lines)

    def show(self, lines: list[logs.LogLine]) -> None:
        self.query_one(LoadingIndicator).display = False
        self.lines = lines
        hide = self.query_one("#noise", Switch).value
        groups = logs.grouped(lines, hide_noise=hide)
        rows = []
        for g in groups:
            name = logs.PRIORITY.get(g["worst"], "?")
            rows.append((g["source"], {"worst": -g["worst"], "source": g["source"].lower(), "count": g["count"], "last": g["last"], "msg": g["message"], "src": g["source"]},
                         [Text(name, style=PRIO_STYLE.get(g["worst"], C["subtext0"])), Text(g["source"], style="bold"), Text(str(g["count"])),
                          muted(logs.fmt_time(g["last"])), plain(g["message"][:140].replace("\n", " "))]))
        self.query_one("#groups", SortTable).set_rows(rows)
        hidden = len(lines) - sum(g["count"] for g in groups)
        self.query_one("#foot", Label).update(
            f"{len(lines)} messages from {len(groups)} sources" + (f" · {hidden} known-harmless messages hidden" if hidden else "")
            + " · a few errors are normal on every Linux PC")

    @on(Select.Changed)
    @on(Input.Submitted, "#grep")
    def _refetch(self) -> None:
        if self.loaded:
            self.fetch()

    @on(Switch.Changed, "#noise")
    def _noise(self) -> None:
        self.show(self.lines)

    @on(SortTable.RowSelected, "#groups")
    def _open(self) -> None:
        g = self.query_one("#groups", SortTable).selected()
        if not g:
            return
        items = [ln for ln in self.lines if ln.source == g["src"]]
        text = "\n".join(f"{time.strftime('%d %b %H:%M:%S', time.localtime(ln.time))}  [{logs.PRIORITY.get(ln.priority, ln.priority)}]  {ln.message}" for ln in items[-500:])
        self.show_text(f"{g['src']} - {len(items)} messages", text)

    @work(thread=True, exclusive=True, group="crash")
    def fetch_crashes(self) -> None:
        c, b = logs.crashes(), logs.boots()
        self.app.call_from_thread(self.show_crashes, c, b)

    def show_crashes(self, crashes: list[dict], boots: list[dict]) -> None:
        self.crash_items = crashes
        self.query_one("#crashes", SortTable).set_rows([
            (str(i), {"app": c["app"], "time": c["time"], "size": c["size"], "file": c["file"]},
             [Text(c["app"], style="bold"), muted(logs.fmt_time(c["time"])), muted(human(c["size"]) if c["size"] else "")]) for i, c in enumerate(crashes)])
        self.query_one("#boots", SortTable).set_rows([
            (b["id"], {"index": b["index"], "start": b["start"], "end": b["end"]}, [Text(str(b["index"])), plain(b["start"]), plain(b["end"])]) for b in boots])

    @on(Button.Pressed, "#ref-crash")
    def _refc(self) -> None:
        self.fetch_crashes()

    @on(Button.Pressed, "#show-crash")
    @on(SortTable.RowSelected, "#crashes")
    @work
    async def _showc(self) -> None:
        c = self.query_one("#crashes", SortTable).selected()
        if not c or not c.get("file"):
            return
        from ...core.run import read
        text = await asyncio.to_thread(read, c["file"])
        head = "\n".join(ln for ln in text.splitlines() if not ln.startswith(" ") and len(ln) < 400)[:20000]
        self.show_text(f"Crash report: {c['app']}", head)
