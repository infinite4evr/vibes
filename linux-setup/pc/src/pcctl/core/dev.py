"""Developer stuff: language versions, pm2 bots, containers, git projects, dev servers on ports."""

from __future__ import annotations

import glob
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .run import HOME, Step, has, out, read, sh, which

# ---------------------------------------------------------------- runtimes

TOOLS = [
    ("Node.js", ["node", "--version"]),
    ("npm", ["npm", "--version"]),
    ("pnpm", ["pnpm", "--version"]),
    ("Bun", ["bun", "--version"]),
    ("Python", ["python3", "--version"]),
    ("uv", ["uv", "--version"]),
    ("pip", ["pip3", "--version"]),
    ("Go", ["go", "version"]),
    ("Rust", ["rustc", "--version"]),
    ("Java", ["java", "-version"]),
    (".NET", ["dotnet", "--version"]),
    ("Git", ["git", "--version"]),
    ("GitHub CLI", ["gh", "--version"]),
    ("Docker", ["docker", "--version"]),
    ("Podman", ["podman", "--version"]),
    ("pm2", ["pm2", "--version"]),
]


def _nvm_bin(name: str) -> str | None:
    """Tools installed with npm under nvm aren't on PATH outside an interactive shell."""
    found = which(name)
    if found:
        return found
    default = nvm_default()
    cands = []
    if default:
        cands.append(HOME / f".nvm/versions/node/{default}/bin/{name}")
    cands += sorted((Path(p) for p in glob.glob(str(HOME / f".nvm/versions/node/*/bin/{name}"))), reverse=True)
    for c in cands:
        if c.exists():
            return str(c)
    return None


def runtimes() -> list[dict]:
    res = []
    for label, cmd in TOOLS:
        path = _nvm_bin(cmd[0]) if cmd[0] in ("node", "npm", "pnpm", "pm2") else which(cmd[0])
        if not path:
            continue
        r = sh([path, *cmd[1:]], timeout=8, env={**os.environ, "PATH": f"{os.path.dirname(path)}:{os.environ.get('PATH', '')}"})
        text = [ln for ln in (r.out + "\n" + r.err).strip().splitlines() if ln.strip() and not ln.startswith("Picked up")]
        ver = ""
        joined = "\n".join(text)
        m = re.search(r'version "([^"]+)"', joined) or re.search(r"(\d+\.\d+(?:\.\d+)?)", joined)
        if m:
            ver = m.group(1)
        elif text:
            ver = text[0][:30]
        res.append({"name": label, "version": ver, "path": path.replace(str(HOME), "~")})
    return res


def nvm_default() -> str:
    alias = read(HOME / ".nvm/alias/default").strip()
    if not alias:
        return ""
    installed = sorted((os.path.basename(p) for p in glob.glob(str(HOME / ".nvm/versions/node/v*"))), key=_vkey)
    # alias can be "22", "v22.11.0", "lts/*", "lts/jod", "node"
    if alias.startswith("lts/"):
        target = read(HOME / ".nvm/alias" / alias).strip()
        alias = target or alias
    if alias in ("node", "stable") and installed:
        return installed[-1]
    want = alias.lstrip("v")
    matches = [v for v in installed if v.lstrip("v") == want or v.lstrip("v").startswith(want + ".")]
    return matches[-1] if matches else ""


def _vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in v.lstrip("v").split("."))


def pm2_node_versions() -> set[str]:
    used = set()
    for f in glob.glob("/etc/systemd/system/pm2-*.service"):
        used.update(re.findall(r"\.nvm/versions/node/(v[\d.]+)", read(f)))
    pm2 = _nvm_bin("pm2")
    if pm2:
        m = re.search(r"node/(v[\d.]+)/", pm2)
        if m:
            used.add(m.group(1))
    return used


def node_versions() -> list[dict]:
    base = HOME / ".nvm/versions/node"
    if not base.is_dir():
        return []
    default = nvm_default()
    pm2 = pm2_node_versions()
    vs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: _vkey(d.name))
    newest = vs[-1].name if vs else ""
    res = []
    for d in vs:
        tags = []
        if d.name == default:
            tags.append("default")
        if d.name in pm2:
            tags.append("pm2")
        if not default and d.name == newest:
            tags.append("newest")
        res.append({"version": d.name, "path": str(d), "tags": tags, "protected": bool(tags)})
    return res


def python_versions() -> list[dict]:
    res = []
    py = HOME / ".pyenv/versions"
    glob_v = read(HOME / ".pyenv/version").split()[0] if (HOME / ".pyenv/version").exists() and read(HOME / ".pyenv/version").split() else ""
    if py.is_dir():
        for d in sorted(py.iterdir()):
            if d.is_dir():
                res.append({"version": d.name, "manager": "pyenv", "tags": ["global"] if d.name == glob_v else []})
    if has("uv"):
        for line in out(["uv", "python", "list", "--only-installed"], timeout=15).splitlines():
            parts = line.split()
            if parts:
                res.append({"version": parts[0], "manager": "uv", "tags": []})
    return res


def nvm_cmd(args: str) -> list[str]:
    return ["bash", "-c", f'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh" && nvm {args}']


# ---------------------------------------------------------------- pm2

def pm2_list() -> list[dict]:
    pm2 = _nvm_bin("pm2")
    if not pm2:
        return []
    env = {**os.environ, "PATH": f"{os.path.dirname(pm2)}:{os.environ.get('PATH', '')}"}
    r = sh([pm2, "jlist"], timeout=15, env=env)
    return parse_pm2(r.out)


def parse_pm2(text: str) -> list[dict]:
    start = text.find("[")
    if start < 0:
        return []
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        return []
    res = []
    for p in data:
        env = p.get("pm2_env", {})
        mon = p.get("monit", {})
        up = env.get("pm_uptime")
        res.append({
            "name": p.get("name", "?"),
            "id": p.get("pm_id"),
            "status": env.get("status", "?"),
            "cpu": mon.get("cpu", 0),
            "mem": mon.get("memory", 0),
            "restarts": env.get("restart_time", 0),
            "uptime": (time.time() - up / 1000) if up and env.get("status") == "online" else None,
            "cwd": env.get("pm_cwd", ""),
            "script": env.get("pm_exec_path", ""),
        })
    return res


def pm2_steps(action: str, name: str) -> list[Step]:
    pm2 = _nvm_bin("pm2") or "pm2"
    env = {"PATH": f"{os.path.dirname(pm2)}:/usr/bin:/bin"}
    return [Step(f"pm2 {action} {name}", [pm2, action, str(name)], env=env)] + (
        [Step("Save pm2 list (survives reboot)", [pm2, "save"], env=env, optional=True)] if action in ("stop", "start", "delete") else [])


def pm2_logs(name: str, lines: int = 200) -> str:
    pm2 = _nvm_bin("pm2")
    if not pm2:
        return ""
    env = {**os.environ, "PATH": f"{os.path.dirname(pm2)}:{os.environ.get('PATH', '')}"}
    return sh([pm2, "logs", str(name), "--lines", str(lines), "--nostream", "--raw"], timeout=15, env=env).out


# ---------------------------------------------------------------- containers

def container_tool() -> str | None:
    return "podman" if has("podman") else ("docker" if has("docker") else None)


def containers() -> list[dict]:
    tool = container_tool()
    if not tool:
        return []
    r = sh([tool, "ps", "-a", "--format", "json"], timeout=20)
    return parse_containers(r.out)


def parse_containers(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text) if text.startswith("[") else [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    except json.JSONDecodeError:
        return []
    res = []
    for c in data:
        names = c.get("Names")
        name = names[0] if isinstance(names, list) and names else (names or c.get("Name") or c.get("Id", "")[:12])
        state = c.get("State") or c.get("Status", "")
        ports = c.get("Ports")
        if isinstance(ports, list):
            ports = ", ".join(f"{p.get('host_port', p.get('hostPort', ''))}→{p.get('container_port', p.get('containerPort', ''))}" for p in ports if isinstance(p, dict))
        res.append({"id": (c.get("Id") or c.get("ID") or "")[:12], "name": name, "image": c.get("Image", ""),
                    "state": str(state).lower(), "status": c.get("Status", ""), "ports": ports or ""})
    return res


# ---------------------------------------------------------------- git projects

SKIP_DIRS = {"node_modules", ".cache", ".local", ".npm", ".nvm", ".pyenv", ".cargo", ".rustup", "snap", ".var",
             "venv", ".venv", "__pycache__", ".git", "go", ".vscode", ".mozilla", ".config", ".texlive2025", "VirtualBox VMs"}


def find_repos(roots: list[Path] | None = None, max_depth: int = 4, limit: int = 200) -> list[str]:
    roots = roots or [HOME]
    found: list[str] = []
    for root in roots:
        base = len(root.parts)
        for cur, dirs, _ in os.walk(root):
            if ".git" in dirs or os.path.isfile(os.path.join(cur, ".git")):
                found.append(cur)
                dirs[:] = []
                continue
            depth = len(Path(cur).parts) - base
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (d.startswith(".") and depth == 0 and d not in (".dotfiles",))] if depth < max_depth else []
            if len(found) >= limit:
                return found
    return found


def parse_git_status(text: str) -> dict:
    info = {"branch": "", "ahead": 0, "behind": 0, "changed": 0, "untracked": 0, "upstream": ""}
    for line in text.splitlines():
        if line.startswith("# branch.head "):
            info["branch"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                info["ahead"], info["behind"] = int(m.group(1)), int(m.group(2))
        elif line.startswith(("1 ", "2 ", "u ")):
            info["changed"] += 1
        elif line.startswith("? "):
            info["untracked"] += 1
    return info


def repo_status(path: str) -> dict:
    st = parse_git_status(sh(["git", "-C", path, "status", "--porcelain=v2", "--branch"], timeout=15).out)
    last = out(["git", "-C", path, "log", "-1", "--format=%ct\t%s"], timeout=10)
    ts, _, msg = last.partition("\t")
    remote = out(["git", "-C", path, "remote", "get-url", "origin"], timeout=5)
    st.update({"path": path, "name": os.path.basename(path), "last_commit": float(ts) if ts.isdigit() else 0.0,
               "message": msg, "remote": remote})
    return st


def repos(roots: list[Path] | None = None) -> list[dict]:
    paths = find_repos(roots)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(repo_status, paths))
    res.sort(key=lambda r: -r["last_commit"])
    return res


# ---------------------------------------------------------------- dev servers

DEV_HINTS = {"node": "Node", "next-server": "Next.js", "vite": "Vite", "python": "Python", "python3": "Python",
             "uvicorn": "Uvicorn", "gunicorn": "Gunicorn", "ruby": "Ruby", "java": "Java", "php": "PHP", "bun": "Bun",
             "deno": "Deno", "go": "Go", "postgres": "PostgreSQL", "mysqld": "MySQL", "redis-server": "Redis",
             "mongod": "MongoDB", "docker-proxy": "Docker", "rootlessport": "Podman", "code": "VS Code"}
