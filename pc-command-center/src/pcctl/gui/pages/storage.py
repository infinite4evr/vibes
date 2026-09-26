"""Storage: drives, partitions and health, swap, speed test, folder explorer (list + map), big files, duplicates and similar
photos, empty folders, file types and the Trash."""

from __future__ import annotations

import os
import time

from gi.repository import Adw, Gtk

from ...core import drives, dupes, storage, system
from ...core.fmt import ago, human
from ...core.run import HOME, Step, has
from ..util import button, clear, esc, flow, hbox, idle, label, open_path, pill, spacer, status_icon, vbox
from ..widgets import Column, DataTable, HBars, MiniBar, Treemap, card
from .base import Page, action_row, banner, boxed_list, group, tabs

DUPE_ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]


def short(p: str) -> str:
    return p.replace(str(HOME), "~", 1)


class StoragePage(Page):
    ID = "storage"
    TITLE = "Storage"
    ICON = "drive-harddisk-symbolic"
    SUBTITLE = "What's taking up space, down to single files. Find big files and duplicates."

    def build(self) -> None:
        self.header()
        self.overview = vbox(spacing=18)
        self.explore = vbox(spacing=10)
        self.big = vbox(spacing=10)
        self.dups = vbox(spacing=12)
        self.trash_box = vbox(spacing=10)
        self.types_box = vbox(spacing=14)
        sw, self.stack = tabs(("overview", "Disks", "drive-harddisk-symbolic", self.overview),
                              ("explore", "Explore", "folder-open-symbolic", self.explore),
                              ("big", "Big files", "zoom-in-symbolic", self.big),
                              ("dups", "Duplicates", "edit-copy-symbolic", self.dups),
                              ("types", "File types", "folder-documents-symbolic", self.types_box),
                              ("trash", "Trash", "user-trash-symbolic", self.trash_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_explore()
        self._build_big()
        self._build_dups()
        self._build_trash()
        self._build_types()

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"overview": self.load_overview, "explore": lambda: self.go(self.path), "big": self.find_big, "dups": lambda: None,
         "trash": self.load_trash, "types": lambda: None}[name]()

    # ---------------------------------------------------------------- overview
    def load_overview(self) -> None:
        self.loading(self.overview, "Measuring disks…")

        def work():
            return system.mounts(), drives.block_devices(), storage.children(HOME, timeout=120), drives.swap_info()
        self.bg(work, self.show_overview)

    def show_overview(self, res) -> None:
        mounts, disks, (home_total, home_items), swaps = res
        clear(self.overview)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=3, min_children_per_line=1,
                           column_spacing=12, row_spacing=12)
        for m in mounts:
            bar = MiniBar(height=12, warn=80, crit=90)
            bar.set(m.pct / 100)
            pct = label(f"{m.pct:.0f}%", ["big-num", "bad-text" if m.pct >= 90 else ("warn-text" if m.pct >= 80 else "ok-text")])
            name = "Main disk" if m.mountpoint == "/" else ("Home" if m.mountpoint == "/home" else m.mountpoint)
            c = card(hbox(pct, vbox(label(f"{human(m.free)} free", "heading"), label(f"of {human(m.total)}", "dim"), spacing=0), spacing=14),
                     bar, label(f"{m.mountpoint} · {m.device} · {m.fstype}", "dim", ellipsize=True), title=name)
            flow.append(c)
        self.overview.append(flow)

        # home breakdown
        top = [e for e in home_items if e.size > 0][:12]
        if top:
            bars = HBars("mauve", row=26, label_width=260)
            bars.set_items([(("~/" + e.name) + (f"   ({storage.hint_for(e.path)[:40]})" if storage.hint_for(e.path) else ""), e.size, human(e.size))
                            for e in top])
            self.overview.append(card(bars, hbox(label(f"Your home folder uses {human(home_total)}.", "dim", hexpand=True),
                                                 button("Explore", css="flat", on_click=lambda: (self.go(str(HOME)), self.stack.set_visible_child_name("explore")))),
                                      title="What's in your home folder"))

        # drives + partitions
        dg = group("Drives", "Every drive in or plugged into this PC. “Health” reads the drive's own report: wear, errors, temperature.")
        for d in disks:
            kind = "HDD" if d["rota"] and d["tran"] not in ("nvme", "virtio") else ("NVMe SSD" if d["name"].startswith("nvme") else
                                                                                    ("USB drive" if d["tran"] == "usb" else "SSD"))
            icon = "drive-removable-media-symbolic" if d["removable"] or d["tran"] == "usb" else (
                "drive-harddisk-solidstate-symbolic" if "SSD" in kind else "drive-harddisk-symbolic")
            exp = Adw.ExpanderRow(title=esc(d["model"] or d["name"]), subtitle=esc(f"{human(d['size'])} {kind} · {d['path']}"))
            exp.add_prefix(Gtk.Image.new_from_icon_name(icon))
            btns = hbox(spacing=6)
            btns.set_valign(Gtk.Align.CENTER)
            if d["type"] == "disk":
                btns.append(button("Health", css="flat", on_click=lambda dv=d["path"]: self.smart(dv)))
            if d["removable"] or d["tran"] == "usb":
                btns.append(button("Safely remove", icon="media-eject-symbolic", css="flat", on_click=lambda dd=d: self.run(
                    f"Safely remove {dd['model'] or dd['path']}", drives.eject_steps(dd), "Unmounts it and switches it off. Unplug it "
                    "when this finishes.", ok_label="Remove", reload=True, ask=False)))
            exp.add_suffix(btns)
            parts = d["children"] or ([d] if d["fstype"] else [])
            for pt in parts:
                used = f" · {human(pt['used'])} used of {human(pt['size'])}" if pt["used"] else f" · {human(pt['size'])}"
                sub = (pt["fstype"] or "no filesystem") + used + (f" · mounted at {', '.join(pt['mounts'])}" if pt["mounts"] else " · not mounted")
                row_btns = []
                if pt["fstype"] and pt["fstype"] not in ("swap", "crypto_LUKS") and not any(m in ("/", "/boot", "/boot/efi", "/home", "[SWAP]") for m in pt["mounts"]):
                    if pt["mounts"]:
                        row_btns.append(button("Unmount", css="flat", on_click=lambda pp=pt: self.run(f"Unmount {pp['path']}", drives.unmount_steps(pp["path"]),
                                                                                                      ask=False)))
                    else:
                        row_btns.append(button("Mount", css="flat", on_click=lambda pp=pt: self.run(f"Mount {pp['path']}", drives.mount_steps(pp["path"]),
                                                                                                    ask=False)))
                if pt["mounts"] and pt["mounts"][0].startswith("/"):
                    row_btns.append(button(icon="folder-open-symbolic", css="flat", tooltip="Open", on_click=lambda m=pt["mounts"][0]: open_path(m)))
                exp.add_row(action_row(pt["label"] or pt["name"], sub, *row_btns))
            dg.add(exp)
        if disks:
            self.overview.append(dg)

        # swap
        sg = group("Swap", "Overflow space for when memory is full. Compressed memory (zram, in Tweaks) is faster than a swap file.")
        if not swaps:
            sg.add(action_row("No swap", "If memory runs out, apps get closed. A swap file or zram prevents that."))
        for sw_ in swaps:
            b = []
            if not sw_["zram"] and sw_["type"] == "file":
                b.append(button("Resize…", css="flat", on_click=lambda ss=sw_: self.resize_swap(ss)))
            sg.add(action_row(sw_["path"], f"{'compressed memory (zram)' if sw_['zram'] else sw_['type']} · {human(sw_['used'])} used of "
                              f"{human(sw_['size'])}", *b))
        self.overview.append(sg)

        self.speed_row = action_row("Disk speed test", "Writes and reads a 512 MB test file in your home folder (then deletes it).",
                                    button("Run", css="flat", on_click=self.disk_speed))
        self.overview.append(group("How fast is it?", "", self.speed_row))
        tools = [action_row("Trim SSDs now", "Tells the SSD which blocks are free so it stays fast. Ubuntu does this weekly; running it now is harmless.",
                            button("Run", css="flat", on_click=lambda: self.run("Trim SSDs", [Step("Trim all mounted filesystems", ["fstrim", "-av"], root=True)], ok_label="Trim"))),
                 action_row("Disks app", "Format drives, check partitions, benchmark.", button("Open", css="flat", on_click=lambda: self._launch("gnome-disks"))),
                 action_row("Disk Usage Analyzer", "Ubuntu's sunburst chart of folders.", button("Open", css="flat", on_click=lambda: self._launch("baobab")))]
        self.overview.append(group("Tools", "", *tools))

    def _launch(self, cmd: str) -> None:
        from ..util import launch
        if has(cmd):
            launch([cmd])
        else:
            self.toast(f"{cmd} isn't installed.")

    def smart(self, dev: str) -> None:
        from ..runner import capture
        self.toast("Reading the drive's health report (needs your password)…", 3)

        def done(ok: bool, lines: list[str]) -> None:
            text = "\n".join(lines)
            info = drives.parse_smart(text)
            if not info["facts"] and info["ok"] is None:
                self.text(f"Drive health: {dev}", text or "No report. The drive may not support SMART (common in virtual machines and some USB adapters).")
                return
            self.show_smart(dev, info, text)
        capture(drives.smart_steps(dev), done)

    def show_smart(self, dev: str, info: dict, raw: str) -> None:
        d = Adw.Dialog()
        d.set_title(f"Drive health: {info.get('model') or dev}")
        d.set_content_width(620)
        d.set_content_height(520)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        box = vbox(spacing=12)
        for m in ("start", "end", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        level = "ok" if info["ok"] else ("bad" if info["ok"] is False else "info")
        box.append(banner(info["verdict"], level))
        lb = boxed_list()
        for lab, val, lvl in info["facts"]:
            lb.append(action_row(lab, val, prefix=status_icon(lvl)))
        box.append(lb)
        box.append(hbox(label(f"{dev}" + (f" · serial {info['serial']}" if info.get("serial") else ""), "dim", hexpand=True),
                        button("Full report", css="flat", on_click=lambda: self.text("SMART report", raw))))
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_vexpand(True)
        sw.set_child(box)
        tv.set_content(sw)
        d.set_child(tv)
        d.present(self.win)

    def resize_swap(self, sw_: dict) -> None:
        from ..dialogs import ask_text

        def got(v: str | None) -> None:
            if not v:
                return
            try:
                gb = int(float(v))
            except ValueError:
                self.toast("Enter a number of GB, like 8.")
                return
            if not 1 <= gb <= 64:
                self.toast("Pick between 1 and 64 GB.")
                return
            self.run(f"Swap file {gb} GB", drives.resize_swapfile_steps(gb, sw_["path"]), "Swap is briefly turned off while it's resized; "
                     "make sure you have enough free memory right now.", ok_label="Resize")
        ask_text(self.win, "Swap file size", f"Now {human(sw_['size'])}. A common choice is the same as your RAM up to 8 GB "
                 "(more only if you hibernate).", "8", got, ok_label="Resize", initial=str(max(1, round(sw_["size"] / 1024 ** 3))))

    def disk_speed(self) -> None:
        self.speed_row.set_subtitle("Testing… this takes a few seconds.")
        self.bg(lambda: drives.speed_test(HOME / ".cache"), self._speed_done)

    def _speed_done(self, r: dict) -> None:
        if r.get("error"):
            self.speed_row.set_subtitle(r["error"])
            return
        self.speed_row.set_subtitle(f"Read {r['read_mbs']:.0f} MB/s · write {r['write_mbs']:.0f} MB/s. {drives.speed_verdict(r['read_mbs'])}")

    # ---------------------------------------------------------------- explore
    def _build_explore(self) -> None:
        self.path = str(HOME)
        self.history: list[str] = []
        self.crumb = label("", ["heading", "mono"], ellipsize=True, hexpand=True)
        self.explore_total = label("", "dim")
        nav = hbox(button(icon="go-previous-symbolic", tooltip="Back", on_click=self.back),
                   button(icon="go-up-symbolic", tooltip="Up one folder", on_click=lambda: self.go(os.path.dirname(self.path.rstrip("/")) or "/")),
                   button(icon="user-home-symbolic", tooltip="Home folder", on_click=lambda: self.go(str(HOME))),
                   button("/", tooltip="Whole disk (some folders need admin rights to measure)", on_click=lambda: self.go("/")), spacing=0, css="linked")
        self.explore.append(flow(nav, self.crumb, self.explore_total, self._view_toggle(),
                                 button("Open in Files", icon="folder-open-symbolic", on_click=lambda: open_path(self.path)),
                                 min_per_line=1, max_per_line=5, column_spacing=8, row_spacing=8))
        self.etable = DataTable([
            Column("name", "Name", "markup", expand=True),
            Column("share", "Share", "bar", width=150, fmt=lambda v, d: f"{(v or 0) * 100:.0f}%"),
            Column("size", "Size", "size", width=100),
            Column("hint", "What it is", "muted", expand=True),
        ], on_activate=self._enter, empty="Empty folder.", sort="size")
        self.etable.set_size_request(-1, 480)
        self.etable.set_context(lambda r: [("Open", self._enter), ("Show in Files", lambda rr: open_path(os.path.dirname(rr["_e"].path))),
                                           ("Move to Trash…", lambda rr: self.trash([rr["_e"].path], rr["_e"].size, after=lambda: self.go(self.path)))],
                                "folder")
        self.treemap = Treemap(480, on_click=self._map_click)
        self.estack = Gtk.Stack()
        self.estack.add_named(self.etable, "list")
        self.estack.add_named(self.treemap, "map")
        self.explore.append(self.estack)
        self.explore.append(flow(label("Double-click a folder to open it. Sizes include everything inside.", "dim", wrap=True, hexpand=True),
                                 button("Show in Files", css="flat", on_click=self._reveal),
                                 button("Move to Trash…", icon="user-trash-symbolic", css="destructive-action", on_click=self._trash_sel), spacing=8, max_per_line=3))

    def _view_toggle(self) -> Gtk.Box:
        lst = Gtk.ToggleButton(icon_name="view-list-symbolic", tooltip_text="List", active=True)
        mp = Gtk.ToggleButton(icon_name="view-grid-symbolic", tooltip_text="Map: boxes sized by how much space they take")
        mp.set_group(lst)
        lst.connect("toggled", lambda b: b.get_active() and self.estack.set_visible_child_name("list"))
        mp.connect("toggled", lambda b: b.get_active() and self.estack.set_visible_child_name("map"))
        box = hbox(lst, mp, spacing=0)
        box.add_css_class("linked")
        return box

    def _map_click(self, path: str) -> None:
        if os.path.isdir(path) and not os.path.islink(path):
            self.go(path)
        else:
            open_path(os.path.dirname(path))

    def go(self, path: str, push: bool = True) -> None:
        if push and path != self.path:
            self.history.append(self.path)
        self.path = path
        self.crumb.set_text(short(path))
        self.explore_total.set_text("measuring…")
        self.etable.set_rows([])
        self.etable.set_empty("Measuring folder sizes… big folders take a moment.")
        self.bg(lambda: storage.children(path, timeout=240), lambda r: self.show_explore(path, r))

    def back(self) -> None:
        if self.history:
            self.go(self.history.pop(), push=False)

    def show_explore(self, path: str, res) -> None:
        if path != self.path:
            return
        total, items = res
        self.explore_total.set_text(f"{human(total)} · {len(items)} items")
        rows = []
        for e in items:
            rows.append({"key": e.path, "name": f"{'<b>' if e.is_dir else ''}{esc(e.name)}{'/</b>' if e.is_dir else ''}", "size": e.size,
                         "share": e.size / total if total else 0, "hint": storage.hint_for(e.path), "_e": e})
        self.etable.set_rows(rows)
        self.etable.set_empty("Empty folder (or no permission to look inside).")
        self.treemap.set_items([(e.name + ("/" if e.is_dir else ""), e.size, e.path, storage.hint_for(e.path)) for e in items])

    def _enter(self, row: dict) -> None:
        e = row["_e"]
        if e.is_dir:
            self.go(e.path)
        else:
            open_path(os.path.dirname(e.path))

    def _reveal(self) -> None:
        r = self.etable.selected()
        open_path(os.path.dirname(r["_e"].path) if r else self.path)

    def _trash_sel(self) -> None:
        r = self.etable.selected()
        if not r:
            self.toast("Select something first.")
            return
        self.trash([r["_e"].path], r["_e"].size, after=lambda: self.go(self.path))

    def trash(self, paths: list[str], size: int, after=None) -> None:
        bad = [p for p in paths if not p.startswith(str(HOME) + "/") or p.rstrip("/") in {str(HOME / d) for d in ("Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music", ".config", ".local", ".ssh")}]
        if bad:
            self.toast("Only files and folders inside your home folder can be trashed from here (and not whole standard folders).", 5)
            return
        names = ", ".join(os.path.basename(p) for p in paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        self.run("Move to Trash", [Step(f"Move {len(paths)} item{'s' if len(paths) != 1 else ''} to Trash", ["gio", "trash", "--", *paths])],
                 f"{names} ({human(size)}). You can restore from the Trash until you empty it.", danger=True, ok_label="Move to Trash",
                 reload=False, done=lambda ok: ok and after and after())

    # ---------------------------------------------------------------- big files
    def _build_big(self) -> None:
        self.min_dd = Gtk.DropDown.new_from_strings(["Over 100 MB", "Over 250 MB", "Over 500 MB", "Over 1 GB", "Over 4 GB"])
        self.min_dd.set_selected(1)
        self.min_dd.connect("notify::selected", lambda *_: self.find_big())
        self.big_status = label("", "dim", hexpand=True)
        self.big.append(flow(self.min_dd, self.big_status, button("Search again", icon="view-refresh-symbolic", on_click=self.find_big), spacing=8, max_per_line=3))
        self.btable = DataTable([
            Column("name", "File", "bold", width=280),
            Column("size", "Size", "size", width=100),
            Column("age", "Last changed", "muted", width=130, sort="mtime"),
            Column("folder", "Folder", "mono", expand=True),
        ], on_activate=lambda r: open_path(os.path.dirname(r["key"])), empty="No big files found.", sort="size")
        self.btable.set_size_request(-1, 460)
        self.big.append(self.btable)
        self.big.append(flow(label("Only your home folder is searched. Double-click opens the folder.", "dim", wrap=True, hexpand=True),
                             button("Open file", css="flat", on_click=lambda: self._b(lambda r: open_path(r["key"]))),
                             button("Show in Files", css="flat", on_click=lambda: self._b(lambda r: open_path(os.path.dirname(r["key"])))),
                             button("Move to Trash…", icon="user-trash-symbolic", css="destructive-action",
                                    on_click=lambda: self._b(lambda r: self.trash([r["key"]], r["size"], after=self.find_big))),
                             spacing=8, max_per_line=4))

    def _b(self, fn) -> None:
        r = self.btable.selected()
        if r:
            fn(r)
        else:
            self.toast("Select a file first.")

    def find_big(self) -> None:
        mb = [100, 250, 500, 1024, 4096][self.min_dd.get_selected()]
        self.big_status.set_text("Searching your home folder…")
        self.btable.set_rows([])
        self.btable.set_empty("Searching…")

        def work():
            items = storage.big_files(HOME, min_mb=mb, limit=300)
            return [(e, os.path.getmtime(e.path) if os.path.exists(e.path) else 0) for e in items]
        self.bg(work, self.show_big)

    def show_big(self, items) -> None:
        rows = [{"key": e.path, "name": e.name, "size": e.size, "mtime": mt, "age": ago(mt) if mt else "", "folder": short(os.path.dirname(e.path))}
                for e, mt in items]
        self.btable.set_rows(rows)
        self.btable.set_empty("No files that big. Nice.")
        self.big_status.set_text(f"{len(rows)} files · {human(sum(r['size'] for r in rows))}")

    # ---------------------------------------------------------------- duplicates
    def _build_dups(self) -> None:
        self.dup_checks: dict[str, Gtk.CheckButton] = {}
        boxes = []
        for d in DUPE_ROOTS:
            cb = Gtk.CheckButton(label=d, active=(HOME / d).is_dir())
            cb.set_sensitive((HOME / d).is_dir())
            self.dup_checks[d] = cb
            boxes.append(cb)
        self.dup_min = Gtk.DropDown.new_from_strings(["Files over 100 KB", "Files over 1 MB", "Files over 10 MB"])
        self.dup_min.set_selected(1)
        self.dup_btn = button("Find duplicates", icon="system-search-symbolic", css="suggested-action", on_click=self.find_dups)
        self.sim_btn = button("Find similar photos", icon="image-x-generic-symbolic", tooltip="Resized, re-saved or re-sent copies of the same photo",
                              on_click=self.find_similar)
        self.empty_btn = button("Empty folders & files", icon="folder-symbolic", on_click=self.find_empty)
        self.dups.append(card(label("Duplicates: files with exactly the same content (compared byte for byte, not by name); the oldest copy is kept. "
                                    "Similar photos: the same picture resized or re-saved (WhatsApp/Telegram copies, edits); the biggest is kept.",
                                    "dim", wrap=True),
                              flow(*boxes, spacing=14, min_per_line=2), flow(self.dup_min, self.empty_btn, self.sim_btn, self.dup_btn, spacing=8, max_per_line=4),
                              title="Where to look"))
        self.dup_status = label("", "subtle", wrap=True)
        self.dups.append(self.dup_status)
        self.dup_list = vbox(spacing=10)
        self.dups.append(self.dup_list)
        self.dup_sel: dict[str, tuple[Gtk.CheckButton, int]] = {}
        self.dup_groups: list[list[str]] = []
        self.dup_mode = "exact"

    def _dup_roots(self) -> list:
        return [HOME / d for d, cb in self.dup_checks.items() if cb.get_active()]

    def find_similar(self) -> None:
        roots = self._dup_roots()
        if not roots:
            self.toast("Tick at least one folder.")
            return
        self.dup_mode = "similar"
        self.sim_btn.set_sensitive(False)
        self.dup_status.set_text("Comparing photos by what they look like…")
        clear(self.dup_list)
        t0 = time.time()

        def done(groups) -> None:
            self.sim_btn.set_sensitive(True)
            self.show_dups(groups, time.time() - t0)
            if groups:
                self.dup_status.set_text(self.dup_status.get_text().replace("identical files", "similar photos") +
                                         " Check them before deleting: “similar” can also mean a burst of nearly identical shots.")
        self.bg(lambda: drives.similar_images(roots, progress=lambda m: idle(self.dup_status.set_text, f"Looking at photos: {m}…")), done)

    def find_empty(self) -> None:
        roots = self._dup_roots()
        if not roots:
            self.toast("Tick at least one folder.")
            return
        self.dup_status.set_text("Looking for empty folders and files…")

        def done(res) -> None:
            items = [(p, short(p) + "/", "empty folder", True) for p in res["dirs"]] + [(p, short(p), "empty file (0 bytes)", True) for p in res["files"]]
            if not items:
                self.dup_status.set_text("No empty folders or files.")
                return
            self.dup_status.set_text(f"{len(res['dirs'])} empty folders and {len(res['files'])} empty files.")
            from ..dialogs import PickDialog

            def picked(keys) -> None:
                if keys:
                    self.run("Move empty items to Trash", [Step(f"Move {len(keys)} empty items to Trash", ["gio", "trash", "--", *keys])],
                             "They take no space, but clutter your folders. You can restore them from the Trash.", ok_label="Move to Trash",
                             reload=False)
            PickDialog("Empty folders and files", "Ticked items go to the Trash.", items, picked).present(self.win)
        self.bg(lambda: drives.empty_things(roots), done)

    def find_dups(self) -> None:
        self.dup_mode = "exact"
        roots = [HOME / d for d, cb in self.dup_checks.items() if cb.get_active()]
        if not roots:
            self.toast("Tick at least one folder.")
            return
        min_size = [100 * 1024, 1024 ** 2, 10 * 1024 ** 2][self.dup_min.get_selected()]
        self.dup_btn.set_sensitive(False)
        self.dup_status.set_text("Looking for identical files…")
        clear(self.dup_list)
        t0 = time.time()

        def progress(msg: str) -> None:
            idle(self.dup_status.set_text, f"Comparing files: {msg}…")
        self.bg(lambda: dupes.find_duplicates(roots, min_size=min_size, progress=progress), lambda g: self.show_dups(g, time.time() - t0))

    def show_dups(self, groups: list[list[dict]], secs: float) -> None:
        self.dup_btn.set_sensitive(True)
        clear(self.dup_list)
        self.dup_sel = {}
        self.dup_groups = [[f["path"] for f in g] for g in groups[:400]]
        if not groups:
            self.dup_status.set_text(f"No duplicates found ({secs:.1f}s).")
            return
        wasted = sum(g[0]["size"] * (len(g) - 1) for g in groups)
        self.dup_total = label("", "mid-num")
        trash_btn = button("Move ticked copies to Trash…", icon="user-trash-symbolic", css="destructive-action", on_click=self.trash_dups)
        self.dup_list.append(flow(self.dup_total, button("Tick all copies", css="flat", on_click=lambda: self._tick_dups(True)),
                                   button("Untick all", css="flat", on_click=lambda: self._tick_dups(False)), trash_btn,
                                   min_per_line=1, max_per_line=4, column_spacing=8, row_spacing=8))
        self.dup_status.set_text(f"{len(groups)} sets of identical files, {human(wasted)} of extra copies ({secs:.1f}s).")
        lb = boxed_list()
        for g in groups[:400]:
            first = g[0]
            row = Adw.ExpanderRow(title=esc(os.path.basename(first["path"])),
                                  subtitle=esc(f"{len(g)} copies · {human(first['size'])} each · {human(first['size'] * (len(g) - 1))} extra"))
            for n, f in enumerate(g):
                r = Adw.ActionRow(title=esc(short(f["path"])), subtitle=esc(f"changed {ago(f['mtime'])}"))
                r.set_title_lines(1)
                cb = Gtk.CheckButton(active=n > 0)
                cb.set_valign(Gtk.Align.CENTER)
                cb.connect("toggled", lambda *_: self._dup_total())
                r.add_prefix(cb)
                r.set_activatable_widget(cb)
                if n == 0:
                    r.add_suffix(pill("oldest" if self.dup_mode == "exact" else "biggest", "ok"))
                openb = button(icon="folder-open-symbolic", css="flat", tooltip="Show in Files", on_click=lambda p=f["path"]: open_path(os.path.dirname(p)))
                openb.set_valign(Gtk.Align.CENTER)
                r.add_suffix(openb)
                row.add_row(r)
                self.dup_sel[f["path"]] = (cb, f["size"])
            lb.append(row)
        self.dup_list.append(lb)
        self._dup_total()

    def _tick_dups(self, on: bool) -> None:
        """Tick every copy except the oldest of each set (or untick everything)."""
        for paths in self.dup_groups:
            for n, p in enumerate(paths):
                self.dup_sel[p][0].set_active(on and n > 0)
        self._dup_total()

    def _dup_total(self) -> None:
        chosen = [(p, s) for p, (cb, s) in self.dup_sel.items() if cb.get_active()]
        self.dup_total.set_text(f"{len(chosen)} ticked · {human(sum(s for _, s in chosen))}")

    def trash_dups(self) -> None:
        chosen = [(p, s) for p, (cb, s) in self.dup_sel.items() if cb.get_active()]
        if not chosen:
            self.toast("Tick some copies first.")
            return
        self.trash([p for p, _ in chosen], sum(s for _, s in chosen), after=self.find_dups)


    # ---------------------------------------------------------------- trash
    def _build_trash(self) -> None:
        self.trash_status = label("", "subtle", hexpand=True)
        self.trash_box.append(flow(self.trash_status,
                                    button("Restore", icon="edit-undo-symbolic", on_click=lambda: self._t(self.restore)),
                                    button("Delete for good…", css="destructive-action", on_click=lambda: self._t(lambda r: self.delete_forever([r]))),
                                    button("Empty Trash…", icon="user-trash-full-symbolic", on_click=self.empty_trash),
                                    min_per_line=1, max_per_line=4, column_spacing=6, row_spacing=6))
        self.ttable = DataTable([
            Column("name", "Name", "bold", width=240),
            Column("size", "Size", "size", width=90),
            Column("when", "Deleted", "muted", width=120, sort="deleted"),
            Column("orig", "Came from", "mono", expand=True),
        ], on_activate=self.restore, empty="The Trash is empty.", sort="deleted")
        self.ttable.set_size_request(-1, 460)
        self.ttable.set_context(lambda r: [("Restore", self.restore), ("Delete for good…", lambda rr: self.delete_forever([rr]))], "trash")
        self.trash_box.append(self.ttable)
        self.trash_box.append(label("Double-click to put something back where it was. Trash on USB drives is listed in Cleanup.", "dim", wrap=True))

    def _t(self, fn) -> None:
        r = self.ttable.selected()
        if r:
            fn(r)
        else:
            self.toast("Select something first.")

    def load_trash(self) -> None:
        self.ttable.set_empty("Looking in the Trash…")
        self.bg(drives.trash_items, self.show_trash)

    def show_trash(self, items: list[dict]) -> None:
        self.trash_items = items
        rows = [{"key": it["path"], "name": it["name"] + ("/" if it["is_dir"] else ""), "size": it["size"], "deleted": it["deleted"],
                 "when": ago(it["deleted"]) if it["deleted"] else "", "orig": short(it["original"]), "_it": it} for it in items]
        self.ttable.set_rows(rows)
        self.ttable.set_empty("The Trash is empty.")
        self.trash_status.set_text(f"{len(items)} items · {human(sum(i['size'] for i in items))}" if items else "The Trash is empty.")

    def restore(self, r: dict) -> None:
        try:
            dest = drives.restore_trash(r["_it"])
            self.toast(f"Restored to {short(dest)}")
        except OSError as e:
            self.toast(f"Couldn't restore: {e}")
        self.load_trash()

    def delete_forever(self, rows: list[dict]) -> None:
        items = [r["_it"] for r in rows]
        self.run("Delete for good", drives.delete_trash_steps(items), ", ".join(i["name"] for i in items[:5]) + " - this can't be undone.",
                 danger=True, ok_label="Delete", reload=False, done=lambda ok: self.load_trash())

    def empty_trash(self) -> None:
        items = getattr(self, "trash_items", [])
        if not items:
            self.toast("The Trash is already empty.")
            return
        self.run("Empty the Trash", drives.delete_trash_steps(items), f"{len(items)} items, {human(sum(i['size'] for i in items))}. "
                 "This can't be undone.", danger=True, ok_label="Empty Trash", reload=False, done=lambda ok: self.load_trash())

    # ---------------------------------------------------------------- file types
    def _build_types(self) -> None:
        self.types_status = label("See what kind of files fill your home folder: videos, photos, music, documents, installers, code. "
                                  "Apps, caches and code dependencies are skipped.", "dim", wrap=True, hexpand=True)
        self.types_btn = button("Analyse", icon="system-search-symbolic", css="suggested-action", on_click=self.analyse_types)
        self.types_box.append(flow(self.types_status, self.types_btn, min_per_line=1, max_per_line=2, column_spacing=8, row_spacing=8))
        self.types_result = vbox(spacing=14)
        self.types_box.append(self.types_result)

    def analyse_types(self) -> None:
        self.types_btn.set_sensitive(False)
        self.loading(self.types_result, "Looking through your files…")
        self.bg(lambda: drives.file_types(HOME, progress=lambda m: idle(self.types_status.set_text, m)), self.show_types)

    def show_types(self, res: dict) -> None:
        self.types_btn.set_sensitive(True)
        clear(self.types_result)
        types = sorted(res["types"].items(), key=lambda kv: -kv[1]["size"])
        total = sum(v["size"] for _, v in types)
        self.types_status.set_text(f"{res['files']:,} files, {human(total)}" + (" (stopped early: very large folder)" if res["partial"] else "") + ".")
        bars = HBars("blue", row=28, label_width=200)
        bars.set_items([(f"{k}  ·  {v['count']:,} files", v["size"], human(v["size"])) for k, v in types if v["size"]])
        self.types_result.append(card(bars, title="By kind"))
        rows = [{"key": e, "ext": "." + e if e != "(none)" else e, "size": sz, "count": n} for e, sz, n in res["exts"]]
        t = DataTable([Column("ext", "Extension", "bold", width=160), Column("count", "Files", "num", width=90),
                       Column("size", "Size", "size", expand=True)], sort="size")
        t.set_rows(rows)
        t.set_size_request(-1, 320)
        self.types_result.append(label("Biggest file types", "section-title"))
        self.types_result.append(t)
        self.types_result.append(flow(label("Find the actual files on the Big files tab.", "dim", wrap=True, hexpand=True),
                                       button("Big files", css="flat", on_click=lambda: self.stack.set_visible_child_name("big")),
                                       min_per_line=1, max_per_line=2, column_spacing=8, row_spacing=8))


PAGE = StoragePage
