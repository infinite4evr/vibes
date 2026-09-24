"""Power & hardware: battery health and charge limit, power modes, temperatures and fans, specs, and session actions."""

from __future__ import annotations

import glob
import os

from gi.repository import Gtk

from ...core import system
from ...core.fmt import duration, human
from ...core.run import Step, has, out, read, sh
from ..util import button, clear, hbox, label, launch, vbox
from ..widgets import LineGraph, MiniBar, RingGauge, card
from .base import Page, action_row, group

MODES = [("power-saver", "Power saver", "Longest battery life. Slower, cooler, quieter.", "power-profile-power-saver-symbolic"),
         ("balanced", "Balanced", "The right choice most of the time.", "power-profile-balanced-symbolic"),
         ("performance", "Performance", "Fastest. Louder fans and shorter battery life.", "power-profile-performance-symbolic")]


def charge_limit_files() -> list[str]:
    return sorted(glob.glob("/sys/class/power_supply/BAT*/charge_control_end_threshold"))


class PowerPage(Page):
    ID = "power"
    TITLE = "Power & hardware"
    ICON = "battery-good-symbolic"
    SUBTITLE = "Battery health, power modes, temperatures, what's inside this PC, and restart/shutdown."
    AUTO_REFRESH = 2.0

    def build(self) -> None:
        self.header()
        # battery hero
        self.gauge = RingGauge(128, 12)
        self.bat_title = label("…", "mid-num", wrap=True)
        self.bat_sub = label("", "subtle", wrap=True)
        self.bat_grid = Gtk.Grid(column_spacing=28, row_spacing=4)
        info = vbox(self.bat_title, self.bat_sub, self.bat_grid, spacing=6)
        info.set_hexpand(True)
        info.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(self.gauge, info, spacing=24))
        hero.add_css_class("hero")
        self.body.append(hero)

        # power modes
        self.mode_box = hbox(spacing=12, homogeneous=True)
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
            self.mode_box.append(b)
        self.mode_note = label("", "dim", wrap=True)
        self.body.append(vbox(label("Power mode", "section-title"), self.mode_box, self.mode_note, spacing=8))
        self._mode_guard = False

        self.limit_holder = vbox()
        self.body.append(self.limit_holder)

        # temps
        self.temp_graph = LineGraph(("peach", "red"), points=90, height=80, maximum=110)
        self.temp_list = vbox(spacing=6)
        self.fan_label = label("", "dim")
        self.body.append(card(self.temp_graph, self.temp_list, self.fan_label, title="Temperatures"))

        self.specs_holder = vbox()
        self.body.append(self.specs_holder)

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
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, min_children_per_line=2, column_spacing=8, row_spacing=8)
        for b in sess:
            flow.append(b)
        self.body.append(vbox(label("Session", "section-title"), flow, spacing=8))
        self.body.append(group("More settings", "", action_row("Power settings", "Automatic suspend, screen blank, power button behaviour.",
                                                                 button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "power"])))))

    def load(self) -> None:
        self.tick()
        self.bg(lambda: (system.hardware(), system.identity()), self.show_specs)
        self.show_limit()

    def tick(self) -> bool:
        self.bg(lambda: (system.battery(), system.power_profile(), system.temperatures(), system.fans()), self.show_live)
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
            for n, (k, v) in enumerate(facts):
                self.bat_grid.attach(label(k.upper(), "stat-label"), n % 3, (n // 3) * 2, 1, 1)
                self.bat_grid.attach(label(v, "heading"), n % 3, (n // 3) * 2 + 1, 1, 1)
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
        clear(self.temp_list)
        cpu = system.cpu_temp()
        top = max((t["current"] for t in temps), default=0)
        self.temp_graph.push(cpu or 0, top)
        seen = set()
        for t in sorted(temps, key=lambda t: -t["current"])[:10]:
            key = (t["chip"], t["label"])
            if key in seen:
                continue
            seen.add(key)
            crit = t.get("critical") or t.get("high") or 100
            bar = MiniBar(width=180, height=8, warn=75, crit=90)
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


PAGE = PowerPage
