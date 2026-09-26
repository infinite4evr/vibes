"""Apps: everything installed (apt, Snap, Flatpak, AppImage), install new ones (also from a downloaded file), AppImages in
the app grid, app permissions, apps installed twice or never used, and default apps (including the terminal)."""

from __future__ import annotations

import os
import time

from gi.repository import Adw, Gio, GLib, Gtk

from ...core import appmgr, packages
from ...core.fmt import ago, human
from ...core.run import HOME, out, read
from ..dialogs import ChoiceDialog, PickDialog
from ..util import button, clear, flow, hbox, label, launch, pill, spacer, vbox
from ..widgets import Column, DataTable, card
from .base import Page, action_row, banner, boxed_list, group, stat, switch_row, tabs

SOURCE_PILL = {"apt": ("apt", "info"), "snap": ("snap", "warn"), "flatpak": ("flatpak", "ok"), "appimage": ("AppImage", "accent"),
               "manual": ("manual", "neutral")}

# Popular, well-maintained apps for a developer who likes nice tools. (source, id, name, summary, classic)
PICKS = [
    ("flatpak", "com.mattjakeman.ExtensionManager", "Extension Manager", "Browse and install GNOME extensions", False),
    ("flatpak", "io.missioncenter.MissionCenter", "Mission Center", "Beautiful task manager with GPU stats", False),
    ("flatpak", "io.github.flattool.Warehouse", "Warehouse", "Manage Flatpak apps, their data and versions", False),
    ("flatpak", "it.mijorus.gearlever", "Gear Lever", "Keep AppImages tidy and up to date", False),
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

UNUSED_DAYS = 90


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


def icon_image(icon: str, fallback: str = "application-x-executable-symbolic", size: int = 32) -> Gtk.Image:
    """An app icon from a desktop entry's Icon= value (a name or a file path)."""
    if icon and icon.startswith("/") and os.path.isfile(icon):
        img = Gtk.Image.new_from_file(icon)
    elif icon and not icon.startswith("/"):
        img = Gtk.Image.new_from_icon_name(icon)
    else:
        img = Gtk.Image.new_from_icon_name(fallback)
    img.set_pixel_size(size)
    return img


class PermsDialog(Adw.Dialog):
    """What a Snap or Flatpak app is allowed to do, with switches (like Flatseal)."""

    def __init__(self, page: "AppsPage", app: packages.App):
        super().__init__()
        self.page, self.app = page, app
        self.set_title(f"What {app.name} may do")
        self.set_content_width(680)
        self.set_content_height(640)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        self.box = vbox(spacing=14)
        for m in ("start", "end"):
            getattr(self.box, f"set_margin_{m}")(18)
        self.box.set_margin_bottom(18)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(self.box)
        tv.set_content(sw)
        self.set_child(tv)
        self.load()

    def load(self) -> None:
        self.page.loading(self.box, "Reading permissions…")
        if self.app.source == "snap":
            self.page.bg(lambda: appmgr.snap_connections(self.app.id), self.show_snap)
        else:
            self.page.bg(lambda: appmgr.flatpak_permissions(self.app.id), self.show_flatpak)

    def _change(self, title: str, steps, explain: str, settle) -> None:
        def done(ok: bool) -> None:
            settle(ok)
            if ok:
                self.load()
        self.page.run(title, steps, explain, ok_label="Change", reload=False, done=done)

    def show_snap(self, plugs: list[dict]) -> None:
        clear(self.box)
        self.box.append(label("Snaps run in a sandbox. Each switch below opens one door out of it. Changes apply right away; "
                              "restart the app if it's open. Needs your password.", "dim", wrap=True))
        if not plugs:
            self.box.append(label("This snap asks for no special permissions (or Snap isn't available here).", "dim", wrap=True))
            return
        common = [p for p in plugs if not p["technical"]]
        other = [p for p in plugs if p not in common]
        for title, lst in (("Permissions", common), ("Technical ones", other)):
            if not lst:
                continue
            g = group(title, "" if title == "Permissions" else "Parts the app needs to work. Leave these as they are unless you know why.")
            for p in lst:
                sub = (p["what"] + "  ·  " if p["what"] else "") + p["plug"] + ("  ·  changed by you" if p["manual"] else "")

                def change(on: bool, settle, pp=p) -> None:
                    self._change(("Allow " if on else "Block ") + pp["title"].lower() + f" for {self.app.name}",
                                 appmgr.snap_plug_steps(pp["plug"], on), f"{pp['title']}: {pp['what']}", settle)
                g.add(switch_row(p["title"], sub, p["connected"], change))
            self.box.append(g)

    def show_flatpak(self, res) -> None:
        eff, mine = res
        clear(self.box)
        if not eff:
            self.box.append(label("Couldn't read this app's permissions (is Flatpak installed?).", "dim", wrap=True))
            return
        self.box.append(label("Flatpak apps run in a sandbox. These switches open or close the most common doors out of it. "
                              "Changes are yours only (no password) and apply the next time the app starts.", "dim", wrap=True))
        g = group("Common permissions")
        for key, value, title, what, on_flag, off_flag in appmgr.FLATPAK_TOGGLES:
            def change(on: bool, settle, f_on=on_flag, f_off=off_flag, t=title) -> None:
                self._change(("Allow " if on else "Block ") + t.lower() + f" for {self.app.name}",
                             appmgr.flatpak_override_steps(self.app.id, f_on if on else f_off, ("Allow " if on else "Block ") + t.lower()),
                             "", settle)
            g.add(switch_row(title, what, appmgr.flatpak_has(eff, key, value), change))
        self.box.append(g)
        words = appmgr.flatpak_summary(eff)
        self.box.append(group("Everything it may do", ", ".join(words) if words else "Nothing beyond its own sandbox."))
        if mine.get("Context") or any(mine.values()):
            changed = ", ".join(appmgr.flatpak_summary(mine)) or "some settings"
            self.box.append(group("Your changes", f"You changed: {changed}.",
                                  action_row("Go back to the app's own permissions", "Removes every change you made for this app.",
                                             button("Reset", css="destructive-action", on_click=self.reset))))
        self.box.append(label("Want finer control (single folders, D-Bus)? Install Flatseal from the Get apps tab.", "dim", wrap=True))

    def reset(self) -> None:
        self.page.run(f"Reset permissions of {self.app.name}", appmgr.flatpak_reset_steps(self.app.id), ok_label="Reset", reload=False,
                      done=lambda ok: ok and self.load())


class AppsPage(Page):
    ID = "apps"
    TITLE = "Apps"
    ICON = "view-app-grid-symbolic"
    SUBTITLE = "Everything installed from every source, new apps, and which app opens what."
    PALETTE = [("file", "Install an app from a file (.deb, Flatpak, AppImage, Snap)"),
               ("appimages", "AppImages: add to the app grid or remove"),
               ("several", "Uninstall several apps at once"),
               ("tidy", "Apps installed twice, and apps you never open"),
               ("perms", "App permissions (Snap and Flatpak: camera, files, microphone…)"),
               ("terminal", "Choose the default terminal (Ptyxis, Ghostty…)")]

    def build(self) -> None:
        self.apps: list[packages.App] = []
        self.all_pkgs = False
        self._pending: str | None = None
        self.header(None, button("Install from a file…", icon="document-open-symbolic", tooltip="Install a .deb, .flatpakref, .flatpak, "
                                 "AppImage or .snap file you downloaded", on_click=self.pick_file))
        self.s_count, self.s_size = stat("…", "apps"), stat("…", "space used")
        self.s_by = {k: stat("…", k) for k in ("apt", "snap", "flatpak", "appimage")}
        self.body.append(card(flow(self.s_count, self.s_size, *self.s_by.values(), spacing=22, min_per_line=2, homogeneous=True)))

        self.installed_box = vbox(spacing=10)
        self.get_box = vbox(spacing=14)
        self.appimage_box = vbox(spacing=18)
        self.tidy_box = vbox(spacing=18)
        self.defaults_box = vbox(spacing=14)
        sw, self.stack = tabs(("installed", "Installed", "view-app-grid-symbolic", self.installed_box),
                              ("get", "Get apps", "system-software-install-symbolic", self.get_box),
                              ("appimages", "AppImages", "application-x-executable-symbolic", self.appimage_box),
                              ("tidy", "Tidy up", "edit-clear-all-symbolic", self.tidy_box),
                              ("defaults", "Defaults", "emblem-default-symbolic", self.defaults_box))
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
        self.installed_box.append(flow(self.search_entry, self.source, hbox(label("All packages", "dim"), self.all_switch, spacing=8), spacing=10, max_per_line=3))
        self.table = DataTable([
            Column("name", "App", "bold", expand=True),
            Column("src", "From", "pill", width=100, sort="source"),
            Column("version", "Version", "mono", width=170),
            Column("size", "Size", "size", width=90),
            Column("summary", "Description", "muted", expand=True),
        ], on_activate=lambda r: self.info(r), empty="No apps match.", sort="size")
        self.table.set_size_request(-1, 460)
        self.table.set_context(self._row_menu, "apps")
        self.installed_box.append(self.table)
        self.installed_box.append(flow(
            button("Open", icon="media-playback-start-symbolic", on_click=self.open_selected),
            button("Details", icon="dialog-information-symbolic", on_click=lambda: self.info(self.table.selected())),
            button("Permissions", icon="security-medium-symbolic", tooltip="What a Snap or Flatpak app is allowed to do",
                   on_click=self.perms_selected),
            button(icon="folder-open-symbolic", tooltip="Show its files", on_click=self.files_selected),
            button("Several…", icon="edit-select-all-symbolic", tooltip="Tick several apps and uninstall them in one go",
                   on_click=self.remove_several),
            button("Uninstall…", icon="user-trash-symbolic", css="destructive-action", on_click=self.remove_selected),
            spacing=8, max_per_line=6))

        # get apps
        self.get_entry = Gtk.SearchEntry(placeholder_text="Search Ubuntu, Snap Store and Flathub. Example: vlc, obsidian, postman")
        self.get_entry.set_hexpand(True)
        self.get_entry.connect("activate", lambda *_: self.search())
        self.get_box.append(hbox(self.get_entry, button("Search", css="suggested-action", on_click=self.search)))
        self.get_box.append(group("Downloaded an app from a website?", "",
                                  action_row("Install from a file", "Pick a .deb, .flatpakref, .flatpak, AppImage or .snap file. "
                                             "You'll see exactly what happens before anything is installed.",
                                             button("Choose file…", css="suggested-action", on_click=self.pick_file),
                                             prefix=Gtk.Image.new_from_icon_name("document-open-symbolic"))))
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
        self.tab_loaded -= {"appimages", "tidy"}

    def show(self, apps: list[packages.App]) -> None:
        for a in apps:
            if a.source == "appimage":
                a.name = appmgr.appimage_name(a.id)
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
        if self._pending == "several":
            self._pending = None
            self.remove_several()

    def render(self) -> None:
        q = self.search_entry.get_text().strip().lower()
        src = [None, "apt", "snap", "flatpak", "appimage"][self.source.get_selected()]
        rows = []
        for a in self.apps:
            if src and not (a.source == src or (src == "appimage" and a.source == "manual")):
                continue
            if q and q not in a.name.lower() and q not in a.id.lower() and q not in a.summary.lower():
                continue
            rows.append({"key": f"{a.source}:{a.id}", "name": a.name, "source": a.source, "src": SOURCE_PILL.get(a.source, (a.source, "neutral")),
                         "version": a.version[:30], "size": a.size, "summary": a.summary or a.location, "_a": a})
        self.table.set_rows(rows)

    def _row_menu(self, row: dict) -> list:
        a = row["_a"]
        items = [("Open", lambda r: self.open_selected()), ("Details", self.info)]
        if a.source in ("snap", "flatpak"):
            items.append(("Permissions…", lambda r: PermsDialog(self, r["_a"]).present(self.win)))
        items += [("Show files", lambda r: self.files_selected()), ("Uninstall…", lambda r: self.remove_selected())]
        return items

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

    def perms_selected(self) -> None:
        a = self._sel()
        if not a:
            return
        if a.source not in ("snap", "flatpak"):
            self.toast("Only Snap and Flatpak apps have permissions to change. Other apps can do anything you can.", 5)
            return
        PermsDialog(self, a).present(self.win)

    def remove_selected(self) -> None:
        a = self._sel()
        if not a:
            return
        if appmgr.is_protected(a):
            self.toast(f"{a.name} is part of Ubuntu itself. Removing it would break the desktop.", 5)
            return
        self.run(f"Uninstall {a.name}", packages.remove_steps(a),
                 f"Removes {a.name} ({a.source})" + (f" and frees about {human(a.size)}." if a.size else ".")
                 + (" Its settings in your home folder are kept." if a.source == "apt" else ""), danger=True, ok_label="Uninstall")

    # ---------------------------------------------------------------- E3: several at once
    def remove_several(self, preselect: set[str] | None = None, only: list[packages.App] | None = None) -> None:
        if not self.apps and only is None:
            self._pending = "several"
            self.toast("Still loading your apps…")
            return
        rows = only if only is not None else [r["_a"] for r in (self.table.visible_rows() or [])] or self.apps
        rows = sorted((a for a in rows if not appmgr.is_protected(a)), key=lambda a: a.name.lower())
        by = {f"{a.source}:{a.id}": a for a in rows}
        items = [(k, a.name, f"{SOURCE_PILL.get(a.source, (a.source,))[0]} · {human(a.size) if a.size else 'size unknown'}"
                  + (f" · {a.summary}" if a.summary else ""), k in (preselect or set())) for k, a in by.items()]
        if not items:
            self.toast("No apps to choose from.")
            return

        def done(keys: list[str] | None) -> None:
            if not keys:
                return
            chosen = [by[k] for k in keys if k in by]
            total = sum(a.size for a in chosen)
            names = ", ".join(a.name for a in chosen[:12]) + ("…" if len(chosen) > 12 else "")
            self.run(f"Uninstall {len(chosen)} app{'s' if len(chosen) != 1 else ''}", appmgr.remove_many_steps(chosen),
                     f"Removes {names}." + (f" Frees about {human(total)}." if total else "")
                     + " Their settings and data are deleted too (apt keeps settings in your home folder).",
                     danger=True, ok_label="Uninstall")
        PickDialog("Uninstall several apps", "Tick every app to remove. You'll see all the commands before anything happens. "
                   "Tip: filter the list on the Installed tab first to make this shorter.", items, done).present(self.win)

    # ---------------------------------------------------------------- tabs
    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "get":
            self.show_picks()
        elif name == "defaults":
            self.show_defaults()
        elif name == "appimages":
            self.load_appimages()
        elif name == "tidy":
            self.load_tidy()

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

    # ---------------------------------------------------------------- E1: install from a file
    def pick_file(self, appimage_only: bool = False) -> None:
        if not hasattr(Gtk, "FileDialog"):
            self.toast("The file picker needs a newer GTK. Double-click the file in Files instead.", 5)
            return
        dlg = Gtk.FileDialog(title="Choose an AppImage" if appimage_only else "Install an app from a file")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter()
        if appimage_only:
            f.set_name("AppImages")
            for p in ("*.AppImage", "*.appimage"):
                f.add_pattern(p)
        else:
            f.set_name("Apps (.deb, .flatpakref, .flatpak, AppImage, .snap)")
            for p in appmgr.FILE_PATTERNS:
                f.add_pattern(p)
        filters.append(f)
        every = Gtk.FileFilter()
        every.set_name("All files")
        every.add_pattern("*")
        filters.append(every)
        dlg.set_filters(filters)
        dlg.set_default_filter(f)
        downloads = HOME / "Downloads"
        if downloads.is_dir():
            dlg.set_initial_folder(Gio.File.new_for_path(str(downloads)))

        def picked(d, res) -> None:
            try:
                gf = d.open_finish(res)
            except GLib.Error:
                return
            path = gf.get_path() if gf else None
            if not path:
                self.toast("Pick a file that's on this PC.")
                return
            self.install_file(path)
        dlg.open(self.win, None, picked)

    def install_file(self, path: str) -> None:
        kind = appmgr.file_kind(path)
        if kind is None:
            self.toast("That isn't a file this app can install. Pick a .deb, .flatpakref, .flatpak, AppImage or .snap file.", 5)
            return
        if kind == "appimage":
            self.add_appimage(path)
            return
        if kind == "deb":
            self.toast("Checking what this package needs…")
            self.bg(lambda: appmgr.deb_preview(path), self._confirm_deb)
            return
        info = appmgr.describe_file(path)
        name = info["name"]
        if kind in ("flatpakref", "flatpak"):
            src = info["extra"].get("Url", "")
            explain = (f"Installs {name} for your account from {info['file']}."
                       + (f" It downloads from {src}." if src else "")
                       + " Flatpak apps run in a sandbox and update themselves. No password needed.")
            self.run(f"Install {name}", appmgr.install_file_steps(path, kind, name), explain, ok_label="Install")
        else:
            explain = (f"Installs {name} from {info['file']}. This snap did not come from the Snap Store, so nobody has checked it and "
                       "it won't update by itself. It still runs in the snap sandbox, but only install files from people you trust.")
            self.run(f"Install {name}", appmgr.install_file_steps(path, kind, name), explain, danger=True, ok_label="Install anyway")

    def _confirm_deb(self, prev: dict) -> None:
        f = prev["fields"]
        fname = os.path.basename(prev["path"])
        pkg = f.get("Package", "")
        title = (f.get("Description", "").splitlines() or [""])[0]
        name = pkg or fname
        if prev["error"]:
            self.text(f"Can't install {fname}", "apt can't install this file as it is. What it says:\n\n" + prev["error"]
                      + "\n\nOften this means the file is for another Ubuntu version or another kind of PC (for example ARM).")
            return
        parts = [f"Installs {name}" + (f" {f.get('Version')}" if f.get("Version") else "") + (f": {title}" if title else "") + f" (from {fname})."]
        extra = [p for p, _ in prev["install"] if p != pkg]
        if extra:
            parts.append(f"It also installs {len(extra)} package{'s' if len(extra) != 1 else ''} it needs: "
                         + ", ".join(extra[:12]) + ("…" if len(extra) > 12 else "") + ".")
        if any(p == pkg for p, _ in prev["upgrade"]):
            parts.append("It replaces the version you have installed now.")
        upg = [p for p, _ in prev["upgrade"] if p != pkg]
        if upg:
            parts.append("It updates: " + ", ".join(upg[:12]) + ("…" if len(upg) > 12 else "") + ".")
        removed = [p for p, _ in prev["remove"]]
        if removed:
            parts.append("Careful: it REMOVES " + ", ".join(removed[:12]) + ("…" if len(removed) > 12 else "") + ".")
        parts.append("A .deb gets full access to your PC, so only install ones from websites you trust.")
        self.run(f"Install {name}", appmgr.install_file_steps(prev["path"], "deb", name), "\n\n".join(parts), danger=bool(removed),
                 ok_label="Install")

    # ---------------------------------------------------------------- E2: AppImages
    def load_appimages(self) -> None:
        self.loading(self.appimage_box, "Looking for AppImages…")

        def work():
            integ = appmgr.integrated_appimages()
            return integ, appmgr.loose_appimages(integ), appmgr.fuse2_installed()
        self.bg(work, self.show_appimages)

    def show_appimages(self, res) -> None:
        integ, loose, fuse_ok = res
        box = self.appimage_box
        clear(box)
        box.append(label("AppImages are single-file apps you download from a website. Adding one to the app grid makes it runnable and "
                         "gives it an icon, like any other app.", "dim", wrap=True))
        if not fuse_ok:
            box.append(banner("Many AppImages need a small library called FUSE 2 (libfuse2) to start, and Ubuntu doesn't include it "
                              "anymore. If an AppImage does nothing when you open it, install this.", "warn",
                              button("Install it", on_click=lambda: self.run_make("Install libfuse2", appmgr.fuse2_steps,
                                                                                  "Lets older-style AppImages start. Small and safe.",
                                                                                  ok_label="Install", reload=False))))
        add = button("Add an AppImage…", icon="list-add-symbolic", css="flat", on_click=lambda: self.pick_file(True))
        g = group("In your app grid", "Ones already added. Removing takes away the icon; you can also delete the file.", suffix=add)
        if not integ:
            g.add(action_row("None yet", "Add one with the button above, or from the list below."))
        for a in integ:
            pills = []
            if not a.exists:
                pills.append(pill("file missing", "bad"))
            elif not a.executable:
                pills.append(pill("can't run", "warn"))
            sub = a.short + (f"  ·  {human(a.size)}" if a.size else "") + ("" if a.ours else "  ·  added by another tool")
            open_b = button(icon="media-playback-start-symbolic", css="flat", tooltip="Open", on_click=lambda p=a.path: launch([p]))
            open_b.set_sensitive(a.exists)
            g.add(action_row(a.name, sub, *pills, open_b,
                             button(icon="user-trash-symbolic", css="flat", tooltip="Remove…", on_click=lambda x=a: self.remove_appimage(x)),
                             prefix=icon_image(a.icon or read_icon(a.desktop))))
        box.append(g)
        lg = group("Not in your app grid yet", "Found in Downloads, ~/Applications, ~/Apps and similar folders.")
        if not loose:
            lg.add(action_row("Nothing waiting", "No other AppImage files found."))
        for a in loose[:40]:
            sub = f"{a.short}  ·  {human(a.size)}  ·  downloaded {ago(a.mtime)}"
            lg.add(action_row(a.name, sub, button("Add to app grid", css="flat", on_click=lambda p=a.path: self.add_appimage(p)),
                              button(icon="user-trash-symbolic", css="flat", tooltip="Move the file to the Trash",
                                     on_click=lambda x=a: self.run(f"Delete {os.path.basename(x.path)}",
                                                                   appmgr.remove_integration_steps(x, delete_file=True),
                                                                   "Moves the file to the Trash. You can restore it from there.",
                                                                   ok_label="Move to Trash", reload=False, done=lambda ok: self.load_appimages())),
                              prefix=Gtk.Image.new_from_icon_name("application-x-executable-symbolic")))
        box.append(lg)
        box.append(label("To update an AppImage, download the new version and add it again: the old icon is replaced.", "dim", wrap=True))

    def add_appimage(self, path: str) -> None:
        name = appmgr.appimage_name(path)
        if os.path.dirname(os.path.abspath(path)) == str(appmgr.APPS_DIR):
            self._integrate(path, "keep")
            return
        d = Adw.AlertDialog(heading=f"Add {name} to your app grid",
                            body="Where should the file live? Keeping AppImages in ~/Applications keeps Downloads tidy, and the icon "
                                 "won't break when you clean up Downloads.")
        d.add_response("cancel", "Cancel")
        d.add_response("keep", "Leave it here")
        d.add_response("copy", "Copy there")
        d.add_response("move", "Move to ~/Applications")
        d.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("move")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r != "cancel" and self._integrate(path, r))
        d.present(self.win)

    def _integrate(self, path: str, place: str) -> None:
        name = appmgr.appimage_name(path)
        self.run(f"Add {name} to the app grid", appmgr.integrate_steps(path, place),
                 "Makes it runnable, takes its icon from inside the file, and adds it to your app grid. No password needed.",
                 ok_label="Add", reload=False, done=lambda ok: self._after_appimage())

    def _after_appimage(self) -> None:
        self.tab_loaded.discard("appimages")
        if self.stack.get_visible_child_name() == "appimages":
            self._tab()
        self.bg(appmgr.fuse2_installed, lambda ok: None if ok else self.toast("Tip: if it doesn't start, install libfuse2 (AppImages tab).", 5))

    def remove_appimage(self, a: appmgr.AppImage) -> None:
        d = Adw.AlertDialog(heading=f"Remove {a.name}?", body="Its icon and launcher are removed from the app grid. You can also move the "
                                                              "AppImage file itself to the Trash.")
        d.add_response("cancel", "Cancel")
        d.add_response("grid", "Remove from app grid")
        if a.exists:
            d.add_response("all", "Also move the file to Trash")
            d.set_response_appearance("all", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_close_response("cancel")

        def resp(_d, r) -> None:
            if r == "cancel":
                return
            self.run(f"Remove {a.name}", appmgr.remove_integration_steps(a, delete_file=r == "all"), ok_label="Remove", ask=False,
                     reload=False, done=lambda ok: self._after_appimage())
        d.connect("response", resp)
        d.present(self.win)

    # ---------------------------------------------------------------- E5 + E6: tidy up
    def load_tidy(self) -> None:
        self.loading(self.tidy_box, "Looking for apps installed twice and apps you don't use…")
        have = list(self.apps)

        def work():
            apps = have or packages.all_apps()
            used = appmgr.last_used(apps)
            dups = appmgr.find_duplicates(apps, {k: v[0] for k, v in used.items() if v[1] == "gnome"})
            unused = appmgr.unused_apps(apps, used, UNUSED_DAYS, appmgr.desktop_core_packages())
            return dups, unused, appmgr.APP_STATE.exists(), used
        self.bg(work, self.show_tidy)

    def show_tidy(self, res) -> None:
        dups, unused, gnome, used = res
        box = self.tidy_box
        clear(box)
        # installed twice
        if not dups:
            box.append(group("Installed twice", "", action_row("No app is installed twice", "Nothing to tidy here.",
                                                                 prefix=Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))))
        for g in dups:
            keep = next(c for c in g["copies"] if c["source"] == g["keep"])
            desc = (f"Two copies waste space and you may open the old one by mistake. Suggested: keep the {keep['label']}. "
                    + g["why"])
            grp = group(f"{g['title']} is installed {len(g['copies'])} times", desc)
            for c in g["copies"]:
                sub = ", ".join(c["ids"][:4]) + (f"  ·  {human(c['size'])}" if c["size"] else "")
                sub += f"  ·  last opened {since(c['last'])}" if c["last"] else ""
                if c["source"] == g["keep"]:
                    suffix = pill("keep", "ok")
                else:
                    suffix = button("Remove this copy", css="flat", on_click=lambda cc=c, gg=g: self.remove_copy(gg, cc))
                grp.add(action_row(c["label"], sub, pill(*SOURCE_PILL.get(c["source"], (c["source"], "neutral"))), suffix))
            box.append(grp)
        # not opened in a while
        total = sum(u["app"].size for u in unused)
        how = ("From GNOME's own record of which apps you open." if gnome else
               "GNOME's app-usage record wasn't found, so these are estimates from when the app's files were last read.")
        more = button("Choose several…", icon="edit-select-all-symbolic", css="flat",
                      on_click=lambda: self.remove_several(only=[u["app"] for u in unused]))
        more.set_sensitive(bool(unused))
        ug = group(f"Not opened in {UNUSED_DAYS // 30} months or more",
                   (f"{len(unused)} apps using {human(total)}. " if unused else "") + how, suffix=more)
        if not unused:
            ug.add(action_row("You use all your apps", f"Every app was opened in the last {UNUSED_DAYS // 30} months (or we can't tell).",
                              prefix=Gtk.Image.new_from_icon_name("emblem-ok-symbolic")))
        for u in unused[:40]:
            a = u["app"]
            when = f"last opened {since(u['last'])}" + (" (estimate)" if u["how"] == "files" else "")
            sub = when + (f"  ·  {human(a.size)}" if a.size else "") + (f"  ·  {a.summary}" if a.summary else "")
            ug.add(action_row(a.name, sub, pill(*SOURCE_PILL.get(a.source, (a.source, "neutral"))),
                              button("Remove…", css="flat", on_click=lambda aa=a: self._remove_app(aa))))
        box.append(ug)
        box.append(label("Parts of Ubuntu itself are never listed here.", "dim", wrap=True))

    def _remove_app(self, a: packages.App) -> None:
        self.run(f"Uninstall {a.name}", packages.remove_steps(a), f"Removes {a.name} ({a.source})"
                 + (f" and frees about {human(a.size)}." if a.size else "."), danger=True, ok_label="Uninstall")

    def remove_copy(self, g: dict, c: dict) -> None:
        keep = next(x for x in g["copies"] if x["source"] == g["keep"])
        self.run(f"Remove the {c['label']} copy of {g['title']}", appmgr.remove_copy_steps(c),
                 f"Removes the {c['label']} copy of {g['title']}" + (f" (about {human(c['size'])})" if c["size"] else "")
                 + (f". The {keep['label']} copy stays." if keep is not c else ".")
                 + " Your settings and data are kept, so you can put it back later.", danger=True, ok_label="Remove")

    # ---------------------------------------------------------------- defaults (+ E7 terminal)
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
        self.term_holder = vbox()
        self.defaults_box.append(self.term_holder)
        self.loading(self.term_holder, "Looking for terminals…")

        def work():
            terms = appmgr.installed_terminals()
            return terms, appmgr.default_terminal(terms)
        self.bg(work, self.show_terminals)

    def show_terminals(self, res) -> None:
        terms, (cur, src) = res
        clear(self.term_holder)
        g = group("Terminal", "Which terminal opens for “Open in Terminal”, Ctrl+Alt+T and apps that need one. Ubuntu uses Ptyxis; "
                  "Ghostty is a popular, faster choice.")
        if not terms:
            g.add(action_row("No terminal apps found", "Install one from the Get apps tab (try “ghostty” or “ptyxis”)."))
        for t in terms:
            icon = appmgr.parse_desktop_entry(read(t["file"])).get("Icon", "")
            suffix = pill("default", "ok") if t["id"] == cur else button("Make default", css="flat", on_click=lambda tt=t: self.set_terminal(tt))
            g.add(action_row(t["name"], t["note"] or t["id"], suffix, prefix=icon_image(icon, "utilities-terminal-symbolic")))
        self.term_holder.append(g)
        if cur and src:
            self.term_holder.append(label(f"Set in {src.replace(str(HOME), '~')}.", "dim", wrap=True))

    def set_terminal(self, t: dict) -> None:
        self.run_make(f"Make {t['name']} the default terminal", lambda: appmgr.set_terminal_steps(t),
                 f"{t['name']} opens for “Open in Terminal”, Ctrl+Alt+T and apps that need a terminal. No password needed.",
                 ok_label="Make default", reload=False, done=lambda ok: ok and self._refresh_defaults())

    def _refresh_defaults(self) -> None:
        self.toast("Default terminal changed.")
        self.show_defaults()

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

    # ---------------------------------------------------------------- command palette
    def palette_action(self, key: str) -> None:
        if key == "file":
            self.pick_file()
        elif key == "appimages":
            self.stack.set_visible_child_name("appimages")
        elif key == "several":
            self.stack.set_visible_child_name("installed")
            self.remove_several()
        elif key == "tidy":
            self.stack.set_visible_child_name("tidy")
        elif key == "perms":
            self.stack.set_visible_child_name("installed")
            self.toast("Pick a Snap or Flatpak app, then click Permissions.", 5)
        elif key == "terminal":
            self.stack.set_visible_child_name("defaults")


def since(ts: float) -> str:
    """'3 days ago', '5 months ago', 'over a year ago': friendlier than exact hours for rarely used apps."""
    days = int((time.time() - ts) // 86400)
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 45:
        return f"{days} days ago"
    if days < 365:
        return f"{round(days / 30)} months ago"
    years = days / 365
    return "over a year ago" if years < 2 else f"over {int(years)} years ago"


def read_icon(desktop_file: str) -> str:
    return appmgr.parse_desktop_entry(read(desktop_file)).get("Icon", "") if desktop_file else ""


PAGE = AppsPage
