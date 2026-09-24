from __future__ import annotations

import asyncio
import subprocess

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Select, Static

from ...core import maint
from ...core.fmt import C, ago, human
from ..widgets import Btn, Card, Choice, ChoiceScreen, Panel, kv, muted

THEMES = ["catppuccin-mocha", "catppuccin-macchiato", "catppuccin-frappe", "catppuccin-latte", "tokyo-night", "rose-pine", "gruvbox", "nord", "dracula"]


class MaintenancePanel(Panel):
    PANEL_ID = "maintenance"
    TITLE = "Maintenance"
    ICON = "󰖷"
    PLAIN_ICON = "✚"
    HELP = "Automatic weekly checkup, settings backups, system snapshots and your setup"

    DEFAULT_CSS = """
    MaintenancePanel Card { margin-bottom: 1; }
    MaintenancePanel Card Horizontal { height: auto; margin-top: 1; }
    MaintenancePanel Card Button { margin-right: 1; }
    MaintenancePanel Select { width: 32; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        with VerticalScroll():
            yield Card("Weekly checkup", Static(id="timer"), Horizontal(
                Btn("Turn on", id="timer-on", variant="primary"), Btn("Turn off", id="timer-off"), Btn("Run it now", id="timer-run"),
                Btn("Past results", id="timer-log")))
            yield Card("Back up your settings", Static(id="backup"), Horizontal(
                Btn("Back up now", id="bk-now", variant="primary"), Btn("Restore…", id="bk-restore"), Btn("Open Backups folder", id="bk-open")))
            yield Card("System snapshots (undo button for the whole system)", Static(id="snap"), Horizontal(
                Btn("Create snapshot", id="snap-now", variant="primary"), Btn("Open Timeshift", id="snap-open")))
            yield Card("Your setup (theme, tools, shell)", Static(id="setup"), Horizontal(
                Btn("Re-run setup", id="setup-run"), Btn("Undo the look", id="setup-undo"), Btn("Cleanup script", id="setup-clean")))
            current = maint.config().get("theme", THEMES[0])
            themes = THEMES if current in THEMES else [current, *THEMES]
            yield Card("pc itself", Static(id="about"), Horizontal(Choice([(t, t) for t in themes], value=current,
                                                                          allow_blank=False, id="theme")))

    def load(self) -> None:
        self.fetch()

    @work(thread=True, exclusive=True, group="maint")
    def fetch(self) -> None:
        ts = maint.timer_status()
        bks = maint.settings_backups()
        tools = maint.snapshot_tools()
        sd = maint.setup_dir()
        self.app.call_from_thread(self.show, ts, bks, tools, sd)

    def show(self, ts, bks, tools, sd) -> None:
        self.backups = bks
        self.query_one("#timer", Static).update(kv([
            ("Status", Text("on - every Sunday 11:00", style=C["green"]) if ts["enabled"] else Text("off", style=C["peach"])),
            ("Next run", ts["next"] or "-"), ("Last run", ts["last"] or "never"),
            ("What it does", "Clears caches safely, checks disk space, updates, failing services, and sends you a notification. Never asks for your password."),
        ]))
        last = bks[0] if bks else None
        self.query_one("#backup", Static).update(kv([
            ("Includes", "shell + git config, VS Code/Zed settings, Ghostty, GNOME settings, startup apps, fonts, VS Code extension list"),
            ("Saved to", "~/Backups"),
            ("Latest", f"{last['name']} ({human(last['size'])}, {ago(last['time'])})" if last else Text("none yet", style=C["peach"])),
            ("Tip", "Copy ~/Backups to a USB drive or cloud folder now and then."),
        ]))
        if tools["timeshift"]:
            snap = [("Timeshift", Text("installed", style=C["green"])), ("Tip", "Take a snapshot before big changes; restore from Timeshift if something breaks.")]
        else:
            snap = [("Timeshift", Text("not installed", style=C["peach"])),
                    ("Why", "Snapshots let you roll the whole system back after a bad update. 'Create snapshot' installs it first.")]
        self.query_one("#snap", Static).update(kv(snap))
        self.setup_path = sd
        self.query_one("#setup", Static).update(kv([("Scripts", str(sd).replace(str(maint.HOME), "~") if sd else Text("not found", style=C["peach"])),
                                                    ("Tip", "Re-run setup after a big Ubuntu upgrade; it's safe to repeat.")]))
        from ... import __version__
        self.query_one("#about", Static).update(kv([("Version", __version__), ("Settings", "~/.config/pc/config.json"), ("Theme", "pick below - or press ctrl+p → theme")]))

    # ---- weekly checkup
    @on(Button.Pressed, "#timer-on")
    @work
    async def _ton(self) -> None:
        await self.run("Turn on weekly checkup", maint.enable_timer_steps())

    @on(Button.Pressed, "#timer-off")
    @work
    async def _toff(self) -> None:
        await self.run("Turn off weekly checkup", maint.disable_timer_steps())

    @on(Button.Pressed, "#timer-run")
    @work
    async def _trun(self) -> None:
        self.app.notify("Running checkup…")
        summary = await asyncio.to_thread(maint.maintain_auto)
        self.app.notify(summary, title="Checkup done", timeout=10)
        self.fetch()

    @on(Button.Pressed, "#timer-log")
    def _tlog(self) -> None:
        from ...core.run import read
        self.show_text("Weekly checkup history", read(maint.STATE_DIR / "maintain.log") or "No checkups have run yet.")

    # ---- backups
    @on(Button.Pressed, "#bk-now")
    @work
    async def _bk(self) -> None:
        await self.run("Back up settings", maint.backup_settings_steps())

    @on(Button.Pressed, "#bk-restore")
    @work
    async def _restore(self) -> None:
        bks = getattr(self, "backups", [])
        if not bks:
            self.app.notify("No backups yet.")
            return
        rows = [(b["path"], [Text(b["name"], style="bold"), muted(human(b["size"])), muted(ago(b["time"]))]) for b in bks]
        choice = await self.app.push_screen_wait(ChoiceScreen("Restore settings from…", ["Backup", "Size", "When"], rows))
        if choice:
            await self.run("Restore settings", maint.restore_settings_steps(choice),
                           "Overwrites your current config files with the ones in the backup. Log out and in afterwards.", danger=True)

    @on(Button.Pressed, "#bk-open")
    def _bkopen(self) -> None:
        maint.BACKUP_DIR.mkdir(exist_ok=True)
        subprocess.Popen(["xdg-open", str(maint.BACKUP_DIR)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # ---- snapshots
    @on(Button.Pressed, "#snap-now")
    @work
    async def _snap(self) -> None:
        installed = maint.snapshot_tools()["timeshift"]
        ok = await self.run("Create a system snapshot" if installed else "Install Timeshift", maint.timeshift_steps(),
                            "Copies your system files (not your personal files) so you can roll back." if installed else
                            "After installing, open Timeshift once to pick where snapshots go, then come back here.")
        if ok and not installed:
            self.fetch()

    @on(Button.Pressed, "#snap-open")
    def _snapopen(self) -> None:
        for cmd in (["timeshift-launcher"], ["timeshift-gtk"]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return
            except FileNotFoundError:
                continue
        self.app.notify("Timeshift isn't installed yet - press 'Create snapshot' to install it.")

    # ---- setup scripts
    def _setup(self, arg: str) -> None:
        sd = getattr(self, "setup_path", None)
        if not sd:
            self.app.notify("Couldn't find linux-setup/setup.sh.", severity="warning")
            return
        with self.app.suspend():
            subprocess.call(["bash", str(sd / "setup.sh"), arg])
            input("\nPress Enter to go back to pc…")

    @on(Button.Pressed, "#setup-run")
    def _srun(self) -> None:
        self._setup("setup")

    @on(Button.Pressed, "#setup-undo")
    def _sundo(self) -> None:
        self._setup("undo")

    @on(Button.Pressed, "#setup-clean")
    def _sclean(self) -> None:
        self._setup("clean")

    @on(Select.Changed, "#theme")
    def _theme(self, e: Select.Changed) -> None:
        if e.value and e.value != self.app.theme:
            self.app.theme = str(e.value)
