from __future__ import annotations

from collections import deque

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Digits, Label, Sparkline, Static

from ...core import health, system
from ...core.fmt import C, bar, duration, human, level_color, rate
from ..widgets import Btn, Card, Panel, kv, lvl


class CheckRow(Horizontal):
    DEFAULT_CSS = """
    CheckRow { height: auto; padding: 0 0 0 0; }
    CheckRow Static { width: 1fr; }
    CheckRow Button { min-width: 16; height: 1; border: none; margin-left: 1; }
    """

    def __init__(self, check: health.Check):
        super().__init__()
        self.check = check

    def compose(self) -> ComposeResult:
        c = self.check
        t = lvl(c.level)
        t.append(" " + c.title, style="bold")
        t.append("  " + c.detail, style=C["subtext0"])
        yield Static(t)
        if c.fix_label and (c.steps or c.goto):
            yield Btn(c.fix_label, variant="primary" if c.level == "bad" else "default", compact=True)

    @on(Button.Pressed)
    def _fix(self) -> None:
        self.app.fix_check(self.check)


class OverviewPanel(Panel):
    PANEL_ID = "overview"
    TITLE = "Overview"
    ICON = "󰕮"
    PLAIN_ICON = "◉"
    HELP = "Live view of your PC and anything that needs attention"
    AUTO_REFRESH = 2.0

    DEFAULT_CSS = """
    OverviewPanel .row { height: auto; margin-bottom: 0; }
    OverviewPanel .row > Card { width: 1fr; margin-right: 1; }
    OverviewPanel #c-ident { width: 2fr; }
    OverviewPanel Card { height: auto; }
    OverviewPanel #score { width: 100%; content-align: center middle; text-align: center; }
    OverviewPanel #score-label { width: 100%; text-align: center; color: $text-muted; }
    OverviewPanel Sparkline { height: 2; margin-top: 0; }
    OverviewPanel #cpu-spark > .sparkline--max-color { color: $error; }
    OverviewPanel #cpu-spark > .sparkline--min-color { color: $primary; }
    OverviewPanel #net-spark > .sparkline--max-color { color: $accent; }
    OverviewPanel #net-spark > .sparkline--min-color { color: $secondary; }
    OverviewPanel #checks { height: auto; max-height: 14; }
    OverviewPanel #bottom { height: auto; margin-top: 1; }
    OverviewPanel #apps { width: 1fr; }
    OverviewPanel #attention { width: 2fr; margin-right: 1; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.sampler = system.Sampler()
        self.watcher = system.ProcessWatcher()
        self.cpu_hist: deque[float] = deque([0.0] * 60, maxlen=60)
        self.net_hist: deque[float] = deque([0.0] * 60, maxlen=60)
        self.ticks = 0
        self.ident = system.identity()

    def compose(self) -> ComposeResult:
        yield from self.head()
        with VerticalScroll():
            with Horizontal(id="top", classes="row"):
                yield Card("This PC", Static(id="ident"), id="c-ident")
                yield Card("Health", Digits("--", id="score"), Label("checking…", id="score-label"), id="c-health")
                yield Card("Battery & power", Static(id="power"), id="c-power")
            with Horizontal(classes="row"):
                yield Card("CPU", Static(id="cpu"), Sparkline(list(self.cpu_hist), id="cpu-spark"))
                yield Card("Memory", Static(id="mem"))
            with Horizontal(classes="row"):
                yield Card("Network", Static(id="net"), Sparkline(list(self.net_hist), id="net-spark"))
                yield Card("Disks", Static(id="disks"))
            with Horizontal(id="bottom"):
                yield Card("Needs attention", Vertical(Static("Running checks…", classes="hint"), id="checks"), id="attention")
                yield Card("Busiest apps", Static(id="apps-list"), id="apps")

    def load(self) -> None:
        i = self.ident
        up = duration(system.uptime_seconds())
        self.query_one("#ident", Static).update(kv([
            ("Computer", i["model"]),
            ("System", f"{i['os']} · {i['desktop'] or 'desktop'} {i['session']}".strip()),
            ("Kernel", i["kernel"]),
            ("Up for", up),
            ("User", f"{i['user']} · {i['shell']}"),
        ]))
        self.tick()
        self.load_health()

    def reload(self) -> None:
        self.query_one("#score-label", Label).update("checking…")
        self.load_health()

    @work(thread=True, exclusive=True, group="health")
    def load_health(self) -> None:
        checks = health.run_all()
        self.app.call_from_thread(self.show_health, checks)

    def show_health(self, checks: list[health.Check]) -> None:
        score = health.score(checks)
        d = self.query_one("#score", Digits)
        d.update(str(score))
        d.styles.color = C["green"] if score >= 85 else (C["peach"] if score >= 60 else C["red"])
        todo = [c for c in checks if c.level in ("bad", "warn")]
        self.query_one("#score-label", Label).update("all good" if not todo else f"{len(todo)} thing{'s' if len(todo) != 1 else ''} to look at")
        box = self.query_one("#checks", Vertical)
        box.remove_children()
        shown = todo + [c for c in checks if c.level in ("info", "ok")][: max(0, 8 - len(todo))]
        box.mount_all([CheckRow(c) for c in shown])
        self.app.set_badge("overview", len(todo))

    def tick(self) -> None:
        self.collect()

    @work(thread=True, exclusive=True, group="tick")
    def collect(self) -> None:
        snap = self.sampler.sample()
        procs = self.watcher.list()
        temp = system.cpu_temp()
        mounts = system.mounts()
        bat = system.battery() if self.ticks % 10 == 0 else None
        prof = system.power_profile() if self.ticks % 10 == 0 else None
        self.app.call_from_thread(self.render_live, snap, procs, temp, mounts, bat, prof)

    def render_live(self, s: system.Snapshot, procs, temp, mounts, bat, prof) -> None:
        self.ticks += 1
        self.cpu_hist.append(s.cpu)
        self.net_hist.append(s.net_rx + s.net_tx)
        cpu = Text.from_markup(f"[b]{s.cpu:4.0f}%[/b]  {bar(s.cpu, 16)}")
        extra = []
        if s.freq_mhz:
            extra.append(f"{s.freq_mhz / 1000:.1f} GHz")
        if temp:
            extra.append(f"[{level_color(temp, 75, 88)}]{temp:.0f}°C[/]")
        extra.append(f"load {s.load[0]:.1f}")
        extra.append(f"{s.procs} processes")
        cpu.append("\n")
        cpu.append_text(Text.from_markup("  ".join(extra), style=C["subtext0"]))
        self.query_one("#cpu", Static).update(cpu)
        self.query_one("#cpu-spark", Sparkline).data = list(self.cpu_hist)

        mem = Text.from_markup(f"[b]RAM [/b] {bar(s.mem_pct, 14, 80, 92)} {human(s.mem_used)} / {human(s.mem_total)}")
        if s.swap_total:
            sp = s.swap_used / s.swap_total * 100
            mem.append("\n")
            mem.append_text(Text.from_markup(f"[b]Swap[/b] {bar(sp, 14, 50, 80)} {human(s.swap_used)} / {human(s.swap_total)}"))
        mem.append("\n")
        mem.append(f"Disk  ↓{rate(s.disk_read)} ↑{rate(s.disk_write)}", style=C["subtext0"])
        self.query_one("#mem", Static).update(mem)

        net = Text.from_markup(f"[{C['teal']}]↓ {rate(s.net_rx)}[/]   [{C['peach']}]↑ {rate(s.net_tx)}[/]")
        self.query_one("#net", Static).update(net)
        self.query_one("#net-spark", Sparkline).data = list(self.net_hist)

        dt = Text()
        for i, m in enumerate(mounts[:4]):
            if i:
                dt.append("\n")
            dt.append_text(Text.from_markup(f"{m.mountpoint[:10]:<10} {bar(m.pct, 10, 80, 90)} {human(m.free)} free"))
        self.query_one("#disks", Static).update(dt)

        groups = system.app_groups(procs)
        top = sorted(groups, key=lambda g: (-g["cpu"], -g["mem"]))[:7]
        at = Text()
        for i, g in enumerate(top):
            if i:
                at.append("\n")
            at.append(f"{g['name'][:18]:<18}", style="bold")
            at.append(f"{g['cpu']:5.1f}% ", style=level_color(g["cpu"], 40, 80))
            at.append(f"{human(g['mem']):>9}", style=C["subtext0"])
            if g["count"] > 1:
                at.append(f" ×{g['count']}", style=C["overlay1"])
        self.query_one("#apps-list", Static).update(at)

        if bat is not None or prof is not None or self.ticks == 1:
            self._render_power(bat if bat is not None else system.battery(), prof if prof is not None else system.power_profile())

    def _render_power(self, bat, prof) -> None:
        rows = []
        if bat:
            state = "charging" if bat.get("plugged") else "on battery"
            left = ""
            if bat.get("secs_left") and not bat.get("plugged"):
                left = f" · {duration(bat['secs_left'])} left"
            rows.append(("Charge", Text.from_markup(f"{bar(bat['percent'], 12, 101, 101)} {bat['percent']:.0f}% {state}{left}")))
            if bat.get("health"):
                rows.append(("Health", f"{bat['health']:.0f}% of original"))
        else:
            rows.append(("Battery", "none (desktop)"))
        if prof and prof.get("available"):
            rows.append(("Mode", prof.get("current", "?")))
        self.query_one("#power", Static).update(kv(rows))
