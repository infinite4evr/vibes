from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, LoadingIndicator, SelectionList, Static
from textual.widgets.selection_list import Selection

from ...core import junk
from ...core.fmt import C, human
from ..widgets import Btn, Panel, PickScreen


class CleanupPanel(Panel):
    PANEL_ID = "cleanup"
    TITLE = "Cleanup"
    ICON = "󰃢"
    PLAIN_ICON = "✧"
    HELP = "Tick what to remove. Deep scan also finds old projects, versions and downloads"

    DEFAULT_CSS = """
    CleanupPanel #body { height: 1fr; }
    CleanupPanel SelectionList { width: 3fr; height: 1fr; }
    CleanupPanel #detail-box { width: 2fr; height: 1fr; border: round $surface-lighten-2; padding: 0 1; margin-left: 1; }
    CleanupPanel #summary { text-style: bold; color: $success; margin-bottom: 1; }
    CleanupPanel LoadingIndicator { height: 3; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.junks: dict[str, junk.Junk] = {}
        self.chosen: dict[str, list[str]] = {}
        self.deep = False

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(classes="toolbar"):
            yield Btn("Clean selected", id="clean", variant="primary")
            yield Btn("Rescan", id="scan")
            yield Btn("Deep scan", id="deep")
            yield Btn("Choose items…", id="pick")
        yield Label("Scanning…", id="summary")
        yield LoadingIndicator()
        with Horizontal(id="body"):
            yield SelectionList()
            with VerticalScroll(id="detail-box"):
                yield Static("Select a category to see what's in it and the exact commands.", id="detail")

    def load(self) -> None:
        self.query_one(LoadingIndicator).display = True
        self.query_one("#summary", Label).update("Scanning… (deep scan also walks your projects)" if self.deep else "Scanning…")
        self.scan()

    @work(thread=True, exclusive=True, group="junk")
    def scan(self) -> None:
        res = junk.scan(deep=self.deep)
        self.app.call_from_thread(self.show, res)

    def show(self, res: list[junk.Junk]) -> None:
        self.query_one(LoadingIndicator).display = False
        self.junks = {j.id: j for j in res}
        sl = self.query_one(SelectionList)
        sl.clear_options()
        for j in res:
            sl.add_option(Selection(self._label(j), j.id, j.default and not j.pick))
        self._summary()
        if res:
            self._detail(res[0].id)
        total = sum(j.size or 0 for j in res)
        self.app.set_badge("cleanup", 1 if total > 1024**3 else 0)

    def _label(self, j: junk.Junk) -> Text:
        size = "?" if j.size is None else human(j.size)
        t = Text(f"{size:>9}  ", style=f"bold {C['peach']}" if (j.size or 0) > 1024**3 else C["subtext0"])
        t.append(j.title, style="bold" if (j.size or 0) > 500 * 1024**2 else "")
        if j.pick:
            n = len(self.chosen.get(j.id, []))
            t.append(f"   {n} chosen" if n else "   choose items…", style=C["overlay1"])
        elif j.root:
            t.append("   admin", style=C["overlay1"])
        return t

    def _summary(self) -> None:
        sel = self.query_one(SelectionList).selected
        total = 0
        for jid in sel:
            j = self.junks.get(jid)
            if not j:
                continue
            if j.pick:
                keys = set(self.chosen.get(jid, []))
                total += sum(i.size for i in j.items if i.key in keys)
            else:
                total += j.size or 0
        found = sum(j.size or 0 for j in self.junks.values())
        self.query_one("#summary", Label).update(f"Found {human(found)} you could free · {human(total)} selected")

    @on(SelectionList.SelectionHighlighted)
    def _hl(self, e: SelectionList.SelectionHighlighted) -> None:
        self._detail(e.selection.value)

    @on(SelectionList.SelectedChanged)
    def _changed(self) -> None:
        sl = self.query_one(SelectionList)
        for jid in sl.selected:
            j = self.junks.get(jid)
            if j and j.pick and not self.chosen.get(jid):
                self.pick(jid)
                break
        self._summary()

    def _detail(self, jid: str) -> None:
        j = self.junks.get(jid)
        if not j:
            return
        t = Text()
        t.append(j.title + "\n", style=f"bold {C['mauve']}")
        t.append(j.desc + "\n\n")
        if j.items:
            t.append("What's in it\n", style="bold")
            for i in sorted(j.items, key=lambda i: -i.size)[:25]:
                mark = ""
                if j.pick:
                    mark = "☑ " if i.key in self.chosen.get(j.id, []) else "☐ "
                t.append(f"  {mark}{i.label}", style=C["text"])
                if i.size:
                    t.append(f"  {human(i.size)}", style=C["subtext0"])
                if i.note:
                    t.append(f"  {i.note}", style=C["overlay1"])
                t.append("\n")
            if len(j.items) > 25:
                t.append(f"  … and {len(j.items) - 25} more\n", style=C["overlay1"])
            t.append("\n")
        steps = j.steps_for(self.chosen.get(j.id) if j.pick else None)
        if steps:
            t.append("Commands\n", style="bold")
            for s in steps:
                t.append(f"  $ {s.display()}\n", style=C["overlay1"])
        elif j.pick:
            t.append("Press 'Choose items…' to pick which ones to remove.\n", style=C["peach"])
        self.query_one("#detail", Static).update(t)

    @on(Button.Pressed, "#pick")
    def _pick_btn(self) -> None:
        sl = self.query_one(SelectionList)
        if sl.highlighted is None:
            return
        jid = sl.get_option_at_index(sl.highlighted).value
        if self.junks.get(jid) and self.junks[jid].items:
            self.pick(jid)

    @work
    async def pick(self, jid: str) -> None:
        j = self.junks[jid]
        opts = [(f"{i.label}   {human(i.size)}" + (f"   ({i.note})" if i.note else ""), i.key, i.key in self.chosen.get(jid, [])) for i in j.items]
        res = await self.app.push_screen_wait(PickScreen(f"Choose: {j.title}", opts, j.desc))
        sl = self.query_one(SelectionList)
        if res is not None:
            self.chosen[jid] = res
        if not self.chosen.get(jid):
            sl.deselect(jid)
        else:
            sl.select(jid)
        idx = next((n for n in range(sl.option_count) if sl.get_option_at_index(n).value == jid), None)
        if idx is not None:
            sl.replace_option_prompt_at_index(idx, self._label(j))
        self._detail(jid)
        self._summary()

    @on(Button.Pressed, "#scan")
    def _scan(self) -> None:
        self.load()

    @on(Button.Pressed, "#deep")
    def _deep(self) -> None:
        self.deep = True
        self.load()

    @on(Button.Pressed, "#clean")
    def _clean_btn(self) -> None:
        self.clean()

    @work
    async def clean(self) -> None:
        steps = []
        titles = []
        for jid in self.query_one(SelectionList).selected:
            j = self.junks.get(jid)
            if not j:
                continue
            chosen = self.chosen.get(jid) if j.pick else None
            s = j.steps_for(chosen)
            if s:
                steps += s
                titles.append(j.title)
        if not steps:
            self.app.notify("Tick at least one category first.")
            return
        ok = await self.run("Clean up", steps, "Removing: " + ", ".join(titles) + ".")
        if ok:
            self.chosen = {}
