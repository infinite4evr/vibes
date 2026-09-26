"""Opt-in diagnostic logging with aggressive secret redaction.

Debug logging is deliberately off by default.  When enabled it records app lifecycle,
commands, task state and failures to rotating files under ~/.local/state/pc/logs.
The logger never intentionally records raw command-line secrets or environment values.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import shlex
import threading
import time
import zipfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .state import private_dir

HOME = Path.home()
LOG_DIR = HOME / ".local/state/pc/logs"
LOG_FILE = LOG_DIR / "debug.log"

_lock = threading.RLock()
_enabled = False
_logger = logging.getLogger("pcctl")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False


class _PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating handler whose newly-created base file is always 0600."""

    def _open(self):  # type: ignore[override]
        flags = os.O_WRONLY | os.O_CREAT
        flags |= os.O_APPEND if "a" in self.mode else os.O_TRUNC
        fd = os.open(self.baseFilename, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)

# Common token formats plus generic key/value forms.  This intentionally errs on the
# side of hiding too much: support logs should be useful, not credential archives.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:sk-(?:proj-|svcacct-|admin-)?|gh[pousr]_|github_pat_|glpat-|xox[baprs]-|hf_|npm_|r8_)[A-Za-z0-9_.\-]{8,}"), "<redacted-token>"),
    (re.compile(r"(?i)(\b(?:password|passwd|passphrase|psk|token|secret|api[_-]?key|authorization|credential)\s*[=:]\s*)([^\s,;]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)(\b(?:password|passwd|passphrase|psk|token|secret|api[_-]?key|authorization|credential)\b\s+)([^\s]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)(https?://[^\s:/@]+:)([^\s@/]+)(@)"), r"\1<redacted>\3"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}"), r"\1<redacted>"),
]
_SENSITIVE_WORD = re.compile(r"(?i)(password|passwd|passphrase|psk|token|secret|api[-_]?key|authorization|credential|private[-_]?key)")


def redact_text(text: object, extra_values: Iterable[str] = ()) -> str:
    s = str(text)
    for value in extra_values:
        if value:
            s = s.replace(str(value), "<redacted>")
    for rx, repl in _PATTERNS:
        s = rx.sub(repl, s)
    return s


def redact_argv(argv: Sequence[object], *, extra_values: Iterable[str] = ()) -> list[str]:
    vals = [str(x) for x in argv]
    hidden = {str(v) for v in extra_values if v}
    out: list[str] = []
    hide_next = False
    for arg in vals:
        if arg in hidden:
            out.append("<redacted>")
            hide_next = False
            continue
        if hide_next:
            out.append("<redacted>")
            hide_next = False
            continue
        if "=" in arg:
            k, _v = arg.split("=", 1)
            if _SENSITIVE_WORD.search(k):
                out.append(k + "=<redacted>")
                continue
        out.append(redact_text(arg, hidden))
        if _SENSITIVE_WORD.search(arg.lstrip("-")) and "=" not in arg:
            hide_next = True
    return out


def redact_env(env: Mapping[str, object]) -> dict[str, str]:
    return {k: ("<redacted>" if _SENSITIVE_WORD.search(k) else redact_text(v)) for k, v in env.items()}


def display_argv(argv: Sequence[object], *, extra_values: Iterable[str] = ()) -> str:
    return shlex.join(redact_argv(argv, extra_values=extra_values))


def ensure_log_dir() -> Path:
    """Create the private diagnostics directory and return it."""
    return private_dir(LOG_DIR)

def configure(enabled: bool) -> None:
    global _enabled
    with _lock:
        _enabled = bool(enabled)
        if not _enabled:
            # release the file, so turning logging back on honours a changed LOG_FILE
            for h in [h for h in _logger.handlers if isinstance(h, _PrivateRotatingFileHandler)]:
                h.close()
                _logger.removeHandler(h)
        # look for our own handler: test runners and other tools may attach theirs to this logger
        if _enabled and not any(isinstance(h, _PrivateRotatingFileHandler) for h in _logger.handlers):
            private_dir(LOG_DIR)
            handler = _PrivateRotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=4, encoding="utf-8")
            try:
                os.chmod(LOG_FILE, 0o600)
            except OSError:
                pass
            handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
            _logger.addHandler(handler)
        if _enabled:
            _logger.info("debug logging enabled pid=%s", os.getpid())


def enabled() -> bool:
    return _enabled


def log(message: str, *args: object, level: int = logging.DEBUG) -> None:
    if not _enabled:
        return
    try:
        if args:
            args = tuple(redact_text(a) for a in args)
        _logger.log(level, redact_text(message), *args)
    except Exception:
        pass


def event(name: str, **fields: object) -> None:
    if not _enabled:
        return
    safe = {k: ("<redacted>" if _SENSITIVE_WORD.search(k) else redact_text(v)) for k, v in fields.items()}
    log("event=%s %s", name, json.dumps(safe, sort_keys=True, ensure_ascii=False))


def exception(where: str, exc: BaseException) -> None:
    if _enabled:
        _logger.exception("%s: %s", redact_text(where), redact_text(exc))


def clear() -> None:
    with _lock:
        for h in [h for h in _logger.handlers if isinstance(h, _PrivateRotatingFileHandler)]:
            h.flush()
            h.close()
            _logger.removeHandler(h)
        for p in [LOG_FILE, *(LOG_DIR / f"debug.log.{i}" for i in range(1, 6))]:
            try:
                p.unlink()
            except OSError:
                pass
        if _enabled:
            configure(True)


def export_bundle(destination: str | Path | None = None) -> Path:
    """Create a support ZIP containing redacted PC Command Center logs and small metadata."""
    private_dir(LOG_DIR)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if destination is None:
        out_dir = HOME / "Downloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        destination = out_dir / f"pc-command-center-support-{stamp}.zip"
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Pre-create privately so there is no 0644 window while ZipFile is writing.
    if not dest.exists():
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    else:
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
    try:
        from .. import __version__
    except Exception:  # pragma: no cover - support export must not fail on metadata
        __version__ = "unknown"
    metadata = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "pc_command_center": __version__,
        "python": os.sys.version.split()[0],
        "platform": os.uname().sysname + " " + os.uname().release,
        "debug_enabled": _enabled,
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(metadata, indent=2))
        for p in sorted(LOG_DIR.glob("*.log*")):
            try:
                data = redact_text(p.read_text(errors="replace"))
                z.writestr(f"logs/{p.name}", data)
            except OSError:
                pass
        err = HOME / ".local/state/pc/gui-errors.log"
        if err.exists():
            try:
                z.writestr("logs/gui-errors.log", redact_text(err.read_text(errors="replace")))
            except OSError:
                pass
        activity = HOME / ".local/state/pc/activity.jsonl"
        if activity.exists():
            try:
                z.writestr("logs/activity.jsonl", redact_text(activity.read_text(errors="replace")))
            except OSError:
                pass
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    log("exported support bundle %s", dest)
    return dest
