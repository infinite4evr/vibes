from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from ...core import services, system
from ...core.fmt import C
from ...core.run import py_step
from ..widgets import Btn, Card, ChoiceScreen, Panel, SortTable, muted, plain


class StartupPanel(Panel):
    PANEL_ID = "startup"
    TITLE = "Startup"
    ICON = "󰐥"
    PLAIN_ICON = "▶"
    HELP = "Apps that open when you log in, and what slows down booting"

    DEFAULT_CSS = """
    StartupPanel #apps-box { height: 1fr; }
    StartupPanel #boot { height: auto; max-height: 18; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(classes="toolbar"):
            yield Btn("Turn on / off (space)", id="toggle", variant="primary")
            yield Btn("Add an app…", id="add")
            yield Btn("Remove", id="remove")
        with Vertical(id="apps-box"):
            yield SortTable([("on", "On"), ("name", "App"), ("desc", "What it does"), ("from", "Added by"), ("exec", "Command")], sort="on", empty="No apps start at login")
        yield Card("Startup speed", Static("Measuring…", id="boot-text"), id="boot")

    BINDINGS = [("space", "toggle", "On/off")]

    def load(self) -> None:
        self.render_apps()
        self.fetch_boot()

    def render_apps(self) -> None:
        self.items = {a.id: a for a in services.startup_apps()}
        rows = []
        for a in self.items.values():
            rows.append((a.id, {"on": 1 if a.enabled else 0, "name": a.name.lower(), "desc": a.comment, "from": a.system, "exec": a.exec},
                         [Text("● on" if a.enabled else "○ off", style=C["green"] if a.enabled else C["overlay0"]), Text(a.name, style="bold"),
                          plain(a.comment[:60]), muted("Ubuntu" if a.system else "you / an app"), muted(a.exec[:60])]))
        self.query_one(SortTable).set_rows(rows)

    @work(thread=True, exclusive=True, group="boot")
    def fetch_boot(self) -> None:
        b = system.boot()
        self.app.call_from_thread(self.show_boot, b)

    def show_boot(self, b: dict) -> None:
        t = Text()
        if not b.get("total"):
            t.append("Boot timing isn't available.", style=C["subtext0"])
        else:
            t.append(f"Last boot took {b['total']:.1f} s", style="bold")
            parts = [f"{k} {b[k]:.1f}s" for k in ("firmware", "loader", "kernel", "userspace") if k in b]
            if parts:
                t.append("  (" + " · ".join(parts) + ")", style=C["subtext0"])
            if b.get("blame"):
                t.append("\nSlowest services:\n", style=C["subtext0"])
                top = b["blame"][0][0] or 1
                for secs, unit in b["blame"][:8]:
                    width = max(1, int(secs / top * 24))
                    t.append(f"  {secs:6.2f}s ", style=C["peach"] if secs > 5 else C["subtext0"])
                    t.append("▇" * width, style=C["mauve"])
                    t.append(f" {unit}", style="")
                    ex = services.explain(unit)
                    if ex:
                        t.append(f"  - {ex}", style=C["overlay1"])
                    t.append("\n")
                t.append("Tip: 'NetworkManager-wait-online' often adds seconds and is safe to disable in Services on a laptop.", style=C["overlay1"])
        self.query_one("#boot-text", Static).update(t)

    def _sel(self):
        k = self.query_one(SortTable).selected_key()
        return self.items.get(k) if k else None

    @on(Button.Pressed, "#toggle")
    @on(SortTable.RowSelected)
    def action_toggle(self) -> None:
        a = self._sel()
        if not a:
            return
        msg = services.set_startup_enabled(a, not a.enabled)
        self.app.notify(msg.capitalize() + " at login.")
        self.render_apps()

    @on(Button.Pressed, "#add")
    @work
    async def _add(self) -> None:
        apps = await asyncio.to_thread(services.launchable_apps)
        rows = [(f, [Text(name, style="bold"), muted(f)]) for name, f in apps]
        choice = await self.app.push_screen_wait(ChoiceScreen("Open an app automatically when you log in", ["App", "File"], rows))
        if choice:
            self.app.notify(services.add_startup(choice))
            self.render_apps()

    @on(Button.Pressed, "#remove")
    @work
    async def _remove(self) -> None:
        a = self._sel()
        if not a:
            return
        if a.system:
            self.app.notify("That one comes with Ubuntu - switched off instead of removed.")
        await self.run(f"Remove {a.name} from startup", [py_step("Remove from startup", lambda: services.remove_startup(a), f"rm ~/.config/autostart/{a.id}")],
                       reload=False)
        self.render_apps()
