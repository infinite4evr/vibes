"""Security checklist with plain-language explanations and one-click fixes."""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field

from . import network, packages, system
from .run import HOME, Step, has, out, read, sh


@dataclass
class Check:
    id: str
    title: str
    level: str  # ok | info | warn | bad
    detail: str
    fix_label: str = ""
    steps: list[Step] = field(default_factory=list)
    goto: str = ""  # panel to open instead of running steps


def firewall() -> Check:
    if not has("ufw"):
        return Check("firewall", "Firewall", "warn", "No firewall tool installed. A firewall blocks other devices on your Wi-Fi from reaching apps on this PC.",
                     "Install and turn on", [Step("Install ufw", ["apt-get", "install", "-y", "ufw"], root=True), *_ufw_enable_steps()])
    r = sh(["ufw", "status"], root=True, timeout=8)
    if r.ok:
        active = "Status: active" in r.out
    else:
        active = bool(re.search(r"^ENABLED=yes", read("/etc/ufw/ufw.conf"), re.M))
    if active:
        return Check("firewall", "Firewall", "ok", "On. Other devices can't reach apps on this PC unless you allow them.")
    return Check("firewall", "Firewall", "bad", "Off. Anything listening on your network (dev servers, databases) can be reached by others on the same Wi-Fi.",
                 "Turn on firewall", _ufw_enable_steps())


def _ufw_enable_steps() -> list[Step]:
    steps = [Step("Block incoming connections by default", ["ufw", "default", "deny", "incoming"], root=True),
             Step("Allow outgoing connections", ["ufw", "default", "allow", "outgoing"], root=True)]
    if ssh_active():
        steps.append(Step("Keep SSH reachable", ["ufw", "allow", "OpenSSH"], root=True, optional=True))
    steps.append(Step("Turn firewall on", ["ufw", "--force", "enable"], root=True))
    return steps


def auto_updates() -> Check:
    if packages.auto_updates_enabled():
        return Check("auto-updates", "Automatic security updates", "ok", "On. Security fixes install by themselves every day.")
    conf = 'APT::Periodic::Update-Package-Lists "1";\\nAPT::Periodic::Unattended-Upgrade "1";\\n'
    return Check("auto-updates", "Automatic security updates", "warn", "Off. Security fixes only arrive when you update by hand.",
                 "Turn on", [Step("Install unattended-upgrades", ["apt-get", "install", "-y", "unattended-upgrades"], root=True, optional=True),
                             Step("Turn on daily security updates", ["bash", "-c", f"printf '{conf}' > /etc/apt/apt.conf.d/20auto-upgrades"], root=True)])


def security_updates(ups: list[packages.Update] | None = None) -> Check:
    ups = ups if ups is not None else packages.pending_updates()
    sec = [u for u in ups if u.security]
    if not sec:
        return Check("sec-updates", "Security updates", "ok", "None waiting.")
    names = ", ".join(u.name for u in sec[:6]) + ("…" if len(sec) > 6 else "")
    return Check("sec-updates", "Security updates", "bad", f"{len(sec)} waiting: {names}", "Install now", packages.security_only_steps())


def ssh_active() -> bool:
    return any(out(["systemctl", "is-active", u]) == "active" for u in ("ssh.service", "ssh.socket", "sshd.service"))


def ssh() -> Check:
    if not ssh_active():
        return Check("ssh", "Remote login (SSH)", "ok", "Off. Nobody can log in to this PC over the network.")
    return Check("ssh", "Remote login (SSH)", "warn", "On. Other computers can try to log in to this one. Turn it off unless you use it.",
                 "Turn off SSH", [Step("Stop SSH and don't start it at boot", ["systemctl", "disable", "--now", "ssh.socket", "ssh.service"], root=True)])


DOCKER_PROCS = {"docker-proxy", "dockerd", "rootlesskit"}
BENIGN = {"avahi-daemon", "systemd-resolve", "cupsd", "cups-browsed", "NetworkManager", "dhclient", "chronyd", "systemd-timesyn", "kdeconnectd", "gsd-sharing"}


def exposed_ports(fw: Check | None = None) -> Check:
    items = [p for p in network.ports() if p.exposed and p.process not in BENIGN and p.port not in (5353, 68, 546)]
    if not items:
        return Check("ports", "Apps open to your network", "ok", "Nothing is listening for other devices.")
    listing = ", ".join(sorted({f"{p.port} ({p.process or '?'})" for p in items}))[:200]
    protected = fw is not None and fw.level == "ok"
    docker = sorted({str(p.port) for p in items if p.process in DOCKER_PROCS})
    if protected and docker:
        return Check("ports", "Apps open to your network", "warn", f"Listening: {listing}. The firewall blocks them from other devices, "
                     f"except Docker's ({', '.join(docker)}): Docker skips the firewall. See the Docker item.", "See ports", goto="network")
    if protected:
        return Check("ports", "Apps open to your network", "info", f"Listening: {listing}. The firewall blocks them from other devices.", goto="network")
    return Check("ports", "Apps open to your network", "warn", f"Reachable from your Wi-Fi: {listing}. Turn on the firewall or bind dev servers to localhost.",
                 "See ports", goto="network")


def screen_lock() -> Check:
    if not has("gsettings"):
        return Check("lock", "Screen lock", "info", "Couldn't check.")
    enabled = out(["gsettings", "get", "org.gnome.desktop.screensaver", "lock-enabled"]) == "true"
    delay = out(["gsettings", "get", "org.gnome.desktop.session", "idle-delay"]).replace("uint32", "").strip()
    mins = int(delay) // 60 if delay.isdigit() else 0
    if enabled and 0 < mins <= 15:
        return Check("lock", "Screen lock", "ok", f"Locks after {mins} min of inactivity.")
    if enabled and mins == 0:
        return Check("lock", "Screen lock", "warn", "The screen never turns off on its own, so it never locks.",
                     "Lock after 5 min", [Step("Blank screen after 5 minutes", ["gsettings", "set", "org.gnome.desktop.session", "idle-delay", "300"])])
    if enabled:
        return Check("lock", "Screen lock", "info", f"Locks after {mins} min. Shorter is safer on a laptop.")
    return Check("lock", "Screen lock", "bad", "Off. Anyone at your desk can use your PC while you're away.",
                 "Turn on", [Step("Lock screen when it blanks", ["gsettings", "set", "org.gnome.desktop.screensaver", "lock-enabled", "true"])])


def auto_login() -> Check:
    conf = read("/etc/gdm3/custom.conf")
    if re.search(r"^\s*AutomaticLoginEnable\s*=\s*true", conf, re.M | re.I):
        return Check("autologin", "Automatic login", "warn", "On. The PC logs in without a password after restart.",
                     "Turn off", [Step("Require password after restart", ["sed", "-i", "s/^\\s*AutomaticLoginEnable\\s*=.*/AutomaticLoginEnable=false/I", "/etc/gdm3/custom.conf"], root=True)])
    return Check("autologin", "Automatic login", "ok", "Off. A password is needed after restart.")


def remote_desktop() -> Check:
    active = out(["systemctl", "--user", "is-active", "gnome-remote-desktop.service"]) == "active"
    if not active:
        return Check("rdp", "Remote desktop sharing", "ok", "Off.")
    return Check("rdp", "Remote desktop sharing", "warn", "On. Others on the network can view or control your screen if they know the password.",
                 "Turn off", [Step("Stop remote desktop", ["systemctl", "--user", "disable", "--now", "gnome-remote-desktop.service"])])


def secure_boot() -> Check:
    if not has("mokutil"):
        return Check("secureboot", "Secure Boot", "info", "Couldn't check (mokutil not installed).")
    state = out(["mokutil", "--sb-state"])
    if "enabled" in state.lower():
        return Check("secureboot", "Secure Boot", "ok", "On. Only trusted software can run while the PC starts.")
    return Check("secureboot", "Secure Boot", "info", "Off. Can be turned on in your BIOS/UEFI settings; some drivers (VirtualBox, NVIDIA) then need signing.")


def disk_encryption() -> Check:
    text = out(["lsblk", "-no", "TYPE,MOUNTPOINTS"])
    if "crypt" in text:
        return Check("encryption", "Disk encryption", "ok", "Your disk is encrypted. A stolen laptop's files can't be read.")
    return Check("encryption", "Disk encryption", "info", "Not encrypted. If the laptop is stolen its files can be read. Encryption can only be set up when reinstalling Ubuntu.")


def reboot_needed() -> Check:
    pkgs = system.reboot_required()
    if pkgs is None:
        return Check("reboot", "Restart needed", "ok", "No pending restart.")
    detail = f"Updates to {', '.join(pkgs[:4])} finish after a restart." if pkgs else "Some updates finish after a restart."
    return Check("reboot", "Restart needed", "warn", detail, "Restart now",
                 [Step("Restart the computer", ["systemctl", "reboot"])])


def _safe(fn, *args):
    """Run an extra check; a broken one is skipped instead of breaking the whole checklist."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return None


def all_checks() -> list[Check]:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_secrets = ex.submit(_safe, secrets_check)   # walks project folders for a few seconds: start it first
        f_docker = ex.submit(_safe, docker_ports)
        fw = firewall()
        checks = [fw, auto_updates(), security_updates(), reboot_needed(), exposed_ports(fw), ssh(), screen_lock(),
                  auto_login(), remote_desktop(), secure_boot(), disk_encryption()]
        dp = f_docker.result()
        extra = [_safe(docker_check, fw, dp) if dp else None, _safe(ssh_settings_check), _safe(apparmor), f_secrets.result()]
    return checks + [c for c in extra if c is not None]


def score(checks: list[Check]) -> int:
    weights = {"ok": 0, "info": 0, "warn": 8, "bad": 20}
    return max(0, 100 - sum(weights[c.level] for c in checks))


# ---------------------------------------------------------------- firewall rules

def ufw_rules() -> list[dict]:
    return parse_ufw_rules(sh(["ufw", "status", "numbered"], root=True, timeout=10).out)


def parse_ufw_rules(text: str) -> list[dict]:
    res = []
    for line in text.splitlines():
        m = re.match(r"\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)(?: IN| OUT)?\s+(.+)$", line)
        if m:
            res.append({"num": int(m.group(1)), "to": m.group(2).strip(), "action": m.group(3), "from": m.group(4).strip()})
    return res


def ufw_allow_steps(port: str, proto: str = "tcp", from_lan_only: bool = True) -> list[Step]:
    if from_lan_only:
        return [Step(f"Allow {port}/{proto} from your local network", ["ufw", "allow", "from", "192.168.0.0/16", "to", "any", "port", port, "proto", proto], root=True),
                Step("…and from 10.x networks", ["ufw", "allow", "from", "10.0.0.0/8", "to", "any", "port", port, "proto", proto], root=True, optional=True)]
    return [Step(f"Allow {port}/{proto} from anywhere", ["ufw", "allow", f"{port}/{proto}"], root=True)]


def ufw_delete_step(num: int) -> Step:
    return Step(f"Delete firewall rule {num}", ["ufw", "--force", "delete", str(num)], root=True)


# ---------------------------------------------------------------- passwords and API keys (see core/secrets.py)

def secrets_check(findings: list | None = None) -> Check:
    from . import secrets
    fs = findings if findings is not None else secrets.scan(budget=3.0)
    level, text = secrets.summary(fs)
    return Check("secrets", "Passwords and API keys", level, text, "Show me" if level in ("bad", "warn") else "", goto="security")


# ---------------------------------------------------------------- Docker publishes ports around the firewall

@dataclass
class DockerPort:
    container: str
    image: str
    host_ip: str
    host_port: str
    container_port: str
    proto: str
    compose_dir: str = ""
    compose_service: str = ""

    @property
    def exposed(self) -> bool:
        return self.host_ip in ("", "0.0.0.0", "::", "[::]", "*")


DB_PORTS = {"5432": "PostgreSQL", "3306": "MySQL", "6379": "Redis", "27017": "MongoDB", "9200": "Elasticsearch", "5984": "CouchDB",
            "11211": "Memcached", "1433": "SQL Server", "8086": "InfluxDB", "9000": "MinIO"}
DAEMON_JSON = "/etc/docker/daemon.json"
# Runs as root: sets (or with an empty value removes) Docker's default address for published ports, keeping other settings.
DAEMON_SET = ("import json,os,sys\n"
              "p,ip=sys.argv[1],sys.argv[2]\n"
              "try:\n    d=json.load(open(p))\n"
              "except FileNotFoundError:\n    d={}\n"
              "except ValueError:\n    sys.exit(p+' is not valid JSON, so it was left alone.')\n"
              "d.pop('ip',None) if not ip else d.__setitem__('ip',ip)\n"
              "os.makedirs(os.path.dirname(p),exist_ok=True)\n"
              "open(p,'w').write(json.dumps(d,indent=2)+'\\n')\n"
              "print('Docker default address:', ip or 'all networks')\n")


def parse_docker_port_list(text: str) -> list[tuple[str, str, str, str]]:
    """'0.0.0.0:5432->5432/tcp, :::5432->5432/tcp, 80/tcp' -> [(host ip, host port, container port, proto)] (published only)."""
    res = []
    for part in (text or "").split(","):
        m = re.match(r"^(?:(.*):)?(\d+(?:-\d+)?)->(\d+(?:-\d+)?)/(\w+)$", part.strip())
        if m:
            res.append((m.group(1) or "", m.group(2), m.group(3), m.group(4)))
    return res


def parse_docker_ps(text: str) -> list[DockerPort]:
    """`docker ps --format '{{json .}}'` -> one DockerPort per published port (IPv4/IPv6 duplicates merged)."""
    res: list[DockerPort] = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        labels = d.get("Labels") or ""
        wd = re.search(r"com\.docker\.compose\.project\.working_dir=([^,]*)", labels)
        svc = re.search(r"com\.docker\.compose\.service=([^,]*)", labels)
        name = (d.get("Names") or "?").split(",")[0]
        seen = set()
        for ip, hp, cp, proto in parse_docker_port_list(d.get("Ports", "")):
            p = DockerPort(name, d.get("Image", ""), ip, hp, cp, proto, wd.group(1) if wd else "", svc.group(1) if svc else "")
            key = (hp, cp, proto, p.exposed)
            if key in seen:
                continue
            seen.add(key)
            res.append(p)
    return res


def docker_ports() -> tuple[str, list[DockerPort]]:
    """(state, ports). state: missing | no-access | not-running | ok."""
    if not has("docker"):
        return "missing", []
    r = sh(["docker", "ps", "--format", "{{json .}}"], timeout=8)
    if not r.ok:
        return ("no-access" if "permission denied" in r.err.lower() else "not-running"), []
    return "ok", parse_docker_ps(r.out)


def docker_default_ip() -> str:
    try:
        return str(json.loads(read(DAEMON_JSON) or "{}").get("ip", ""))
    except ValueError:
        return ""


def docker_check(fw: Check | None = None, state_ports: tuple[str, list[DockerPort]] | None = None) -> Check | None:
    state, ports = state_ports or docker_ports()
    title = "Docker and the firewall"
    if state == "missing":
        return None
    if state == "no-access":
        return Check("docker", title, "info", "Couldn't list your containers: your account isn't allowed to talk to Docker.")
    if state == "not-running":
        return Check("docker", title, "ok", "Docker isn't running, so no containers can be reached.")
    exposed = [p for p in ports if p.exposed]
    if not exposed:
        return Check("docker", title, "ok", "Your containers only accept connections from this PC." if ports else "No container shares a port.")
    listing = ", ".join(sorted({f"{p.host_port} ({p.container})" for p in exposed}))[:200]
    dbs = sorted({DB_PORTS[p.container_port] for p in exposed if p.container_port in DB_PORTS})
    level = "bad" if dbs else "warn"
    fw_on = fw is not None and fw.level == "ok"
    why = ("The firewall is on but does NOT block these: Docker adds its own network rules that skip it."
           if fw_on else "Other devices on your Wi-Fi can connect to them.")
    db = f" Databases ({', '.join(dbs)}) often have default passwords." if dbs else ""
    return Check("docker", title, level, f"Reachable from other devices: {listing}. {why}{db} Bind them to 127.0.0.1 so only this PC can connect.",
                 "Only this PC", docker_localhost_steps(True))


def docker_localhost_steps(on: bool = True) -> list[Step]:
    title = "Make Docker share ports only with this PC (127.0.0.1) by default" if on else "Let Docker share ports with your network again"
    return [Step(title, ["python3", "-c", DAEMON_SET, DAEMON_JSON, "127.0.0.1" if on else ""], root=True),
            Step("Restart Docker so containers pick it up (running containers restart)", ["systemctl", "restart", "docker"], root=True)]


def docker_fix_text(ports: list[DockerPort]) -> str:
    """Plain-English instructions for each exposed container."""
    lines = ["Change how each container shares its port so it only listens on this PC (127.0.0.1).", ""]
    by_c: dict[str, list[DockerPort]] = {}
    for p in ports:
        if p.exposed:
            by_c.setdefault(p.container, []).append(p)
    for name, ps in sorted(by_c.items()):
        p0 = ps[0]
        maps = [(p.host_port, p.container_port) for p in ps]
        lines.append(f"■ {name}  ({p0.image})")
        if p0.compose_dir:
            lines.append(f"  Started by Docker Compose from {p0.compose_dir}")
            lines.append(f"  In docker-compose.yml (or compose.yaml), under the service \"{p0.compose_service or name}\", change:")
            for h, c in maps:
                lines.append(f"      - \"{h}:{c}\"   →   - \"127.0.0.1:{h}:{c}\"")
            lines.append(f"  Then run:  cd {p0.compose_dir} && docker compose up -d")
        else:
            lines.append("  Re-create it with the port bound to this PC only:")
            for h, c in maps:
                lines.append(f"      -p {h}:{c}   →   -p 127.0.0.1:{h}:{c}")
        lines.append("")
    lines.append("Or use \"Only this PC\" to make 127.0.0.1 Docker's default for every container (set in /etc/docker/daemon.json).")
    lines.append("Your apps on this PC keep working at localhost:PORT; only other devices (like your phone) lose access.")
    return "\n".join(lines)


# ---------------------------------------------------------------- SSH server settings

SSHD = "/usr/sbin/sshd"
HARDEN_FILE = "/etc/ssh/sshd_config.d/00-pc-hardening.conf"   # 00-: sshd keeps the FIRST value it reads for each setting
SSHD_DEFAULTS = {"port": "22", "passwordauthentication": "yes", "permitrootlogin": "prohibit-password", "permitemptypasswords": "no",
                 "kbdinteractiveauthentication": "yes", "usepam": "no", "pubkeyauthentication": "yes", "maxauthtries": "6"}


def ssh_server_installed() -> bool:
    return os.path.exists(SSHD) or has("sshd")


def parse_sshd_T(text: str) -> dict:
    """`sshd -T` output ("key value" per line, keys lower-case)."""
    res: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            res.setdefault(parts[0].lower(), parts[1].strip())
    return res


def parse_sshd_config(path: str = "/etc/ssh/sshd_config", reader=read, globber=glob.glob, _depth: int = 0,
                      _into: dict | None = None) -> dict:
    """Effective global settings from sshd_config + its Include files. Like sshd, the first value wins; Match blocks are skipped."""
    res: dict[str, str] = {} if _into is None else _into
    if _depth > 8:
        return res
    for raw in reader(path).splitlines():
        line = raw.split("#", 1)[0].strip()
        m = re.match(r"(\S+?)(?:\s*=\s*|\s+)(.*)$", line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip().strip('"')
        if key == "match":
            break
        if key == "include":
            for pat in val.split():
                pat = pat if pat.startswith("/") else "/etc/ssh/" + pat
                for f in sorted(globber(pat)):
                    parse_sshd_config(f, reader, globber, _depth + 1, res)
            continue
        res.setdefault(key, val)
    return res


def sshd_settings() -> dict:
    if os.geteuid() == 0 and ssh_server_installed():
        r = sh([SSHD if os.path.exists(SSHD) else "sshd", "-T"], timeout=8)
        if r.ok and "port " in r.out:
            return {**parse_sshd_T(r.out), "source": "sshd -T"}
    return {**SSHD_DEFAULTS, **parse_sshd_config(), "source": "config files"}


def authorized_keys_count(home=None) -> int:
    try:
        text = ((home or HOME) / ".ssh/authorized_keys").read_text(errors="replace")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))


def ssh_hardening(settings: dict | None = None) -> list[Check]:
    """One item per setting that matters, for the SSH server section."""
    s = settings if settings is not None else sshd_settings()
    yes = lambda k: s.get(k, SSHD_DEFAULTS.get(k, "no")).lower() == "yes"  # noqa: E731
    items = []
    pw = yes("passwordauthentication") or (yes("kbdinteractiveauthentication") and yes("usepam"))
    items.append(Check("ssh-password", "Password login", "warn" if pw else "ok",
                       "On. Anyone who can reach this PC can try to guess your password. SSH keys are much safer."
                       if pw else "Off. Only SSH keys can log in."))
    root = s.get("permitrootlogin", "prohibit-password").lower()
    items.append(Check("ssh-root", "Logging in as root (the admin account)", "bad" if root == "yes" else "ok",
                       {"yes": "Allowed with a password. Attackers try 'root' first.", "no": "Not allowed.",
                        "forced-commands-only": "Only for pre-set commands with a key."}.get(root, "Only with an SSH key (the normal setting).")))
    if yes("permitemptypasswords"):
        items.append(Check("ssh-empty", "Accounts without a password", "bad", "Allowed to log in over SSH with an empty password!"))
    port = s.get("port", "22")
    items.append(Check("ssh-port", "Port", "info", f"{port}. " + ("The standard port; changing it only hides SSH from simple scanners."
                                                              if port == "22" else "Not the standard port.")))
    return items


def ssh_harden_steps(keys: int | None = None) -> list[Step]:
    keys = authorized_keys_count() if keys is None else keys
    lines = ["# Added by PC Command Center: safer SSH server settings. Delete this file to undo.",
             "# Named 00- on purpose: SSH uses the first value it reads for each setting.",
             "PermitRootLogin no", "PermitEmptyPasswords no", "MaxAuthTries 4"]
    if keys:
        lines += ["PasswordAuthentication no", "KbdInteractiveAuthentication no"]
    content = "\n".join(lines) + "\n"
    script = ('f="$1"; printf "%s" "$2" > "$f" && chmod 644 "$f" || exit 1; '
              f'if ! {SSHD} -t; then rm -f "$f"; echo "SSH did not accept the new settings, so they were removed again."; exit 1; fi; '
              'echo "Saved $f"')
    return [Step("Save safer SSH settings (checked before use)", ["bash", "-c", script, "pc-ssh", HARDEN_FILE, content], root=True),
            Step("Apply them (reloads the SSH server if it's running)", ["systemctl", "try-reload-or-restart", "ssh.service"], root=True, optional=True)]


def ssh_unharden_steps() -> list[Step]:
    return [Step("Remove PC Command Center's SSH settings", ["rm", "-f", HARDEN_FILE], root=True),
            Step("Apply (reloads the SSH server if it's running)", ["systemctl", "try-reload-or-restart", "ssh.service"], root=True, optional=True)]


def ssh_off_steps() -> list[Step]:
    return [Step("Stop SSH and don't start it at boot", ["systemctl", "disable", "--now", "ssh.socket", "ssh.service"], root=True)]


def ssh_settings_check() -> Check | None:
    if not ssh_active():
        return None
    todo = [c for c in ssh_hardening() if c.level in ("bad", "warn")]
    if not todo:
        return Check("ssh-settings", "SSH server settings", "ok", "Passwords can't be used to log in and root login is off.")
    level = "bad" if any(c.level == "bad" for c in todo) else "warn"
    keys = authorized_keys_count()
    detail = "; ".join(f"{c.title}: {c.detail.split('.')[0].lower()}" for c in todo) + "."
    if not keys:
        detail += " Password login stays on until you add an SSH key, so you can't lock yourself out."
    return Check("ssh-settings", "SSH server settings", level, detail, "Make safer", ssh_harden_steps(keys))


def parse_last_remote(text: str) -> list[dict]:
    """Remote logins from `last -i -w`: lines whose 'from' column is a real IP address."""
    res = []
    for line in text.splitlines():
        if not line.strip() or line.startswith(("wtmp", "reboot", "shutdown")):
            continue
        parts = line.split()
        ip = next((p for p in parts[1:4] if re.fullmatch(r"\d+\.\d+\.\d+\.\d+|[0-9a-fA-F]*:[0-9a-fA-F:]+", p)), "")
        if ip and ip not in ("0.0.0.0", "::", "::1", "127.0.0.1"):
            res.append({"user": parts[0], "from": ip, "when": line.split(ip, 1)[1].strip()})
    return res


def remote_logins() -> list[dict]:
    return parse_last_remote(out(["last", "-i", "-w", "-n", "300"], timeout=10))


# ---------------------------------------------------------------- AppArmor

def parse_aa_profiles(text: str) -> dict:
    """/sys/kernel/security/apparmor/profiles ("name (mode)" per line) -> {mode: count}."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = re.search(r"\((\w+)\)\s*$", line)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def parse_aa_status(text: str) -> dict:
    """`aa-status --json` or plain `aa-status` output -> {mode: count}."""
    t = text.strip()
    counts: dict[str, int] = {}
    if t.startswith("{"):
        try:
            for mode in (json.loads(t).get("profiles") or {}).values():
                counts[mode] = counts.get(mode, 0) + 1
        except ValueError:
            pass
        return counts
    for m in re.finditer(r"^(\d+) profiles are in (\w+) mode", t, re.M):
        counts[m.group(2)] = int(m.group(1))
    return counts


def apparmor_status() -> dict:
    enabled = None
    v = read("/sys/module/apparmor/parameters/enabled").strip()
    if v:
        enabled = v.upper().startswith("Y")
    elif has("aa-enabled"):
        r = sh(["aa-enabled"], timeout=5)
        enabled = r.out.strip().lower().startswith("yes") if (r.out or r.ok) else None
    counts = parse_aa_profiles(read("/sys/kernel/security/apparmor/profiles"))
    source = "kernel" if counts else ""
    if not counts and os.geteuid() == 0 and has("aa-status"):
        counts = parse_aa_status(out(["aa-status", "--json"], timeout=10))
        source = "aa-status" if counts else ""
    return {"enabled": enabled, "counts": counts, "source": source, "boot_off": bool(re.search(r"\bapparmor=0\b", read("/proc/cmdline"))),
            "installed": has("aa-status") or os.path.exists("/etc/apparmor.d")}


def apparmor(st: dict | None = None) -> Check:
    st = st or apparmor_status()
    title = "App protection (AppArmor)"
    counts = st["counts"]
    if st["enabled"] is None:
        return Check("apparmor", title, "info", "Couldn't check. AppArmor limits what apps like your browser can touch if they get hacked.")
    if not st["enabled"]:
        if st["boot_off"]:
            return Check("apparmor", title, "warn", "Turned off at startup (apparmor=0 in the boot settings). Apps have no extra safety limits.")
        return Check("apparmor", title, "warn", "Off. It limits what apps can touch if they get hacked; Ubuntu normally has it on.")
    if counts:
        enforce, complain = counts.get("enforce", 0), counts.get("complain", 0)
        if enforce == 0:
            return Check("apparmor", title, "warn", "On, but no app rules are loaded.", "Load the rules",
                         [Step("Start AppArmor and load its rules", ["systemctl", "enable", "--now", "apparmor.service"], root=True)])
        return Check("apparmor", title, "ok", f"On. {enforce} app rule sets are enforced" + (f", {complain} only log problems" if complain else "") + ".")
    return Check("apparmor", title, "ok", "On. Apps like your browser are limited in what they can touch if they get hacked.")
