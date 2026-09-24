"""Care: one-click tune-up, weekly automatic checkup, settings backups, system snapshots, setup scripts and preferences."""

from __future__ import annotations

import os
from pathlib import Path

from gi.repository import Gtk

from ... import __version__
from ...core import junk, maint, packages
from ...core.fmt import ago, human
from ...core.run import HOME, Step, has, py_step
from ..dialogs import ask_text
from ..runner import capture
from ..util import button, clear, hbox, label, launch, open_in_terminal, open_path, vbox
from ..widgets import card
from .base import Page, action_row, group, switch_row


class MaintenancePage(Page):
    ID = "maintenance"
    TITLE = "Maintenance"
    ICON = "emblem-system-symbolic"
    SUBTITLE = "Keep the PC in shape with one click, on a schedule, and with backups you can roll back to."

    def build(self) -> None:
        self.header()
        img = Gtk.Image.new_from_icon_name("starred-symbolic")
        img.set_pixel_size(56)
        img.add_css_class("accent-text")
        self.tune_btn = button("Run tune-up", icon="media-playback-start-symbolic", css=["suggested-action", "pill"], on_click=self.tune_up)
        self.tune_sub = label("Installs all updates, cleans recommended junk (caches, old logs, leftovers) and removes unused packages. "
                              "You see every command first.", "subtle", wrap=True)
        t = vbox(label("One-click tune-up", "mid-num"), self.tune_sub, hbox(self.tune_btn), spacing=6)
        t.set_hexpand(True)
        hero = card(hbox(img, t, spacing=22))
        hero.add_css_class("hero")
        self.body.append(hero)
        self.holder = vbox(spacing=18)
        self.body.append(self.holder)

    def load(self) -> None:
        clear(self.holder)
        self.holder.append(self._schedule_group())
        self.holder.append(self._backup_group())
        self.holder.append(self._snapshot_group())
        self.holder.append(self._setup_group())
        self.holder.append(self._prefs_group())
        self.holder.append(group("About", "", action_row("PC Command Center", f"version {__version__} · also available in the terminal as `pc`",
                                                               button("Open terminal version", css="flat", on_click=lambda: open_in_terminal(["pc"]))),
                                 action_row("Keyboard shortcuts", "Ctrl+1…9 switch pages, F5 refreshes, Ctrl+F searches.",
                                            button("Show", css="flat", on_click=self.win.shortcuts))))

    # ---------------------------------------------------------------- tune-up
    def tune_up(self) -> None:
        self.tune_btn.set_sensitive(False)
        self.tune_sub.set_text("Looking for updates and junk…")

        def work():
            found = junk.scan(deep=False)
            steps = packages.update_all_steps()
            freed = 0
            titles = []
            for j in found:
                if j.default and not j.pick and j.id not in ("apt-cache",):
                    s = j.steps_for()
                    if s:
                        steps += s
                        freed += j.size or 0
                        titles.append(j.title)
            steps.append(Step("Clean package download cache", ["apt-get", "clean"], root=True, optional=True))
            return steps, freed, titles

        def ready(res) -> None:
            steps, freed, titles = res
            self.tune_btn.set_sensitive(True)
            self.tune_sub.set_text("Installs all updates, cleans recommended junk (caches, old logs, leftovers) and removes unused packages. "
                                   "You see every command first.")
            self.run("Tune-up", steps, f"Updates everything, then frees about {human(freed)} from: {', '.join(titles) or 'nothing extra'}. "
                     "Takes a few minutes; keep the laptop plugged in.", ok_label="Start tune-up")
        self.bg(work, ready)

    # ---------------------------------------------------------------- schedule
    def _schedule_group(self):
        st = maint.timer_status()

        def toggle(on: bool, settle) -> None:
            self.run("Weekly checkup", maint.enable_timer_steps() if on else maint.disable_timer_steps(),
                     "Every Sunday (or the next time the PC is on) it clears safe caches, then sends a notification if anything needs you." if on else "",
                     ok_label="Turn on" if on else "Turn off", ask=on, done=settle)
        log = maint.STATE_DIR / "maintain.log"
        sub = (f"Next: {st['next']}" if st["next"] else "Sundays at 11:00") + (f" · last ran {st['last']}" if st["last"] else "")
        return group("Weekly checkup", "Runs in the background. Never needs your password, never removes anything you'd miss.",
                     switch_row("Automatic weekly checkup", sub, st["enabled"], toggle),
                     action_row("Run it now", "Clears safe caches and checks disks, updates and services.",
                                button("Run", css="flat", on_click=lambda: self.run("Weekly checkup", [py_step("Run checkup", maint.maintain_auto, "pc maintain --auto")],
                                                                                     ask=False))),
                     action_row("Past results", "What the checkup did each week.",
                                button("View", css="flat", on_click=lambda: self.text("Checkup history", log.read_text() if log.exists() else "No runs yet."))))

    # ---------------------------------------------------------------- backups
    def _backup_group(self):
        rows = [action_row("Back up settings now", "Shell, git, editor (VS Code, Zed), terminal, GNOME settings, fonts and SSH config into ~/Backups.",
                           button("Back up", css="suggested-action", on_click=lambda: self.run("Back up settings", maint.backup_settings_steps(), ask=False)))]
        for b in maint.settings_backups()[:6]:
            rows.append(action_row(b["name"], f"{ago(b['time'])} · {human(b['size'])}",
                                   button("Restore…", css="flat", on_click=lambda p=b["path"]: self.run(
                                       "Restore settings", maint.restore_settings_steps(p), "Overwrites your current settings files with the ones in this backup. "
                                       "Tip: back up first so you can go back.", danger=True, ok_label="Restore")),
                                   button(icon="user-trash-symbolic", css="flat", tooltip="Delete backup", on_click=lambda p=b["path"]: self.run(
                                       "Delete backup", [Step("Delete backup", ["rm", "-f", p])], os.path.basename(p), danger=True, ok_label="Delete"))))
        return group("Settings backups", "Copy the files to a USB stick or cloud drive to move your setup to a new PC.", *rows,
                     suffix=button("Open folder", css="flat", on_click=lambda: open_path(str(maint.BACKUP_DIR)) if maint.BACKUP_DIR.exists() else self.toast("No backups yet.")))

    # ---------------------------------------------------------------- snapshots
    def _snapshot_group(self):
        tools = maint.snapshot_tools()
        rows = []
        if tools["timeshift"]:
            rows.append(action_row("Create a system snapshot", "Saves the system (not your files) so you can roll back a bad update or driver.",
                                   button("Create", css="suggested-action", on_click=lambda: self.run("System snapshot", maint.timeshift_steps(),
                                                                                                       "Takes a few minutes the first time.", ok_label="Create"))))
            self.snap_row = action_row("Snapshots", "Reading the list needs your password.", button("Show", css="flat", on_click=self.list_snapshots))
            rows.append(self.snap_row)
            rows.append(action_row("Timeshift app", "Restore a snapshot, set a schedule, choose the disk.",
                                   button("Open", css="flat", on_click=lambda: launch(["timeshift-launcher"]) if has("timeshift-launcher") else launch(["pkexec", "timeshift-gtk"]))))
        else:
            rows.append(action_row("Timeshift isn't installed", "System snapshots let you undo a bad update in minutes. Highly recommended.",
                                   button("Install", css="suggested-action", on_click=lambda: self.run("Install Timeshift", maint.timeshift_steps(), ok_label="Install"))))
        if tools["deja-dup"]:
            rows.append(action_row("Backups of your files", "Ubuntu's Backups app (Déjà Dup) copies your home folder to a drive or the cloud.",
                                   button("Open", css="flat", on_click=lambda: launch(["deja-dup"]))))
        return group("System snapshots", "", *rows)

    def list_snapshots(self) -> None:
        self.snap_row.set_subtitle("Reading…")
        capture([Step("List snapshots", ["timeshift", "--list", "--scripted"], root=True)],
                lambda ok, lines: self.text("Snapshots", "\n".join(lines)) if ok else self.snap_row.set_subtitle("Couldn't read the list."))

    # ---------------------------------------------------------------- setup scripts
    def _setup_group(self):
        d = maint.setup_dir()
        if not d:
            return group("Setup scripts", "The linux-setup folder wasn't found.",
                         action_row("Where is linux-setup?", "Point to the folder that contains setup.sh.",
                                    button("Choose…", css="flat", on_click=self.choose_setup)))
        sh_path = str(d / "setup.sh")

        def term(*args: str) -> None:
            open_in_terminal(["bash", sh_path, *args])
        return group("Setup scripts", f"From {str(d).replace(str(HOME), '~')}. They run in a terminal because they ask questions.",
                     action_row("Re-apply the setup", "Theme, fonts, terminal, editors and tools. Safe to run again.", button("Run", css="flat", on_click=lambda: term("setup"))),
                     action_row("Scan report", "A text report of disk use and junk.", button("Run", css="flat", on_click=lambda: term("scan"))),
                     action_row("Tips", "Your cheat sheet: aliases, shortcuts, commands.", button("Show", css="flat", on_click=lambda: term("tips"))),
                     action_row("Undo the look", "Puts GNOME's theme, fonts and terminal back the way they were before the setup.",
                                button("Undo…", css="flat", on_click=lambda: term("undo"))),
                     suffix=button("Open folder", css="flat", on_click=lambda: open_path(str(d))))

    def choose_setup(self) -> None:
        def got(p: str | None) -> None:
            if p and (Path(p).expanduser() / "setup.sh").exists():
                maint.save_config(setup_dir=p)
                self.load()
            elif p:
                self.toast("No setup.sh in that folder.")
        ask_text(self.win, "linux-setup folder", "Full path of the folder containing setup.sh", "~/Documents/Vibes/linux-setup", got)

    # ---------------------------------------------------------------- preferences
    def _prefs_group(self):
        roots = maint.config()["projects"]
        rows = []
        for r in roots:
            exists = Path(r).expanduser().is_dir()
            rows.append(action_row(r, "found" if exists else "doesn't exist (skipped)",
                                   button(icon="list-remove-symbolic", css="flat", tooltip="Remove", on_click=lambda rr=r: self._set_roots([x for x in roots if x != rr]))))

        def add() -> None:
            def got(p: str | None) -> None:
                if p and p not in roots:
                    self._set_roots(roots + [p])
            ask_text(self.win, "Add a project folder", "Where you keep code, e.g. ~/code or ~/Documents/Vibes", "~/code", got, ok_label="Add")
        return group("Project folders", "Where the Developer page and the deep cleanup look for your code.", *rows,
                     suffix=button("Add…", icon="list-add-symbolic", css="flat", on_click=add))

    def _set_roots(self, roots: list[str]) -> None:
        maint.save_config(projects=roots)
        self.toast("Saved.")
        self.load()


PAGE = MaintenancePage
