"""Privacy: what's using your camera/mic right now, GNOME privacy switches, what Ubuntu and your developer tools send home,
file search indexing, and clearing history."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from ...core import devtelemetry, indexing, junk, privacy
from ...core.fmt import human
from ...core.run import Step, has, py_step, sh
from ..util import button, clear, esc, flow, hbox, label, launch, pill, vbox
from ..widgets import card
from .base import Page, action_row, group, switch_row, tabs


def _truncate(path: str):
    def run() -> str:
        with open(path, "w"):
            pass
        return f"cleared {path}"
    return run


class PrivacyPage(Page):
    ID = "privacy"
    TITLE = "Privacy"
    ICON = "security-medium-symbolic"
    SUBTITLE = "Who's using your camera and microphone, what Ubuntu and your developer tools send home, and what your PC remembers about you."
    AUTO_REFRESH = 3.0
    PALETTE = [("telemetry", "Turn off developer tool telemetry (Next.js, .NET, VS Code…)"), ("indexing", "File search indexing on or off"),
               ("reset-index", "Delete the file search index"), ("history", "Clear command history and other traces")]

    def build(self) -> None:
        self.header()
        self.live = {}
        tiles = []
        for key, icon, title in (("camera", "camera-web-symbolic", "Camera"), ("mic", "audio-input-microphone-symbolic", "Microphone"),
                                 ("screen", "video-display-symbolic", "Screen sharing"), ("location", "find-location-symbolic", "Location")):
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(30)
            state = label("…", "mid-num")
            who = label("", "dim", wrap=True)
            c = card(hbox(img, vbox(label(title.upper(), "tile-title"), state, spacing=0), spacing=14), who)
            c.set_hexpand(True)
            self.live[key] = (state, who, img)
            tiles.append(c)
        self.body.append(flow(*tiles, spacing=12, min_per_line=2, homogeneous=True))

        self.settings_holder = vbox(spacing=18)
        self.tele_box = vbox(spacing=18)
        self.search_box = vbox(spacing=18)
        self.traces_box = vbox(spacing=18)
        self.ubuntu_holder = vbox(spacing=18)
        self.dev_holder = vbox(spacing=18)
        self.tele_box.append(self.dev_holder)
        self.tele_box.append(self.ubuntu_holder)
        sw, self.stack = tabs(("settings", "Settings", "emblem-system-symbolic", self.settings_holder),
                              ("telemetry", "Tracking", "network-transmit-symbolic", self.tele_box),
                              ("search", "File search", "system-search-symbolic", self.search_box),
                              ("traces", "History", "document-open-recent-symbolic", self.traces_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab_shown)
        self.dev_status: dict = {}
        self.index_status: dict = {}

    def load(self) -> None:
        self.tick()
        self.bg(lambda: (privacy.settings(), privacy.telemetry(), privacy.shell_histories(), junk.recent_files(), junk.clipboard_history(),
                         junk.thumbnails()), self.show)
        self.load_dev()
        self.load_index()

    def _tab_shown(self, *_a) -> None:
        """Tabs are filled while hidden and GTK 4.14 then keeps a stale size for boxes whose text wraps (content overlaps).
        Measure the shown tab again once it's really on screen."""
        def walk(w, depth: int) -> None:
            c = w.get_first_child()
            while c is not None:
                if isinstance(c, Gtk.Box):
                    c.queue_resize()
                    if depth < 2:
                        walk(c, depth + 1)
                c = c.get_next_sibling()

        def later() -> bool:
            child = self.stack.get_visible_child()
            if child is not None:
                child.queue_resize()
                walk(child, 0)
            return False
        GLib.timeout_add(30, later)

    def palette_action(self, key: str) -> None:
        if key == "telemetry":
            self.stack.set_visible_child_name("telemetry")
            if self.dev_status and not self.dev_status.get("configured"):
                self.dev_toggle(True, lambda _ok: None)
        elif key == "indexing":
            self.stack.set_visible_child_name("search")
        elif key == "reset-index":
            self.stack.set_visible_child_name("search")
            self.reset_index()
        elif key == "history":
            self.stack.set_visible_child_name("traces")

    def tick(self) -> bool:
        self.bg(lambda: (privacy.camera_users(), privacy.microphone_users(), privacy.screen_sharing(),
                         sh(["gsettings", "get", "org.gnome.system.location", "enabled"], timeout=3).out.strip() == "true"), self.show_live)
        return True

    def show_live(self, res) -> None:
        cams, mics, screen, loc = res
        for key, users, on_text in (("camera", cams, "IN USE"), ("mic", mics, "IN USE")):
            state, who, img = self.live[key]
            if users:
                state.set_text(on_text)
                state.set_css_classes(["mid-num", "bad-text"])
                who.set_text("by " + ", ".join(sorted({u["name"] for u in users})))
            else:
                state.set_text("Not in use")
                state.set_css_classes(["mid-num", "ok-text"])
                who.set_text("No app is using it right now.")
        state, who, _ = self.live["screen"]
        state.set_text("ACTIVE" if screen else "Off")
        state.set_css_classes(["mid-num", "warn-text" if screen else "ok-text"])
        who.set_text("An app may be recording or sharing your screen." if screen else "Nothing is sharing your screen.")
        state, who, _ = self.live["location"]
        state.set_text("On" if loc else "Off")
        state.set_css_classes(["mid-num", "subtle" if loc else "ok-text"])
        who.set_text("Apps may ask for your approximate location." if loc else "Apps can't get your location.")

    # ---------------------------------------------------------------- settings, Ubuntu reports, traces
    def show(self, res) -> None:
        settings, tele, hist, recent, clip, thumbs = res
        clear(self.settings_holder)
        groups: dict[str, list] = {"Devices": [], "Screen lock": [], "History": [], "Housekeeping": [], "Reports": []}
        where = {"camera": "Devices", "microphone": "Devices", "location": "Devices", "lock-enabled": "Screen lock", "idle-delay": "Screen lock",
                 "notif-lock": "Screen lock", "remember-recent": "History", "recent-age": "History", "remember-app-usage": "History",
                 "remove-old-trash": "Housekeeping", "remove-old-temp": "Housekeeping", "old-files-age": "Housekeeping",
                 "report-problems": "Reports", "usage-stats": "Reports"}
        for s in settings:
            groups[where.get(s.id, "History")].append(self._setting_row(s))
        titles = {"Devices": ("Camera, microphone and location", "Block them for every app at once. Apps can't turn these back on."),
                  "Screen lock": ("Screen lock", "Protects your PC when you step away."),
                  "History": ("What your PC remembers", "Recent files and app usage are only stored on this PC."),
                  "Housekeeping": ("Automatic clean-up", "Let GNOME empty old Trash and temp files for you."),
                  "Reports": ("Reports to GNOME", "")}
        for key, rows in groups.items():
            if rows:
                t, d = titles[key]
                self.settings_holder.append(group(t, d, *rows))
        if not settings:
            self.settings_holder.append(group("Settings", "", action_row("GNOME's privacy settings aren't available here",
                                                                         "They appear when you run the app in a GNOME desktop session.")))

        clear(self.ubuntu_holder)
        rows = []
        for t in tele:
            def change(on: bool, settle, tt=t) -> None:
                steps = tt.on_steps if on else tt.off_steps
                root = any(s.root for s in steps)
                self.run(("Turn on " if on else "Turn off ") + tt.title, steps, tt.desc, reload=False, done=settle, ask=root)
            rows.append(switch_row(t.title, t.desc, t.active, change))
        if rows:
            off_all = [s for t in tele if t.active for s in t.off_steps]
            self.ubuntu_holder.append(group("What Ubuntu sends home", "Reports and ads. Turning them off doesn't affect updates.", *rows,
                                            suffix=button("Turn all off", css="flat", on_click=lambda: self.run(
                                                "Turn off reporting", off_all, "Stops crash/usage reports and Pro ads.", ok_label="Turn off"))
                                            if off_all else None))
        else:
            self.ubuntu_holder.append(group("What Ubuntu sends home", "", action_row("Nothing to turn off", "No Ubuntu reporting tools are installed.")))

        # history and traces
        clear(self.traces_box)
        trace_rows = []
        if recent.size:
            trace_rows.append(action_row("Recent files list", recent.desc, button("Clear", css="flat", on_click=lambda: self.run(
                "Clear recent files", recent.steps, ok_label="Clear", ask=False))))
        if clip.size:
            trace_rows.append(action_row("Clipboard history", f"{clip.desc} ({human(clip.size)})", button("Clear", css="flat", on_click=lambda: self.run(
                "Clear clipboard history", clip.steps, ok_label="Clear"))))
        if thumbs.size:
            trace_rows.append(action_row("Image thumbnails", f"Small previews of every picture and video you've opened ({human(thumbs.size or 0)}). "
                                         "They can reveal files you've since deleted.",
                                         button("Clear", css="flat", on_click=lambda: self.run("Clear thumbnails", thumbs.steps_for(), ok_label="Clear"))))
        for h in hist:
            trace_rows.append(action_row(h["name"], f"{h['lines']} lines · {human(h['size'])}. Command history can contain pasted passwords or tokens.",
                                         button("View", css="flat", on_click=lambda p=h["path"]: self.text(p, open(p, errors="replace").read()[-200_000:])),
                                         button("Clear", css="flat", on_click=lambda p=h["path"], n=h["name"]: self.run(
                                             f"Clear {n}", [py_step(f"Clear {n}", _truncate(p), f": > {p}")],
                                             "Open terminals keep their history in memory and may write it back when closed.", ok_label="Clear"))))
        keys_row = action_row("Passwords and API keys in your history", "Removes only the lines with keys in them, instead of the whole history.",
                              button("Check", css="flat", on_click=self.open_secrets), prefix=Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        self.traces_box.append(group("Traces you can clear", "", keys_row, *trace_rows))

        perm = [action_row("App permissions", "Which apps may use the camera, files, notifications and more.",
                           button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "applications"])))]
        if has("flatpak"):
            if sh(["flatpak", "info", "com.github.tchx84.Flatseal"], timeout=5).ok:
                perm.append(action_row("Flatseal", "Fine-grained permissions for Flatpak apps.", button("Open", css="flat", on_click=lambda: launch(["flatpak", "run", "com.github.tchx84.Flatseal"]))))
            else:
                perm.append(action_row("Flatseal", "Review and restrict what each Flatpak app can access.", button("Install", css="flat", on_click=lambda: self.run(
                    "Install Flatseal", [Step("Install Flatseal", ["flatpak", "install", "-y", "--user", "flathub", "com.github.tchx84.Flatseal"])], ok_label="Install"))))
        self.traces_box.append(group("App permissions", "", *perm))

    def open_secrets(self) -> None:
        self.win.goto("security")
        page = self.win.pages.get("security")
        if page is not None and hasattr(page, "palette_action"):
            GLib.timeout_add(250, lambda: (page.palette_action("secrets"), False)[1])

    def _setting_row(self, s: privacy.Setting) -> Gtk.Widget:
        if s.kind == "bool":
            def change(on: bool, settle, ss=s) -> None:
                st = ss.set_step(on)
                r = sh(st.cmd, timeout=5)
                settle(r.ok)
                if not r.ok:
                    self.toast(f"Couldn't change it: {r.err.strip()[:100]}")
            return switch_row(s.title, s.desc, bool(s.value), change)
        model = Gtk.StringList.new([o[0] for o in s.options])
        row = Adw.ComboRow(model=model)
        row.set_use_markup(False)
        row.set_title(s.title)
        row.set_subtitle(s.desc)
        vals = [o[1] for o in s.options]
        if s.value in vals:
            row.set_selected(vals.index(s.value))
        elif s.value is not None:
            model.append(f"{s.value} (custom)")
            vals.append(s.value)
            row.set_selected(len(vals) - 1)

        def picked(r, _p, ss=s, vv=vals) -> None:
            v = vv[r.get_selected()]
            if v != ss.value:
                res = sh(ss.set_step(v).cmd, timeout=5)
                if res.ok:
                    ss.value = v
                    self.toast(f"{ss.title}: {model.get_string(r.get_selected())}")
        row.connect("notify::selected", picked)
        return row

    # ---------------------------------------------------------------- developer tool telemetry (N1)
    def load_dev(self) -> None:
        self.bg(devtelemetry.status, self.show_dev)

    def show_dev(self, st: dict) -> None:
        self.dev_status = st
        clear(self.dev_holder)
        self.dev_switch = switch_row("Stop developer tools from sending usage data",
                                     "One switch for all of them. New terminals follow it right away; apps you open from the desktop "
                                     "after you log out and back in.", st["configured"], self.dev_toggle)
        count = action_row(f"{st['off_count']} of {st['total']} opt-outs are active",
                           "Each tool reads its own \"don't send\" setting. Nothing else about the tools changes.",
                           prefix=Gtk.Image.new_from_icon_name("emblem-ok-symbolic" if st["off_count"] == st["total"] else "dialog-information-symbolic"))
        installed = [v for v in st["vars"] if v["installed"]]
        exp = Adw.ExpanderRow(title=esc("See each tool"), subtitle=esc(
            f"{len(installed) + len(st['editors'])} installed on this PC; frameworks like Next.js live inside your projects"))
        self.dev_expander = exp
        for e in st["editors"]:
            r = Adw.ActionRow(title=esc(e["name"]), subtitle=esc(f'settings.json → "telemetry.telemetryLevel": "{e["level"]}"'
                                                               + ("" if e["readable"] else " (file couldn't be read, left alone)")))
            r.add_suffix(self._state_pill(e["level"] == "off"))
            r.add_suffix(pill("installed", "neutral"))
            exp.add_row(r)
        for v in sorted(st["vars"], key=lambda v: (not v["installed"], not v["in_projects"], v["tools"].lower())):
            where = "installed" if v["installed"] else ("in projects" if v["in_projects"] else "")
            r = Adw.ActionRow(title=esc(v["tools"]), subtitle=esc(f"{v['var']}={v['value']}"))
            r.set_subtitle_selectable(True)
            if where:
                r.add_suffix(pill(where, "neutral"))
            r.add_suffix(self._state_pill(v["off"]))
            exp.add_row(r)
        if st.get("flutter") or st.get("dart"):
            r = Adw.ActionRow(title=esc("Flutter and Dart"), subtitle=esc("Turned off with their own commands (flutter config --no-analytics)"))
            r.add_suffix(pill("installed", "neutral"))
            exp.add_row(r)
        self.dev_holder.append(group("Developer tools", "Frameworks and command-line tools (Next.js, .NET, VS Code, Homebrew, Angular…) send "
                                     "anonymous usage data unless you opt out, each with its own setting.", self.dev_switch, count, exp))
        self._tab_shown()

    def _state_pill(self, off: bool) -> Gtk.Widget:
        return pill("Off" if off else "Sends data", "ok" if off else "warn")

    def dev_toggle(self, on: bool, settle) -> None:
        if on:
            steps = devtelemetry.off_steps()
            self.run("Turn off developer tool telemetry", steps,
                     "Writes the opt-out settings to your own files (no password needed): a settings file for desktop apps, a marked block "
                     "in your shell startup files, and the telemetry setting in VS Code-style editors (comments in settings.json are kept). "
                     "Switch it back on to remove exactly these lines.", ok_label="Turn off telemetry", reload=False,
                     done=lambda ok: (settle(ok), self.load_dev()))
        else:
            self.run("Let developer tools send usage data again", devtelemetry.on_steps(),
                     "Removes the settings this switch added. Tools go back to their own defaults.", ok_label="Remove opt-outs", reload=False,
                     done=lambda ok: (settle(ok), self.load_dev()))

    # ---------------------------------------------------------------- file search indexing (N2)
    def load_index(self) -> None:
        self.bg(indexing.status, self.show_index)

    def show_index(self, st: dict) -> None:
        self.index_status = st
        box = self.search_box
        clear(box)
        desc = ("GNOME reads your files in the background so searching in Files and the Activities overview is instant. "
                "It keeps an index of file names and their contents on this PC (nothing is sent anywhere).")
        if not st.get("available"):
            box.append(group("File search", desc, action_row("File search indexing isn't installed", "Searching in Files still works, it just "
                                                             "looks through folders as you type.", prefix=Gtk.Image.new_from_icon_name("dialog-information-symbolic"))))
            return
        name = st.get("name") or "the indexer"
        if not st.get("schema"):
            sw = action_row("Index my files for fast search", "Its settings aren't available in this session.")
        else:
            sw = switch_row("Index my files for fast search", "Off: saves a little battery and disk activity, and no index of your files is kept. "
                            "Search in Files still works, just slower.", st["enabled"], self.index_toggle)
        folders = indexing.pretty_dirs(st.get("recursive", [])) + [d for d in indexing.pretty_dirs(st.get("single", []))]
        rows = [sw,
                action_row("Folders it reads", ", ".join(folders) if folders else "None: nothing is being indexed.",
                           prefix=Gtk.Image.new_from_icon_name("folder-symbolic")),
                action_row("Index size", f"{human(st.get('size', 0))} on disk" + (f" · {name} is running" if st.get("running") else ""),
                           button("Delete index", css="flat", tooltip="Frees the space; it's rebuilt by itself while indexing is on",
                                  on_click=self.reset_index),
                           prefix=Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))]
        if st.get("unit"):
            if st.get("masked"):
                rows.append(action_row("The indexer is blocked", f"{st['unit']} can't start at all.",
                                       button("Unblock", css="flat", on_click=lambda: self.run(
                                           "Unblock the file indexer", indexing.block_steps(st, False), ok_label="Unblock", reload=False,
                                           done=lambda ok: ok and self.load_index()))))
            elif not st.get("enabled"):
                rows.append(action_row("Block the indexer completely", "Stops the background service from starting at all. Only if you never "
                                       "want it: some apps expect it and fall back to slower search.",
                                       button("Block", css="flat", on_click=lambda: self.run(
                                           "Block the file indexer", indexing.block_steps(st, True),
                                           "Undo with the Unblock button here.", ok_label="Block", reload=False,
                                           done=lambda ok: ok and self.load_index()))))
        if indexing.gnome_search_settings():
            rows.append(action_row("Search settings", "Choose which folders and apps show up in search results.",
                                   button("Open", css="flat", on_click=lambda: launch(indexing.gnome_search_settings()))))
        box.append(group("File search", desc + (f" On this PC it's called {name}." if st.get("name") else ""), *rows))
        self._tab_shown()

    def index_toggle(self, on: bool, settle) -> None:
        st = self.index_status
        if on:
            self.run("Turn on file search indexing", indexing.on_steps(st), "GNOME indexes your folders again in the background "
                     "(the first run can keep the disk busy for a while).", ok_label="Turn on", reload=False,
                     done=lambda ok: (settle(ok), self.load_index()))
        else:
            self.run("Turn off file search indexing", indexing.off_steps(st), "Your current folder list is saved so turning it back on restores it. "
                     "Use \"Delete index\" afterwards to also remove what was already indexed.", ok_label="Turn off", reload=False,
                     done=lambda ok: (settle(ok), self.load_index()))

    def reset_index(self) -> None:
        st = self.index_status or indexing.status()
        steps = indexing.reset_steps(st)
        if not steps:
            self.toast("There's no search index to delete.")
            return
        self.run("Delete the file search index", steps, "Removes the stored list of your files and their contents. "
                 + ("It's rebuilt quietly in the background while indexing is on." if st.get("enabled") else "Indexing is off, so it stays empty."),
                 ok_label="Delete index", reload=False, done=lambda ok: ok and self.load_index())


PAGE = PrivacyPage
