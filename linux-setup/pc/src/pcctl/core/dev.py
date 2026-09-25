"""Developer stuff: language versions, pm2 bots, containers, git projects, dev servers on ports."""

from __future__ import annotations

import glob
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
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


# ---------------------------------------------------------------- dev servers: stop all (P7)

DEV_PROCS = {"node", "next-server", "vite", "python", "python3", "uvicorn", "gunicorn", "hypercorn", "daphne", "flask", "ruby", "puma",
             "rails", "php", "bun", "deno", "go", "air", "java", "esbuild", "nodemon", "npm", "pnpm", "yarn", "hugo", "jekyll", "dotnet",
             "jupyter-lab", "jupyter-notebook", "streamlit", "caddy", "wrangler", "workerd", "astro", "nuxt", "remix", "turbo"}
DEV_WORDS = ("npm run", "pnpm dev", "yarn dev", "vite", "next dev", "next-server", "runserver", "flask run", "uvicorn", "manage.py",
             "http.server", "webpack", "rails s", "hugo server", "jekyll serve", "astro dev", "nuxt dev", "jupyter", "streamlit", "wrangler")
NOT_DEV = {"code", "code-insiders", "cursor", "docker-proxy", "rootlessport", "spotify", "steam", "chrome", "firefox", "slack", "discord",
           "zed", "zeditor", "ollama", "syncthing", "kdeconnectd", "gsd-sharing", "gnome-remote-de"}


def is_dev_server(process: str, cmd: str = "") -> bool:
    """Is this listening program one of your dev servers (not an app like VS Code, Docker or Spotify)?"""
    name = (process or "").lower()
    if name in NOT_DEV:
        return False
    low = (cmd or "").lower()
    if name in DEV_PROCS:
        return True
    return any(w in low for w in DEV_WORDS)


def _pm2_managed(pid: int) -> bool:
    """pm2 restarts whatever it manages, so stopping those here is pointless - they belong on the pm2 tab."""
    try:
        import psutil
        for parent in psutil.Process(pid).parents():
            name = parent.name()
            if name.startswith("PM2") or "God Daemon" in " ".join(parent.cmdline()[:2]):
                return True
    except Exception:  # noqa: BLE001 - process vanished or isn't ours
        return False
    return False


def stop_targets(rows: list[dict], skip_pm2: bool = True) -> tuple[list[dict], list[dict]]:
    """Split dev-server table rows (dicts with pid, process, cmd, port) into (to stop, skipped with a reason)."""
    stop, skipped, seen = [], [], set()
    for r in rows:
        pid = r.get("pid")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if not is_dev_server(r.get("process", ""), r.get("cmd", "")):
            skipped.append({**r, "why": "not a dev server"})
        elif skip_pm2 and _pm2_managed(pid):
            skipped.append({**r, "why": "managed by pm2"})
        else:
            stop.append(r)
    return stop, skipped


def stop_steps(targets: list[dict], force: bool = False) -> list[Step]:
    sig = "-KILL" if force else "-TERM"
    return [Step(f"{'Force-stop' if force else 'Stop'} {t.get('process', '?')} on port {t.get('port', '?')} (process {t['pid']})",
                 ["kill", sig, str(t["pid"])], optional=True) for t in targets]


def still_running(pids: list[int]) -> list[int]:
    import psutil
    res = []
    for pid in pids:
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                res.append(pid)
        except psutil.Error:
            pass
    return res


# ---------------------------------------------------------------- projects: fetch all / unpushed work (P6)

def parse_branches(text: str) -> dict:
    """`git for-each-ref --format='%(refname)%09%(upstream:short)%09%(upstream:track)' refs/heads refs/remotes`"""
    local, remote = [], set()
    for line in text.splitlines():
        ref, _, rest = line.partition("\t")
        up, _, track = rest.partition("\t")
        if ref.startswith("refs/remotes/"):
            name = ref[len("refs/remotes/"):]
            if not name.endswith("/HEAD"):
                remote.add(name)
            continue
        if not ref.startswith("refs/heads/"):
            continue
        a = re.search(r"ahead (\d+)", track)
        b = re.search(r"behind (\d+)", track)
        local.append({"name": ref[len("refs/heads/"):], "upstream": up, "ahead": int(a.group(1)) if a else 0,
                      "behind": int(b.group(1)) if b else 0, "gone": "gone" in track})
    for br in local:
        br["on_remote"] = any(r.split("/", 1)[-1] == br["name"] for r in remote)
    return {"local": local, "remote": sorted(remote)}


def attention(r: dict) -> list[tuple[str, str]]:
    """Plain-English reasons a project needs you: [(kind warn|info, text)]"""
    res = []
    changes = r.get("changed", 0) + r.get("untracked", 0)
    if changes:
        res.append(("warn", f"{changes} uncommitted change{'s' if changes != 1 else ''}"))
    if r.get("ahead"):
        res.append(("warn", f"{r['ahead']} commit{'s' if r['ahead'] != 1 else ''} not pushed"))
    if r.get("remote") and r.get("branch") and r["branch"] != "(detached)" and not r.get("upstream"):
        res.append(("warn", f"branch {r['branch']} isn't on the remote yet"))
    if r.get("behind"):
        res.append(("info", f"{r['behind']} new commit{'s' if r['behind'] != 1 else ''} to pull"))
    others = [b for b in r.get("branches", []) if b["name"] != r.get("branch") and
              (b["ahead"] or (r.get("remote") and not b["upstream"] and not b["on_remote"]))]
    if others:
        res.append(("warn", f"{len(others)} other branch{'es' if len(others) != 1 else ''} with unpushed work ({', '.join(b['name'] for b in others[:3])})"))
    gone = [b["name"] for b in r.get("branches", []) if b["gone"]]
    if gone:
        res.append(("info", f"{len(gone)} branch{'es' if len(gone) != 1 else ''} deleted on the remote (merged?) - safe to delete: {', '.join(gone[:3])}"))
    if r.get("stashes"):
        res.append(("info", f"{r['stashes']} stash{'es' if r['stashes'] != 1 else ''} (changes you set aside)"))
    if not r.get("remote"):
        res.append(("info", "not backed up anywhere (no remote)"))
    return res


def repo_status_full(path: str) -> dict:
    """repo_status() plus every branch's push state, stashes and a plain-English 'attention' list."""
    st = repo_status(path)
    fmt = "%(refname)%09%(upstream:short)%09%(upstream:track)"
    br = parse_branches(out(["git", "-C", path, "for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes"], timeout=10))
    st["branches"] = br["local"]
    st["stashes"] = len([ln for ln in out(["git", "-C", path, "stash", "list"], timeout=10).splitlines() if ln.strip()])
    st["attention"] = attention(st)
    st["needs_you"] = any(k == "warn" for k, _ in st["attention"])
    return st


def repos_full(roots: list[Path] | None = None) -> list[dict]:
    paths = find_repos(roots)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(repo_status_full, paths))
    res.sort(key=lambda r: -r["last_commit"])
    return res


FETCH_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10"}


def fetch_all_steps(repos_: list[dict]) -> list[Step]:
    """git fetch every project that has a remote. Never asks for passwords (would hang), never changes your files."""
    return [Step(f"Fetch {r['name']}", ["git", "-C", r["path"], "fetch", "--all", "--prune"], env=FETCH_ENV, optional=True)
            for r in repos_ if r.get("remote")]


# ---------------------------------------------------------------- Docker disk usage (P2)

_UNITS = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}


def parse_size(text) -> int:
    """Docker's '1.29GB', '512.3kB', '0B', '12.5MB (45%)' -> bytes"""
    if isinstance(text, (int, float)):
        return int(text)
    m = re.match(r"\s*([\d.]+)\s*([a-zA-Z]*)", str(text or ""))
    if not m:
        return 0
    try:
        return round(float(m.group(1)) * _UNITS.get(m.group(2).lower() or "b", 1))
    except ValueError:
        return 0


def _json_items(text: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        res = []
        for ln in text.splitlines():
            try:
                res.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return res


DF_TYPES = {"images": ("images", "Images"), "containers": ("containers", "Containers"), "local volumes": ("volumes", "Volumes"),
            "volumes": ("volumes", "Volumes"), "build cache": ("cache", "Build cache")}


def parse_docker_df(text: str) -> list[dict]:
    """`docker system df --format '{{json .}}'` (one object per line) or podman's JSON array."""
    res = []
    for d in _json_items(text):
        if not isinstance(d, dict):
            continue
        kind = DF_TYPES.get(str(d.get("Type", "")).lower())
        if not kind:
            continue
        size = d.get("RawSize") if isinstance(d.get("RawSize"), (int, float)) else parse_size(d.get("Size"))
        rec = d.get("RawReclaimable") if isinstance(d.get("RawReclaimable"), (int, float)) else parse_size(d.get("Reclaimable"))
        count = d.get("TotalCount", d.get("Total", 0))
        res.append({"type": kind[0], "label": kind[1], "count": int(count or 0), "active": int(d.get("Active") or 0),
                    "size": int(size or 0), "reclaimable": int(rec or 0)})
    return res


def parse_docker_df_verbose(text: str) -> dict:
    """`docker system df -v --format '{{json .}}'` -> {'images', 'containers', 'volumes', 'cache'} lists."""
    items = _json_items(text)
    data = items[0] if items and isinstance(items[0], dict) else {}
    images = []
    for i in data.get("Images") or []:
        repo, tag = i.get("Repository", "<none>"), i.get("Tag", "<none>")
        used = int(str(i.get("Containers", "0")).strip() or 0) if str(i.get("Containers", "0")).strip().isdigit() else 0
        images.append({"id": str(i.get("ID", ""))[:19], "name": f"{repo}:{tag}" if repo != "<none>" else "<untagged>",
                       "size": parse_size(i.get("Size")), "unique": parse_size(i.get("UniqueSize") or i.get("Size")), "used_by": used,
                       "dangling": repo == "<none>", "age": i.get("CreatedSince", "")})
    containers = []
    for c in data.get("Containers") or []:
        state = str(c.get("State", "")).lower()
        containers.append({"id": str(c.get("ID", ""))[:12], "name": str(c.get("Names", "")).split(",")[0], "image": c.get("Image", ""),
                           "size": parse_size(c.get("Size")), "state": state, "status": c.get("Status", ""), "running": state == "running"})
    volumes = [{"name": v.get("Name", ""), "size": parse_size(v.get("Size")), "links": int(v.get("Links") or 0) if str(v.get("Links", "")).isdigit() else 0,
                "anonymous": bool(re.fullmatch(r"[0-9a-f]{64}", v.get("Name", "")))} for v in data.get("Volumes") or []]
    cache = [{"id": b.get("ID", ""), "size": parse_size(b.get("Size")), "in_use": str(b.get("InUse", "")).lower() == "true"}
             for b in data.get("BuildCache") or []]
    return {"images": images, "containers": containers, "volumes": volumes, "cache": cache}


def docker_problem(code: int, text: str) -> str:
    """'' | 'missing' | 'permission' | 'stopped' | 'error'"""
    low = text.lower()
    if code == 127 or "not installed" in low:
        return "missing"
    if "permission denied" in low and ("docker.sock" in low or "daemon socket" in low or "docker api" in low):
        return "permission"
    if "cannot connect to the docker daemon" in low or "is the docker daemon running" in low or "failed to connect to the docker api" in low \
            or "no such file or directory" in low and "docker.sock" in low:
        return "stopped"
    return "error" if code else ""


def docker_disk() -> dict:
    tool = "docker" if has("docker") else ("podman" if has("podman") else "")
    res = {"tool": tool, "problem": "", "message": "", "summary": [], "images": [], "containers": [], "volumes": [], "cache": []}
    if not tool:
        res["problem"] = "missing"
        return res
    r = sh([tool, "system", "df", "--format", "{{json .}}" if tool == "docker" else "json"], timeout=30)
    prob = docker_problem(r.code, r.err + r.out if not r.ok else "")
    if prob:
        res["problem"], res["message"] = prob, (r.err or r.out).strip().splitlines()[-1] if (r.err or r.out).strip() else ""
        return res
    res["summary"] = parse_docker_df(r.out)
    if tool == "docker":
        v = sh([tool, "system", "df", "-v", "--format", "{{json .}}"], timeout=60)
        if v.ok:
            res.update(parse_docker_df_verbose(v.out))
    return res


PRUNE = {
    "images": (["image", "prune", "-a", "-f"], "Remove images no container uses",
               "Deletes every image that no container (running or stopped) uses. They download again automatically the next time you need them.", False),
    "containers": (["container", "prune", "-f"], "Remove stopped containers",
                   "Deletes containers that aren't running. Their images stay. Anything a container saved inside itself (not in a volume) is lost.", False),
    "volumes": (["volume", "prune", "-f"], "Remove unused volumes",
                "Volumes hold data such as your projects' databases. This deletes volumes no container is using - if you removed a project's containers, "
                "its database goes too and can't be recovered. Newer Docker only removes unnamed (anonymous) volumes this way; named ones are "
                "listed below to delete one by one.", True),
    "cache": (["builder", "prune", "-a", "-f"], "Clear the build cache",
              "Deletes cached build layers. Nothing breaks - your next docker build is just slower once.", False),
}


def docker_prune_steps(kind: str, tool: str = "docker") -> tuple[list[Step], str, bool]:
    """(steps, explanation, dangerous) for one kind of cleanup."""
    args, title, why, danger = PRUNE[kind]
    if tool == "podman" and kind == "cache":
        args = ["system", "prune", "-f"]
    return [Step(title, [tool, *args])], why, danger


def docker_remove_steps(kind: str, item: dict, tool: str = "docker") -> list[Step]:
    if kind == "images":
        return [Step(f"Remove image {item['name']}", [tool, "rmi", item["id"]])]
    if kind == "containers":
        return [Step(f"Remove container {item['name']}", [tool, "rm", item["id"]])]
    if kind == "volumes":
        return [Step(f"Delete volume {item['name']} and its data", [tool, "volume", "rm", item["name"]])]
    return []


def docker_fix_steps(problem: str) -> tuple[list[Step], str]:
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "me"
    if problem == "permission":
        return ([Step(f"Add {user} to the docker group", ["usermod", "-aG", "docker", user], root=True)],
                "Lets you use docker without sudo. Log out and back in afterwards (or restart) for it to take effect. "
                "Note: members of the docker group can control the whole PC through Docker, so only do this on your own computer.")
    if problem == "stopped":
        return ([Step("Start Docker (and on every boot)", ["systemctl", "enable", "--now", "docker.service", "docker.socket"], root=True)],
                "Docker's background service isn't running.")
    if problem == "missing":
        return ([Step("Install Docker from Ubuntu", ["apt-get", "install", "-y", "docker.io", "docker-buildx", "docker-compose-v2"], root=True,
                      env={"DEBIAN_FRONTEND": "noninteractive"})], "Installs Docker from Ubuntu's own repositories.")
    return [], ""
