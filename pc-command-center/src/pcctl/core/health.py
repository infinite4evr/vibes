"""The overall health check shown on the Overview and by `pc doctor`."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import psutil

from . import junk, packages, security, services, system
from .fmt import human
from .run import Step, sh
from .security import Check


def disk_checks() -> list[Check]:
    res = []
    for m in system.mounts():
        if m.pct >= 90:
            res.append(Check(f"disk:{m.mountpoint}", f"Disk {m.mountpoint} almost full", "bad", f"{m.pct:.0f}% used, {human(m.free)} left.", "Free up space", goto="cleanup"))
        elif m.pct >= 80:
            res.append(Check(f"disk:{m.mountpoint}", f"Disk {m.mountpoint} filling up", "warn", f"{m.pct:.0f}% used, {human(m.free)} left.", "Free up space", goto="cleanup"))
    if not res:
        root = next((m for m in system.mounts() if m.mountpoint == "/"), None)
        res.append(Check("disk", "Disk space", "ok", f"{human(root.free)} free on your main disk." if root else "OK"))
    return res


def memory_check() -> Check:
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    if vm.percent >= 90 or (sw.total and sw.used > vm.total * 0.5):
        return Check("memory", "Memory is tight", "warn", f"{vm.percent:.0f}% RAM used, {human(sw.used)} swap. Close heavy apps (see Processes).", "See what's using it", goto="processes")
    return Check("memory", "Memory", "ok", f"{vm.percent:.0f}% used.")


def updates_check(ups: list[packages.Update]) -> Check:
    last = packages.last_apt_update()
    age_days = (time.time() - last) / 86400 if last else 99
    sec = sum(u.security for u in ups)
    if ups:
        lvl = "bad" if sec else "warn"
        return Check("updates", "Updates waiting", lvl, f"{len(ups)} updates" + (f", {sec} security" if sec else "") + ".", "Update now", packages.update_all_steps())
    if age_days > 7:
        return Check("updates", "Haven't checked for updates", "warn", f"Last check {int(age_days)} days ago.", "Check now", packages.refresh_steps())
    return Check("updates", "Updates", "ok", "Everything is up to date.")


def services_check() -> Check:
    bad = services.failed()
    if bad:
        return Check("services", "Services failing", "warn", ", ".join(s.name for s in bad[:5]), "Open Services", goto="services")
    return Check("services", "Background services", "ok", "Nothing is failing.")


def junk_check() -> Check:
    items = [junk.apt_cache(), junk.python_caches(), junk.js_caches(), junk.journal(), junk.snap_old(), junk.trash(), junk.thumbnails()]
    total = sum(j.size or 0 for j in items)
    if total > 2 * 1024**3:
        return Check("junk", "Junk piling up", "warn", f"About {human(total)} of caches, logs and old versions.", "Clean up", goto="cleanup")
    return Check("junk", "Junk", "ok", f"Only {human(total)} of caches and logs.")


def temp_check() -> Check:
    t = system.cpu_temp()
    if t is None:
        return Check("temp", "Temperature", "info", "No sensors found.")
    if t >= 90:
        return Check("temp", "CPU is hot", "bad", f"{t:.0f}°C. Check vents/fans, or switch to power-saver mode.", "Power settings", goto="power")
    if t >= 80:
        return Check("temp", "CPU is warm", "warn", f"{t:.0f}°C.", "Power settings", goto="power")
    return Check("temp", "Temperature", "ok", f"CPU {t:.0f}°C.")


def battery_check() -> Check | None:
    b = system.battery()
    if not b:
        return None
    h = b.get("health")
    if h and h < 70:
        return Check("battery", "Battery is worn", "warn", f"Holds {h:.0f}% of its original charge.", "Details", goto="power")
    return Check("battery", "Battery", "ok", f"Health {h:.0f}%." if h else f"{b['percent']:.0f}% charged.")


def time_check() -> Check:
    probe = sh(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=5)
    if not probe.ok or probe.out.strip() not in ("yes", "no"):
        detail = "Clock synchronization status is unavailable." if probe.code == 127 else "Could not determine clock synchronization status."
        return Check("time", "Clock status unknown", "info", detail)
    if probe.out.strip() == "no":
        return Check("time", "Clock not synced", "warn", "Your clock may drift; websites and logins can fail.", "Turn on time sync",
                     [Step("Sync clock automatically", ["timedatectl", "set-ntp", "true"], root=True)])
    return Check("time", "Clock", "ok", "Synced.")


def run_all(ups: list[packages.Update] | None = None) -> list[Check]:
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_ups = ex.submit(packages.pending_updates) if ups is None else None
        f_sec = ex.submit(lambda: [security.firewall(), security.auto_updates(), security.reboot_needed(), security.screen_lock()])
        f_junk = ex.submit(junk_check)
        f_svc = ex.submit(services_check)
        f_misc = ex.submit(lambda: [memory_check(), temp_check(), time_check()])
        ups = ups if ups is not None else f_ups.result()
        checks = disk_checks() + [updates_check(ups)] + f_sec.result() + [f_svc.result(), f_junk.result()] + f_misc.result()
    b = battery_check()
    if b:
        checks.append(b)
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    checks.sort(key=lambda c: order[c.level])
    return checks


def score(checks: list[Check]) -> int:
    weights = {"ok": 0, "info": 0, "warn": 7, "bad": 18}
    return max(0, 100 - sum(weights[c.level] for c in checks))
