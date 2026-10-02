#!/usr/bin/env python3
"""Print a pre-filled "new GitHub issue" link for an ubuntu-setup error.

    report_issue.py TITLE ERROR [LOG_FILE]

The issue holds the error, the end of this run's log and the system. Home folder, user and
computer names, IP/MAC addresses, e-mail addresses and secret-looking values are removed; the
person sees (and can edit) everything in the browser before submitting. Nothing is sent from here.
"""

import getpass
import platform
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlencode

REPO = "infinite4evr/vibes"
MAX_URL = 7600  # GitHub refuses links much over 8 KB


def scrub(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)  # terminal colours
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    for name in {getpass.getuser(), socket.gethostname()}:
        if name and len(name) >= 3:
            text = re.sub(rf"\b{re.escape(name)}\b", "[name]", text)
    text = re.sub(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "[mac]", text, flags=re.I)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[ip]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    text = re.sub(r"(?i)\b(token|password|passwd|secret|api[_-]?key|authorization)\b(\s*[:=]\s*)\S+", r"\1\2[secret]", text)
    return text


def system() -> list[str]:
    info = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            k, _, v = line.partition("=")
            info[k] = v.strip('"')
    except OSError:
        pass
    import os
    return ["| | |", "|---|---|",
            f"| OS | {info.get('PRETTY_NAME', '?')} |",
            f"| Kernel | {platform.release()} |",
            f"| Desktop | {os.environ.get('XDG_CURRENT_DESKTOP', '?')} ({os.environ.get('XDG_SESSION_TYPE', '?')}) |",
            f"| Python | {platform.python_version()} |"]


def body(error: str, log: list[str]) -> str:
    out = ["**Where:** ubuntu-setup", "", "### Error", "", "```text", error, "```", ""]
    if log:
        out += ["### Log (end)", "", "```text", *log, "```", ""]
    out += ["### System", "", *system(), "",
            "<sub>Created from ubuntu-setup's error prompt. Home folder, user/computer names, IP/MAC addresses "
            "and secrets were removed before this text was shown to you.</sub>"]
    return "\n".join(out)


def link(title: str, error: str, log_file: str = "") -> str:
    log: list[str] = []
    if log_file:
        try:
            log = [line for line in Path(log_file).read_text(errors="replace").splitlines() if line.strip()][-40:]
        except OSError:
            pass
    title, error, log = scrub(f"[ubuntu-setup] {title}")[:110], scrub(error), [scrub(x) for x in log]
    while True:
        url = f"https://github.com/{REPO}/issues/new?" + urlencode({"title": title, "labels": "bug", "body": body(error, log)})
        if len(url) <= MAX_URL:
            return url
        if len(log) > 3:
            log = log[len(log) // 4 or 1:]
        elif len(error) > 300:
            error = "…" + error[-len(error) * 2 // 3:]
        else:
            return url[:MAX_URL]


if __name__ == "__main__":
    a = sys.argv[1:] + ["", "", ""]
    print(link(a[0] or "Error", a[1] or a[0], a[2]))
