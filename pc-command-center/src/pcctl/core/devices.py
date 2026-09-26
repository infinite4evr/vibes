"""What's plugged in and built in: USB, PCI cards/chips, sound, Bluetooth, screens, cameras, memory modules.

Read-only. Each source degrades on its own (missing tool → a note, not an error).
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

from .run import HOME, Step, has, out, py_step, read, sh

# ---------------------------------------------------------------- USB

USB_SKIP = re.compile(r"root hub|^Linux Foundation", re.I)


def parse_lsusb(text: str) -> list[dict]:
    """`lsusb` -> [{bus, dev, id, name}], without the built-in root hubs."""
    res = []
    for line in text.splitlines():
        m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s*(.*)$", line.strip())
        if not m:
            continue
        name = m.group(4).strip()
        if USB_SKIP.search(name):
            continue
        res.append({"bus": int(m.group(1)), "dev": int(m.group(2)), "id": m.group(3).lower(), "name": name or f"USB device {m.group(3)}"})
    return res


def usb_sysfs(root: str = "/sys/bus/usb/devices") -> list[dict]:
    res = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        base = os.path.basename(d)
        if ":" in base or base.startswith("usb"):
            continue  # interfaces and root hubs
        vid, pid = read(os.path.join(d, "idVendor")).strip(), read(os.path.join(d, "idProduct")).strip()
        if not vid:
            continue
        name = " ".join(x for x in (read(os.path.join(d, "manufacturer")).strip(), read(os.path.join(d, "product")).strip()) if x)
        res.append({"bus": 0, "dev": 0, "id": f"{vid}:{pid}", "name": name or f"USB device {vid}:{pid}"})
    return res


def usb_devices() -> tuple[list[dict], str]:
    if has("lsusb"):
        return parse_lsusb(out(["lsusb"], timeout=8)), ""
    items = usb_sysfs()
    return items, "" if items else "No USB devices found (or this is a virtual machine)."


def usb_kind(name: str) -> str:
    n = name.lower()
    for words, kind in ((("bluetooth",), "Bluetooth adapter"), (("webcam", "camera", "cam "), "Camera"),
                        (("fingerprint", "goodix", "synaptics fp", "validity"), "Fingerprint reader"),
                        (("receiver", "mouse", "keyboard", "unifying", "bolt"), "Mouse / keyboard"),
                        (("hub",), "USB hub"), (("audio", "headset", "dac", "microphone", "yeti"), "Sound"),
                        (("wireless", "wlan", "wi-fi", "802.11", "ethernet", "lan"), "Network"),
                        (("mass storage", "flash", "sandisk", "kingston", "card reader", "ssd", "disk"), "Storage"),
                        (("controller", "gamepad", "xbox", "dualsense", "dualshock"), "Game controller"),
                        (("printer", "scanner"), "Printer / scanner"), (("phone", "android", "iphone", "pixel"), "Phone")):
        if any(w in n for w in words):
            return kind
    return ""


# ---------------------------------------------------------------- PCI

PCI_GROUPS = [
    ("Graphics", ("VGA compatible controller", "3D controller", "Display controller")),
    ("Network", ("Network controller", "Ethernet controller")),
    ("Sound", ("Audio device", "Multimedia audio controller")),
    ("Storage", ("Non-Volatile memory controller", "SATA controller", "RAID bus controller", "Mass storage controller", "IDE interface")),
    ("USB & Thunderbolt", ("USB controller", "Thunderbolt", "System peripheral")),
]
PCI_PLAIN = {"Network controller": "Wi-Fi", "Ethernet controller": "Wired network", "VGA compatible controller": "Graphics",
             "3D controller": "Graphics (extra GPU)", "Display controller": "Graphics", "Non-Volatile memory controller": "NVMe SSD",
             "SATA controller": "SATA disks", "USB controller": "USB ports", "Audio device": "Sound", "Multimedia audio controller": "Sound"}


def parse_lspci_mm(text: str) -> list[dict]:
    """`lspci -mm` -> [{slot, cls, vendor, device, group, plain}]."""
    res = []
    for line in text.splitlines():
        m = re.match(r"(\S+)\s+(.*)$", line.strip())
        if not m:
            continue
        q = re.findall(r'"([^"]*)"', m.group(2))
        if len(q) < 3:
            continue
        cls, vendor, device = q[0], q[1], q[2]
        vendor = re.sub(r"\s*(Corporation|Co\.?,? Ltd\.?|Semiconductor|Electronics|Technology|Inc\.?|Incorporated|\[AMD/ATI\])\b\.?", "", vendor).strip(" ,")
        group = next((g for g, classes in PCI_GROUPS if cls in classes), "Chipset")
        res.append({"slot": m.group(1), "cls": cls, "vendor": vendor, "device": device, "group": group, "plain": PCI_PLAIN.get(cls, cls)})
    return res


# ---------------------------------------------------------------- sound

def parse_pactl_json(text: str, default: str = "") -> list[dict]:
    """`pactl -f json list sinks|sources` -> [{name, description, state, default, bus}] (monitors skipped)."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    res = []
    for d in data if isinstance(data, list) else []:
        name = str(d.get("name", ""))
        props = d.get("properties") or {}
        if name.endswith(".monitor") or props.get("device.class") == "monitor":
            continue
        res.append({"name": name, "description": d.get("description") or props.get("device.description") or name,
                    "state": str(d.get("state", "")).lower(), "default": bool(default) and name == default,
                    "bus": props.get("device.bus", ""), "port": (d.get("active_port") or "")})
    return res


def parse_wpctl_status(text: str) -> dict[str, list[dict]]:
    """`wpctl status` -> {"sinks": [...], "sources": [...]} for the Audio section."""
    res: dict[str, list[dict]] = {"sinks": [], "sources": []}
    section, sub = "", ""
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith(("│", "├", "└")):
            section = line.strip().split()[0] if line.strip() else ""
            sub = ""
            continue
        clean = line.replace("│", " ").replace("├", " ").replace("└", " ").replace("─", " ")
        m = re.match(r"\s*(Sinks|Sources|Devices|Sink endpoints|Source endpoints|Streams|Filters|Clients):\s*$", clean)
        if m:
            sub = m.group(1)
            continue
        if section != "Audio" or sub not in ("Sinks", "Sources"):
            continue
        m = re.match(r"\s*(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[[^\]]*\])?\s*$", clean)
        if m:
            res["sinks" if sub == "Sinks" else "sources"].append({"name": m.group(2), "description": m.group(3).strip(), "state": "",
                                                                  "default": bool(m.group(1)), "bus": "", "port": ""})
    return res


def sound_devices() -> tuple[list[dict], list[dict], str]:
    if has("pactl"):
        ds, dsrc = out(["pactl", "get-default-sink"], timeout=5), out(["pactl", "get-default-source"], timeout=5)
        sinks = parse_pactl_json(out(["pactl", "-f", "json", "list", "sinks"], timeout=8), ds)
        sources = parse_pactl_json(out(["pactl", "-f", "json", "list", "sources"], timeout=8), dsrc)
        if sinks or sources:
            return sinks, sources, ""
    if has("wpctl"):
        st = parse_wpctl_status(out(["wpctl", "status"], timeout=8))
        if st["sinks"] or st["sources"]:
            return st["sinks"], st["sources"], ""
    cards = re.findall(r"^\s*\d+\s+\[[^\]]+\]:\s*(.+)$", read("/proc/asound/cards"), re.M)
    if cards:
        return [{"name": c, "description": c.split(" - ")[-1].strip(), "state": "", "default": False, "bus": "", "port": ""} for c in cards], [], \
            "The sound server isn't answering, so only the sound cards are listed."
    return [], [], "No sound devices found (the sound server isn't running, or this is a virtual machine)."


# ---------------------------------------------------------------- Bluetooth

def parse_bluetoothctl_devices(text: str) -> list[tuple[str, str]]:
    """`bluetoothctl devices [Paired|Connected]` -> [(mac, name)]."""
    res = []
    for line in text.splitlines():
        m = re.search(r"Device ([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s*(.*)$", line, re.I)
        if m:
            res.append((m.group(1).upper(), m.group(2).strip() or m.group(1)))
    return res


def bluetooth_devices() -> tuple[list[dict], str]:
    if not glob.glob("/sys/class/bluetooth/hci*"):
        return [], "No Bluetooth adapter found."
    if not has("bluetoothctl"):
        return [], "bluetoothctl isn't installed (package bluez)."
    if sh(["systemctl", "is-active", "bluetooth"], timeout=5).out.strip() != "active":
        return [], "The Bluetooth service is off."
    paired = parse_bluetoothctl_devices(out(["bluetoothctl", "devices", "Paired"], timeout=5))
    if not paired:
        paired = parse_bluetoothctl_devices(out(["bluetoothctl", "paired-devices"], timeout=5))
    connected = {m for m, _ in parse_bluetoothctl_devices(out(["bluetoothctl", "devices", "Connected"], timeout=5))}
    items = [{"mac": m, "name": n, "connected": m in connected} for m, n in paired]
    items.sort(key=lambda d: (not d["connected"], d["name"].lower()))
    return items, "" if items else "Bluetooth is on, but nothing is paired yet."


# ---------------------------------------------------------------- screens

CONNECTORS = {"eDP": "Built-in screen", "LVDS": "Built-in screen", "DSI": "Built-in screen", "HDMI-A": "HDMI", "HDMI-B": "HDMI",
              "DP": "DisplayPort / USB-C", "DVI-D": "DVI", "DVI-I": "DVI", "VGA": "VGA", "Virtual": "Virtual screen"}


def parse_edid(data: bytes) -> dict:
    """Monitor name, maker code and size from the first 128 bytes of an EDID blob."""
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return {}
    word = (data[8] << 8) | data[9]
    maker = "".join(chr(((word >> s) & 0x1F) + 64) for s in (10, 5, 0))
    name = serial = ""
    for off in (54, 72, 90, 108):
        blk = data[off:off + 18]
        if blk[0:2] == b"\x00\x00" and blk[2] == 0:
            txt = blk[5:18].split(b"\x0a")[0].decode("ascii", errors="replace").strip()
            if blk[3] == 0xFC:
                name = txt
            elif blk[3] == 0xFF:
                serial = txt
    w, h = data[21], data[22]
    inches = round(((w * w + h * h) ** 0.5) / 2.54, 1) if w and h else None
    return {"name": name, "maker": maker if maker.isalpha() else "", "serial": serial, "width_cm": w, "height_cm": h, "inches": inches}


def displays(root: str = "/sys/class/drm") -> list[dict]:
    res = []
    for d in sorted(glob.glob(os.path.join(root, "card*-*"))):
        conn = os.path.basename(d).split("-", 1)[1]
        if conn.startswith("Writeback"):
            continue
        status = read(os.path.join(d, "status")).strip()
        kind = re.sub(r"-\d+$", "", conn)
        try:
            edid = parse_edid(Path(d, "edid").read_bytes())
        except OSError:
            edid = {}
        modes = read(os.path.join(d, "modes")).split()
        res.append({"connector": conn, "kind": CONNECTORS.get(kind, kind), "connected": status == "connected",
                    "enabled": read(os.path.join(d, "enabled")).strip() == "enabled", "name": edid.get("name", ""),
                    "maker": edid.get("maker", ""), "inches": edid.get("inches"), "best_mode": modes[0] if modes else ""})
    res.sort(key=lambda x: (not x["connected"], x["connector"]))
    return res


# ---------------------------------------------------------------- cameras

def cameras(root: str = "/sys/class/video4linux") -> list[str]:
    names: list[str] = []
    for d in sorted(glob.glob(os.path.join(root, "video*"))):
        idx = read(os.path.join(d, "index")).strip()
        name = read(os.path.join(d, "name")).strip()
        a, _, b = name.partition(": ")
        if b and a.startswith(b.strip()):
            name = a  # "Integrated_Webcam_HD: Integrate" -> "Integrated_Webcam_HD"
        name = name.replace("_", " ")
        if name and idx in ("", "0") and name not in names:
            names.append(name)
    return names


# ---------------------------------------------------------------- memory modules

MEM_CACHE = HOME / ".cache/pc/memory-modules.txt"


def parse_dmidecode_memory(text: str) -> list[dict]:
    """`dmidecode -t memory` -> installed modules [{slot, size, type, speed, configured, maker, part, form}]."""
    res = []
    for block in re.split(r"\n(?=Handle )", text):
        if "Memory Device" not in block:
            continue
        kv = {}
        for line in block.splitlines():
            m = re.match(r"\s+([^:]+):\s*(.*)$", line)
            if m:
                kv.setdefault(m.group(1).strip(), m.group(2).strip())
        size = kv.get("Size", "")
        if not size or "No Module" in size or size in ("0", "Unknown", "Not Installed"):
            continue
        res.append({"slot": kv.get("Locator", ""), "bank": kv.get("Bank Locator", ""), "size": size, "type": kv.get("Type", ""),
                    "speed": kv.get("Speed", ""), "configured": kv.get("Configured Memory Speed", "") or kv.get("Configured Clock Speed", ""),
                    "maker": kv.get("Manufacturer", "") if kv.get("Manufacturer", "") not in ("Unknown", "Not Specified") else "",
                    "part": kv.get("Part Number", "").strip() if kv.get("Part Number", "").strip() not in ("Unknown", "Not Specified") else "",
                    "form": kv.get("Form Factor", "")})
    return res


def memory_slots(text: str) -> int:
    return len(re.findall(r"^Memory Device\s*$", text, re.M))


def memory_modules_steps(path: Path = MEM_CACHE) -> list[Step]:
    """dmidecode needs admin rights: run it once and keep the answer in your cache folder (readable by you)."""
    uid, gid = os.getuid(), os.getgid()
    p = str(path)

    def mkdir() -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"folder {path.parent} ready"
    return [py_step("Make the cache folder", mkdir, f"mkdir -p {_q(os.path.dirname(p))}"),
            Step("Read memory module details from the BIOS", ["bash", "-c", f"dmidecode -t memory > {_q(p)} && chown {uid}:{gid} {_q(p)}"], root=True)]


def cached_memory_modules(path: Path = MEM_CACHE) -> tuple[list[dict], int] | None:
    text = read(path)
    if not text:
        return None
    return parse_dmidecode_memory(text), memory_slots(text)


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def mem_total() -> int:
    m = re.search(r"^MemTotal:\s+(\d+) kB", read("/proc/meminfo"), re.M)
    return int(m.group(1)) * 1024 if m else 0


# ---------------------------------------------------------------- everything

def all_devices() -> dict:
    """Everything above in one go (for the Devices tab). Each part fails on its own."""
    res: dict = {}

    def safe(key, fn, default):
        try:
            res[key] = fn()
        except Exception as e:  # noqa: BLE001 - one broken source mustn't hide the others
            res[key] = default
            res.setdefault("errors", []).append(f"{key}: {e}")
    safe("usb", usb_devices, ([], "Couldn't read USB devices."))
    safe("pci", lambda: parse_lspci_mm(out(["lspci", "-mm"], timeout=8)) if has("lspci") else [], [])
    safe("sound", sound_devices, ([], [], ""))
    safe("bluetooth", bluetooth_devices, ([], ""))
    safe("displays", displays, [])
    safe("cameras", cameras, [])
    safe("memory", cached_memory_modules, None)
    res["pci_note"] = "" if has("lspci") else "Install pciutils to see the names of the cards and chips inside."
    return res
