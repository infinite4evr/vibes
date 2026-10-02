"""Updates: apt + snap + flatpak in one list, security first; history with undo, drivers/firmware/kernels, software sources,
and update settings."""

from __future__ import annotations

import time
from pathlib import Path

from gi.repository import Adw, Gtk

from ...core import packages, security, system
from ...core.fmt import ago, human
from ...core.packages import APT_ENV
from ...core.run import Step, has, out
from .. import prefs, theme
from ..dialogs import ask_text
from ..util import button, clear, esc, flow, hbox, label, launch, open_in_terminal, pill, status_icon, vbox
from ..widgets import Column, DataTable, card
from .base import Page, action_row, banner, boxed_list, group, set_switch_quiet, stat, switch_row, tabs

AUTO_OFF = 'APT::Periodic::Update-Package-Lists "1";\\nAPT::Periodic::Unattended-Upgrade "0";\\n'


def one_update_steps(u: packages.Update) -> list[Step]:
    if u.source == "apt":
        return [Step(f"Update {u.name}", ["apt-get", "install", "--only-upgrade", "-y", u.name], root=True, env=APT_ENV)]
    if u.source == "snap":
        return [Step(f"Update {u.name}", ["snap", "refresh", u.name], root=True)]
    if u.source == "flatpak":
        return [Step(f"Update {u.name}", ["flatpak", "update", "-y", "--noninteractive", u.name])]
    return []


class UpdatesPage(Page):
    ID = "updates"
    TITLE = "Updates"
    ICON = "software-update-available-symbolic"
    SUBTITLE = "System packages, Snaps and Flatpaks in one place. Security fixes first. Undo, drivers, kernels and sources too."

    def build(self) -> None:
        self.ups: list[packages.Update] = []
        self.header(None, button("Check now", icon="view-refresh-symbolic", tooltip="Ask Ubuntu's servers what's new",
                                 on_click=self.check_now))

        # hero
        self.status = label("Looking for updates…", "mid-num", wrap=True)
        self.status_sub = label("", "subtle", wrap=True)
        self.s_total, self.s_sec, self.s_snap, self.s_flat = stat("…", "waiting"), stat("…", "security", "bad-text"), stat("…", "snaps"), stat("…", "flatpaks")
        self.update_btn = button("Update everything", icon="software-update-available-symbolic", css=["suggested-action", "pill"],
                                 on_click=self.update_all)
        self.sec_btn = button("Security fixes only", css="pill", on_click=self.security_only)
        left = vbox(self.status, self.status_sub, flow(self.update_btn, self.sec_btn, spacing=8, max_per_line=2), spacing=6)
        left.set_hexpand(True)
        stats = flow(self.s_total, self.s_sec, self.s_snap, self.s_flat, spacing=22, min_per_line=2)
        stats.set_valign(Gtk.Align.CENTER)
        hero = card(flow(left, stats, spacing=20, min_per_line=1, max_per_line=2))
        hero.add_css_class("hero")
        self.body.append(hero)
        self.reboot_box = vbox()
        self.body.append(self.reboot_box)

        # tabs
        self.waiting_box = vbox(spacing=10)
        self.history_box = vbox(spacing=10)
        self.drivers_box = vbox(spacing=18)
        self.sources_box = vbox(spacing=18)
        self.settings_box = vbox(spacing=18)
        sw, self.stack = tabs(("waiting", "Waiting", "software-update-available-symbolic", self.waiting_box),
                              ("history", "History & undo", "document-open-recent-symbolic", self.history_box),
                              ("drivers", "Drivers", "drive-harddisk-solidstate-symbolic", self.drivers_box),
                              ("sources", "Sources", "folder-download-symbolic", self.sources_box),
                              ("settings", "Settings", "emblem-system-symbolic", self.settings_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab_changed)
        self.tab_loaded: set[str] = set()

        self.table = DataTable([
            Column("sec", "", "pill", width=86),
            Column("source", "From", "muted", width=80),
            Column("name", "Package", "bold", expand=True),
            Column("current", "Installed", "mono", width=220),
            Column("new", "New version", "mono", width=220),
        ], on_activate=self.update_one, empty="Nothing to update. You're all set.", sort="sec")
        self.table.set_size_request(-1, 440)
        self.table.set_context(self._row_menu, "updates")
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filter updates…")
        self.search_entry.connect("search-changed", lambda e: self.table.set_filter(e.get_text()))
        self.one_btn = button("Update selected", icon="go-down-symbolic", on_click=lambda: self.update_one(self.table.selected()))
        self.log_btn = button("What's new?", icon="text-x-generic-symbolic", tooltip="Changelog of the selected package",
                              on_click=lambda: self.changelog(self.table.selected()))
        self.waiting_box.append(flow(self.search_entry, self.log_btn, self.one_btn, spacing=8, max_per_line=3))
        self.waiting_box.append(self.table)
        self.waiting_box.append(label("Updating is safe: apps you're using keep running, and some updates finish after a restart. "
                                      "Double-click a row to update just that package; right-click for more.", "dim", wrap=True))

    def _row_menu(self, row: dict) -> list:
        u = row["_u"]
        items = [("Update just this", self.update_one), ("What's new in this update?", self.changelog)]
        if u.source == "apt":
            items.append(("Keep at the current version (hold)", lambda r: self.run(f"Hold {u.name}", packages.hold_steps(u.name, True),
                                                                                     "It won't be updated until you release it (Sources tab).",
                                                                                     ok_label="Hold")))
        return items

    # ---------------------------------------------------------------- data
    def load(self) -> None:
        self.status.set_text("Looking for updates…")

        def work():
            return (packages.pending_updates(), packages.auto_updates_enabled(), system.reboot_required(), packages.last_apt_update())
        self.bg(work, self.show)
        name = self.stack.get_visible_child_name()
        self.tab_loaded.discard(name)
        self._tab_changed()

    def show(self, res) -> None:
        ups, auto, reboot, last = res
        self.ups = ups
        sec = [u for u in ups if u.security]
        by = {s: sum(1 for u in ups if u.source == s) for s in ("apt", "snap", "flatpak")}
        self.s_total._value.set_text(str(len(ups)))
        self.s_sec._value.set_text(str(len(sec)))
        self.s_sec._value.set_css_classes(["stat-num", "bad-text" if sec else "ok-text"])
        self.s_snap._value.set_text(str(by["snap"]))
        self.s_flat._value.set_text(str(by["flatpak"]))
        if ups:
            self.status.set_text(f"{len(ups)} update{'s' if len(ups) != 1 else ''} waiting" + (f", {len(sec)} security fix{'es' if len(sec) != 1 else ''}" if sec else ""))
        else:
            self.status.set_text("You're up to date")
        sub = f"Last checked {ago(last) if last else 'never'}."
        if last and time.time() - last > 3 * 86400:
            sub += " That's a while ago: press Check now for the latest list."
        sub += "  Automatic security updates are " + ("on." if auto else "off.")
        self.status_sub.set_text(sub)
        self.update_btn.set_sensitive(bool(ups))
        self.sec_btn.set_sensitive(bool(sec))
        clear(self.reboot_box)
        if reboot is not None:
            msg = "Restart needed to finish earlier updates" + (f" ({', '.join(reboot[:4])})." if reboot else ".")
            self.reboot_box.append(banner(msg, "warn", button("Restart…", on_click=self.restart)))
        rows = []
        for u in ups:
            rows.append({"key": f"{u.source}:{u.name}", "sec": ("security", "bad") if u.security else ("", "neutral"), "source": u.source,
                         "name": u.name, "current": u.current, "new": u.new, "_u": u})
        self.table.set_rows(rows)
        page = self.stack.get_page(self.waiting_box)
        page.set_badge_number(len(ups))
        page.set_needs_attention(bool(sec))
        self.auto = auto
        if "settings" in self.tab_loaded and hasattr(self, "auto_row"):
            set_switch_quiet(self.auto_row, auto)
        self.win.set_badge("updates", len(sec) or len(ups), bad=bool(sec))

    def _tab_changed(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"history": self.load_history, "drivers": self.load_drivers, "sources": self.load_sources, "settings": self.load_settings,
         "waiting": lambda: None}[name]()

    # ---------------------------------------------------------------- actions
    def check_now(self) -> None:
        self.run("Check for updates", packages.refresh_steps(), "Asks Ubuntu's servers what's new. Nothing gets installed yet.", ok_label="Check")

    def _snapshot_first(self) -> list[Step]:
        if prefs.get("snapshot_before_update", False) and has("timeshift"):
            return [Step("Take a system snapshot first (Timeshift)", ["timeshift", "--create", "--comments", "before update (PC Command Center)",
                                                                       "--scripted"], root=True)]
        return []

    def update_all(self) -> None:
        snap = self._snapshot_first()
        self.run("Update everything", snap + packages.update_all_steps(), "Installs every waiting update for the system, Snaps and Flatpaks, "
                 "then removes packages nothing needs anymore. Takes a few minutes; keep the laptop plugged in." +
                 (" A Timeshift snapshot is taken first, so you can roll back." if snap else "") +
                 ("\n\nIf something breaks afterwards, the History & undo tab can reverse it." if packages.apt3_history_supported() else ""),
                 ok_label="Update")

    def security_only(self) -> None:
        self.run("Install security fixes", self._snapshot_first() + packages.security_only_steps(), "Only fixes that close security holes.",
                 ok_label="Install")

    def update_one(self, row: dict | None) -> None:
        if not row:
            self.toast("Select an update first.")
            return
        u = row["_u"]
        self.run(f"Update {u.name}", one_update_steps(u), f"{u.current or 'installed'} → {u.new}", ok_label="Update")

    def changelog(self, row: dict | None) -> None:
        if not row:
            self.toast("Select an update first.")
            return
        u = row["_u"]
        if u.source == "snap":
            self.bg(lambda: out(["snap", "info", u.name], timeout=20), lambda t: self.text(f"{u.name} (snap)", t))
        elif u.source == "flatpak":
            self.bg(lambda: out(["flatpak", "remote-info", "flathub", u.name], timeout=30), lambda t: self.text(u.name, t or "No details."))
        else:
            self.toast("Fetching the changelog…", 2)
            self.bg(lambda: packages.changelog(u.name), lambda t: self.text(f"What's new in {u.name} {u.new}", t))

    def restart(self) -> None:
        self.run("Restart the computer", [Step("Restart", ["systemctl", "reboot"])], "Save your work first. Open apps will close.",
                 danger=True, ok_label="Restart")

    # ---------------------------------------------------------------- history + undo
    def load_history(self) -> None:
        self.loading(self.history_box, "Reading update history…")

        def work():
            supported = packages.apt3_history_supported()
            return supported, (packages.apt3_history() if supported else []), packages.apt_history()
        self.bg(work, self.show_history)

    def show_history(self, res) -> None:
        supported, h3, entries = res
        clear(self.history_box)
        if supported and h3:
            self.history_box.append(label("Undo any apt change: installs are removed, removals are reinstalled, upgrades go back to "
                                          "the previous version. “Roll back to here” undoes everything done after that point.", "dim", wrap=True))
            lb = boxed_list()
            for e in h3[:60]:
                row = action_row(f"#{e['id']} · {e['action']}: {e['cmd'][:80]}", f"{e['date']} · {e['changes']} package change{'s' if e['changes'] != 1 else ''}",
                                 button("Details", css="flat", on_click=lambda i=e["id"]: self.bg(lambda: packages.apt3_history_info(i),
                                                                                                  lambda t, i=i: self.text(f"apt change #{i}", t))),
                                 button("Undo", css="flat", on_click=lambda ee=e: self.run(
                                     f"Undo: {ee['cmd'][:60]}", packages.apt3_undo_steps(ee["id"]), f"Reverses apt change #{ee['id']} "
                                     f"({ee['action'].lower()}, {ee['changes']} packages) from {ee['date']}.", danger=True, ok_label="Undo")),
                                 button("Roll back to here", css="flat", on_click=lambda ee=e: self.run(
                                     "Roll back", packages.apt3_rollback_steps(ee["id"]), f"Undoes every apt change made after #{ee['id']} "
                                     f"({ee['date']}). Use this when an update broke something and you don't know which one.",
                                     danger=True, ok_label="Roll back")))
                lb.append(row)
            self.history_box.append(lb)
            return
        if not supported:
            self.history_box.append(banner("One-click undo needs APT 3.1 or newer (Ubuntu 26.04). This PC can still show what changed.", "info"))
        if not entries:
            self.history_box.append(label("No apt history found.", "dim"))
            return
        lb = boxed_list()
        for e in entries:
            parts = []
            for k, word in (("installed", "installed"), ("upgraded", "updated"), ("removed", "removed")):
                if e[k]:
                    parts.append(f"{len(e[k])} {word}")
            row = Adw.ExpanderRow(title=esc(e["date"]), subtitle=esc(", ".join(parts) or "no package changes") + "\n<span font_family='monospace' "
                                  f"foreground='{theme.hex('overlay1')}'>{esc(e['cmd'][:140])}</span>")
            row.set_subtitle_lines(2)
            icon = "list-add-symbolic" if e["installed"] and not e["upgraded"] else ("list-remove-symbolic" if e["removed"] and not e["upgraded"] else "software-update-available-symbolic")
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            for k, word in (("installed", "Installed"), ("upgraded", "Updated"), ("removed", "Removed")):
                if e[k]:
                    names = ", ".join(e[k][:80]) + (f" … +{len(e[k]) - 80}" if len(e[k]) > 80 else "")
                    r = Adw.ActionRow(title=word, subtitle=esc(names))
                    r.set_subtitle_lines(6)
                    r.set_subtitle_selectable(True)
                    row.add_row(r)
            if e["installed"] and not e["upgraded"] and not e["removed"]:
                undo = button("Remove what this installed", css="flat")
                undo.connect("clicked", lambda _b, pk=e["installed"]: self.run(
                    "Undo install", [Step("Remove packages", ["apt-get", "purge", "-y", *pk], root=True, env=APT_ENV)],
                    ", ".join(pk[:20]), danger=True, ok_label="Remove"))
                box = hbox(undo)
                box.set_margin_top(6)
                box.set_margin_bottom(6)
                box.set_margin_start(12)
                row.add_row(box)
            lb.append(row)
        self.history_box.append(flow(label(f"Last {len(entries)} changes made with apt (newest first).", "dim", wrap=True, hexpand=True),
                                      button("Full log", css="flat", on_click=lambda: self.text("apt history", "\n".join(
                                          f"{e['date']}  {e['cmd']}\n  + {' '.join(e['installed'])}\n  ^ {' '.join(e['upgraded'])}\n  - {' '.join(e['removed'])}\n"
                                          for e in entries))), min_per_line=1, max_per_line=2, column_spacing=8, row_spacing=8))
        self.history_box.append(lb)

    # ---------------------------------------------------------------- drivers, firmware, kernels
    def load_drivers(self) -> None:
        self.loading(self.drivers_box, "Looking at your hardware…")

        def work():
            fw_names, devices = [], ""
            if has("fwupdmgr"):
                devices = out(["fwupdmgr", "get-devices"], timeout=40)
                fw_names = packages.firmware_updates()
            return packages.drivers(), fw_names, devices, packages.kernels()
        self.bg(work, self.show_drivers)

    def show_drivers(self, res) -> None:
        drivers, fw_names, devices, kernels = res
        clear(self.drivers_box)
        # drivers
        g = group("Drivers", "Extra drivers for your hardware (graphics cards, Wi-Fi, fingerprint readers). Same as Ubuntu's "
                  "“Additional Drivers”.")
        if not has("ubuntu-drivers"):
            g.add(action_row("Driver tool not installed", "ubuntu-drivers-common finds proprietary drivers for your hardware.",
                             button("Install", css="flat", on_click=lambda: self.run("Install driver tool", [Step(
                                 "Install ubuntu-drivers-common", ["apt-get", "install", "-y", "ubuntu-drivers-common"], root=True, env=APT_ENV)]))))
        elif not drivers:
            g.add(action_row("Nothing needed", "All your hardware works with the drivers that come with Ubuntu.", prefix=status_icon("ok")))
        else:
            missing_rec = [d for dev in drivers for d in dev["drivers"] if d["recommended"] and not d["installed"]]
            if missing_rec:
                g.set_header_suffix(button("Install recommended", css="suggested-action", on_click=lambda: self.run(
                    "Install recommended drivers", packages.driver_install_steps(), "Installs " + ", ".join(d["package"] for d in missing_rec) +
                    ". A restart is needed afterwards.", ok_label="Install")))
            for dev in drivers:
                exp = Adw.ExpanderRow(title=esc(dev["model"] or dev["device"]), subtitle=esc(dev["vendor"]))
                inst = [d for d in dev["drivers"] if d["installed"]]
                if inst:
                    exp.add_suffix(pill("using " + inst[0]["package"], "ok"))
                for d in dev["drivers"]:
                    tags = ("recommended · " if d["recommended"] else "") + ("open source" if d["free"] else "proprietary")
                    suf = pill("installed", "ok") if d["installed"] else button("Install", css="flat", on_click=lambda dd=d: self.run(
                        f"Install {dd['package']}", packages.driver_install_steps(dd["package"]), "A restart is needed afterwards.", ok_label="Install"))
                    exp.add_row(action_row(d["package"], tags, suf))
                g.add(exp)
        self.drivers_box.append(g)

        # firmware
        fg = group("Firmware", "BIOS/UEFI, SSD, dock and other devices that support firmware updates (fwupd / LVFS).")
        if not has("fwupdmgr"):
            fg.add(action_row("fwupd isn't installed", "", button("Install", css="flat", on_click=lambda: self.run(
                "Install fwupd", [Step("Install fwupd", ["apt-get", "install", "-y", "fwupd"], root=True, env=APT_ENV)]))))
        else:
            if fw_names:
                fg.add(action_row("Updates available", ", ".join(fw_names), button("Update firmware", css="suggested-action", on_click=lambda: self.run(
                    "Update firmware", [Step("Refresh firmware list", ["fwupdmgr", "refresh", "--force"], root=True, optional=True),
                                        Step("Update firmware", ["fwupdmgr", "update", "-y", "--no-reboot-check"], root=True)],
                    "Keep the laptop plugged in. The PC may restart to finish (it will tell you first).", ok_label="Update")),
                    prefix=status_icon("warn")))
            else:
                fg.add(action_row("Firmware is up to date", "", prefix=status_icon("ok")))
            cur = None
            for line in devices.splitlines():
                st = line.lstrip("│ ")
                if st.startswith(("├─", "└─")):
                    cur = Adw.ExpanderRow(title=esc(st[2:].strip().rstrip(":")))
                    cur.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
                    fg.add(cur)
                    continue
                t = st.strip()
                if cur is None or ":" not in t:
                    continue
                k, _, v = t.partition(":")
                k, v = k.strip(), v.strip()
                if k == "Current version":
                    cur.set_subtitle(esc(f"version {v}"))
                if k in ("Current version", "Vendor", "Summary", "Update State", "Update Error") and v:
                    cur.add_row(Adw.ActionRow(title=esc(k), subtitle=esc(v)))
        self.drivers_box.append(fg)

        # kernels
        kg = group("Kernels", "The core of the system. Ubuntu keeps older ones as a fallback; the running one and the two newest are "
                   "always kept.")
        if not kernels:
            kg.add(action_row("No kernel packages found", "This system's kernel isn't managed by apt (virtual machine or container)."))
        removable = [k for k in kernels if k["removable"]]
        if removable:
            kg.set_header_suffix(button(f"Remove {len(removable)} old", css="flat", on_click=lambda: self.run(
                "Remove old kernels", [s for k in removable for s in packages.remove_kernel_steps(k)],
                f"Frees about {human(sum(k['size'] for k in removable))}. " + ", ".join(k["version"] for k in removable), ok_label="Remove")))
        for k in kernels:
            tags = [pill("running", "ok")] if k["running"] else []
            if k["newest"] and not k["running"]:
                tags.append(pill("newest: restart to use it", "info"))
            elif k["newest"]:
                tags.append(pill("newest", "accent"))
            suf = tags + ([button("Remove", css="flat", on_click=lambda kk=k: self.run(f"Remove kernel {kk['version']}", packages.remove_kernel_steps(kk),
                                                                                     f"Frees about {human(kk['size'])}.", ok_label="Remove"))]
                          if k["removable"] else [])
            kg.add(action_row(f"Linux {k['version']}", f"{human(k['size'])} · {len(k['packages'])} packages", *suf))
        self.drivers_box.append(kg)

    # ---------------------------------------------------------------- sources
    def load_sources(self) -> None:
        self.loading(self.sources_box, "Reading software sources…")
        self.bg(lambda: (packages.sources(), packages.holds(), packages.obsolete_packages()), self.show_sources)

    def show_sources(self, res) -> None:
        srcs, holds, obsolete = res
        clear(self.sources_box)
        official = [s for s in srcs if s["official"]]
        extra = [s for s in srcs if not s["official"]]
        og = group("Ubuntu", "Ubuntu's own repositories.")
        for s in official:
            og.add(action_row(s["name"], " · ".join(s["suites"]) + ("" if s["enabled"] else "  (off)"), button("View", css="flat", on_click=lambda ss=s: self.text(ss["file"], Path(ss["file"]).read_text(errors="replace"))),
                              prefix=status_icon("ok" if s["enabled"] else "info")))
        self.sources_box.append(og)
        eg = group("Extra sources and PPAs", "Added by you or by app installers (Docker, VS Code, Chrome…). Turn off a source that "
                   "causes update errors instead of deleting it.",
                   suffix=button("Add PPA…", icon="list-add-symbolic", css="flat", on_click=self.add_ppa))
        if not extra:
            eg.add(action_row("None", "Only Ubuntu's own repositories are used."))
        for s in extra:
            def toggle(on: bool, settle, ss=s) -> None:
                self.run(("Turn on " if on else "Turn off ") + ss["name"], packages.source_toggle_steps(ss, on), ", ".join(ss["uris"]),
                         reload=False, done=settle)
            row = switch_row(("PPA " + s["ppa"]) if s["ppa"] else s["name"], ", ".join(s["uris"])[:120], s["enabled"], toggle)
            for b in (button(icon="text-x-generic-symbolic", css="flat", tooltip="View file",
                             on_click=lambda ss=s: self.text(ss["file"], open(ss["file"], errors="replace").read())),
                      button(icon="user-trash-symbolic", css="flat", tooltip="Remove this source",
                             on_click=lambda ss=s: self.run(f"Remove {ss['name']}", packages.source_remove_steps(ss),
                                                            "Apps already installed from it stay installed but won't get updates.", danger=True,
                                                            ok_label="Remove", done=lambda ok: ok and self.load_sources()))):
                b.set_valign(Gtk.Align.CENTER)
                row.add_suffix(b)
            eg.add(row)
        self.sources_box.append(eg)

        hg = group("Kept at their version (held)", "Held packages are skipped by updates. Handy when a new version breaks something.",
                   suffix=button("Hold a package…", css="flat", on_click=self.hold_pkg))
        if not holds:
            hg.add(action_row("Nothing held", "Every package updates normally."))
        for h in holds:
            hg.add(action_row(h, "", button("Release", css="flat", on_click=lambda p=h: self.run(f"Release {p}", packages.hold_steps(p, False),
                                                                                              ok_label="Release", done=lambda ok: self.load_sources()))))
        self.sources_box.append(hg)

        lg = group("Leftover packages", "Installed packages that no repository offers anymore (often from older Ubuntu versions or removed PPAs).")
        if obsolete:
            lg.add(action_row(f"{len(obsolete)} leftover package{'s' if len(obsolete) != 1 else ''}", ", ".join(obsolete[:30]),
                              button("Review…", css="flat", on_click=lambda: self.remove_obsolete(obsolete))))
        else:
            lg.add(action_row("None", "Every installed package still comes from a repository."))
        self.sources_box.append(lg)

    def add_ppa(self) -> None:
        def got(v: str | None) -> None:
            if v:
                self.run(f"Add {v}", packages.add_ppa_steps(v), "Only add PPAs you trust: a PPA can replace any package on your system.",
                         ok_label="Add", done=lambda ok: ok and self.load_sources())
        ask_text(self.win, "Add a PPA", "For example ppa:deadsnakes/ppa", "ppa:owner/name", got, ok_label="Add")

    def hold_pkg(self) -> None:
        def got(v: str | None) -> None:
            if v:
                self.run(f"Hold {v}", packages.hold_steps(v, True), ok_label="Hold", done=lambda ok: ok and self.load_sources())
        ask_text(self.win, "Keep a package at its version", "Package name, e.g. google-chrome-stable", "package", got, ok_label="Hold")

    # ---------------------------------------------------------------- settings
    def load_settings(self) -> None:
        clear(self.settings_box)
        auto = packages.auto_updates_enabled()
        self.auto_row = switch_row("Install security fixes automatically", "Checks every day and installs security fixes in the background.",
                                   auto, self.toggle_auto)

        def snap_pref(on: bool, settle) -> None:
            if on and not has("timeshift"):
                self.toast("Install Timeshift first (Maintenance page).")
                settle(False)
                return
            prefs.set("snapshot_before_update", on)
            settle(True)
        snap_row = switch_row("Snapshot before updating", "Takes a Timeshift system snapshot before “Update everything”, so a bad update "
                              "can be rolled back in minutes.", prefs.get("snapshot_before_update", False), snap_pref)
        self.settings_box.append(group("Automatic updates", "", self.auto_row, snap_row))
        self.snap_group = group("Snap updates", "Snaps update themselves in the background.")
        self.settings_box.append(self.snap_group)
        tools = []
        if has("software-properties-gtk"):
            tools.append(action_row("Software & Updates", "Ubuntu's own settings for download server and repositories.",
                                    button("Open", css="flat", on_click=lambda: launch(["software-properties-gtk"]))))
        tools.append(action_row("Upgrade to a new Ubuntu release", "Checks whether a newer Ubuntu version is offered and walks you through it in a terminal.",
                                button("Check…", css="flat", on_click=lambda: open_in_terminal(["sudo", "do-release-upgrade"]))))
        tools.append(action_row("Repair broken packages", "Fixes half-finished installs (after a crash or power cut during an update).",
                                button("Repair", css="flat", on_click=self.repair)))
        self.settings_box.append(group("Tools", "", *tools))
        self.pro_group = group("Ubuntu Pro", "Free for personal use on up to 5 machines: security fixes for 10 years for universe packages too.")
        self.settings_box.append(self.pro_group)
        self.bg(lambda: (out(["pro", "status"], timeout=20) if has("pro") else "", packages.snap_refresh_info()), self._show_settings_data)

    def _show_settings_data(self, res) -> None:
        pro, snapinfo = res
        if has("snap"):
            hold_line = next((ln.split(":", 1)[1].strip() for ln in snapinfo.splitlines() if ln.startswith("hold:")), "")
            held = bool(hold_line) and hold_line != "n/a"
            nxt = next((ln.split(":", 1)[1].strip() for ln in snapinfo.splitlines() if ln.startswith("next:")), "")

            def hold(on: bool, settle) -> None:
                self.run("Snap updates", packages.snap_hold_steps(on), "Snaps stay at their current versions until you resume." if on else "",
                         reload=False, done=settle)
            self.snap_group.add(switch_row("Pause automatic snap updates", (f"Paused ({hold_line})." if held else f"Next check: {nxt}.") if snapinfo else "",
                                           held, hold))
            self.snap_group.add(action_row("Recent snap changes", "What snapd installed, refreshed or removed lately.",
                                           button("View", css="flat", on_click=lambda: self.bg(packages.snap_changes, lambda t: self.text("Snap changes", t)))))
        else:
            self.snap_group.set_visible(False)
        if pro:
            attached = "not attached" not in pro.lower()
            services = [ln for ln in pro.splitlines() if ln.startswith(("esm-", "livepatch", "usg", "fips", "realtime"))][:6]
            btns = [button("Details", css="flat", on_click=lambda: self.text("Ubuntu Pro", pro))]
            if not attached:
                btns.append(button("Attach…", css="flat", on_click=lambda: open_in_terminal(["sudo", "pro", "attach"])))
            self.pro_group.add(action_row("Status", "Attached: security coverage is extended." if attached else
                                          "Not attached. Get a free token at ubuntu.com/pro, then press Attach.", *btns))
            for s in services:
                cols = s.split()
                self.pro_group.add(action_row(cols[0], " ".join(cols[1:4])))
        else:
            self.pro_group.set_visible(False)

    def remove_obsolete(self, names: list[str]) -> None:
        from ..dialogs import PickDialog

        def done(keys):
            if keys:
                self.run("Remove leftover packages", [Step("Remove selected packages", ["apt-get", "purge", "-y", *keys], root=True, env=APT_ENV)],
                         "Only remove what you recognise and don't use. Kernels and drivers are safer to keep.", danger=True, ok_label="Remove")
        PickDialog("Leftover packages", "Tick packages to remove. Nothing is ticked by default.", [(n, n, "", False) for n in names], done).present(self.win)

    def repair(self) -> None:
        self.run("Repair packages", [Step("Finish interrupted installs", ["dpkg", "--configure", "-a"], root=True, env=APT_ENV),
                                     Step("Fix broken dependencies", ["apt-get", "install", "-f", "-y"], root=True, env=APT_ENV)],
                 "Safe to run any time.", ok_label="Repair")

    def toggle_auto(self, on: bool, settle) -> None:
        if on:
            steps = security.auto_updates().steps or [Step("Turn on daily security updates", ["bash", "-c", "printf 'APT::Periodic::Update-Package-Lists \"1\";\\nAPT::Periodic::Unattended-Upgrade \"1\";\\n' > /etc/apt/apt.conf.d/20auto-upgrades"], root=True)]
            self.run("Turn on automatic security updates", steps, "Security fixes will install by themselves every day.", done=settle, reload=False)
        else:
            self.run("Turn off automatic updates", [Step("Turn off automatic security updates", ["bash", "-c", f"printf '{AUTO_OFF}' > /etc/apt/apt.conf.d/20auto-upgrades"], root=True)],
                     "You'll only get security fixes when you update by hand. Not recommended.", danger=True, ok_label="Turn off", done=settle, reload=False)


PAGE = UpdatesPage
