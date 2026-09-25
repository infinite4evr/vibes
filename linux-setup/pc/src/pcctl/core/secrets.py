"""Secrets check: API keys, tokens and passwords left where they shouldn't be (like gitleaks / trufflehog, for your PC).

Looks in three places:
- command history (bash, zsh, fish, Python, Node, database shells),
- project folders: `.env` files git would upload (or already has), private keys and token files inside projects,
- your home folder: credential files other accounts can read, plaintext Git passwords, SSH keys without a passphrase.

A secret is never shown in full: mask() keeps the first 4 and last 2 characters. Nothing leaves the PC.
Use scan() -> list[Finding] and format_text(findings); `python -m pcctl.core.secrets` prints a report.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import run as _run
from .run import Step, py_step, sh

LEVELS = {"bad": 0, "warn": 1, "info": 2}
BACKUP_DIR_NAME = ".local/state/pc/history-backups"


# ---------------------------------------------------------------- what a secret looks like

@dataclass
class Rule:
    id: str
    name: str
    pattern: str
    group: int = 0
    rotate: str = ""        # where to make a new key and revoke the leaked one
    generic: bool = False   # a guess from context ("PASSWORD=…") rather than a known token format
    flags: int = 0

    def __post_init__(self) -> None:
        self.rx = re.compile(self.pattern, self.flags)


SECRET_NAME = r"[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_PASSWD|APIKEY|PASSWORD|SECRET|TOKEN)"

# Specific formats first: when two rules match the same text the earlier one wins.
RULES: list[Rule] = [
    Rule("private-key", "Private key", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    Rule("anthropic", "Anthropic (Claude) API key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}", rotate="https://console.anthropic.com/settings/keys"),
    Rule("openrouter", "OpenRouter API key", r"\bsk-or-v1-[A-Za-z0-9]{32,}", rotate="https://openrouter.ai/settings/keys"),
    Rule("openai", "OpenAI API key", r"\bsk-(?!ant-|or-v1-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}", rotate="https://platform.openai.com/api-keys"),
    Rule("github", "GitHub token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}", rotate="https://github.com/settings/tokens"),
    Rule("github-pat", "GitHub token", r"\bgithub_pat_[A-Za-z0-9_]{22,}", rotate="https://github.com/settings/personal-access-tokens"),
    Rule("gitlab", "GitLab token", r"\bglpat-[A-Za-z0-9_\-]{20,}", rotate="https://gitlab.com/-/user_settings/personal_access_tokens"),
    Rule("aws", "AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", rotate="https://console.aws.amazon.com/iam/home#/security_credentials"),
    Rule("google", "Google API key", r"\bAIza[0-9A-Za-z_\-]{35}", rotate="https://console.cloud.google.com/apis/credentials"),
    Rule("slack", "Slack token", r"\bxox[baprs]-[0-9A-Za-z\-]{10,}", rotate="https://api.slack.com/apps"),
    Rule("stripe", "Stripe live secret key", r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}", rotate="https://dashboard.stripe.com/apikeys"),
    Rule("huggingface", "Hugging Face token", r"\bhf_[A-Za-z0-9]{30,}", rotate="https://huggingface.co/settings/tokens"),
    Rule("npm", "npm token", r"\bnpm_[A-Za-z0-9]{36}\b", rotate="https://docs.npmjs.com/revoking-access-tokens"),
    Rule("groq", "Groq API key", r"\bgsk_[A-Za-z0-9]{40,}", rotate="https://console.groq.com/keys"),
    Rule("replicate", "Replicate token", r"\br8_[A-Za-z0-9]{30,}", rotate="https://replicate.com/account/api-tokens"),
    Rule("sendgrid", "SendGrid API key", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{30,}", rotate="https://app.sendgrid.com/settings/api_keys"),
    # generic: judged from the words around it
    Rule("bearer", "Login token in a web request", r"(?i)\bauthorization:\s*(?:bearer|token|basic)\s+([A-Za-z0-9._~+/=\-]{16,})", group=1, generic=True),
    Rule("url-password", "Password inside a web address", r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@'\"]+:([^\s@/'\"]{4,})@[A-Za-z0-9.\-]+",
         group=1, generic=True),
    Rule("mysql", "Database password typed in a command", r"\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n|;&]*?\s(?:-p|--password=)([^\s'\"\-][^\s'\"]*)",
         group=1, generic=True),
    Rule("sshpass", "Password typed in an sshpass command", r"\bsshpass\s+-p\s*['\"]?([^\s'\"]+)", group=1, generic=True),
    Rule("identified-by", "Database password", r"(?i)\bidentified\s+by\s+'([^']{4,})'", group=1, generic=True),
    Rule("assign", "Password or key", SECRET_NAME + r"\s*=\s*['\"]?([^\s'\"$`;|&()]{12,})", group=1, generic=True),
    Rule("fish-set", "Password or key", r"\bset\s+(?:-[a-zA-Z]+\s+)+" + SECRET_NAME + r"\s+['\"]?([^\s'\"$`;|&()]{12,})", group=1, generic=True),
]
RULE_BY_ID = {r.id: r for r in RULES}

PLACEHOLDER = re.compile(r"(?i)your|xxxx|example|placeholder|changeme|change_me|dummy|redacted|replace|insert|sample|<|>|\*\*\*|\.\.\.|…|\{\{|\}\}")
WEAK_DEFAULTS = {"password", "passwd", "postgres", "root", "admin", "secret", "pass", "test", "1234", "12345", "123456", "12345678",
                 "guest", "mysql", "changeit", "letmein", "toor", "user", "demo", "prisma", "docker"}


@dataclass
class Hit:
    rule: Rule
    value: str
    start: int
    end: int


def _placeholder(value: str, whole: str, rule: Rule) -> bool:
    if rule.id == "private-key":
        return False
    if PLACEHOLDER.search(value) or (rule.generic and PLACEHOLDER.search(whole)):
        return True
    if len(set(value)) <= 3:  # "aaaaaaaaaaaa", "000000000000"
        return True
    return rule.generic and value.lower() in WEAK_DEFAULTS


def find_secrets(text: str, rules: list[Rule] | None = None) -> list[Hit]:
    """Every secret-looking value in text, in order. Overlapping matches keep the most specific rule."""
    hits: list[Hit] = []
    taken: list[tuple[int, int]] = []
    for r in rules or RULES:
        for m in r.rx.finditer(text):
            s, e = m.span(r.group)
            value = m.group(r.group)
            if not value or _placeholder(value, m.group(0), r):
                continue
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            hits.append(Hit(r, value, s, e))
    hits.sort(key=lambda h: h.start)
    return hits


def mask(secret: str, generic: bool = False) -> str:
    """Never show a whole secret: first 4 + … + last 2 characters. Passwords (generic matches) show only 2 characters."""
    s = secret.strip()
    if s.startswith("-----BEGIN"):
        return "-----BEGIN … PRIVATE KEY-----"
    if len(s) >= 12 and not generic:
        return f"{s[:4]}…{s[-2:]}"
    if len(s) >= 6:
        return f"{s[:2]}…"
    return "…"


def mask_text(text: str, hits: list[Hit] | None = None) -> str:
    """text with every secret in it masked."""
    hits = find_secrets(text) if hits is None else hits
    out, pos = [], 0
    for h in sorted(hits, key=lambda h: h.start):
        if h.start < pos:
            continue
        out.append(text[pos:h.start])
        out.append(mask(h.value, h.rule.generic))
        pos = h.end
    out.append(text[pos:])
    return "".join(out)


def _context(text: str, s: int, e: int, hits: list[Hit], width: int = 110) -> str:
    """The masked line around a hit, trimmed to `width` characters, without history-format prefixes."""
    ls = text.rfind("\n", 0, s) + 1
    le = text.find("\n", e)
    le = len(text) if le < 0 else le
    line_hits = [Hit(h.rule, h.value, h.start - ls, h.end - ls) for h in hits if h.start >= ls and h.end <= le]
    line = mask_text(text[ls:le], line_hits)
    line = re.sub(r"^: \d+:\d+;", "", line)       # zsh extended history
    line = re.sub(r"^- cmd: ", "", line)           # fish history
    line = line.strip()
    if len(line) > width:
        first = mask(line_hits[0].value, line_hits[0].rule.generic) if line_hits else ""
        at = max(0, line.find(first) - width // 3) if first else 0
        line = ("…" if at else "") + line[at:at + width] + ("…" if at + width < len(line) else "")
    return line


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    id: str
    kind: str                 # history | project | home | ssh
    level: str                # bad | warn | info
    title: str
    detail: str
    path: str = ""
    line: int = 0
    rule: str = ""
    preview: str = ""         # the masked secret
    rotate: str = ""          # web page to make a new key and revoke this one
    fix_label: str = ""
    steps: list[Step] = field(default_factory=list, repr=False)
    terminal: list[str] = field(default_factory=list)   # interactive fix (asks for input) to run in a terminal
    count: int = 1
    raw: str = field(default="", repr=False, compare=False)  # never displayed; used to scrub history

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "level": self.level, "title": self.title, "detail": self.detail, "path": self.path,
                "line": self.line, "rule": self.rule, "preview": self.preview, "rotate": self.rotate, "fix": self.fix_label,
                "terminal": shlex.join(self.terminal) if self.terminal else "", "count": self.count}


def short(path: str | Path, home: Path | None = None) -> str:
    home = home or _run.HOME
    p = str(path)
    h = str(home)
    return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p


def _fid(*parts: str) -> str:
    return hashlib.sha1("\0".join(parts).encode(errors="replace")).hexdigest()[:12]


def _read(path: Path | str, limit: int = 262144, tail: bool = False) -> str:
    try:
        with open(path, "rb") as f:
            if tail:
                size = os.fstat(f.fileno()).st_size
                if size > limit:
                    f.seek(size - limit)
            data = f.read(limit)
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def _chmod_step(path: str, mode: str, title: str) -> Step:
    return Step(title, ["chmod", mode, path])


# ---------------------------------------------------------------- 1. command history

HISTORY_FILES = [
    (".bash_history", "terminal history"), (".zsh_history", "terminal history"), (".zhistory", "terminal history"),
    (".local/share/fish/fish_history", "terminal history"), (".python_history", "Python history"),
    (".node_repl_history", "Node.js history"), (".psql_history", "PostgreSQL history"), (".mysql_history", "MySQL history"),
    (".sqlite_history", "SQLite history"), (".rediscli_history", "Redis history"),
]
HISTORY_MAX = 16 * 1024 * 1024


def history_files(home: Path) -> list[tuple[Path, str]]:
    res: list[tuple[Path, str]] = []
    seen: set[str] = set()
    cands = [(home / rel, where) for rel, where in HISTORY_FILES]
    hf = os.environ.get("HISTFILE")
    if hf and home == _run.HOME:
        cands.append((Path(hf).expanduser(), "terminal history"))
    for p, where in cands:
        try:
            if p.is_file() and str(p.resolve()) not in seen:
                seen.add(str(p.resolve()))
                res.append((p, where))
        except OSError:
            continue
    return res


def scan_history_text(text: str, path: str, where: str, home: Path | None = None) -> list[Finding]:
    """Findings for one history file's text (one per distinct secret)."""
    hits = find_secrets(text)
    if not hits:
        return []
    raws = sorted({h.value for h in hits})
    steps = [scrub_step(path, raws, home)]
    by_value: dict[str, list[tuple[Hit, int]]] = {}
    line, pos = 1, 0
    for h in hits:
        line += text.count("\n", pos, h.start)
        pos = h.start
        by_value.setdefault(h.value, []).append((h, line))
    res = []
    name = short(path, home)
    for value, items in by_value.items():
        h, ln = items[0]
        more = f" (and {len(items) - 1} more time{'s' if len(items) > 2 else ''})" if len(items) > 1 else ""
        ctx = _context(text, h.start, h.end, hits)
        rotate = "Make a new key and delete the old one, then " if h.rule.rotate else "Change it, then "
        res.append(Finding(
            id="history:" + _fid(path, value), kind="history", level="warn" if h.rule.generic else "bad",
            title=f"{h.rule.name} in your {where}",
            detail=f"{name} line {ln}{more}: {ctx}\nAny app running as you can read this file. {rotate}remove it from the history.",
            path=path, line=ln, rule=h.rule.id, preview=mask(value, h.rule.generic), rotate=h.rule.rotate,
            fix_label="Remove from history", steps=steps, count=len(items), raw=value))
    return res


def scan_histories(home: Path) -> list[Finding]:
    res = []
    for p, where in history_files(home):
        res += scan_history_text(_read(p, HISTORY_MAX, tail=True), str(p), where, home)
    return res


def history_format(name: str, lines: list[str]) -> str:
    if "fish_history" in name:
        return "fish"
    if "zsh" in name or "zhistory" in name or any(re.match(r": \d+:\d+;", ln) for ln in lines[:50]):
        return "zsh"
    if name.endswith("bash_history") or any(re.fullmatch(r"#\d{9,11}\n?", ln) for ln in lines[:50]):
        return "bash"
    return "plain"


def split_entries(lines: list[str], fmt: str) -> list[tuple[int, int]]:
    """Group physical lines into history entries: (start, end) index ranges."""
    ents: list[tuple[int, int]] = []
    i, n = 0, len(lines)
    while i < n:
        j = i + 1
        if fmt == "fish":
            while j < n and not lines[j].startswith("- cmd:"):
                j += 1
        elif fmt == "zsh":
            while j < n and lines[j - 1].rstrip("\n").endswith("\\"):
                j += 1
        elif fmt == "bash" and re.fullmatch(r"#\d{9,11}\n?", lines[i]):
            j = min(n, i + 2)
        ents.append((i, j))
        i = j
    return ents


def scrub_text(text: str, secrets: list[str], fmt: str) -> tuple[str, int]:
    """Drop every history entry that contains one of `secrets`. Returns (new text, entries removed)."""
    lines = text.splitlines(keepends=True)
    keep, removed = [], 0
    for s, e in split_entries(lines, fmt):
        chunk = "".join(lines[s:e])
        if any(sec in chunk for sec in secrets):
            removed += 1
        else:
            keep.append(chunk)
    return "".join(keep), removed


def scrub_history(path: str, secrets: list[str], home: Path | None = None) -> str:
    """Rewrite a history file without the entries holding `secrets`. A private backup is kept."""
    home = home or _run.HOME
    p = Path(path)
    data = p.read_bytes().decode("utf-8", "surrogateescape")
    fmt = history_format(p.name, data.splitlines(keepends=True))
    new, removed = scrub_text(data, secrets, fmt)
    if not removed:
        return f"Nothing to remove from {short(p, home)} (already gone)."
    st = p.stat()
    bdir = home / BACKUP_DIR_NAME
    bdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = bdir / f"{p.name.lstrip('.')}.{time.strftime('%Y%m%d-%H%M%S')}"
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode("utf-8", "surrogateescape"))
    tmp = p.with_name(p.name + ".pc-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IMODE(st.st_mode) or 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(new.encode("utf-8", "surrogateescape"))
    os.replace(tmp, p)
    return (f"Removed {removed} entr{'y' if removed == 1 else 'ies'} from {short(p, home)}.\n"
            f"The old file is kept (only you can read it) at {short(backup, home)}. Delete it once you've made new keys.\n"
            "Terminals that are still open remember their own history: close them so they don't write it back.")


def scrub_step(path: str, secrets: list[str], home: Path | None = None) -> Step:
    name = short(path, home)
    return py_step(f"Remove keys from {name}", lambda: scrub_history(path, secrets, home),
                   f"rewrite {name} without the commands that hold {len(secrets)} key{'s' if len(secrets) != 1 else ''} or password{'s' if len(secrets) != 1 else ''}"
                   f" (a private backup goes to ~/{BACKUP_DIR_NAME})")


# ---------------------------------------------------------------- 2. project folders

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "env", "dist", "build", "target", "vendor", "site-packages", "coverage",
             "bower_components", "Pods", "DerivedData", "snap", "go", "Library", "out", "_build", "deps"}
HOME_SKIP = {"Downloads", "Pictures", "Music", "Videos", "Public", "Templates", "snap", "Backups"}
KEY_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk"}
EXAMPLE = re.compile(r"(?i)(example|sample|template|dist|defaults?|schema|tmpl|test)$")
GCP_JSON = re.compile(r"(?i)(service[-_]?account|firebase-adminsdk|credentials|gcp[-_].*key|google.*key).*\.json$")


def classify(name: str) -> str:
    if name == ".env" or name.startswith(".env.") or (name.endswith(".env") and len(name) > 4):
        stem = name[5:] if name.startswith(".env.") else ("" if name == ".env" else name[:-4])
        return "env-example" if stem and EXAMPLE.search(stem) else "env"
    if name in KEY_NAMES or name.endswith((".pem", ".key")):
        return "key"
    if name in (".npmrc", ".pypirc"):
        return "rc"
    if GCP_JSON.search(name):
        return "gcp-json"
    return ""


@dataclass
class Candidate:
    path: str
    kind: str
    repo: str   # enclosing git repository ("" if none)


def _repo_of(path: Path, stop: Path) -> str:
    cur = path
    for _ in range(12):
        if (cur / ".git").exists():
            return str(cur)
        if cur == stop or cur.parent == cur:
            break
        cur = cur.parent
    return ""


def walk_projects(roots: list[Path], home: Path, budget: float = 3.0, max_depth: int = 6) -> tuple[list[Candidate], dict]:
    """Find candidate files under roots, skipping dependency/build folders. Stops after `budget` seconds."""
    deadline = time.monotonic() + budget
    cands: list[Candidate] = []
    stats = {"dirs": 0, "truncated": False}
    uniq: list[Path] = []
    for r in sorted({Path(r) for r in roots}, key=lambda p: len(p.parts)):
        if not any(r == u or u in r.parents for u in uniq):
            uniq.append(r)
    for i, root in enumerate(uniq):
        # every root gets a fair share of what's left, so one huge folder can't starve the others
        root_deadline = time.monotonic() + max(0.0, deadline - time.monotonic()) / (len(uniq) - i)
        stack = [(str(root), 0, _repo_of(root, home))]
        while stack:
            if time.monotonic() > root_deadline:
                stats["truncated"] = True
                break
            d, depth, repo = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                continue
            stats["dirs"] += 1
            if any(e.name == ".git" for e in entries):
                repo = d
            for e in entries:
                name = e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if (depth < max_depth and not name.startswith(".") and name not in SKIP_DIRS
                                and not (d == str(home) and name in HOME_SKIP)):
                            stack.append((e.path, depth + 1, repo))
                    elif e.is_file(follow_symlinks=False):
                        kind = classify(name)
                        if kind:
                            cands.append(Candidate(e.path, kind, repo))
                except OSError:
                    continue
    return cands, stats


def git_state(repo: str, paths: list[str]) -> dict[str, str]:
    """path -> tracked | ignored | exposed (git would pick it up) | unknown."""
    rels = {p: os.path.relpath(p, repo) for p in paths}
    base = ["git", "-c", "safe.directory=*", "-C", repo]
    r = sh([*base, "ls-files", "-z", "--", *rels.values()], timeout=10)
    if r.code != 0:
        return {p: "unknown" for p in paths}
    tracked = {x for x in r.out.split("\0") if x}
    rest = [rel for rel in rels.values() if rel not in tracked]
    ignored: set[str] = set()
    if rest:
        r2 = sh([*base, "check-ignore", "-z", "--stdin"], input="\0".join(rest) + "\0", timeout=10)
        if r2.code not in (0, 1):
            return {p: ("tracked" if rels[p] in tracked else "unknown") for p in paths}
        ignored = {x for x in r2.out.split("\0") if x}
    return {p: "tracked" if rel in tracked else "ignored" if rel in ignored else "exposed" for p, rel in rels.items()}


def env_secrets(text: str) -> list[str]:
    """Names of variables in a .env file that hold a real-looking secret (names only; values are never returned)."""
    names = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.\-]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        name, value = m.group(1), m.group(2).strip().strip("'\"")
        if not value or value.startswith("${") or PLACEHOLDER.search(value) or len(set(value)) <= 3:
            continue
        specific = any(not h.rule.generic for h in find_secrets(value))
        secretish = re.search(r"(?i)(key|token|secret|passw|pwd|auth|credential|private|dsn|database_url|_url$)", name)
        url_pw = re.search(r"://[^\s:/@]+:[^\s@/]+@", value)
        if specific or (secretish and (len(value) >= 8 or url_pw)):
            names.append(name)
    return names


def gitignore_step(repo: str, patterns: list[str]) -> Step:
    def do() -> str:
        gi = Path(repo) / ".gitignore"
        existing = gi.read_text(errors="replace") if gi.exists() else ""
        have = {ln.strip() for ln in existing.splitlines()}
        add = [p for p in patterns if p not in have]
        if not add:
            return f"{gi} already lists {', '.join(patterns)}"
        text = existing + ("\n" if existing and not existing.endswith("\n") else "")
        text += ("\n" if existing else "") + "# Secret files (added by PC Command Center)\n" + "\n".join(add) + "\n"
        gi.write_text(text)
        return f"Added {', '.join(add)} to {gi}"
    return py_step(f"Tell git to ignore {', '.join(patterns)}", do, f"add {' '.join(patterns)} to {repo}/.gitignore")


def _ignore_pattern(path: str, repo: str) -> list[str]:
    name = os.path.basename(path)
    if name == ".env":
        return [".env"]
    if name.startswith(".env."):
        return [".env", name]
    return ["/" + os.path.relpath(path, repo)]


def scan_projects(roots: list[Path], home: Path, budget: float = 3.0) -> tuple[list[Finding], dict]:
    cands, stats = walk_projects(roots, home, budget)
    stats["files"] = len(cands)
    interesting: list[tuple[Candidate, str, list[str]]] = []  # (candidate, what, secret names)
    for c in cands:
        head = _read(c.path, 262144)
        if c.kind == "env":
            names = env_secrets(head)
            interesting.append((c, "env", names))
        elif c.kind == "env-example":
            names = [h.rule.name for h in find_secrets(head) if not h.rule.generic]
            if names:
                interesting.append((c, "env-example", names))
        elif c.kind == "key" and re.search(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY", head):
            interesting.append((c, "key", []))
        elif c.kind == "rc" and re.search(r"(?m)^\s*(?:\S*:)?(?:_authToken|_auth|_password)\s*=\s*(?!\$\{)\S|^\s*password\s*[=:]\s*(?!\$\{)\S", head):
            interesting.append((c, "rc", []))
        elif c.kind == "gcp-json" and '"private_key"' in head and "PRIVATE KEY" in head:
            interesting.append((c, "gcp-json", []))
    states: dict[str, str] = {}
    by_repo: dict[str, list[str]] = {}
    for c, _w, _n in interesting:
        if c.repo:
            by_repo.setdefault(c.repo, []).append(c.path)
    for repo, paths in by_repo.items():
        states.update(git_state(repo, paths))
    res: list[Finding] = []
    for c, what, names in interesting:
        state = states.get(c.path, "none") if c.repo else "none"
        res += _project_finding(c, what, names, state, home)
    return res, stats


WHAT = {"env": "Secret settings file", "env-example": "Example settings file with a real-looking key", "key": "Private key",
        "rc": "Package registry token file", "gcp-json": "Google service account key"}


def _project_finding(c: Candidate, what: str, names: list[str], state: str, home: Path) -> list[Finding]:
    rel = os.path.relpath(c.path, c.repo) if c.repo else os.path.basename(c.path)
    where = f"{rel} in {short(c.repo, home)}" if c.repo else short(c.path, home)
    inside = ""
    if names:
        shown = ", ".join(sorted(set(names))[:4]) + ("…" if len(set(names)) > 4 else "")
        inside = f" It holds {len(names)} secret-looking value{'s' if len(names) != 1 else ''} ({shown})."
    label = WHAT[what]
    fid = "project:" + _fid(c.path)
    if state == "tracked":
        steps = [gitignore_step(c.repo, _ignore_pattern(c.path, c.repo)),
                 Step(f"Stop tracking {rel} (the file stays on your PC)", ["git", "rm", "--cached", "--quiet", "--", rel], cwd=c.repo)]
        return [Finding(fid, "project", "bad", f"{label} is saved in git", f"{where}: it's part of the project's history.{inside} "
                        "If you pushed the project (for example to GitHub), treat every key in it as leaked and make new ones. "
                        "Then stop tracking the file so future commits leave it out.",
                        path=c.path, fix_label="Stop tracking it", steps=steps)]
    if state == "exposed":
        level = "bad" if (what != "env" or names) else "warn"
        extra = inside if names else (" It's empty of secrets right now, but anything you add would be uploaded." if what == "env" else "")
        return [Finding(fid, "project", level, f"{label} that git would upload",
                        f"{where} isn't in .gitignore, so `git add .` would include it and pushing would publish it.{extra}",
                        path=c.path, fix_label="Add to .gitignore", steps=[gitignore_step(c.repo, _ignore_pattern(c.path, c.repo))])]
    if what in ("key", "gcp-json", "rc", "env"):
        try:
            mode = os.stat(c.path).st_mode & 0o777
            if not os.stat(home).st_mode & 0o001:   # other accounts can't get into your home folder anyway
                return []
        except OSError:
            return []
        if mode & 0o004 and (what != "env" or names):
            return [Finding("perm:" + _fid(c.path), "project", "warn", f"{label} can be read by every account",
                            f"{where} can be opened by any user on this PC. Make it private so only you can read it.",
                            path=c.path, fix_label="Make private", steps=[_chmod_step(c.path, "600", f"Make {os.path.basename(c.path)} private")])]
    return []


# ---------------------------------------------------------------- 3. home folder credential files

CRED_FILES: list[tuple[str, str, str | None]] = [
    (".aws/credentials", "your AWS keys", None),
    (".npmrc", "your npm login token", r"(?m)(_authToken|_auth|_password)\s*="),
    (".docker/config.json", "your Docker registry password", r'"auth"\s*:\s*"[^"]+"'),
    (".netrc", "saved website and FTP passwords", r"\bpassword\s+\S"),
    (".pypirc", "your PyPI upload password", r"(?m)^\s*password\s*[=:]\s*\S"),
    (".config/gh/hosts.yml", "your GitHub CLI login", r"oauth_token:\s*\S"),
    (".git-credentials", "your Git passwords", None),
    (".pgpass", "your PostgreSQL passwords", None),
    (".my.cnf", "your MySQL password", r"(?im)^\s*password\s*="),
    (".kube/config", "your Kubernetes cluster login", r"(?m)(token|client-key-data|password):"),
    (".config/rclone/rclone.conf", "your cloud storage logins (rclone)", r"(?im)^\s*(pass|token|secret_access_key)\s*="),
    (".vault-token", "your Vault token", None),
    (".terraform.d/credentials.tfrc.json", "your Terraform Cloud token", None),
    (".config/hub", "your GitHub token (hub)", r"oauth_token"),
    (".boto", "your cloud storage keys", r"(?im)^\s*(aws|gs)_secret_access_key\s*="),
    (".s3cfg", "your S3 keys", r"(?im)^\s*secret_key\s*=\s*\S"),
    (".config/gcloud/application_default_credentials.json", "your Google Cloud login", None),
    (".claude/.credentials.json", "your Claude Code login", None),
    (".codex/auth.json", "your Codex login", None),
    (".config/github-copilot/apps.json", "your GitHub Copilot login", None),
    (".config/github-copilot/hosts.json", "your GitHub Copilot login", None),
]


def _who(mode: int) -> str:
    return "every account on this PC" if mode & 0o004 else "other members of your group"


def scan_home(home: Path) -> list[Finding]:
    res: list[Finding] = []
    for rel, what, rx in CRED_FILES:
        p = home / rel
        try:
            st = p.stat()
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        if rx and not re.search(rx, _read(p)):
            continue
        mode = st.st_mode & 0o777
        if mode & 0o077:
            res.append(Finding("perm:" + _fid(str(p)), "home", "bad" if mode & 0o004 else "warn", f"{short(p, home)} can be read by others",
                               f"It holds {what}. Right now {_who(mode)} can open it (permissions {oct(mode)[2:]}). "
                               "Make it private so only you can.",
                               path=str(p), fix_label="Make private", steps=[_chmod_step(str(p), "600", f"Make {short(p, home)} private")]))
    gc = home / ".git-credentials"
    text = _read(gc)
    logins = re.findall(r"(?m)^\s*[a-z][a-z0-9+.\-]*://([^:\s/@]*):([^@\s]+)@([^/\s:]+)", text)
    if logins:
        hosts = sorted({h for _u, _p, h in logins})
        previews = ", ".join(mask(pw, not any(not h.rule.generic for h in find_secrets(pw))) for _u, pw, _h in logins[:3])
        gh = "github.com" in hosts
        res.append(Finding("gitcred:" + _fid(str(gc)), "home", "warn", "Git passwords saved in plain text",
                           f"~/.git-credentials keeps {len(logins)} login{'s' if len(logins) != 1 else ''} for {', '.join(hosts[:4])} "
                           f"unencrypted ({previews}). Any program you run can read them. "
                           "Signing in with GitHub CLI (gh auth login) keeps the login in your keyring instead.",
                           path=str(gc), preview=previews, rotate="https://github.com/settings/tokens" if gh else "",
                           terminal=["gh", "auth", "login"] if gh and _run.has("gh") else []))
    return res


# ---------------------------------------------------------------- 4. SSH keys

def key_encrypted(text: str) -> bool | None:
    """True if a private key file needs a passphrase, False if not, None if unknown. Pure Python, no ssh-keygen."""
    if "BEGIN OPENSSH PRIVATE KEY" in text:
        body = "".join(ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("-----"))
        try:
            blob = base64.b64decode(body[:200] + "=" * (-len(body[:200]) % 4))
        except (ValueError, TypeError):
            return None
        magic = b"openssh-key-v1\0"
        if not blob.startswith(magic) or len(blob) < len(magic) + 4:
            return None
        n = int.from_bytes(blob[len(magic):len(magic) + 4], "big")
        cipher = blob[len(magic) + 4:len(magic) + 4 + n]
        return cipher != b"none"
    if "BEGIN ENCRYPTED PRIVATE KEY" in text:
        return True
    if "PRIVATE KEY-----" in text:
        return "ENCRYPTED" in text.split("-----END", 1)[0][:400]
    return None


SSH_NOT_KEYS = {"known_hosts", "known_hosts.old", "config", "authorized_keys", "authorized_keys2", "environment", "rc"}


def scan_ssh(home: Path) -> list[Finding]:
    d = home / ".ssh"
    res: list[Finding] = []
    try:
        dmode = d.stat().st_mode & 0o777
    except OSError:
        return res
    if dmode & 0o077:
        res.append(Finding("ssh-dir", "ssh", "warn", "Your SSH folder can be opened by others",
                           f"~/.ssh has permissions {oct(dmode)[2:]}: {_who(dmode)} can look inside. SSH expects only you to have access.",
                           path=str(d), fix_label="Make private", steps=[_chmod_step(str(d), "700", "Make ~/.ssh private")]))
    try:
        files = sorted(d.iterdir())
    except OSError:
        return res
    for f in files:
        if f.suffix == ".pub" or f.name in SSH_NOT_KEYS or f.name.endswith((".old", ".bak")):
            continue
        try:
            if not f.is_file():
                continue
            mode = f.stat().st_mode & 0o777
        except OSError:
            continue
        head = _read(f, 16384)
        if "PRIVATE KEY-----" not in head:
            continue
        name = short(f, home)
        if mode & 0o077:
            res.append(Finding("sshperm:" + _fid(str(f)), "ssh", "bad", f"SSH private key {f.name} can be read by others",
                               f"{name} has permissions {oct(mode)[2:]}: {_who(mode)} could copy it and log in as you "
                               "wherever this key is accepted (GitHub, servers). SSH itself refuses to use it like this.",
                               path=str(f), fix_label="Make private", steps=[_chmod_step(str(f), "600", f"Make {name} private")]))
        if key_encrypted(head) is False:
            res.append(Finding("sshpass:" + _fid(str(f)), "ssh", "info", f"SSH key {f.name} has no passphrase",
                               f"Anyone who gets a copy of {name} (a backup, a stolen laptop without disk encryption) can use it. "
                               "Adding a passphrase protects it; Ubuntu's keyring remembers it after you log in.",
                               path=str(f), terminal=["ssh-keygen", "-p", "-f", str(f)]))
    ak = d / "authorized_keys"
    try:
        amode = ak.stat().st_mode & 0o777
        if amode & 0o022:
            res.append(Finding("sshauth", "ssh", "bad", "Others can change who may log in to this PC",
                               f"~/.ssh/authorized_keys can be changed by {_who(amode)} (permissions {oct(amode)[2:]}).",
                               path=str(ak), fix_label="Make private", steps=[_chmod_step(str(ak), "600", "Make authorized_keys private")]))
    except OSError:
        pass
    return res


# ---------------------------------------------------------------- everything

LAST: dict = {"at": 0.0, "findings": [], "stats": {}}


def default_roots(home: Path) -> list[Path]:
    if home == _run.HOME:
        try:
            from .maint import project_roots
            return project_roots()
        except Exception:  # noqa: BLE001 - fall back to the usual folders
            pass
    roots = [home / n for n in ("Documents", "Projects", "code", "dev", "src", "repos", "work")]
    return [r for r in roots if r.is_dir()] or [home]


def scan(home: Path | str | None = None, roots: list[Path] | None = None, budget: float = 4.0) -> list[Finding]:
    """Look everywhere. Takes a few seconds at most (project folders stop after the time budget)."""
    t0 = time.monotonic()
    home = Path(home) if home else _run.HOME
    findings: list[Finding] = []
    errors = []
    for fn in (scan_histories, scan_home, scan_ssh):
        try:
            findings += fn(home)
        except Exception as e:  # noqa: BLE001 - one broken file must not stop the whole check
            errors.append(f"{fn.__name__}: {e}")
    roots = default_roots(home) if roots is None else roots
    try:
        pf, stats = scan_projects(roots, home, max(0.8, budget - (time.monotonic() - t0)))
    except Exception as e:  # noqa: BLE001
        pf, stats = [], {"error": str(e)}
    findings += pf
    findings.sort(key=lambda f: (LEVELS.get(f.level, 3), {"history": 0, "project": 1, "home": 2, "ssh": 3}.get(f.kind, 4), f.path, f.line))
    stats.update(seconds=round(time.monotonic() - t0, 2), roots=[short(r, home) for r in roots],
                 histories=[short(p, home) for p, _ in history_files(home)], errors=errors)
    LAST.update(at=time.time(), findings=findings, stats=stats)
    return findings


def recent(max_age: float = 60.0) -> list[Finding] | None:
    """The last scan's findings if it ran less than max_age seconds ago."""
    return LAST["findings"] if LAST["at"] and time.time() - LAST["at"] < max_age else None


def fix_all_steps(findings: list[Finding]) -> list[Step]:
    """Every automatic fix, each once (history files are scrubbed once each)."""
    steps, seen = [], set()
    for f in findings:
        for s in f.steps:
            key = (s.title, s.display())
            if key not in seen:
                seen.add(key)
                steps.append(s)
    return steps


def summary(findings: list[Finding]) -> tuple[str, str]:
    """(level, one sentence) for the security checklist."""
    bad = [f for f in findings if f.level == "bad"]
    warn = [f for f in findings if f.level == "warn"]
    if bad:
        kinds = sorted({f.title.split(" in your")[0] for f in bad if f.kind == "history"})
        what = f" ({', '.join(kinds[:3])})" if kinds else ""
        return "bad", f"{len(bad)} exposed secret{'s' if len(bad) != 1 else ''}{what}. Open the Secrets tab to see where and fix them."
    if warn:
        return "warn", f"{len(warn)} thing{'s' if len(warn) != 1 else ''} worth a look: passwords in history or files others can read."
    if findings:
        return "info", "Nothing exposed. " + findings[0].title + "."
    return "ok", "No API keys or passwords found in your command history, projects or settings files."


def format_text(findings: list[Finding], stats: dict | None = None) -> str:
    stats = LAST["stats"] if stats is None else stats
    lines: list[str] = []
    if not findings:
        lines.append("✓ No exposed secrets found in your command history, projects or settings files.")
    else:
        bad = sum(1 for f in findings if f.level == "bad")
        lines.append(f"Secrets check: {len(findings)} finding{'s' if len(findings) != 1 else ''}" + (f", {bad} serious" if bad else "") + ".")
        lines.append("Secrets are shown partly hidden (first 4 and last 2 characters).")
        icons = {"bad": "✗", "warn": "!", "info": "i"}
        for f in findings:
            lines.append("")
            lines.append(f"{icons.get(f.level, '·')} {f.title}")
            for part in f.detail.splitlines():
                lines.append(f"    {part}")
            if f.rotate:
                lines.append(f"    Make a new key / revoke this one: {f.rotate}")
            if f.fix_label and f.steps:
                lines.append(f"    Fix: {f.fix_label} → " + "; ".join(s.display() for s in f.steps))
            if f.terminal:
                lines.append(f"    Fix (in a terminal): {shlex.join(f.terminal)}")
    if stats:
        where = ", ".join(stats.get("roots", [])[:5])
        more = " (stopped early: large folders)" if stats.get("truncated") else ""
        lines.append("")
        lines.append(f"Looked at {len(stats.get('histories', []))} history files, settings files in your home folder, "
                     f"and project folders ({where}){more} in {stats.get('seconds', 0)} s.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="pc secrets", description="Find API keys, tokens and passwords left in history, projects and settings files.")
    p.add_argument("--json", action="store_true", help="machine-readable output (secrets stay masked)")
    p.add_argument("--budget", type=float, default=6.0, help="seconds to spend walking project folders")
    a = p.parse_args(argv)
    findings = scan(budget=a.budget)
    if a.json:
        print(json.dumps({"findings": [f.as_dict() for f in findings], "stats": LAST["stats"]}, indent=2))
    else:
        print(format_text(findings))
    return 1 if any(f.level == "bad" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
