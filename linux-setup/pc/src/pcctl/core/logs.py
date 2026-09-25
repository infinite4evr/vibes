"""System logs: errors grouped by where they came from, crash reports, per-boot history."""

from __future__ import annotations

import glob
import json
import os
import re
import time
from dataclasses import dataclass

from .run import Step, out, read, sh

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


# ---------------------------------------------------------------- kernel messages (hardware, drivers, USB)

# (pattern, plain explanation, harmless?) - first match wins, so specific patterns come first.
KERNEL_EXPLAIN: list[tuple[str, str, bool]] = [
    (r"Out of memory: Killed process|invoked oom-killer|oom-kill:",
     "The PC ran out of memory and Linux closed an app to recover. Close big apps or browser tabs, or add more swap.", False),
    (r"segfault at|traps: .*general protection|trap invalid opcode",
     "An app crashed (it touched memory it shouldn't). See the Crashes tab; updating the app usually helps.", False),
    (r"soft lockup|hard LOCKUP|blocked for more than \d+ seconds|hung_task|rcu_.*stall",
     "Part of the system froze for a while. If the PC hung at that moment, this is why; usually a driver or a slow/failing disk.", False),
    (r"mce: \[Hardware Error\]|Machine check events logged|Hardware Error",
     "The processor reported (and fixed) a hardware error. One now and then is OK; many can mean overheating or bad memory.", False),
    (r"critical temperature reached|Package temperature above threshold|Core temperature above threshold|cpu clock throttled",
     "The CPU got too hot and slowed itself down to stay safe. Check the fan and vents.", False),
    (r"EXT4-fs error|BTRFS (error|critical)|I/O error|critical medium error|Buffer I/O error|failed command: (READ|WRITE)|hard resetting link",
     "A disk had trouble reading or writing. Once can be a glitch; repeated errors can mean a failing disk or cable. Back up, then check disk health on the Storage page.", False),
    (r"nvme\S* .*(timeout|I/O \d+ QID|controller is down|Abort status)",
     "The SSD didn't answer in time. If it happens often, update the SSD's firmware (Maintenance → Firmware) or the BIOS.", False),
    (r"NVRM: Xid",
     "The NVIDIA graphics card reported an error. An occasional one is OK; many in a row can mean a driver problem or an overheating GPU.", False),
    (r"GPU HANG|gpu hang|ring \S+ timeout|GPU reset|amdgpu.*(timeout|reset)",
     "The graphics chip froze for a moment and was reset. If the screen froze or flickered, this is why; updates often fix it.", False),
    (r"iwlwifi.*(Microcode SW error|firmware crashed|FW error|Hardware error)|ath1\dk.*firmware crashed|mt7\d.*(timeout|reset)",
     "The Wi-Fi chip's firmware crashed and was restarted. If Wi-Fi drops a lot, installing updates (linux-firmware, a newer kernel) usually fixes it.", False),
    (r"usb \S+: (device descriptor read|device not accepting address|unable to enumerate|can't set config|Cannot enable)",
     "A USB device didn't answer properly when it was plugged in. Usually a flaky cable, a hub without enough power, or a worn port. Try another port or cable.", False),
    (r"usb \S+: (new .*USB device|New USB device|Product:|Manufacturer:|SerialNumber:|USB disconnect)|usbcore: registered",
     "A USB device was plugged in or removed. Just information.", True),
    (r"ACPI BIOS Error|ACPI Error|ACPI Warning|AE_NOT_FOUND|AE_ALREADY_EXISTS",
     "Your BIOS has small mistakes in its power-management tables. Linux works around them. Harmless and very common.", True),
    (r"\[Firmware (Bug|Warn|Info)\]",
     "The BIOS/firmware reports something slightly wrong and Linux corrects for it. Harmless.", True),
    (r"Direct firmware load for .* failed|no suitable firmware found|firmware: failed to load",
     "A driver looked for an optional firmware file, then used another one. Harmless if the device works.", True),
    (r"Bluetooth: hci\d+: .*(tx timeout|Reading supported features failed|command .* failed|Opcode .* failed)",
     "The Bluetooth chip didn't answer a command. If Bluetooth misbehaves, turn it off and on again.", False),
    (r"Bluetooth: hci\d+:",
     "Chatter from the Bluetooth chip's firmware while it starts. Harmless unless Bluetooth actually misbehaves.", True),
    (r"PCIe Bus Error.*Corrected|AER: Corrected error|AER:.*severity=Corrected",
     "The PCIe link fixed a small transfer error by itself. Common on some laptops and harmless unless you also see freezes.", True),
    (r'apparmor="(DENIED|AUDIT)"',
     "AppArmor (Ubuntu's app sandbox) stopped an app from doing something it isn't allowed to. Usually harmless (snaps poke around a lot).", True),
    (r'apparmor="STATUS"|audit: type=|kauditd_printk_skb',
     "Security-audit bookkeeping (AppArmor profiles loaded). Harmless.", True),
    (r"taints kernel|module verification failed|Disabling lock debugging due to kernel taint|loading out-of-tree module",
     "A driver that isn't part of Ubuntu's kernel was loaded (NVIDIA, VirtualBox, …). Normal when you use such drivers.", True),
    (r"Lockdown: .* is restricted|kernel_lockdown",
     "Secure Boot stopped a program from poking at kernel memory. Harmless.", True),
    (r"integrity: Problem loading X\.509|Couldn't get size: 0x800000000000000e|MODSIGN",
     "A Secure Boot certificate from the BIOS couldn't be read. Harmless.", True),
    (r"Unknown key (pressed|released)|atkbd .*Use 'setkeycodes'",
     "A special keyboard key sent a code Linux doesn't know. Harmless.", True),
    (r"loop\d+: detected capacity change|squashfs",
     "A snap app package was opened. Harmless.", True),
    (r"clocksource|Marking TSC unstable|tsc: ",
     "The kernel picked a different internal clock. Harmless (common in virtual machines).", True),
    (r"Link is (Up|Down)|link (up|down)|NIC Link is|deauthenticating|disassociated|authenticate with|associated",
     "A network connection went up or down (cable plugged/unplugged, Wi-Fi reconnecting).", True),
    (r"snd_hda_intel.*(spurious response|azx_get_response timeout|no codecs)|sof-audio.*(error|failed)",
     "A hiccup from the sound chip. Harmless unless sound doesn't work.", True),
    (r"ucsi|typec|UCSI",
     "USB-C controller firmware messages. Usually harmless.", True),
    (r"tpm tpm0|tpm_crb|TPM",
     "The TPM security chip's firmware has a small quirk. Harmless.", True),
    (r"perf: interrupt took too long|hogged CPU|workqueue: .* consumed",
     "A driver task took a little longer than expected. Harmless.", True),
    (r"Spectre|Meltdown|MDS:|mitigation|Mitigation|vulnerable|RETBleed|SRBDS|GDS:",
     "Information about the CPU security protections Linux turned on.", True),
    (r"PM: suspend (entry|exit)|PM: (hibernation|resume)|ACPI: PM: (Waking|Preparing|Low-level resume|Saving platform)",
     "The PC went to sleep or woke up.", True),
]

KERNEL_CATEGORIES: list[tuple[str, str, str]] = [  # (name, icon, pattern)
    ("Apps that crashed", "computer-fail-symbolic", r"segfault|traps:|general protection|invalid opcode"),
    ("Memory", "media-flash-symbolic", r"Out of memory|oom|\bRAS\b|EDAC|Memory"),
    ("Security (AppArmor, Secure Boot)", "security-high-symbolic", r"apparmor|audit|Lockdown|integrity:|secureboot|Secure boot|MODSIGN"),
    ("Bluetooth", "bluetooth-symbolic", r"Bluetooth|btusb|btintel|btrtl|btmtk|hci\d"),
    ("USB", "media-removable-symbolic", r"^usb |usbcore|xhci|ehci|uhci|usbhid|^hub |cdc_|ucsi|typec|thunderbolt|USB"),
    ("Graphics", "video-display-symbolic", r"i915|xe \d|amdgpu|radeon|nouveau|nvidia|NVRM|\[drm\]|drm:|simpledrm|fbcon|efifb|GPU"),
    ("Wi-Fi and network", "network-wireless-symbolic",
     r"iwlwifi|iwlmvm|ath\d+k|rtw\d*|rtl\d|r8169|r8152|mt7\d|brcm|wlp|wlan|wlo|eth\d|enp|eno|cfg80211|mac80211|e1000e|igc|wireguard|IPv6|nf_|netfilter"),
    ("Disks and storage", "drive-harddisk-symbolic", r"nvme|ata\d|\bsd[a-z]\b|scsi|EXT4|BTRFS|XFS|zfs|I/O error|blk_|dm-\d|loop\d|md\d|mmc|squashfs|fstrim"),
    ("Sound", "audio-card-symbolic", r"snd_|sof-|sof_|hda|HDA|audio"),
    ("Firmware and BIOS", "application-x-firmware-symbolic", r"ACPI|Firmware|BIOS|DMI:|efi|EFI|tpm|TPM|firmware"),
    ("Processor and temperature", "power-profile-performance-symbolic",
     r"mce|Hardware Error|microcode|CPU\d|cpu\d|thermal|clocksource|tsc|smpboot|x86|Spectre|Meltdown|mitigation|Mitigation"),
    ("Keyboard, mouse, touchpad", "input-keyboard-symbolic", r"input:|hid|atkbd|i8042|psmouse|touchpad|elan|synaptics|HID"),
    ("Sleep and power", "weather-clear-night-symbolic", r"PM:|suspend|resume|hibernat|battery|power_supply|button|lid"),
]


def kernel_explain(msg: str) -> tuple[str, bool] | None:
    """(plain explanation, harmless?) for well-known kernel messages, or None."""
    for pat, text, harmless in KERNEL_EXPLAIN:
        if re.search(pat, msg):
            return text, harmless
    return None


def kernel_category(msg: str) -> tuple[str, str]:
    for name, icon, pat in KERNEL_CATEGORIES:
        if re.search(pat, msg):
            return name, icon
    return "Other", "application-x-addon-symbolic"


def kernel_entries(since: str = "boot", max_priority: int = 4, limit: int = 3000, grep: str = "") -> list[LogLine]:
    """Kernel messages (like dmesg) from the journal: hardware, drivers, USB, disks."""
    return entries(since=since, max_priority=max_priority, kernel=True, limit=limit, grep=grep)


def kernel_groups(lines: list[LogLine], hide_harmless: bool = True) -> list[dict]:
    """Kernel lines grouped by area (USB, Graphics, …) with counts, worst level and the explanation of each line."""
    groups: dict[str, dict] = {}
    for ln in lines:
        ex = kernel_explain(ln.message)
        if hide_harmless and ex and ex[1]:
            continue
        name, icon = kernel_category(ln.message)
        g = groups.setdefault(name, {"name": name, "icon": icon, "count": 0, "worst": 7, "last": 0.0, "lines": [], "harmless": 0})
        g["count"] += 1
        g["worst"] = min(g["worst"], ln.priority)
        g["last"] = max(g["last"], ln.time)
        g["harmless"] += 1 if ex and ex[1] else 0
        g["lines"].append((ln, ex))
    for g in groups.values():
        g["lines"].sort(key=lambda p: -p[0].time)
    return sorted(groups.values(), key=lambda g: (g["worst"], g["name"] == "Other", -g["count"]))


# ---------------------------------------------------------------- live follow

def follow_cmd(max_priority: int = 6, kernel: bool = False, grep: str = "", backlog: int = 0) -> list[str]:
    """journalctl command that prints new messages as JSON lines as they happen (read it line by line)."""
    args = ["journalctl", "-f", "-o", "json", "--no-pager", "-n", str(backlog), "-p", str(max_priority)]
    if kernel:
        args.append("-k")
    if grep:
        args += ["-g", grep, "--case-sensitive=false"]
    return args


# ---------------------------------------------------------------- journal size

JOURNALD_DROPIN = "/etc/systemd/journald.conf.d/pc-size.conf"
SIZE_UNITS = {"": 1, "B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}


def parse_size(text: str) -> int | None:
    """'1.2G', '512.0M', '8K', '0B', '1.5 GiB' -> bytes."""
    m = re.match(r"\s*([\d.]+)\s*([KMGTP]?)(?:i?B)?\s*$", text.strip(), re.I)
    if not m:
        return None
    return int(float(m.group(1)) * SIZE_UNITS[m.group(2).upper()])


def parse_disk_usage(text: str) -> int | None:
    """`journalctl --disk-usage` -> bytes."""
    m = re.search(r"take up ([\d.]+\s*[KMGTP]?(?:i?B)?) ", text + " ")
    return parse_size(m.group(1)) if m else None


def disk_usage() -> int | None:
    r = sh(["journalctl", "--disk-usage"], timeout=20)
    size = parse_disk_usage(r.out + r.err)
    if size is None:
        r = sh(["journalctl", "--disk-usage"], root=True, timeout=20)
        size = parse_disk_usage(r.out + r.err)
    return size


def parse_journald_conf(text: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        if section == "[Journal]" and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def journald_settings() -> dict[str, str]:
    """Effective journald settings from journald.conf and its drop-ins (later files win)."""
    vals = parse_journald_conf(read("/etc/systemd/journald.conf"))
    drop: dict[str, str] = {}
    for d in ("/usr/lib/systemd/journald.conf.d", "/run/systemd/journald.conf.d", "/etc/systemd/journald.conf.d"):
        for f in glob.glob(os.path.join(d, "*.conf")):
            drop[os.path.basename(f)] = f
    for name in sorted(drop):
        vals.update(parse_journald_conf(read(drop[name])))
    return vals


def journal_info() -> dict:
    """Size, where logs are kept and the limit in force."""
    s = journald_settings()
    storage = s.get("Storage", "auto").lower()
    persistent = storage == "persistent" or (storage == "auto" and os.path.isdir("/var/log/journal"))
    return {"size": disk_usage(), "persistent": persistent, "storage": storage, "max_use": s.get("SystemMaxUse", ""),
            "max_age": s.get("MaxRetentionSec", ""), "ours": os.path.exists(JOURNALD_DROPIN)}


def vacuum_steps(size_mb: int | None = None, days: int | None = None) -> list[Step]:
    """Delete old logs now so only the newest `size_mb` / last `days` remain."""
    steps = []
    if size_mb:
        steps.append(Step(f"Delete old logs, keep the newest {size_mb} MB", ["journalctl", f"--vacuum-size={size_mb}M"], root=True))
    if days:
        steps.append(Step(f"Delete logs older than {days} days", ["journalctl", f"--vacuum-time={days}d"], root=True))
    return steps


def limit_steps(size_mb: int | None = None, days: int | None = None) -> list[Step]:
    """Keep the journal under a size (and/or age) from now on, with a journald drop-in. Both None removes our limit."""
    restart = Step("Restart the log service so it takes effect", ["systemctl", "restart", "systemd-journald"], root=True)
    if not size_mb and not days:
        return [Step("Remove the size limit (back to Ubuntu's default)", ["rm", "-f", JOURNALD_DROPIN], root=True), restart]
    lines = ["# Added by PC Command Center: keep system logs small", "[Journal]"]
    if size_mb:
        lines.append(f"SystemMaxUse={size_mb}M")
    if days:
        lines.append(f"MaxRetentionSec={days}day")
    printf = 'printf "%s\\n" ' + " ".join(f'"{ln}"' for ln in lines)  # plain text only, so double quotes are safe and read cleanly
    return [Step("Save the limit", ["bash", "-c", f"mkdir -p {os.path.dirname(JOURNALD_DROPIN)} && {printf} > {JOURNALD_DROPIN}"], root=True),
            restart, *vacuum_steps(size_mb, days)]
