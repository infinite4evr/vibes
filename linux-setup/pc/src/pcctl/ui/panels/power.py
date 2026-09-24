from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from ...core import system
from ...core.fmt import C, bar, duration, human, level_color
from ...core.run import Step
from ..widgets import Btn, Card, Panel, kv


class PowerPanel(Panel):
    PANEL_ID = "power"
    TITLE = "Power & specs"
    ICON = "󰁹"
    PLAIN_ICON = "↯"
    HELP = "Battery health, power mode, temperatures and what's inside your PC"
    AUTO_REFRESH = 5.0

    DEFAULT_CSS = """
    PowerPanel .row { height: auto; }
    PowerPanel .row > Card { width: 1fr; margin-right: 1; }
    PowerPanel #modes Button { margin-right: 1; }
    PowerPanel #session Button { margin-right: 1; }
    PowerPanel Card { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        with VerticalScroll():
            with Horizontal(classes="row"):
                yield Card("Battery", Static("…", id="bat"))
                yield Card("Power mode", Static("…", id="mode"), Horizontal(
                    Btn("Power saver", id="power-saver"), Btn("Balanced", id="balanced"), Btn("Performance", id="performance"), id="modes"))
            with Horizontal(classes="row"):
                yield Card("Temperatures & fans", Static("…", id="temps"))
                yield Card("Suspend, restart, shut down", Static("Save your work first. These ask before doing anything.", classes="hint"),
                           Horizontal(Btn("Suspend", id="suspend"), Btn("Restart", id="reboot", variant="warning"),
                                      Btn("Shut down", id="poweroff", variant="error"), id="session"))
            yield Card("What's inside", Static("…", id="hw"))

    def load(self) -> None:
        self.tick()
        self.fetch_hw()

    def tick(self) -> None:
        self.fetch_live()

    @work(thread=True, exclusive=True, group="live")
    def fetch_live(self) -> None:
        b, p, t, f = system.battery(), system.power_profile(), system.temperatures(), system.fans()
        self.app.call_from_thread(self.show_live, b, p, t, f)

    def show_live(self, b, p, temps, fans) -> None:
        if b:
            rows = [("Charge", Text.from_markup(f"{bar(b['percent'], 20, 101, 101)} {b['percent']:.0f}%")),
                    ("State", b.get("state") or ("charging" if b.get("plugged") else "on battery"))]
            if b.get("secs_left") and not b.get("plugged"):
                rows.append(("Time left", duration(b["secs_left"])))
            if b.get("health"):
                h = b["health"]
                rows.append(("Health", Text(f"{h:.0f}% of its original capacity", style=C["green"] if h >= 80 else (C["peach"] if h >= 60 else C["red"]))))
            if b.get("energy_full") and b.get("energy_design"):
                rows.append(("Capacity", f"{b['energy_full']:.1f} Wh now / {b['energy_design']:.1f} Wh new"))
            if b.get("cycles"):
                rows.append(("Charge cycles", str(b["cycles"])))
            if b.get("rate"):
                rows.append(("Power draw", f"{b['rate']:.1f} W"))
            if b.get("vendor") or b.get("model"):
                rows.append(("Model", f"{b.get('vendor', '')} {b.get('model', '')}".strip()))
            self.query_one("#bat", Static).update(kv(rows))
        else:
            self.query_one("#bat", Static).update(Text("No battery - this looks like a desktop.", style=C["subtext0"]))
        if p.get("available"):
            cur = p.get("current", "")
            self.query_one("#mode", Static).update(kv([("Now", Text(cur, style=f"bold {C['mauve']}")),
                                                       ("Tip", "Power saver = cooler & longer battery. Performance = faster builds.")]))
            for name in ("power-saver", "balanced", "performance"):
                btn = self.query_one(f"#{name}", Button)
                btn.variant = "primary" if name == cur else "default"
                btn.display = name in p.get("profiles", [])
        else:
            self.query_one("#mode", Static).update(Text("Power modes aren't available (power-profiles-daemon not running).", style=C["subtext0"]))
            self.query_one("#modes").display = False
        t = Text()
        seen = set()
        for x in sorted(temps, key=lambda x: -x["current"]):
            key = (x["chip"], x["label"])
            if key in seen or len(seen) >= 10:
                continue
            seen.add(key)
            hi = x["high"] or 85
            t.append(f"{x['label'][:18]:<18}", style="bold")
            t.append(f"{x['current']:5.0f}°C  ", style=level_color(x["current"], hi - 10, hi))
            t.append_text(Text.from_markup(bar(x["current"], 14, hi - 10, hi)))
            t.append(f"  {x['chip']}\n", style=C["overlay1"])
        for fan in fans:
            t.append(f"{fan['label'][:18]:<18}", style="bold")
            t.append(f"{fan['rpm']:5d} rpm\n", style=C["subtext0"])
        self.query_one("#temps", Static).update(t if t.plain else Text("No sensors found. Install lm-sensors and run `sudo sensors-detect`.", style=C["subtext0"]))

    @work(thread=True, exclusive=True, group="hw")
    def fetch_hw(self) -> None:
        hw, ident = system.hardware(), system.identity()
        self.app.call_from_thread(self.show_hw, hw, ident)

    def show_hw(self, hw: dict, ident: dict) -> None:
        rows = [("Computer", ident["model"]), ("Processor", f"{hw['cpu']}  ({hw['cores']} cores / {hw['threads']} threads)"),
                ("Memory", human(hw["ram"]))]
        for g in hw["gpus"] or ["-"]:
            rows.append(("Graphics", g))
        for d in hw["disks"]:
            rows.append(("Disk", f"{d['name']}  {d['model'] or ''}  {human(d['size'])}  {d['kind']}{' · ' + d['bus'] if d['bus'] else ''}"))
        if hw["board"]:
            rows.append(("Motherboard", hw["board"]))
        if hw["bios"]:
            rows.append(("BIOS", hw["bios"]))
        rows += [("System", ident["os"]), ("Kernel", ident["kernel"]), ("Architecture", hw["arch"])]
        self.query_one("#hw", Static).update(kv(rows))

    @on(Button.Pressed, "#power-saver")
    @on(Button.Pressed, "#balanced")
    @on(Button.Pressed, "#performance")
    @work
    async def _mode(self, e: Button.Pressed) -> None:
        name = e.button.id
        await self.run(f"Switch to {name}", [Step(f"Power mode: {name}", ["powerprofilesctl", "set", name])], reload=False)
        self.tick()

    @on(Button.Pressed, "#suspend")
    @on(Button.Pressed, "#reboot")
    @on(Button.Pressed, "#poweroff")
    @work
    async def _session(self, e: Button.Pressed) -> None:
        what = {"suspend": "Suspend (sleep)", "reboot": "Restart", "poweroff": "Shut down"}[e.button.id]
        await self.run(what, [Step(what, ["systemctl", e.button.id])], "Unsaved work in open apps may be lost.", danger=e.button.id != "suspend",
                       reload=False, ok_label=what)
