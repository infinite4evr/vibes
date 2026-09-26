"""“Why is my PC slow?” - measures for a couple of seconds, then explains what's holding things back, with fixes."""

from __future__ import annotations

import glob
import os
import time

import psutil

from . import gpu, services, system
from .fmt import duration, human
from .run import Step, out, read
from .security import Check

ME = os.environ.get("USER", "")


def psi(kind: str) -> dict:
    """Pressure stall info: % of time tasks waited for cpu/memory/io over the last 10 s (some) and fully stalled (full)."""
    res = {"some": 0.0, "full": 0.0}
    for line in read(f"/proc/pressure/{kind}").splitlines():
        parts = line.split()
        if parts and parts[0] in res:
            for p in parts[1:]:
                if p.startswith("avg10="):
                    try:
                        res[parts[0]] = float(p.split("=")[1])
                    except ValueError:
                        pass
    return res


def pressure() -> dict:
    """0-100 'how much is the PC struggling' per resource, for the dashboard."""
    return {k: psi(k)["some"] for k in ("cpu", "memory", "io")}


def throttle_count() -> int:
    total = 0
    for f in glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/*_throttle_count"):
        try:
            total += int(read(f).strip() or 0)
        except ValueError:
            pass
    return total


def _sample_procs(secs: float = 1.5) -> list[dict]:
    procs = {}
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "username"]):
        if p.pid == me:
            continue
        try:
            p.cpu_percent(None)
            io = p.io_counters() if p.info.get("username") == ME else None
            procs[p.pid] = (p, io)
        except (psutil.Error, AttributeError):
            continue
    time.sleep(secs)
    ncpu = psutil.cpu_count() or 1
    res = []
    for pid, (p, io0) in procs.items():
        try:
            cpu = p.cpu_percent(None) / ncpu
            mem = p.memory_info().rss
            io_rate = 0.0
            if io0 is not None:
                io1 = p.io_counters()
                io_rate = ((io1.read_bytes - io0.read_bytes) + (io1.write_bytes - io0.write_bytes)) / secs
            res.append({"pid": pid, "name": p.info.get("name") or "?", "user": p.info.get("username") or "", "cpu": cpu, "mem": mem, "io": io_rate})
        except (psutil.Error, AttributeError):
            continue
    return res


def _group(procs: list[dict], key: str) -> list[tuple[str, float, list[int], set[str]]]:
    groups: dict[str, list] = {}
    for p in procs:
        name = p["name"].split("/")[0]
        for pre in ("chrome", "brave", "firefox", "code", "electron", "zed", "slack", "discord", "cursor"):
            if name.lower().startswith(pre):
                name = pre
        g = groups.setdefault(name, [0.0, [], set()])
        g[0] += p[key]
        g[1].append(p["pid"])
        g[2].add(p["user"])
    return sorted(((n, v[0], v[1], v[2]) for n, v in groups.items()), key=lambda x: -x[1])


def efficiency_steps(name: str, pids: list[int], users: set[str]) -> list[Step]:
    """Windows-style efficiency mode: lowest CPU priority and idle disk priority."""
    root = any(u and u != ME for u in users)
    pid_s = [str(p) for p in pids]
    return [Step(f"Lowest CPU priority for {name}", ["renice", "-n", "19", "-p", *pid_s], root=root, ok_codes=(0, 1)),
            Step(f"Disk access only when idle for {name}", ["ionice", "-c", "3", "-p", *pid_s], root=root, ok_codes=(0, 1), optional=True)]


def run(secs: float = 1.5) -> list[Check]:
    t0_throttle = throttle_count()
    cpu_total = psutil.cpu_percent(None)
    sw0 = psutil.swap_memory()
    procs = _sample_procs(secs)
    cpu_total = psutil.cpu_percent(None)
    sw1 = psutil.swap_memory()
    vm = psutil.virtual_memory()
    found: list[Check] = []

    # CPU
    by_cpu = _group(procs, "cpu")
    if by_cpu and (cpu_total >= 70 or by_cpu[0][1] >= 40):
        name, val, pids, users = by_cpu[0]
        found.append(Check("cpu", f"{name} is using {val:.0f}% of the CPU", "bad" if cpu_total >= 90 else "warn",
                           f"The whole CPU is {cpu_total:.0f}% busy. Efficiency mode lets {name} keep running but gives everything else priority.",
                           "Efficiency mode", efficiency_steps(name, pids, users)))
    # memory
    mem_psi = psi("memory")
    if vm.available < vm.total * 0.10 or mem_psi["some"] > 10:
        top = _group(procs, "mem")[:3]
        who = ", ".join(f"{n} {human(v)}" for n, v, _, _ in top)
        found.append(Check("memory", "Memory is almost full", "bad", f"Only {human(vm.available)} free. Biggest users: {who}. "
                           "Close tabs or apps you don't need.", "See processes", goto="processes"))
    # swapping
    swapped = (sw1.sin - sw0.sin) + (sw1.sout - sw0.sout)
    if sw1.total and (swapped > 5 * 1024 ** 2 or (sw1.percent > 60 and mem_psi["some"] > 5)):
        zram = bool(glob.glob("/sys/block/zram*")) and "zram" in read("/proc/swaps")
        found.append(Check("swap", "The PC is swapping to disk", "warn", f"{human(sw1.used)} of memory moved to disk; everything waits for it. "
                           + ("" if zram else "Compressed memory (zram) makes this much faster."),
                           "Tweaks" if not zram else "See processes", goto="tweaks" if not zram else "processes"))
    # disk
    io_psi = psi("io")
    if io_psi["some"] > 20:
        top = _group(procs, "io")
        who = f" Busiest: {top[0][0]} ({human(top[0][1])}/s)." if top and top[0][1] > 1024 ** 2 else ""
        found.append(Check("io", "Apps are waiting for the disk", "warn", f"{io_psi['some']:.0f}% of the time something waited on the disk.{who}",
                           "See processes", goto="processes"))
    # heat
    t = system.cpu_temp()
    throttled = throttle_count() > t0_throttle
    if throttled or (t and t >= 90):
        found.append(Check("thermal", "The CPU is slowing itself down because it's hot", "bad",
                           f"{t:.0f}°C. Clean the vents, use it on a hard surface, or switch to Balanced/Power saver." if t else
                           "Thermal throttling detected.", "Power & hardware", goto="power"))
    # power mode
    prof = system.power_profile()
    if prof.get("available") and prof.get("current") == "power-saver":
        found.append(Check("power-saver", "Power saver mode is on", "info", "It trades speed for battery life.", "Switch to Balanced",
                           [Step("Balanced power mode", ["powerprofilesctl", "set", "balanced"])]))
    # disk space
    for m in system.mounts():
        if m.mountpoint in ("/", "/home") and m.pct >= 92:
            found.append(Check("disk-full", f"{m.mountpoint} is {m.pct:.0f}% full", "bad", "A nearly full disk makes everything slow and "
                               "updates can fail.", "Free up space", goto="cleanup"))
    # background jobs
    names = {p["name"] for p in procs}
    busy_bg = []
    if names & {"unattended-upgr", "unattended-upgrade", "apt", "apt-get", "dpkg"}:
        busy_bg.append("installing updates")
    if names & {"localsearch-3", "localsearch", "tracker-miner-fs-3", "tracker-extract-3"} and \
            sum(p["cpu"] for p in procs if p["name"].startswith(("localsearch", "tracker"))) > 10:
        busy_bg.append("indexing your files for search")
    if "snapd" in names and "Doing" in out(["snap", "changes"], timeout=5):
        busy_bg.append("updating snaps")
    if "packagekitd" in names and sum(p["cpu"] for p in procs if p["name"] == "packagekitd") > 10:
        busy_bg.append("checking for software updates")
    if busy_bg:
        found.append(Check("background", "Ubuntu is busy in the background", "info", "Right now it's " + " and ".join(busy_bg) +
                           ". This finishes by itself; give it a few minutes."))
    # browser
    for n, v, _, _ in _group(procs, "mem"):
        if n in ("chrome", "firefox", "brave", "msedge", "chromium") and v > 3 * 1024 ** 3:
            found.append(Check("browser", f"Your browser uses {human(v)} of memory", "warn", "Every tab costs memory. Close tabs you don't need, "
                               "or turn on the browser's Memory Saver.", "See processes", goto="processes"))
            break
    # login apps
    try:
        on = [a for a in services.startup_apps() if a.enabled and not a.system]
        if len(on) >= 8:
            found.append(Check("startup", f"{len(on)} apps start when you log in", "info", "Each one slows down login and uses memory all day.",
                               "Startup", goto="startup"))
    except Exception:  # noqa: BLE001
        pass
    # failing services that restart in a loop
    bad = services.failed()
    if bad:
        found.append(Check("failed", f"{len(bad)} background service(s) failing", "info", ", ".join(s.name for s in bad[:4]),
                           "Services", goto="services"))
    # graphics driver
    hint = gpu.driver_hint()
    if hint:
        found.append(Check("gpu-driver", "Graphics card on the basic driver", "warn", hint, "Drivers", goto="updates"))
    # uptime
    up = system.uptime_seconds()
    if up > 14 * 86400:
        found.append(Check("uptime", f"Running for {duration(up)} without a restart", "info",
                           "A restart clears memory leaks and finishes pending updates.", "Restart…",
                           [Step("Restart the computer", ["systemctl", "reboot"])]))
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    found.sort(key=lambda c: order[c.level])
    if not found:
        found.append(Check("fine", "Nothing is slowing your PC down right now", "ok",
                           f"CPU {cpu_total:.0f}% busy, {human(vm.available)} memory free, no disk waiting, no overheating."))
    return found
