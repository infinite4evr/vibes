"""Tweaks: recommended system tweaks (apply/undo), desktop look and behaviour, the dock, the Files app, GNOME extensions,
keyboard shortcuts (Ctrl+Shift+Esc for Processes), and the computer's name, time zone and clock sync."""

from __future__ import annotations

import datetime as _dt

from gi.repository import Adw, GLib, Graphene, Gtk

from ...core import desktop, extensions, shortcuts, tweaks
from ...core.run import Step
from ..dialogs import ChoiceDialog, ask_text
from ..util import button, clear, esc, hbox, label, launch, pill, spacer, status_icon, vbox
from ..widgets import card
from .. import theme
from .base import Page, action_row, banner, group, switch_row, tabs


def combo_row(title: str, subtitle: str, labels: list[str]) -> Adw.ComboRow:
    """A drop-down row with plain-text title/subtitle (ComboRow's markup default differs between libadwaita versions)."""
    row = Adw.ComboRow(model=Gtk.StringList.new(labels))
    row.set_use_markup(False)
    row.set_title(title)
    row.set_subtitle(subtitle)
    return row


def compact_tabs(page: Page, sw: Adw.ViewSwitcher, n: int, per_tab: int = 150) -> None:
    """Kept for compatibility: base.tabs() now switches every page's tabs to the compact style when the window is narrow."""


ACCENTS = ["blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "slate"]
SCALES = [("100% (normal)", 1.0), ("110%", 1.1), ("125%", 1.25), ("150%", 1.5)]
CAPS = [("Caps Lock (normal)", ""), ("Escape (great for Vim)", "caps:escape"), ("Ctrl", "ctrl:nocaps"), ("Backspace", "caps:backspace"),
        ("Nothing (disabled)", "caps:none")]
IFACE = "org.gnome.desktop.interface"
INPUT = "org.gnome.desktop.input-sources"
KB = "org.gnome.desktop.peripherals.keyboard"

DOCK_GROUPS = [("Position and size", "", ["dock-pos", "dock-size", "dock-hide", "dock-extend"]),
               ("What it shows", "", ["dock-trash", "dock-mounts", "dock-apps-top", "dock-dots", "dock-monitors", "dock-isolate"]),
               ("Clicks and keys", "", ["dock-click", "dock-scroll", "dock-hotkeys"])]
FILES_GROUPS = [("Showing files", "", ["files-hidden", "files-dirs-first", "files-view", "files-tree", "files-dates", "files-count"]),
                ("Clicks and menus", "", ["files-click", "files-perm-delete", "files-link"]),
                ("Speed", "Previews and searching inside network folders or USB drives can make Files slow.", ["files-thumbs", "files-thumb-limit", "files-search"])]


def _unq(v: str) -> str:
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == "'" else v


class ShortcutDialog(Adw.Dialog):
    """Name + command + key combination (recorded by pressing it, or typed like <Super>t)."""

    def __init__(self, on_done, name: str = "", command: str = "", binding: str = "", title: str = "Add a keyboard shortcut"):
        super().__init__()
        self.set_title(title)
        self.set_content_width(560)
        self.set_content_height(470)
        self.on_done_cb = on_done
        self.binding = binding
        self.recording = False
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_end_title_buttons(False)
        hb.set_show_start_title_buttons(False)
        cancel = button("Cancel", on_click=self.close)
        self.ok = button("Save", css="suggested-action", on_click=self._save)
        hb.pack_start(cancel)
        hb.pack_end(self.ok)
        tv.add_top_bar(hb)
        box = vbox(spacing=14)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(18 if m != "top" else 6)
        lst = Gtk.ListBox()
        lst.add_css_class("boxed-list")
        lst.set_selection_mode(Gtk.SelectionMode.NONE)
        self.name_row = Adw.EntryRow(title="Name (just for you)")
        self.name_row.set_text(name)
        self.cmd_row = Adw.EntryRow(title="Command to run")
        self.cmd_row.set_text(command)
        self.keys_row = Adw.ActionRow(title="Keys")
        self.keys_lbl = label("", "kbd")
        self.rec_btn = button("Record", icon="media-record-symbolic", on_click=self._toggle_record)
        self.keys_row.add_suffix(self.keys_lbl)
        self.keys_row.add_suffix(self.rec_btn)
        for w in (self.keys_lbl, self.rec_btn):
            w.set_valign(Gtk.Align.CENTER)
        self.typed = Adw.EntryRow(title=esc("…or type them, like <Super>t or <Control><Alt>Delete"))
        self.typed.set_text(binding)
        self.typed.connect("changed", lambda r: self._set_binding(r.get_text().strip(), from_typed=True))
        for r in (self.name_row, self.cmd_row, self.keys_row, self.typed):
            lst.append(r)
        box.append(lst)
        self.hint = label("", "dim", wrap=True)
        box.append(self.hint)
        box.append(label("Tip: click Record, then press the keys together. Esc cancels, Backspace clears. GNOME runs the command even "
                         "when this app is closed.", "dim", wrap=True))
        self.cmd_row.connect("changed", lambda *_: self._validate())
        self.name_row.connect("changed", lambda *_: self._validate())
        tv.set_content(box)
        self.set_child(tv)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self._set_binding(binding)

    def _toggle_record(self) -> None:
        self.recording = not self.recording
        self.rec_btn.get_child().set_label("Press keys…" if self.recording else "Record") if isinstance(self.rec_btn.get_child(), Adw.ButtonContent) else None
        if self.recording:
            self.rec_btn.add_css_class("destructive-action")
            self.keys_lbl.set_text("press the keys now")
        else:
            self.rec_btn.remove_css_class("destructive-action")
            self._set_binding(self.binding)

    def _key(self, _c, keyval: int, _code: int, state) -> bool:
        if not self.recording:
            return False
        from gi.repository import Gdk
        mods = state & Gtk.accelerator_get_default_mod_mask()
        name = Gdk.keyval_name(keyval) or ""
        if name.startswith(("Shift", "Control", "Alt", "Super", "Meta", "Hyper", "ISO_Level")):
            return True  # wait for the real key
        if not mods and keyval == Gdk.KEY_Escape:
            self._toggle_record()
            return True
        if not mods and keyval == Gdk.KEY_BackSpace:
            self.binding = ""
            self._toggle_record()
            return True
        accel = Gtk.accelerator_name(keyval, mods)
        self.recording = True
        self._toggle_record()
        self._set_binding(accel)
        self.typed.set_text(accel)
        return True

    def _set_binding(self, accel: str, from_typed: bool = False) -> None:
        self.binding = accel
        self.keys_lbl.set_text(shortcuts.pretty(accel) or "not set")
        self._validate()

    def _validate(self) -> bool:
        problems = []
        if not self.name_row.get_text().strip():
            problems.append("Give it a name.")
        warn = shortcuts.command_ok(self.cmd_row.get_text())
        if warn:
            problems.append(warn)
        if not self.binding or not shortcuts.valid_accel(self.binding):
            problems.append("Choose the keys (click Record).")
        else:
            mods, key = shortcuts.split_accel(self.binding)
            if not mods and len(key) == 1:
                problems.append("Add Ctrl, Alt or Super - a single letter would fire while you type.")
        self.hint.set_text(" ".join(problems))
        self.hint.set_css_classes(["warn-text"] if problems else ["dim"])
        ok = not problems or (problems == [warn] and warn and "wasn't found" in warn)
        self.ok.set_sensitive(bool(ok))
        return bool(ok)

    def _save(self) -> None:
        if not self._validate():
            return
        name, cmd = self.name_row.get_text().strip(), self.cmd_row.get_text().strip()
        self.close()
        self.on_done_cb(name, cmd, self.binding)


class TweaksPage(Page):
    ID = "tweaks"
    TITLE = "Tweaks"
    ICON = "preferences-system-symbolic"
    SUBTITLE = "Small changes that make a dev laptop faster and smoother, plus the desktop options GNOME hides. Everything explains itself and can be undone."
    PALETTE = [("extensions", "GNOME extensions: switch on/off, settings, remove"), ("dock", "Dock settings: position, icon size, auto-hide"),
               ("taskmgr", "Make Ctrl+Shift+Esc open Processes (like Windows)"), ("shortcuts", "Add your own keyboard shortcut"),
               ("files", "Files app: show hidden files, folders first"), ("windows", "Window buttons: minimise and maximise"),
               ("clock", "24-hour clock, seconds, battery percentage"), ("hostname", "Rename this computer"), ("timezone", "Change the time zone")]

    def build(self) -> None:
        self.header()
        self.rec = vbox(spacing=18)
        self.desk = vbox(spacing=18)
        self.dock = vbox(spacing=18)
        self.files = vbox(spacing=18)
        self.ext = vbox(spacing=18)
        self.keys = vbox(spacing=18)
        self.sys = vbox(spacing=18)
        sw, self.stack = tabs(("rec", "System", "computer-symbolic", self.rec), ("desk", "Desktop", "video-display-symbolic", self.desk),
                              ("dock", "Dock", "view-app-grid-symbolic", self.dock), ("files", "Files", "folder-symbolic", self.files),
                              ("ext", "Extensions", "application-x-addon-symbolic", self.ext),
                              ("keys", "Shortcuts", "input-keyboard-symbolic", self.keys))
        self.body.append(sw)
        self.body.append(self.stack)
        compact_tabs(self, sw, 6)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self.count = label("…", "huge-num")
        self.count_sub = label("Checking your settings…", "subtle", wrap=True)
        self.apply_all_btn = button("Apply all recommended", icon="emblem-ok-symbolic", css=["suggested-action", "pill"], on_click=self.apply_all)
        t = vbox(self.count_sub, hbox(self.apply_all_btn), spacing=8)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(self.count, t, spacing=24))
        hero.add_css_class("hero")
        self.rec.append(hero)
        self.sys_holder = vbox(spacing=18)
        self.rec.append(self.sys_holder)
        self.rec.append(self.sys)
        self.items: list[tweaks.Tweak] = []
        self.sc_paths: list[str] = []
        self.sc_list: list[shortcuts.Shortcut] = []
        self._pending: str | None = None

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"rec": self.load_rec, "desk": self.load_desk, "dock": self.load_dock, "files": self.load_files, "ext": self.load_ext,
         "keys": self.load_keys}[name]()

    def palette_action(self, key: str) -> None:
        tab = {"extensions": "ext", "dock": "dock", "taskmgr": "keys", "shortcuts": "keys", "files": "files", "windows": "desk",
               "clock": "desk", "hostname": "rec", "timezone": "rec"}.get(key)
        if not tab:
            return
        self._pending = key
        self.stack.set_visible_child_name(tab)
        if key in ("hostname", "timezone"):
            GLib.timeout_add(400, lambda: (self._scroll_to(self.sys), False)[1])
        if tab in self.tab_loaded and key in ("taskmgr", "shortcuts", "hostname", "timezone") and (tab != "rec" or hasattr(self, "tm")):
            self._run_pending()

    def _scroll_to(self, w: Gtk.Widget) -> None:
        ok, pt = w.compute_point(self.body, Graphene.Point()) if hasattr(w, "compute_point") else (False, None)
        if ok:
            self.get_first_child().get_vadjustment().set_value(max(0, pt.y - 20))

    def _run_pending(self) -> None:
        key, self._pending = self._pending, None
        if key == "taskmgr":
            self.add_preset(shortcuts.presets()[0])
        elif key == "shortcuts":
            self.new_shortcut()
        elif key == "hostname":
            self.rename()
        elif key == "timezone":
            self.pick_timezone()

    # ---------------------------------------------------------------- helpers
    def _quiet(self, title: str, steps: list[Step], done=None, ok_toast: str = "") -> None:
        """Run small per-user changes (gsettings) straight away, without a dialog; they still go into Activity history."""
        def fin(res) -> None:
            ok, lines = res
            try:
                from ..activity import record
                record(title, [s.display() for s in steps], ok, "" if ok else (lines[-1] if lines else ""), lines)
            except Exception:  # noqa: BLE001 - history is best effort
                pass
            if not ok:
                self.toast(f"Couldn't change it: {lines[-1] if lines else 'unknown error'}", 5)
            elif ok_toast:
                self.toast(ok_toast)
            if done:
                done(ok)
        self.bg(lambda: desktop.run_quiet(steps), fin)

    def _combo(self, title: str, subtitle: str, labels: list[str], selected: int, on_pick) -> Adw.ComboRow:
        labels = list(labels)
        if selected < 0:
            labels.append("Custom (your own setting)")
            selected = len(labels) - 1
        row = combo_row(title, subtitle, labels)
        row.set_selected(selected)
        row._last = selected
        n = len(labels) - (1 if labels[-1].startswith("Custom (") else 0)

        def picked(r, _p) -> None:
            i = r.get_selected()
            if i >= n or i == r._last:
                return
            r._last = i
            on_pick(i)
        row.connect("notify::selected", picked)
        return row

    def _opt_row(self, o: desktop.Opt, cur, values: dict) -> Gtk.Widget:
        if o.kind == "switch":
            def change(v: bool, settle, oo=o) -> None:
                self._quiet(f"{oo.title}: {'on' if v else 'off'}", desktop.set_steps(oo, v, values), done=settle)
            return switch_row(o.title, o.desc, bool(cur), change)
        if o.kind == "choice":
            return self._combo(o.title, o.desc, [lb for lb, _ in o.options], cur if isinstance(cur, int) else -1,
                               lambda i, oo=o: self._quiet(f"{oo.title}: {oo.options[i][0]}", desktop.set_steps(oo, i, values)))
        row = Adw.SpinRow.new_with_range(o.lo, o.hi, o.step)
        row.set_title(esc(o.title))
        row.set_subtitle(esc(o.desc + (f" ({o.unit})" if o.unit else "")))
        row.set_value(cur if isinstance(cur, (int, float)) else o.lo)
        row._timer = None

        def later(r=row, oo=o) -> bool:
            r._timer = None
            v = r.get_value()
            self._quiet(f"{oo.title}: {v:g}", desktop.set_steps(oo, v, values))
            return False

        def changed(r, _p) -> None:
            if r._timer:
                GLib.source_remove(r._timer)
            r._timer = GLib.timeout_add(700, later)
        row.connect("notify::value", changed)
        return row

    def _opt_groups(self, box: Gtk.Box, items: list, values: dict, layout: list) -> None:
        by = {o.id: (o, cur) for o, cur in items}
        for title, desc, ids in layout:
            rows = [self._opt_row(*by[i], values) for i in ids if i in by]
            if rows:
                box.append(group(title, desc, *rows))

    @staticmethod
    def _read_opts(opts: list[desktop.Opt]):
        values = desktop.read_values([s for o in opts for s, _ in o.places()])
        return [(o, desktop.current(o, values)) for o in opts if desktop.present(o, values)], values

    # ---------------------------------------------------------------- recommended (system)
    def load_rec(self) -> None:
        self.loading(self.sys_holder, "Checking system settings…")
        self.bg(tweaks.system_tweaks, self.show_system)
        self.load_sys()

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
                sub = esc(t.desc) + "\n" + theme.span("overlay2", f"Now: {esc(t.state)}") + ("\n" + theme.span("peach", esc(t.note)) if t.note else "")
                row = Adw.ActionRow(title=esc(t.title), subtitle=sub)
                row.set_subtitle_lines(6)
                row.add_prefix(status_icon("ok" if t.applied else "info"))
                box = hbox(spacing=6)
                box.set_valign(Gtk.Align.CENTER)
                if t.applied:
                    box.append(pill("done", "ok"))
                    if t.revert:
                        box.append(button("Undo", css="flat", on_click=lambda tt=t: self.run(f"Undo: {tt.title}", tt.revert, tt.desc, ok_label="Undo",
                                                                                          reload=False, done=lambda ok: ok and self.load_rec())))
                elif t.apply:
                    box.append(button("Apply", css="suggested-action", on_click=lambda tt=t: self.run(tt.title, tt.apply, tt.desc, ok_label="Apply",
                                                                                                    reload=False, done=lambda ok: ok and self.load_rec())))
                row.add_suffix(box)
                rows.append(row)
            self.sys_holder.append(group(g, desc.get(g, ""), *rows))

    def apply_all(self) -> None:
        todo = [t for t in self.items if not t.applied and t.apply]
        steps = [s for t in todo for s in t.apply]
        self.run("Apply recommended tweaks", steps, "Applies: " + ", ".join(t.title for t in todo) + ". Each can be undone here later.",
                 ok_label="Apply all", reload=False, done=lambda ok: self.load_rec())

    # ---------------------------------------------------------------- desktop
    def load_desk(self) -> None:
        self.loading(self.desk, "Reading desktop settings…")
        self.bg(lambda: (tweaks.desktop_switches(), self._read_opts(desktop.WINDOW_OPTS), desktop.read_values([IFACE, INPUT, KB])),
                self.show_desktop)

    def show_desktop(self, res) -> None:
        switches, (win_items, win_values), vals = res
        clear(self.desk)
        if not switches and not win_items and not vals:
            self.desk.append(banner("GNOME's settings tool (gsettings) isn't available, so desktop options can't be shown here.", "warn"))
            return
        self.desk.append(self._look_group(vals))
        kb = self._keyboard_group(vals)
        if kb is not None:
            self.desk.append(kb)
        groups: dict[str, list] = {}
        for s, on in switches:
            def change(v: bool, settle, ss=s) -> None:
                self._quiet(f"{ss.title}: {'on' if v else 'off'}", tweaks.switch_steps(ss, v), done=settle)
            groups.setdefault(s.group, []).append(switch_row(s.title, s.desc, on, change))
        win_rows = [self._opt_row(o, cur, win_values) for o, cur in win_items]
        groups["Windows"] = win_rows + groups.get("Windows", [])
        desc = {"Desktop": "Takes effect immediately.", "Top bar & clock": "The clock and icons at the top of the screen.",
                "Windows": "Title bars and how new windows open."}
        order = ["Desktop", "Top bar & clock", "Windows", "Touchpad", "Workspaces", "Power"]
        for g in sorted(groups, key=lambda x: order.index(x) if x in order else 99):
            if groups[g]:
                self.desk.append(group(g, desc.get(g, ""), *groups[g]))

    def _look_group(self, vals: dict) -> Adw.PreferencesGroup:
        rows = []
        scheme = _unq(vals.get((IFACE, "color-scheme"), "'default'"))

        def dark(v: bool, settle) -> None:
            self._quiet("Dark style: " + ("on" if v else "off"), [Step("Colour scheme", ["gsettings", "set", IFACE, "color-scheme", "prefer-dark" if v else "default"])],
                        done=settle)
        rows.append(switch_row("Dark style", "Apps that support it switch to dark colours.", scheme == "prefer-dark", dark))
        if (IFACE, "accent-color") in vals:
            cur = _unq(vals[(IFACE, "accent-color")])
            rows.append(self._combo("Accent colour", "Buttons, switches and selections.", [a.title() for a in ACCENTS],
                                    ACCENTS.index(cur) if cur in ACCENTS else -1,
                                    lambda i: self._quiet(f"Accent colour: {ACCENTS[i]}", [Step("Accent colour", ["gsettings", "set", IFACE, "accent-color", ACCENTS[i]])],
                                                          ok_toast=f"Accent: {ACCENTS[i]}")))
        try:
            scale = float(desktop.norm(vals.get((IFACE, "text-scaling-factor"), "1")))
        except ValueError:
            scale = 1.0
        svals = [v for _, v in SCALES]
        idx = min(range(len(svals)), key=lambda i: abs(svals[i] - scale))
        rows.append(self._combo("Text size", "Makes all text bigger without changing the display scale.", [n for n, _ in SCALES], idx,
                                lambda i: self._quiet(f"Text size: {SCALES[i][0]}", [Step("Text size", ["gsettings", "set", IFACE, "text-scaling-factor", str(SCALES[i][1])])])))
        if (IFACE, "cursor-size") in vals:
            try:
                cs = int(float(desktop.norm(vals[(IFACE, "cursor-size")])))
            except ValueError:
                cs = 24
            sizes = [24, 32, 48, 64]
            rows.append(self._combo("Mouse pointer size", "", ["Normal", "Large", "Larger", "Largest"], sizes.index(cs) if cs in sizes else -1,
                                    lambda i: self._quiet("Mouse pointer size", [Step("Pointer size", ["gsettings", "set", IFACE, "cursor-size", str(sizes[i])])])))
        return group("Look", "Your Catppuccin theme stays in place; these are GNOME's own options.", *rows)

    def _keyboard_group(self, vals: dict) -> Adw.PreferencesGroup | None:
        if (INPUT, "xkb-options") not in vals:
            return None
        opts = extensions.parse_strv(vals[(INPUT, "xkb-options")])
        cur = next((o for o in opts if o.startswith("caps:") or o == "ctrl:nocaps"), "")
        keys = [v for _, v in CAPS]

        def pick(i: int) -> None:
            new = [o for o in opts if not (o.startswith("caps:") or o == "ctrl:nocaps")]
            if keys[i]:
                new.append(keys[i])

            def done(ok: bool) -> None:
                if ok:
                    opts[:] = new
            self._quiet(f"Caps Lock: {CAPS[i][0]}", [Step("Caps Lock key", ["gsettings", "set", INPUT, "xkb-options", shortcuts.strv(new)])], done=done,
                        ok_toast=f"Caps Lock now: {CAPS[i][0]}")
        rows = [self._combo("Caps Lock key acts as", "Many developers turn it into Escape or Ctrl.", [n for n, _ in CAPS],
                            keys.index(cur) if cur in keys else -1, pick)]
        if (KB, "delay") in vals:
            try:
                delay = int(float(desktop.norm(vals[(KB, "delay")])))
            except ValueError:
                delay = 500
            opts_d = [("Short (200 ms)", 200), ("Medium (300 ms)", 300), ("Default (500 ms)", 500)]
            dv = [v for _, v in opts_d]
            rows.append(self._combo("Key repeat delay", "How long to hold a key before it repeats. Shorter feels snappier when editing.",
                                    [n for n, _ in opts_d], min(range(3), key=lambda i: abs(dv[i] - delay)),
                                    lambda i: self._quiet("Key repeat delay", [Step("Key repeat delay", ["gsettings", "set", KB, "delay", f"uint32 {dv[i]}"])])))
        return group("Keyboard", "", *rows)

    # ---------------------------------------------------------------- dock
    def load_dock(self) -> None:
        self.loading(self.dock, "Reading dock settings…")
        self.bg(lambda: self._read_opts(desktop.DOCK_OPTS), self.show_dock)

    def show_dock(self, res) -> None:
        items, values = res
        clear(self.dock)
        if not items:
            self.dock.append(banner("Ubuntu Dock's settings weren't found. They only exist in Ubuntu's GNOME desktop (with the Ubuntu Dock "
                                    "extension on the Extensions tab).", "warn"))
            return
        self.dock.append(label("Ubuntu Dock is the bar with your apps. Changes show up instantly.", "dim", wrap=True))
        self._opt_groups(self.dock, items, values, DOCK_GROUPS)
        self.dock.append(hbox(spacer(), button("Reset the dock to Ubuntu's defaults", css="flat", on_click=lambda: self.run(
            "Reset the dock", desktop.reset_steps(desktop.DOCK_OPTS), "Every dock option on this tab goes back to how Ubuntu ships it.",
            ok_label="Reset", reload=False, done=lambda ok: ok and self.load_dock()))))

    # ---------------------------------------------------------------- files
    def load_files(self) -> None:
        self.loading(self.files, "Reading Files settings…")
        self.bg(lambda: self._read_opts(desktop.FILES_OPTS), self.show_files)

    def show_files(self, res) -> None:
        items, values = res
        clear(self.files)
        if not items:
            self.files.append(banner("The Files app's settings weren't found (is Files / Nautilus installed?).", "warn"))
            return
        intro = "Options for the Files app (and the Open / Save windows of other apps). Changes show up instantly."
        if not any(s == desktop.NAUTILUS for s, _ in values):
            intro += " More options appear when the Files app (Nautilus) is installed."
        self.files.append(label(intro, "dim", wrap=True))
        self._opt_groups(self.files, items, values, FILES_GROUPS)

    # ---------------------------------------------------------------- extensions
    def load_ext(self) -> None:
        self.loading(self.ext, "Asking GNOME Shell for your extensions…")
        self.bg(extensions.extensions, self.show_ext)

    def show_ext(self, res: dict) -> None:
        clear(self.ext)
        mgr = res["manager"]
        more = button("Get more extensions", icon="list-add-symbolic", css="suggested-action",
                      on_click=lambda: launch(mgr) if mgr else launch(["xdg-open", extensions.WEBSITE]))
        more.set_tooltip_text("Opens Extension Manager" if mgr else "Opens extensions.gnome.org in your browser")
        self.ext.append(hbox(label("Extensions add features to the desktop: a clipboard history, blur, a keep-awake button… "
                                   "Too many (or broken ones) can make the desktop slow or crash.", "dim", wrap=True, hexpand=True),
                             more, button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_ext), spacing=10))
        if res["reason"]:
            self.ext.append(banner(res["reason"], "warn" if not res["items"] else "info"))
        if not res["items"]:
            return

        def master(v: bool, settle) -> None:
            self._quiet("Your extensions: " + ("on" if v else "paused"), extensions.global_steps(v), done=lambda ok: (settle(ok), ok and self.load_ext()))
        self.ext.append(group("", "", switch_row("Use the extensions you installed",
                                                 "The master switch. If the desktop acts up, switch this off: if the problem goes away, one of your "
                                                 "extensions is the cause. Ubuntu's built-in ones keep working either way.", res["user_extensions_on"], master)))
        sections = [("Part of Ubuntu", "Switched on by Ubuntu itself. You can switch them off, not remove them.", [e for e in res["items"] if e.builtin]),
                    ("Installed by you", "Stored in your home folder.", [e for e in res["items"] if e.user]),
                    ("Installed for everyone", "Came with an Ubuntu package. Remove the package on the Apps page to get rid of one.",
                     [e for e in res["items"] if not e.user and not e.builtin])]
        for title, desc, items in sections:
            if items:
                self.ext.append(group(title, desc, *[self._ext_row(e, res["user_extensions_on"]) for e in items]))

    def _ext_row(self, e: extensions.Extension, users_on: bool) -> Adw.ActionRow:
        sub = esc(e.friendly or "No description.")
        if e.version:
            sub += "  " + theme.span("overlay2", f"· version {esc(e.version)}")
        if e.problem:
            sub += "\n" + theme.span("peach", esc(e.problem))
        elif e.user and not users_on:
            sub += "\n" + theme.span("peach", "Paused by the master switch above.")
        row = Adw.ActionRow(title=esc(e.name), subtitle=sub)
        row.set_subtitle_lines(4)
        row.set_tooltip_text(e.uuid)
        if e.state_kind in ("bad", "warn", "info"):
            p = pill(e.state_text, e.state_kind)
            row.add_suffix(p)
        if e.has_prefs:
            row.add_suffix(button(icon="emblem-system-symbolic", css="flat", tooltip=f"{e.name} settings",
                                  on_click=lambda: launch(extensions.prefs_cmd(e))))
        if e.user:
            row.add_suffix(button(icon="user-trash-symbolic", css="flat", tooltip=f"Remove {e.name}", on_click=lambda: self.run(
                f"Remove {e.name}", extensions.remove_steps(e), "Deletes the extension from your home folder. You can install it again later "
                "from Extension Manager.", danger=True, ok_label="Remove", reload=False, done=lambda ok: ok and self.load_ext())))
        sw = Gtk.Switch(active=e.enabled)
        sw.set_valign(Gtk.Align.CENTER)
        sw.set_tooltip_text("On / off")
        sw._guard = False

        def toggled(s, _p) -> None:
            if s._guard:
                return
            on = s.get_active()

            def done(ok: bool) -> None:
                if not ok:
                    s._guard = True
                    s.set_active(not on)
                    s._guard = False
            self._quiet(f"{e.name}: {'on' if on else 'off'}", extensions.toggle_steps(e, on), done=done,
                        ok_toast=f"{e.name} switched {'on' if on else 'off'}")
        sw.connect("notify::active", toggled)
        row.add_suffix(sw)
        row.set_activatable_widget(sw)
        return row

    # ---------------------------------------------------------------- shortcuts
    def load_keys(self) -> None:
        self.loading(self.keys, "Reading your keyboard shortcuts…")
        self.bg(lambda: (shortcuts.available(), shortcuts.custom_paths(), shortcuts.custom_shortcuts(), shortcuts.presets()), self.show_keys)

    def show_keys(self, res) -> None:
        ok, paths, items, presets = res
        clear(self.keys)
        if not ok:
            self.keys.append(banner("GNOME's keyboard-shortcut settings weren't found, so custom shortcuts can't be managed here.", "warn"))
            return
        self.sc_paths, self.sc_list = paths, items
        by_id = {s.id: s for s in items}
        rows = []
        for p in presets:
            have = by_id.get(p["id"])
            keys = label(shortcuts.pretty(have.binding if have else p["binding"]), "kbd")
            if have:
                btns = [pill("on", "ok"), button("Remove", css="flat", on_click=lambda s=have: self.remove_shortcut(s))]
            else:
                btns = [button("Add", css="suggested-action", on_click=lambda pp=p: self.add_preset(pp))]
            rows.append(action_row(p["name"], p["why"], keys, *btns))
        self.keys.append(group("Ready-made shortcuts", "One click to add. They work everywhere, even when this app is closed.", *rows))
        mine = []
        for s in items:
            btns = [label(s.keys, "kbd")]
            if s.ours:
                btns += [button(icon="document-edit-symbolic", css="flat", tooltip="Change", on_click=lambda ss=s: self.edit_shortcut(ss)),
                         button(icon="user-trash-symbolic", css="flat", tooltip="Remove", on_click=lambda ss=s: self.remove_shortcut(ss))]
            else:
                btns.append(button(icon="emblem-system-symbolic", css="flat", tooltip="Change in GNOME Settings",
                                   on_click=lambda: launch(["gnome-control-center", "keyboard"])))
            mine.append(action_row(s.name or "(no name)", s.command, *btns))
        if not mine:
            mine = [action_row("No custom shortcuts yet", "Add one with the button above, or use a ready-made one.")]
        self.keys.append(group("Your custom shortcuts", "Made here or in GNOME Settings → Keyboard. Ones you made in GNOME Settings are only "
                                                        "changed there, never here.", *mine,
                               suffix=button("Add a shortcut…", icon="list-add-symbolic", css="flat", on_click=self.new_shortcut)))
        if self._pending in ("taskmgr", "shortcuts"):
            self._run_pending()

    def add_preset(self, p: dict) -> None:
        self._add_shortcut(p["id"], p["name"], p["command"], p["binding"])

    def new_shortcut(self) -> None:
        ShortcutDialog(lambda n, c, b: self._add_shortcut(shortcuts.new_id(self.sc_paths), n, c, b)).present(self.win)

    def edit_shortcut(self, s: shortcuts.Shortcut) -> None:
        ShortcutDialog(lambda n, c, b: self._add_shortcut(s.id, n, c, b, skip=s.path), s.name, s.command, s.binding,
                       title="Change shortcut").present(self.win)

    def _add_shortcut(self, sid: str, name: str, command: str, binding: str, skip: str = "") -> None:
        def work():
            return shortcuts.custom_paths(), shortcuts.find_conflicts(binding, shortcuts.builtin_settings(), shortcuts.custom_shortcuts(),
                                                                      skip or f"{shortcuts.BASE}{sid}/")

        def go(res) -> None:
            paths, clashes = res
            explain = f"Pressing {shortcuts.pretty(binding)} will run:\n{command}"
            if clashes:
                explain += "\n\nHeads-up: these keys are already used by " + ", ".join(clashes[:3]) + ". Your shortcut may win or lose depending on the app."
            self.run(f"Add shortcut: {name}", shortcuts.add_steps(paths, sid, name, command, binding), explain, ok_label="Add",
                     reload=False, done=lambda ok: ok and self.load_keys())
        self.bg(work, go)

    def remove_shortcut(self, s: shortcuts.Shortcut) -> None:
        if not s.ours:
            self.toast("That one was made in GNOME Settings - change it there.")
            return
        self.bg(shortcuts.custom_paths, lambda paths: self.run(
            f"Remove shortcut: {s.name}", shortcuts.remove_steps(paths, s.path), f"{s.keys} will stop running “{s.command}”. Your other shortcuts stay.",
            ok_label="Remove", reload=False, done=lambda ok: ok and self.load_keys()))

    # ---------------------------------------------------------------- name & time
    def load_sys(self) -> None:
        self.loading(self.sys, "Reading the computer name and clock…")
        self.bg(lambda: (desktop.hostname_info(), desktop.time_info()), self.show_sys)

    def show_sys(self, res) -> None:
        host, tm = res
        self.host, self.tm = host, tm
        clear(self.sys)
        name = host["static"]
        sub = f"{name}" + (f"  (shown as “{host['pretty']}”)" if host["pretty"] and host["pretty"] != name else "")
        self.sys.append(group("Computer name", "How this PC shows up on your network, in Bluetooth and in the terminal prompt.",
                              action_row("Computer name", sub, button("Rename…", on_click=self.rename))))
        now = _dt.datetime.now().astimezone()
        tz_row = action_row("Time zone", f"{tm['timezone']} · now {now.strftime('%H:%M')} (UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})",
                            button("Change…", on_click=self.pick_timezone))
        rows = [tz_row]
        if tm["ntp"] is None:
            rows.append(action_row("Set the time automatically", "Can't read this here: the time service (timedatectl) isn't answering."))
        else:
            if tm["chrony"]:
                c = tm["chrony"]
                sync = (f"In sync with {c['source']}" + (f" (off by {c['offset']})" if c["offset"] else "") + " · Chrony") if c["synced"] \
                    else "Not in sync yet - Chrony is still looking for a time server."
            elif tm["synced"]:
                sync = f"In sync ({tm['service'] or 'network time'})."
            else:
                sync = "Not in sync yet." if tm["ntp"] else "Off: the clock can drift a few seconds a week."

            def ntp(v: bool, settle) -> None:
                self.run(("Turn on" if v else "Turn off") + " automatic time", desktop.ntp_steps(v),
                         "Keeps the clock right using internet time servers." if v else "The clock will slowly drift until you set it by hand.",
                         ok_label="Turn on" if v else "Turn off", reload=False, done=lambda ok: (settle(ok), ok and self.load_sys()))
            rows.append(switch_row("Set the time automatically", f"Uses internet time servers. {sync}", bool(tm["ntp"]), ntp))
        if tm["auto_tz"] is not None:
            note = "Changes the time zone when you travel, based on your location."
            if tm["location_on"] is False:
                note += " Needs Location Services, which are off (Privacy page)."

            def auto_tz(v: bool, settle) -> None:
                self._quiet("Automatic time zone: " + ("on" if v else "off"), desktop.auto_tz_steps(v), done=settle)
            rows.append(switch_row("Set the time zone automatically", note, tm["auto_tz"], auto_tz))
        self.sys.append(group("Date and time", "", *rows))
        if self._pending in ("hostname", "timezone"):
            self._run_pending()

    def rename(self) -> None:
        cur = getattr(self, "host", {}).get("static", "")

        def got(text: str | None) -> None:
            if not text or text == cur:
                return
            problem = desktop.hostname_problem(text)
            if problem:
                sug = desktop.suggest_hostname(text)
                if sug and not desktop.hostname_problem(sug):
                    self.toast(f"{problem} Try “{sug}”.", 6)
                else:
                    self.toast(problem, 5)
                return
            self.run(f"Rename this computer to {text}", desktop.hostname_steps(text),
                     f"Other devices on your network and in Bluetooth will see “{text}”. Terminals you already have open keep showing "
                     f"“{cur}” until you open a new one. Also updates /etc/hosts so admin commands don't complain.",
                     ok_label="Rename", reload=False, done=lambda ok: ok and self.load_sys())
        ask_text(self.win, "Rename this computer", "Letters, numbers and dashes only, like ashu-pc.", "ashu-pc", got, ok_label="Next", initial=cur)

    def pick_timezone(self) -> None:
        cur = getattr(self, "tm", {}).get("timezone", "")

        def rows():
            from zoneinfo import ZoneInfo
            now = _dt.datetime.now(_dt.timezone.utc)
            res = []
            for z in desktop.timezones():
                try:
                    t = now.astimezone(ZoneInfo(z))
                    off = t.strftime("%z")
                    sub = f"now {t.strftime('%H:%M')} · UTC{off[:3]}:{off[3:]}"
                except Exception:  # noqa: BLE001 - unknown zone name
                    sub = ""
                res.append((z, z.replace("_", " "), sub + ("  · current" if z == cur else "")))
            return res

        def picked(z: str | None) -> None:
            if z and z != cur:
                self.run(f"Set the time zone to {z}", desktop.timezone_steps(z), "The clock in the top bar switches right away.",
                         ok_label="Set", reload=False, done=lambda ok: ok and self.load_sys())
        self.bg(rows, lambda r: ChoiceDialog("Choose your time zone", r, picked, explain=f"Now: {cur}. Type a city or region, like Kolkata or Berlin.").present(self.win))


PAGE = TweaksPage
