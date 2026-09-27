"""Live system state: CPU, memory, disks, network, battery, temperatures, hardware, boot."""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .run import has, out, read, sh

REAL_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "f2fs", "zfs", "jfs", "reiserfs"}


# ---------------------------------------------------------------- identity

def os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"')
    return data


def identity() -> dict[str, str]:
    osr = os_release()
    dmi = Path("/sys/class/dmi/id")
    vendor = read(dmi / "sys_vendor").strip()
    product = read(dmi / "product_name").strip()
    version = read(dmi / "product_version").strip()
    model = " ".join(x for x in (vendor, product) if x and x.lower() not in ("to be filled by o.e.m.", "default string"))
    if version and version.lower() not in ("none", "to be filled by o.e.m.", "default string", "1.0") and version not in model:
        model = f"{model} ({version})" if model else version
    return {
        "host": platform.node(),
        "os": osr.get("PRETTY_NAME", "Linux"),
        "version": osr.get("VERSION_ID", ""),
        "codename": osr.get("VERSION_CODENAME", ""),
        "kernel": platform.release(),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "").replace("ubuntu:", ""),
        "session": os.environ.get("XDG_SESSION_TYPE", ""),
        "shell": os.path.basename(os.environ.get("SHELL", "")),
        "model": model or "Unknown computer",
        "user": os.environ.get("USER") or getpass.getuser(),
    }


def uptime_seconds() -> float:
    return time.time() - psutil.boot_time()


# ---------------------------------------------------------------- CPU / memory

def cpu_model() -> str:
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
    return platform.processor() or "CPU"


@dataclass
class Snapshot:
    cpu: float
    per_cpu: list[float]
    load: tuple[float, float, float]
    freq_mhz: float | None
    mem_used: int
    mem_total: int
    mem_pct: float
    swap_used: int
    swap_total: int
    net_rx: float  # bytes/s
    net_tx: float
    disk_read: float
    disk_write: float
    procs: int


class Sampler:
    """Keeps previous counters so it can report rates between calls."""

    def __init__(self) -> None:
        self._t = time.monotonic()
        self._net = psutil.net_io_counters()
        self._disk = psutil.disk_io_counters()
        psutil.cpu_percent(percpu=True)

    def sample(self) -> Snapshot:
        now = time.monotonic()
        dt = max(now - self._t, 0.001)
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        rx = (net.bytes_recv - self._net.bytes_recv) / dt if net and self._net else 0.0
        tx = (net.bytes_sent - self._net.bytes_sent) / dt if net and self._net else 0.0
        dr = (disk.read_bytes - self._disk.read_bytes) / dt if disk and self._disk else 0.0
        dw = (disk.write_bytes - self._disk.write_bytes) / dt if disk and self._disk else 0.0
        self._t, self._net, self._disk = now, net, disk
        per = psutil.cpu_percent(percpu=True)
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        try:
            freq = psutil.cpu_freq()
            f = freq.current if freq else None
        except (FileNotFoundError, NotImplementedError):  # some VMs
            f = None
        return Snapshot(
            cpu=sum(per) / len(per) if per else 0.0,
            per_cpu=per,
            load=os.getloadavg(),
            freq_mhz=f,
            mem_used=vm.total - vm.available,
            mem_total=vm.total,
            mem_pct=vm.percent,
            swap_used=sw.used,
            swap_total=sw.total,
            net_rx=max(rx, 0),
            net_tx=max(tx, 0),
            disk_read=max(dr, 0),
            disk_write=max(dw, 0),
            procs=len(psutil.pids()),
        )


# ---------------------------------------------------------------- disks

@dataclass
class Mount:
    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    pct: float


def mounts() -> list[Mount]:
    seen: set[str] = set()
    res: list[Mount] = []
    for p in psutil.disk_partitions(all=False):
        hidden = p.mountpoint.startswith(("/snap", "/var/snap", "/run/")) and not p.mountpoint.startswith("/run/media")
        if p.fstype not in REAL_FS or hidden:
            continue
        if p.device in seen:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        seen.add(p.device)
        res.append(Mount(p.device, p.mountpoint, p.fstype, u.total, u.used, u.free, u.percent))
    res.sort(key=lambda m: (m.mountpoint != "/", m.mountpoint))
    return res


def physical_disks() -> list[dict]:
    r = sh(["lsblk", "-J", "-d", "-b", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE"])
    if not r.ok:
        return []
    try:
        devs = json.loads(r.out).get("blockdevices", [])
    except json.JSONDecodeError:
        return []
    disks = []
    for d in devs:
        if d.get("type") != "disk" or str(d.get("name", "")).startswith(("loop", "zram", "ram")):
            continue
        kind = "HDD" if d.get("rota") in (True, "1", 1) else ("NVMe SSD" if str(d.get("name", "")).startswith("nvme") else "SSD")
        disks.append({"name": d.get("name"), "model": (d.get("model") or "").strip(), "size": int(d.get("size") or 0), "kind": kind, "bus": d.get("tran") or ""})
    return disks


# ---------------------------------------------------------------- battery / power / sensors

def parse_upower(text: str) -> dict:
    info: dict = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        info[k] = v
    def num(key: str) -> float | None:
        m = re.match(r"([\d.,]+)", info.get(key, ""))
        return float(m.group(1).replace(",", ".")) if m else None
    full, design = num("energy-full"), num("energy-full-design")
    health = round(full / design * 100, 1) if full and design else None
    cycles = info.get("charge-cycles")
    return {
        "vendor": info.get("vendor", ""),
        "model": info.get("model", ""),
        "state": info.get("state", ""),
        "percentage": num("percentage"),
        "health": health,
        "energy_full": full,
        "energy_design": design,
        "rate": num("energy-rate"),
        "cycles": int(cycles) if cycles and cycles.isdigit() and int(cycles) > 0 else None,
        "time_to_empty": info.get("time to empty", ""),
        "time_to_full": info.get("time to full", ""),
        "technology": info.get("technology", ""),
    }


def battery() -> dict | None:
    # Battery information is optional.  psutil may expose sensors_battery() but
    # still raise on desktops, containers/VMs, or systems without a readable
    # /sys/class/power_supply.  A missing probe must never take down a page.
    try:
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    except (AttributeError, OSError, NotImplementedError):
        return None
    if b is None:
        return None
    data = {"percent": b.percent, "plugged": b.power_plugged, "secs_left": b.secsleft if b.secsleft and b.secsleft > 0 else None}
    if has("upower"):
        dev = next((ln.strip() for ln in out(["upower", "-e"]).splitlines() if "battery_BAT" in ln or "/battery_" in ln), "")
        if dev:
            data.update({k: v for k, v in parse_upower(out(["upower", "-i", dev])).items() if v not in (None, "")})
    return data


def temperatures() -> list[dict]:
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return []
    res = []
    for chip, entries in temps.items():
        for e in entries:
            if e.current is None or e.current <= 0:
                continue
            res.append({"chip": chip, "label": e.label or chip, "current": e.current, "high": e.high, "critical": e.critical})
    return res


def cpu_temp() -> float | None:
    temps = temperatures()
    for pref in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
        vals = [t["current"] for t in temps if t["chip"] == pref]
        if vals:
            return max(vals)
    return max((t["current"] for t in temps), default=None)


def fans() -> list[dict]:
    try:
        f = psutil.sensors_fans()
    except (AttributeError, OSError):
        return []
    return [{"chip": chip, "label": e.label or chip, "rpm": e.current} for chip, es in f.items() for e in es]


def power_profile() -> dict:
    if not has("powerprofilesctl"):
        return {"available": False}
    current = out(["powerprofilesctl", "get"], timeout=5)
    if not current:
        return {"available": False}
    listing = out(["powerprofilesctl", "list"])
    profiles = re.findall(r"^\s*\*?\s*([a-z-]+):\s*$", listing, re.M)
    return {"available": True, "current": current, "profiles": profiles or ["power-saver", "balanced", "performance"]}


# ---------------------------------------------------------------- hardware + boot

def gpus() -> list[str]:
    res = []
    for line in out(["lspci", "-mm"]).splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:
                res.append(f"{parts[1]} {parts[2]}".replace("Corporation", "").replace("  ", " ").strip())
    return res


def hardware() -> dict:
    vm = psutil.virtual_memory()
    dmi = Path("/sys/class/dmi/id")
    return {
        "cpu": cpu_model(),
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count() or 0,
        "ram": vm.total,
        "gpus": gpus(),
        "disks": physical_disks(),
        "bios": " ".join(x for x in (read(dmi / "bios_vendor").strip(), read(dmi / "bios_version").strip(), read(dmi / "bios_date").strip()) if x),
        "board": " ".join(x for x in (read(dmi / "board_vendor").strip(), read(dmi / "board_name").strip()) if x),
        "arch": platform.machine(),
    }


def parse_boot_time(text: str) -> dict:
    total = re.search(r"=\s*([\d.]+min\s*)?([\d.]+)s", text)
    res: dict = {"raw": text.strip().splitlines()[0] if text.strip() else ""}
    if total:
        mins = float(total.group(1).replace("min", "").strip()) if total.group(1) else 0
        res["total"] = mins * 60 + float(total.group(2))
    for part in ("firmware", "loader", "kernel", "userspace"):
        m = re.search(r"([\d.]+min\s*)?([\d.]+)s \(" + part + r"\)", text)
        if m:
            mins = float(m.group(1).replace("min", "").strip()) if m.group(1) else 0
            res[part] = mins * 60 + float(m.group(2))
    return res


def parse_blame(text: str, limit: int = 12) -> list[tuple[float, str]]:
    res = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:(\d+)min\s*)?([\d.]+)(ms|s)\s+(\S+)", line)
        if not m:
            continue
        secs = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1) + (int(m.group(1)) * 60 if m.group(1) else 0)
        res.append((secs, m.group(4)))
        if len(res) >= limit:
            break
    return res


def boot() -> dict:
    if not has("systemd-analyze"):
        return {}
    info = parse_boot_time(out(["systemd-analyze", "time"], timeout=15))
    info["blame"] = parse_blame(out(["systemd-analyze", "blame", "--no-pager"], timeout=15))
    return info


def reboot_required() -> list[str] | None:
    if not Path("/var/run/reboot-required").exists():
        return None
    return [p for p in read("/var/run/reboot-required.pkgs").split() if p]


# ---------------------------------------------------------------- processes

@dataclass
class Proc:
    pid: int
    name: str
    user: str
    cpu: float
    mem: int
    mem_pct: float
    cmd: str
    status: str
    started: float
    threads: int = 0
    children: list = field(default_factory=list)
    ppid: int = 0
    io: float = 0.0          # disk read+write, bytes per second (your own processes; others need admin rights)
    nice: int = 0


class ProcessWatcher:
    """psutil.process_iter caches Process objects, so cpu_percent() compares against the last call."""

    def __init__(self) -> None:
        self.ncpu = psutil.cpu_count() or 1
        self._io: dict[int, tuple[float, int]] = {}

    def list(self) -> list[Proc]:
        import time as _t
        res: list[Proc] = []
        attrs = ["pid", "name", "username", "memory_info", "memory_percent", "cmdline", "status", "create_time", "num_threads", "ppid",
                 "io_counters", "nice"]
        now = _t.monotonic()
        new_io: dict[int, tuple[float, int]] = {}
        for p in psutil.process_iter(attrs):
            try:
                cpu = p.cpu_percent(None) / self.ncpu
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                cpu = 0.0
            mi = p.info.get("memory_info")
            cmd = p.info.get("cmdline") or []
            res.append(Proc(
                pid=p.info["pid"],
                name=p.info.get("name") or "?",
                user=p.info.get("username") or "?",
                cpu=cpu,
                mem=mi.rss if mi else 0,
                mem_pct=p.info.get("memory_percent") or 0.0,
                cmd=" ".join(cmd) if cmd else f"[{p.info.get('name')}]",
                status=p.info.get("status") or "",
                started=p.info.get("create_time") or 0,
                threads=p.info.get("num_threads") or 0,
                ppid=p.info.get("ppid") or 0,
                nice=p.info.get("nice") or 0,
            ))
            ioc = p.info.get("io_counters")
            if ioc is not None:
                total = ioc.read_bytes + ioc.write_bytes
                prev = self._io.get(p.pid)
                if prev and now > prev[0]:
                    res[-1].io = max(0.0, (total - prev[1]) / (now - prev[0]))
                new_io[p.pid] = (now, total)
        self._io = new_io
        return res


def app_groups(procs: list[Proc]) -> list[dict]:
    """Group processes into 'apps' by name (chrome's 30 helpers become one row)."""
    groups: dict[str, dict] = {}
    for p in procs:
        key = p.name.split("/")[0]
        for pre in ("chrome", "brave", "firefox", "code", "electron", "zed", "slack", "discord", "telegram"):
            if key.lower().startswith(pre):
                key = pre
                break
        g = groups.setdefault(key, {"name": key, "cpu": 0.0, "mem": 0, "count": 0, "pids": []})
        g["cpu"] += p.cpu
        g["mem"] += p.mem
        g["count"] += 1
        g["pids"].append(p.pid)
    return sorted(groups.values(), key=lambda g: (-g["mem"]))
