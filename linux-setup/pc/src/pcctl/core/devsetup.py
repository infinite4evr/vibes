"""Developer setup checks: PATH doctor, GitHub connection and SSH keys, git identity and defaults, global packages,
and Python versions installed with uv."""

from __future__ import annotations

import json
import os
import pwd
import re
import shlex
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .run import HOME, Step, has, out, py_size, read, sh, which

# ---------------------------------------------------------------- PATH doctor

PATH_TOOLS = ["node", "npm", "python", "python3", "pip", "pip3", "uv", "go", "cargo", "rustc", "java", "code", "git"]
VERSION_ARGS = {"go": ["version"], "java": ["-version"]}
MARK = "__PCPATH__"
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"


def tilde(p: str) -> str:
    h = str(HOME)
    return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p


def user_shell() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
    except KeyError:
        return os.environ.get("SHELL", "/bin/bash")


def _base_env() -> dict:
    """A fresh environment like the one a new login gets (so PATH isn't polluted by how this app was started)."""
    m = re.search(r'^PATH="?([^"\n]+)"?', read("/etc/environment"), re.M)
    env = {"HOME": str(HOME), "USER": os.environ.get("USER", ""), "LOGNAME": os.environ.get("USER", ""), "TERM": "dumb",
           "LANG": "C.UTF-8", "PATH": m.group(1) if m else DEFAULT_PATH, "SHELL": user_shell()}
    for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def extract_path(text: str) -> str:
    """Pull our marked PATH line out of whatever a shell printed (banners, fastfetch, warnings…)."""
    for line in reversed(text.splitlines()):
        if MARK in line:
            return line.split(MARK, 1)[1].strip()
    return ""


def shell_paths() -> dict:
    """{'session': PATH that apps started from the dock get, 'terminal': PATH in a new terminal, 'shell': name}"""
    shell = user_shell()
    name = os.path.basename(shell)
    show = f'printf "\\n{MARK}%s\\n" "$PATH"'
    env = _base_env()
    session = extract_path(sh(["bash", "-lc", show], timeout=15, env=env, input="").out)
    if name == "zsh" and has("zsh"):
        term_cmd = ["bash", "-lc", f"exec zsh -ic {shlex.quote(show)}"]
    elif name == "fish" and has("fish"):
        fish_show = 'printf "%s%s\\n" ' + MARK + " (string join : $PATH)"
        term_cmd = ["bash", "-lc", "exec fish -ic " + shlex.quote(fish_show)]
    else:
        name = "bash"
        term_cmd = ["bash", "-lic", show]
    terminal = extract_path(sh(term_cmd, timeout=20, env=env, input="").out)
    return {"session": session or os.environ.get("PATH", ""), "terminal": terminal or session or os.environ.get("PATH", ""), "shell": name}


def split_path(path: str) -> list[dict]:
    """Every PATH entry with whether it exists and whether it repeats an earlier one."""
    res = []
    seen: dict[str, int] = {}
    for i, d in enumerate(path.split(":")):
        entry = {"index": i, "dir": d, "shown": tilde(d) if d else "(empty = current folder)", "exists": bool(d) and os.path.isdir(d),
                 "dup_of": None, "relative": not d.startswith("/")}
        key = os.path.normpath(d) if d else ""
        if key in seen:
            entry["dup_of"] = seen[key]
        else:
            seen[key] = i
        res.append(entry)
    return res


def find_all(name: str, path: str) -> list[str]:
    """Like `type -a name`: every executable called `name` along PATH, first one wins. Same file via symlinks counts once."""
    res, real = [], set()
    for d in path.split(":"):
        if not d.startswith("/"):
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            rp = os.path.realpath(p)
            if rp not in real:
                real.add(rp)
                res.append(p)
    return res


def parse_version(text: str) -> str:
    m = re.search(r'version "([^"]+)"', text) or re.search(r"(?:\bgo|\bv|\b)(\d+\.\d+(?:\.\d+)?(?:[a-z]+\d*)?)", text)
    return m.group(1) if m else ""


def tool_version(exe: str, name: str, path: str) -> str:
    env = {**os.environ, "PATH": f"{os.path.dirname(exe)}:{path}", "LANG": "C"}
    r = sh([exe, *VERSION_ARGS.get(name, ["--version"])], timeout=8, env=env)
    return parse_version(r.out + "\n" + r.err)


def path_report(path: str, session_path: str = "", tools: list[str] | None = None, versions: bool = True) -> dict:
    tools = tools if tools is not None else PATH_TOOLS
    entries = split_path(path)
    found = {t: find_all(t, path) for t in tools}
    vers: dict[str, str] = {}
    if versions:
        todo = [(t, p) for t, ps in found.items() for p in ps]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for (t, p), v in zip(todo, ex.map(lambda tp: tool_version(tp[1], tp[0], path), todo)):
                vers[p] = v
    tool_rows = [{"name": t, "copies": [{"path": p, "shown": tilde(p), "version": vers.get(p, ""), "wins": i == 0,
                                          "real": os.path.realpath(p)} for i, p in enumerate(ps)]} for t, ps in found.items()]
    sess = {os.path.normpath(d) for d in session_path.split(":") if d} if session_path else set()
    terminal_only = [e["dir"] for e in entries if session_path and e["dir"] and e["dup_of"] is None and os.path.normpath(e["dir"]) not in sess]
    report = {"entries": entries, "tools": tool_rows, "missing": [e for e in entries if e["dir"] and not e["exists"] and e["dup_of"] is None],
              "dups": [e for e in entries if e["dup_of"] is not None], "relative": [e for e in entries if e["relative"]],
              "terminal_only": terminal_only}
    report["tips"] = path_tips(report)
    return report


def _describe(c: dict) -> str:
    return f"{c['shown']}" + (f" ({c['version']})" if c["version"] else "")


def path_tips(r: dict) -> list[tuple[str, str]]:
    """[(level ok|info|warn|bad, plain-English tip)]"""
    tips: list[tuple[str, str]] = []
    if r["relative"]:
        tips.append(("bad", "Your PATH contains an empty or relative entry (like “.”). That makes the shell run programs from whatever folder "
                            "you're in - a classic security hole. Look for “::” or “:.” in the PATH lines of ~/.zshrc / ~/.bashrc."))
    if r["missing"]:
        names = ", ".join(e["shown"] for e in r["missing"][:4]) + ("…" if len(r["missing"]) > 4 else "")
        tips.append(("info", f"{len(r['missing'])} folder{'s' if len(r['missing']) != 1 else ''} on your PATH "
                             f"{'don' if len(r['missing']) != 1 else 'doesn'}'t exist: {names}. Harmless, usually left over from "
                             "a tool you removed. Delete the line that adds it in your shell config to tidy up."))
    if r["dups"]:
        counts: dict[str, int] = {}
        for e in r["dups"]:
            counts[e["shown"]] = counts.get(e["shown"], 0) + 1
        names = ", ".join(f"{k} ({v + 1}×)" for k, v in list(counts.items())[:4])
        tips.append(("info", f"Some folders are on your PATH more than once: {names}. Harmless (the first copy wins) - usually a config "
                             "file that adds it every time it's loaded."))
    tools = {t["name"]: t["copies"] for t in r["tools"]}
    for name, copies in tools.items():
        distinct = {c["version"] or c["real"] for c in copies}
        if len(copies) < 2 or len(distinct) < 2:
            continue
        win, rest = copies[0], copies[1:]
        text = f"{len(copies)} copies of {name}: {_describe(win)} is the one that runs; " + ", ".join(_describe(c) for c in rest) + \
               (" is" if len(rest) == 1 else " are") + " hidden behind it because it comes later in PATH."
        level = "info"
        if name == "node" and win["path"].startswith("/usr/") and any("/.nvm/" in c["path"] for c in rest):
            level = "warn"
            text += " Ubuntu's own Node package is beating nvm. Remove the apt “nodejs” package (Apps page), or load nvm last in your shell config."
        elif name in ("python3", "python") and win["path"].startswith("/usr/"):
            text += " That's fine: Ubuntu's python3 must stay for system tools. For projects, use uv (uv venv / uv run) - it picks the right Python per project."
        elif name in ("python3", "python"):
            text += " Keep in mind Ubuntu's system tools still use /usr/bin/python3."
        tips.append((level, text))
    for pip in ("pip", "pip3"):
        pcs, pys = tools.get(pip, []), tools.get("python3", [])
        if pcs and pys and pcs[0]["version"] and pys[0]["version"]:
            pv = re.search(r"python (\d+\.\d+)", pcs[0].get("pyinfo", "")) if pcs[0].get("pyinfo") else None
            if pv and not pys[0]["version"].startswith(pv.group(1)):
                tips.append(("warn", f"{pip} installs into Python {pv.group(1)}, but python3 is {pys[0]['version']}. Use “python3 -m pip” or uv so "
                                     "packages land where you expect."))
    npm, node = tools.get("npm", []), tools.get("node", [])
    if npm and node and os.path.dirname(npm[0]["path"]) != os.path.dirname(node[0]["path"]) and "/.nvm/" in npm[0]["path"] + node[0]["path"]:
        tips.append(("warn", f"npm ({npm[0]['shown']}) and node ({node[0]['shown']}) come from different installs. Global packages may end up "
                             "with the wrong Node - make sure nvm's folder comes first in PATH."))
    local_bin = str(HOME / ".local/bin")
    if os.path.isdir(local_bin) and os.listdir(local_bin) and not any(os.path.normpath(e["dir"]) == local_bin for e in r["entries"]):
        tips.append(("warn", "~/.local/bin isn't on your PATH, but tools are installed there (uv, pipx and others put commands there). "
                             "Add this line to ~/.zshrc: export PATH=\"$HOME/.local/bin:$PATH\""))
    if r["terminal_only"]:
        names = ", ".join(tilde(d) for d in r["terminal_only"][:3]) + ("…" if len(r["terminal_only"]) > 3 else "")
        tips.append(("info", f"Only your terminal sees {names}. Apps started from the dock don't. Usually fine - VS Code and most editors "
                             "load your shell settings themselves - but it explains “command not found” in apps that don't."))
    missing_tools = [n for n, c in tools.items() if not c and n in ("git", "node", "python3")]
    if missing_tools:
        tips.append(("info", "Not installed (or not on PATH): " + ", ".join(missing_tools) + "."))
    if not tips:
        tips.append(("ok", "Your PATH looks tidy: no missing folders, no duplicates, and no tools hiding behind each other."))
    return tips


def pip_python(pip_exe: str) -> str:
    """'pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)' -> 'python 3.12'"""
    return (sh([pip_exe, "--version"], timeout=8).out or "").strip()


def path_doctor() -> dict:
    sp = shell_paths()
    rep = path_report(sp["terminal"], sp["session"])
    for t in rep["tools"]:
        if t["name"] in ("pip", "pip3") and t["copies"]:
            t["copies"][0]["pyinfo"] = pip_python(t["copies"][0]["path"])
    rep["tips"] = path_tips(rep)
    rep["shell"] = sp["shell"]
    rep["path"] = sp["terminal"]
    return rep


# ---------------------------------------------------------------- GitHub connection

def parse_gh_status(text: str) -> dict:
    """`gh auth status` (old and new formats) -> {'logged_in', 'host', 'account', 'protocol', 'scopes', 'source', 'error'}"""
    info = {"logged_in": False, "host": "", "account": "", "protocol": "", "scopes": [], "source": "", "error": ""}
    for line in text.splitlines():
        s = line.strip().lstrip("✓✗X!-* ").strip()
        m = re.match(r"Logged in to (\S+) (?:account|as) (\S+)(?: \(([^)]*)\))?", s)
        if m and not info["logged_in"]:
            info.update(logged_in=True, host=m.group(1), account=m.group(2), source=m.group(3) or "")
            continue
        m = re.match(r"Failed to log in to (\S+) account (\S+)", s)
        if m:
            info.update(host=m.group(1), account=m.group(2), error="The saved GitHub login stopped working (token expired or revoked). Log in again.")
            continue
        m = re.match(r"Git operations protocol: (\w+)", s) or re.match(r"Git operations for \S+ configured to use (\w+) protocol", s)
        if m:
            info["protocol"] = m.group(1)
            continue
        m = re.match(r"Token scopes: (.*)", s)
        if m:
            info["scopes"] = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip() and x.strip() != "none"]
        if "not logged into any" in s.lower():
            info["error"] = "Not logged in to GitHub yet."
    return info


def gh_status() -> dict:
    if not has("gh"):
        return {"installed": False, "logged_in": False, "account": "", "protocol": "", "scopes": [], "error": "", "host": "", "source": ""}
    r = sh(["gh", "auth", "status", "--hostname", "github.com"], timeout=15)
    info = parse_gh_status(r.out + "\n" + r.err)
    info["installed"] = True
    return info


def parse_ssh_test(code: int, text: str) -> dict:
    """`ssh -T git@github.com` -> {'ok', 'user', 'message'}. GitHub answers with exit code 1 even when it worked."""
    m = re.search(r"Hi ([\w.-]+)! You've successfully authenticated", text)
    if m:
        return {"ok": True, "user": m.group(1), "message": f"Connected as {m.group(1)}. Git over SSH works."}
    low = text.lower()
    if "permission denied (publickey)" in low:
        msg = "GitHub doesn't know any of your SSH keys yet. Upload your key below."
    elif "host key verification failed" in low or "remote host identification has changed" in low:
        msg = "GitHub's identity check failed (its saved fingerprint in ~/.ssh/known_hosts doesn't match). Remove the old github.com line from that file."
    elif "could not resolve hostname" in low or "network is unreachable" in low or "timed out" in low or code == 124:
        msg = "Couldn't reach github.com - check your internet connection."
    elif code == 127 or "not installed" in low:
        msg = "The ssh program isn't installed (package openssh-client)."
    else:
        msg = (text.strip().splitlines() or ["SSH connection to GitHub failed."])[-1]
    return {"ok": False, "user": "", "message": msg}


def ssh_test() -> dict:
    r = sh(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new", "git@github.com"], timeout=15)
    return parse_ssh_test(r.code, r.out + "\n" + r.err)


@dataclass
class SshKey:
    path: str
    type: str
    comment: str
    private: bool
    fingerprint: str = ""

    @property
    def kind(self) -> str:
        return {"ssh-ed25519": "Ed25519 (modern, recommended)", "ssh-rsa": "RSA (older)", "ecdsa-sha2-nistp256": "ECDSA",
                "sk-ssh-ed25519@openssh.com": "Ed25519 on a security key"}.get(self.type, self.type)


def parse_pubkey(text: str) -> tuple[str, str]:
    """'ssh-ed25519 AAAA… me@pc' -> ('ssh-ed25519', 'me@pc')"""
    parts = text.strip().split(None, 2)
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[2] if len(parts) > 2 else ""


def ssh_keys(ssh_dir: Path | None = None) -> list[SshKey]:
    d = ssh_dir or HOME / ".ssh"
    res = []
    for pub in sorted(d.glob("*.pub")) if d.is_dir() else []:
        typ, comment = parse_pubkey(read(pub))
        if not typ:
            continue
        fp = ""
        if has("ssh-keygen"):
            m = re.search(r"(SHA256:\S+)", out(["ssh-keygen", "-lf", str(pub)], timeout=5))
            fp = m.group(1) if m else ""
        res.append(SshKey(str(pub), typ, comment, Path(str(pub)[:-4]).exists(), fp))
    return res


def keygen_cmd(email: str, path: str | None = None, passphrase: bool = False) -> list[str]:
    p = path or str(HOME / ".ssh/id_ed25519")
    cmd = ["ssh-keygen", "-t", "ed25519", "-C", email or f"{os.environ.get('USER', 'me')}@{socket.gethostname()}", "-f", p]
    return cmd if passphrase else cmd + ["-N", ""]


def keygen_steps(email: str, path: str | None = None) -> list[Step]:
    """Create a new key without a passphrase. Never overwrites an existing key."""
    p = path or str(HOME / ".ssh/id_ed25519")
    if os.path.exists(p):
        return []
    return [Step("Make sure ~/.ssh exists (private to you)", ["bash", "-c", f"mkdir -p {shlex.quote(os.path.dirname(p))} && chmod 700 {shlex.quote(os.path.dirname(p))}"]),
            Step("Create an Ed25519 SSH key", keygen_cmd(email, p))]


def upload_key_steps(pub: str, title: str | None = None, signing: bool = False) -> list[Step]:
    t = title or socket.gethostname()
    cmd = ["gh", "ssh-key", "add", pub, "--title", t + (" (signing)" if signing else "")]
    if signing:
        cmd += ["--type", "signing"]
    return [Step(f"Upload {tilde(pub)} to GitHub" + (" as a signing key" if signing else ""), cmd)]


def needs_key_scope(scopes: list[str]) -> bool:
    """gh needs admin:public_key (or write:public_key) to upload SSH keys. Fine-grained / unknown scopes -> assume OK."""
    return bool(scopes) and not any(s in ("admin:public_key", "write:public_key") for s in scopes)


def private_email_cmd() -> list[str]:
    return ["gh", "api", "user", "--jq", '"\\(.id)+\\(.login)@users.noreply.github.com"']


# ---------------------------------------------------------------- git identity & defaults

def parse_git_config(text: str) -> dict[str, list[str]]:
    """`git config --global -z --list` (key\\nvalue\\0…) or plain key=value lines -> {key: [values]}"""
    res: dict[str, list[str]] = {}
    if "\0" in text:
        for item in text.split("\0"):
            if not item:
                continue
            k, _, v = item.partition("\n")
            res.setdefault(k.lower(), []).append(v)
    else:
        for line in text.splitlines():
            k, sep, v = line.partition("=")
            if sep or k:
                res.setdefault(k.strip().lower(), []).append(v)
    return res


def git_config() -> dict[str, list[str]]:
    if not has("git"):
        return {}
    return parse_git_config(sh(["git", "config", "--global", "-z", "--list"], timeout=5).out)


def gget(cfg: dict[str, list[str]], key: str, default: str = "") -> str:
    v = cfg.get(key.lower())
    return v[-1] if v else default


def git_set(key: str, value: str | None, title: str | None = None) -> Step:
    if value is None:
        return Step(title or f"Unset {key}", ["git", "config", "--global", "--unset-all", key], ok_codes=(0, 5))
    return Step(title or f"{key} = {value}", ["git", "config", "--global", key, value])


PULL_MODES = [
    ("merge", "Merge (Git's default)", "When both you and GitHub have new commits, git makes a small merge commit.", {"pull.rebase": "false", "pull.ff": None}),
    ("rebase", "Rebase (tidy history)", "Your local commits are replayed on top of the new ones - no merge commits.", {"pull.rebase": "true", "pull.ff": None}),
    ("ff-only", "Only when it's simple (safest)", "Pull refuses when both sides have new commits, so nothing surprising happens. You then decide.",
     {"pull.ff": "only", "pull.rebase": None}),
]


def pull_mode(cfg: dict[str, list[str]]) -> str:
    if gget(cfg, "pull.ff") == "only":
        return "ff-only"
    if gget(cfg, "pull.rebase") in ("true", "merges", "interactive", "i", "m"):
        return "rebase"
    if gget(cfg, "pull.rebase") == "false":
        return "merge"
    return ""


def pull_steps(mode: str) -> list[Step]:
    for mid, label, _why, keys in PULL_MODES:
        if mid == mode:
            return [git_set(k, v, f"Pull: {label}" if v is not None else f"Clear {k}") for k, v in keys.items()]
    return []


def editors() -> list[tuple[str, str]]:
    """(label, core.editor value) for editors that are installed."""
    res = []
    for exe, label, val in (("code", "VS Code", "code --wait"), ("cursor", "Cursor", "cursor --wait"), ("zed", "Zed", "zed --wait"),
                            ("zeditor", "Zed", "zeditor --wait"), ("gnome-text-editor", "Text Editor", "gnome-text-editor --standalone"),
                            ("nano", "nano (inside the terminal)", "nano"), ("micro", "micro (inside the terminal)", "micro"),
                            ("nvim", "Neovim", "nvim"), ("vim", "Vim", "vim")):
        if which(exe) and label not in [x[0] for x in res]:
            res.append((label, val))
    return res


GIT_SWITCHES = [
    ("push.autoSetupRemote", "true", "Push new branches without extra typing",
     "No more “fatal: the current branch has no upstream branch” - the first git push of a new branch just works."),
    ("fetch.prune", "true", "Forget branches deleted on GitHub", "When a branch is deleted on GitHub (e.g. after a merged pull request), your copy of it goes too."),
    ("rerere.enabled", "true", "Remember how you fixed merge conflicts", "If the same conflict comes back (common when rebasing), git fixes it the same way."),
    ("init.defaultBranch", "main", "New projects start on “main”", "GitHub's default branch name. Without it, git init still uses “master”."),
    ("help.autocorrect", "prompt", "Offer to fix typos in git commands", "“git stauts” asks whether you meant “git status”."),
    ("diff.colorMoved", "zebra", "Highlight moved lines in diffs", "Code you moved shows in a different colour than code you changed."),
]


def credential_helper(cfg: dict[str, list[str]]) -> str:
    helpers = cfg.get("credential.https://github.com.helper", []) + cfg.get("credential.helper", [])
    helpers = [h for h in helpers if h]
    if any("gh auth git-credential" in h for h in helpers):
        return "gh"
    if any("libsecret" in h for h in helpers):
        return "libsecret"
    if any(h.startswith("cache") for h in helpers):
        return "cache"
    if any(h.startswith("store") for h in helpers):
        return "store"
    return helpers[-1] if helpers else ""


def signing_state(cfg: dict[str, list[str]]) -> dict:
    return {"on": gget(cfg, "commit.gpgsign") == "true", "format": gget(cfg, "gpg.format"), "key": gget(cfg, "user.signingkey")}


def signing_steps(pub: str, on: bool) -> list[Step]:
    if not on:
        return [git_set("commit.gpgsign", "false", "Stop signing commits")]
    return [git_set("gpg.format", "ssh", "Sign with your SSH key (not GPG)"), git_set("user.signingkey", pub, f"Use {tilde(pub)}"),
            git_set("commit.gpgsign", "true", "Sign every commit"), git_set("tag.gpgsign", "true", "Sign tags too")]


# ---------------------------------------------------------------- global packages

@dataclass
class GlobalPkg:
    manager: str
    name: str
    version: str = ""
    size: int = 0
    note: str = ""
    path: str = ""
    removable: bool = True
    extra: dict = field(default_factory=dict)


def parse_npm_ls(text: str) -> list[GlobalPkg]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    res = []
    for name, info in (data.get("dependencies") or {}).items():
        builtin = name in ("npm", "corepack")
        res.append(GlobalPkg("npm", name, (info or {}).get("version", ""), note="comes with Node" if builtin else "", removable=not builtin))
    return res


def parse_pnpm_ls(text: str) -> list[GlobalPkg]:
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    res = []
    for block in data if isinstance(data, list) else [data]:
        for name, info in (block.get("dependencies") or {}).items():
            res.append(GlobalPkg("pnpm", name, (info or {}).get("version", ""), path=(info or {}).get("path", "")))
    return res


def parse_pipx_list(text: str) -> list[GlobalPkg]:
    text = text[text.find("{"):] if "{" in text else ""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    res = []
    for name, v in (data.get("venvs") or {}).items():
        meta = (v or {}).get("metadata", {})
        main = meta.get("main_package", {})
        apps = main.get("apps", [])
        py = meta.get("python_version", "")
        res.append(GlobalPkg("pipx", main.get("package") or name, main.get("package_version", ""),
                             note=", ".join(apps[:4]) + (f" · {py}" if py else ""), extra={"venv": name}))
    return res


def parse_uv_tools(text: str) -> list[GlobalPkg]:
    """`uv tool list [--show-paths]`: 'ruff v0.8.0 (/path)' followed by '- ruff' command lines."""
    res: list[GlobalPkg] = []
    for line in text.splitlines():
        if not line.strip() or line.lower().startswith(("no tools", "warning")):
            continue
        if line.startswith("- "):
            if res:
                cmd = line[2:].split(" (")[0].strip()
                res[-1].extra.setdefault("apps", []).append(cmd)
            continue
        m = re.match(r"^(\S+) v?(\S+)(?: \[[^\]]*\])?(?: \((.+)\))?$", line.strip())
        if m:
            res.append(GlobalPkg("uv", m.group(1), m.group(2), path=m.group(3) or ""))
    for p in res:
        p.note = ", ".join(p.extra.get("apps", [])[:4])
    return res


def parse_cargo_list(text: str) -> list[GlobalPkg]:
    """`cargo install --list`: 'ripgrep v14.1.0:' then indented binary names."""
    res: list[GlobalPkg] = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) v(\S+?)(?: \(([^)]+)\))?:$", line)
        if m:
            res.append(GlobalPkg("cargo", m.group(1), m.group(2)))
        elif line.startswith((" ", "\t")) and res and line.strip():
            res[-1].extra.setdefault("bins", []).append(line.strip())
    for p in res:
        p.note = ", ".join(p.extra.get("bins", [])[:4])
    return res


def _node_env(exe: str) -> dict:
    return {**os.environ, "PATH": f"{os.path.dirname(exe)}:{os.environ.get('PATH', '')}"}


def _npm_exe() -> str | None:
    from .dev import _nvm_bin
    return _nvm_bin("npm")


def _dir_size(p: str | Path) -> int:
    try:
        return py_size(p, limit_s=5)
    except OSError:
        return 0


def global_packages() -> dict:
    """{'items': [GlobalPkg], 'managers': {name: bool}}"""
    items: list[GlobalPkg] = []
    managers: dict[str, bool] = {}
    npm = _npm_exe()
    managers["npm"] = bool(npm)
    if npm:
        env = _node_env(npm)
        pk = parse_npm_ls(sh([npm, "ls", "-g", "--depth=0", "--json"], timeout=20, env=env).out)
        root = sh([npm, "root", "-g"], timeout=10, env=env).out.strip()
        for p in pk:
            if root:
                p.path = os.path.join(root, p.name)
                p.size = _dir_size(p.path)
        items += pk
    pnpm = which("pnpm")
    managers["pnpm"] = bool(pnpm)
    if pnpm:
        for p in parse_pnpm_ls(sh([pnpm, "ls", "-g", "--json"], timeout=20, env=_node_env(pnpm)).out):
            p.size = _dir_size(p.path) if p.path else 0
            items.append(p)
    pipx = which("pipx")
    managers["pipx"] = bool(pipx)
    if pipx:
        venvs = out([pipx, "environment", "--value", "PIPX_LOCAL_VENVS"], timeout=10) or str(HOME / ".local/share/pipx/venvs")
        for p in parse_pipx_list(sh([pipx, "list", "--json"], timeout=20).out):
            p.path = os.path.join(venvs, p.extra.get("venv", p.name))
            p.size = _dir_size(p.path)
            items.append(p)
    uv = which("uv")
    managers["uv"] = bool(uv)
    if uv:
        for p in parse_uv_tools(sh([uv, "tool", "list", "--show-paths"], timeout=20).out):
            p.size = _dir_size(p.path) if p.path else 0
            items.append(p)
    cargo = which("cargo")
    managers["cargo"] = bool(cargo)
    if cargo:
        cbin = Path(os.environ.get("CARGO_HOME", HOME / ".cargo")) / "bin"
        for p in parse_cargo_list(sh([cargo, "install", "--list"], timeout=20).out):
            p.size = sum((cbin / b).stat().st_size for b in p.extra.get("bins", []) if (cbin / b).exists())
            items.append(p)
    gobin = go_bin_dir()
    managers["go"] = bool(which("go")) or gobin.is_dir()
    if gobin.is_dir():
        for f in sorted(gobin.iterdir()):
            if f.is_file() and os.access(f, os.X_OK):
                items.append(GlobalPkg("go", f.name, "", size=f.stat().st_size, path=str(f), note="Go program"))
    return {"items": items, "managers": managers}


def go_bin_dir() -> Path:
    gobin = os.environ.get("GOBIN")
    if gobin:
        return Path(gobin)
    gopath = os.environ.get("GOPATH") or (out(["go", "env", "GOPATH"], timeout=5) if has("go") else "") or str(HOME / "go")
    return Path(gopath.split(":")[0]) / "bin"


def uninstall_steps(p: GlobalPkg) -> list[Step]:
    if not p.removable:
        return []
    if p.manager == "npm":
        npm = _npm_exe() or "npm"
        return [Step(f"npm: remove {p.name}", [npm, "uninstall", "-g", p.name], env={"PATH": f"{os.path.dirname(npm)}:/usr/bin:/bin"})]
    if p.manager == "pnpm":
        return [Step(f"pnpm: remove {p.name}", ["pnpm", "remove", "-g", p.name])]
    if p.manager == "pipx":
        return [Step(f"pipx: remove {p.name}", ["pipx", "uninstall", p.extra.get("venv", p.name)])]
    if p.manager == "uv":
        return [Step(f"uv: remove {p.name}", ["uv", "tool", "uninstall", p.name])]
    if p.manager == "cargo":
        return [Step(f"cargo: remove {p.name}", ["cargo", "uninstall", p.name])]
    if p.manager == "go" and p.path:
        return [Step(f"Delete {tilde(p.path)}", ["rm", "-f", p.path])]
    return []


def update_all_steps(managers: dict[str, bool]) -> list[Step]:
    steps = []
    if managers.get("npm"):
        npm = _npm_exe() or "npm"
        steps.append(Step("npm: update global packages", [npm, "update", "-g"], env={"PATH": f"{os.path.dirname(npm)}:/usr/bin:/bin"}, optional=True))
    if managers.get("pnpm"):
        steps.append(Step("pnpm: update global packages", ["pnpm", "update", "-g"], optional=True))
    if managers.get("pipx"):
        steps.append(Step("pipx: upgrade every app", ["pipx", "upgrade-all"], optional=True))
    if managers.get("uv"):
        steps.append(Step("uv: upgrade every tool", ["uv", "tool", "upgrade", "--all"], optional=True))
    return steps


def parse_npm_outdated(text: str) -> dict[str, dict]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return {k: {"current": v.get("current", ""), "latest": v.get("latest", ""), "wanted": v.get("wanted", "")}
            for k, v in data.items() if isinstance(v, dict)}


def npm_outdated() -> dict[str, dict]:
    npm = _npm_exe()
    if not npm:
        return {}
    return parse_npm_outdated(sh([npm, "outdated", "-g", "--json"], timeout=60, env=_node_env(npm)).out)


# ---------------------------------------------------------------- Python versions with uv

def parse_uv_python_list(text: str) -> list[dict]:
    """`uv python list` lines: 'cpython-3.12.7-linux-x86_64-gnu   /path/to/python' or '<download available>'."""
    res = []
    for line in text.splitlines():
        parts = line.split(None, 1)
        if not parts or not re.match(r"^[a-z]+-\d", parts[0]):
            continue
        key = parts[0]
        where = parts[1].strip() if len(parts) > 1 else ""
        m = re.match(r"^([a-z]+)-(\d+\.\d+\.\d+[a-z0-9]*)(\+[a-z]+)?-", key)
        if not m:
            continue
        impl, ver, variant = m.group(1), m.group(2), (m.group(3) or "").lstrip("+")
        download = where.startswith("<download")
        path = "" if download else where.split(" -> ")[0].strip()
        managed = "/uv/python/" in path
        res.append({"key": key, "impl": impl, "version": ver, "minor": ".".join(ver.split(".")[:2]), "variant": variant,
                    "installed": not download, "path": path, "managed": managed, "system": bool(path) and not managed})
    return res


def uv_pythons() -> dict:
    """{'uv': bool, 'installed': [...], 'available': [...], 'global_pin': '', 'pin_global': bool}"""
    uv = which("uv")
    if not uv:
        return {"uv": False, "installed": [], "available": [], "global_pin": "", "pin_global": False}
    rows = [r for r in parse_uv_python_list(sh([uv, "python", "list"], timeout=20).out) if r["impl"] == "cpython" and not r["variant"]]
    seen_paths: set[str] = set()
    installed = []
    for r in rows:
        if r["installed"]:
            real = os.path.realpath(r["path"]) if r["path"] else r["key"]
            if real in seen_paths:
                continue
            seen_paths.add(real)
            installed.append(r)
    have_minor = {r["minor"] for r in installed if r["managed"]}
    available, seen_minor = [], set()
    for r in rows:
        if not r["installed"] and r["minor"] not in seen_minor and r["minor"] not in have_minor and not re.search(r"[a-z]", r["version"]):
            seen_minor.add(r["minor"])
            available.append(r)
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "uv/.python-version"
    pin_help = sh([uv, "python", "pin", "--help"], timeout=10).out
    return {"uv": True, "installed": installed, "available": available, "global_pin": read(cfg).strip(), "pin_global": "--global" in pin_help}


def uv_python_install(minor: str) -> list[Step]:
    return [Step(f"Download and install Python {minor}", ["uv", "python", "install", minor])]


def uv_python_uninstall(version: str) -> list[Step]:
    return [Step(f"Remove Python {version} (uv's copy)", ["uv", "python", "uninstall", version])]


def uv_python_pin(minor: str) -> list[Step]:
    return [Step(f"Use Python {minor} for new projects", ["uv", "python", "pin", "--global", minor])]


def uv_install_steps() -> list[Step]:
    if has("pipx"):
        return [Step("Install uv with pipx", ["pipx", "install", "uv"])]
    # Avoid `curl | sh`: use Python's package installer so the downloaded artifact is
    # handled by a package manager and no network response is executed as a shell script.
    return [Step("Install uv with Python", ["python3", "-m", "pip", "install", "--user", "uv"])]
