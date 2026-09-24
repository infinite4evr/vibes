from __future__ import annotations

import os
import time

from gi.repository import Adw, Gtk

from ...core import health, system
from ...core.fmt import duration, human, rate
from ..util import bg, button, clear, esc, hbox, label, spacer, status_icon, vbox
from ..widgets import LineGraph, MiniBar, RingGauge, card, level_color
from .base import Page


class DashboardPage(Page):
    ID = "dashboard"
    TITLE = "Dashboard"
    ICON = "utilities-system-monitor-symbolic"
    AUTO_REFRESH = 1.5

    def build(self) -> None:
        ident = system.identity()
        self.ident = ident
        hour = time.localtime().tm_hour
        greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        self.header(f"{greet}, {ident['user']}.  {ident['model']} · {ident['os']}")

        # hero: health + quick actions
        self.gauge = RingGauge(132, 12)
        self.hero_title = label("Checking your PC…", "mid-num", wrap=True)
        self.hero_sub = label("This takes a few seconds.", "subtle", wrap=True)
        actions = hbox(
            button("Clean up", icon="edit-clear-all-symbolic", css="suggested-action", on_click=lambda: self.win.goto("cleanup")),
            button("Updates", icon="software-update-available-symbolic", on_click=lambda: self.win.goto("updates")),
            button("Security", icon="security-high-symbolic", on_click=lambda: self.win.goto("security")),
            button("Tweaks", icon="preferences-system-symbolic", on_click=lambda: self.win.goto("tweaks")),
            spacing=8)
        actions.set_margin_top(6)
        text = vbox(self.hero_title, self.hero_sub, actions, spacing=6)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        self.uptime = label("", "dim")
        hero = hbox(self.gauge, text, spacing=24)
        hero_card = card(hero)
        hero_card.add_css_class("hero")
        self.body.append(hero_card)

        # live tiles
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=1, max_children_per_line=3,
                                column_spacing=14, row_spacing=14)
        self.body.append(self.flow)

        self.cpu_num = label("0%", "big-num")
        self.cpu_info = label("", "dim", ellipsize=True)
        self.cpu_graph = LineGraph(("mauve",))
        self.cores = Gtk.Box(spacing=3, homogeneous=True)
        self.core_bars: list[MiniBar] = []
        self._tile("CPU", self.cpu_num, self.cpu_info, self.cpu_graph, self.cores)

        self.mem_num = label("0%", "big-num")
        self.mem_info = label("", "dim")
        self.mem_graph = LineGraph(("blue",))
        self.swap_bar = MiniBar(height=7, warn=50, crit=80)
        self.swap_info = label("", "dim")
        self._tile("Memory", self.mem_num, self.mem_info, self.mem_graph, hbox(label("Swap", "dim"), self.swap_bar, self.swap_info))

        self.net_num = label("", "mid-num")
        self.net_info = label("", "dim")
        self.net_graph = LineGraph(("teal", "peach"), maximum=None)
        self._tile("Network", self.net_num, self.net_info, self.net_graph)

        self.disk_box = vbox(spacing=10)
        self._tile("Disks", self.disk_box)

        self.temp_num = label("--", "big-num")
        self.temp_info = label("", "dim")
        self.temp_graph = LineGraph(("peach",), maximum=100)
        self._tile("Temperature", self.temp_num, self.temp_info, self.temp_graph)

        self.bat_num = label("--", "big-num")
        self.bat_info = label("", "dim", wrap=True)
        self.bat_bar = MiniBar(height=10, warn=101, crit=101, color="green")
        self._tile("Battery & power", self.bat_num, self.bat_bar, self.bat_info)

        # attention + busiest apps
        self.checks_list = Gtk.ListBox()
        self.checks_list.add_css_class("boxed-list")
        self.checks_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.apps_list = Gtk.ListBox()
        self.apps_list.add_css_class("boxed-list")
        self.apps_list.set_selection_mode(Gtk.SelectionMode.NONE)
        left = vbox(label("Needs attention", "section-title"), self.checks_list, spacing=8)
        left.set_hexpand(True)
        right = vbox(hbox(label("Busiest apps", "section-title"), spacer(),
                          button("All processes", css="flat", on_click=lambda: self.win.goto("processes"))), self.apps_list, spacing=8)
        right.set_size_request(380, -1)
        self.body.append(hbox(left, right, spacing=18))

        self.sampler = system.Sampler()
        self.watcher = system.ProcessWatcher()
        self.ticks = 0
        self.busy = False

    def _tile(self, title: str, *children: Gtk.Widget) -> Gtk.Box:
        t = card(*children, title=title)
        t.set_valign(Gtk.Align.FILL)
        self.flow.append(t)
        return t

    # ---------------------------------------------------------------- data
    def load(self) -> None:
        self.tick()
        self.load_health()

    def reload(self) -> None:
        self.hero_title.set_text("Checking your PC…")
        self.load_health()

    def load_health(self) -> None:
        self.bg(health.run_all, self.show_health)

    def show_health(self, checks: list) -> None:
        score = health.score(checks)
        todo = [c for c in checks if c.level in ("bad", "warn")]
        self.gauge.set(score, str(score), "health")
        if not todo:
            self.hero_title.set_text("Your PC is in great shape")
            self.hero_sub.set_text("Nothing needs your attention right now.")
        else:
            self.hero_title.set_text(f"{len(todo)} thing{'s' if len(todo) != 1 else ''} could use your attention")
            self.hero_sub.set_text("Fix them below, or run a cleanup and update.")
        clear(self.checks_list)
        shown = todo + [c for c in checks if c.level in ("info", "ok")][: max(0, 7 - len(todo))]
        for c in shown:
            row = Adw.ActionRow(title=esc(c.title), subtitle=esc(c.detail))
            row.set_subtitle_lines(2)
            row.add_prefix(status_icon(c.level))
            if c.fix_label and (c.steps or c.goto):
                b = button(c.fix_label, css="suggested-action" if c.level == "bad" else None)
                b.set_valign(Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, ch=c: self.fix(ch))
                row.add_suffix(b)
            self.checks_list.append(row)
        self.win.set_badge("dashboard", len(todo), bad=any(c.level == "bad" for c in todo))

    def fix(self, check) -> None:
        if check.goto:
            self.win.goto(check.goto)
        elif check.steps:
            self.run(check.fix_label or check.title, check.steps, check.detail, done=lambda ok: ok and self.load_health())

    def tick(self) -> bool:
        s = self.sampler.sample()
        self.ticks += 1
        self.cpu_num.set_text(f"{s.cpu:.0f}%")
        self.cpu_num.set_css_classes(["big-num", f"{level_color(s.cpu, 60, 85)}-text" if s.cpu >= 60 else "big-num"])
        info = [f"load {s.load[0]:.2f}", f"{s.procs} processes"]
        if s.freq_mhz:
            info.insert(0, f"{s.freq_mhz / 1000:.1f} GHz")
        self.cpu_info.set_text(" · ".join(info))
        self.cpu_graph.push(s.cpu)
        if len(self.core_bars) != len(s.per_cpu):
            clear(self.cores)
            self.core_bars = [MiniBar(height=30 if len(s.per_cpu) <= 16 else 22, warn=70, crit=90, vertical=True) for _ in s.per_cpu]
            for b in self.core_bars:
                b.set_hexpand(True)
                b.set_tooltip_text("CPU core")
                self.cores.append(b)
        for n, (b, v) in enumerate(zip(self.core_bars, s.per_cpu)):
            b.set(v / 100)
            b.set_tooltip_text(f"Core {n}: {v:.0f}%")

        self.mem_num.set_text(f"{s.mem_pct:.0f}%")
        self.mem_info.set_text(f"{human(s.mem_used)} of {human(s.mem_total)} in use · disk ↓{rate(s.disk_read)} ↑{rate(s.disk_write)}")
        self.mem_graph.push(s.mem_pct)
        if s.swap_total:
            self.swap_bar.set(s.swap_used / s.swap_total)
            self.swap_info.set_text(f"{human(s.swap_used)} / {human(s.swap_total)}")
        else:
            self.swap_info.set_text("none")

        self.net_num.set_markup(f"<span foreground='#94e2d5'>↓ {esc(rate(s.net_rx))}</span>   <span foreground='#fab387'>↑ {esc(rate(s.net_tx))}</span>")
        self.net_graph.push(s.net_rx, s.net_tx)
        self.net_info.set_text("download (teal) and upload (peach), last 90 seconds")

        if self.ticks % 4 == 1:
            self._slow()
        if self.ticks % 2 == 1 and not self.busy:
            self.busy = True
            bg(self.watcher.list, self._show_apps)
        return True

    def _slow(self) -> None:
        clear(self.disk_box)
        for m in system.mounts()[:5]:
            bar = MiniBar(height=9, warn=80, crit=90)
            bar.set(m.pct / 100)
            self.disk_box.append(vbox(hbox(label(m.mountpoint, "heading", ellipsize=True, hexpand=True), label(f"{human(m.free)} free", "dim")),
                                      bar, label(f"{human(m.used)} of {human(m.total)} · {m.fstype}", "dim"), spacing=4))
        t = system.cpu_temp()
        if t:
            self.temp_num.set_text(f"{t:.0f}°C")
            self.temp_graph.push(t)
            fans = system.fans()
            self.temp_info.set_text("CPU" + (f" · fan {fans[0]['rpm']} rpm" if fans else "") + (" · running hot" if t > 85 else ""))
        else:
            self.temp_num.set_text("--")
            self.temp_info.set_text("No temperature sensors found.")
        b = system.battery()
        prof = system.power_profile()
        mode = f"Power mode: {prof['current']}" if prof.get("available") else ""
        if b:
            self.bat_num.set_text(f"{b['percent']:.0f}%")
            self.bat_bar.set(b["percent"] / 100)
            parts = ["charging" if b.get("plugged") else "on battery"]
            if b.get("secs_left") and not b.get("plugged"):
                parts.append(f"{duration(b['secs_left'])} left")
            if b.get("health"):
                parts.append(f"health {b['health']:.0f}%")
            if mode:
                parts.append(mode)
            self.bat_info.set_text(" · ".join(parts))
        else:
            self.bat_num.set_text("AC")
            self.bat_bar.set(1)
            self.bat_info.set_text("No battery - plugged-in desktop." + (f"\n{mode}" if mode else "") + f"\nUp for {duration(system.uptime_seconds())}")

    def _show_apps(self, procs) -> None:
        self.busy = False
        groups = sorted(system.app_groups(procs), key=lambda g: (-g["cpu"], -g["mem"]))[:8]
        clear(self.apps_list)
        me = os.environ.get("USER", "")
        owner = {p.pid: p.user for p in procs}
        for g in groups:
            row = Adw.ActionRow(title=esc(g["name"]), subtitle=f"{g['cpu']:.1f}% CPU · {human(g['mem'])}" + (f" · {g['count']} processes" if g["count"] > 1 else ""))
            bar = MiniBar(width=60, height=6, warn=40, crit=80)
            bar.set(min(1.0, g["cpu"] / 100))
            row.add_suffix(bar)
            if all(owner.get(p) == me for p in g["pids"]):
                end = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="End this app")
                end.add_css_class("flat")
                end.set_valign(Gtk.Align.CENTER)
                end.connect("clicked", lambda _b, gg=g: self._end(gg))
                row.add_suffix(end)
            self.apps_list.append(row)

    def _end(self, g: dict) -> None:
        from ...core.run import Step
        self.run(f"End {g['name']}", [Step(f"End {g['name']}", ["kill", "-TERM", *map(str, g["pids"])], ok_codes=(0, 1))],
                 "The app gets a chance to close cleanly. Unsaved work may be lost.", reload=False)


PAGE = DashboardPage
