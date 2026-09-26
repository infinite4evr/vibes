"""Virus scan with ClamAV (like CleanMyMac's Protection scan).

Linux rarely gets viruses, but a scan is useful for files you download and then pass on to Windows or Mac users
(email attachments, cracked installers, USB sticks). Scans run through the normal step runner so output streams live.
"""

from __future__ import annotations

import glob
import os
import re
import time
from pathlib import Path

from . import run as _run
from .state import append_private, atomic_write_text
from .run import Step, has, out, py_step

DB_DIR = "/var/lib/clamav"
LOG_NAME = ".cache/pc/clamscan.log"
START = "# pc scan of "
END = "# pc scan finished "


def log_path() -> Path:
    return _run.HOME / LOG_NAME


def downloads() -> str:
    d = out(["xdg-user-dir", "DOWNLOAD"], timeout=3) if has("xdg-user-dir") else ""
    return d if d and d != str(_run.HOME) and os.path.isdir(d) else str(_run.HOME / "Downloads")


def installed() -> bool:
    return has("clamscan")


def parse_version(text: str) -> dict:
    """'ClamAV 1.4.3/27771/Wed Sep 24 08:25:03 2025' -> {engine, db, date (unix time or None)}."""
    m = re.match(r"\s*ClamAV\s+([\w.\-~+]+)(?:/(\d+)/(.+))?", text or "")
    if not m:
        return {"engine": "", "db": 0, "date": None}
    date = None
    if m.group(3):
        try:
            date = time.mktime(time.strptime(" ".join(m.group(3).split()), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            date = None
    return {"engine": m.group(1), "db": int(m.group(2) or 0), "date": date}


def db_files(db_dir: str = DB_DIR) -> list[str]:
    return sorted(glob.glob(os.path.join(db_dir, "*.cvd")) + glob.glob(os.path.join(db_dir, "*.cld")))


def status() -> dict:
    st = {"installed": installed(), "engine": "", "db": 0, "date": None, "age_days": None, "db_files": db_files(),
          "updater": "", "downloads": downloads()}
    if st["installed"]:
        st.update(parse_version(out(["clamscan", "--version"], timeout=15)))
        if st["date"] is None and st["db_files"]:
            st["date"] = max(os.path.getmtime(f) for f in st["db_files"])
        if st["date"]:
            st["age_days"] = max(0.0, (time.time() - st["date"]) / 86400)
        st["updater"] = out(["systemctl", "is-active", "clamav-freshclam.service"], timeout=5)
    st["last"] = last_scan()
    return st


def install_steps() -> list[Step]:
    return [Step("Install ClamAV (virus scanner) and its updater", ["apt-get", "install", "-y", "clamav", "clamav-freshclam"], root=True,
                 env={"DEBIAN_FRONTEND": "noninteractive"})]


def update_db_steps() -> list[Step]:
    return [Step("Pause the automatic updater", ["systemctl", "stop", "clamav-freshclam.service"], root=True, optional=True),
            Step("Download the latest virus list", ["freshclam"], root=True),
            Step("Turn the automatic updater back on", ["systemctl", "start", "clamav-freshclam.service"], root=True, optional=True)]


def scan_steps(folder: str) -> list[Step]:
    log = log_path()

    def start() -> str:
        atomic_write_text(log, f"{START}{folder} at {int(time.time())}\n", mode=0o600)
        return f"Scanning {folder}. Loading the virus list takes about a minute first; big folders take longer."

    def finish() -> str:
        found = parse_scan(_run.read(log))
        append_private(log, f"{END}{int(time.time())}\n", mode=0o600)
        return f"Done. {len(found)} infected file{'s' if len(found) != 1 else ''} found." if found else "Done. Nothing infected found."
    return [py_step("Get ready", start, f"start a new scan report in ~/{LOG_NAME}"),
            Step(f"Scan {folder}", ["clamscan", "-r", "-i", "--no-summary", f"--log={log}", folder], ok_codes=(0, 1)),
            py_step("Summarise", finish, "count what was found")]


def parse_scan(text: str) -> list[dict]:
    """clamscan's 'path: Virus.Name FOUND' lines -> [{path, virus}]."""
    res, seen = [], set()
    for line in text.splitlines():
        line = line.rstrip()
        if not line.endswith(" FOUND"):
            continue
        path, sep, virus = line[:-6].rpartition(": ")
        if sep and path not in seen:
            seen.add(path)
            res.append({"path": path, "virus": virus.strip()})
    return res


def last_scan(text: str | None = None) -> dict | None:
    """The last scan run from the app: {folder, started, finished (None if it didn't finish), infected}."""
    text = _run.read(log_path()) if text is None else text
    m = re.search(r"^" + re.escape(START) + r"(.+) at (\d+)$", text, re.M)
    if not m:
        return None
    f = re.search(r"^" + re.escape(END) + r"(\d+)$", text, re.M)
    found = parse_scan(text)
    return {"folder": m.group(1), "started": int(m.group(2)), "finished": int(f.group(1)) if f else None,
            "found": found, "infected": [x for x in found if os.path.exists(x["path"])]}


def trash_steps(paths: list[str]) -> list[Step]:
    return [Step(f"Move {len(paths)} infected file{'s' if len(paths) != 1 else ''} to the Trash", ["gio", "trash", "--", *paths])]
