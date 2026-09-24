"""Storage: disks and their health, a folder explorer by size, big files, and duplicate finder."""

from __future__ import annotations

import os
import time

from gi.repository import Adw, Gtk

from ...core import dupes, storage, system
from ...core.fmt import ago, human
from ...core.run import HOME, Step, has
from ..util import button, clear, esc, hbox, idle, label, open_path, pill, spacer, vbox
from ..widgets import Column, DataTable, HBars, MiniBar, card
from .base import Page, action_row, boxed_list, group, tabs

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
        sw, self.stack = tabs(("overview", "Disks", "drive-harddisk-symbolic", self.overview),
                              ("explore", "Explore folders", "folder-open-symbolic", self.explore),
                              ("big", "Big files", "zoom-in-symbolic", self.big),
                              ("dups", "Duplicates", "edit-copy-symbolic", self.dups))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_explore()
        self._build_big()
        self._build_dups()

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"overview": self.load_overview, "explore": lambda: self.go(self.path), "big": self.find_big, "dups": lambda: None}[name]()

    # ---------------------------------------------------------------- overview
    def load_overview(self) -> None:
        self.loading(self.overview, "Measuring disks…")

        def work():
            return system.mounts(), system.physical_disks(), storage.children(HOME, timeout=120)
        self.bg(work, self.show_overview)

    def show_overview(self, res) -> None:
        mounts, disks, (home_total, home_items) = res
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

        # physical disks
        rows = []
        for d in disks:
            dev = f"/dev/{d['name']}"
            rows.append(action_row(f"{d['model'] or d['name']}", f"{human(d['size'])} {d['kind']}" + (f" · {d['bus']}" if d['bus'] else "") + f" · {dev}",
                                   button("Check health", css="flat", on_click=lambda dv=dev: self.smart(dv)),
                                   prefix=Gtk.Image.new_from_icon_name("drive-harddisk-solidstate-symbolic" if "SSD" in d["kind"] else "drive-harddisk-symbolic")))
        if rows:
            self.overview.append(group("Drives", "Physical drives in this PC. Health reads the drive's own SMART report (wear, errors, temperature).", *rows))
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
        steps = []
        if not has("smartctl"):
            steps.append(Step("Install smartmontools", ["apt-get", "install", "-y", "smartmontools"], root=True, env={"DEBIAN_FRONTEND": "noninteractive"}))
        steps.append(Step(f"Health report for {dev}", ["smartctl", "-H", "-A", "-i", dev], root=True, ok_codes=tuple(range(0, 256))))
        self.run(f"Check drive health ({dev})", steps, "Reads the drive's built-in health report. Look for “PASSED”, and on NVMe drives "
                 "“Percentage Used” (wear; under 80% is fine).", ok_label="Check", reload=False)

    # ---------------------------------------------------------------- explore
    def _build_explore(self) -> None:
        self.path = str(HOME)
        self.history: list[str] = []
        self.crumb = label("", ["heading", "mono"], ellipsize=True, hexpand=True)
        self.explore_total = label("", "dim")
        self.explore.append(hbox(
            button(icon="go-previous-symbolic", tooltip="Back", on_click=self.back),
            button(icon="go-up-symbolic", tooltip="Up one folder", on_click=lambda: self.go(os.path.dirname(self.path.rstrip("/")) or "/")),
            button(icon="user-home-symbolic", tooltip="Home folder", on_click=lambda: self.go(str(HOME))),
            button("/", tooltip="Whole disk (some folders need admin rights to measure)", on_click=lambda: self.go("/")),
            self.crumb, self.explore_total,
            button("Open in Files", icon="folder-open-symbolic", on_click=lambda: open_path(self.path)), spacing=6))
        self.etable = DataTable([
            Column("name", "Name", "markup", expand=True),
            Column("share", "Share", "bar", width=150, fmt=lambda v, d: f"{(v or 0) * 100:.0f}%"),
            Column("size", "Size", "size", width=100),
            Column("hint", "What it is", "muted", expand=True),
        ], on_activate=self._enter, empty="Empty folder.", sort="size")
        self.etable.set_size_request(-1, 480)
        self.explore.append(self.etable)
        self.explore.append(hbox(label("Double-click a folder to open it. Sizes include everything inside.", "dim", hexpand=True),
                                 button("Show in Files", css="flat", on_click=self._reveal),
                                 button("Move to Trash…", icon="user-trash-symbolic", css="destructive-action", on_click=self._trash_sel)))

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
        self.big.append(hbox(self.min_dd, self.big_status, button("Search again", icon="view-refresh-symbolic", on_click=self.find_big)))
        self.btable = DataTable([
            Column("name", "File", "bold", width=280),
            Column("size", "Size", "size", width=100),
            Column("age", "Last changed", "muted", width=130, sort="mtime"),
            Column("folder", "Folder", "mono", expand=True),
        ], on_activate=lambda r: open_path(os.path.dirname(r["key"])), empty="No big files found.", sort="size")
        self.btable.set_size_request(-1, 460)
        self.big.append(self.btable)
        self.big.append(hbox(label("Only your home folder is searched. Double-click opens the folder.", "dim", hexpand=True),
                             button("Open file", css="flat", on_click=lambda: self._b(lambda r: open_path(r["key"]))),
                             button("Show in Files", css="flat", on_click=lambda: self._b(lambda r: open_path(os.path.dirname(r["key"])))),
                             button("Move to Trash…", icon="user-trash-symbolic", css="destructive-action",
                                    on_click=lambda: self._b(lambda r: self.trash([r["key"]], r["size"], after=self.find_big)))))

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
        self.dups.append(card(label("Finds files with exactly the same content (compared byte for byte by hash, not by name). The oldest copy is kept; "
                                    "the others are ticked for the Trash.", "dim", wrap=True),
                              hbox(*boxes, spacing=14), hbox(self.dup_min, spacer(), self.dup_btn), title="Where to look"))
        self.dup_status = label("", "subtle", wrap=True)
        self.dups.append(self.dup_status)
        self.dup_list = vbox(spacing=10)
        self.dups.append(self.dup_list)
        self.dup_sel: dict[str, tuple[Gtk.CheckButton, int]] = {}
        self.dup_groups: list[list[str]] = []

    def find_dups(self) -> None:
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
        self.dup_list.append(hbox(self.dup_total, spacer(), button("Tick all copies", css="flat", on_click=lambda: self._tick_dups(True)),
                                  button("Untick all", css="flat", on_click=lambda: self._tick_dups(False)), trash_btn))
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
                    r.add_suffix(pill("oldest", "ok"))
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


PAGE = StoragePage
