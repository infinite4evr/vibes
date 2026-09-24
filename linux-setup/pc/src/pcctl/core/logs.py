"""System logs: errors grouped by where they came from, crash reports, per-boot history."""

from __future__ import annotations

import glob
import json
import os
import re
import time
from dataclasses import dataclass

from .run import out, read, sh

PRIORITY = {0: "emergency", 1: "alert", 2: "critical", 3: "error", 4: "warning", 5: "notice", 6: "info", 7: "debug"}

# Messages that are noisy on almost every Ubuntu install and never need action.
NOISE = [
    r"gkr-pam: unable to locate daemon control file",
    r"Failed to (load|read) .*hwdb",
    r"ACPI BIOS Error",
    r"ACPI Error",
    r"GLib-GObject.*: g_object",
    r"Gtk-(WARNING|CRITICAL)",
    r"JS ERROR: .*Extension",
    r"Unable to connect to the xdg-desktop-portal",
    r"tpm_crb .*: \[Firmware Bug\]",
]


@dataclass
class LogLine:
    time: float
    source: str
    unit: str
    priority: int
    message: str
    pid: str = ""


def _msg(v) -> str:
    if isinstance(v, list):  # journald stores non-UTF8 messages as byte arrays
        try:
            return bytes(v).decode(errors="replace")
        except (TypeError, ValueError):
            return str(v)
    return str(v or "")


def parse_journal_json(text: str) -> list[LogLine]:
    res = []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = int(d.get("__REALTIME_TIMESTAMP", "0") or 0) / 1_000_000
        src = d.get("SYSLOG_IDENTIFIER") or d.get("_COMM") or ("kernel" if d.get("_TRANSPORT") == "kernel" else "?")
        res.append(LogLine(ts, src, d.get("_SYSTEMD_UNIT", "") or d.get("_SYSTEMD_USER_UNIT", ""), int(d.get("PRIORITY", 6) or 6),
                           _msg(d.get("MESSAGE")).strip(), str(d.get("_PID", ""))))
    return res


def entries(since: str = "boot", max_priority: int = 3, unit: str = "", kernel: bool = False, limit: int = 2000, grep: str = "") -> list[LogLine]:
    args = ["journalctl", "--no-pager", "-o", "json", "-p", str(max_priority), "-n", str(limit)]
    if since == "boot":
        args.append("-b")
    elif since == "previous":
        args += ["-b", "-1"]
    elif since:
        args += ["--since", since]
    if unit:
        args += ["-u", unit]
    if kernel:
        args.append("-k")
    if grep:
        args += ["-g", grep, "--case-sensitive=false"]
    r = sh(args, timeout=30)
    lines = parse_journal_json(r.out)
    if not lines:
        r2 = sh(args, root=True, timeout=30)
        if r2.ok:
            lines = parse_journal_json(r2.out)
    return lines


def is_noise(msg: str) -> bool:
    return any(re.search(p, msg) for p in NOISE)


def grouped(lines: list[LogLine], hide_noise: bool = True) -> list[dict]:
    groups: dict[str, dict] = {}
    for ln in lines:
        if hide_noise and is_noise(ln.message):
            continue
        g = groups.setdefault(ln.source, {"source": ln.source, "count": 0, "last": 0.0, "message": "", "worst": 7, "unit": ln.unit})
        g["count"] += 1
        g["worst"] = min(g["worst"], ln.priority)
        if ln.time >= g["last"]:
            g["last"], g["message"] = ln.time, ln.message
    return sorted(groups.values(), key=lambda g: (g["worst"], -g["count"]))


def crashes() -> list[dict]:
    res = []
    for f in glob.glob("/var/crash/*.crash"):
        text = read(f)[:4000]
        exe = re.search(r"^ExecutablePath: (.*)$", text, re.M)
        fallback = os.path.basename(f).split(".")[0].split("_")[-1]
        res.append({"file": f, "app": os.path.basename(exe.group(1)) if exe else fallback,
                    "time": os.path.getmtime(f), "size": os.path.getsize(f)})
    if not res and out(["which", "coredumpctl"]):
        for line in out(["coredumpctl", "list", "--no-pager", "--no-legend", "-q"], timeout=15).splitlines()[-20:]:
            parts = line.split()
            if len(parts) >= 10:
                res.append({"file": "", "app": parts[-1], "time": 0, "size": 0, "raw": line})
    res.sort(key=lambda c: -c["time"])
    return res


def boots() -> list[dict]:
    res = []
    for line in out(["journalctl", "--list-boots", "--no-pager"], timeout=15).splitlines():
        m = re.match(r"\s*(-?\d+)\s+(\S+)\s+\w+\s+(\S+ \S+) \S+\s*[—-]\s*\w+\s+(\S+ \S+)", line)
        if m:
            res.append({"index": int(m.group(1)), "id": m.group(2), "start": m.group(3), "end": m.group(4)})
    return res[-10:]


def fmt_time(ts: float) -> str:
    if not ts:
        return ""
    t = time.localtime(ts)
    today = time.localtime()
    return time.strftime("%H:%M" if t[:3] == today[:3] else "%d %b %H:%M", t)
