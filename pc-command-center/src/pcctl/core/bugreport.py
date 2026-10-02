"""Turn an error into a privacy-redacted GitHub issue (pre-filled link) plus a full local log.

Shared by the desktop app, the terminal app and the CLI. Nothing is sent anywhere
by this module: it only builds text and a github.com/…/issues/new URL that the user
opens (and reviews) in their own browser.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import socket
import time
import traceback
from pathlib import Path
from urllib.parse import urlencode

from . import debug

REPO = "infinite4evr/vibes"
NEW_ISSUE = f"https://github.com/{REPO}/issues/new"
ERRORS_LOG = Path.home() / ".local/state/pc/gui-errors.log"
# GitHub rejects very long URLs (HTTP 414 around 8 KB); stay well under after percent-encoding.
MAX_URL = 7600


# Messages that say something failed. The apps show these in their error dialog (with "Create GitHub
# issue") instead of a passing notification: every problem, however small, can be reported.
_ERROR_TEXT = re.compile(r"^\s*(error\b|couldn['’]t\b|could not\b|can['’]t\b|cannot\b|failed\b|unable to\b)"
                         r"|\b(failed|not installed|permission denied|refused|timed out)\b", re.I)


def is_error_text(text: object) -> bool:
    return bool(_ERROR_TEXT.search(str(text or "")))


def scrub(text: object) -> str:
    """Secrets, home folder, user and machine names, MAC/IP addresses: nothing that identifies the person."""
    from .report import redact
    s = debug.redact_text(text)
    home = str(Path.home())
    if len(home) > 1:
        s = s.replace(home, "~")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no passwd entry (containers)
        user = ""
    return redact(s, host=socket.gethostname(), user=user)


def environment() -> dict[str, str]:
    from .. import __version__
    env = {"PC Command Center": __version__, "Python": platform.python_version()}
    try:
        info = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
        env["OS"] = info.get("PRETTY_NAME", "").strip('"')
    except OSError:
        pass
    env["Kernel"] = platform.release()
    env["Desktop"] = f"{os.environ.get('XDG_CURRENT_DESKTOP', '?')} ({os.environ.get('XDG_SESSION_TYPE', '?')})"
    import sys
    if "gi.repository.Gtk" not in sys.modules:  # the CLI / terminal app: don't load GTK just to report its version
        return env
    try:
        from gi.repository import Adw, Gtk
        env["GTK"] = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        env["libadwaita"] = f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
    except Exception:  # noqa: BLE001 - CLI / terminal app without GTK
        pass
    return env


def _tail(path: Path, lines: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 256 * 1024))
            data = f.read().decode(errors="replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-lines:])


def _recent_entries(text: str, max_age: float) -> str:
    """Keep only "== YYYY-mm-dd HH:MM:SS ==" blocks newer than max_age seconds (old, unrelated crashes are noise)."""
    keep, current, cutoff = [], None, time.time() - max_age
    for line in text.splitlines():
        m = re.fullmatch(r"== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ==", line.strip())
        if m:
            try:
                current = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) >= cutoff
            except ValueError:
                current = False
        if current:
            keep.append(line)
    return "\n".join(keep)


def recent_logs(lines: int = 60, max_age: float = 86400) -> str:
    """The newest lines of the error log (last day only) and, when enabled, the debug log; redacted."""
    parts = []
    for name, path in (("gui-errors.log", ERRORS_LOG), ("debug.log", debug.LOG_FILE)):
        text = _tail(path, 2000 if path == ERRORS_LOG else lines)
        if path == ERRORS_LOG:
            text = "\n".join(_recent_entries(text, max_age).splitlines()[-lines:])
        if text.strip():
            parts.append(f"--- {name} (last {lines} lines) ---\n{text}")
    return scrub("\n\n".join(parts))


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def summary(error: str) -> str:
    """One line for the issue title: the last 'SomeError: message' line, or the first line."""
    lines = [ln.strip() for ln in str(error).strip().splitlines() if ln.strip()]
    if not lines:
        return "Unknown error"
    pick = next((ln for ln in reversed(lines) if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b", ln)), lines[-1])
    return pick[:110]


class Report:
    def __init__(self, error: str, where: str = "", context: str = "", logs: str | None = None):
        self.where = where or "PC Command Center"
        self.error = scrub(error).strip() or "(no details)"
        self.context = scrub(context).strip()
        self.logs = recent_logs() if logs is None else scrub(logs)
        self.env = environment()
        self.when = time.strftime("%Y-%m-%d %H:%M:%S %z")
        self.title = f"[{self.where}] {summary(self.error)}"

    def body(self, error: str | None = None, logs: str | None = None) -> str:
        env = "\n".join(f"| {k} | {v} |" for k, v in self.env.items())
        out = [f"**Where:** {self.where}  \n**When:** {self.when}", ""]
        if self.context:
            out += ["**What was happening:**", "", self.context, ""]
        out += ["### Error", "", "```text", self.error if error is None else error, "```", ""]
        lg = self.logs if logs is None else logs
        if lg.strip():
            out += ["<details><summary>Recent app log</summary>", "", "```text", lg, "```", "", "</details>", ""]
        out += ["### Environment", "", "| | |", "|---|---|", env, "",
                "<sub>Created from PC Command Center's error dialog. Home folder, user/computer names, IP/MAC addresses "
                "and secrets were removed before this text was shown to you.</sub>"]
        return "\n".join(out)

    def full_text(self) -> str:
        """Everything (untruncated), for Copy / Save."""
        return f"{self.title}\n\n{self.body()}"

    def url(self, max_len: int = MAX_URL) -> str:
        """Pre-filled new-issue link, shrinking the log and then the error (keeping their ends) to fit a URL."""
        def make(err: str, logs: str) -> str:
            return NEW_ISSUE + "?" + urlencode({"title": self.title, "labels": "bug", "body": self.body(err, logs)})
        err, logs = self.error, self.logs
        u = make(err, logs)
        while len(u) > max_len and logs:
            keep = len(logs) // 2
            logs = ("…(older lines trimmed: use “Copy details” for the full log)\n" + logs[-keep:]) if keep > 200 else ""
            u = make(err, logs)
        while len(u) > max_len and len(err) > 400:
            err = "…(trimmed)\n" + err[-(len(err) * 2 // 3):]
            u = make(err, logs)
        return u

    def save(self, folder: Path | None = None) -> Path:
        """Write the full redacted report next to the user's Downloads (private file)."""
        from .state import atomic_write_text
        folder = folder or (Path.home() / "Downloads")
        path = folder / f"pc-command-center-error-{time.strftime('%Y%m%d-%H%M%S')}.md"
        atomic_write_text(path, self.full_text() + "\n", mode=0o600, private_parent=False)
        return path


def from_exception(exc: BaseException, where: str = "", context: str = "") -> Report:
    return Report(format_exception(exc), where, context)
