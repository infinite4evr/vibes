"""Shared building blocks: tables, dialogs, the task runner, and the Panel base class."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any, Iterable, Sequence

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, RichLog, Select, SelectionList, Static, TextArea

from ..core.fmt import C
from ..core.run import Step, needs_root, stream, sudo_ready

LEVEL = {
    "ok": (C["green"], "●"),
    "info": (C["blue"], "●"),
    "warn": (C["peach"], "▲"),
    "bad": (C["red"], "■"),
}


def lvl(level: str, text: str = "") -> Text:
    color, sym = LEVEL.get(level, (C["overlay1"], "•"))
    t = Text(sym + (" " if text else ""), style=color)
    if text:
        t.append(text)
    return t


def plain(s: Any) -> Text:
    """Untrusted text (file names, commands) - never parsed as markup."""
    return Text(str(s))


def muted(s: Any) -> Text:
    return Text(str(s), style=C["overlay1"])


def colored(s: Any, color: str, bold: bool = False) -> Text:
    return Text(str(s), style=f"{'bold ' if bold else ''}{C.get(color, color)}")


# ---------------------------------------------------------------- compact controls


class Btn(Button):
    """One-line button (keeps toolbars light)."""

    def __init__(self, *a, **kw):
        kw.setdefault("compact", True)
        super().__init__(*a, **kw)


class SearchInput(Input):
    def __init__(self, *a, **kw):
        kw.setdefault("compact", True)
        super().__init__(*a, **kw)


class Choice(Select):
    def __init__(self, *a, **kw):
        kw.setdefault("compact", True)
        super().__init__(*a, **kw)


# ---------------------------------------------------------------- table


class SortTable(DataTable):
    """DataTable that sorts on header click and keeps the cursor on the same row across refreshes."""

    DEFAULT_CSS = "SortTable { height: 1fr; }"

    def __init__(self, columns: Sequence[tuple[str, str]], sort: str | None = None, reverse: bool = True, empty: str = "Nothing here", **kw):
        super().__init__(cursor_type="row", zebra_stripes=True, **kw)
        self.empty = empty
        self._cols = columns
        self.sort_key = sort
        self.sort_reverse = reverse
        self._raw: dict[str, dict] = {}

    def on_mount(self) -> None:
        for key, label in self._cols:
            self.add_column(label, key=key)

    def set_rows(self, rows: Iterable[tuple[str, dict, list]]) -> None:
        """rows: (row_key, sort_values_by_column, cells)."""
        current = None
        if self.row_count and self.cursor_row is not None:
            try:
                current = self.coordinate_to_cell_key((self.cursor_row, 0)).row_key.value
            except Exception:  # noqa: BLE001
                current = None
        rows = list(rows)
        if self.sort_key:
            rows.sort(key=lambda r: _sortable(r[1].get(self.sort_key)), reverse=self.sort_reverse)
        scroll = self.scroll_y
        self.clear()
        self._raw = {}
        for key, values, cells in rows:
            self._raw[key] = values
            self.add_row(*cells, key=key)
        if not rows:
            self.add_row(Text(self.empty, style=C["overlay1"]), *[""] * (len(self._cols) - 1), key="__empty__")
        if current is not None and current in self._raw:
            try:
                self.move_cursor(row=self.get_row_index(current), animate=False, scroll=False)
            except Exception:  # noqa: BLE001
                pass
        self.scroll_y = min(scroll, self.max_scroll_y)

    def selected_key(self) -> str | None:
        if not self.row_count:
            return None
        try:
            return self.coordinate_to_cell_key((self.cursor_row, 0)).row_key.value
        except Exception:  # noqa: BLE001
            return None

    def selected(self) -> dict | None:
        k = self.selected_key()
        return self._raw.get(k) if k not in (None, "__empty__") else None

    @on(DataTable.HeaderSelected)
    def _header(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key.value
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, True
        items = [(k, v, [self.get_cell(k, c.key) for c in self.columns.values()]) for k, v in self._raw.items()]
        self.set_rows(items)


def _sortable(v: Any) -> tuple:
    if v is None:
        return (0, 0)
    if isinstance(v, (int, float)):
        return (1, v)
    return (2, str(v).lower())


# ---------------------------------------------------------------- dialogs


class Dialog(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Close")]
    DEFAULT_CSS = """
    Dialog { align: center middle; }
    Dialog > Vertical { width: 90; max-width: 95%; height: auto; max-height: 90%; background: $surface; border: round $primary; padding: 1 2; }
    Dialog .d-title { text-style: bold; color: $primary; margin-bottom: 1; }
    Dialog .d-body { color: $foreground; margin-bottom: 1; }
    Dialog .d-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    Dialog .d-buttons Button { margin-left: 1; }
    """

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(Dialog):
    """Shows exactly what will run before anything changes."""

    DEFAULT_CSS = """
    ConfirmScreen .cmds { height: auto; max-height: 16; background: $panel; padding: 0 1; margin-bottom: 1; }
    ConfirmScreen .cmd { color: $text-muted; }
    ConfirmScreen .cmd-title { color: $foreground; }
    ConfirmScreen .note { color: $warning; }
    """

    def __init__(self, title: str, steps: list[Step], explain: str = "", danger: bool = False, ok_label: str = "Run"):
        super().__init__()
        self.t, self.steps, self.explain, self.danger, self.ok_label = title, steps, explain, danger, ok_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            if self.explain:
                yield Static(self.explain, classes="d-body", markup=False)
            with VerticalScroll(classes="cmds"):
                from ..core.action_preview import describe
                yield Static(describe(self.steps), markup=False, id="action-preview")
                for s in self.steps:
                    yield Static(Text("▸ " + s.title, style="bold"), classes="cmd-title")
                    yield Static(Text("  $ " + s.display()), classes="cmd")
            if needs_root(self.steps):
                yield Static("Needs your password (admin rights) - you'll be asked in the terminal if it isn't cached.", classes="note")
            with Horizontal(classes="d-buttons"):
                yield Button("Cancel", id="no")
                from ..core.action_preview import review
                yield Button(self.ok_label, id="yes", variant="error" if self.danger else "primary", disabled=not review(self.steps)["ready"])

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(False)


class TaskScreen(Dialog):
    """Runs steps one by one with live output."""

    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    TaskScreen > Vertical { width: 110; height: 34; }
    TaskScreen #steps { height: auto; max-height: 10; margin-bottom: 1; }
    TaskScreen RichLog { height: 1fr; background: $panel; border: none; }
    TaskScreen #result { height: auto; margin-top: 1; }
    """

    def __init__(self, title: str, steps: list[Step]):
        super().__init__()
        self.t, self.steps = title, steps
        self.done = False
        self.success = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            with VerticalScroll(id="steps"):
                for i, s in enumerate(self.steps):
                    yield Static(Text("○ " + s.title, style=C["overlay1"]), id=f"st{i}")
            yield RichLog(highlight=False, markup=False, wrap=True, max_lines=4000)
            yield Static("", id="result")
            with Horizontal(classes="d-buttons"):
                yield Button("Running…", id="close", disabled=True)

    def on_mount(self) -> None:
        self.run_all()

    @work(exclusive=True)
    async def run_all(self) -> None:
        log = self.query_one(RichLog)
        ok_all = True
        failed: list[str] = []
        for i, s in enumerate(self.steps):
            w = self.query_one(f"#st{i}", Static)
            w.update(Text("◐ " + s.title, style=f"bold {C['mauve']}"))
            log.write(Text(f"$ {s.display()}", style=C["mauve"]))
            code = await stream(s, lambda line: log.write(Text(line)))
            good = code in s.ok_codes
            if good:
                w.update(Text("✓ " + s.title, style=C["green"]))
            elif s.optional:
                w.update(Text(f"– {s.title} (skipped, exit {code})", style=C["overlay1"]))
            else:
                ok_all = False
                failed.append(s.title)
                w.update(Text(f"✗ {s.title} (exit {code})", style=C["red"]))
                if s.root and code == 1 and not sudo_ready():
                    log.write(Text("Admin rights expired - run it again and enter your password.", style=C["peach"]))
                break
        self.done, self.success = True, ok_all
        res = self.query_one("#result", Static)
        res.update(Text("Done." if ok_all else "Something went wrong - see the output above.", style=f"bold {C['green'] if ok_all else C['red']}"))
        btn = self.query_one("#close", Button)
        btn.label, btn.disabled = "Close", False
        btn.focus()
        if not ok_all:
            # The error dialog, with "Create GitHub issue", over the output.
            tail = "\n".join(line.text for line in log.lines[-40:])
            self.app.show_error(
                f"Action failed: {self.t}\n" + (f"Failed step: {', '.join(failed)}\n" if failed else "") + f"\nLast output:\n{tail}",
                where=f"pc (terminal app): {self.t}",
                context="Commands:\n" + "\n".join(f"  {s.display()}" for s in self.steps))

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        if self.done:
            self.dismiss(self.success)


class ErrorScreen(Dialog):
    """Every error in the terminal app: what went wrong, and "Create GitHub issue" (a pre-filled,
    redacted issue opened in the browser; the link is also shown, for terminals without one)."""

    DEFAULT_CSS = """
    ErrorScreen > Vertical { border: round $error; }
    ErrorScreen .d-title { color: $error; }
    ErrorScreen #err-msg { margin-bottom: 1; }
    ErrorScreen #err-more { color: $text-muted; margin-bottom: 1; }
    ErrorScreen #err-repeats { color: $text-muted; }
    """

    def __init__(self, error: str, where: str = "pc (terminal app)", context: str = ""):
        super().__init__()
        from ..core import bugreport
        self.rep = bugreport.Report(error, where, context)
        self.count = 1

    def compose(self) -> ComposeResult:
        from ..core import bugreport
        with Vertical():
            yield Label("Something went wrong", classes="d-title")
            yield Static(Text(bugreport.summary(self.rep.error), style="bold"), id="err-msg")
            yield Static("“Create GitHub issue” opens a pre-filled issue in your browser; you can read and edit everything "
                         "before you submit. Names, your home folder, network addresses and secrets are already removed.",
                         id="err-more", markup=False)
            yield Static("", id="err-repeats")
            with Horizontal(classes="d-buttons"):
                yield Button("Create GitHub issue", id="issue", variant="primary")
                yield Button("Copy details", id="copy")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.query_one("#issue", Button).focus()

    def add_repeat(self) -> None:
        self.count += 1
        self.query_one("#err-repeats", Static).update(f"Happened {self.count} times.")

    @on(Button.Pressed, "#issue")
    def _issue(self) -> None:
        import webbrowser
        url = self.rep.url()
        try:
            opened = webbrowser.open(url)
        except Exception:  # noqa: BLE001 - no browser
            opened = False
        if not opened:
            self.app.copy_to_clipboard(url)
            self.app.push_screen(TextScreen("Create GitHub issue", "No browser could be opened; the link was copied. "
                                            f"Open it in a browser:\n\n{url}"))

    @on(Button.Pressed, "#copy")
    def _copy(self) -> None:
        self.app.copy_to_clipboard(self.rep.full_text())
        self.query_one("#err-repeats", Static).update("Copied.")

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)


class TextScreen(Dialog):
    """Read-only text (logs, details). Select text with the mouse to copy it."""

    DEFAULT_CSS = """
    TextScreen > Vertical { width: 120; height: 90%; }
    TextScreen TextArea { height: 1fr; }
    """

    def __init__(self, title: str, text: str, language: str | None = None):
        super().__init__()
        self.t, self.text, self.language = title, text, language

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            ta = TextArea(self.text or "(nothing to show)", read_only=True, soft_wrap=True, show_line_numbers=False)
            if self.language:
                try:
                    ta.language = self.language
                except Exception:  # noqa: BLE001
                    pass
            yield ta
            with Horizontal(classes="d-buttons"):
                yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        ta = self.query_one(TextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)


class InputScreen(Dialog):
    def __init__(self, title: str, prompt: str = "", placeholder: str = "", password: bool = False, value: str = ""):
        super().__init__()
        self.t, self.prompt, self.placeholder, self.password, self.value = title, prompt, placeholder, password, value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            if self.prompt:
                yield Static(self.prompt, classes="d-body", markup=False)
            yield Input(value=self.value, placeholder=self.placeholder, password=self.password, id="inp")
            with Horizontal(classes="d-buttons"):
                yield Button("Cancel", id="no")
                yield Button("OK", id="yes", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#yes")
    def _ok(self) -> None:
        v = self.query_one(Input).value.strip()
        self.dismiss(v or None)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(None)


class PickScreen(Dialog):
    """Tick the items you want (e.g. which node_modules folders to delete)."""

    DEFAULT_CSS = "PickScreen SelectionList { height: auto; max-height: 24; }"

    def __init__(self, title: str, options: list[tuple[str, str, bool]], explain: str = ""):
        super().__init__()
        self.t, self.options, self.explain = title, options, explain

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            if self.explain:
                yield Static(self.explain, classes="d-body", markup=False)
            yield SelectionList(*[(Text(label), key, sel) for label, key, sel in self.options])
            with Horizontal(classes="d-buttons"):
                yield Button("None", id="none")
                yield Button("All", id="all")
                yield Button("Cancel", id="no")
                yield Button("Done", id="yes", variant="primary")

    @on(Button.Pressed, "#all")
    def _all(self) -> None:
        self.query_one(SelectionList).select_all()

    @on(Button.Pressed, "#none")
    def _none(self) -> None:
        self.query_one(SelectionList).deselect_all()

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(list(self.query_one(SelectionList).selected))

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(None)


class ChoiceScreen(Dialog):
    """Pick one row from a table."""

    DEFAULT_CSS = "ChoiceScreen > Vertical { width: 120; height: 80%; } ChoiceScreen DataTable { height: 1fr; }"

    def __init__(self, title: str, columns: list[str], rows: list[tuple[str, list]], explain: str = ""):
        super().__init__()
        self.t, self.columns, self.rows, self.explain = title, columns, rows, explain

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.t, classes="d-title")
            if self.explain:
                yield Static(self.explain, classes="d-body", markup=False)
            yield DataTable(cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="d-buttons"):
                yield Button("Cancel", id="no")
                yield Button("Choose", id="yes", variant="primary")

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns(*self.columns)
        for key, cells in self.rows:
            t.add_row(*cells, key=key)
        t.focus()

    def _pick(self) -> None:
        t = self.query_one(DataTable)
        if t.row_count:
            self.dismiss(t.coordinate_to_cell_key((t.cursor_row, 0)).row_key.value)
        else:
            self.dismiss(None)

    @on(DataTable.RowSelected)
    def _row(self) -> None:
        self._pick()

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self._pick()

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- running actions


async def ensure_sudo(app) -> bool:
    if await asyncio.to_thread(sudo_ready):
        return True
    try:
        with app.suspend():
            print("\n\033[1;38;2;203;166;247mpc needs admin rights for this.\033[0m Enter your password (the one you log in with):\n")
            subprocess.call(["sudo", "-v"])
    except Exception:  # noqa: BLE001 - e.g. running without a real terminal
        app.notify("Admin rights needed. Run `sudo -v` in a terminal, then try again.", severity="error", timeout=8)
        return False
    app.refresh()
    ok = await asyncio.to_thread(sudo_ready)
    if not ok:
        app.notify("Password wasn't accepted, so nothing was changed.", severity="warning")
    return ok


async def run_steps(app, title: str, steps: list[Step], explain: str = "", confirm: bool = True, danger: bool = False,
                    ok_label: str = "Run") -> bool:
    """Confirm → get admin rights if needed → run with live output. Returns True if everything worked."""
    if not steps:
        app.notify("Nothing to do.")
        return False
    if confirm:
        yes = await app.push_screen_wait(ConfirmScreen(title, steps, explain, danger, ok_label))
        if not yes:
            return False
    if needs_root(steps) and not await ensure_sudo(app):
        return False
    return bool(await app.push_screen_wait(TaskScreen(title, steps)))


# ---------------------------------------------------------------- panel base


class Panel(Vertical):
    """One section of the app. Loads its data the first time it's shown."""

    PANEL_ID = ""
    TITLE = ""
    ICON = ""
    PLAIN_ICON = ""
    HELP = ""
    AUTO_REFRESH: float = 0  # seconds; only while visible

    DEFAULT_CSS = """
    Panel { padding: 0 1; }
    Panel .p-head { height: auto; margin-bottom: 1; }
    Panel .p-title { text-style: bold; color: $primary; width: auto; }
    Panel .p-help { color: $text-muted; width: 1fr; margin-left: 2; }
    Panel .toolbar { height: auto; margin-bottom: 1; }
    Panel .toolbar Button { margin-right: 1; min-width: 10; }
    Panel .toolbar Input { width: 1fr; }
    Panel .hint { color: $text-muted; height: auto; }
    """

    def __init__(self, **kw):
        super().__init__(id=self.PANEL_ID, **kw)
        self.loaded = False
        self._timer = None

    def head(self) -> ComposeResult:
        with Horizontal(classes="p-head"):
            yield Label(self.TITLE, classes="p-title")
            yield Label(self.HELP, classes="p-help")

    def activate(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.load()
        if self.AUTO_REFRESH and self._timer is None:
            self._timer = self.set_interval(self.AUTO_REFRESH, self.tick)

    def deactivate(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def load(self) -> None:  # override
        pass

    def tick(self) -> None:  # override for live updates
        pass

    def reload(self) -> None:
        self.load()

    async def run(self, title: str, steps: list[Step], explain: str = "", danger: bool = False, reload: bool = True, ok_label: str = "Run") -> bool:
        ok = await run_steps(self.app, title, steps, explain, danger=danger, ok_label=ok_label)
        if ok and reload:
            self.reload()
        return ok

    def show_text(self, title: str, text: str, language: str | None = None) -> None:
        self.app.push_screen(TextScreen(title, text, language))


class Card(Vertical):
    DEFAULT_CSS = """
    Card { height: auto; border: round $surface-lighten-2; padding: 0 1; }
    Card > .c-title { color: $text-muted; text-style: bold; }
    """

    def __init__(self, title: str, *children: Widget, **kw):
        super().__init__(*children, **kw)
        self.border_title = title


def kv(rows: list[tuple[str, Any]]) -> Text:
    """Aligned label/value lines."""
    width = max((len(k) for k, _ in rows), default=0)
    t = Text()
    for i, (k, v) in enumerate(rows):
        if i:
            t.append("\n")
        t.append(k.ljust(width + 2), style=C["overlay1"])
        if isinstance(v, Text):
            t.append_text(v)
        else:
            t.append(str(v))
    return t


__all__ = ["escape"]
