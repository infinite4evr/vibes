"""Power & hardware: battery (health, charge limit, history graph), power modes, keep awake, shutdown/sleep timers,
temperatures and CPU speed, connected devices, specs, and session actions."""

from __future__ import annotations

import glob
import os
import time

from gi.repository import Adw, Gtk, Pango

from ...core import devices, power, system
from ...core.fmt import duration, human
from ...core.run import Step, has, out, read, sh
from ..util import button, clear, esc, flow, hbox, label, launch, pill, status_icon, vbox
from ..widgets import LineGraph, MiniBar, RingGauge, card, rgb
from .base import Page, action_row, group, tabs

MODES = [("power-saver", "Power saver", "Longest battery life. Slower, cooler, quieter.", "power-profile-power-saver-symbolic"),
         ("balanced", "Balanced", "The right choice most of the time.", "power-profile-balanced-symbolic"),
         ("performance", "Performance", "Fastest. Louder fans and shorter battery life.", "power-profile-performance-symbolic")]

TIMER_WHAT = [("poweroff", "Shut down"), ("reboot", "Restart"), ("suspend", "Sleep")]
TIMER_WHEN = [(15, "In 15 minutes"), (30, "In 30 minutes"), (60, "In 1 hour"), (120, "In 2 hours"), (180, "In 3 hours"), (0, "Custom…")]


def charge_limit_files() -> list[str]:
    return sorted(glob.glob("/sys/class/power_supply/BAT*/charge_control_end_threshold"))


def _record(title: str, cmd: list[str], ok: bool, note: str = "") -> None:
    """Put quick actions that don't go through the step runner into Activity history too."""
    try:
        from ..activity import record
        record(title, [" ".join(cmd)], ok, note)
    except Exception:  # noqa: BLE001 - history is best effort
        pass


class HistoryGraph(Gtk.DrawingArea):
    """Battery charge (or power draw) over time with a time axis. Plugged-in stretches are shaded."""

    def __init__(self, height: int = 210):
        super().__init__()
        self.points: list[tuple[float, float, str]] = []
        self.start, self.end = 0.0, 1.0
        self.unit, self.maximum, self.color = "%", 100.0, "green"
        self.empty = ""
        self.pad_l, self.pad_b, self.pad_t, self.pad_r = 44, 22, 8, 10
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)

    def set_data(self, points: list[tuple[float, float, str]], start: float, end: float, unit: str = "%", maximum: float | None = 100.0,
                 color: str = "green", empty: str = "") -> None:
        self.points, self.start, self.end, self.unit, self.color, self.empty = points, start, max(end, start + 1), unit, color, empty
        top = max((v for _, v, _ in points), default=0)
        self.maximum = maximum if maximum else max(5.0, top * 1.15)
        self.queue_draw()

    def _x(self, t: float, w: int) -> float:
        return self.pad_l + (t - self.start) / (self.end - self.start) * (w - self.pad_l - self.pad_r)

    def _y(self, v: float, h: int) -> float:
        return self.pad_t + (1 - min(1.0, max(0.0, v / self.maximum))) * (h - self.pad_t - self.pad_b)

    def _text(self, cr, text: str, x: float, y: float, align: float = 0.0) -> None:
        from gi.repository import PangoCairo
        layout = self.create_pango_layout(text)
        desc = self.get_pango_context().get_font_description().copy()
        desc.set_size(int(8.5 * Pango.SCALE))
        layout.set_font_description(desc)
        tw, th = layout.get_pixel_size()
        cr.move_to(x - tw * align, y - th / 2)
        PangoCairo.show_layout(cr, layout)

    def _draw(self, _a, cr, w: int, h: int) -> None:
        span = self.end - self.start
        max_gap = 2 * 3600 if span <= 36 * 3600 else 6 * 3600
        # grid + value labels
        cr.set_line_width(1)
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            y = round(self._y(self.maximum * frac, h)) + 0.5
            cr.set_source_rgba(*rgb("surface1", 0.6 if frac else 0.9))
            cr.move_to(self.pad_l, y)
            cr.line_to(w - self.pad_r, y)
            cr.stroke()
            cr.set_source_rgba(*rgb("overlay1", 1))
            val = self.maximum * frac
            self._text(cr, f"{val:.0f}{self.unit}" if self.unit == "%" else f"{val:.0f} {self.unit}", self.pad_l - 6, y, 1.0)
        # time labels
        fmt = "%H:%M" if span <= 36 * 3600 else "%a"
        for i in range(5):
            t = self.start + span * i / 4
            txt = "now" if i == 4 else time.strftime(fmt, time.localtime(t))
            cr.set_source_rgba(*rgb("overlay1", 1))
            self._text(cr, txt, self._x(t, w), h - self.pad_b / 2, 1.0 if i == 4 else (0.0 if i == 0 else 0.5))
        pts = self.points
        if len(pts) < 2:
            cr.set_source_rgba(*rgb("overlay1", 1))
            self._text(cr, self.empty or "No history for this period yet.", (w + self.pad_l) / 2, (h - self.pad_b) / 2, 0.5)
            return
        # plugged-in (charging / full) stretches
        cr.set_source_rgba(*rgb("green", 0.10))
        for (t0, _v0, s0), (t1, _v1, _s1) in zip(pts, pts[1:]):
            if s0 in ("charging", "fully-charged", "pending-charge") and t1 - t0 < max_gap:
                x0, x1 = self._x(t0, w), self._x(t1, w)
                cr.rectangle(x0, self.pad_t, max(1.0, x1 - x0), h - self.pad_t - self.pad_b)
        cr.fill()
        # line, broken where the PC was off or asleep
        segs: list[list[tuple[float, float]]] = [[]]
        prev = None
        for t, v, _s in pts:
            if prev is not None and t - prev > max_gap:
                segs.append([])
            segs[-1].append((self._x(t, w), self._y(v, h)))
            prev = t
        base = h - self.pad_b
        for seg in segs:
            if len(seg) < 2:
                if seg:
                    cr.set_source_rgba(*rgb(self.color, 1))
                    cr.arc(seg[0][0], seg[0][1], 2, 0, 6.3)
                    cr.fill()
                continue
            cr.move_to(*seg[0])
            for x, y in seg[1:]:
                cr.line_to(x, y)
            cr.set_source_rgba(*rgb(self.color, 1))
            cr.set_line_width(2)
            cr.stroke_preserve()
            cr.line_to(seg[-1][0], base)
            cr.line_to(seg[0][0], base)
            cr.close_path()
            cr.set_source_rgba(*rgb(self.color, 0.13))
            cr.fill()

    def _tooltip(self, _w, x, _y, _kb, tip) -> bool:
        if len(self.points) < 2:
            return False
        w = self.get_width()
        best = min(self.points, key=lambda p: abs(self._x(p[0], w) - x))
        if abs(self._x(best[0], w) - x) > 30:
            return False
        val = f"{best[1]:.0f}%" if self.unit == "%" else f"{best[1]:.1f} {self.unit}"
        state = {"charging": "charging", "discharging": "on battery", "fully-charged": "full, plugged in"}.get(best[2], best[2])
        tip.set_text(f"{time.strftime('%a %H:%M', time.localtime(best[0]))} · {val} · {state}")
        return True


class PowerPage(Page):
    ID = "power"
    TITLE = "Power & hardware"
    ICON = "battery-good-symbolic"
    SUBTITLE = "Battery health and history, power modes, keep awake, shutdown timer, temperatures, CPU speed and what's plugged in."
    AUTO_REFRESH = 2.0
    PALETTE = [("awake", "Keep the PC awake for a while (no sleep, no screen blank)"), ("timer", "Shut down, restart or sleep on a timer"),
               ("battery", "Battery history graph"), ("cpu", "CPU speed, turbo and overheating"),
               ("devices", "Connected devices: USB, Bluetooth, screens, sound")]

    def build(self) -> None:
        self.header()
        self.has_battery = False
        # battery hero
        self.gauge = RingGauge(128, 12)
        self.bat_title = label("…", "mid-num", wrap=True)
        self.bat_sub = label("", "subtle", wrap=True)
        self.bat_grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=28, row_spacing=8, min_children_per_line=1,
                                    max_children_per_line=3)  # wraps on narrow windows
        info = vbox(self.bat_title, self.bat_sub, self.bat_grid, spacing=6)
        info.set_hexpand(True)
        info.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(self.gauge, info, spacing=24))
        hero.add_css_class("hero")
        self.body.append(hero)

        self.power_box = vbox(spacing=18)
        self.battery_box = vbox(spacing=14)
        self.cpu_box = vbox(spacing=18)
        self.dev_box = vbox(spacing=18)
        self.specs_holder = vbox(spacing=18)
        sw, self.stack = tabs(("power", "Power", "power-profile-balanced-symbolic", self.power_box),
                              ("battery", "Battery", "battery-level-70-symbolic", self.battery_box),
                              ("cpu", "CPU & heat", "power-profile-performance-symbolic", self.cpu_box),
                              ("devices", "Devices", "media-removable-symbolic", self.dev_box),
                              ("specs", "What's inside", "computer-symbolic", self.specs_holder))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_power_tab()
        self._build_battery_tab()
        self._build_cpu_tab()
        self._ticks = 0

    # ---------------------------------------------------------------- power tab
    def _build_power_tab(self) -> None:
        # power modes
        mode_widgets: list[Gtk.ToggleButton] = []
        self.mode_buttons: dict[str, Gtk.ToggleButton] = {}
        group_btn = None
        for key, title, desc, icon in MODES:
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(28)
            content = vbox(img, label(title, "heading", xalign=0.5), label(desc, "dim", xalign=0.5, wrap=True), spacing=6)
            b = Gtk.ToggleButton()
            b.set_child(content)
            b.add_css_class("mode-card")
            b.add_css_class("card")
            if group_btn is None:
                group_btn = b
            else:
                b.set_group(group_btn)
            b.connect("toggled", self._mode_toggled, key)
            self.mode_buttons[key] = b
            mode_widgets.append(b)
        self.mode_box = flow(*mode_widgets, min_per_line=1, max_per_line=3, homogeneous=True, column_spacing=12, row_spacing=12)
        self.mode_note = label("", "dim", wrap=True)
        self.power_box.append(vbox(label("Power mode", "section-title"), self.mode_box, self.mode_note, spacing=8))
        self._mode_guard = False

        # keep awake (J2)
        self.awake_dd = Gtk.DropDown.new_from_strings([t for _, t in power.AWAKE_CHOICES])
        self.awake_dd.set_selected(1)
        self.awake_dd.set_valign(Gtk.Align.CENTER)
        self.awake_start = button("Start", css="suggested-action", on_click=self.start_awake)
        self.awake_stop = button("Stop", icon="media-playback-stop-symbolic", css="destructive-action", on_click=self.stop_awake)
        self.awake_row = Adw.ActionRow(title="Keep awake for")
        self.awake_row.set_subtitle_lines(3)
        self.awake_icon = Gtk.Image.new_from_icon_name("weather-clear-night-symbolic")
        self.awake_row.add_prefix(self.awake_icon)
        for w in (self.awake_dd, self.awake_start, self.awake_stop):
            w.set_valign(Gtk.Align.CENTER)
            self.awake_row.add_suffix(w)
        self.inhib_row = Adw.ExpanderRow(title="Other things that keep the PC awake", subtitle="Checking…")
        self.power_box.append(group("Keep awake", "Stops the PC from going to sleep and the screen from turning off, like the Caffeine app. "
                                    "Handy for downloads, long builds or a presentation. Keeps working after you close this app.",
                                    self.awake_row, self.inhib_row))
        self._inhib_rows: list[Gtk.Widget] = []

        # timers (J3)
        self.timer_pending = Gtk.ListBox()
        self.timer_pending.add_css_class("boxed-list")
        self.timer_pending.set_selection_mode(Gtk.SelectionMode.NONE)
        self.timer_pending.set_visible(False)
        self.timer_what = Adw.ComboRow(title="What", model=Gtk.StringList.new([t for _, t in TIMER_WHAT]))
        self.timer_when = Adw.ComboRow(title="When", model=Gtk.StringList.new([t for _, t in TIMER_WHEN]))
        self.timer_when.set_selected(2)
        self.timer_mins = Adw.SpinRow.new_with_range(1, 24 * 60, 5)
        self.timer_mins.set_title("Minutes from now")
        self.timer_mins.set_value(45)
        self.timer_mins.set_visible(False)
        self.timer_when.connect("notify::selected", lambda *_: self.timer_mins.set_visible(TIMER_WHEN[self.timer_when.get_selected()][0] == 0))
        self.timer_btn = button("Start timer", icon="alarm-symbolic", css="suggested-action", on_click=self.start_timer)
        start_row = Adw.ActionRow(title="Start the countdown", subtitle="You can cancel it any time before it's up.")
        start_row.add_suffix(self.timer_btn)
        self.timer_btn.set_valign(Gtk.Align.CENTER)
        tg = group("Timer", "Shut down, restart or put the PC to sleep later, e.g. after a download or when a film ends.",
                   self.timer_what, self.timer_when, self.timer_mins, start_row)
        self.power_box.append(vbox(self.timer_pending, tg, spacing=10))

        # session
        sess = []
        for text, icon, cmd, danger, explain in (
                ("Lock screen", "system-lock-screen-symbolic", ["loginctl", "lock-session"], False, ""),
                ("Suspend", "weather-clear-night-symbolic", ["systemctl", "suspend"], False, "The PC sleeps; open apps stay as they are."),
                ("Log out", "system-log-out-symbolic", ["gnome-session-quit", "--logout", "--no-prompt"], True, "Open apps will close. Save your work first."),
                ("Restart", "system-reboot-symbolic", ["systemctl", "reboot"], True, "Open apps will close. Save your work first."),
                ("Restart into BIOS", "preferences-system-symbolic", ["systemctl", "reboot", "--firmware-setup"], True,
                 "Restarts straight into the BIOS/UEFI settings screen (for Secure Boot, boot order, Fast Boot…)."),
                ("Power off", "system-shutdown-symbolic", ["systemctl", "poweroff"], True, "Open apps will close. Save your work first.")):
            b = button(text, icon=icon, css="destructive-action" if text == "Power off" else None)
            if not explain:
                b.connect("clicked", lambda _b, c=cmd: launch(c))
            else:
                b.connect("clicked", lambda _b, t=text, c=cmd, d=danger, e=explain: self.run(t, [Step(t, c)], e, danger=d, ok_label=t, reload=False))
            sess.append(b)
        fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, min_children_per_line=2, column_spacing=8, row_spacing=8)
        for b in sess:
            fb.append(b)
        self.power_box.append(vbox(label("Session", "section-title"), fb, spacing=8))
        self.limit_holder = vbox()
        self.power_box.append(self.limit_holder)
        self.power_box.append(group("More settings", "", action_row("Power settings", "Automatic suspend, screen blank, power button behaviour.",
                                                                      button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "power"])))))

    # ---------------------------------------------------------------- battery tab (J1)
    def _build_battery_tab(self) -> None:
        self.hist_range = 24
        self.hist_kind = "charge"
        r24 = Gtk.ToggleButton(label="Last 24 hours", active=True)
        r7 = Gtk.ToggleButton(label="Last 7 days", group=r24)
        kc = Gtk.ToggleButton(label="Charge", active=True)
        kr = Gtk.ToggleButton(label="Power use", group=kc)
        r24.connect("toggled", lambda b: b.get_active() and self._set_hist(hours=24))
        r7.connect("toggled", lambda b: b.get_active() and self._set_hist(hours=24 * 7))
        kc.connect("toggled", lambda b: b.get_active() and self._set_hist(kind="charge"))
        kr.connect("toggled", lambda b: b.get_active() and self._set_hist(kind="rate"))
        seg1 = hbox(r24, r7, spacing=0, css="linked")
        seg2 = hbox(kc, kr, spacing=0, css="linked")
        self.hist_controls = flow(seg1, seg2, min_per_line=1, max_per_line=2, column_spacing=12, row_spacing=8)
        self.hist_graph = HistoryGraph(220)
        self.hist_note = label("", "dim", wrap=True)
        self.hist_summary = label("", None, wrap=True)
        self.hist_card = card(self.hist_graph, self.hist_summary, self.hist_note, title="Battery history")
        self.health_holder = vbox()
        self.no_battery = vbox(spacing=8)
        img = Gtk.Image.new_from_icon_name("battery-missing-symbolic")
        img.set_pixel_size(64)
        img.add_css_class("dim")
        self.no_battery.append(img)
        self.no_battery.append(label("This computer has no battery", ["mid-num"], xalign=0.5, wrap=True))
        self.no_battery.append(label("It runs on mains power, so there's no charge history or battery health to show.", "dim", xalign=0.5, wrap=True))
        self.no_battery.set_margin_top(30)
        self.no_battery.set_visible(False)
        self.battery_box.append(self.no_battery)
        self.battery_box.append(self.hist_controls)
        self.battery_box.append(self.hist_card)
        self.battery_box.append(self.health_holder)

    def _set_hist(self, hours: int | None = None, kind: str | None = None) -> None:
        if hours:
            self.hist_range = hours
        if kind:
            self.hist_kind = kind
        self.load_history()

    def load_history(self) -> None:
        hours, kind = self.hist_range, self.hist_kind

        def work():
            b = system.battery()
            if not b:
                return None, [], {}
            pts = power.battery_history(kind, hours)
            charge = pts if kind == "charge" else power.battery_history("charge", hours)
            return b, power.downsample(pts, 500), power.history_summary(charge)
        self.bg(work, self.show_history)

    def show_history(self, res) -> None:
        b, pts, summ = res
        self.has_battery = bool(b)
        self.no_battery.set_visible(not b)
        for w in (self.hist_controls, self.hist_card, self.health_holder):
            w.set_visible(bool(b))
        if not b:
            return
        now = time.time()
        start = now - self.hist_range * 3600
        files = power.history_files(self.hist_kind)
        empty = "No history for this period yet." if files else "UPower hasn't saved any battery history yet. It records it while the laptop runs."
        if self.hist_kind == "charge":
            self.hist_graph.set_data(pts, start, now, "%", 100, "green", empty)
        else:
            self.hist_graph.set_data(pts, start, now, "W", None, "peach", empty)
        self.hist_note.set_text(("Shaded = plugged in. " if self.hist_kind == "charge" else "How many watts the laptop drew from the battery. ")
                                + "Gaps are times the laptop was off or asleep. Hover the graph for exact values.")
        if summ:
            parts = [f"Between {summ['low']:.0f}% and {summ['high']:.0f}%"]
            if summ.get("on_battery"):
                parts.append(f"about {duration(summ['on_battery'])} on battery")
            if summ.get("charges"):
                parts.append(f"plugged in to charge {summ['charges']} time{'s' if summ['charges'] != 1 else ''}")
            self.hist_summary.set_text(", ".join(parts) + ".")
        else:
            self.hist_summary.set_text("")
        # health
        clear(self.health_holder)
        h = b.get("health")
        rows = []
        if h:
            lvl = "ok" if h >= 80 else ("warn" if h >= 60 else "bad")
            rows.append(action_row(f"Health: {h:.0f}% of its original capacity",
                                   "Good: it still holds most of what it did when new." if h >= 80 else
                                   "OK: it has lost some capacity, which is normal after a few years." if h >= 60 else
                                   "Worn: it holds much less than new. A replacement battery would give you back your battery life.",
                                   prefix=status_icon(lvl)))
        if b.get("cycles"):
            rows.append(action_row(f"Charge cycles: {b['cycles']}", "One cycle = using 100% of the battery in total (e.g. twice from 100% to 50%). "
                                   "Most laptop batteries are made for 500 to 1000 cycles."))
        if b.get("rate"):
            rows.append(action_row(f"Power draw now: {b['rate']:.1f} W", "Lower is better for battery life. Around 5–10 W is typical when idle; "
                                   "games and builds can use 30 W or more."))
        left = b.get("time_to_empty") or b.get("time_to_full")
        if left:
            rows.append(action_row(("Time until empty: " if b.get("time_to_empty") else "Time until full: ") + left, "An estimate based on the power draw right now."))
        if b.get("energy_full") and b.get("energy_design"):
            rows.append(action_row(f"Capacity: {b['energy_full']:.1f} Wh now, {b['energy_design']:.1f} Wh when new", "Wh = watt-hours, the size of the battery's 'tank'."))
        if rows:
            self.health_holder.append(group("Battery details", "", *rows))

    # ---------------------------------------------------------------- CPU tab (J4)
    def _build_cpu_tab(self) -> None:
        self.temp_graph = LineGraph(("peach", "red"), points=90, height=80, maximum=110)
        self.temp_list = vbox(spacing=6)
        self.fan_label = label("", "dim", wrap=True)
        self.cpu_box.append(card(self.temp_graph, self.temp_list, self.fan_label, title="Temperatures"))
        self.cpu_speed_big = label("…", "mid-num", wrap=True)
        self.cpu_speed_sub = label("", "dim", wrap=True)
        self.core_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=10, row_spacing=10,
                                     min_children_per_line=2, max_children_per_line=8)
        self.core_tiles: dict[int, tuple[Gtk.Label, MiniBar]] = {}
        self.cpu_box.append(card(self.cpu_speed_big, self.cpu_speed_sub, self.core_flow, title="CPU speed right now"))
        self.cpu_facts = vbox()
        self.cpu_box.append(self.cpu_facts)
        self._cpu_sig = None

    def load_cpu(self) -> None:
        self.bg(power.cpu_speeds, self.show_cpu)

    def show_cpu(self, info: dict) -> None:
        cores = info["cores"]
        if not cores:
            self.cpu_speed_big.set_text("Speed unknown")
            self.cpu_speed_sub.set_text("This system doesn't report CPU speeds (common in virtual machines).")
        else:
            avg, top, mx = info.get("avg_mhz"), info.get("top_mhz"), info.get("max_mhz")
            self.cpu_speed_big.set_text(f"{(avg or 0) / 1000:.2f} GHz on average" if avg else "Speed unknown")
            bits = []
            if top:
                bits.append(f"fastest core {top / 1000:.2f} GHz")
            if mx:
                bits.append(f"top speed {mx / 1000:.2f} GHz")
            if info["source"] == "cpuinfo":
                bits.append("limits aren't reported here (virtual machine?)")
            text = ", ".join(bits)
            self.cpu_speed_sub.set_text((text[:1].upper() + text[1:] + ". " if text else "") + "Cores slow down when idle to save power; that's normal.")
        sig = tuple(c["cpu"] for c in cores)
        if sig != self._cpu_sig:
            self._cpu_sig = sig
            clear(self.core_flow)
            self.core_tiles.clear()
            for c in cores:
                v = label("", ["heading"])
                bar = MiniBar(height=6, warn=101, crit=101, color="blue")
                tile = vbox(hbox(label(f"CPU {c['cpu']}", "dim", hexpand=True), v), bar, spacing=4)
                self.core_flow.append(tile)
                self.core_tiles[c["cpu"]] = (v, bar)
            ch = self.core_flow.get_first_child()
            while ch is not None:
                ch.set_focusable(False)
                ch = ch.get_next_sibling()
        top = info.get("max_mhz") or max((c["mhz"] or 0 for c in cores), default=1) or 1
        for c in cores:
            v, bar = self.core_tiles.get(c["cpu"], (None, None))
            if v is None:
                continue
            v.set_text(f"{c['mhz'] / 1000:.2f} GHz" if c["mhz"] else "?")
            bar.set((c["mhz"] or 0) / (c["max"] or top))
        if "cpu_facts" not in self.tab_loaded:
            self.tab_loaded.add("cpu_facts")
            self._show_cpu_facts(info)

    def _show_cpu_facts(self, info: dict) -> None:
        clear(self.cpu_facts)
        rows = [action_row(t, d) for t, d in power.cpu_facts(info)]
        lvl, text = power.throttle_verdict(info.get("throttle_core"), info.get("throttle_pkg"))
        rows.append(action_row("Slowing down to cool off (throttling)", text, prefix=status_icon(lvl)))
        g = group("How the CPU speed is managed", "Read-only. Your power mode (Power tab) sets these through power-profiles-daemon, "
                  "so there's no need to change them by hand.", *rows)
        self.cpu_facts.append(g)

    # ---------------------------------------------------------------- devices tab (J5)
    def load_devices(self) -> None:
        self.loading(self.dev_box, "Looking for devices…")
        self.bg(devices.all_devices, self.show_devices)

    def show_devices(self, d: dict) -> None:
        clear(self.dev_box)
        refresh = button("Look again", icon="view-refresh-symbolic", css="flat", on_click=self.load_devices)
        self.dev_box.append(hbox(label("Everything plugged in or built in, in plain names. Nothing here changes your PC.", "dim", wrap=True, hexpand=True),
                                 refresh))
        # screens
        rows = []
        for s in d.get("displays", []):
            name = s["name"] or s["kind"]
            sub = [s["kind"] if s["name"] else "", f"{s['inches']:.0f}-inch" if s.get("inches") else "", s["best_mode"] and f"best {s['best_mode']}",
                   s["connector"]]
            rows.append(action_row(name, " · ".join(x for x in sub if x), pill("in use" if s["enabled"] else "connected", "ok" if s["enabled"] else "neutral")
                                   if s["connected"] else pill("empty port", "neutral"),
                                   prefix=Gtk.Image.new_from_icon_name("video-display-symbolic")))
        connected = [r for r, s in zip(rows, d.get("displays", [])) if s["connected"]]
        ports = [r for r, s in zip(rows, d.get("displays", [])) if not s["connected"]]
        if connected or ports:
            g = group("Screens", "", *connected)
            if ports:
                ex = Adw.ExpanderRow(title=esc(f"Empty display ports ({len(ports)})"), subtitle="Sockets you could plug another screen into.")
                for r in ports:
                    ex.add_row(r)
                g.add(ex)
            self.dev_box.append(g)
        # USB
        usb, note = d.get("usb", ([], ""))
        rows = []
        for u in usb:
            kind = devices.usb_kind(u["name"])
            rows.append(action_row(u["name"].replace("_", " "), " · ".join(x for x in (kind, f"ID {u['id']}") if x),
                                   prefix=Gtk.Image.new_from_icon_name("media-removable-symbolic")))
        self.dev_box.append(group("USB devices", note or "Includes built-in parts that use USB inside the laptop (camera, Bluetooth, fingerprint reader).", *rows)
                            if rows else group("USB devices", note or "No USB devices found."))
        # Bluetooth
        bt, note = d.get("bluetooth", ([], ""))
        rows = [action_row(b["name"], b["mac"], pill("connected", "ok") if b["connected"] else pill("paired", "neutral"),
                           prefix=Gtk.Image.new_from_icon_name("bluetooth-symbolic")) for b in bt]
        self.dev_box.append(group("Bluetooth", note, *rows))
        # sound
        sinks, sources, note = d.get("sound", ([], [], ""))
        rows = []
        for s in sinks:
            rows.append(action_row(s["description"], "Speakers / headphones" + (" · playing now" if s["state"] == "running" else ""),
                                   *([pill("default", "accent")] if s["default"] else []),
                                   prefix=Gtk.Image.new_from_icon_name("audio-speakers-symbolic")))
        for s in sources:
            rows.append(action_row(s["description"], "Microphone" + (" · in use now" if s["state"] == "running" else ""),
                                   *([pill("default", "accent")] if s["default"] else []),
                                   prefix=Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")))
        self.dev_box.append(group("Sound", note or "Where sound comes out and goes in. Change the default in GNOME Settings > Sound.", *rows)
                            if rows else group("Sound", note))
        # cameras
        cams = d.get("cameras", [])
        if cams:
            self.dev_box.append(group("Cameras", "", *[action_row(c, "", prefix=Gtk.Image.new_from_icon_name("camera-web-symbolic")) for c in cams]))
        # memory
        self._show_memory(d.get("memory"))
        # PCI
        pci = d.get("pci", [])
        if pci:
            g = group("Inside the PC", "Cards and chips on the motherboard.")
            by: dict[str, list[dict]] = {}
            for p in pci:
                by.setdefault(p["group"], []).append(p)
            for name, _classes in devices.PCI_GROUPS:
                for p in by.get(name, []):
                    g.add(action_row(f"{p['plain']}: {p['vendor']} {p['device']}".strip(), p["cls"]))
            chips = by.get("Chipset", [])
            if chips:
                ex = Adw.ExpanderRow(title=esc(f"Motherboard chips ({len(chips)})"), subtitle="Bridges, controllers and helpers. You rarely need these.")
                for p in chips:
                    r = Adw.ActionRow(title=esc(f"{p['vendor']} {p['device']}"), subtitle=esc(p["cls"]))
                    ex.add_row(r)
                g.add(ex)
            self.dev_box.append(g)
        elif d.get("pci_note"):
            self.dev_box.append(group("Inside the PC", d["pci_note"]))

    def _show_memory(self, mem) -> None:
        total = devices.mem_total()
        btn = button("Show module details", css="flat", on_click=self.load_memory,
                     tooltip="Reading memory details from the BIOS needs your password once")
        if mem is None:
            g = group("Memory (RAM)", "", action_row(f"{human(total)} in total" if total else "Memory",
                                                     "Which sticks are installed, their speed and make are stored in the BIOS; reading them needs admin rights.", btn,
                                                     prefix=Gtk.Image.new_from_icon_name("media-flash-symbolic")))
            self.dev_box.append(g)
            return
        mods, slots = mem
        g = group("Memory (RAM)", f"{human(total)} usable · {len(mods)} of {slots} slots used" if slots else f"{human(total)} usable", suffix=button(
            icon="view-refresh-symbolic", css="flat", tooltip="Read again", on_click=self.load_memory))
        for m in mods:
            speed = m["configured"] or m["speed"]
            g.add(action_row(f"{m['size']} {m['type']}".strip() + (f" at {speed}" if speed and speed != "Unknown" else ""),
                             " · ".join(x for x in (m["slot"], m["form"], m["maker"], m["part"]) if x and x not in ("Unknown", "Other")),
                             prefix=Gtk.Image.new_from_icon_name("media-flash-symbolic")))
        if not mods:
            g.add(action_row("No details", "The BIOS didn't list any memory modules (common in virtual machines)."))
        self.dev_box.append(g)

    def load_memory(self) -> None:
        self.run("Read memory details", devices.memory_modules_steps(), "Reads what the BIOS knows about the memory sticks (size, speed, maker). "
                 "Nothing is changed.", ok_label="Read", reload=False, done=lambda ok: ok and self.load_devices())

    # ---------------------------------------------------------------- lifecycle
    def load(self) -> None:
        self.tick()
        self.bg(lambda: (system.hardware(), system.identity()), self.show_specs)
        self.show_limit()
        self.load_awake_extra()
        self.refresh_timers(bus=True)
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "battery":
            self.load_history()
        elif name == "cpu":
            self.tab_loaded.discard("cpu_facts")
            self.load_cpu()
        elif name == "devices":
            self.load_devices()

    def tick(self) -> bool:
        self.bg(lambda: (system.battery(), system.power_profile(), system.temperatures(), system.fans()), self.show_live)
        self.show_awake(power.keep_awake_status())
        self._ticks += 1
        if self._ticks % 3 == 0:
            self.refresh_timers()
        if self.stack.get_visible_child_name() == "cpu" and self._ticks > 1:
            self.load_cpu()
        return True

    # ---------------------------------------------------------------- live
    def show_live(self, res) -> None:
        b, prof, temps, fans = res
        clear(self.bat_grid)
        if b:
            pct = b.get("percentage") or b["percent"]
            color = "green" if pct > 40 else ("peach" if pct > 15 else "red")
            self.gauge.set(pct, f"{pct:.0f}%", "charging" if b.get("plugged") else "battery", color)
            state = b.get("state") or ("charging" if b.get("plugged") else "discharging")
            if b.get("plugged"):
                self.bat_title.set_text("Plugged in" + (f", full in {b['time_to_full']}" if b.get("time_to_full") else (", fully charged" if state == "fully-charged" else "")))
            else:
                left = b.get("time_to_empty") or (duration(b["secs_left"]) if b.get("secs_left") else "")
                self.bat_title.set_text("On battery" + (f", about {left} left" if left else ""))
            h = b.get("health")
            self.bat_sub.set_text(("Battery health is " + ("good." if h >= 80 else "OK." if h >= 60 else "worn; it holds much less than new.")) if h else "")
            facts = [("Health", f"{h:.0f}% of original capacity" if h else "?"), ("Charge cycles", str(b.get("cycles") or "?")),
                     ("Power draw", f"{b['rate']:.1f} W" if b.get("rate") else "?"),
                     ("Capacity", f"{b['energy_full']:.1f} of {b['energy_design']:.1f} Wh" if b.get("energy_full") and b.get("energy_design") else "?"),
                     ("Battery", " ".join(x for x in (b.get("vendor", ""), b.get("model", ""), b.get("technology", "")) if x) or "?")]
            for k, v in facts:
                cell = vbox(label(k.upper(), "stat-label"), label(v, "heading", wrap=True), spacing=0)
                self.bat_grid.append(cell)
                cell.get_parent().set_focusable(False)
        else:
            self.gauge.set(100, "AC", "no battery", "blue")
            self.bat_title.set_text("Desktop PC on mains power")
            self.bat_sub.set_text(f"No battery found. Up for {duration(system.uptime_seconds())}.")
        # modes
        self._mode_guard = True
        if prof.get("available"):
            self.mode_box.set_sensitive(True)
            for key, btn in self.mode_buttons.items():
                btn.set_visible(key in prof["profiles"])
                btn.set_active(key == prof["current"])
            self.mode_note.set_text("Tip: Power saver also turns on automatically when the battery gets low (GNOME setting).")
        else:
            self.mode_box.set_sensitive(False)
            self.mode_note.set_text("Power modes need power-profiles-daemon (installed by default on Ubuntu desktop).")
        self._mode_guard = False
        # temps
        cpu = system.cpu_temp()
        top = max((t["current"] for t in temps), default=0)
        self.temp_graph.push(cpu or 0, top)
        if self.stack.get_visible_child_name() != "cpu" and self.temp_list.get_first_child() is not None:
            return
        clear(self.temp_list)
        seen = set()
        for t in sorted(temps, key=lambda t: -t["current"])[:10]:
            key = (t["chip"], t["label"])
            if key in seen:
                continue
            seen.add(key)
            crit = t.get("critical") or t.get("high") or 100
            bar = MiniBar(width=160, height=8, warn=75, crit=90)
            bar.set(t["current"] / crit if crit else 0)
            name = f"{t['label']} ({t['chip']})" if t["label"] != t["chip"] else t["chip"]
            self.temp_list.append(hbox(label(name, None, ellipsize=True, hexpand=True), bar,
                                       label(f"{t['current']:.0f}°C", ["heading", "bad-text" if t["current"] >= 90 else ("warn-text" if t["current"] >= 75 else "ok-text")])))
        if not temps:
            self.temp_list.append(label("No temperature sensors found (common in virtual machines). Installing lm-sensors can help on real hardware.", "dim", wrap=True))
        self.fan_label.set_text(" · ".join(f"{f['label']}: {f['rpm']} rpm" for f in fans) if fans else
                                "Graph: CPU (orange) and hottest sensor (red), last 3 minutes.")

    def _mode_toggled(self, btn: Gtk.ToggleButton, key: str) -> None:
        if self._mode_guard or not btn.get_active():
            return
        r = sh(["powerprofilesctl", "set", key], timeout=8)
        name = {k: t for k, t, _, _ in MODES}[key]
        self.toast(f"Power mode: {name}" if r.ok else f"Couldn't switch: {(r.err or r.out).strip()[:120]}")

    # ---------------------------------------------------------------- keep awake
    def show_awake(self, st: dict | None) -> None:
        on = st is not None
        self.awake_dd.set_visible(not on)
        self.awake_start.set_visible(not on)
        self.awake_stop.set_visible(on)
        self.awake_icon.set_from_icon_name("alarm-symbolic" if on else "weather-clear-night-symbolic")
        for c in ("accent-text",):
            (self.awake_icon.add_css_class if on else self.awake_icon.remove_css_class)(c)
        if not on:
            self.awake_row.set_title("Keep awake for")
            self.awake_row.set_subtitle("Off. The PC sleeps and the screen turns off as usual.")
            return
        self.awake_row.set_title("Keeping the PC awake")
        what = "no sleep, no screen blank" if st.get("screen") else "no automatic sleep"
        if st.get("until"):
            self.awake_row.set_subtitle(esc(f"On until {power.clock(st['until'])} ({power.human_left(st['left'] or 0)} left) · {what}."))
        else:
            self.awake_row.set_subtitle(esc(f"On until you press Stop · {what}. It keeps going after you close this app."))

    def start_awake(self, seconds: int | None = None) -> None:
        if seconds is None:
            seconds = power.AWAKE_CHOICES[self.awake_dd.get_selected()][0]
        label_ = next((t for s, t in power.AWAKE_CHOICES if s == seconds), f"{seconds}s")

        def work():
            try:
                return power.start_keep_awake(seconds), ""
            except (RuntimeError, OSError) as e:  # expected problems (no logind, no permission) become a toast, not a crash
                return None, str(e)

        def done(res) -> None:
            st, err = res
            _record(f"Keep awake: {label_.lower()}", power.keep_awake_cmd(seconds), not err, err)
            if err:
                self.toast(f"Couldn't keep the PC awake: {err}", 6)
                return
            self.show_awake(st or power.keep_awake_status())
            self.toast("The PC will stay awake " + ("until you stop it." if not seconds else f"for {label_}."))
            self.load_awake_extra()
        self.bg(work, done)

    def stop_awake(self) -> None:
        def done(stopped: bool) -> None:
            _record("Stop keep awake", ["kill", "(the keep-awake process)"], True)
            self.show_awake(None)
            self.toast("Back to normal: the PC can sleep again." if stopped else "Keep awake was already off.")
            self.load_awake_extra()
        self.bg(power.stop_keep_awake, done)

    def load_awake_extra(self) -> None:
        self.bg(power.inhibitors, self.show_inhibitors)

    def show_inhibitors(self, items: list[dict]) -> None:
        for r in self._inhib_rows:
            self.inhib_row.remove(r)
        self._inhib_rows = []
        others = [i for i in items if i["who"] != power.WHO and i["mode"] == "block" and any(
            w in i["what"].split(":") for w in ("sleep", "idle", "shutdown"))]
        self.inhib_row.set_subtitle(esc(f"{len(others)} app{'s' if len(others) != 1 else ''} stopping sleep or shutdown right now" if others else
                                        "Nothing else is stopping sleep right now. (Short delays by GNOME and the network are normal.)"))
        self.inhib_row.set_enable_expansion(bool(others))
        for i in others:
            r = Adw.ActionRow(title=esc(i["who"] or "?"), subtitle=esc(power.explain_inhibitor(i) + (f" · process {i['pid']}" if i.get("pid") else "")))
            r.set_subtitle_lines(3)
            self.inhib_row.add_row(r)
            self._inhib_rows.append(r)

    # ---------------------------------------------------------------- timers
    def refresh_timers(self, bus: bool = False) -> None:
        def work():
            res = []
            s = power.parse_scheduled(read(power.SCHEDULED_FILE)) if not bus else power.scheduled_shutdown()
            if s:
                res.append(s)
            t = power.suspend_timer() if power.SUSPEND_FILE.exists() else None
            if t:
                res.append(t)
            return res
        self.bg(work, self.show_timers)

    def show_timers(self, pending: list[dict]) -> None:
        clear(self.timer_pending)
        self.timer_pending.set_visible(bool(pending))
        now = time.time()
        for p in pending:
            what = {"poweroff": "shut down", "reboot": "restart", "suspend": "go to sleep", "halt": "shut down", "kexec": "restart"}.get(p["mode"], p["mode"])
            left = p["when"] - now
            r = Adw.ActionRow(title=esc(f"The PC will {what} at {power.clock(p['when'])}"),
                              subtitle=esc(f"In {power.human_left(left)}." if left > 0 else "Any moment now."))
            r.add_prefix(status_icon("warn"))
            b = button("Cancel", css="destructive-action", on_click=lambda m=p["mode"]: self.cancel_timer(m))
            b.set_valign(Gtk.Align.CENTER)
            r.add_suffix(b)
            self.timer_pending.append(r)

    def start_timer(self) -> None:
        kind = TIMER_WHAT[self.timer_what.get_selected()][0]
        mins = TIMER_WHEN[self.timer_when.get_selected()][0] or int(self.timer_mins.get_value())
        explain = {"poweroff": "Save your work: open apps will close when the PC shuts down.",
                   "reboot": "Save your work: open apps will close when the PC restarts.",
                   "suspend": "The PC goes to sleep; open apps stay as they are."}[kind]
        name = dict(TIMER_WHAT)[kind]
        self.run(f"{name} {power.in_words(mins)}", power.timer_steps(kind, mins), explain + " You can cancel it here any time before then.",
                 ok_label="Start timer", reload=False, done=lambda ok: self.refresh_timers(bus=True))

    def cancel_timer(self, mode: str) -> None:
        self.run("Cancel the timer", power.cancel_timer_steps("suspend" if mode == "suspend" else "shutdown"), ask=False, reload=False,
                 done=lambda ok: (self.refresh_timers(bus=True), ok and self.toast("Timer cancelled.")))

    # ---------------------------------------------------------------- charge limit
    def show_limit(self) -> None:
        clear(self.limit_holder)
        files = charge_limit_files()
        if not files:
            return
        cur = read(files[0]).strip()
        rows = []
        for val, title, desc in (("80", "Protect battery (stop at 80%)", "Best if the laptop is plugged in most of the time. Doubles battery lifespan."),
                                 ("90", "Stop at 90%", "A middle ground."),
                                 ("100", "Charge to 100%", "Maximum runtime today, faster wear.")):
            active = cur == val
            b = button("Current" if active else "Use", css="flat" if not active else ["flat", "accent-text"])
            b.set_sensitive(not active)
            b.connect("clicked", lambda _b, v=val: self.set_limit(v))
            rows.append(action_row(title, desc, b))
        self.limit_holder.append(group("Battery charge limit", f"Currently stops charging at {cur}%. Saved so it survives restarts.", *rows))

    def set_limit(self, val: str) -> None:
        files = charge_limit_files()
        lines = "".join(f"w {f} - - - - {val}\\n" for f in files)
        writes = "; ".join(f"echo {val} > {f}" for f in files)
        steps = [Step(f"Stop charging at {val}%", ["bash", "-c", writes], root=True),
                 Step("Keep it after restart", ["bash", "-c", f"printf '{lines}' > /etc/tmpfiles.d/pc-battery-limit.conf"], root=True)]
        self.run(f"Charge limit {val}%", steps, "Takes effect right away.", ok_label="Apply", reload=False, done=lambda ok: self.show_limit())

    # ---------------------------------------------------------------- specs
    def show_specs(self, res) -> None:
        hw, ident = res
        clear(self.specs_holder)
        facts = [("Computer", ident.get("model", "")), ("Processor", f"{hw['cpu']} ({hw['cores']} cores, {hw['threads']} threads)"),
                 ("Memory", human(hw["ram"])), ("Graphics", ", ".join(hw["gpus"]) or "?"),
                 ("Storage", ", ".join(f"{d['model'] or d['name']} {human(d['size'])} {d['kind']}" for d in hw["disks"]) or "?"),
                 ("Motherboard", hw["board"] or "?"), ("BIOS", hw["bios"] or "?"),
                 ("System", f"{ident.get('os', '')} · kernel {ident.get('kernel', '')} · {hw['arch']}"),
                 ("Desktop", f"{os.environ.get('XDG_CURRENT_DESKTOP', '?')} on {os.environ.get('XDG_SESSION_TYPE', '?')}")]
        text = "\n".join(f"{k}: {v}" for k, v in facts)
        copy = button("Copy", icon="edit-copy-symbolic", css="flat", on_click=lambda: (self.get_clipboard().set(text), self.toast("Specs copied.")))
        g = group("What's inside", "", suffix=copy)
        for k, v in facts:
            r = action_row(k, v)
            r.set_subtitle_selectable(True)
            g.add(r)
        if has("nvidia-smi"):
            g.add(action_row("NVIDIA", out(["nvidia-smi", "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total",
                                            "--format=csv,noheader"]) or "driver not loaded"))
        self.specs_holder.append(g)
        self.specs_holder.append(label("Tip: the Devices tab lists what's plugged in (USB, Bluetooth, screens, sound) and the memory sticks.", "dim", wrap=True))

    # ---------------------------------------------------------------- command palette
    def palette_action(self, key: str) -> None:
        if key == "awake":
            self.stack.set_visible_child_name("power")
            from ..dialogs import ChoiceDialog
            rows = [(str(s), f"Keep awake: {t.lower()}" if s else "Keep awake until I stop it", "No sleep and no screen blank")
                    for s, t in power.AWAKE_CHOICES]
            if power.keep_awake_status():
                rows.insert(0, ("stop", "Stop keeping the PC awake", "Let it sleep as usual again"))
            ChoiceDialog("Keep the PC awake", rows, lambda k: k and (self.stop_awake() if k == "stop" else self.start_awake(int(k))),
                         search=False).present(self.win)
        elif key == "timer":
            self.stack.set_visible_child_name("power")
            self.timer_btn.grab_focus()
        elif key in ("battery", "cpu", "devices"):
            self.stack.set_visible_child_name(key)


PAGE = PowerPage
