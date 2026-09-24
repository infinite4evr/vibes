"""Privacy: what's using your camera/mic right now, GNOME privacy switches, telemetry, and clearing history."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ...core import junk, privacy
from ...core.fmt import human
from ...core.run import Step, has, py_step, sh
from ..util import button, clear, esc, flow, hbox, label, launch, vbox
from ..widgets import card
from .base import Page, action_row, group, switch_row


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
    SUBTITLE = "Who's using your camera and microphone, what Ubuntu sends home, and what your PC remembers about you."
    AUTO_REFRESH = 3.0

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
        self.body.append(self.settings_holder)

    def load(self) -> None:
        self.tick()
        self.bg(lambda: (privacy.settings(), privacy.telemetry(), privacy.shell_histories(), junk.recent_files(), junk.clipboard_history(),
                         junk.thumbnails()), self.show)

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

    # ---------------------------------------------------------------- settings
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

        rows = []
        for t in tele:
            def change(on: bool, settle, tt=t) -> None:
                steps = tt.on_steps if on else tt.off_steps
                root = any(s.root for s in steps)
                self.run(("Turn on " if on else "Turn off ") + tt.title, steps, tt.desc, reload=False, done=settle, ask=root)
            rows.append(switch_row(t.title, t.desc, t.active, change))
        if rows:
            off_all = [s for t in tele if t.active for s in t.off_steps]
            self.settings_holder.append(group("What Ubuntu sends home", "Reports and ads. Turning them off doesn't affect updates.", *rows,
                                              suffix=button("Turn all off", css="flat", on_click=lambda: self.run(
                                                  "Turn off reporting", off_all, "Stops crash/usage reports and Pro ads.", ok_label="Turn off"))
                                              if off_all else None))

        # history and traces
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
        if trace_rows:
            self.settings_holder.append(group("Traces you can clear", "", *trace_rows))

        perm = [action_row("App permissions", "Which apps may use the camera, files, notifications and more.",
                           button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "applications"])))]
        if has("flatpak"):
            if sh(["flatpak", "info", "com.github.tchx84.Flatseal"], timeout=5).ok:
                perm.append(action_row("Flatseal", "Fine-grained permissions for Flatpak apps.", button("Open", css="flat", on_click=lambda: launch(["flatpak", "run", "com.github.tchx84.Flatseal"]))))
            else:
                perm.append(action_row("Flatseal", "Review and restrict what each Flatpak app can access.", button("Install", css="flat", on_click=lambda: self.run(
                    "Install Flatseal", [Step("Install Flatseal", ["flatpak", "install", "-y", "--user", "flathub", "com.github.tchx84.Flatseal"])], ok_label="Install"))))
        self.settings_holder.append(group("App permissions", "", *perm))

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
        row = Adw.ComboRow(title=esc(s.title), subtitle=esc(s.desc), model=model)
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


PAGE = PrivacyPage
