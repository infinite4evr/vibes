"""Graphics card usage: NVIDIA (nvidia-smi), AMD (amdgpu sysfs) and Intel (frequency as a proxy)."""

from __future__ import annotations

import glob
import os
import re
from functools import lru_cache

from .run import has, out, read


@lru_cache(maxsize=1)
def names() -> dict[str, str]:
    """PCI address → marketing-ish name, from lspci."""
    res = {}
    for line in out(["lspci", "-mm", "-D"]).splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
            addr = line.split()[0]
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:
                res[addr] = f"{parts[1]} {parts[2]}".replace("Corporation", "").replace("Advanced Micro Devices, Inc. [AMD/ATI]", "AMD").strip()
    return res


def _num(path: str) -> float | None:
    v = read(path).strip()
    try:
        return float(v)
    except ValueError:
        return None


def _nvidia() -> list[dict]:
    if not has("nvidia-smi"):
        return []
    text = out(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,clocks.gr",
                "--format=csv,noheader,nounits"], timeout=5)
    res = []
    for line in text.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 7:
            continue

        def f(x: str) -> float | None:
            try:
                return float(x)
            except ValueError:
                return None
        res.append({"vendor": "NVIDIA", "name": p[0], "busy": f(p[1]), "vram_used": (f(p[2]) or 0) * 1024 ** 2,
                    "vram_total": (f(p[3]) or 0) * 1024 ** 2, "temp": f(p[4]), "power": f(p[5]), "freq": f(p[6]), "driver": "nvidia"})
    return res


def _drm_cards() -> list[str]:
    return sorted(c for c in glob.glob("/sys/class/drm/card[0-9]*") if re.match(r".*/card\d+$", c))


def _sysfs() -> list[dict]:
    res = []
    pci_names = names()
    for card in _drm_cards():
        dev = os.path.join(card, "device")
        driver = os.path.basename(os.path.realpath(os.path.join(dev, "driver"))) if os.path.exists(os.path.join(dev, "driver")) else ""
        addr = os.path.basename(os.path.realpath(dev))
        name = pci_names.get(addr, driver or os.path.basename(card))
        if driver == "amdgpu":
            hw = (glob.glob(os.path.join(dev, "hwmon/hwmon*")) or [""])[0]
            temp = _num(os.path.join(hw, "temp1_input")) if hw else None
            power = _num(os.path.join(hw, "power1_average")) if hw else None
            res.append({"vendor": "AMD", "name": name, "busy": _num(os.path.join(dev, "gpu_busy_percent")),
                        "vram_used": _num(os.path.join(dev, "mem_info_vram_used")) or 0, "vram_total": _num(os.path.join(dev, "mem_info_vram_total")) or 0,
                        "temp": temp / 1000 if temp else None, "power": power / 1e6 if power else None, "freq": None, "driver": driver})
        elif driver in ("i915", "xe"):
            cur = _num(os.path.join(card, "gt_act_freq_mhz")) or _num(os.path.join(card, "gt_cur_freq_mhz"))
            mx = _num(os.path.join(card, "gt_max_freq_mhz")) or _num(os.path.join(card, "gt_RP0_freq_mhz"))
            if cur is None:  # xe driver layout
                cur = _num(os.path.join(dev, "tile0/gt0/freq0/act_freq"))
                mx = _num(os.path.join(dev, "tile0/gt0/freq0/max_freq"))
            busy = round(cur / mx * 100) if cur is not None and mx else None
            res.append({"vendor": "Intel", "name": name, "busy": busy, "busy_is_freq": True, "vram_used": 0, "vram_total": 0, "temp": None,
                        "power": None, "freq": cur, "driver": driver})
        elif driver == "nouveau":
            res.append({"vendor": "NVIDIA", "name": name, "busy": None, "vram_used": 0, "vram_total": 0, "temp": None, "power": None,
                        "freq": None, "driver": driver})
    return res


def gpus() -> list[dict]:
    nv = _nvidia()
    rest = [g for g in _sysfs() if not (nv and g["vendor"] == "NVIDIA")]
    return nv + rest


def driver_hint() -> str:
    """A plain-language note when an NVIDIA card runs on the slow open-source driver."""
    for g in _sysfs():
        if g["driver"] == "nouveau":
            return "Your NVIDIA card uses the basic open-source driver. The official NVIDIA driver is much faster (Updates → Drivers)."
    return ""
