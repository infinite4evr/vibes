"""Tweaks: explained system tweaks for a dev laptop (apply/undo), desktop switches, look and keyboard."""

from __future__ import annotations

import ast

from gi.repository import Adw, Gtk

from ...core import tweaks
from ...core.run import out, sh
from ..util import button, clear, esc, hbox, label, pill, status_icon, vbox
from ..widgets import card
from .base import Page, group, switch_row

ACCENTS = ["blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "slate"]
SCALES = [("100% (normal)", 1.0), ("110%", 1.1), ("125%", 1.25), ("150%", 1.5)]
CAPS = [("Caps Lock (normal)", ""), ("Escape (great for Vim)", "caps:escape"), ("Ctrl", "ctrl:nocaps"), ("Backspace", "caps:backspace"),
        ("Nothing (disabled)", "caps:none")]


def gget(schema: str, key: str) -> str:
    return out(["gsettings", "get", schema, key])


def gset(schema: str, key: str, value: str) -> bool:
    return sh(["gsettings", "set", schema, key, value], timeout=5).ok


def writable(schema: str, key: str) -> bool:
    return sh(["gsettings", "writable", schema, key], timeout=3).ok


class TweaksPage(Page):
    ID = "tweaks"
    TITLE = "Tweaks"
    ICON = "preferences-system-symbolic"
    SUBTITLE = "Small changes that make a dev laptop faster and smoother. Each one explains itself and can be undone."

    def build(self) -> None:
        self.header()
        self.count = label("…", "huge-num")
        self.count_sub = label("Checking your settings…", "subtle", wrap=True)
        self.apply_all_btn = button("Apply all recommended", icon="emblem-ok-symbolic", css=["suggested-action", "pill"], on_click=self.apply_all)
        t = vbox(self.count_sub, hbox(self.apply_all_btn), spacing=8)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(self.count, t, spacing=24))
        hero.add_css_class("hero")
        self.body.append(hero)
        self.sys_holder = vbox(spacing=18)
        self.desk_holder = vbox(spacing=18)
        self.body.append(self.sys_holder)
        self.body.append(self.desk_holder)
        self.items: list[tweaks.Tweak] = []

    def load(self) -> None:
        self.loading(self.sys_holder, "Checking system settings…")
        self.bg(tweaks.system_tweaks, self.show_system)
        self.bg(tweaks.desktop_switches, self.show_desktop)

    # ---------------------------------------------------------------- system
    def show_system(self, items: list[tweaks.Tweak]) -> None:
        self.items = items
        clear(self.sys_holder)
        done = sum(t.applied for t in items)
        self.count.set_text(f"{done}/{len(items)}")
        self.count.set_css_classes(["huge-num", "ok-text" if done == len(items) else "accent-text"])
        todo = [t for t in items if not t.applied and t.apply]
        self.count_sub.set_text("recommended tweaks are in place." + ("" if todo else " Your PC is tuned."))
        self.apply_all_btn.set_visible(bool(todo))
        groups: dict[str, list] = {}
        for t in items:
            groups.setdefault(t.group, []).append(t)
        desc = {"Developer": "Limits that dev tools run into.", "Performance": "Memory and disk behaviour.",
                "Speed": "Boot, shutdown and disk space.", "Quiet": "Fewer nags."}
        for g, ts in groups.items():
            rows = []
            for t in ts:
                sub = esc(t.desc) + f"\n<span foreground='#9399b2'>Now: {esc(t.state)}</span>" + (f"\n<span foreground='#fab387'>{esc(t.note)}</span>" if t.note else "")
                row = Adw.ActionRow(title=esc(t.title), subtitle=sub)
                row.set_subtitle_lines(6)
                row.add_prefix(status_icon("ok" if t.applied else "info"))
                box = hbox(spacing=6)
                box.set_valign(Gtk.Align.CENTER)
                if t.applied:
                    box.append(pill("done", "ok"))
                    if t.revert:
                        box.append(button("Undo", css="flat", on_click=lambda tt=t: self.run(f"Undo: {tt.title}", tt.revert, tt.desc, ok_label="Undo")))
                elif t.apply:
                    box.append(button("Apply", css="suggested-action", on_click=lambda tt=t: self.run(tt.title, tt.apply, tt.desc, ok_label="Apply")))
                row.add_suffix(box)
                rows.append(row)
            self.sys_holder.append(group(g, desc.get(g, ""), *rows))

    def apply_all(self) -> None:
        todo = [t for t in self.items if not t.applied and t.apply]
        steps = [s for t in todo for s in t.apply]
        self.run("Apply recommended tweaks", steps, "Applies: " + ", ".join(t.title for t in todo) + ". Each can be undone here later.",
                 ok_label="Apply all")

    # ---------------------------------------------------------------- desktop
    def show_desktop(self, switches) -> None:
        clear(self.desk_holder)
        self.desk_holder.append(self._look_group())
        kb = self._keyboard_group()
        if kb is not None:
            self.desk_holder.append(kb)
        groups: dict[str, list] = {}
        for s, on in switches:
            def change(v: bool, settle, ss=s) -> None:
                ok = tweaks.set_switch(ss, v)
                settle(ok)
            groups.setdefault(s.group, []).append(switch_row(s.title, s.desc, on, change))
        for g, rows in groups.items():
            self.desk_holder.append(group(g, "Takes effect immediately." if g == "Desktop" else "", *rows))

    def _combo(self, title: str, subtitle: str, labels: list[str], selected: int, on_pick) -> Adw.ComboRow:
        row = Adw.ComboRow(title=esc(title), subtitle=esc(subtitle), model=Gtk.StringList.new(labels))
        if selected >= 0:
            row.set_selected(selected)
        row.connect("notify::selected", lambda r, _p: on_pick(r.get_selected()))
        return row

    def _look_group(self) -> Adw.PreferencesGroup:
        rows = []
        iface = "org.gnome.desktop.interface"
        scheme = gget(iface, "color-scheme").strip("'")

        def dark(v: bool, settle) -> None:
            settle(gset(iface, "color-scheme", "prefer-dark" if v else "default"))
        rows.append(switch_row("Dark style", "Apps that support it switch to dark colours.", scheme == "prefer-dark", dark))
        if writable(iface, "accent-color"):
            cur = gget(iface, "accent-color").strip("'")
            rows.append(self._combo("Accent colour", "Buttons, switches and selections.", [a.title() for a in ACCENTS],
                                    ACCENTS.index(cur) if cur in ACCENTS else -1,
                                    lambda i: gset(iface, "accent-color", ACCENTS[i]) and self.toast(f"Accent: {ACCENTS[i]}")))
        try:
            scale = float(gget(iface, "text-scaling-factor") or 1)
        except ValueError:
            scale = 1.0
        vals = [v for _, v in SCALES]
        idx = min(range(len(vals)), key=lambda i: abs(vals[i] - scale))
        rows.append(self._combo("Text size", "Makes all text bigger without changing the display scale.", [n for n, _ in SCALES], idx,
                                lambda i: gset(iface, "text-scaling-factor", str(SCALES[i][1]))))
        if writable(iface, "cursor-size"):
            try:
                cs = int(gget(iface, "cursor-size") or 24)
            except ValueError:
                cs = 24
            sizes = [24, 32, 48, 64]
            rows.append(self._combo("Mouse pointer size", "", ["Normal", "Large", "Larger", "Largest"], sizes.index(cs) if cs in sizes else 0,
                                    lambda i: gset(iface, "cursor-size", str(sizes[i]))))
        return group("Look", "Your Catppuccin theme stays in place; these are GNOME's own options.", *rows)

    def _keyboard_group(self) -> Adw.PreferencesGroup | None:
        schema = "org.gnome.desktop.input-sources"
        if not writable(schema, "xkb-options"):
            return None
        try:
            opts = ast.literal_eval(gget(schema, "xkb-options").replace("@as ", "")) or []
        except (ValueError, SyntaxError):
            opts = []
        cur = next((o for o in opts if o.startswith("caps:") or o == "ctrl:nocaps"), "")
        keys = [v for _, v in CAPS]

        def pick(i: int) -> None:
            new = [o for o in opts if not (o.startswith("caps:") or o == "ctrl:nocaps")]
            if keys[i]:
                new.append(keys[i])
            if gset(schema, "xkb-options", str(new)):
                opts[:] = new
                self.toast(f"Caps Lock now: {CAPS[i][0]}")
        rows = [self._combo("Caps Lock key acts as", "Many developers turn it into Escape or Ctrl.", [n for n, _ in CAPS],
                            keys.index(cur) if cur in keys else 0, pick)]
        kb = "org.gnome.desktop.peripherals.keyboard"
        if writable(kb, "delay"):
            try:
                delay = int(gget(kb, "delay").split()[-1])
            except (ValueError, IndexError):
                delay = 500
            opts_d = [("Short (200 ms)", 200), ("Medium (300 ms)", 300), ("Default (500 ms)", 500)]
            vals = [v for _, v in opts_d]
            rows.append(self._combo("Key repeat delay", "How long to hold a key before it repeats. Shorter feels snappier when editing.",
                                    [n for n, _ in opts_d], min(range(3), key=lambda i: abs(vals[i] - delay)),
                                    lambda i: gset(kb, "delay", f"uint32 {vals[i]}")))
        return group("Keyboard", "", *rows)


PAGE = TweaksPage
