"""Safe optimization advisor.

Recommendations are evidence-based and non-destructive.  The advisor never applies a
change by itself; UI/CLI callers can present the optional Step list for confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import psutil

from . import junk, packages, services, system
from .fmt import human
from .run import Step, sh


@dataclass
class Advice:
    id: str
    title: str
    detail: str
    benefit: str
    risk: str = "low"
    goto: str | None = None
    steps: list[Step] = field(default_factory=list)


def recommendations() -> list[Advice]:
    out: list[Advice] = []

    # Storage pressure and reclaimable caches.
    mounts = system.mounts()
    root = next((m for m in mounts if m.mountpoint == "/"), None)
    if root and root.pct >= 80:
        out.append(Advice("disk-pressure", "Free space on the main disk",
                          f"The main disk is {root.pct:.0f}% full with {human(root.free)} available.",
                          "More free space reduces update failures and gives applications room for temporary files.",
                          goto="cleanup"))
    try:
        candidates = [junk.apt_cache(), junk.python_caches(), junk.js_caches(), junk.journal(), junk.trash(), junk.thumbnails()]
        reclaim = sum(x.size or 0 for x in candidates)
        if reclaim >= 1024**3:
            out.append(Advice("junk", "Review reclaimable files", f"About {human(reclaim)} of caches, logs and Trash can be reviewed.",
                              "Recovers disk space without touching personal documents.", goto="cleanup"))
    except Exception:  # probes must never make the advisor fail
        pass

    # Memory pressure: recommend inspection, never dubious 'RAM cleaners'.
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    if vm.percent >= 85 or (sw.total and sw.percent >= 60):
        out.append(Advice("memory", "Review heavy applications",
                          f"RAM is {vm.percent:.0f}% used" + (f" and swap is {sw.percent:.0f}% used." if sw.total else "."),
                          "Closing or limiting the actual heavy application is safer than clearing Linux caches.", goto="processes"))

    # Updates.
    try:
        ups = packages.pending_updates()
        sec = sum(bool(u.security) for u in ups)
        if ups:
            out.append(Advice("updates", "Install pending updates", f"{len(ups)} updates are waiting" + (f", including {sec} security fixes." if sec else "."),
                              "Gets bug, compatibility and security fixes.", risk="medium", goto="updates"))
    except Exception:
        pass

    # Failed services: diagnose rather than blindly disabling them.
    try:
        failed = services.failed()
        if failed:
            names = ", ".join(s.name for s in failed[:4])
            out.append(Advice("failed-services", "Investigate failed services", f"Failed: {names}.",
                              "Fixing a repeatedly failing service can reduce errors and background retries.", risk="medium", goto="services"))
    except Exception:
        pass

    # Journal retention is a safe, explainable candidate.
    try:
        j = junk.journal()
        if (j.size or 0) >= 1024**3:
            out.append(Advice("journal", "Trim old system logs", f"System logs use about {human(j.size or 0)}.",
                              "Recovers space while retaining recent logs for troubleshooting.", goto="cleanup"))
    except Exception:
        pass

    # Power profile hint on battery-powered systems.
    try:
        b = system.battery()
        if b and not b.get("plugged") and b.get("percent", 100) <= 35:
            out.append(Advice("battery", "Use the power-saver profile", f"Battery is at {b.get('percent', 0):.0f}%.",
                              "Can extend remaining battery time without making permanent changes.", goto="power"))
    except Exception:
        pass

    # Clock synchronization is surprisingly important for package/TLS reliability.
    r = sh(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=4)
    if r.ok and r.out.strip() == "no":
        out.append(Advice("clock", "Enable automatic clock synchronization", "The system clock is not synchronized.",
                          "Avoids TLS, login and repository errors caused by clock drift.", risk="low",
                          steps=[Step("Enable network time synchronization", ["timedatectl", "set-ntp", "true"], root=True)]))

    if not out:
        out.append(Advice("healthy", "No optimization is needed", "The checks did not find a change worth recommending right now.",
                          "PC Command Center avoids placebo tweaks when the system is already healthy."))
    return out
