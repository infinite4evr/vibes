from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Digits, Label, LoadingIndicator, Static

from ...core import security
from ...core.fmt import C
from ..widgets import Btn, Panel, lvl


class SecRow(Horizontal):
    DEFAULT_CSS = """
    SecRow { height: auto; padding: 0 0 1 0; }
    SecRow > Static { width: 1fr; }
    SecRow Button { min-width: 18; margin-left: 1; }
    """

    def __init__(self, check: security.Check):
        super().__init__()
        self.check = check

    def compose(self) -> ComposeResult:
        c = self.check
        t = lvl(c.level)
        t.append(" " + c.title + "\n", style="bold")
        t.append("  " + c.detail, style=C["subtext0"])
        yield Static(t)
        if c.fix_label and (c.steps or c.goto):
            yield Btn(c.fix_label, variant="primary" if c.level == "bad" else "default")

    @on(Button.Pressed)
    def _fix(self) -> None:
        self.app.fix_check(self.check)


class SecurityPanel(Panel):
    PANEL_ID = "security"
    TITLE = "Security"
    ICON = "󰒃"
    PLAIN_ICON = "◈"
    HELP = "A checklist of the things that actually matter on a laptop"

    DEFAULT_CSS = """
    SecurityPanel #score-box { height: auto; margin-bottom: 1; }
    SecurityPanel Digits { width: auto; margin-right: 2; }
    SecurityPanel #verdict { width: 1fr; content-align: left middle; height: 3; }
    SecurityPanel LoadingIndicator { height: 3; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(id="score-box"):
            yield Digits("--", id="score")
            yield Static("Checking…", id="verdict")
            yield Btn("Check again", id="again")
        yield LoadingIndicator()
        yield VerticalScroll(id="list")

    def load(self) -> None:
        self.query_one(LoadingIndicator).display = True
        self.fetch()

    @work(thread=True, exclusive=True, group="sec")
    def fetch(self) -> None:
        checks = security.all_checks()
        self.app.call_from_thread(self.show, checks)

    def show(self, checks: list[security.Check]) -> None:
        self.query_one(LoadingIndicator).display = False
        score = security.score(checks)
        d = self.query_one("#score", Digits)
        d.update(str(score))
        d.styles.color = C["green"] if score >= 85 else (C["peach"] if score >= 60 else C["red"])
        todo = [c for c in checks if c.level in ("bad", "warn")]
        v = Text()
        v.append("Well protected ✓" if not todo else f"{len(todo)} thing{'s' if len(todo) != 1 else ''} worth fixing", style=f"bold {C['green'] if not todo else C['peach']}")
        v.append("\nScore out of 100. Fix the red ones first.", style=C["subtext0"])
        self.query_one("#verdict", Static).update(v)
        box = self.query_one("#list", VerticalScroll)
        box.remove_children()
        order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
        box.mount_all([SecRow(c) for c in sorted(checks, key=lambda c: order[c.level])])
        self.app.set_badge("security", sum(1 for c in checks if c.level == "bad"))

    @on(Button.Pressed, "#again")
    def _again(self) -> None:
        self.load()
