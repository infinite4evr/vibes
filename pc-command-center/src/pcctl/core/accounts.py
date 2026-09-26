"""User accounts: who can log in, who is an admin, when they last logged in (like Cockpit's Accounts page). Read-only."""

from __future__ import annotations

import os
import pwd
import re
from dataclasses import dataclass, field

from .run import has, out, read, sh

ADMIN_GROUPS = ("sudo", "admin", "wheel")
# Groups that quietly give admin-level power without a password prompt.
ROOTISH = {"docker": "Docker", "lxd": "LXD", "incus-admin": "Incus", "libvirt": "virtual machines (libvirt)", "disk": "raw disk access"}
NO_LOGIN = ("nologin", "false", "sync", "shutdown", "halt")
DATE_RX = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w{3}\s+\d{1,2}\s+\d\d:\d\d(?::\d\d)?(?:\s+[+-]\d{4})?(?:\s+\d{4})?")


@dataclass
class Account:
    name: str
    uid: int
    gid: int
    full_name: str
    home: str
    shell: str
    groups: list[str] = field(default_factory=list)
    admin: bool = False
    rootish: list[str] = field(default_factory=list)
    last_login: str = ""      # "" unknown, "Never", or a date
    last_from: str = ""
    password: str = ""        # set | locked | none | "" (unknown without admin rights)
    me: bool = False

    @property
    def can_login(self) -> bool:
        return not self.shell.rstrip("/").endswith(NO_LOGIN)

    @property
    def is_human(self) -> bool:
        return 1000 <= self.uid < 60000


def parse_passwd(text: str) -> list[dict]:
    res = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 7 or line.startswith("#"):
            continue
        try:
            uid, gid = int(parts[2]), int(parts[3])
        except ValueError:
            continue
        res.append({"name": parts[0], "uid": uid, "gid": gid, "full_name": parts[4].split(",")[0], "home": parts[5], "shell": parts[6].strip()})
    return res


def parse_group(text: str) -> tuple[dict[str, list[str]], dict[int, str]]:
    """/etc/group -> ({group: [members]}, {gid: group})."""
    members: dict[str, list[str]] = {}
    by_gid: dict[int, str] = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        members[parts[0]] = [m for m in parts[3].strip().split(",") if m]
        try:
            by_gid[int(parts[2])] = parts[0]
        except ValueError:
            pass
    return members, by_gid


def parse_shadow(text: str) -> dict[str, str]:
    """/etc/shadow (only readable as admin) -> {name: set|locked|none}."""
    res = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        h = parts[1]
        res[parts[0]] = "none" if h == "" else "locked" if h.startswith(("!", "*")) else "set"
    return res


def parse_passwd_status(text: str) -> str:
    """`passwd -S name` -> set | locked | none | ''."""
    parts = text.split()
    if len(parts) < 2:
        return ""
    return {"P": "set", "PS": "set", "L": "locked", "LK": "locked", "NP": "none"}.get(parts[1], "")


def parse_lastlog(text: str) -> dict[str, tuple[str, str]]:
    """`lastlog` / `lastlog2` -> {name: (when, from)}. 'Never' when the user never logged in."""
    res = {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        name = line.split()[0]
        if "Never logged in" in line:
            res[name] = ("Never", "")
            continue
        m = DATE_RX.search(line)
        if not m:
            continue
        before = line[:m.start()].split()[1:]
        frm = next((p for p in before if re.fullmatch(r"[\d.]+|[0-9a-fA-F:]+:[0-9a-fA-F:]*|[\w.-]+\.\w+", p) and not p.startswith(("tty", "pts", ":"))), "")
        res[name] = (_tidy_date(m.group(0)), frm)
    return res


def parse_last(text: str) -> dict[str, tuple[str, str]]:
    """`last -w` (newest first) -> {name: (when, from)} for each user's most recent login."""
    res: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith(("wtmp", "reboot", "shutdown", "btmp")):
            continue
        name = line.split()[0]
        if name in res:
            continue
        m = DATE_RX.search(line)
        if not m:
            continue
        cols = line[:m.start()].split()
        frm = cols[2] if len(cols) >= 3 and not cols[2].startswith(("tty", ":", "0.0.0.0")) else ""
        res[name] = (_tidy_date(m.group(0)), frm)
    return res


def _tidy_date(s: str) -> str:
    s = re.sub(r"\s+[+-]\d{4}", "", s)          # drop the time-zone offset
    s = re.sub(r"(\d\d:\d\d):\d\d", r"\1", s)    # and the seconds
    return " ".join(s.split())


def last_logins() -> dict[str, tuple[str, str]]:
    for cmd, parser in ((["lastlog2"], parse_lastlog), (["lastlog"], parse_lastlog), (["last", "-w", "-n", "500"], parse_last)):
        if has(cmd[0]):
            text = out(cmd, timeout=10)
            if text:
                data = parser(text)
                if data:
                    return data
    return {}


def build(passwd_text: str, group_text: str, me: str = "", shadow: dict | None = None, logins: dict | None = None) -> list[Account]:
    """Accounts that can log in (people plus root), with admin status and last login."""
    members, by_gid = parse_group(group_text)
    res = []
    for u in parse_passwd(passwd_text):
        acct = Account(u["name"], u["uid"], u["gid"], u["full_name"], u["home"], u["shell"], me=u["name"] == me)
        if not (acct.uid == 0 or (acct.is_human and acct.can_login)):
            continue
        acct.groups = sorted({g for g, ms in members.items() if acct.name in ms} | ({by_gid[acct.gid]} if acct.gid in by_gid else set()))
        acct.admin = acct.uid == 0 or any(g in acct.groups for g in ADMIN_GROUPS)
        acct.rootish = [ROOTISH[g] for g in acct.groups if g in ROOTISH]
        if shadow and acct.name in shadow:
            acct.password = shadow[acct.name]
        if logins and acct.name in logins:
            acct.last_login, acct.last_from = logins[acct.name]
        res.append(acct)
    res.sort(key=lambda a: (a.uid == 0, not a.me, a.uid))
    return res


def accounts() -> list[Account]:
    me = pwd.getpwuid(os.getuid()).pw_name if hasattr(os, "getuid") else ""
    shadow_text = read("/etc/shadow")
    shadow = parse_shadow(shadow_text) if shadow_text else {}
    accts = build(read("/etc/passwd"), read("/etc/group"), me, shadow, last_logins())
    if not shadow and has("passwd"):
        for a in accts:
            if a.me:
                r = sh(["passwd", "-S", a.name], timeout=5)
                a.password = parse_passwd_status(r.out) if r.ok else ""
    return accts


def checks(accts: list[Account]) -> list[tuple[str, str, str]]:
    """Warnings worth showing: (level, title, detail)."""
    res = []
    for a in accts:
        if a.password == "none" and a.can_login:
            res.append(("bad", f"{a.name} has no password", f"Anyone at this PC can log in as {a.name}. Set a password in Settings → Users."))
    people_admins = [a for a in accts if a.admin and a.uid != 0]
    if len(people_admins) > 1:
        res.append(("info", f"{len(people_admins)} accounts are admins", f"{', '.join(a.name for a in people_admins)} can each change anything on "
                    "this PC. Give admin rights only to people who need them (Settings → Users → Administrator)."))
    for a in accts:
        if a.rootish and not a.admin:
            res.append(("warn", f"{a.name} has hidden admin power", f"Being in the {', '.join(a.rootish)} group lets {a.name} take full control "
                        "of this PC without a password."))
    root = next((a for a in accts if a.uid == 0), None)
    if root and root.password in ("set", "none"):
        res.append(("info", "The root account has a password", "Ubuntu normally keeps root locked and uses sudo instead. "
                    "That's fine if you set it on purpose."))
    return res
