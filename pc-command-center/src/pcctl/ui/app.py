"""The pc control center app: sidebar + panels + command palette."""

from __future__ import annotations

import asyncio
from functools import partial

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Footer, Label, OptionList, Static
from textual.widgets.option_list import Option

from .. import __version__
from ..core import maint, network, packages, security, system
from ..core.fmt import C, duration
from ..core.run import Step
from .panels.apps import AppsPanel
from .panels.cleanup import CleanupPanel
from .panels.dev import DevPanel
from .panels.logs import LogsPanel
from .panels.maintenance import MaintenancePanel
from .panels.network import NetworkPanel
from .panels.overview import OverviewPanel
from .panels.power import PowerPanel
from .panels.processes import ProcessesPanel
from .panels.security import SecurityPanel
from .panels.services import ServicesPanel
from .panels.startup import StartupPanel
from .panels.storage import StoragePanel
from .panels.updates import UpdatesPanel
from .widgets import InputScreen, Panel, TextScreen, run_steps

PANELS: list[type[Panel]] = [OverviewPanel, ProcessesPanel, StoragePanel, CleanupPanel, UpdatesPanel, AppsPanel, StartupPanel,
                             ServicesPanel, NetworkPanel, DevPanel, PowerPanel, SecurityPanel, LogsPanel, MaintenancePanel]
KEYS = "1234567890"


def use_nerd_icons(pref: str) -> bool:
    """Nerd Font icons only when the terminal is likely using one (Ghostty/VS Code/Zed set up by ubuntu-setup)."""
    import os
    if pref in ("nerd", "plain"):
        return pref == "nerd"
    term = (os.environ.get("TERM_PROGRAM", "") + " " + os.environ.get("TERM", "")).lower()
    if not any(x in term for x in ("ghostty", "vscode", "zed", "wezterm", "kitty")) and not os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return False
    from ..core.run import out
    return "Nerd Font" in out(["fc-list", ":", "family"], timeout=5)


class PcCommands(Provider):
    """Everything pc can do, searchable with Ctrl+P."""

    def _commands(self) -> list[tuple[str, str, object]]:
        app: PcApp = self.app  # type: ignore[assignment]
        cmds: list[tuple[str, str, object]] = []
        for p in PANELS:
            cmds.append((f"Go to {p.TITLE}", p.HELP, partial(app.goto, p.PANEL_ID)))
        cmds += [
            ("Update everything", "apt + snap + flatpak", partial(app.run_steps_action, "Update everything", packages.update_all_steps)),
            ("Install security fixes only", "", partial(app.run_steps_action, "Install security fixes", packages.security_only_steps)),
            ("Clean up junk", "Open the cleanup list", partial(app.goto, "cleanup")),
            ("Free a port (kill what's using it)", "e.g. a dev server stuck on 3000", app.free_port),
            ("Turn on firewall", "ufw", partial(app.run_steps_action, "Turn on firewall", lambda: security.firewall().steps or [])),
            ("Back up settings now", "~/Backups", partial(app.run_steps_action, "Back up settings", maint.backup_settings_steps)),
            ("Weekly checkup: turn on", "Sundays 11:00", partial(app.run_steps_action, "Turn on weekly checkup", maint.enable_timer_steps)),
            ("Power mode: performance", "", partial(app.run_steps_action, "Performance mode", lambda: [Step("Performance mode", ["powerprofilesctl", "set", "performance"])])),
            ("Power mode: balanced", "", partial(app.run_steps_action, "Balanced mode", lambda: [Step("Balanced mode", ["powerprofilesctl", "set", "balanced"])])),
            ("Power mode: power saver", "", partial(app.run_steps_action, "Power saver", lambda: [Step("Power saver", ["powerprofilesctl", "set", "power-saver"])])),
            ("Wi-Fi off", "", partial(app.run_steps_action, "Wi-Fi off", lambda: [Step("Wi-Fi off", ["nmcli", "radio", "wifi", "off"])])),
            ("Wi-Fi on", "", partial(app.run_steps_action, "Wi-Fi on", lambda: [Step("Wi-Fi on", ["nmcli", "radio", "wifi", "on"])])),
            ("Restart the computer", "", partial(app.run_steps_action, "Restart", lambda: [Step("Restart", ["systemctl", "reboot"])])),
            ("Shut down", "", partial(app.run_steps_action, "Shut down", lambda: [Step("Shut down", ["systemctl", "poweroff"])])),
            ("Help: keys and tips", "", app.action_help),
        ]
        return cmds

    async def discover(self) -> Hits:
        for name, help_text, cb in self._commands():
            yield DiscoveryHit(name, cb, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, cb in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), cb, help=help_text)


HELP = """\
pc - your computer's control center

Moving around
  1 … 0           jump to a section (see numbers in the sidebar)
  Tab / Shift+Tab  move between controls        ↑ ↓  move in lists
  Enter            open / details               Esc  close a dialog
  Ctrl+P           search every action (update, free a port, power mode…)
  r                refresh the current section  q    quit

Safety
  Nothing changes until you press Run in a confirmation that shows the exact
  commands. Admin actions ask for your password in this terminal.
  Deleting files moves them to the Trash where possible.

From any terminal
  pc status        one-screen summary          pc doctor     health check
  pc clean         safe cleanup                pc update     update everything
  pc ports         what's listening            pc kill-port 3000
  pc big ~/        biggest folders             pc repos      all your git projects
  pc info          hardware + system           pc logs       recent errors
"""


class PcApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "pc"
    COMMANDS = App.COMMANDS | {PcCommands}
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "help", "Help"),
        *[Binding(k, f"goto_index({i})", show=False) for i, k in enumerate(KEYS)],
    ]

    def __init__(self, start: str = "overview"):
        super().__init__()
        self.start = start
        self.cfg = maint.config()
        self.nerd = use_nerd_icons(self.cfg.get("icons", "auto"))
        self.badges: dict[str, int] = {}
        self.current: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Label(" pc ", id="brand")
            yield Label("", id="ident")
            yield Label("", id="clock")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield OptionList(*[Option(self._label(p, i), id=p.PANEL_ID) for i, p in enumerate(PANELS)], id="nav")
                yield Static("", id="side-stats")
            with ContentSwitcher(initial=None, id="panels"):
                for p in PANELS:
                    yield p()
        yield Footer()

    def _label(self, p: type[Panel], i: int) -> Text:
        icon = p.ICON if self.nerd else p.PLAIN_ICON
        t = Text()
        t.append(f"{icon:<2} ", style=C["mauve"])
        t.append(f"{p.TITLE[:14]:<14}")
        n = self.badges.get(p.PANEL_ID, 0)
        badge = f" {n if n < 100 else '99+'} " if n else ""
        t.append(" " * max(0, 5 - len(badge)))
        if badge:
            t.append(badge, style=f"bold {C['crust']} on {C['peach']}")
        t.append(f" {KEYS[i]}" if i < len(KEYS) else "  ", style=C["overlay0"])
        return t

    def on_mount(self) -> None:
        theme = self.cfg.get("theme", "catppuccin-mocha")
        self.theme = theme if theme in self.available_themes else "catppuccin-mocha"
        ident = system.identity()
        self.query_one("#ident", Label).update(Text.assemble((ident["host"], "bold"), ("  ·  ", C["overlay0"]), ident["os"],
                                                             ("  ·  ", C["overlay0"]), f"kernel {ident['kernel']}"))
        self.update_clock()
        self.set_interval(5, self.update_clock)
        self.goto(self.start if self.start in [p.PANEL_ID for p in PANELS] else "overview")
        self.query_one("#nav", OptionList).focus()

    def watch_theme(self, theme: str) -> None:
        if getattr(self, "cfg", None) is not None and theme != self.cfg.get("theme"):
            self.cfg["theme"] = theme
            try:
                maint.save_config(theme=theme)
            except OSError:
                pass

    def update_clock(self) -> None:
        import time
        import psutil
        vm = psutil.virtual_memory()
        self.query_one("#clock", Label).update(Text.assemble(
            (f"up {duration(system.uptime_seconds())}", C["subtext0"]), ("  ·  ", C["overlay0"]),
            (f"RAM {vm.percent:.0f}%", C["subtext0"]), ("  ·  ", C["overlay0"]), (time.strftime("%a %H:%M"), "bold")))

    # ---------------------------------------------------------------- navigation
    def goto(self, panel_id: str) -> None:
        sw = self.query_one("#panels", ContentSwitcher)
        if self.current and self.current != panel_id:
            try:
                self.query_one(f"#{self.current}", Panel).deactivate()
            except Exception:  # noqa: BLE001
                pass
        sw.current = panel_id
        self.current = panel_id
        panel = self.query_one(f"#{panel_id}", Panel)
        panel.activate()
        nav = self.query_one("#nav", OptionList)
        idx = next(i for i, p in enumerate(PANELS) if p.PANEL_ID == panel_id)
        if nav.highlighted != idx:
            nav.highlighted = idx

    @on(OptionList.OptionHighlighted, "#nav")
    def _nav_hl(self, e: OptionList.OptionHighlighted) -> None:
        if e.option.id and e.option.id != self.current:
            self.goto(e.option.id)

    @on(OptionList.OptionSelected, "#nav")
    def _nav_sel(self, e: OptionList.OptionSelected) -> None:
        panel = self.query_one(f"#{e.option.id}", Panel)
        self.goto(e.option.id)
        try:
            panel.focus_next()
        except Exception:  # noqa: BLE001
            pass

    def action_goto_index(self, i: int) -> None:
        if i < len(PANELS):
            self.goto(PANELS[i].PANEL_ID)

    def action_refresh(self) -> None:
        if self.current:
            self.query_one(f"#{self.current}", Panel).reload()
            self.notify("Refreshing…", timeout=1.5)

    def action_help(self) -> None:
        self.push_screen(TextScreen("Keys and tips", HELP))

    def set_badge(self, panel_id: str, n: int) -> None:
        if self.badges.get(panel_id, 0) == n:
            return
        self.badges[panel_id] = n
        nav = self.query_one("#nav", OptionList)
        for i, p in enumerate(PANELS):
            if p.PANEL_ID == panel_id:
                nav.replace_option_prompt_at_index(i, self._label(p, i))

    # ---------------------------------------------------------------- actions used everywhere
    def fix_check(self, check) -> None:
        if check.goto:
            self.goto(check.goto)
        elif check.steps:
            self.run_steps_action(check.fix_label or check.title, lambda: check.steps, check.detail)

    @work
    async def run_steps_action(self, title: str, make_steps, explain: str = "") -> None:
        steps = await asyncio.to_thread(make_steps)
        ok = await run_steps(self, title, steps, explain)
        if ok and self.current:
            self.query_one(f"#{self.current}", Panel).reload()

    @work
    async def free_port(self) -> None:
        v = await self.push_screen_wait(InputScreen("Free a port", "Stops whatever is using it, e.g. a dev server stuck on 3000.", "3000"))
        if not v or not v.isdigit():
            return
        steps = await asyncio.to_thread(network.kill_port_steps, int(v))
        if not steps:
            self.notify(f"Nothing is using port {v}.", severity="warning")
            return
        await run_steps(self, f"Free port {v}", steps)

    async def run_in_thread(self, fn, *args):
        return await asyncio.to_thread(fn, *args)


def run(start: str = "overview") -> None:
    PcApp(start).run()
