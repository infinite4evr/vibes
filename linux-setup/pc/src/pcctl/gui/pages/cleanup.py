"""Cleanup: ~40 kinds of junk, grouped, with per-item choice, live totals and the exact commands."""

from __future__ import annotations

import json
import os
import time

from gi.repository import Adw, Gtk

from ...core import junk
from ...core.fmt import ago, human
from ...core.run import HOME, Step
from ..util import button, clear, esc, hbox, idle, label, pill, vbox
from ..widgets import HBars, card
from .. import prefs, theme
from .base import Page, action_row, group

HISTORY = HOME / ".local/state/pc/cleanup-history.json"
ALL = "__all__"
GROUP_ICONS = {"System": "computer-symbolic", "Developer": "utilities-terminal-symbolic", "Apps & browsers": "web-browser-symbolic",
               "Your files": "folder-symbolic", "Privacy": "security-medium-symbolic"}


def _history() -> list[dict]:
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return []


def _free_space() -> int:
    """Free bytes on / plus /home when it's a separate disk: measured before and after a cleanup."""
    seen, total = set(), 0
    for p in ("/", str(HOME)):
        try:
            st = os.statvfs(p)
        except OSError:
            continue
        if st.f_fsid in seen:
            continue
        seen.add(st.f_fsid)
        total += st.f_bavail * st.f_frsize
    return total


def _save_history(freed: int, what: list[str], measured: int | None = None) -> None:
    h = _history()[-49:]
    h.append({"ts": time.time(), "freed": freed, "what": what, "measured": measured})
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(h))
    except OSError:
        pass


def selectable(j: junk.Junk) -> bool:
    return bool(j.items) and j.make_steps is not None


class CleanupPage(Page):
    ID = "cleanup"
    TITLE = "Cleanup"
    ICON = "edit-clear-all-symbolic"
    SUBTITLE = "Caches, leftovers, old logs, unused packages, duplicates and more. Nothing is removed until you confirm."

    def build(self) -> None:
        self.deep = False
        self.scanning = False
        self.junks: list[junk.Junk] = []
        self.checked: dict[str, set[str]] = {}
        self.cat_checks: dict[str, Gtk.CheckButton] = {}
        self.item_checks: dict[str, dict[str, Gtk.CheckButton]] = {}
        self._sync = False

        self.quick_btn = button("Quick scan", icon="view-refresh-symbolic", on_click=lambda: self.scan(False))
        self.deep_btn = button("Deep scan", icon="system-search-symbolic", tooltip="Also looks through your projects, old runtimes, "
                               "old downloads and duplicate files", on_click=lambda: self.scan(True))
        self.header(None, self.quick_btn, self.deep_btn)

        # summary hero
        self.total = label("…", "clean-total")
        self.total_sub = label("Scanning your PC…", "subtle", wrap=True)
        self.sel_label = label("", "mid-num")
        self.spinner = Gtk.Spinner()
        self.clean_btn = button("Clean selected", icon="user-trash-symbolic", css=["suggested-action", "pill"], on_click=self.clean)
        self.clean_btn.set_sensitive(False)
        rec = button("Recommended", css="flat", tooltip="Tick only the safe, recommended items", on_click=self.select_recommended)
        none = button("None", css="flat", on_click=self.select_none)
        left = vbox(hbox(self.total, self.spinner, spacing=12), self.total_sub, spacing=2)
        left.set_hexpand(True)
        right = vbox(self.sel_label, hbox(rec, none, self.clean_btn, spacing=6), spacing=6)
        right.set_valign(Gtk.Align.CENTER)
        self.sel_label.set_xalign(1)
        self.bars = HBars("green", row=22, label_width=150)
        self.bars.set_visible(False)
        self.history_label = label("", "dim", wrap=True)
        self.history_label.set_hexpand(True)
        hist = hbox(self.history_label, button("History", icon="document-open-recent-symbolic", css="flat", on_click=self.show_history))
        hero = card(hbox(left, right, spacing=18), self.bars, hist, spacing=12)
        hero.add_css_class("hero")
        self.body.append(hero)

        self.deep_hint = label("Tip: Deep scan also finds old node_modules, build folders, virtualenvs, unused Node/Python versions, "
                               "old downloads and duplicate files.", "dim", wrap=True)
        self.body.append(self.deep_hint)
        self.groups_box = vbox(spacing=22)
        self.body.append(self.groups_box)

        auto = action_row("Clean automatically every week", "Safe caches only (no password needed). Set it up in Maintenance.",
                          button("Set up", css="flat", on_click=lambda: self.win.goto("maintenance")),
                          prefix=Gtk.Image.new_from_icon_name("alarm-symbolic"))
        self.body.append(group("Keep it clean", "", auto))
        self.body.append(label("Safe by design: your documents, photos and project source code are never touched. Removals are limited to "
                               "your home and temp folders, package managers do the rest, and every command is shown before it runs.",
                               "dim", wrap=True))

    # ---------------------------------------------------------------- scanning
    def load(self) -> None:
        self.scan(self.deep)

    def scan(self, deep: bool) -> None:
        if self.scanning:
            return
        self.deep = deep
        self.scanning = True
        self.spinner.start()
        self.quick_btn.set_sensitive(False)
        self.deep_btn.set_sensitive(False)
        self.clean_btn.set_sensitive(False)
        self.total.set_text("…")
        self.total_sub.set_text("Deep scan: walking your projects and downloads, this can take a minute…" if deep else "Scanning 35 places…")
        self.found = [0, 0]

        def found(j: junk.Junk) -> None:
            self.found[0] += 1
            self.found[1] += j.size or 0
            idle(self.total_sub.set_text, f"Scanning… found {self.found[0]} things so far ({human(self.found[1])})")

        self.bg(lambda: junk.scan(deep=deep, on_result=found), self.show)

    def show(self, res: list[junk.Junk]) -> None:
        self.scanning = False
        self.spinner.stop()
        self.quick_btn.set_sensitive(True)
        self.deep_btn.set_sensitive(True)
        self.junks = res
        self.checked = {}
        for j in res:
            if selectable(j):
                self.checked[j.id] = {i.key for i in j.items if i.default} if (j.default and not j.pick) else set()
            else:
                self.checked[j.id] = {ALL} if (j.default and not j.pick) else set()
        self.render()
        self.update_totals()
        self.deep_hint.set_visible(not self.deep)

    # ---------------------------------------------------------------- rendering
    def render(self) -> None:
        clear(self.groups_box)
        self.cat_checks, self.item_checks = {}, {}
        found = sum(j.size or 0 for j in self.junks)
        self.total.set_text(human(found) if found else "All clean")
        self.total_sub.set_text(f"can be freed across {len(self.junks)} places" + (" (deep scan)" if self.deep else "")
                                if self.junks else "Nothing worth cleaning right now.")
        by_group: dict[str, list[junk.Junk]] = {}
        for j in self.junks:
            by_group.setdefault(j.group, []).append(j)
        items = [(g, sum(j.size or 0 for j in js), human(sum(j.size or 0 for j in js))) for g, js in by_group.items()]
        self.bars.set_items(sorted(items, key=lambda x: -x[1]))
        self.bars.set_visible(bool(items))
        for g in junk.GROUPS:
            js = by_group.get(g)
            if not js:
                continue
            size = sum(j.size or 0 for j in js)
            pg = Adw.PreferencesGroup(title=esc(g), description=f"{human(size)} in {len(js)} place{'s' if len(js) != 1 else ''}")
            icon = Gtk.Image.new_from_icon_name(GROUP_ICONS.get(g, "folder-symbolic"))
            icon.add_css_class("dim")
            pg.set_header_suffix(icon)
            for j in js:
                pg.add(self._row(j))
            self.groups_box.append(pg)
        h = _history()
        if h:
            last = h[-1]
            self.history_label.set_text(f"Last cleanup {ago(last['ts'])}: freed about {human(last['freed'])}. "
                                        f"Total freed with PC Command Center: {human(sum(x['freed'] for x in h))}.")
        else:
            self.history_label.set_text("")
        self.win.set_badge("cleanup", 0, text=human(found).replace(" ", "") if found > 1024 ** 3 else None)

    def _row(self, j: junk.Junk) -> Gtk.Widget:
        size_text = "?" if j.size is None else (human(j.size) if j.size else "")
        sub = esc(j.desc)
        if j.warn:
            sub += "\n" + theme.span("peach", esc(j.warn))
        cb = Gtk.CheckButton()
        cb.set_valign(Gtk.Align.CENTER)
        cb.connect("toggled", self._cat_toggled, j)
        self.cat_checks[j.id] = cb
        size = label(size_text, ["heading", "warn-text" if (j.size or 0) > 1024 ** 3 else "subtle"])
        size.set_valign(Gtk.Align.CENTER)
        tags = []
        if j.root:
            tags.append(pill("admin", "info"))
        if j.pick:
            tags.append(pill("you choose", "accent"))
        if j.deep:
            tags.append(pill("deep", "neutral"))
        only = button(icon="user-trash-symbolic", css="flat", tooltip="Clean just this", on_click=lambda jj=j: self.clean([jj]))
        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="More")
        more.add_css_class("flat")
        pop = Gtk.Popover()
        mbox = vbox(spacing=2)
        for text, fn in (("Show exactly what would run", lambda jj=j: self.show_commands(jj)),
                         ("Clean just this", lambda jj=j: self.clean([jj])),
                         ("Never clean this category", lambda jj=j: self.exclude(jj.id, jj.title))):
            b = Gtk.Button(label=text)
            b.add_css_class("flat")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, f=fn, p=pop: (p.popdown(), f()))
            mbox.append(b)
        pop.set_child(mbox)
        more.set_popover(pop)
        # one box, so the order is the same on every libadwaita version
        suffix = hbox(*tags, size, only, more, spacing=6)
        suffix.set_valign(Gtk.Align.CENTER)

        if j.items:
            row = Adw.ExpanderRow(title=esc(j.title), subtitle=sub)
            row.set_subtitle_lines(3)
            row.add_prefix(cb)
            row.add_suffix(suffix)
            self.item_checks[j.id] = {}
            items = sorted(j.items, key=lambda i: -i.size)
            for it in items[:300]:
                ir = Adw.ActionRow(title=esc(it.label), subtitle=esc(it.note))
                ir.set_title_lines(1)
                ir.set_tooltip_text(it.label)
                if selectable(j):
                    icb = Gtk.CheckButton(active=it.key in self.checked[j.id])
                    icb.set_valign(Gtk.Align.CENTER)
                    icb.connect("toggled", self._item_toggled, j, it.key)
                    ir.add_prefix(icb)
                    ir.set_activatable_widget(icb)
                    self.item_checks[j.id][it.key] = icb
                if it.size:
                    ir.add_suffix(label(human(it.size), "dim"))
                if selectable(j):
                    nb = button(icon="action-unavailable-symbolic", css="flat", tooltip="Never clean this item",
                                on_click=lambda jj=j, ii=it: self.exclude(f"{jj.id}|{ii.key}", ii.label))
                    nb.set_valign(Gtk.Align.CENTER)
                    ir.add_suffix(nb)
                row.add_row(ir)
            if len(items) > 300:
                row.add_row(Adw.ActionRow(title=f"… and {len(items) - 300} more (use the category box to include them)"))
        else:
            row = Adw.ActionRow(title=esc(j.title), subtitle=sub)
            row.set_subtitle_lines(3)
            row.add_prefix(cb)
            row.set_activatable_widget(cb)
            row.add_suffix(suffix)
        self._sync_cat(j)
        return row

    # ---------------------------------------------------------------- selection
    def _cat_toggled(self, cb: Gtk.CheckButton, j: junk.Junk) -> None:
        if self._sync:
            return
        on = cb.get_active()
        cb.set_inconsistent(False)
        if selectable(j):
            self.checked[j.id] = {i.key for i in j.items} if on else set()
            self._sync = True
            for key, icb in self.item_checks.get(j.id, {}).items():
                icb.set_active(on)
            self._sync = False
        else:
            self.checked[j.id] = {ALL} if on else set()
        self.update_totals()

    def _item_toggled(self, cb: Gtk.CheckButton, j: junk.Junk, key: str) -> None:
        if self._sync:
            return
        s = self.checked.setdefault(j.id, set())
        if cb.get_active():
            s.add(key)
        else:
            s.discard(key)
        self._sync_cat(j)
        self.update_totals()

    def _sync_cat(self, j: junk.Junk) -> None:
        cb = self.cat_checks.get(j.id)
        if cb is None:
            return
        chosen = self.checked.get(j.id, set())
        self._sync = True
        if selectable(j):
            n, total = len(chosen), len(j.items)
            cb.set_active(n > 0)
            cb.set_inconsistent(0 < n < total)
        else:
            cb.set_active(ALL in chosen)
            cb.set_inconsistent(False)
        self._sync = False

    def _set_all(self, fn) -> None:
        for j in self.junks:
            self.checked[j.id] = fn(j)
            self._sync = True
            for key, icb in self.item_checks.get(j.id, {}).items():
                icb.set_active(key in self.checked[j.id])
            self._sync = False
            self._sync_cat(j)
        self.update_totals()

    def select_recommended(self) -> None:
        def rec(j: junk.Junk) -> set[str]:
            if not j.default or j.pick:
                return set()
            return {i.key for i in j.items if i.default} if selectable(j) else {ALL}
        self._set_all(rec)

    def select_none(self) -> None:
        self._set_all(lambda j: set())

    def chosen(self, j: junk.Junk) -> list[str] | None:
        """None = whole category (no item choice); [] = nothing chosen."""
        c = self.checked.get(j.id, set())
        if selectable(j):
            return sorted(c)
        return None if ALL in c else []

    def size_chosen(self, j: junk.Junk) -> int:
        c = self.chosen(j)
        if c is None:
            return j.size or 0
        if not c:
            return 0
        return j.size_for(c)

    def update_totals(self) -> None:
        picked = [j for j in self.junks if self.chosen(j) != []]
        total = sum(self.size_chosen(j) for j in picked)
        self.sel_label.set_text(f"{human(total)} selected" if picked else "Nothing selected")
        self.clean_btn.set_sensitive(bool(picked) and not self.scanning)

    # ---------------------------------------------------------------- actions
    def steps_for(self, j: junk.Junk) -> list[Step]:
        c = self.chosen(j)
        if c == []:
            return []
        return j.steps_for(c)

    def show_commands(self, j: junk.Junk) -> None:
        c = self.chosen(j)
        steps = j.steps_for(c if c != [] else ([i.key for i in j.items] if selectable(j) else None))
        lines = [j.title, "", j.desc, ""]
        if j.warn:
            lines += ["Note: " + j.warn, ""]
        if j.items:
            lines.append(f"What's in it ({len(j.items)}):")
            for i in sorted(j.items, key=lambda i: -i.size)[:60]:
                lines.append(f"  {'[x]' if selectable(j) and i.key in self.checked.get(j.id, set()) else '[ ]' if selectable(j) else ' - '} "
                             f"{i.label}" + (f"   {human(i.size)}" if i.size else "") + (f"   ({i.note})" if i.note else ""))
            if len(j.items) > 60:
                lines.append(f"  … and {len(j.items) - 60} more")
            lines.append("")
        lines.append("Commands" + (" (for what is ticked)" if c != [] else " (if everything were ticked)") + ":")
        lines += [f"  $ {s.display()}" + ("   [admin]" if s.root else "") for s in steps] or ["  (nothing)"]
        self.text(j.title, "\n".join(lines))

    def exclude(self, key: str, name: str) -> None:
        junk.set_excluded(key, True)
        self.toast(f"“{name}” won't be offered again. Undo in Preferences → Cleanup.", 5)
        self.show([j for j in (junk.apply_exclusions(j) for j in self.junks) if j is not None])

    def show_history(self) -> None:
        h = _history()
        if not h:
            self.toast("No cleanups yet.")
            return
        lines = [f"{'When':<18} {'Estimated':>10} {'Measured':>10}  What", ""]
        for e in reversed(h):
            when = time.strftime("%d %b %Y %H:%M", time.localtime(e["ts"]))
            meas = human(e["measured"]) if e.get("measured") is not None else "-"
            lines.append(f"{when:<18} {human(e['freed']):>10} {meas:>10}  {', '.join(e['what'])[:110]}")
        lines += ["", f"Total: {human(sum(e['freed'] for e in h))} over {len(h)} cleanups."]
        self.text("Cleanup history", "\n".join(lines))

    def clean(self, only: list[junk.Junk] | None = None) -> None:
        targets = only if only is not None else self.junks
        steps: list[Step] = []
        titles, warns = [], []
        freed = 0
        for j in targets:
            if only is not None and self.chosen(j) == []:
                s = j.steps_for([i.key for i in j.items] if selectable(j) else None)
                size = j.size or 0
            else:
                s = self.steps_for(j)
                size = self.size_chosen(j)
            if not s:
                continue
            steps += s
            titles.append(j.title)
            freed += size
            if j.warn:
                warns.append(j.warn)
        if not steps:
            self.toast("Tick something to clean first.")
            return
        explain = f"About {human(freed)} from: " + ", ".join(titles) + "."
        if warns:
            explain += "\n\n" + " ".join(sorted(set(warns)))

        before = _free_space()

        def done(ok: bool) -> None:
            if ok:
                measured = max(0, _free_space() - before)
                _save_history(freed, titles, measured)
                self.toast(f"Freed {human(measured)} of disk space" if measured else f"Freed about {human(freed)}", 5)

        def go() -> None:
            self.run("Clean up" if only is None else f"Clean: {titles[0]}", steps, explain, ok_label="Clean", done=done,
                     danger=freed > big)
        big = int(prefs.get("big_delete_gb") or 10) * 1024 ** 3
        if freed > big:
            d = Adw.AlertDialog(heading=f"Delete {human(freed)}?", body="That's a lot at once. Make sure nothing in the list is something you "
                                "still need (expand the categories to check).")
            d.add_response("cancel", "Go back")
            d.add_response("ok", "Continue")
            d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            d.connect("response", lambda _d, r: r == "ok" and go())
            d.present(self.win)
        else:
            go()


PAGE = CleanupPage
