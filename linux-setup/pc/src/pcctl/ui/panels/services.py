from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, LoadingIndicator, Select

from ...core import services as svc
from ...core.fmt import C
from ..widgets import Btn, Choice, Panel, SearchInput, SortTable, muted, plain

STATE_STYLE = {"active": (C["green"], "● running"), "failed": (C["red"], "■ failed"), "inactive": (C["overlay0"], "○ stopped"),
               "activating": (C["yellow"], "◐ starting"), "deactivating": (C["yellow"], "◑ stopping")}


class ServicesPanel(Panel):
    PANEL_ID = "services"
    TITLE = "Services"
    ICON = "󰒓"
    PLAIN_ICON = "✱"
    HELP = "Background programs. s start · x stop · R restart · e/d on/off at boot · l logs"

    BINDINGS = [Binding("s", "act('start')", "Start"), Binding("x", "act('stop')", "Stop"), Binding("R", "act('restart')", "Restart"),
                Binding("e", "act('enable --now')", "On at boot"), Binding("d", "act('disable --now')", "Off at boot"),
                Binding("l", "logs", "Logs")]

    DEFAULT_CSS = """
    ServicesPanel .toolbar Select { width: 24; }
    ServicesPanel LoadingIndicator { height: 3; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.items: dict[str, svc.Service] = {}

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(classes="toolbar"):
            yield SearchInput(placeholder="Search services…", id="filter")
            yield Choice([("System", "system"), ("Mine (user)", "user")], value="system", allow_blank=False, id="scope")
            yield Choice([("Running + failed", "running"), ("Failed only", "failed"), ("Everything", "all")], value="running", allow_blank=False, id="show")
        with Horizontal(classes="toolbar"):
            yield Btn("Start", id="start")
            yield Btn("Stop", id="stop")
            yield Btn("Restart", id="restart")
            yield Btn("On at boot", id="enable")
            yield Btn("Off at boot", id="disable")
            yield Btn("Logs", id="logs", variant="primary")
        yield LoadingIndicator()
        yield SortTable([("state", "State"), ("name", "Service"), ("boot", "At boot"), ("desc", "What it does")], sort="state", reverse=False, empty="No services match")
        yield Label("", id="foot", classes="hint")

    def load(self) -> None:
        self.query_one(LoadingIndicator).display = True
        self.fetch(self.query_one("#scope", Select).value == "user")

    @work(thread=True, exclusive=True, group="svc")
    def fetch(self, user: bool) -> None:
        items = svc.services(user=user)
        self.app.call_from_thread(self.show, items)

    def show(self, items: list[svc.Service]) -> None:
        self.query_one(LoadingIndicator).display = False
        self.all = items
        self.render_rows()
        failed = [s for s in items if s.active == "failed"]
        if not items[0:1] or not items[0].user:
            self.app.set_badge("services", len(failed))

    def render_rows(self) -> None:
        q = self.query_one("#filter", Input).value.strip().lower()
        show = self.query_one("#show", Select).value
        rows = []
        self.items = {}
        order = {"failed": 0, "active": 1, "activating": 2, "deactivating": 3, "inactive": 4}
        for s in getattr(self, "all", []):
            if show == "running" and s.active not in ("active", "failed", "activating"):
                continue
            if show == "failed" and s.active != "failed":
                continue
            ex = svc.explain(s.unit)
            if q and q not in s.unit.lower() and q not in s.description.lower() and q not in ex.lower():
                continue
            self.items[s.unit] = s
            color, label = STATE_STYLE.get(s.active, (C["overlay1"], s.active))
            boot = {"enabled": Text("on", style=C["green"]), "disabled": muted("off"), "static": muted("auto"), "masked": Text("blocked", style=C["red"])}.get(
                s.enabled, muted(s.enabled or "-"))
            desc = Text(ex, style="") if ex else plain(s.description)
            if ex and s.description:
                desc.append(f"  ({s.description})", style=C["overlay0"])
            rows.append((s.unit, {"state": order.get(s.active, 5), "name": s.name.lower(), "boot": s.enabled, "desc": ex or s.description},
                         [Text(label, style=color), Text(s.name, style="bold"), boot, desc]))
        self.query_one(SortTable).set_rows(rows)
        running = sum(1 for s in getattr(self, "all", []) if s.active == "active")
        failed = sum(1 for s in getattr(self, "all", []) if s.active == "failed")
        self.query_one("#foot", Label).update(f"{running} running · {failed} failed · {len(getattr(self, 'all', []))} total")

    @on(Input.Changed, "#filter")
    @on(Select.Changed, "#show")
    def _filter(self) -> None:
        self.render_rows()

    @on(Select.Changed, "#scope")
    def _scope(self) -> None:
        self.load()

    def _sel(self) -> svc.Service | None:
        k = self.query_one(SortTable).selected_key()
        return self.items.get(k) if k else None

    @on(Button.Pressed)
    def _btn(self, e: Button.Pressed) -> None:
        mapping = {"start": "start", "stop": "stop", "restart": "restart", "enable": "enable --now", "disable": "disable --now"}
        if e.button.id in mapping:
            self.action_act(mapping[e.button.id])
        elif e.button.id == "logs":
            self.action_logs()

    @work
    async def action_act(self, action: str) -> None:
        s = self._sel()
        if not s:
            return
        warn = ""
        if action.startswith(("stop", "disable")) and s.name in ("NetworkManager", "gdm", "gdm3", "dbus", "systemd-logind", "polkit", "accounts-daemon"):
            warn = " Careful: this is a core part of Ubuntu - stopping it can log you out or cut your connection."
        ex = svc.explain(s.unit)
        await self.run(f"{action.split()[0].title()} {s.name}", svc.action_steps(s, action),
                       (f"{s.name}: {ex}." if ex else f"{s.name}.") + warn, danger=bool(warn))

    @on(SortTable.RowSelected)
    @work
    async def action_logs(self) -> None:
        s = self._sel()
        if not s:
            return
        status = await asyncio.to_thread(svc.status_text, s)
        logs = await asyncio.to_thread(svc.logs, s, 300)
        self.show_text(f"{s.name} - status and recent logs", status + "\n" + "─" * 60 + "\n" + logs)
