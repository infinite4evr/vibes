"""System report: one self-contained HTML (or plain-text) file with specs, health, disks, updates and recent errors.

Keep it for yourself, or share the redacted version when asking for help (host name, user name, IP and MAC addresses and
serial numbers are masked). Used by the Maintenance page and `pc report`.
"""

from __future__ import annotations

import html
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

from .. import __version__
from .fmt import duration, human
from .run import HOME, has
from .state import atomic_write_text

LEVEL_MARK = {"ok": "✓", "info": "·", "warn": "!", "bad": "✗"}


# ---------------------------------------------------------------- collecting

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - a report section failing must never break the whole report
        return default


def collect(quick: bool = False) -> dict:
    """Gather everything (in parallel where slow). quick=True skips the update check and the error log."""
    from . import gpu, health, logs, packages, services, system

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_checks = ex.submit(_safe, lambda: health.run_all(), [])
        f_updates = ex.submit(_safe, packages.pending_updates, []) if not quick else None
        f_errors = ex.submit(_safe, lambda: logs.grouped(logs.entries(since="24 hours ago", max_priority=3, limit=1500))[:15], []) if not quick else None
        f_failed = ex.submit(_safe, services.failed, [])
        f_hw = ex.submit(_safe, system.hardware, {})
        f_gpu = ex.submit(_safe, gpu.gpus, [])
        f_snaps = ex.submit(_safe, lambda: len(packages.snap_apps()), None)
        f_flat = ex.submit(_safe, lambda: len(packages.flatpak_apps()), None)
        checks = f_checks.result()
        data = {
            "made": time.time(),
            "identity": _safe(system.identity, {}),
            "hardware": f_hw.result(),
            "gpus": f_gpu.result(),
            "uptime": _safe(system.uptime_seconds, 0),
            "checks": checks,
            "score": _safe(lambda: health.score(checks), None),
            "mounts": _safe(system.mounts, []),
            "memory": psutil.virtual_memory(),
            "swap": psutil.swap_memory(),
            "battery": _safe(system.battery),
            "temp": _safe(system.cpu_temp),
            "updates": f_updates.result() if f_updates else None,
            "errors": f_errors.result() if f_errors else None,
            "failed": f_failed.result(),
            "reboot": _safe(system.reboot_required),
            "snaps": f_snaps.result(),
            "flatpaks": f_flat.result(),
            "top": _top_processes(),
            "net": _net(),
            "quick": quick,
        }
    return data


def _top_processes(n: int = 8) -> list[dict]:
    procs = []
    for p in psutil.process_iter(["name", "memory_info", "username"]):
        try:
            procs.append({"name": p.info["name"] or "?", "mem": p.info["memory_info"].rss if p.info["memory_info"] else 0})
        except (psutil.Error, AttributeError):
            continue
    groups: dict[str, int] = {}
    for p in procs:
        groups[p["name"]] = groups.get(p["name"], 0) + p["mem"]
    return [{"name": k, "mem": v} for k, v in sorted(groups.items(), key=lambda x: -x[1])[:n]]


def _net() -> list[dict]:
    res = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if name == "lo" or name.startswith(("veth", "br-", "docker", "virbr")):
            continue
        st = stats.get(name)
        ips = [a.address for a in addrs if a.family.name == "AF_INET"]
        mac = next((a.address for a in addrs if a.family.name == "AF_PACKET"), "")
        res.append({"name": name, "up": bool(st and st.isup), "speed": st.speed if st else 0, "ips": ips, "mac": mac})
    return res


# ---------------------------------------------------------------- redaction

_MAC = re.compile(r"\b([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")


def redact(text: str, host: str = "", user: str = "") -> str:
    """Mask things that identify the person or their network. Keeps private/local ranges readable (192.168.x.x)."""
    if host and len(host) > 1:
        text = re.sub(re.escape(host), "this-pc", text)
    if user and len(user) > 1:
        text = text.replace(f"/home/{user}", "/home/user")
        text = re.sub(rf"\b{re.escape(user)}\b", "user", text)
    text = _MAC.sub("xx:xx:xx:xx:xx:xx", text)

    def ip(m: re.Match) -> str:
        a, b = int(m.group(1)), int(m.group(2))
        if a == 127 or (a, b) == (0, 0):
            return m.group(0)
        return f"{a}.{b}.x.x" if a in (10, 192, 172) else "x.x.x.x"
    text = _IPV4.sub(ip, text)
    return _IPV6.sub("xxxx::xxxx", text)


# ---------------------------------------------------------------- rendering

def _rows(data: dict) -> dict[str, list[tuple[str, str]]]:
    """The facts, as (label, value) pairs per section, shared by the HTML and the text versions."""
    i, hw = data.get("identity") or {}, data.get("hardware") or {}
    mem, sw = data["memory"], data["swap"]
    sections: dict[str, list[tuple[str, str]]] = {}
    sections["Computer"] = [
        ("Model", i.get("model", "")), ("Processor", f"{hw.get('cpu', '')} · {hw.get('cores', 0)} cores / {hw.get('threads', 0)} threads"),
        ("Memory", human(hw.get("ram") or mem.total)),
        ("Graphics", "; ".join(g["name"] + (f" ({g['driver']})" if g.get("driver") else "") for g in data.get("gpus") or []) or
         "; ".join(hw.get("gpus") or []) or "unknown"),
        ("Motherboard", hw.get("board", "")), ("BIOS", hw.get("bios", "")),
        ("System", f"{i.get('os', '')} · kernel {i.get('kernel', '')} · {hw.get('arch', '')}"),
        ("Desktop", f"{i.get('desktop', '')} ({i.get('session', '')})"), ("Computer name", i.get("host", "")),
        ("Up for", duration(data.get("uptime") or 0)),
    ]
    if data.get("temp"):
        sections["Computer"].append(("CPU temperature", f"{data['temp']:.0f} °C"))
    sections["Memory"] = [("In use", f"{human(mem.total - mem.available)} of {human(mem.total)} ({mem.percent:.0f}%)"),
                          ("Swap", f"{human(sw.used)} of {human(sw.total)}" if sw.total else "none")]
    b = data.get("battery")
    if b:
        sections["Battery"] = [("Charge", f"{b.get('percent', 0):.0f}%{' (plugged in)' if b.get('plugged') else ''}")]
        if b.get("health"):
            sections["Battery"].append(("Health", f"{b['health']:.0f}% of its original capacity"))
        if b.get("cycles"):
            sections["Battery"].append(("Charge cycles", str(b["cycles"])))
    sections["Disks"] = [(m.mountpoint, f"{human(m.used)} of {human(m.total)} used ({m.pct:.0f}%) · {m.fstype}") for m in data.get("mounts") or []]
    ups = data.get("updates")
    if ups is not None:
        kinds: dict[str, int] = {}
        for u in ups:
            kinds[u.source] = kinds.get(u.source, 0) + 1
        sec = sum(1 for u in ups if getattr(u, "security", False))
        sections["Updates"] = [("Waiting", ", ".join(f"{n} {k}" for k, n in kinds.items()) or "none, all up to date")]
        if sec:
            sections["Updates"].append(("Security fixes", str(sec)))
    if data.get("reboot"):
        sections.setdefault("Updates", []).append(("Restart needed for", ", ".join(data["reboot"][:6]) or "updates"))
    apps = []
    if data.get("snaps") is not None:
        apps.append(f"{data['snaps']} snaps")
    if data.get("flatpaks") is not None:
        apps.append(f"{data['flatpaks']} flatpaks")
    if apps:
        sections["Apps"] = [("Installed", ", ".join(apps))]
    sections["Network"] = [(n["name"], _net_text(n)) for n in data.get("net") or []]
    sections["Biggest memory users"] = [(p["name"], human(p["mem"])) for p in data.get("top") or []]
    return {k: [(a, b) for a, b in rows if b and b.strip(" ()·")] for k, rows in sections.items()}


def _net_text(n: dict) -> str:
    bits = ["up" if n["up"] else "down"]
    if n["speed"]:
        bits.append(f"{n['speed']} Mb/s")
    if n["ips"]:
        bits.append(", ".join(n["ips"]))
    if n["mac"]:
        bits.append(f"MAC {n['mac']}")
    return " · ".join(bits)


def text(data: dict | None = None, redacted: bool = True, quick: bool = False) -> str:
    """Plain text, good for pasting into a chat or forum post."""
    data = data or collect(quick)
    i = data.get("identity") or {}
    lines = [f"PC report · {time.strftime('%Y-%m-%d %H:%M', time.localtime(data['made']))} · PC Command Center {__version__}", ""]
    if data.get("score") is not None:
        lines.append(f"Health score: {data['score']}/100")
    for c in data.get("checks") or []:
        if c.level != "ok":
            lines.append(f"  {LEVEL_MARK[c.level]} {c.title}: {c.detail}")
    for title, rows in _rows(data).items():
        if not rows:
            continue
        lines += ["", title]
        w = max(len(k) for k, _ in rows)
        lines += [f"  {k.ljust(w)}  {v}" for k, v in rows]
    if data.get("failed"):
        lines += ["", "Failing services"] + [f"  ✗ {s.unit} - {s.description}" for s in data["failed"]]
    if data.get("errors"):
        lines += ["", "Recent errors (last 24 h)"] + [f"  {g['count']}× {g['source']}: {g['message'][:160]}" for g in data["errors"]]
    body = "\n".join(lines) + "\n"
    return redact(body, i.get("host", ""), i.get("user", "")) if redacted else body


CSS = """
:root { --bg:#eff1f5; --card:#ffffff; --text:#4c4f69; --sub:#6c6f85; --line:#dce0e8; --accent:#8839ef; --ok:#40a02b; --warn:#df8e1d;
  --bad:#d20f39; --info:#1e66f5; --bar:#e6e9ef; }
@media (prefers-color-scheme: dark) { :root { --bg:#1e1e2e; --card:#27273a; --text:#cdd6f4; --sub:#a6adc8; --line:#313244;
  --accent:#cba6f7; --ok:#a6e3a1; --warn:#f9e2af; --bad:#f38ba8; --info:#89b4fa; --bar:#313244; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, "Inter", "Ubuntu", sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 28px 16px 60px; }
h1 { font-size: 1.7rem; margin: 0 0 4px; } h2 { font-size: 1.1rem; margin: 0 0 10px; }
.sub { color: var(--sub); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }
.score { display:flex; align-items:center; gap:18px; }
.ring { width:86px; height:86px; border-radius:50%; display:grid; place-items:center; font-size:1.6rem; font-weight:800;
  background: conic-gradient(var(--c) calc(var(--p) * 1%), var(--bar) 0); }
.ring span { background: var(--card); width:66px; height:66px; border-radius:50%; display:grid; place-items:center; }
table { width:100%; border-collapse: collapse; } td { padding: 6px 0; border-top: 1px solid var(--line); vertical-align: top; }
tr:first-child td { border-top: 0; } td.k { color: var(--sub); width: 34%; padding-right: 12px; }
.check { display:flex; gap:10px; padding:7px 0; border-top:1px solid var(--line); } .check:first-child { border-top:0; }
.mark { font-weight:800; width:1.2em; text-align:center; } .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.info { color:var(--info); }
.bar { height:8px; background:var(--bar); border-radius:4px; overflow:hidden; margin-top:4px; } .bar i { display:block; height:100%; }
code { font: 13px/1.4 ui-monospace, "JetBrains Mono", monospace; }
footer { color: var(--sub); font-size: 0.85rem; margin-top: 30px; }
@media print { body { background: #fff; } .card { break-inside: avoid; } }
"""


def build_html(data: dict | None = None, redacted: bool = False, quick: bool = False) -> str:
    data = data or collect(quick)
    i = data.get("identity") or {}
    e = html.escape
    when = time.strftime("%A %d %B %Y, %H:%M", time.localtime(data["made"]))
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>PC report · {e(i.get('host', ''))}</title><style>{CSS}</style></head><body><main>",
             f"<h1>PC report</h1><div class='sub'>{e(i.get('model', ''))} · {e(i.get('os', ''))} · {e(when)}</div>"]
    score = data.get("score")
    if score is not None:
        col = "var(--ok)" if score >= 85 else "var(--warn)" if score >= 60 else "var(--bad)"
        verdict = "Healthy" if score >= 85 else "A few things need attention" if score >= 60 else "Needs attention"
        checks = "".join(f"<div class='check'><span class='mark {c.level}'>{LEVEL_MARK[c.level]}</span><div><b>{e(c.title)}</b>"
                         f"<div class='sub'>{e(c.detail)}</div></div></div>" for c in data.get("checks") or [])
        parts.append(f"<section class='card'><div class='score'><div class='ring' style='--p:{score};--c:{col}'><span>{score}</span></div>"
                     f"<div><h2>{verdict}</h2><div class='sub'>Health score out of 100</div></div></div><div style='margin-top:12px'>{checks}</div></section>")
    for title, rows in _rows(data).items():
        if not rows:
            continue
        if title == "Disks":
            body = "".join(f"<tr><td class='k'><code>{e(m.mountpoint)}</code></td><td>{e(human(m.free))} free of {e(human(m.total))} · {e(m.fstype)}"
                           f"<div class='bar'><i style='width:{m.pct:.0f}%;background:{'var(--bad)' if m.pct >= 90 else 'var(--warn)' if m.pct >= 75 else 'var(--accent)'}'></i>"
                           f"</div></td></tr>" for m in data.get("mounts") or [])
        else:
            body = "".join(f"<tr><td class='k'>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
        parts.append(f"<section class='card'><h2>{e(title)}</h2><table>{body}</table></section>")
    if data.get("failed"):
        items = "".join(f"<div class='check'><span class='mark bad'>✗</span><div><code>{e(s.unit)}</code><div class='sub'>{e(s.description)}</div></div></div>"
                        for s in data["failed"])
        parts.append(f"<section class='card'><h2>Failing services</h2>{items}</section>")
    if data.get("errors"):
        items = "".join(f"<div class='check'><span class='mark warn'>{g['count']}×</span><div><b>{e(g['source'])}</b>"
                        f"<div class='sub'><code>{e(g['message'][:300])}</code></div></div></div>" for g in data["errors"])
        parts.append(f"<section class='card'><h2>Errors in the last 24 hours</h2>{items}</section>")
    elif data.get("errors") is not None:
        parts.append("<section class='card'><h2>Errors in the last 24 hours</h2><div class='sub'>None worth mentioning.</div></section>")
    note = "Names, IP and MAC addresses are hidden in this copy." if redacted else "This copy includes names and addresses; share the redacted one."
    parts.append(f"<footer>Made by PC Command Center {e(__version__)}. {note}</footer></main></body></html>")
    doc = "\n".join(parts)
    return redact(doc, i.get("host", ""), i.get("user", "")) if redacted else doc


def default_path(redacted: bool = False) -> Path:
    folder = HOME / "Documents"
    if not folder.is_dir():
        folder = HOME
    host = "shared" if redacted else (os.uname().nodename or "pc")
    return folder / f"PC-report-{host}-{time.strftime('%Y-%m-%d')}.html"


def save(path: str | Path | None = None, redacted: bool = False, quick: bool = False, data: dict | None = None) -> Path:
    p = Path(path).expanduser() if path else default_path(redacted)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, build_html(data, redacted=redacted, quick=quick), mode=0o600, private_parent=False)
    return p


def open_cmd(path: Path) -> list[str]:
    return ["xdg-open", str(path)] if has("xdg-open") else ["gio", "open", str(path)]


def summary_line(data: dict) -> str:
    """One line for toasts/notifications."""
    s = data.get("score")
    bad = sum(1 for c in data.get("checks") or [] if c.level in ("bad", "warn"))
    return (f"Health {s}/100" if s is not None else "Report ready") + (f" · {bad} thing(s) to look at" if bad else "")
