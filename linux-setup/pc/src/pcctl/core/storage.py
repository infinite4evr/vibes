"""Disk usage: folder sizes you can drill into, big files, and hints about what things are."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .run import HOME, sh


@dataclass
class Entry:
    path: str
    size: int
    is_dir: bool

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("/")) or self.path


def parse_du(text: str, root: str) -> list[Entry]:
    res: list[Entry] = []
    root_norm = os.path.normpath(root)
    for line in text.splitlines():
        if "\t" not in line:
            continue
        size, path = line.split("\t", 1)
        if not size.isdigit() or os.path.normpath(path) == root_norm:
            continue
        res.append(Entry(path, int(size), os.path.isdir(path) and not os.path.islink(path)))
    res.sort(key=lambda e: -e.size)
    return res


def children(path: str | Path, timeout: float = 180) -> tuple[int, list[Entry]]:
    """Size of each item directly inside `path` (stays on one filesystem). Returns (total, items)."""
    path = str(path)
    r = sh(["du", "-xaB1", "--max-depth=1", path], timeout=timeout)
    total = 0
    for line in r.out.splitlines():
        if "\t" in line:
            s, p = line.split("\t", 1)
            if os.path.normpath(p) == os.path.normpath(path) and s.isdigit():
                total = int(s)
    return total, parse_du(r.out, path)


def big_files(root: str | Path = HOME, min_mb: int = 500, limit: int = 40) -> list[Entry]:
    r = sh(["find", str(root), "-xdev", "-type", "f", "-size", f"+{min_mb}M",
            "-not", "-path", "*/.local/share/Trash/*", "-printf", "%s\t%p\n"], timeout=180)
    items = []
    for line in r.out.splitlines():
        s, _, p = line.partition("\t")
        if s.isdigit():
            items.append(Entry(p, int(s), False))
    items.sort(key=lambda e: -e.size)
    return items[:limit]


# What common folders are, and whether they're safe to delete.
HINTS: list[tuple[str, str]] = [
    (".cache", "App caches - safe to clean (Cleanup tab)"),
    ("node_modules", "npm packages - rebuilt by `npm install`"),
    (".npm", "npm download cache - safe to clean"),
    (".nvm", "Node.js versions (nvm)"),
    (".pyenv", "Python versions (pyenv)"),
    (".local/share/Trash", "Trash"),
    (".local/share/flatpak", "Flatpak apps (per-user)"),
    (".var", "Flatpak app data"),
    ("snap", "Snap app data"),
    (".texlive2025", "TeX Live user files"),
    ("VirtualBox VMs", "Virtual machine disks"),
    (".android", "Android tools data"),
    (".gradle", "Gradle build cache - safe to delete"),
    (".cargo", "Rust toolchain + crates"),
    (".rustup", "Rust toolchains"),
    (".dotnet", ".NET SDK files"),
    (".vscode", "VS Code extensions"),
    (".config/Code", "VS Code settings + caches"),
    (".mozilla", "Firefox profile"),
    (".config/google-chrome", "Chrome profile"),
    (".config/BraveSoftware", "Brave profile"),
    (".local/share/containers", "Podman images and containers"),
    (".pm2", "pm2 process manager (your bots)"),
    ("Zotero", "Zotero library"),
    (".venv", "Python virtual environment - recreate with `uv sync`"),
    ("venv", "Python virtual environment"),
    ("__pycache__", "Python bytecode - safe to delete"),
    (".next", "Next.js build output - rebuilt automatically"),
    ("dist", "Build output"),
    ("target", "Rust/Java build output"),
]


def hint_for(path: str) -> str:
    rel = os.path.relpath(path, HOME) if path.startswith(str(HOME)) else path
    for key, text in HINTS:
        if rel == key or rel.endswith("/" + key) or os.path.basename(path) == key:
            return text
    return ""


@dataclass
class Project:
    path: str
    node_modules: int
    last_touched: float


def stale_node_modules(roots: list[Path] | None = None, days: int = 30, max_depth: int = 5) -> list[Project]:
    """node_modules folders in projects you haven't touched for `days` days."""
    roots = roots or [HOME / d for d in ("Documents", "Projects", "projects", "code", "Code", "dev", "src", "Desktop", "work")]
    found: list[Project] = []
    cutoff = time.time() - days * 86400
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for cur, dirs, _files in os.walk(root):
            depth = len(Path(cur).parts) - base_depth
            if "node_modules" in dirs:
                nm = os.path.join(cur, "node_modules")
                last = latest_mtime(cur, skip={"node_modules", ".git"})
                if last < cutoff:
                    size = dir_size(nm)
                    if size > 1024 * 1024:
                        found.append(Project(cur, size, last))
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "__pycache__")] if depth < max_depth else []
    found.sort(key=lambda p: -p.node_modules)
    return found


def latest_mtime(folder: str, skip: set[str], depth: int = 2) -> float:
    """Newest modification time of files in a project (a couple of levels deep), plus git activity."""
    latest = 0.0
    for marker in (".git/index", ".git/logs/HEAD", ".git/FETCH_HEAD"):
        try:
            latest = max(latest, os.stat(os.path.join(folder, marker)).st_mtime)
        except OSError:
            pass
    stack = [(folder, 0)]
    while stack:
        cur, d = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    if e.name in skip:
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    latest = max(latest, st.st_mtime)
                    if d < depth and e.is_dir(follow_symlinks=False):
                        stack.append((e.path, d + 1))
        except OSError:
            pass
    return latest


def dir_size(path: str | Path) -> int:
    r = sh(["du", "-sxB1", str(path)], timeout=120)
    try:
        return int(r.out.split("\t", 1)[0])
    except (ValueError, IndexError):
        return 0


def old_downloads(days: int = 90) -> list[Entry]:
    d = HOME / "Downloads"
    if not d.is_dir():
        return []
    cutoff = time.time() - days * 86400
    res = []
    for e in os.scandir(d):
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if max(st.st_mtime, st.st_atime) < cutoff:
            size = dir_size(e.path) if e.is_dir(follow_symlinks=False) else st.st_size
            res.append(Entry(e.path, size, e.is_dir(follow_symlinks=False)))
    res.sort(key=lambda x: -x.size)
    return res
