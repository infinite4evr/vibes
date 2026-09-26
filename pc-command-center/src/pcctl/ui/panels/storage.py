from __future__ import annotations

import os
import subprocess

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Label, LoadingIndicator, Static

from ...core import storage, system
from ...core.fmt import C, bar, human
from ...core.run import HOME, Step, has
from ..widgets import Btn, Panel, SortTable, muted, plain


class StoragePanel(Panel):
    PANEL_ID = "storage"
    TITLE = "Storage"
    ICON = "󰋊"
    PLAIN_ICON = "▤"
    HELP = "Enter opens a folder · Backspace goes up · d moves to Trash"

    BINDINGS = [
        Binding("backspace", "up", "Up"),
        Binding("d", "trash", "Move to Trash"),
        Binding("o", "open", "Open"),
        Binding("b", "big", "Big files"),
    ]

    DEFAULT_CSS = """
    StoragePanel #mounts { height: auto; margin-bottom: 1; }
    StoragePanel #crumb { color: $accent; text-style: bold; margin-bottom: 0; }
    StoragePanel LoadingIndicator { height: 3; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.path = str(HOME)
        self.cache: dict[str, tuple[int, list[storage.Entry]]] = {}
        self.mode = "folders"

    def compose(self) -> ComposeResult:
        yield from self.head()
        yield Static(id="mounts")
        with Horizontal(classes="toolbar"):
            yield Btn("Up", id="up")
            yield Btn("Home", id="home")
            yield Btn("/", id="root")
            yield Btn("Big files", id="big")
            yield Btn("Open", id="open")
            yield Btn("To Trash", id="trash", variant="error")
            if has("gdu"):
                yield Btn("gdu", id="gdu")
        yield Label("", id="crumb")
        yield LoadingIndicator(id="loading")
        yield SortTable([("name", "Name"), ("size", "Size"), ("pct", "Share"), ("hint", "What it is")], sort="size", empty="Empty folder")

    def load(self) -> None:
        mt = Text()
        for i, m in enumerate(system.mounts()):
            if i:
                mt.append("\n")
            mt.append_text(Text.from_markup(f"[b]{m.mountpoint:<16}[/b] {bar(m.pct, 30, 80, 90)} {m.pct:3.0f}%  {human(m.used)} used · [b]{human(m.free)} free[/b] of {human(m.total)}  [dim]{m.fstype}[/dim]"))
        self.query_one("#mounts", Static).update(mt)
        self.cache.pop(self.path, None)
        self.open_path(self.path)

    def open_path(self, path: str) -> None:
        self.mode = "folders"
        self.path = path
        self.query_one("#crumb", Label).update(Text(f" {path.replace(str(HOME), '~', 1) or '/'}"))
        if path in self.cache:
            self.show(*self.cache[path])
            return
        self.query_one("#loading").display = True
        self.query_one(SortTable).display = False
        self.scan(path)

    @work(thread=True, exclusive=True, group="scan")
    def scan(self, path: str) -> None:
        total, items = storage.children(path, timeout=600 if path == "/" else 300)
        self.cache[path] = (total, items)
        self.app.call_from_thread(self._scanned, path)

    def _scanned(self, path: str) -> None:
        if path == self.path and self.mode == "folders":
            self.show(*self.cache[path])

    def show(self, total: int, items: list[storage.Entry]) -> None:
        self.query_one("#loading").display = False
        t = self.query_one(SortTable)
        t.display = True
        rows = []
        for e in items:
            pct = e.size / total * 100 if total else 0
            name = Text(("▸ " if e.is_dir else "  ") + e.name, style=f"bold {C['blue']}" if e.is_dir else "")
            rows.append((e.path, {"name": e.name.lower(), "size": e.size, "pct": pct, "hint": "", "path": e.path, "dir": e.is_dir},
                         [name, Text(human(e.size), style="bold" if pct > 20 else ""), Text.from_markup(f"{bar(pct, 16, 101, 101)} {pct:4.1f}%"),
                          muted(storage.hint_for(e.path))]))
        t.set_rows(rows)
        t.focus()
        self.query_one("#crumb", Label).update(f" {escape(self.path.replace(str(HOME), '~', 1) or '/')}   [b]{human(total)}[/b] total")

    @on(SortTable.RowSelected)
    def _enter(self) -> None:
        sel = self.query_one(SortTable).selected()
        if sel and sel.get("dir"):
            self.open_path(sel["path"])

    def action_up(self) -> None:
        if self.mode != "folders":
            self.open_path(self.path)
            return
        parent = os.path.dirname(self.path.rstrip("/")) or "/"
        if parent != self.path:
            self.open_path(parent)

    @on(Button.Pressed, "#up")
    def _up(self) -> None:
        self.action_up()

    @on(Button.Pressed, "#home")
    def _home(self) -> None:
        self.open_path(str(HOME))

    @on(Button.Pressed, "#root")
    def _root(self) -> None:
        self.open_path("/")

    @on(Button.Pressed, "#big")
    def action_big(self) -> None:
        self.mode = "big"
        self.query_one("#crumb", Label).update(" Files over 500 MB in your home folder (searching…)")
        self.query_one("#loading").display = True
        self.query_one(SortTable).display = False
        self.find_big()

    @work(thread=True, exclusive=True, group="scan")
    def find_big(self) -> None:
        items = storage.big_files(HOME, 500, 60)
        self.app.call_from_thread(self._show_big, items)

    def _show_big(self, items: list[storage.Entry]) -> None:
        if self.mode != "big":
            return
        self.query_one("#loading").display = False
        t = self.query_one(SortTable)
        t.display = True
        t.set_rows([(e.path, {"name": e.name.lower(), "size": e.size, "pct": 0, "hint": "", "path": e.path, "dir": False},
                     [plain(e.path.replace(str(HOME), "~", 1)), Text(human(e.size), style="bold"), muted(""), muted(storage.hint_for(e.path))]) for e in items])
        self.query_one("#crumb", Label).update(f" {len(items)} files over 500 MB · Backspace to go back to folders")
        t.focus()

    @on(Button.Pressed, "#open")
    def action_open(self) -> None:
        sel = self.query_one(SortTable).selected()
        target = sel["path"] if sel and sel.get("dir") else (os.path.dirname(sel["path"]) if sel else self.path)
        if has("xdg-open"):
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            self.app.notify("xdg-open isn't available")

    @on(Button.Pressed, "#trash")
    def _trash(self) -> None:
        self.action_trash()

    @work
    async def action_trash(self) -> None:
        sel = self.query_one(SortTable).selected()
        if not sel:
            return
        path = sel["path"]
        if not path.startswith(str(HOME) + "/"):
            self.app.notify("Only files inside your home folder can be moved to Trash from here.", severity="warning")
            return
        ok = await self.run(f"Move {os.path.basename(path)} to Trash", [Step("Move to Trash", ["gio", "trash", path])],
                            f"{human(sel['size'])} goes to the Trash. You can restore it from the Files app until you empty the Trash.", reload=False)
        if ok:
            self.cache.pop(self.path, None)
            parent = os.path.dirname(path)
            for k in list(self.cache):
                if parent.startswith(k):
                    self.cache.pop(k, None)
            if self.mode == "big":
                self.action_big()
            else:
                self.open_path(self.path)

    @on(Button.Pressed, "#gdu")
    def _gdu(self) -> None:
        with self.app.suspend():
            subprocess.call(["gdu", self.path])
