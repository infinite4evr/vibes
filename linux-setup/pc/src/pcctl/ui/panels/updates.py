from __future__ import annotations

import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, LoadingIndicator, Static

from ...core import packages, security, system
from ...core.fmt import C, ago
from ...core.run import has
from ..widgets import Btn, Panel, SortTable, muted, plain


class UpdatesPanel(Panel):
    PANEL_ID = "updates"
    TITLE = "Updates"
    ICON = "󰚰"
    PLAIN_ICON = "↻"
    HELP = "System (apt), Snap and Flatpak updates in one list. ★ = security fix"

    DEFAULT_CSS = """
    UpdatesPanel #status { height: auto; margin-bottom: 1; }
    UpdatesPanel LoadingIndicator { height: 3; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        yield Static(id="status")
        with Horizontal(classes="toolbar"):
            yield Btn("Update all", id="all", variant="primary")
            yield Btn("Security only", id="sec")
            yield Btn("Check now", id="check")
            yield Btn("Auto updates: off", id="auto")
            if has("fwupdmgr"):
                yield Btn("Firmware", id="fw")
        yield LoadingIndicator()
        yield SortTable([("sec", "★"), ("source", "From"), ("name", "Name"), ("current", "Installed"), ("new", "New version")], sort="sec", empty="Nothing to update ✓")
        yield Label("", classes="hint", id="foot")

    def load(self) -> None:
        self.query_one(LoadingIndicator).display = True
        self.fetch()

    @work(thread=True, exclusive=True, group="updates")
    def fetch(self) -> None:
        ups = packages.pending_updates()
        auto = packages.auto_updates_enabled()
        reboot = system.reboot_required()
        last = packages.last_apt_update()
        self.app.call_from_thread(self.show, ups, auto, reboot, last)

    def show(self, ups, auto, reboot, last) -> None:
        self.query_one(LoadingIndicator).display = False
        sec = sum(u.security for u in ups)
        t = Text()
        if ups:
            t.append(f"{len(ups)} updates waiting", style=f"bold {C['peach']}")
            if sec:
                t.append(f" · {sec} security fixes", style=f"bold {C['red']}")
        else:
            t.append("You're up to date ✓", style=f"bold {C['green']}")
        t.append(f"\nLast checked {ago(last) if last else 'never'}", style=C["subtext0"])
        if last and time.time() - last > 7 * 86400:
            t.append(" - press 'Check now'", style=C["peach"])
        if reboot is not None:
            t.append("\nRestart needed to finish earlier updates" + (f" ({', '.join(reboot[:3])})" if reboot else ""), style=C["peach"])
        self.query_one("#status", Static).update(t)
        btn = self.query_one("#auto", Button)
        btn.label = "Auto updates: on" if auto else "Auto updates: off"
        btn.variant = "success" if auto else "warning"
        self.auto = auto
        rows = []
        for u in ups:
            key = f"{u.source}:{u.name}"
            rows.append((key, {"sec": 1 if u.security else 0, "source": u.source, "name": u.name, "current": u.current, "new": u.new},
                         [Text("★" if u.security else "", style=C["red"]), muted(u.source), plain(u.name), muted(u.current), plain(u.new)]))
        self.query_one(SortTable).set_rows(rows)
        self.query_one("#foot", Label).update("Updating is safe; apps you're using keep running. Some updates finish after a restart.")
        self.app.set_badge("updates", sec or (1 if len(ups) > 20 else 0))

    @on(Button.Pressed, "#all")
    @work
    async def _all(self) -> None:
        await self.run("Update everything", packages.update_all_steps(),
                       "Installs every waiting update for the system, snaps and Flatpaks. Takes a few minutes; keep the laptop plugged in.")

    @on(Button.Pressed, "#sec")
    @work
    async def _sec(self) -> None:
        await self.run("Install security fixes", packages.security_only_steps(), "Only fixes that close security holes.")

    @on(Button.Pressed, "#check")
    @work
    async def _check(self) -> None:
        await self.run("Check for updates", packages.refresh_steps(), "Asks Ubuntu's servers what's new. Nothing gets installed yet.")

    @on(Button.Pressed, "#auto")
    @work
    async def _auto(self) -> None:
        if getattr(self, "auto", False):
            self.app.notify("Automatic security updates are already on.")
            return
        c = security.auto_updates()
        await self.run("Turn on automatic security updates", c.steps, c.detail)

    @on(Button.Pressed, "#fw")
    @work
    async def _fw(self) -> None:
        self.app.notify("Checking firmware…")
        names = await self.app.run_in_thread(packages.firmware_updates)
        if not names:
            self.app.notify("No firmware updates available.")
            return
        from ...core.run import Step
        await self.run("Update firmware", [Step("Update firmware", ["fwupdmgr", "update", "-y", "--no-reboot-check"], root=True)],
                       "Available: " + ", ".join(names) + ". The PC may need a restart to finish.")
