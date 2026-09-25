"""Network: interfaces, Wi-Fi, listening ports (and who owns them), DNS, connectivity checks."""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass

import psutil

from .dev import DEV_HINTS
from .run import Step, has, out, sh


@dataclass
class Port:
    proto: str
    address: str
    port: int
    pid: int | None
    process: str
    exposed: bool  # reachable from other devices (not just this PC)
    user: str = ""
    cmd: str = ""

    @property
    def kind(self) -> str:
        return DEV_HINTS.get(self.process, "")


def _split_addr(addr: str) -> tuple[str, int]:
    host, _, port = addr.rpartition(":")
    host = host.strip("[]").split("%")[0]
    try:
        return host, int(port)
    except ValueError:
        return host, 0


def parse_ss(text: str) -> list[Port]:
    res: list[Port] = []
    seen: set[tuple] = set()
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 5 or cols[0] not in ("tcp", "udp"):
            continue
        state = cols[1]
        if cols[0] == "tcp" and state != "LISTEN":
            continue
        if cols[0] == "udp" and state not in ("UNCONN", "LISTEN"):
            continue
        host, port = _split_addr(cols[4])
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        proc, pid = (m.group(1), int(m.group(2))) if m else ("", None)
        exposed = host in ("0.0.0.0", "::", "*", "") or not (host.startswith("127.") or host == "::1" or host.startswith("fe80"))
        key = (cols[0], port, pid, exposed)
        if key in seen:
            continue
        seen.add(key)
        res.append(Port(cols[0], host or "*", port, pid, proc, exposed))
    res.sort(key=lambda p: (p.proto != "tcp", p.port))
    return res


def ports(with_root: bool = True) -> list[Port]:
    r = sh(["ss", "-tulpnH"], root=with_root, timeout=10)
    if not r.ok:
        r = sh(["ss", "-tulpnH"], timeout=10)
    items = parse_ss(r.out)
    for p in items:
        if p.pid:
            try:
                proc = psutil.Process(p.pid)
                p.user = proc.username()
                p.cmd = " ".join(proc.cmdline())[:200]
            except (psutil.Error, OSError):
                pass
    return items


def kill_port_steps(port: int, items: list[Port] | None = None) -> list[Step]:
    items = items if items is not None else ports()
    pids = sorted({p.pid for p in items if p.port == port and p.pid})
    steps = []
    me = os.environ.get("USER", "")
    for pid in pids:
        owner = next((p.user for p in items if p.pid == pid), "")
        steps.append(Step(f"Stop process {pid} using port {port}", ["kill", str(pid)], root=bool(owner and owner != me)))
    return steps


def interfaces() -> list[dict]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    io = psutil.net_io_counters(pernic=True)
    res = []
    for name, st in stats.items():
        if name == "lo" or name.startswith(("veth", "br-", "docker", "virbr", "podman", "cni")):
            continue
        ipv4 = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
        ipv6 = [a.address.split("%")[0] for a in addrs.get(name, []) if a.family == socket.AF_INET6 and not a.address.startswith("fe80")]
        mac = next((a.address for a in addrs.get(name, []) if a.family == psutil.AF_LINK), "")
        kind = "Wi-Fi" if name.startswith(("wl", "wlan")) else ("Ethernet" if name.startswith(("en", "eth")) else ("VPN" if name.startswith(("tun", "wg", "CloudflareWARP", "tailscale", "proton")) else "Other"))
        c = io.get(name)
        res.append({"name": name, "kind": kind, "up": st.isup, "speed": st.speed, "ipv4": ipv4, "ipv6": ipv6, "mac": mac,
                    "rx": c.bytes_recv if c else 0, "tx": c.bytes_sent if c else 0})
    res.sort(key=lambda i: (not i["up"], i["kind"] != "Wi-Fi", i["name"]))
    return res


def parse_nmcli_wifi(text: str) -> list[dict]:
    res = []
    for line in text.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 4:
            continue
        active, ssid, signal, security = parts[0], parts[1].replace("\\:", ":"), parts[2], parts[3]
        if not ssid:
            continue
        res.append({"active": active == "yes", "ssid": ssid, "signal": int(signal) if signal.isdigit() else 0, "security": security or "open"})
    best: dict[str, dict] = {}
    for w in res:
        if w["ssid"] not in best or w["active"] or w["signal"] > best[w["ssid"]]["signal"] and not best[w["ssid"]]["active"]:
            best[w["ssid"]] = w
    return sorted(best.values(), key=lambda w: (not w["active"], -w["signal"]))


def wifi(rescan: bool = False) -> dict:
    if not has("nmcli"):
        return {"available": False}
    radio = out(["nmcli", "radio", "wifi"])
    nets = parse_nmcli_wifi(out(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes" if rescan else "no"], timeout=20))
    return {"available": True, "enabled": radio == "enabled", "networks": nets}


def dns_servers() -> list[str]:
    text = out(["resolvectl", "dns"]) if has("resolvectl") else ""
    servers = []
    for line in text.splitlines():
        _, _, rest = line.partition(":")
        servers += [s for s in rest.split() if s not in servers]
    if not servers:
        servers = re.findall(r"^nameserver\s+(\S+)", out(["cat", "/etc/resolv.conf"]), re.M)
    return servers


def default_gateway() -> str:
    m = re.search(r"default via (\S+) dev (\S+)", out(["ip", "route"]))
    return f"{m.group(1)} ({m.group(2)})" if m else ""


def public_ip() -> str:
    for url in ("https://ifconfig.me/ip", "https://api.ipify.org"):
        r = sh(["curl", "-fsS", "--max-time", "6", url], timeout=8)
        if r.ok and r.out.strip():
            return r.out.strip()
    return ""


def ping(host: str = "1.1.1.1") -> dict:
    r = sh(["ping", "-c", "4", "-W", "2", host], timeout=15)
    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", r.out)
    avg = re.search(r"= [\d.]+/([\d.]+)/", r.out)
    return {"ok": r.ok, "loss": float(loss.group(1)) if loss else 100.0, "avg_ms": float(avg.group(1)) if avg else None}


def dns_check(name: str = "ubuntu.com") -> bool:
    try:
        socket.getaddrinfo(name, 443)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- speed test

def speed_test(progress=None) -> dict:
    """Download/upload speed against Cloudflare's speed test endpoints (about 25 MB down, 5 MB up)."""
    import time
    import urllib.request

    res: dict = {"down_mbps": None, "up_mbps": None, "latency_ms": None, "server": "speed.cloudflare.com"}
    try:
        t0 = time.monotonic()
        urllib.request.urlopen("https://speed.cloudflare.com/__down?bytes=1", timeout=8).read()
        res["latency_ms"] = (time.monotonic() - t0) * 1000
        if progress:
            progress("Measuring download…")
        size = 25_000_000
        t0 = time.monotonic()
        with urllib.request.urlopen(f"https://speed.cloudflare.com/__down?bytes={size}", timeout=60) as r:
            got = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
        dt = time.monotonic() - t0
        res["down_mbps"] = got * 8 / dt / 1e6
        if progress:
            progress("Measuring upload…")
        data = b"0" * 5_000_000
        req = urllib.request.Request("https://speed.cloudflare.com/__up", data=data, method="POST",
                                     headers={"Content-Type": "application/octet-stream"})
        t0 = time.monotonic()
        urllib.request.urlopen(req, timeout=60).read()
        res["up_mbps"] = len(data) * 8 / (time.monotonic() - t0) / 1e6
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
    return res


def hosts_entries() -> list[str]:
    return [ln for ln in out(["cat", "/etc/hosts"]).splitlines() if ln.strip() and not ln.strip().startswith("#")]


# ---------------------------------------------------------------- active connections

def parse_ss_established(text: str) -> list[dict]:
    """`ss -tunpH state established` → [{proto, local, remote_ip, remote_port, process, pid}]."""
    res = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        proto = cols[0]
        # with a state filter ss drops the State column: proto recv-q send-q local peer [process]
        local, peer = cols[3], cols[4]
        rip, rport = _split_addr(peer)
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        res.append({"proto": proto, "local": local, "remote_ip": rip, "remote_port": rport,
                    "process": m.group(1) if m else "", "pid": int(m.group(2)) if m else 0})
    return res


def connections(resolve: bool = True) -> list[dict]:
    items = parse_ss_established(out(["ss", "-tunpH", "state", "established"], timeout=10))
    items = [c for c in items if not c["remote_ip"].startswith(("127.", "::1")) and c["remote_ip"] not in ("::ffff:127.0.0.1",)]
    if resolve:
        import concurrent.futures
        cache: dict[str, str] = {}

        def rdns(ip: str) -> str:
            try:
                return socket.gethostbyaddr(ip)[0]
            except (OSError, UnicodeError):
                return ""
        ips = sorted({c["remote_ip"] for c in items})
        socket.setdefaulttimeout(2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
            for ip, name in zip(ips, ex.map(rdns, ips)):
                cache[ip] = name
        socket.setdefaulttimeout(None)
        for c in items:
            c["host"] = cache.get(c["remote_ip"], "")
    return items


SERVICES = {443: "HTTPS", 80: "HTTP", 22: "SSH", 53: "DNS", 993: "Mail (IMAP)", 587: "Mail (SMTP)", 5222: "Chat (XMPP)", 3478: "Calls (STUN)",
            5228: "Google push", 8009: "Chromecast", 27017: "MongoDB", 5432: "PostgreSQL", 3306: "MySQL", 6379: "Redis"}


# ---------------------------------------------------------------- DNS switcher (NetworkManager)

DNS_PRESETS = [
    ("auto", "Automatic (from your router)", "", ""),
    ("cloudflare", "Cloudflare 1.1.1.1", "1.1.1.1 1.0.0.1", "2606:4700:4700::1111 2606:4700:4700::1001"),
    ("google", "Google 8.8.8.8", "8.8.8.8 8.8.4.4", "2001:4860:4860::8888 2001:4860:4860::8844"),
    ("quad9", "Quad9 (blocks known malware sites)", "9.9.9.9 149.112.112.112", "2620:fe::fe 2620:fe::9"),
    ("adguard", "AdGuard (blocks ads and trackers)", "94.140.14.14 94.140.15.15", "2a10:50c0::ad1:ff 2a10:50c0::ad2:ff"),
    ("cloudflare-family", "Cloudflare for Families (blocks malware + adult sites)", "1.1.1.3 1.0.0.3", "2606:4700:4700::1113 2606:4700:4700::1003"),
]


def active_connection() -> dict:
    """The NetworkManager connection that carries the default route."""
    for line in out(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "con", "show", "--active"], timeout=10).splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) >= 4 and parts[2] not in ("loopback", "bridge", "tun") and parts[3] and not parts[3].startswith(("docker", "veth", "virbr", "lo")):
            return {"name": parts[0].replace("\\:", ":"), "uuid": parts[1], "type": parts[2], "device": parts[3]}
    return {}


def current_dns_preset(con: dict | None = None) -> str:
    con = con or active_connection()
    if not con:
        return "auto"
    v4 = out(["nmcli", "-g", "ipv4.dns", "con", "show", con["uuid"]], timeout=10).replace(",", " ").split()
    for key, _t, ips, _v6 in DNS_PRESETS:
        if ips and v4 and v4[0] in ips.split():
            return key
    return "custom" if v4 else "auto"


def dns_steps(preset: str, con: dict) -> list:
    from .run import Step
    p = next(x for x in DNS_PRESETS if x[0] == preset)
    uuid = con["uuid"]
    if preset == "auto":
        mods = ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no", "ipv6.dns", "", "ipv6.ignore-auto-dns", "no"]
    else:
        mods = ["ipv4.dns", p[2], "ipv4.ignore-auto-dns", "yes", "ipv6.dns", p[3], "ipv6.ignore-auto-dns", "yes"]
    return [Step(f"Use {p[1]} for {con['name']}", ["nmcli", "con", "mod", uuid, *mods]),
            Step("Reconnect to apply it", ["nmcli", "con", "up", uuid], ok_codes=(0, 4)),
            Step("Forget old lookups", ["resolvectl", "flush-caches"], optional=True)]


# ---------------------------------------------------------------- VPNs, saved Wi-Fi, hotspot

def nm_connections() -> list[dict]:
    res = []
    active = {ln.split(":")[0] for ln in out(["nmcli", "-t", "-f", "UUID", "con", "show", "--active"], timeout=10).splitlines()}
    for line in out(["nmcli", "-t", "-f", "NAME,UUID,TYPE,TIMESTAMP-REAL,AUTOCONNECT", "con", "show"], timeout=10).splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 5:
            continue
        res.append({"name": parts[0].replace("\\:", ":"), "uuid": parts[1], "type": parts[2], "last": parts[3].replace("\\:", ":"),
                    "auto": parts[4] == "yes", "active": parts[1] in active})
    return res


def vpns() -> list[dict]:
    items = [c for c in nm_connections() if c["type"] in ("vpn", "wireguard")]
    if has("tailscale"):
        st = out(["tailscale", "status", "--peers=false"], timeout=8)
        items.append({"name": "Tailscale", "uuid": "", "type": "tailscale", "last": "", "auto": True, "active": bool(st) and "stopped" not in st.lower()})
    return items


def wifi_password(uuid: str) -> str:
    return out(["nmcli", "-s", "-g", "802-11-wireless-security.psk", "con", "show", uuid], timeout=10)


def hotspot_steps(on: bool, ssid: str = "", password: str = "") -> list:
    from .run import Step
    if on:
        args = ["nmcli", "dev", "wifi", "hotspot"]
        if ssid:
            args += ["ssid", ssid]
        if password:
            args += ["password", password]
        return [Step("Start a Wi-Fi hotspot", args)]
    return [Step("Stop the hotspot", ["nmcli", "con", "down", "Hotspot"], ok_codes=(0, 10))]


# ---------------------------------------------------------------- devices on your network

def lan_devices(scan: bool = True) -> list[dict]:
    """Devices your PC can see on the local network (ARP neighbours). A quick ping sweep of the /24 wakes the table up."""
    import concurrent.futures
    import ipaddress
    my = [i for i in interfaces() if i["up"] and i["ipv4"] and i["kind"] in ("Wi-Fi", "Ethernet")]
    if scan and my:
        ip = my[0]["ipv4"][0]
        net = ipaddress.ip_network(ip + "/24", strict=False)
        hosts = [str(h) for h in net.hosts()][:254]

        def ping1(h: str) -> None:
            sh(["ping", "-c", "1", "-W", "1", h], timeout=3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            list(ex.map(ping1, hosts))
    gw = default_gateway().split(" ")[0]
    res = []
    for line in out(["ip", "neigh"], timeout=5).splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+) dev (\S+)(?: lladdr (\S+))? (\S+)", line)
        if not m or not m.group(3) or m.group(4) in ("FAILED", "INCOMPLETE"):
            continue
        ipaddr = m.group(1)
        try:
            name = socket.gethostbyaddr(ipaddr)[0]
        except OSError:
            name = ""
        res.append({"ip": ipaddr, "mac": m.group(3), "name": name, "router": ipaddr == gw, "state": m.group(4)})
    mine = {a for i in my for a in i["ipv4"]}
    for i in my:
        res.append({"ip": i["ipv4"][0], "mac": i["mac"], "name": socket.gethostname() + " (this PC)", "router": False, "state": "self"})
    res.sort(key=lambda d: tuple(int(x) for x in d["ip"].split(".")))
    return [d for d in res if d["ip"] not in mine or d["state"] == "self"]
