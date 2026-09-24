"""Apps: everything installed (apt, Snap, Flatpak, AppImage), install new ones, and default apps."""

from __future__ import annotations

import os

from gi.repository import Gio, Gtk

from ...core import packages
from ...core.fmt import human
from ...core.run import out
from ..dialogs import ChoiceDialog
from ..util import button, clear, hbox, label, launch, pill, spacer, vbox
from ..widgets import Column, DataTable, card
from .base import Page, action_row, boxed_list, group, stat, tabs

SOURCE_PILL = {"apt": ("apt", "info"), "snap": ("snap", "warn"), "flatpak": ("flatpak", "ok"), "appimage": ("AppImage", "accent"),
               "manual": ("manual", "neutral")}

# Popular, well-maintained apps for a developer who likes nice tools. (source, id, name, summary, classic)
PICKS = [
    ("flatpak", "com.mattjakeman.ExtensionManager", "Extension Manager", "Browse and install GNOME extensions", False),
    ("flatpak", "io.missioncenter.MissionCenter", "Mission Center", "Beautiful task manager with GPU stats", False),
    ("flatpak", "io.github.flattool.Warehouse", "Warehouse", "Manage Flatpak apps, their data and versions", False),
    ("flatpak", "md.obsidian.Obsidian", "Obsidian", "Markdown notes and knowledge base", False),
    ("flatpak", "com.usebruno.Bruno", "Bruno", "Open-source API client (Postman alternative)", False),
    ("flatpak", "io.dbeaver.DBeaverCommunity", "DBeaver", "Database GUI for Postgres, MySQL, SQLite…", False),
    ("flatpak", "io.podman_desktop.PodmanDesktop", "Podman Desktop", "Containers and Kubernetes in a GUI", False),
    ("flatpak", "org.localsend.localsend_app", "LocalSend", "AirDrop-style file sharing with your phone", False),
    ("flatpak", "com.github.tchx84.Flatseal", "Flatseal", "Review and change Flatpak app permissions", False),
    ("flatpak", "org.gnome.World.PikaBackup", "Pika Backup", "Simple, encrypted backups of your home folder", False),
    ("flatpak", "com.obsproject.Studio", "OBS Studio", "Screen recording and streaming", False),
    ("flatpak", "org.videolan.VLC", "VLC", "Plays every video and audio format", False),
    ("flatpak", "com.bitwarden.desktop", "Bitwarden", "Password manager", False),
    ("flatpak", "com.discordapp.Discord", "Discord", "Voice and text chat", False),
    ("flatpak", "com.slack.Slack", "Slack", "Team chat", False),
    ("flatpak", "com.spotify.Client", "Spotify", "Music streaming", False),
    ("snap", "postman", "Postman", "API platform", False),
]

DEFAULTS = [
    ("Web browser", ["x-scheme-handler/https", "x-scheme-handler/http", "text/html"], "web-browser-symbolic"),
    ("Email", ["x-scheme-handler/mailto"], "mail-unread-symbolic"),
    ("Text and code files", ["text/plain", "text/markdown", "application/json", "text/x-python"], "text-x-generic-symbolic"),
    ("Folders", ["inode/directory"], "folder-symbolic"),
    ("PDF documents", ["application/pdf"], "x-office-document-symbolic"),
    ("Images", ["image/png", "image/jpeg", "image/webp", "image/gif"], "image-x-generic-symbolic"),
    ("Videos", ["video/mp4", "video/x-matroska", "video/webm"], "video-x-generic-symbolic"),
    ("Music", ["audio/mpeg", "audio/flac", "audio/ogg"], "audio-x-generic-symbolic"),
]


def launch_app(a: packages.App) -> bool:
    if a.source == "apt" and a.desktop:
        launch(["gio", "launch", a.desktop])
    elif a.source == "snap":
        launch(["snap", "run", a.id])
    elif a.source == "flatpak":
        launch(["flatpak", "run", a.id])
    elif a.source == "appimage":
        launch([a.id])
    else:
        return False
    return True


class AppsPage(Page):
    ID = "apps"
    TITLE = "Apps"
    ICON = "view-app-grid-symbolic"
    SUBTITLE = "Everything installed from every source, new apps, and which app opens what."

    def build(self) -> None:
        self.apps: list[packages.App] = []
        self.all_pkgs = False
        self.header()
        self.s_count, self.s_size = stat("…", "apps"), stat("…", "space used")
        self.s_by = {k: stat("…", k) for k in ("apt", "snap", "flatpak", "appimage")}
        self.body.append(card(hbox(self.s_count, self.s_size, spacer(), *self.s_by.values(), spacing=28)))

        self.installed_box = vbox(spacing=10)
        self.get_box = vbox(spacing=14)
        self.defaults_box = vbox(spacing=14)
        sw, self.stack = tabs(("installed", "Installed", "view-app-grid-symbolic", self.installed_box),
                              ("get", "Get apps", "system-software-install-symbolic", self.get_box),
                              ("defaults", "Default apps", "emblem-default-symbolic", self.defaults_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()

        # installed
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search installed apps…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda *_: self.render())
        self.source = Gtk.DropDown.new_from_strings(["All sources", "System (apt)", "Snap", "Flatpak", "AppImage / manual"])
        self.source.connect("notify::selected", lambda *_: self.render())
        self.all_switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Also list command-line packages you installed with apt")
        self.all_switch.connect("notify::active", self._toggle_all)
        self.installed_box.append(hbox(self.search_entry, self.source, label("All packages", "dim"), self.all_switch, spacing=10))
        self.table = DataTable([
            Column("name", "App", "bold", expand=True),
            Column("src", "From", "pill", width=100, sort="source"),
            Column("version", "Version", "mono", width=170),
            Column("size", "Size", "size", width=90),
            Column("summary", "Description", "muted", expand=True),
        ], on_activate=lambda r: self.info(r), empty="No apps match.", sort="size")
        self.table.set_size_request(-1, 460)
        self.installed_box.append(self.table)
        self.installed_box.append(hbox(
            button("Open", icon="media-playback-start-symbolic", on_click=self.open_selected),
            button("Details", icon="dialog-information-symbolic", on_click=lambda: self.info(self.table.selected())),
            button("Show files", icon="folder-open-symbolic", on_click=self.files_selected),
            spacer(),
            button("Uninstall…", icon="user-trash-symbolic", css="destructive-action", on_click=self.remove_selected)))

        # get apps
        self.get_entry = Gtk.SearchEntry(placeholder_text="Search Ubuntu, Snap Store and Flathub. Example: vlc, obsidian, postman")
        self.get_entry.set_hexpand(True)
        self.get_entry.connect("activate", lambda *_: self.search())
        self.get_box.append(hbox(self.get_entry, button("Search", css="suggested-action", on_click=self.search)))
        self.results_box = vbox(spacing=8)
        self.get_box.append(self.results_box)
        self.picks_holder = vbox()
        self.get_box.append(self.picks_holder)

    # ---------------------------------------------------------------- installed
    def load(self) -> None:
        self.table.set_empty("Loading apps…")

        def work():
            apps = packages.all_apps()
            if self.all_pkgs:
                known = {a.id for a in apps}
                apps += [a for a in packages.apt_manual() if a.id not in known]
            return apps
        self.bg(work, self.show)
        if self.stack.get_visible_child_name() != "installed":
            self.tab_loaded.discard(self.stack.get_visible_child_name())
            self._tab()

    def show(self, apps: list[packages.App]) -> None:
        self.apps = apps
        self.table.set_empty("No apps match.")
        by: dict[str, int] = {}
        for a in apps:
            k = "appimage" if a.source == "manual" else a.source
            by[k] = by.get(k, 0) + 1
        self.s_count._value.set_text(str(len(apps)))
        self.s_size._value.set_text(human(sum(a.size for a in apps)))
        for k, w in self.s_by.items():
            w._value.set_text(str(by.get(k, 0)))
        self.render()
        if "get" in self.tab_loaded:
            self.show_picks()

    def render(self) -> None:
        q = self.search_entry.get_text().strip().lower()
        src = [None, "apt", "snap", "flatpak", "appimage"][self.source.get_selected()]
        rows = []
        for i, a in enumerate(self.apps):
            if src and not (a.source == src or (src == "appimage" and a.source == "manual")):
                continue
            if q and q not in a.name.lower() and q not in a.id.lower() and q not in a.summary.lower():
                continue
            rows.append({"key": f"{a.source}:{a.id}", "name": a.name, "source": a.source, "src": SOURCE_PILL.get(a.source, (a.source, "neutral")),
                         "version": a.version[:30], "size": a.size, "summary": a.summary or a.location, "_a": a})
        self.table.set_rows(rows)

    def _toggle_all(self, sw, _p) -> None:
        self.all_pkgs = sw.get_active()
        self.load()

    def _sel(self) -> packages.App | None:
        r = self.table.selected()
        if not r:
            self.toast("Select an app first.")
            return None
        return r["_a"]

    def open_selected(self) -> None:
        a = self._sel()
        if a and not launch_app(a):
            self.toast("This one has no app window to open.")

    def files_selected(self) -> None:
        a = self._sel()
        if not a:
            return
        if a.source in ("appimage", "manual"):
            launch(["xdg-open", os.path.dirname(a.id) if a.source == "appimage" else a.id])
            return
        cmd = {"apt": ["dpkg", "-L", a.id], "snap": ["bash", "-c", f"ls -la /snap/{a.id}/current/ ~/snap/{a.id} 2>&1"],
               "flatpak": ["flatpak", "info", "--show-location", a.id]}.get(a.source)
        self.bg(lambda: out(cmd, timeout=20), lambda t: self.text(f"Files of {a.name}", t))

    def info(self, row: dict | None) -> None:
        if not row:
            return
        a = row["_a"]
        cmd = {"apt": ["apt-cache", "show", "--no-all-versions", a.id], "snap": ["snap", "info", a.id], "flatpak": ["flatpak", "info", a.id]}.get(a.source)
        if not cmd:
            self.text(a.name, f"{a.name}\n{a.location}\n{human(a.size)}")
            return
        self.bg(lambda: out(cmd, timeout=20), lambda t: self.text(f"{a.name} ({a.source})", t))

    def remove_selected(self) -> None:
        a = self._sel()
        if not a:
            return
        protected = {"gnome-shell", "gdm3", "ubuntu-desktop", "nautilus", "gnome-control-center", "snapd", "network-manager", "systemd", "apt"}
        if a.id in protected:
            self.toast(f"{a.name} is part of Ubuntu itself. Removing it would break the desktop.", 5)
            return
        self.run(f"Uninstall {a.name}", packages.remove_steps(a),
                 f"Removes {a.name} ({a.source})" + (f" and frees about {human(a.size)}." if a.size else ".")
                 + (" Its settings in your home folder are kept." if a.source == "apt" else ""), danger=True, ok_label="Uninstall")

    # ---------------------------------------------------------------- get apps
    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "get":
            self.show_picks()
        elif name == "defaults":
            self.show_defaults()

    def show_picks(self) -> None:
        installed = {(a.source, a.id) for a in self.apps}
        clear(self.picks_holder)
        self.picks_group = group("Recommended", "Popular, well-maintained apps. Flatpaks are sandboxed and update themselves.")
        self.picks_holder.append(self.picks_group)
        for src, pid, name, summary, classic in PICKS:
            have = (src, pid) in installed
            a = packages.App(src, pid, name, summary=summary, location="classic" if classic else "")
            suffix = pill("installed", "ok") if have else button("Install", css="flat", on_click=lambda aa=a: self.install(aa))
            self.picks_group.add(action_row(name, summary, pill(src, SOURCE_PILL[src][1]), suffix))

    def search(self) -> None:
        q = self.get_entry.get_text().strip()
        if not q:
            return
        self.loading(self.results_box, f"Searching for “{q}”…")
        self.bg(lambda: packages.search(q), lambda res: self.show_results(q, res))

    def show_results(self, q: str, res: list[packages.App]) -> None:
        clear(self.results_box)
        if not res:
            self.results_box.append(label(f"Nothing found for “{q}”. Try a shorter name.", "dim"))
            return
        lb = boxed_list()
        for a in res[:40]:
            text, kind = SOURCE_PILL.get(a.source, (a.source, "neutral"))
            suffix = pill("installed", "ok") if a.location == "installed" else button("Install", css="flat", on_click=lambda aa=a: self.install(aa))
            lb.append(action_row(a.name, (a.summary or "") + (f"   ·   {a.version}" if a.version else ""), pill(text, kind), suffix))
        self.results_box.append(label(f"Results for “{q}”", "section-title"))
        self.results_box.append(lb)
        self.results_box.append(label("Tip: Flatpak and Snap apps are sandboxed and update themselves; apt apps come from Ubuntu and "
                                      "update with the system.", "dim", wrap=True))

    def install(self, a: packages.App) -> None:
        steps = packages.install_steps(a)
        if not steps:
            self.toast("Can't install this one automatically.")
            return
        self.run(f"Install {a.name}", steps, f"Installs {a.name} from {a.source}.", ok_label="Install")

    # ---------------------------------------------------------------- defaults
    def show_defaults(self) -> None:
        clear(self.defaults_box)
        rows = []
        for title, mimes, icon in DEFAULTS:
            cur = Gio.AppInfo.get_default_for_type(mimes[0], False)
            img = Gtk.Image.new_from_gicon(cur.get_icon()) if cur and cur.get_icon() else Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(32)
            r = action_row(title, cur.get_display_name() if cur else "Not set",
                           button("Change…", css="flat", on_click=lambda t=title, m=mimes: self.change_default(t, m)), prefix=img)
            rows.append(r)
        self.defaults_box.append(group("Opens with", "Which app opens links and files of each kind.", *rows))
        term = out(["bash", "-c", "head -n1 ~/.config/ubuntu-xdg-terminals.list 2>/dev/null || head -n1 ~/.config/xdg-terminals.list 2>/dev/null"])
        self.defaults_box.append(group("Terminal", "", action_row("Default terminal", term.replace(".desktop", "") or "Ubuntu default (Ptyxis)")))

    def change_default(self, title: str, mimes: list[str]) -> None:
        apps = Gio.AppInfo.get_all_for_type(mimes[0])
        seen, rows = set(), []
        for app in apps:
            aid = app.get_id() or ""
            if aid in seen:
                continue
            seen.add(aid)
            rows.append((aid, app.get_display_name(), aid.replace(".desktop", "")))
        if not rows:
            self.toast("No apps installed that can open these.")
            return

        def done(aid: str | None) -> None:
            if not aid:
                return
            app = next((a for a in apps if a.get_id() == aid), None)
            if app is None:
                return
            for m in mimes:
                try:
                    app.set_as_default_for_type(m)
                except Exception:  # noqa: BLE001
                    pass
            if "x-scheme-handler/https" in mimes:
                launch(["xdg-settings", "set", "default-web-browser", aid])
            self.toast(f"{app.get_display_name()} now opens {title.lower()}.")
            self.show_defaults()
        ChoiceDialog(f"Default app: {title}", rows, done, explain="Pick the app that should open these.").present(self.win)


PAGE = AppsPage
