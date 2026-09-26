"""Small, safe helpers for PC Command Center's own local state.

State files can contain command history, paths and diagnostics.  Keep the directory
private and replace files atomically so a power loss cannot leave half-written JSON.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def private_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def atomic_write_text(path: str | Path, text: str, *, mode: int = 0o600, encoding: str = "utf-8",
                      private_parent: bool = True) -> None:
    p = Path(path)
    if private_parent:
        private_dir(p.parent)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
        try:
            dfd = os.open(p.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_private(path: str | Path, text: str, *, mode: int = 0o600, encoding: str = "utf-8") -> None:
    p = Path(path)
    private_dir(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode)
    try:
        try:
            os.fchmod(fd, mode)
        except OSError:
            pass
        with os.fdopen(fd, "a", encoding=encoding) as f:
            f.write(text)
            f.flush()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
