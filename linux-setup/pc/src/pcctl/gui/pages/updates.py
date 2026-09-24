"""Updates: apt + snap + flatpak in one list, security first; history, firmware, and update settings."""

from __future__ import annotations

import glob
import re
import time

from gi.repository import Adw, Gtk

from ...core import packages, security, system
from ...core.fmt import ago
from ...core.packages import APT_ENV
from ...core.run import Step, has, out
from ..util import button, clear, esc, flow, hbox, label, launch, open_in_terminal, spacer, vbox
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
    SUBTITLE = "System packages, Snaps and Flatpaks in one place. Security fixes first."

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
        left = vbox(self.status, self.status_sub, hbox(self.update_btn, self.sec_btn, spacing=8), spacing=6)
        left.set_hexpand(True)
        stats = flow(self.s_total, self.s_sec, self.s_snap, self.s_flat, spacing=22, min_per_line=2)
        stats.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(left, stats, spacing=20))
        hero.add_css_class("hero")
        self.body.append(hero)
        self.reboot_box = vbox()
        self.body.append(self.reboot_box)

        # tabs
        self.waiting_box = vbox(spacing=10)
        self.history_box = vbox(spacing=10)
        self.fw_box = vbox(spacing=10)
        self.settings_box = vbox(spacing=18)
        sw, self.stack = tabs(("waiting", "Waiting", "software-update-available-symbolic", self.waiting_box),
                              ("history", "History", "document-open-recent-symbolic", self.history_box),
                              ("firmware", "Firmware", "drive-harddisk-solidstate-symbolic", self.fw_box),
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
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filter updates…")
        self.search_entry.connect("search-changed", lambda e: self.table.set_filter(e.get_text()))
        self.one_btn = button("Update selected", icon="go-down-symbolic", on_click=lambda: self.update_one(self.table.selected()))
        self.waiting_box.append(hbox(self.search_entry, spacer(), self.one_btn))
        self.waiting_box.append(self.table)
        self.waiting_box.append(label("Updating is safe: apps you're using keep running, and some updates finish after a restart. "
                                      "Double-click a row to update just that package.", "dim", wrap=True))

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
        if "settings" in self.tab_loaded:
            set_switch_quiet(self.auto_row, auto)
        self.win.set_badge("updates", len(sec) or len(ups), bad=bool(sec))

    def _tab_changed(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "history":
            self.load_history()
        elif name == "firmware":
            self.load_firmware()
        elif name == "settings":
            self.load_settings()

    # ---------------------------------------------------------------- actions
    def check_now(self) -> None:
        self.run("Check for updates", packages.refresh_steps(), "Asks Ubuntu's servers what's new. Nothing gets installed yet.", ok_label="Check")

    def update_all(self) -> None:
        fw = has("fwupdmgr")
        self.run("Update everything", packages.update_all_steps(), "Installs every waiting update for the system, Snaps and Flatpaks, "
                 "then removes packages nothing needs anymore. Takes a few minutes; keep the laptop plugged in." +
                 ("\n\nFirmware updates are separate (Firmware tab)." if fw else ""), ok_label="Update")

    def security_only(self) -> None:
        self.run("Install security fixes", packages.security_only_steps(), "Only fixes that close security holes.", ok_label="Install")

    def update_one(self, row: dict | None) -> None:
        if not row:
            self.toast("Select an update first.")
            return
        u = row["_u"]
        self.run(f"Update {u.name}", one_update_steps(u), f"{u.current or 'installed'} → {u.new}", ok_label="Update")

    def restart(self) -> None:
        self.run("Restart the computer", [Step("Restart", ["systemctl", "reboot"])], "Save your work first. Open apps will close.",
                 danger=True, ok_label="Restart")

    # ---------------------------------------------------------------- history
    def load_history(self) -> None:
        self.loading(self.history_box, "Reading update history…")
        self.bg(packages.apt_history, self.show_history)

    def show_history(self, entries: list[dict]) -> None:
        clear(self.history_box)
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
                                  f"foreground='#7f849c'>{esc(e['cmd'][:140])}</span>")
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
            lb.append(row)
        self.history_box.append(hbox(label(f"Last {len(entries)} changes made with apt (newest first).", "dim", hexpand=True),
                                     button("Full log", css="flat", on_click=lambda: self.text("apt history", "\n".join(
                                         f"{e['date']}  {e['cmd']}\n  + {' '.join(e['installed'])}\n  ^ {' '.join(e['upgraded'])}\n  - {' '.join(e['removed'])}\n"
                                         for e in entries)))))
        self.history_box.append(lb)

    # ---------------------------------------------------------------- firmware
    def load_firmware(self) -> None:
        clear(self.fw_box)
        if not has("fwupdmgr"):
            self.fw_box.append(banner("Firmware updates need fwupd (normally installed on Ubuntu).", "info",
                                      button("Install fwupd", on_click=lambda: self.run("Install fwupd", [Step("Install fwupd", ["apt-get", "install", "-y", "fwupd"], root=True, env=APT_ENV)]))))
            return
        self.loading(self.fw_box, "Asking your hardware for firmware versions…")

        def work():
            devices = out(["fwupdmgr", "get-devices"], timeout=40)
            return packages.firmware_updates(), devices
        self.bg(work, self.show_firmware)

    def show_firmware(self, res) -> None:
        names, devices = res
        clear(self.fw_box)
        if names:
            self.fw_box.append(banner("Firmware updates available: " + ", ".join(names), "warn",
                                      button("Update firmware", css="suggested-action", on_click=lambda: self.run(
                                          "Update firmware", [Step("Refresh firmware list", ["fwupdmgr", "refresh", "--force"], root=True, optional=True),
                                                              Step("Update firmware", ["fwupdmgr", "update", "-y", "--no-reboot-check"], root=True)],
                                          "Keep the laptop plugged in. The PC may restart to finish (it will tell you first).", ok_label="Update"))))
        else:
            self.fw_box.append(banner("Your firmware is up to date (BIOS/UEFI, SSD, dock and other devices that support LVFS).", "ok"))
        lb = boxed_list()
        cur = None
        for line in devices.splitlines():
            st = line.lstrip("│ ")
            if st.startswith(("├─", "└─")):
                cur = Adw.ExpanderRow(title=esc(st[2:].strip().rstrip(":")))
                cur.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
                lb.append(cur)
                continue
            t = st.strip()
            if cur is None or ":" not in t:
                continue
            k, _, v = t.partition(":")
            k, v = k.strip(), v.strip()
            if k == "Current version":
                cur.set_subtitle(esc(f"version {v}"))
            if k in ("Current version", "Vendor", "Summary", "Update State", "Update Error", "Serial Number") and v:
                cur.add_row(Adw.ActionRow(title=esc(k), subtitle=esc(v)))
        if lb.get_first_child() is None:
            self.fw_box.append(label("fwupd didn't report any devices.", "dim"))
            return
        self.fw_box.append(label("Devices", "section-title"))
        self.fw_box.append(lb)

    # ---------------------------------------------------------------- settings
    def load_settings(self) -> None:
        clear(self.settings_box)
        auto = packages.auto_updates_enabled()
        self.auto_row = switch_row("Install security fixes automatically", "Checks every day and installs security fixes in the background.",
                                   auto, self.toggle_auto)
        tools = []
        if has("software-properties-gtk"):
            tools.append(action_row("Software sources", "Choose download server, enable extra repositories, proprietary drivers.",
                                    button("Open", css="flat", on_click=lambda: launch(["software-properties-gtk"]))))
        if has("update-manager"):
            tools.append(action_row("Software Updater", "Ubuntu's own updater app.", button("Open", css="flat", on_click=lambda: launch(["update-manager"]))))
        tools.append(action_row("Upgrade to a new Ubuntu release", "Checks whether a newer Ubuntu version is offered and walks you through it in a terminal.",
                                button("Check…", css="flat", on_click=lambda: open_in_terminal(["sudo", "do-release-upgrade"]))))
        tools.append(action_row("Repair broken packages", "Fixes half-finished installs (after a crash or power cut during an update).",
                                button("Repair", css="flat", on_click=self.repair)))
        self.settings_box.append(group("Automatic updates", "", self.auto_row))
        self.settings_box.append(group("Tools", "", *tools))
        self.pro_group = group("Ubuntu Pro", "Free for personal use on up to 5 machines: security fixes for 10 years for universe packages too.")
        self.settings_box.append(self.pro_group)
        self.obs_group = group("Leftover packages", "Installed packages that no repository offers anymore (often from older Ubuntu versions or removed PPAs).")
        self.settings_box.append(self.obs_group)
        self.sources_group = group("Extra software sources", "Third-party apt repositories added to this PC.")
        self.settings_box.append(self.sources_group)
        self.bg(self._settings_data, self._show_settings_data)

    def _settings_data(self):
        pro = out(["pro", "status"], timeout=20) if has("pro") else ""
        obsolete = packages.obsolete_packages()
        sources = []
        for f in sorted(glob.glob("/etc/apt/sources.list.d/*.list") + glob.glob("/etc/apt/sources.list.d/*.sources")):
            text = open(f, errors="replace").read() if f else ""
            urls = sorted(set(re.findall(r"https?://[^\s]+", text)))
            enabled = "Enabled: no" not in text and any(ln.strip().startswith(("deb ", "Types:")) for ln in text.splitlines())
            sources.append((f, urls, enabled))
        return pro, obsolete, sources

    def _show_settings_data(self, res) -> None:
        pro, obsolete, sources = res
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
        if obsolete:
            self.obs_group.add(action_row(f"{len(obsolete)} leftover package{'s' if len(obsolete) != 1 else ''}", ", ".join(obsolete[:30]),
                                          button("Review…", css="flat", on_click=lambda: self.remove_obsolete(obsolete))))
        else:
            self.obs_group.add(action_row("None", "Every installed package still comes from a repository."))
        if sources:
            for f, urls, enabled in sources:
                name = f.rsplit("/", 1)[-1]
                self.sources_group.add(action_row(name, (", ".join(urls[:2]) or "no URLs") + ("" if enabled else "  (disabled)"),
                                                  button("View", css="flat", on_click=lambda ff=f: self.text(ff, open(ff, errors="replace").read()))))
        else:
            self.sources_group.add(action_row("None", "Only Ubuntu's own repositories are used."))

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
