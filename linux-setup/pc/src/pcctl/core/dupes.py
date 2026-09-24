"""Find exact duplicate files: group by size, then a quick partial hash, then a full hash."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

SKIP = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".cache", "snap", ".var", ".local", ".npm", ".nvm", ".pyenv"}


def _hash(path: str, limit: int | None = None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if limit:
                h.update(f.read(limit))
                size = os.fstat(f.fileno()).st_size
                if size > limit * 2:  # also sample the end - catches files that only differ at the tail
                    f.seek(-limit, os.SEEK_END)
                    h.update(f.read(limit))
            else:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(roots: list[Path], min_size: int = 1024 * 1024, progress: Callable[[str], None] | None = None,
                    max_files: int = 200_000) -> list[list[dict]]:
    by_size: dict[int, list[str]] = {}
    seen_inodes: set[tuple[int, int]] = set()
    count = 0
    for root in roots:
        if not root.is_dir():
            continue
        for cur, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for n in files:
                p = os.path.join(cur, n)
                try:
                    st = os.stat(p, follow_symlinks=False)
                except OSError:
                    continue
                if not os.path.isfile(p) or os.path.islink(p) or st.st_size < min_size:
                    continue
                ino = (st.st_dev, st.st_ino)
                if ino in seen_inodes:  # hard links are not duplicates
                    continue
                seen_inodes.add(ino)
                by_size.setdefault(st.st_size, []).append(p)
                count += 1
                if count >= max_files:
                    break
    groups: list[list[dict]] = []
    candidates = [(s, ps) for s, ps in by_size.items() if len(ps) > 1]
    for i, (size, paths) in enumerate(sorted(candidates, key=lambda x: -x[0])):
        if progress and i % 20 == 0:
            progress(f"checking {i}/{len(candidates)} size groups")
        quick: dict[str, list[str]] = {}
        for p in paths:
            h = _hash(p, 64 * 1024)
            if h:
                quick.setdefault(h, []).append(p)
        for same in quick.values():
            if len(same) < 2:
                continue
            full: dict[str, list[str]] = {}
            for p in same:
                h = _hash(p) if size > 128 * 1024 else _hash(p, 64 * 1024)
                if h:
                    full.setdefault(h, []).append(p)
            for dup in full.values():
                if len(dup) > 1:
                    files = []
                    for p in dup:
                        try:
                            files.append({"path": p, "size": size, "mtime": os.path.getmtime(p)})
                        except OSError:
                            pass
                    files.sort(key=lambda f: (f["mtime"], len(f["path"])))  # keep the oldest / shortest path
                    if len(files) > 1:
                        groups.append(files)
    groups.sort(key=lambda g: -(g[0]["size"] * (len(g) - 1)))
    return groups
