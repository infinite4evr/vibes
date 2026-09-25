"""Power extras: battery history (UPower), keep awake, shutdown/restart/sleep timers, CPU speed and throttling.

Everything here is plain Python (no GTK) so the terminal app and CLI can use it too.
"""

from __future__ import annotations

import glob
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from .run import HOME, Step, has, out, py_step, read, sh

STATE_DIR = HOME / ".local/state/pc"

# ---------------------------------------------------------------- battery history (J1)

UPOWER_DIR = "/var/lib/upower"


def parse_upower_history(text: str) -> list[tuple[float, float, str]]:
    """Lines of `<unix time>\\t<value>\\t<state>` -> [(time, value, state)], oldest first. Bad lines are skipped."""
    res = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            ts, val = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if ts <= 0:
            continue
        res.append((ts, val, parts[2] if len(parts) > 2 else "unknown"))
    res.sort(key=lambda p: p[0])
    return res


def history_files(kind: str = "charge", folder: str | None = None) -> list[str]:
    """UPower's history files for one kind (charge, rate, time-full, time-empty), newest first."""
    files = glob.glob(os.path.join(folder or UPOWER_DIR, f"history-{kind}-*.dat"))
    return sorted(files, key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)


def battery_history(kind: str = "charge", hours: float = 24, now: float | None = None, folder: str | None = None) -> list[tuple[float, float, str]]:
    """Charge % (kind=charge) or power draw in W (kind=rate) over the last `hours`, from the most recently used battery."""
    files = history_files(kind, folder)
    if not files:
        return []
    pts = parse_upower_history(read(files[0]))
    now = now if now is not None else time.time()
    start = now - hours * 3600
    inside = [p for p in pts if start <= p[0] <= now + 60]
    # keep the last point before the window so the line starts at the left edge
    before = [p for p in pts if p[0] < start]
    if before and inside:
        inside.insert(0, (start, before[-1][1], before[-1][2]))
    return inside


def downsample(points: list[tuple[float, float, str]], n: int = 400) -> list[tuple[float, float, str]]:
    """Keep at most ~n points (every k-th, always keeping the last)."""
    if len(points) <= n:
        return points
    k = len(points) / n
    res = [points[int(i * k)] for i in range(n)]
    if res[-1] is not points[-1]:
        res.append(points[-1])
    return res


def history_summary(points: list[tuple[float, float, str]]) -> dict:
    """A few plain facts about a charge history: lowest, highest, how much time on battery, charges started."""
    if not points:
        return {}
    vals = [v for _, v, _ in points]
    on_batt = 0.0
    charges = 0
    for (t0, _v0, s0), (t1, _v1, s1) in zip(points, points[1:]):
        gap = t1 - t0
        if s0 == "discharging" and gap < 3 * 3600:
            on_batt += gap
        if s1 == "charging" and s0 != "charging":
            charges += 1
    return {"low": min(vals), "high": max(vals), "on_battery": on_batt, "charges": charges, "first": points[0][0], "last": points[-1][0]}


# ---------------------------------------------------------------- keep awake (J2)

WHO = "PC Command Center"
WHY = "Keep awake"
APP_ID = "io.github.infinite4evr.PcCommandCenter"
AWAKE_FILE = STATE_DIR / "keep-awake.json"
AWAKE_LOG = STATE_DIR / "keep-awake.log"

AWAKE_CHOICES = [(30 * 60, "30 minutes"), (3600, "1 hour"), (2 * 3600, "2 hours"), (4 * 3600, "4 hours"), (0, "Until I stop it")]


def keep_awake_cmd(seconds: int | None, gnome: bool | None = None) -> list[str]:
    """The command that holds the PC awake. seconds=0/None means until stopped.

    systemd-inhibit blocks automatic sleep for the whole system (logind); on GNOME it's wrapped in gnome-session-inhibit
    so the screen doesn't blank and GNOME's own idle suspend is paused too."""
    sleep = ["sleep", str(int(seconds))] if seconds else ["sleep", "infinity"]
    inner = ["systemd-inhibit", "--what=idle:sleep", f"--who={WHO}", f"--why={WHY}", "--mode=block", *sleep]
    if gnome is None:
        gnome = has("gnome-session-inhibit") and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("XDG_RUNTIME_DIR"))
    if gnome:
        return ["gnome-session-inhibit", "--inhibit", "idle:suspend", "--reason", WHY, "--app-id", APP_ID, *inner]
    return inner


def _cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [p.decode(errors="replace") for p in raw.split(b"\0") if p]


def _is_ours(pid: int) -> bool:
    """True if pid is a keep-awake process we started (never kill anything else)."""
    args = _cmdline(pid)
    joined = " ".join(args)
    return bool(args) and ("systemd-inhibit" in joined or "gnome-session-inhibit" in joined) and f"--who={WHO}" in joined


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def keep_awake_status(now: float | None = None, state_file: Path | None = None) -> dict | None:
    """{pid, started, until (0 = until stopped), left (seconds or None)} while keep-awake is on, else None."""
    f = state_file or AWAKE_FILE
    st = _read_state(f)
    pid = int(st.get("pid") or 0)
    if not pid or not _is_ours(pid):
        if st:
            try:
                f.unlink()
            except OSError:
                pass
        return None
    now = now if now is not None else time.time()
    until = float(st.get("until") or 0)
    return {"pid": pid, "started": float(st.get("started") or 0), "until": until, "left": max(0.0, until - now) if until else None,
            "screen": bool(st.get("screen"))}


def start_keep_awake(seconds: int | None) -> dict:
    """Start holding the PC awake in a detached process (keeps working after the app closes). Returns the status."""
    if not has("systemd-inhibit"):
        raise RuntimeError("systemd-inhibit isn't available on this system")
    stop_keep_awake()
    cmd = keep_awake_cmd(seconds)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(AWAKE_LOG, "w") as log:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True, close_fds=True)
    now = time.time()
    _write_state(AWAKE_FILE, {"pid": p.pid, "started": now, "until": now + seconds if seconds else 0, "cmd": cmd,
                              "screen": cmd[0] == "gnome-session-inhibit"})
    time.sleep(0.4)
    if p.poll() is not None:  # it gave up straight away (no permission, no logind…)
        msg = read(AWAKE_LOG).strip().splitlines()
        try:
            AWAKE_FILE.unlink()
        except OSError:
            pass
        last = msg[-1] if msg else f"it stopped straight away (exit {p.returncode})"
        if "connect to bus" in last or "org.freedesktop.login1" in last:
            last = "the power manager (logind) isn't answering here"
        elif "denied" in last.lower():
            last = "Ubuntu didn't allow it (permission denied)"
        raise RuntimeError(last)
    return keep_awake_status() or {}


def stop_keep_awake() -> bool:
    """Stop our keep-awake process (and only ours). Returns True if something was stopped."""
    st = _read_state(AWAKE_FILE)
    pids = [int(st["pid"])] if st.get("pid") else []
    pids += [i["pid"] for i in inhibitors() if i["who"] == WHO and i["uid"] == os.getuid() and i["pid"] not in pids]
    stopped = False
    for pid in pids:
        if not _is_ours(pid):
            continue
        try:
            if os.getpgid(pid) == pid:  # we started it as its own group: stop the inhibitor and its sleep together
                os.killpg(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
            stopped = True
        except (ProcessLookupError, PermissionError):
            pass
    try:
        AWAKE_FILE.unlink()
    except OSError:
        pass
    return stopped


def parse_inhibitors_json(text: str) -> list[dict]:
    """busctl --json=short call … ListInhibitors -> [{what, who, why, mode, uid, pid}]."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    if not rows:
        return []
    items = rows[0] if rows and isinstance(rows[0], list) and rows[0] and isinstance(rows[0][0], list) else rows
    res = []
    for it in items:
        if isinstance(it, list) and len(it) >= 6:
            res.append({"what": str(it[0]), "who": str(it[1]), "why": str(it[2]), "mode": str(it[3]), "uid": int(it[4]), "pid": int(it[5])})
    return res


def parse_inhibitors_text(text: str) -> list[dict]:
    """`systemd-inhibit --list` table (with header) -> [{what, who, why, mode, uid, pid, comm}]."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = next((i for i, ln in enumerate(lines) if re.match(r"\s*WHO\s+UID\s+USER\s+PID", ln)), None)
    res = []
    if head is not None:
        h = lines[head]
        names = ["WHO", "UID", "USER", "PID", "COMM", "WHAT", "WHY", "MODE"]
        starts = [h.find(n) for n in names]
        if all(s >= 0 for s in starts):
            for ln in lines[head + 1:]:
                if re.match(r"\s*\d+ inhibitors? listed", ln):
                    break
                cells = [ln[s:(starts[i + 1] if i + 1 < len(starts) else None)].strip() for i, s in enumerate(starts)]
                if not cells[1].isdigit() or not cells[3].isdigit():
                    continue
                res.append({"who": cells[0], "uid": int(cells[1]), "user": cells[2], "pid": int(cells[3]), "comm": cells[4],
                            "what": cells[5], "why": cells[6], "mode": cells[7]})
            return res
    # no header (--no-legend): best effort
    for ln in lines:
        m = re.match(r"\s*(.+?)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+([a-z:-]+)\s+(.*?)\s+(block|delay|block-weak)\s*$", ln)
        if m:
            res.append({"who": m.group(1), "uid": int(m.group(2)), "user": m.group(3), "pid": int(m.group(4)), "comm": m.group(5),
                        "what": m.group(6), "why": m.group(7), "mode": m.group(8)})
    return res


def inhibitors() -> list[dict]:
    """Everything currently asking the PC not to sleep / shut down / blank (apps, GNOME, our keep-awake)."""
    if has("busctl"):
        text = out(["busctl", "--json=short", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                    "org.freedesktop.login1.Manager", "ListInhibitors"], timeout=5)
        if text:
            return parse_inhibitors_json(text)
    if has("systemd-inhibit"):
        return parse_inhibitors_text(out(["systemd-inhibit", "--list", "--no-pager"], timeout=5))
    return []


WHAT_WORDS = {"sleep": "sleep", "idle": "going idle", "shutdown": "shutdown", "handle-lid-switch": "lid close",
              "handle-power-key": "power button", "handle-suspend-key": "sleep key", "handle-hibernate-key": "hibernate key",
              "handle-reboot-key": "restart key"}


def explain_inhibitor(i: dict) -> str:
    whats = [WHAT_WORDS.get(w, w) for w in i.get("what", "").split(":") if w]
    verb = "Stops" if i.get("mode") == "block" else "Briefly delays"
    return f"{verb} {', '.join(whats)}" + (f": {i['why']}" if i.get("why") else "")


# ---------------------------------------------------------------- shutdown / restart / sleep timers (J3)

SCHEDULED_FILE = "/run/systemd/shutdown/scheduled"
SUSPEND_UNIT = "pc-suspend-timer"
SUSPEND_FILE = STATE_DIR / "suspend-timer.json"
TIMER_KINDS = {"poweroff": "Shut down", "reboot": "Restart", "suspend": "Sleep"}


def parse_scheduled(text: str) -> dict | None:
    """/run/systemd/shutdown/scheduled (USEC=, MODE=) -> {"mode": poweroff|reboot|…, "when": unix time}."""
    vals = dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln)
    try:
        usec = int(vals.get("USEC", "0"))
    except ValueError:
        return None
    if usec <= 0:
        return None
    mode = vals.get("MODE", "poweroff").replace("dry-", "")
    return {"mode": mode, "when": usec / 1_000_000}


def parse_scheduled_property(text: str) -> dict | None:
    """busctl get-property … ScheduledShutdown -> `(st) "poweroff" 1727280000000000`."""
    m = re.search(r'"([a-z-]*)"\s+(\d+)', text)
    if not m or not m.group(1) or int(m.group(2)) <= 0:
        return None
    return {"mode": m.group(1).replace("dry-", ""), "when": int(m.group(2)) / 1_000_000}


def scheduled_shutdown() -> dict | None:
    """A shutdown or restart that's been scheduled (by us, `shutdown +N` or anything else)."""
    text = read(SCHEDULED_FILE)
    if text:
        return parse_scheduled(text)
    if has("busctl"):
        return parse_scheduled_property(out(["busctl", "get-property", "org.freedesktop.login1", "/org/freedesktop/login1",
                                             "org.freedesktop.login1.Manager", "ScheduledShutdown"], timeout=5))
    return None


def suspend_timer(now: float | None = None) -> dict | None:
    """Our sleep timer, if it's still waiting: {"mode": "suspend", "when": unix time}."""
    st = _read_state(SUSPEND_FILE)
    if not st.get("when"):
        return None
    now = now if now is not None else time.time()
    if float(st["when"]) < now - 120:
        try:
            SUSPEND_FILE.unlink()
        except OSError:
            pass
        return None
    r = sh(["systemctl", "--user", "is-active", f"{SUSPEND_UNIT}.timer"], timeout=5)
    if r.out.strip() not in ("active", "activating"):
        return None
    return {"mode": "suspend", "when": float(st["when"])}


def pending_timers() -> list[dict]:
    res = []
    s = scheduled_shutdown()
    if s:
        res.append(s)
    t = suspend_timer()
    if t:
        res.append(t)
    return res


def timer_steps(kind: str, minutes: int) -> list[Step]:
    """Steps to shut down / restart / sleep after `minutes`.

    `shutdown +N` asks logind to schedule it; logind lets the person at the screen do that without a password (the same rule
    that lets you pick Power Off from the menu), so no admin rights are needed. Sleep uses a one-off timer in your account."""
    minutes = max(1, int(minutes))
    when = in_words(minutes)
    if kind == "poweroff":
        return [Step(f"Shut down {when}", ["shutdown", "-h", f"+{minutes}"])]
    if kind == "reboot":
        return [Step(f"Restart {when}", ["shutdown", "-r", f"+{minutes}"])]
    if kind == "suspend":
        target = time.time() + minutes * 60
        return [Step("Clear an earlier sleep timer", ["systemctl", "--user", "stop", f"{SUSPEND_UNIT}.timer"], optional=True, ok_codes=(0, 5)),
                Step(f"Sleep {when}", ["systemd-run", "--user", f"--unit={SUSPEND_UNIT}", f"--on-active={minutes}m",
                                       "--timer-property=AccuracySec=1s", "--description=Sleep timer (PC Command Center)", "systemctl", "suspend"]),
                py_step("Remember the timer", lambda: _write_state(SUSPEND_FILE, {"when": target}) or "saved",
                        f"save the time in {SUSPEND_FILE.relative_to(HOME) if str(SUSPEND_FILE).startswith(str(HOME)) else SUSPEND_FILE}")]
    raise ValueError(kind)


def in_words(minutes: int) -> str:
    """15 -> 'in 15 minutes', 60 -> 'in 1 hour', 90 -> 'in 1 h 30 min', 120 -> 'in 2 hours'."""
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"in {m} minute{'s' if m != 1 else ''}"
    if not m:
        return f"in {h} hour{'s' if h != 1 else ''}"
    return f"in {h} h {m:02d} min"


def cancel_timer_steps(kind: str) -> list[Step]:
    if kind == "suspend":
        def forget() -> str:
            try:
                SUSPEND_FILE.unlink()
            except OSError:
                pass
            return "forgotten"
        return [Step("Cancel the sleep timer", ["systemctl", "--user", "stop", f"{SUSPEND_UNIT}.timer"], ok_codes=(0, 5)),
                py_step("Forget the timer", forget, "remove the saved time")]
    return [Step("Cancel the scheduled shutdown/restart", ["shutdown", "-c"])]


# ---------------------------------------------------------------- CPU speed, governor, turbo, throttling (J4)

CPU_ROOT = "/sys/devices/system/cpu"

DRIVERS = {
    "intel_pstate": "Intel's own speed control (modern Intel CPUs). It picks speeds itself, very quickly.",
    "intel_cpufreq": "Intel speed control in 'passive' mode: Linux picks the speed, Intel's driver applies it.",
    "amd-pstate-epp": "AMD's modern speed control (Ryzen). The CPU picks speeds itself, guided by the energy preference.",
    "amd-pstate": "AMD's speed control with Linux choosing the speed (guided mode).",
    "acpi-cpufreq": "Older, generic speed control through the BIOS. Works everywhere, a little less efficient.",
    "cppc_cpufreq": "Standard firmware-guided speed control (common on ARM and some AMD PCs).",
}

GOVERNORS = {
    "powersave": "With intel_pstate / amd-pstate this is normal: the CPU still speeds up when busy. The energy preference decides how eagerly.",
    "performance": "Keeps the CPU at its highest speed setting. Fastest, but warmer and uses more power.",
    "schedutil": "Speed follows how busy the CPU is (the Linux default for most CPUs).",
    "ondemand": "Jumps to full speed when busy, drops when idle.",
    "conservative": "Speeds up gradually when busy. Saves power, feels a bit slower.",
    "userspace": "A program sets the speed by hand.",
}

EPP = {
    "performance": "Performance: speed first",
    "balance_performance": "Balanced, leaning to speed",
    "default": "Default (balanced)",
    "balance_power": "Balanced, leaning to battery life",
    "power": "Power saving: battery first",
}


def parse_cpuinfo_mhz(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"^cpu MHz\s*:\s*([\d.]+)", text, re.M)]


def _num(path: str) -> int | None:
    v = read(path).strip()
    return int(v) if v.lstrip("-").isdigit() else None


def cpu_speeds(root: str = CPU_ROOT, cpuinfo: str = "/proc/cpuinfo") -> dict:
    """Per-core speed (MHz), limits, governor, energy preference, driver, turbo and thermal throttle counts. All read-only."""
    cores = []
    dirs = sorted(glob.glob(os.path.join(root, "cpu[0-9]*")), key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)) or 0))
    for d in dirs:
        n = int(re.sub(r"\D", "", os.path.basename(d)))
        if read(os.path.join(d, "online")).strip() == "0":
            continue
        f = os.path.join(d, "cpufreq")
        if not os.path.isdir(f):
            continue
        cur = _num(os.path.join(f, "scaling_cur_freq")) or _num(os.path.join(f, "cpuinfo_cur_freq"))
        cores.append({
            "cpu": n,
            "mhz": cur / 1000 if cur else None,
            "min": (_num(os.path.join(f, "cpuinfo_min_freq")) or 0) / 1000 or None,
            "max": (_num(os.path.join(f, "cpuinfo_max_freq")) or 0) / 1000 or None,
            "limit_max": (_num(os.path.join(f, "scaling_max_freq")) or 0) / 1000 or None,
            "governor": read(os.path.join(f, "scaling_governor")).strip(),
            "epp": read(os.path.join(f, "energy_performance_preference")).strip(),
            "driver": read(os.path.join(f, "scaling_driver")).strip(),
            "throttle_core": _num(os.path.join(d, "thermal_throttle/core_throttle_count")),
            "throttle_pkg": _num(os.path.join(d, "thermal_throttle/package_throttle_count")),
        })
    source = "cpufreq"
    if not cores:  # virtual machines and some ARM boards: no cpufreq, only what /proc/cpuinfo reports
        source = "cpuinfo"
        cores = [{"cpu": i, "mhz": mhz, "min": None, "max": None, "limit_max": None, "governor": "", "epp": "", "driver": "",
                  "throttle_core": None, "throttle_pkg": None} for i, mhz in enumerate(parse_cpuinfo_mhz(read(cpuinfo)))]
    info = {"cores": cores, "source": source}
    info["driver"] = next((c["driver"] for c in cores if c["driver"]), "")
    info["governors"] = sorted({c["governor"] for c in cores if c["governor"]})
    info["epps"] = sorted({c["epp"] for c in cores if c["epp"]})
    info["epp_choices"] = read(os.path.join(root, "cpu0/cpufreq/energy_performance_available_preferences")).split()
    # turbo / boost
    turbo, how = None, ""
    no_turbo = _num(os.path.join(root, "intel_pstate/no_turbo"))
    if no_turbo is not None:
        turbo, how = no_turbo == 0, "intel_pstate"
    else:
        boost = _num(os.path.join(root, "cpufreq/boost"))
        if boost is None:
            boost = _num(os.path.join(root, "cpufreq/policy0/boost"))
        if boost is not None:
            turbo, how = boost == 1, "cpufreq"
    info["turbo"], info["turbo_source"] = turbo, how
    info["pstate_status"] = read(os.path.join(root, "intel_pstate/status")).strip() or read(os.path.join(root, "amd_pstate/status")).strip()
    tc = [c["throttle_core"] for c in cores if c["throttle_core"] is not None]
    tp = [c["throttle_pkg"] for c in cores if c["throttle_pkg"] is not None]
    info["throttle_core"] = sum(tc) if tc else None
    info["throttle_pkg"] = max(tp) if tp else None  # the package counter is shared, every core shows the same number
    mhz = [c["mhz"] for c in cores if c["mhz"]]
    info["avg_mhz"] = sum(mhz) / len(mhz) if mhz else None
    info["top_mhz"] = max(mhz) if mhz else None
    info["max_mhz"] = max((c["max"] for c in cores if c["max"]), default=None)
    return info


def throttle_verdict(core: int | None, pkg: int | None) -> tuple[str, str]:
    """(level, plain sentence) about thermal throttling since boot."""
    if core is None and pkg is None:
        return "info", "This CPU doesn't report throttling (normal for AMD and virtual machines). Watch the temperatures instead."
    total = (core or 0) + (pkg or 0)
    if total == 0:
        return "ok", "The CPU hasn't had to slow down to cool off since the PC started."
    if total < 200:
        return "ok", f"The CPU slowed itself down to cool off {total} times since the PC started. A few is normal under heavy load."
    return "warn", (f"The CPU slowed itself down to cool off {total} times since the PC started. That's a lot: it's running hot. "
                    "Check that the vents aren't blocked; on an older laptop, dust or dried thermal paste is common.")


def cpu_facts(info: dict) -> list[tuple[str, str]]:
    """Plain-English rows (title, explanation) for the CPU speed section."""
    facts = []
    drv = info.get("driver")
    if drv:
        facts.append((f"Speed control: {drv}" + (f" ({info['pstate_status']} mode)" if info.get("pstate_status") else ""),
                      DRIVERS.get(drv, "The kernel driver that changes the CPU speed.")))
    govs = info.get("governors") or []
    if govs:
        g = govs[0] if len(govs) == 1 else ", ".join(govs)
        facts.append((f"Governor: {g}", GOVERNORS.get(govs[0], "The rule Linux uses to pick the CPU speed.")))
    epps = info.get("epps") or []
    if epps:
        facts.append((f"Energy preference: {EPP.get(epps[0], epps[0])}" if len(epps) == 1 else "Energy preference: mixed (" + ", ".join(epps) + ")",
                      "A hint to the CPU about speed vs battery life. Your power mode sets it."))
    if info.get("turbo") is not None:
        facts.append(("Turbo boost: " + ("on" if info["turbo"] else "off"),
                      "Short bursts above the normal top speed when the CPU is cool enough." if info["turbo"] else
                      "The CPU never goes above its base speed. Cooler and quieter, but slower in bursts."))
    return facts


# ---------------------------------------------------------------- misc

def human_left(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min"
    return "less than a minute"


def clock(ts: float) -> str:
    t = time.localtime(ts)
    today = time.localtime()
    return time.strftime("%H:%M" if t[:3] == today[:3] else "%a %H:%M", t)
