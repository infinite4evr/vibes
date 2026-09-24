"""Security: score + checklist with one-click fixes, firewall and its rules, SSH keys, accounts and logins."""

from __future__ import annotations

import glob
import os

from gi.repository import Gtk

from ...core import security
from ...core.run import HOME, Step, out, sh
from ..dialogs import ask_text
from ..runner import capture
from ..util import button, clear, hbox, label, status_icon, vbox
from ..widgets import RingGauge, card
from .base import Page, action_row, group, switch_row


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
    try:
        return sum(1 for ln in (HOME / ".ssh/authorized_keys").read_text().splitlines() if ln.strip() and not ln.startswith("#"))
    except OSError:
        return 0


class SecurityPage(Page):
    ID = "security"
    TITLE = "Security"
    ICON = "security-high-symbolic"
    SUBTITLE = "A checklist in plain language with one-click fixes, plus the firewall, SSH keys and who can log in."

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
        self.checks_holder = vbox()
        self.body.append(self.checks_holder)
        self.fw_holder = vbox()
        self.body.append(self.fw_holder)
        self.rules_holder = vbox()
        self.extra_holder = vbox(spacing=18)
        self.body.append(self.extra_holder)
        self.checks: list = []

    def load(self) -> None:
        self.title.set_text("Checking…")
        self.bg(security.all_checks, self.show)
        self.bg(lambda: (ssh_keys(), authorized_keys(), out(["getent", "group", "sudo"]), out(["last", "-n", "12", "-w"], timeout=10),
                         out(["journalctl", "-b", "--no-pager", "-q", "-g", "authentication failure|Failed password", "-n", "200"], timeout=15)),
                self.show_extra)

    def show(self, checks: list) -> None:
        self.checks = checks
        score = security.score(checks)
        todo = [c for c in checks if c.level in ("bad", "warn")]
        self.gauge.set(score, str(score), "security", "green" if score >= 85 else ("peach" if score >= 60 else "red"))
        self.title.set_text("Well protected" if not todo else f"{len(todo)} thing{'s' if len(todo) != 1 else ''} to improve")
        self.sub.set_text("Nothing urgent. Keep updates on and you're good." if not todo else
                          "Each item says what it means for you. Fixes show the exact commands before running.")
        fixable = [c for c in todo if c.steps and c.id not in ("reboot",)]
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
        self.show_firewall(next((c for c in checks if c.id == "firewall"), None))

    def fix(self, c) -> None:
        if c.goto:
            self.win.goto(c.goto)
        else:
            self.run(c.fix_label or c.title, c.steps, c.detail, ok_label=c.fix_label or "Fix")

    def fix_all(self) -> None:
        steps = [s for c in self.checks if c.level in ("bad", "warn") and c.steps and c.id != "reboot" for s in c.steps]
        self.run("Fix security issues", steps, "Applies every recommended fix below in one go.", ok_label="Fix all")

    # ---------------------------------------------------------------- firewall
    def show_firewall(self, fw) -> None:
        clear(self.fw_holder)
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
        self.fw_holder.append(g)
        self.fw_holder.append(self.rules_holder)

    def load_rules(self) -> None:
        clear(self.rules_holder)
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

    # ---------------------------------------------------------------- keys, accounts, logins
    def show_extra(self, res) -> None:
        keys, auth, sudo_line, last, fails = res
        clear(self.extra_holder)
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
        self.extra_holder.append(group("Your SSH keys", f"Keys in ~/.ssh. {auth} key{'s' if auth != 1 else ''} can log in to this PC (authorized_keys)." if auth else
                                       "Keys in ~/.ssh. No one can log in to this PC with a key.", *rows))

        admins = sudo_line.split(":")[-1].split(",") if sudo_line else []
        nfail = len([ln for ln in fails.splitlines() if ln.strip()])
        acc = [action_row("Admins", ", ".join(a for a in admins if a) or "?", prefix=status_icon("ok" if len(admins) <= 2 else "info")),
               action_row("Failed password attempts since boot", str(nfail) + (" (someone typed a wrong password, or something is guessing)" if nfail > 5 else ""),
                          button("View", css="flat", on_click=lambda: self.text("Failed logins", fails or "None")), prefix=status_icon("warn" if nfail > 10 else "ok")),
               action_row("Recent logins", (last.splitlines()[0] if last else "?")[:120], button("View", css="flat", on_click=lambda: self.text("Recent logins", last)),
                          prefix=status_icon("info"))]
        self.extra_holder.append(group("Accounts and logins", "", *acc))

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
                self.load()
            else:
                self.toast(f"Couldn't create key: {r.err.strip()[:120]}")
        ask_text(self.win, "Create an SSH key", "Label it with your email (shown on GitHub). No passphrase, stored in ~/.ssh.", "you@example.com", got,
                 ok_label="Create")


PAGE = SecurityPage
