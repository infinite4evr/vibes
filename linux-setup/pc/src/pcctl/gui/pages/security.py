"""Security: score + checklist with one-click fixes, a check for leaked passwords and API keys, the firewall and the
network services it doesn't cover (Docker, SSH server), AppArmor, a ClamAV virus scan, and who can log in."""

from __future__ import annotations

import glob
import os
import time

from gi.repository import GLib, Gtk

from ...core import accounts, antivirus, secrets, security
from ...core.fmt import ago
from ...core.run import HOME, Step, has, out, sh
from ..dialogs import ask_text
from ..runner import capture
from ..util import button, clear, hbox, label, launch, open_in_terminal, open_path, pill, status_icon, vbox
from ..widgets import RingGauge, card
from .base import Page, action_row, banner, group, switch_row, tabs


def ssh_keys() -> list[dict]:
    res = []
    for pub in sorted(glob.glob(str(HOME / ".ssh/*.pub"))):
        info = out(["ssh-keygen", "-l", "-f", pub])  # "256 SHA256:xxx comment (ED25519)"
        parts = info.split()
        priv = pub[:-4]
        res.append({"file": pub, "name": os.path.basename(priv), "bits": parts[0] if parts else "?", "type": parts[-1].strip("()") if parts else "?",
                    "comment": " ".join(parts[2:-1]) if len(parts) > 3 else "", "private_ok": oct(os.stat(priv).st_mode & 0o777) in ("0o600", "0o400") if os.path.exists(priv) else None})
    return res


def authorized_keys() -> int:
    return security.authorized_keys_count()


KIND_GROUPS = [("history", "Command history", "Commands you typed are saved in plain text. A key in there counts as leaked: make a new one, then remove it."),
               ("project", "Project folders", "Secret files that git would upload (or already has). Once pushed to GitHub, anyone may have copied them."),
               ("home", "Settings files in your home folder", "Where command-line tools keep your logins."),
               ("ssh", "SSH keys", "The keys that log you in to GitHub and servers.")]
NO_FIX_ALL = {"reboot", "docker", "ssh-settings", "secrets"}


def _centred(w: Gtk.Widget) -> Gtk.Widget:
    w.set_valign(Gtk.Align.CENTER)
    return w


class SecurityPage(Page):
    ID = "security"
    TITLE = "Security"
    ICON = "security-high-symbolic"
    SUBTITLE = "A checklist in plain language with one-click fixes, leaked passwords and API keys, the firewall, a virus scan and who can log in."
    PALETTE = [("secrets", "Check for leaked passwords and API keys"), ("virus", "Scan Downloads for viruses"),
               ("accounts", "Who can log in to this PC (user accounts)"), ("docker", "Docker ports and the firewall"),
               ("ssh-server", "SSH server settings (password login, root login)")]

    def build(self) -> None:
        self.header()
        self.gauge = RingGauge(128, 12)
        self.title = label("Checking…", "mid-num", wrap=True)
        self.sub = label("", "subtle", wrap=True)
        self.fix_all_btn = button("Fix all recommended", icon="emblem-ok-symbolic", css=["suggested-action", "pill"], on_click=self.fix_all)
        self.fix_all_btn.set_visible(False)
        t = vbox(self.title, self.sub, hbox(self.fix_all_btn), spacing=6)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        hero = card(hbox(self.gauge, t, spacing=24))
        hero.add_css_class("hero")
        self.body.append(hero)

        self.checks_holder = vbox(spacing=18)
        self.secrets_box = vbox(spacing=18)
        self.net_box = vbox(spacing=18)
        self.virus_box = vbox(spacing=18)
        self.acc_box = vbox(spacing=18)
        sw, self.stack = tabs(("checks", "Checklist", "emblem-ok-symbolic", self.checks_holder),
                              ("secrets", "Secrets", "dialog-password-symbolic", self.secrets_box),
                              ("network", "Firewall", "network-server-symbolic", self.net_box),
                              ("virus", "Viruses", "folder-download-symbolic", self.virus_box),
                              ("accounts", "Accounts", "system-users-symbolic", self.acc_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self.rules_holder = vbox()
        self.checks: list = []
        self.findings: list[secrets.Finding] | None = None
        self.docker: tuple[str, list] = ("missing", [])
        self.fw = None
        self.av: dict = {}

    def load(self) -> None:
        self.title.set_text("Checking…")
        self.sub.set_text("Looking at settings, updates and your files for leaked keys. This takes a few seconds.")
        self.loading(self.checks_holder, "Checking…")
        self.bg(security.all_checks, self.show)
        self.tab_loaded.clear()
        self._tab()

    def _remeasure(self) -> None:
        """GTK 4.14 can keep a stale size for boxes filled while their tab was hidden (text then overlaps). Measure again."""
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

    def _tab(self, *_a) -> None:
        self._remeasure()
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"secrets": self.load_secrets, "network": self.load_network, "virus": self.load_virus, "accounts": self.load_accounts}.get(name, lambda: None)()

    def show_tab(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def palette_action(self, key: str) -> None:
        if key == "secrets":
            self.show_tab("secrets")
        elif key == "virus":
            self.show_tab("virus")
            self.scan_folder(antivirus.downloads())
        elif key == "accounts":
            self.show_tab("accounts")
        elif key in ("docker", "ssh-server"):
            self.show_tab("network")

    # ---------------------------------------------------------------- checklist
    def show(self, checks: list) -> None:
        self.checks = checks
        score = security.score(checks)
        todo = [c for c in checks if c.level in ("bad", "warn")]
        self.gauge.set(score, str(score), "security", "green" if score >= 85 else ("peach" if score >= 60 else "red"))
        self.title.set_text("Well protected" if not todo else f"{len(todo)} thing{'s' if len(todo) != 1 else ''} to improve")
        self.sub.set_text("Nothing urgent. Keep updates on and you're good." if not todo else
                          "Each item says what it means for you. Fixes show the exact commands before running.")
        fixable = [c for c in todo if c.steps and c.id not in NO_FIX_ALL]
        self.fix_all_btn.set_visible(len(fixable) > 1)
        clear(self.checks_holder)
        rows = []
        for c in sorted(checks, key=lambda c: {"bad": 0, "warn": 1, "info": 2, "ok": 3}[c.level]):
            btns = []
            if c.fix_label and (c.steps or c.goto):
                b = button(c.fix_label, css="suggested-action" if c.level == "bad" else "flat")
                b.connect("clicked", lambda _b, ch=c: self.fix(ch))
                btns.append(b)
            rows.append(action_row(c.title, c.detail, *btns, prefix=status_icon(c.level)))
        self.checks_holder.append(group("Checklist", "", *rows))
        self.win.set_badge("security", len([c for c in todo if c.level == "bad"]), bad=True)
        self._remeasure()
        fresh = secrets.recent(300)
        if fresh is not None and "secrets" in self.tab_loaded and self.findings is None:
            self.show_secrets(fresh)

    def fix(self, c) -> None:
        if c.id == "secrets":
            self.show_tab("secrets")
        elif c.id == "docker" and c.steps:
            self.docker_localhost()
        elif c.goto:
            self.win.goto(c.goto)
        else:
            self.run(c.fix_label or c.title, c.steps, c.detail, ok_label=c.fix_label or "Fix")

    def fix_all(self) -> None:
        steps = [s for c in self.checks if c.level in ("bad", "warn") and c.steps and c.id not in NO_FIX_ALL for s in c.steps]
        self.run("Fix security issues", steps, "Applies every recommended fix below in one go.", ok_label="Fix all")

    # ---------------------------------------------------------------- secrets (M1)
    def load_secrets(self, force: bool = False) -> None:
        fresh = None if force else secrets.recent(300)
        if fresh is not None:
            self.show_secrets(fresh)
            return
        self.loading(self.secrets_box, "Looking through your command history, projects and settings files…")
        self.bg(secrets.scan, self.show_secrets)

    def show_secrets(self, findings: list) -> None:
        self.findings = findings
        box = self.secrets_box
        clear(box)
        self._remeasure()
        stats = secrets.LAST.get("stats") or {}
        where = ", ".join((stats.get("histories") or [])[:3] + (stats.get("roots") or [])[:4])
        when = f"Checked {ago(secrets.LAST['at'])} in {stats.get('seconds', 0):.1f} s" if secrets.LAST.get("at") else ""
        intro = label("Finds API keys, tokens and passwords left where they shouldn't be: in your command history, in project folders "
                      "that git would upload, and in settings files other accounts can read. Nothing leaves your PC, and keys are only "
                      "shown partly hidden.", "subtle", wrap=True)
        meta = label(f"{when} · looked in {where}" + (" (stopped early in very big folders)" if stats.get("truncated") else ""), "dim", wrap=True)
        again = button("Check again", icon="view-refresh-symbolic", css="flat", on_click=lambda: self.load_secrets(force=True))
        head = vbox(intro, hbox(meta, again, spacing=8), spacing=6)
        meta.set_hexpand(True)
        again.set_valign(Gtk.Align.CENTER)
        box.append(head)
        bad = [f for f in findings if f.level == "bad"]
        warn = [f for f in findings if f.level == "warn"]
        fix_steps = secrets.fix_all_steps(findings)
        if not findings:
            box.append(banner("No exposed secrets found. Your history, projects and credential files look clean.", "ok"))
            return
        if bad or warn:
            text = (f"{len(bad)} exposed secret{'s' if len(bad) != 1 else ''}" if bad else "") + (" and " if bad and warn else "") + \
                   (f"{len(warn)} thing{'s' if len(warn) != 1 else ''} worth a look" if warn else "") + \
                   ". Treat a leaked key as used by someone else: make a new one on the service's website, then clean up here."
            btns = [button("Fix what I can", css="suggested-action", on_click=lambda: self.run(
                "Clean up secrets", fix_steps, "Removes keys from your history (a private backup is kept), tells git to ignore secret files "
                "and makes credential files private. It can't make new keys for you: use the \"New key\" buttons for that.",
                ok_label="Clean up"))] if fix_steps else []
            box.append(banner(text, "bad" if bad else "warn", *btns))
        for kind, title, desc in KIND_GROUPS:
            items = [f for f in findings if f.kind == kind]
            if items:
                box.append(group(title, desc, *[self._finding_row(f) for f in items]))

    def _finding_row(self, f: secrets.Finding) -> Gtk.Widget:
        btns = []
        if f.rotate:
            btns.append(button("New key", icon="web-browser-symbolic", css="flat", tooltip=f"Make a new key and revoke this one: {f.rotate}",
                               on_click=lambda u=f.rotate: launch(["xdg-open", u])))
        if f.steps:
            btns.append(button(f.fix_label or "Fix", css="suggested-action" if f.level == "bad" and not f.rotate else "flat",
                               on_click=lambda ff=f: self.run(ff.fix_label or ff.title, ff.steps, ff.detail.split("\n")[-1],
                                                             ok_label=ff.fix_label or "Fix", reload=False,
                                                             done=lambda ok: ok and self.load_secrets(force=True))))
        if f.terminal:
            btns.append(button("Add passphrase" if f.terminal[0] == "ssh-keygen" else "Sign in", css="flat",
                               tooltip="Opens a terminal: " + " ".join(f.terminal),
                               on_click=lambda t=f.terminal: open_in_terminal(t) or self.toast("No terminal app found. Run: " + " ".join(t), 6)))
        if f.kind == "project" and f.path:
            btns.append(button(icon="folder-open-symbolic", css="flat", tooltip="Open the folder", on_click=lambda p=f.path: open_path(os.path.dirname(p))))
        detail = f.detail.split("\n")[0] if f.kind == "history" else f.detail
        row = action_row(f.title, detail, *btns, prefix=status_icon(f.level))
        row.set_subtitle_lines(6)
        return row

    # ---------------------------------------------------------------- firewall & servers (M2, M3, M4)
    def load_network(self) -> None:
        self.loading(self.net_box)
        self.bg(lambda: (security.firewall(), security.docker_ports(), security.docker_default_ip(), security.ssh_server_installed(),
                         security.ssh_active(), security.sshd_settings() if security.ssh_server_installed() else {}, security.authorized_keys_count(),
                         security.remote_logins(), os.path.exists(security.HARDEN_FILE), security.apparmor_status()), self.show_network)

    def show_network(self, res) -> None:
        fw, docker, docker_ip, ssh_inst, ssh_on, sshd, nkeys, remote, hardened, aa = res
        self.fw, self.docker = fw, docker
        clear(self.net_box)
        self.show_firewall(fw)
        self._docker_group(fw, docker, docker_ip)
        self._ssh_group(ssh_inst, ssh_on, sshd, nkeys, remote, hardened)
        self._apparmor_group(aa)
        self._remeasure()

    def show_firewall(self, fw) -> None:
        if fw is None:
            return
        on = fw.level == "ok"

        def toggle(want: bool, settle) -> None:
            if want:
                self.run("Turn on the firewall", fw.steps or security._ufw_enable_steps(), "Blocks incoming connections from other devices. "
                         "Everything you do on the internet keeps working.", ok_label="Turn on", done=settle)
            else:
                self.run("Turn off the firewall", [Step("Turn firewall off", ["ufw", "disable"], root=True)],
                         "Anything listening on this PC becomes reachable from your Wi-Fi.", danger=True, ok_label="Turn off", done=settle)
        g = group("Firewall", "Blocks other devices on your network from connecting to this PC. Your own browsing isn't affected.",
                  switch_row("Firewall (ufw)", fw.detail, on, toggle),
                  action_row("Rules", "Exceptions that let other devices in (reading them needs your password).",
                             button("Show rules", css="flat", on_click=self.load_rules),
                             button("Allow a port…", css="flat", on_click=self.add_rule)))
        self.net_box.append(g)
        clear(self.rules_holder)
        self.rules_holder.set_visible(False)
        self.net_box.append(self.rules_holder)

    def load_rules(self) -> None:
        clear(self.rules_holder)
        self.rules_holder.set_visible(True)
        self.rules_holder.append(label("Reading rules…", "dim"))
        capture([Step("Read firewall rules", ["ufw", "status", "numbered"], root=True)], self.show_rules)

    def show_rules(self, ok: bool, lines: list[str]) -> None:
        clear(self.rules_holder)
        if not ok:
            self.rules_holder.append(label("Couldn't read the rules (password cancelled or ufw missing).", "dim"))
            return
        rules = security.parse_ufw_rules("\n".join(lines))
        status = next((ln for ln in lines if ln.startswith("Status:")), "")
        rows = []
        for r in rules:
            rm = button(icon="user-trash-symbolic", css="flat", tooltip="Delete this rule",
                        on_click=lambda n=r["num"], rr=r: self.run(f"Delete rule {n}", [security.ufw_delete_step(n)],
                                                                   f"{rr['action']} {rr['to']} from {rr['from']}", danger=True, ok_label="Delete",
                                                                   reload=False, done=lambda ok: ok and self.load_rules()))
            rows.append(action_row(f"{r['action'].title()} {r['to']}", f"from {r['from']}  ·  rule {r['num']}", rm))
        if not rows:
            rows.append(action_row("No exceptions", status or "Nothing is allowed in."))
        self.rules_holder.append(group("", "", *rows))

    def add_rule(self) -> None:
        def got(text: str | None) -> None:
            if not text:
                return
            port, _, proto = text.partition("/")
            if not port.replace(":", "").isdigit():
                self.toast("Enter a port number like 3000 or 5173/tcp.")
                return
            self.run(f"Allow port {port}", security.ufw_allow_steps(port, proto or "tcp", True),
                     "Only devices on your local network (home or office) can connect, not the whole internet.", ok_label="Allow",
                     reload=False, done=lambda ok: ok and self.load_rules())
        ask_text(self.win, "Allow a port", "For example 3000 to test a dev server from your phone. Local network only.", "3000", got, ok_label="Allow")

    def _docker_group(self, fw, docker, docker_ip: str) -> None:
        state, ports = docker
        if state == "missing":
            return
        desc = ("Docker lets other devices reach a container's port by adding its own network rules, and those skip the firewall above. "
                "Binding ports to 127.0.0.1 keeps them on this PC.")
        rows = []
        fw_on = fw is not None and fw.level == "ok"
        exposed = [p for p in ports if p.exposed]
        if state == "no-access":
            rows.append(action_row("Couldn't list your containers", "Your account isn't allowed to talk to Docker.", prefix=status_icon("info")))
        elif state == "not-running":
            rows.append(action_row("Docker isn't running", "No containers can be reached.", prefix=status_icon("ok")))
        elif not exposed:
            rows.append(action_row("Only this PC can reach your containers" if ports else "No container shares a port",
                                   ", ".join(f"{p.container} → {p.host_ip}:{p.host_port}" for p in ports[:6]), prefix=status_icon("ok")))
        seen = set()
        for p in exposed:
            if (p.container, p.host_port) in seen:
                continue
            seen.add((p.container, p.host_port))
            db = security.DB_PORTS.get(p.container_port)
            sub = (f"{p.image} · port {p.host_port} → {p.container_port}/{p.proto} · " +
                   ("the firewall does NOT block it" if fw_on else "reachable from your Wi-Fi") + (f" · {db} database" if db else ""))
            rows.append(action_row(p.container, sub,
                                   button("How to fix", css="flat", on_click=lambda: self.text("Keep Docker ports on this PC",
                                                                                           security.docker_fix_text(self.docker[1]))),
                                   button("Stop", css="flat", tooltip="Stop this container (start it again with docker start)",
                                          on_click=lambda n=p.container: self.run(f"Stop {n}", [Step(f"Stop container {n}", ["docker", "stop", n])],
                                                                                  "It stops listening right away. Start it again with docker start.",
                                                                                  ok_label="Stop", reload=False, done=lambda ok: ok and self.load_network())),
                                   prefix=status_icon("bad" if db else "warn")))
        if docker_ip == "127.0.0.1":
            rows.append(action_row("Docker's default: only this PC", "New containers share ports with this PC only (set in /etc/docker/daemon.json).",
                                   button("Undo", css="flat", on_click=lambda: self.run(
                                       "Let Docker share ports with your network again", security.docker_localhost_steps(False),
                                       "Restarts Docker; running containers restart too.", ok_label="Undo", reload=False,
                                       done=lambda ok: ok and self.load_network())), prefix=status_icon("ok")))
        suffix = _centred(button("Only this PC", css="suggested-action", on_click=self.docker_localhost)) \
            if exposed and docker_ip != "127.0.0.1" else None
        self.net_box.append(group("Docker and the firewall", desc, *rows, suffix=suffix))

    def docker_localhost(self) -> None:
        self.run("Keep Docker ports on this PC", security.docker_localhost_steps(True),
                 "Makes 127.0.0.1 (this PC only) Docker's default for published ports, then restarts Docker so running containers pick it up. "
                 "Apps on this PC still reach them at localhost; your phone or other computers no longer can. "
                 "Ports you gave an explicit address (like 0.0.0.0:8080:80) stay as they are.",
                 ok_label="Restart Docker", reload=False, done=lambda ok: ok and self.load_network())

    def _ssh_group(self, installed: bool, active: bool, sshd: dict, nkeys: int, remote: list, hardened: bool) -> None:
        desc = "Lets other computers log in to this one over the network. Only needed if you connect to this PC from elsewhere."
        if not installed:
            self.net_box.append(group("SSH server", desc, action_row("Not installed", "Nobody can log in to this PC over the network.",
                                                                     prefix=status_icon("ok"))))
            return
        rows = []
        last = remote[0] if remote else None
        used = (f"Last remote login: {last['user']} from {last['from']}, {last['when'][:16]}." if last else "No remote logins recorded recently.")
        if active:
            rows.append(action_row("SSH server is on", used + ("" if last else " If you don't use it, turn it off."),
                                   button("Turn off", css="flat", on_click=lambda: self.run(
                                       "Turn off the SSH server", security.ssh_off_steps(), "Nobody can log in over the network afterwards. "
                                       "You can turn it on again with: sudo systemctl enable --now ssh", ok_label="Turn off", reload=False,
                                       done=lambda ok: ok and self.load_network())), prefix=status_icon("warn" if not last else "info")))
        else:
            rows.append(action_row("SSH server is installed but off", "Nobody can log in over the network. " + used, prefix=status_icon("ok")))
        items = security.ssh_hardening(sshd) if sshd else []
        for c in items:
            rows.append(action_row(c.title, c.detail, prefix=status_icon(c.level)))
        todo = [c for c in items if c.level in ("bad", "warn")]
        keys_note = (f"You have {nkeys} SSH key{'s' if nkeys != 1 else ''} that can log in, so password login will be turned off."
                     if nkeys else "No SSH key can log in to this PC yet, so password login stays on (otherwise you'd lock yourself out). "
                                   "Add your key to ~/.ssh/authorized_keys first.")
        if hardened:
            rows.append(action_row("Safer settings are on", f"Saved in {security.HARDEN_FILE}.",
                                   button("Undo", css="flat", on_click=lambda: self.run(
                                       "Remove the safer SSH settings", security.ssh_unharden_steps(), "SSH goes back to its previous settings.",
                                       ok_label="Undo", reload=False, done=lambda ok: ok and self.load_network())), prefix=status_icon("ok")))
        suffix = None
        if todo:
            suffix = _centred(button("Make safer", css="suggested-action", on_click=lambda: self.run(
                "Make the SSH server safer", security.ssh_harden_steps(nkeys),
                "Turns off root login and empty passwords and limits password guesses. " + keys_note +
                " The new settings are checked with sshd -t and removed again if SSH doesn't accept them.",
                ok_label="Make safer", reload=False, done=lambda ok: ok and self.load_network())))
        src = "" if not sshd else (" Read from " + ("sshd -T." if sshd.get("source") == "sshd -T" else "/etc/ssh/sshd_config and sshd_config.d."))
        self.net_box.append(group("SSH server", desc + src, *rows, suffix=suffix))

    def _apparmor_group(self, st: dict) -> None:
        c = security.apparmor(st)
        counts = st.get("counts") or {}
        btns = [button("Details", css="flat", tooltip="Lists every app rule set (needs your password)", on_click=self.apparmor_details)] \
            if has("aa-status") else []
        if c.steps:
            btns.append(button(c.fix_label, css="suggested-action", on_click=lambda: self.run(c.fix_label, c.steps, c.detail, ok_label=c.fix_label)))
        extra = ""
        if counts.get("unconfined"):
            extra = f" {counts['unconfined']} more are known but allowed to do anything (normal on Ubuntu for apps like browsers)."
        self.net_box.append(group("App protection (AppArmor)", "Puts apps in a safety box: if one gets hacked it can only touch what it needs.",
                                  action_row("Status", c.detail + extra, *btns, prefix=status_icon(c.level))))

    def apparmor_details(self) -> None:
        def done(ok: bool, lines: list[str]) -> None:
            if ok:
                self.text("AppArmor status", "\n".join(lines))
            else:
                self.toast("Couldn't read AppArmor's status (password cancelled?).")
        capture([Step("Read AppArmor status", ["aa-status"], root=True)], done)

    # ---------------------------------------------------------------- virus scan (M5)
    def load_virus(self) -> None:
        self.loading(self.virus_box)
        self.bg(antivirus.status, self.show_virus)

    def show_virus(self, st: dict) -> None:
        self.av = st
        box = self.virus_box
        clear(box)
        self._remeasure()
        box.append(label("Linux rarely gets viruses, so you don't need a scanner running all the time. A scan is useful for files you "
                         "downloaded and will pass on to Windows or Mac users (installers, email attachments, files from USB sticks). "
                         "It uses ClamAV, the free open-source scanner.", "subtle", wrap=True))
        if not st.get("installed"):
            box.append(group("ClamAV isn't installed", "About 250 MB with its virus list, which updates itself every day.",
                             action_row("Install the virus scanner", "Installs clamav and clamav-freshclam from Ubuntu.",
                                        button("Install", css="suggested-action", on_click=lambda: self.run(
                                            "Install ClamAV", antivirus.install_steps(),
                                            "The virus list downloads in the background after installing; give it a few minutes before your first scan.",
                                            ok_label="Install", reload=False, done=lambda ok: ok and self.load_virus())),
                                        prefix=status_icon("info"))))
            return
        age = st.get("age_days")
        if not st.get("db_files") and age is None:
            db_text, lvl = "Not downloaded yet. Scans can't run until it is.", "warn"
        elif age is None:
            db_text, lvl = "Downloaded (date unknown).", "info"
        else:
            when = time.strftime("%d %b %Y", time.localtime(st["date"]))
            db_text = f"Version {st['db'] or '?'} from {when} ({'today' if age < 1 else f'{age:.0f} days old'})."
            lvl = "ok" if age < 3 else "warn"
        upd = {"active": "Updates itself automatically.", "inactive": "The automatic updater is off."}.get(st.get("updater", ""), "")
        scan_btn = button("Scan Downloads", icon="system-search-symbolic", css=["suggested-action", "pill"],
                          on_click=lambda: self.scan_folder(st.get("downloads") or antivirus.downloads()))
        other_btn = button("Scan another folder…", css="pill", on_click=self.pick_folder)
        box.append(card(hbox(vbox(label("Scan for viruses", "mid-num"),
                                  label(f"Checks every file in {secrets.short(st.get('downloads', '~/Downloads'))} and its subfolders. Loading the virus list takes "
                                        "about a minute; nothing is changed or deleted without asking.", "subtle", wrap=True), spacing=4),
                             spacing=12), hbox(scan_btn, other_btn, spacing=8), spacing=12))
        box.append(group("Virus list", f"ClamAV {st.get('engine', '')}".strip(),
                         action_row("Virus definitions", f"{db_text} {upd}".strip(),
                                    button("Update now", css="flat", on_click=lambda: self.run(
                                        "Update the virus list", antivirus.update_db_steps(), "Downloads the newest virus definitions (a few MB).",
                                        ok_label="Update", reload=False, done=lambda ok: ok and self.load_virus())),
                                    prefix=status_icon(lvl))))
        last = st.get("last")
        if last:
            infected = last["infected"]
            when = ago(last["started"])
            if last["finished"] is None:
                rows = [action_row("The last scan didn't finish", f"{secrets.short(last['folder'])} · started {when}", prefix=status_icon("info"))]
            elif not last["found"]:
                rows = [action_row("Nothing infected found", f"{secrets.short(last['folder'])} · scanned {when}", prefix=status_icon("ok"))]
            else:
                gone = len(last["found"]) - len(infected)
                rows = [action_row(os.path.basename(x["path"]), f"{x['virus']} · {secrets.short(x['path'])}",
                                   button("Move to Trash", css="flat", on_click=lambda p=x["path"]: self.trash([p])), prefix=status_icon("bad"))
                        for x in infected]
                if gone:
                    rows.append(action_row(f"{gone} already removed", "Moved or deleted since the scan.", prefix=status_icon("ok")))
            suffix = _centred(button("Move all to Trash", css="destructive-action", on_click=lambda: self.trash([x["path"] for x in last["infected"]]))) \
                if last.get("infected") and len(last["infected"]) > 1 else None
            box.append(group("Last scan", f"{len(last['found'])} infected file{'s' if len(last['found']) != 1 else ''} found in {secrets.short(last['folder'])}"
                             if last["found"] else "", *rows, suffix=suffix))

    def scan_folder(self, folder: str) -> None:
        if not antivirus.installed():
            self.show_tab("virus")
            self.toast("Install ClamAV first (button below).", 4)
            return
        if not os.path.isdir(folder):
            self.toast(f"{folder} doesn't exist.")
            return
        self.run(f"Scan {os.path.basename(folder) or folder} for viruses", antivirus.scan_steps(folder),
                 "Checks every file with ClamAV. Loading the virus list takes about a minute and a lot of memory (around 1 GB); "
                 "big folders take longer. Nothing is deleted.", ok_label="Scan", reload=False, done=lambda _ok: self.load_virus())

    def pick_folder(self) -> None:
        if not hasattr(Gtk, "FileDialog"):
            self.toast("The folder picker needs a newer GTK.")
            return
        d = Gtk.FileDialog(title="Pick a folder to scan")

        def picked(dlg, res) -> None:
            try:
                f = dlg.select_folder_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                self.scan_folder(f.get_path())
        d.select_folder(self.win, None, picked)

    def trash(self, paths: list[str]) -> None:
        if not paths:
            return
        self.run("Move infected files to the Trash", antivirus.trash_steps(paths),
                 "They go to the Trash, so you can still restore them. Empty the Trash to delete them for good.",
                 ok_label="Move to Trash", reload=False, done=lambda ok: ok and self.load_virus())

    # ---------------------------------------------------------------- accounts, SSH keys, logins (M6)
    def load_accounts(self) -> None:
        self.loading(self.acc_box)
        self.bg(lambda: (accounts.accounts(), ssh_keys(), authorized_keys(),
                         out(["last", "-n", "12", "-w"], timeout=10),
                         out(["journalctl", "-b", "--no-pager", "-q", "-g", "authentication failure|Failed password", "-n", "200"], timeout=15)),
                self.show_accounts)

    def show_accounts(self, res) -> None:
        accts, keys, auth, last, fails = res
        box = self.acc_box
        clear(box)
        warns = accounts.checks(accts)
        if warns:
            box.append(group("Worth a look", "", *[action_row(t, d, prefix=status_icon(lvl)) for lvl, t, d in warns]))
        rows = []
        for a in accts:
            bits = []
            if a.uid == 0:
                bits.append("the built-in admin account; Ubuntu keeps it locked and uses sudo instead")
            elif a.full_name and a.full_name != a.name:
                bits.append(a.full_name)
            if a.last_login:
                bits.append("never logged in" if a.last_login == "Never" else f"last login {a.last_login}" + (f" from {a.last_from}" if a.last_from else ""))
            pw = {"set": "", "locked": "password login locked", "none": "NO PASSWORD"}.get(a.password, "")
            if pw and not (a.uid == 0 and a.password == "locked"):
                bits.append(pw)
            if a.uid == 0 and a.password == "locked":
                bits[0] = "the built-in admin account; locked (normal on Ubuntu)"
            suffix = []
            if a.me:
                suffix.append(pill("You", "accent"))
            if a.admin and a.uid != 0:
                suffix.append(pill("Admin", "warn"))
            for r in a.rootish if not a.admin else []:
                suffix.append(pill(f"{r}: admin-like", "info"))
            if a.password == "none":
                suffix.append(pill("No password", "bad"))
            icon = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
            rows.append(action_row(a.name, " · ".join(bits), *suffix, prefix=icon))
        people = [a for a in accts if a.uid != 0]
        admins = [a for a in people if a.admin]
        desc = (f"{len(people)} account{'s' if len(people) != 1 else ''} can log in; {len(admins)} {'is an admin' if len(admins) == 1 else 'are admins'} "
                "(can install software and change anything). Service accounts that can't log in are hidden.")
        manage = _centred(button("Users settings", css="flat", on_click=lambda: launch(["gnome-control-center", "users"]))) \
            if has("gnome-control-center") else None
        box.append(group("Who can log in", desc, *rows, suffix=manage) if rows else
                   group("Who can log in", "", action_row("Couldn't read the account list", "", prefix=status_icon("info"))))
        self._ssh_keys_group(keys, auth)
        nfail = len([ln for ln in fails.splitlines() if ln.strip()])
        acc = [action_row("Failed password attempts since boot", str(nfail) + (" (someone typed a wrong password, or something is guessing)" if nfail > 5 else ""),
                          button("View", css="flat", on_click=lambda: self.text("Failed logins", fails or "None")), prefix=status_icon("warn" if nfail > 10 else "ok")),
               action_row("Recent logins", next((ln for ln in last.splitlines() if ln.strip() and not ln.startswith(("wtmp", "reboot"))),
                                                "None recorded")[:120], button("View", css="flat", on_click=lambda: self.text("Recent logins", last)),
                          prefix=status_icon("info"))]
        box.append(group("Logins", "", *acc))
        self._remeasure()

    def _ssh_keys_group(self, keys: list, auth: int) -> None:
        rows = []
        for k in keys:
            weak = k["type"] in ("DSA",) or (k["type"] == "RSA" and k["bits"].isdigit() and int(k["bits"]) < 3072)
            perm = "" if k["private_ok"] in (True, None) else "  ·  private key is readable by others: fix permissions!"
            sub = f"{k['type']} {k['bits']} bits" + (f" · {k['comment']}" if k["comment"] else "") + (" · weak, make a new ed25519 key" if weak else "") + perm
            btns = [button("Copy public key", css="flat", on_click=lambda f=k["file"]: (self.get_clipboard().set(open(f).read().strip()), self.toast("Public key copied. Paste it into GitHub → Settings → SSH keys.")))]
            if k["private_ok"] is False:
                btns.append(button("Fix", css="suggested-action", on_click=lambda f=k["file"][:-4]: self.run("Fix key permissions", [Step("Make the private key private", ["chmod", "600", f])])))
            rows.append(action_row(k["name"], sub, *btns, prefix=status_icon("warn" if weak or perm else "ok")))
        if not rows:
            rows.append(action_row("No SSH keys yet", "You need one to push to GitHub over SSH.",
                                   button("Create key", css="suggested-action", on_click=self.make_key)))
        else:
            rows.append(action_row("Create another key", "ed25519, the modern default.", button("Create", css="flat", on_click=self.make_key)))
        self.acc_box.append(group("Your SSH keys", f"Keys in ~/.ssh. {auth} key{'s' if auth != 1 else ''} can log in to this PC (authorized_keys)." if auth else
                                  "Keys in ~/.ssh. No one can log in to this PC with a key.", *rows))

    def make_key(self) -> None:
        def got(email: str | None) -> None:
            if email is None:
                return
            path = HOME / ".ssh/id_ed25519"
            n = 1
            while path.exists():
                path = HOME / f".ssh/id_ed25519_{n}"
                n += 1
            (HOME / ".ssh").mkdir(mode=0o700, exist_ok=True)
            r = sh(["ssh-keygen", "-t", "ed25519", "-C", email, "-f", str(path), "-N", ""], timeout=20)
            if r.ok:
                self.get_clipboard().set(open(str(path) + ".pub").read().strip())
                self.toast(f"Created {path.name}. Public key copied: paste it into GitHub → Settings → SSH keys.", 6)
                self.tab_loaded.discard("accounts")
                self.load_accounts()
            else:
                self.toast(f"Couldn't create key: {r.err.strip()[:120]}")
        ask_text(self.win, "Create an SSH key", "Label it with your email (shown on GitHub). No passphrase, stored in ~/.ssh.", "you@example.com", got,
                 ok_label="Create")


PAGE = SecurityPage
