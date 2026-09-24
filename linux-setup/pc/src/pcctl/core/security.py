"""Security checklist with plain-language explanations and one-click fixes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import network, packages, system
from .run import Step, has, out, read, sh


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


BENIGN = {"avahi-daemon", "systemd-resolve", "cupsd", "cups-browsed", "NetworkManager", "dhclient", "chronyd", "systemd-timesyn", "kdeconnectd", "gsd-sharing"}


def exposed_ports(fw: Check | None = None) -> Check:
    items = [p for p in network.ports() if p.exposed and p.process not in BENIGN and p.port not in (5353, 68, 546)]
    if not items:
        return Check("ports", "Apps open to your network", "ok", "Nothing is listening for other devices.")
    listing = ", ".join(sorted({f"{p.port} ({p.process or '?'})" for p in items}))[:200]
    protected = fw is not None and fw.level == "ok"
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


def all_checks() -> list[Check]:
    fw = firewall()
    checks = [fw, auto_updates(), security_updates(), reboot_needed(), exposed_ports(fw), ssh(), screen_lock(),
              auto_login(), remote_desktop(), secure_boot(), disk_encryption()]
    return checks


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
