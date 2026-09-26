"""Power & hardware, Logs and Services extras (audit J1-J5, K1-K3, L1-L4): parsers and the steps actions would run."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from pcctl.core import devices, logs, power, services

FIX = Path(__file__).parent / "fixtures" / "pls"


def fx(name: str) -> str:
    return (FIX / name).read_text()


# ---------------------------------------------------------------- J1 battery history

BASE = 1790208000  # 2026-09-24 00:00 UTC, start of the fixture day


def test_upower_history_parse():
    pts = power.parse_upower_history(fx("upower/history-charge-5B10W13975-51-4312.dat"))
    assert len(pts) == 18  # the garbage line and blank line are skipped
    assert pts[0] == (BASE, 96.0, "discharging")
    assert pts[-1][1] == 30.0
    assert [p[0] for p in pts] == sorted(p[0] for p in pts)
    assert {p[2] for p in pts} == {"discharging", "charging", "fully-charged"}
    assert power.parse_upower_history("1700000000\t55.5\n0\t12\tx\nabc\tdef\tghi\n") == [(1700000000.0, 55.5, "unknown")]


def test_battery_history_window_and_summary():
    folder = str(FIX / "upower")
    assert power.history_files("charge", folder)[0].endswith("history-charge-5B10W13975-51-4312.dat")
    now = BASE + 20 * 3600
    day = power.battery_history("charge", 24, now=now, folder=folder)
    assert day[0][0] == BASE and day[-1][1] == 30.0
    last4 = power.battery_history("charge", 4, now=now, folder=folder)
    # starts at the window edge with the value that was current then (from the point just before)
    assert last4[0] == (now - 4 * 3600, 99.0, "discharging")
    assert all(p[0] >= now - 4 * 3600 for p in last4)
    rate = power.battery_history("rate", 24, now=now, folder=folder)
    assert any(p[1] == 24.5 and p[2] == "charging" for p in rate)
    assert power.battery_history("charge", 24, now=now, folder="/nonexistent") == []
    s = power.history_summary(day)
    assert s["low"] == 30.0 and s["high"] == 100.0 and s["charges"] == 1
    # the 8 h overnight gap (asleep) doesn't count as time on battery
    assert 8 * 3600 < s["on_battery"] < 13 * 3600
    assert power.history_summary([]) == {}


def test_downsample_keeps_last():
    pts = [(float(i), float(i % 100), "discharging") for i in range(5000)]
    ds = power.downsample(pts, 400)
    assert len(ds) <= 401 and ds[-1] == pts[-1] and ds[0] == pts[0]
    assert power.downsample(pts[:10], 400) == pts[:10]


# ---------------------------------------------------------------- J2 keep awake

def test_keep_awake_cmd():
    cmd = power.keep_awake_cmd(3600, gnome=False)
    assert cmd == ["systemd-inhibit", "--what=idle:sleep", "--who=PC Command Center", "--why=Keep awake", "--mode=block", "sleep", "3600"]
    assert power.keep_awake_cmd(0, gnome=False)[-2:] == ["sleep", "infinity"]
    g = power.keep_awake_cmd(1800, gnome=True)
    assert g[:3] == ["gnome-session-inhibit", "--inhibit", "idle:suspend"] and "systemd-inhibit" in g and g[-1] == "1800"


def test_keep_awake_status_and_stop(tmp_path, monkeypatch):
    state = tmp_path / "keep-awake.json"
    monkeypatch.setattr(power, "AWAKE_FILE", state)
    monkeypatch.setattr(power, "inhibitors", lambda: [])
    # a pid that isn't ours is never trusted (and the stale file is cleaned up)
    state.write_text(json.dumps({"pid": os.getpid(), "started": 1, "until": 0}))
    assert power.keep_awake_status() is None and not state.exists()
    # a stand-in process whose command line looks like our inhibitor
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "systemd-inhibit", "--who=PC Command Center"],
                         start_new_session=True)
    try:
        time.sleep(0.2)
        now = time.time()
        state.write_text(json.dumps({"pid": p.pid, "started": now, "until": now + 600, "screen": True}))
        st = power.keep_awake_status(now=now + 60)
        assert st and st["pid"] == p.pid and 539 <= st["left"] <= 541 and st["screen"]
        state.write_text(json.dumps({"pid": p.pid, "started": now, "until": 0}))
        assert power.keep_awake_status()["left"] is None  # until stopped
        assert power.stop_keep_awake() is True
        assert p.wait(timeout=5) != 0 and not state.exists()
    finally:
        if p.poll() is None:
            p.kill()


def test_inhibitors_parsers():
    js = power.parse_inhibitors_json(fx("inhibitors.json"))
    assert len(js) == 5
    ours = [i for i in js if i["who"] == power.WHO]
    assert ours == [{"what": "idle:sleep", "who": "PC Command Center", "why": "Keep awake", "mode": "block", "uid": 1000, "pid": 48211}]
    tx = power.parse_inhibitors_text(fx("inhibitors.txt"))
    assert len(tx) == 5
    uu = next(i for i in tx if i["pid"] == 1320)
    assert uu["who"] == "Unattended Upgrades Shutdown" and uu["why"].endswith("before shutdown") and uu["mode"] == "delay"
    assert next(i for i in tx if i["pid"] == 48211)["what"] == "idle:sleep"
    assert power.parse_inhibitors_json("not json") == [] and power.parse_inhibitors_text("") == []
    fox = next(i for i in js if i["who"] == "Firefox")
    assert power.explain_inhibitor(fox) == "Stops sleep, going idle: Playing video"
    assert power.explain_inhibitor(js[0]).startswith("Briefly delays sleep")


# ---------------------------------------------------------------- J3 timers

def test_scheduled_shutdown_parsers():
    s = power.parse_scheduled("USEC=1790290800000000\nWARN_WALL=1\nMODE=reboot\nUID=1000\n")
    assert s == {"mode": "reboot", "when": 1790290800.0}
    assert power.parse_scheduled("MODE=poweroff\n") is None
    assert power.parse_scheduled("USEC=1790290800000000\nMODE=dry-poweroff\n")["mode"] == "poweroff"
    assert power.parse_scheduled_property('(st) "poweroff" 1790290800000000') == {"mode": "poweroff", "when": 1790290800.0}
    assert power.parse_scheduled_property('(st) "" 0') is None


def test_timer_steps():
    off = power.timer_steps("poweroff", 30)
    assert [s.cmd for s in off] == [["shutdown", "-h", "+30"]] and not off[0].root  # logind lets the person at the screen do this
    assert power.timer_steps("reboot", 90)[0].cmd == ["shutdown", "-r", "+90"]
    sus = power.timer_steps("suspend", 45)
    assert sus[0].optional and sus[0].cmd[:3] == ["systemctl", "--user", "stop"]
    run = sus[1].cmd
    assert run[:3] == ["systemd-run", "--user", "--unit=pc-suspend-timer"] and "--on-active=45m" in run and run[-2:] == ["systemctl", "suspend"]
    assert not any(s.root for s in sus)
    assert power.cancel_timer_steps("shutdown")[0].cmd == ["shutdown", "-c"]
    assert power.cancel_timer_steps("suspend")[0].cmd == ["systemctl", "--user", "stop", "pc-suspend-timer.timer"]
    assert power.in_words(15) == "in 15 minutes" and power.in_words(60) == "in 1 hour" and power.in_words(90) == "in 1 h 30 min"
    assert off[0].title == "Shut down in 30 minutes" and power.timer_steps("reboot", 120)[0].title == "Restart in 2 hours"
    assert power.human_left(3 * 3600 + 5 * 60) == "3 h 05 min" and power.human_left(30) == "less than a minute"


# ---------------------------------------------------------------- J4 CPU

def _cpu_tree(root: Path, n: int = 4, intel: bool = True) -> None:
    for i in range(n):
        f = root / f"cpu{i}" / "cpufreq"
        f.mkdir(parents=True)
        (f / "scaling_cur_freq").write_text(f"{1200000 + i * 800000}\n")
        (f / "cpuinfo_min_freq").write_text("400000\n")
        (f / "cpuinfo_max_freq").write_text("4700000\n")
        (f / "scaling_max_freq").write_text("4700000\n")
        (f / "scaling_governor").write_text("powersave\n")
        (f / "energy_performance_preference").write_text("balance_performance\n")
        (f / "scaling_driver").write_text("intel_pstate\n" if intel else "amd-pstate-epp\n")
        if intel:
            t = root / f"cpu{i}" / "thermal_throttle"
            t.mkdir()
            (t / "core_throttle_count").write_text(f"{i}\n")
            (t / "package_throttle_count").write_text("12\n")
    (root / "cpu0" / "cpufreq" / "energy_performance_available_preferences").write_text(
        "default performance balance_performance balance_power power\n")
    if n > 3:
        (root / "cpu3" / "online").write_text("1\n")
    if intel:
        (root / "intel_pstate").mkdir()
        (root / "intel_pstate" / "no_turbo").write_text("0\n")
        (root / "intel_pstate" / "status").write_text("active\n")
    else:
        (root / "cpufreq").mkdir()
        (root / "cpufreq" / "boost").write_text("0\n")
        (root / "amd_pstate").mkdir()
        (root / "amd_pstate" / "status").write_text("active\n")


def test_cpu_speeds_intel(tmp_path):
    _cpu_tree(tmp_path)
    (tmp_path / "cpufreq").mkdir()  # the shared policy folder isn't a cpu
    info = power.cpu_speeds(str(tmp_path), cpuinfo="/nonexistent")
    assert [c["cpu"] for c in info["cores"]] == [0, 1, 2, 3]
    assert info["cores"][1]["mhz"] == 2000.0 and info["cores"][0]["max"] == 4700.0
    assert info["driver"] == "intel_pstate" and info["governors"] == ["powersave"] and info["epps"] == ["balance_performance"]
    assert info["turbo"] is True and info["pstate_status"] == "active"
    assert info["throttle_core"] == 0 + 1 + 2 + 3 and info["throttle_pkg"] == 12
    assert info["top_mhz"] == 3600.0 and info["max_mhz"] == 4700.0
    assert "performance" in info["epp_choices"]
    facts = dict(power.cpu_facts(info))
    assert "Turbo boost: on" in facts and any(k.startswith("Governor: powersave") for k in facts)
    lvl, text = power.throttle_verdict(info["throttle_core"], info["throttle_pkg"])
    assert lvl == "ok" and "18 times" in text


def test_cpu_speeds_amd_and_fallback(tmp_path):
    _cpu_tree(tmp_path / "amd", 2, intel=False)
    info = power.cpu_speeds(str(tmp_path / "amd"))
    assert info["driver"] == "amd-pstate-epp" and info["turbo"] is False and info["throttle_core"] is None
    assert power.throttle_verdict(None, None)[0] == "info"
    assert power.throttle_verdict(5000, 900)[0] == "warn"
    ci = tmp_path / "cpuinfo"
    ci.write_text("processor\t: 0\ncpu MHz\t\t: 2803.200\n\nprocessor\t: 1\ncpu MHz\t\t: 2803.211\n")
    vm = power.cpu_speeds(str(tmp_path / "empty"), cpuinfo=str(ci))
    assert vm["source"] == "cpuinfo" and [round(c["mhz"]) for c in vm["cores"]] == [2803, 2803] and vm["turbo"] is None


# ---------------------------------------------------------------- J5 devices

def test_lsusb_and_kinds():
    usb = devices.parse_lsusb(fx("lsusb.txt"))
    assert [u["id"] for u in usb] == ["27c6:6594", "8087:0026", "046d:c52b", "0bda:5634", "0781:5583"]  # root hubs dropped
    kinds = [devices.usb_kind(u["name"]) for u in usb]
    assert kinds == ["Fingerprint reader", "Bluetooth adapter", "Mouse / keyboard", "Camera", "Storage"]


def test_usb_sysfs(tmp_path):
    d = tmp_path / "3-2"
    d.mkdir()
    (d / "idVendor").write_text("046d\n")
    (d / "idProduct").write_text("c52b\n")
    (d / "manufacturer").write_text("Logitech\n")
    (d / "product").write_text("USB Receiver\n")
    (tmp_path / "usb1").mkdir()
    (tmp_path / "3-2:1.0").mkdir()
    assert devices.usb_sysfs(str(tmp_path)) == [{"bus": 0, "dev": 0, "id": "046d:c52b", "name": "Logitech USB Receiver"}]


def test_lspci_groups():
    pci = devices.parse_lspci_mm(fx("lspci-mm.txt"))
    by = {p["slot"]: p for p in pci}
    assert by["00:02.0"]["group"] == "Graphics" and by["00:02.0"]["vendor"] == "Intel"
    assert by["01:00.0"]["plain"] == "Graphics (extra GPU)" and by["01:00.0"]["vendor"] == "NVIDIA"
    assert by["00:14.3"]["plain"] == "Wi-Fi" and by["03:00.0"]["plain"] == "Wired network"
    assert by["02:00.0"]["group"] == "Storage" and by["02:00.0"]["vendor"] == "Samsung"
    assert by["00:1f.4"]["group"] == "Chipset" and by["00:00.0"]["group"] == "Chipset"


def test_sound_parsers():
    sinks = devices.parse_pactl_json(fx("pactl-sinks.json"), default="bluez_output.AC_80_0A_12_34_56.1")
    assert [s["description"] for s in sinks] == ["Built-in Audio Analog Stereo", "WH-1000XM4"]
    assert sinks[1]["default"] and sinks[1]["bus"] == "bluetooth" and sinks[1]["state"] == "running"
    srcs = devices.parse_pactl_json(fx("pactl-sources.json"))
    assert len(srcs) == 1 and srcs[0]["name"].startswith("alsa_input")  # the monitor source is skipped
    assert devices.parse_pactl_json("garbage") == []
    wp = devices.parse_wpctl_status(fx("wpctl-status.txt"))
    assert [s["description"] for s in wp["sinks"]] == ["Built-in Audio Analog Stereo", "WH-1000XM4"]
    assert wp["sinks"][1]["default"] and not wp["sinks"][0]["default"]
    assert [s["description"] for s in wp["sources"]] == ["Built-in Audio Analog Stereo"]  # the Video section's camera isn't audio


def test_bluetoothctl():
    got = devices.parse_bluetoothctl_devices(fx("bluetoothctl-paired.txt"))
    assert got == [("AC:80:0A:12:34:56", "WH-1000XM4"), ("28:11:A5:AB:CD:EF", "MX Master 3"), ("00:1A:7D:DA:71:13", "00:1A:7D:DA:71:13")]


def _edid(name: str, maker: str = "DEL", w: int = 60, h: int = 34) -> bytes:
    b = bytearray(128)
    b[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    word = ((ord(maker[0]) - 64) << 10) | ((ord(maker[1]) - 64) << 5) | (ord(maker[2]) - 64)
    b[8], b[9] = word >> 8, word & 0xFF
    b[21], b[22] = w, h
    desc = bytearray(18)
    desc[3] = 0xFC
    text = (name.encode() + b"\n").ljust(13, b" ")
    desc[5:18] = text[:13]
    b[72:90] = desc
    return bytes(b)


def test_edid_and_displays(tmp_path):
    e = devices.parse_edid(_edid("DELL U2723QE"))
    assert e["name"] == "DELL U2723QE" and e["maker"] == "DEL" and abs(e["inches"] - 27.15) < 0.1
    assert devices.parse_edid(b"\x00" * 128) == {}
    a = tmp_path / "card1-eDP-1"
    a.mkdir()
    (a / "status").write_text("connected\n")
    (a / "enabled").write_text("enabled\n")
    (a / "modes").write_text("1920x1200\n1920x1080\n")
    (a / "edid").write_bytes(_edid("", "BOE", 30, 19))
    b = tmp_path / "card1-HDMI-A-1"
    b.mkdir()
    (b / "status").write_text("disconnected\n")
    (b / "enabled").write_text("disabled\n")
    (b / "edid").write_bytes(b"")
    (tmp_path / "card1-Writeback-1").mkdir()
    ds = devices.displays(str(tmp_path))
    assert [d["connector"] for d in ds] == ["eDP-1", "HDMI-A-1"]
    assert ds[0]["kind"] == "Built-in screen" and ds[0]["connected"] and ds[0]["best_mode"] == "1920x1200" and ds[0]["maker"] == "BOE"
    assert ds[1]["kind"] == "HDMI" and not ds[1]["connected"]


def test_cameras(tmp_path):
    for n, (idx, name) in enumerate([("0", "Integrated_Webcam_HD: Integrate"), ("1", "Integrated_Webcam_HD: Integrate")]):
        d = tmp_path / f"video{n}"
        d.mkdir()
        (d / "index").write_text(idx + "\n")
        (d / "name").write_text(name + "\n")
    assert devices.cameras(str(tmp_path)) == ["Integrated Webcam HD"]


def test_dmidecode_memory_and_steps(tmp_path):
    text = fx("dmidecode-memory.txt")
    mods = devices.parse_dmidecode_memory(text)
    assert len(mods) == 1 and devices.memory_slots(text) == 2
    m = mods[0]
    assert m["size"] == "16 GB" and m["type"] == "DDR4" and m["configured"] == "3200 MT/s" and m["maker"] == "Samsung"
    assert m["part"] == "M471A2K43DB1-CWE" and m["slot"] == "DIMM A" and m["form"] == "SODIMM"
    path = tmp_path / "cache" / "mem.txt"
    steps = devices.memory_modules_steps(path)
    assert steps[0].cmd[0] == "__python__" and not steps[0].root
    assert steps[1].root and steps[1].cmd[:2] == ["bash", "-c"] and f"dmidecode -t memory > {path}" in steps[1].cmd[2]
    assert f"chown {os.getuid()}:{os.getgid()}" in steps[1].cmd[2]
    steps[0]._func()
    assert path.parent.is_dir()
    path.write_text(text)
    assert devices.cached_memory_modules(path) == (mods, 2)
    assert devices.cached_memory_modules(tmp_path / "missing") is None


# ---------------------------------------------------------------- K1 kernel messages

def _kernel_lines():
    return logs.parse_journal_json(fx("kernel.json"))


def test_kernel_explain_and_categories():
    ex = logs.kernel_explain
    assert ex("ACPI BIOS Error (bug): Could not resolve symbol")[1] is True
    assert ex("tpm_crb MSFT0101:00: [Firmware Bug]: ACPI region")[1] is True
    assert ex("usb 3-2: device descriptor read/64, error -71")[1] is False
    assert ex("usb 3-6: new high-speed USB device number 6 using xhci_hcd")[1] is True
    assert ex("Out of memory: Killed process 81234 (chrome)")[1] is False
    assert ex("NVRM: Xid (PCI:0000:01:00): 79")[1] is False
    assert ex("Bluetooth: hci0: Malformed MSFT vendor event: 0x02")[1] is True
    assert ex('audit: type=1400 apparmor="DENIED" operation="open"')[1] is True
    assert ex("some-random-driver: weird thing happened") is None
    cat = logs.kernel_category
    assert cat("usb 3-2: device descriptor read/64")[0] == "USB"
    assert cat("iwlwifi 0000:00:14.3: Direct firmware load")[0] == "Wi-Fi and network"
    assert cat("Bluetooth: hci0: Malformed")[0] == "Bluetooth"
    assert cat("NVRM: Xid")[0] == "Graphics"
    assert cat("nvme nvme0: I/O 18 QID 3 timeout")[0] == "Disks and storage"
    assert cat("ACPI BIOS Error")[0] == "Firmware and BIOS"
    assert cat("Out of memory: Killed process")[0] == "Memory"
    assert cat('audit: apparmor="DENIED"')[0].startswith("Security")
    assert cat("some-random-driver: weird")[0] == "Other"


def test_kernel_groups():
    lines = _kernel_lines()
    assert len(lines) == 15 and all(ln.source == "kernel" for ln in lines)
    everything = logs.kernel_groups(lines, hide_harmless=False)
    assert sum(g["count"] for g in everything) == 15
    worth = logs.kernel_groups(lines, hide_harmless=True)
    names = [g["name"] for g in worth]
    assert "Firmware and BIOS" not in names  # ACPI/firmware noise is hidden
    assert names[0] in ("USB", "Graphics", "Memory", "Disks and storage")  # errors first
    usb = next(g for g in worth if g["name"] == "USB")
    assert usb["count"] == 1 and usb["worst"] == 3
    assert next(g for g in worth if g["name"] == "Other")["count"] == 1
    for g in worth:
        assert all(not (e and e[1]) for _ln, e in g["lines"])


def test_follow_cmd():
    assert logs.follow_cmd() == ["journalctl", "-f", "-o", "json", "--no-pager", "-n", "0", "-p", "6"]
    k = logs.follow_cmd(4, kernel=True, grep="usb", backlog=20)
    assert "-k" in k and k[k.index("-g") + 1] == "usb" and k[k.index("-n") + 1] == "20" and k[k.index("-p") + 1] == "4"


# ---------------------------------------------------------------- K3 journal size

def test_journal_sizes():
    assert logs.parse_size("1.2G") == int(1.2 * 1024 ** 3)
    assert logs.parse_size("512.0M") == 512 * 1024 ** 2
    assert logs.parse_size("0B") == 0 and logs.parse_size("8K") == 8192 and logs.parse_size("1.5 GiB") == int(1.5 * 1024 ** 3)
    assert logs.parse_size("lots") is None
    assert logs.parse_disk_usage("Archived and active journals take up 3.9G in the file system.") == int(3.9 * 1024 ** 3)
    assert logs.parse_disk_usage("Archived and active journals take up 16.0M in the file system.\n") == 16 * 1024 ** 2
    assert logs.parse_disk_usage("No journal files were found.\nArchived and active journals take up 0B in the file system.") == 0
    assert logs.parse_disk_usage("") is None


def test_journald_conf_and_steps():
    assert logs.parse_journald_conf(fx("journald-dropin.conf")) == {"SystemMaxUse": "500M"}
    assert logs.parse_journald_conf("[Other]\nSystemMaxUse=1G\n") == {}
    v = logs.vacuum_steps(size_mb=500)
    assert [s.cmd for s in v] == [["journalctl", "--vacuum-size=500M"]] and v[0].root
    assert logs.vacuum_steps(days=7)[0].cmd == ["journalctl", "--vacuum-time=7d"]
    lim = logs.limit_steps(500)
    assert all(s.root for s in lim)
    script = lim[0].cmd[2]
    assert lim[0].cmd[:2] == ["bash", "-c"] and logs.JOURNALD_DROPIN in script and '"SystemMaxUse=500M"' in script and '"[Journal]"' in script and "'" not in script
    assert lim[1].cmd == ["systemctl", "restart", "systemd-journald"] and lim[2].cmd == ["journalctl", "--vacuum-size=500M"]
    # the printf really produces a valid drop-in
    produced = subprocess.run(["bash", "-c", script.split(" && ", 1)[1].split(" > ")[0]], capture_output=True, text=True).stdout
    assert logs.parse_journald_conf(produced) == {"SystemMaxUse": "500M"}
    both = logs.limit_steps(500, 30)
    assert '"MaxRetentionSec=30day"' in both[0].cmd[2] and both[-1].cmd == ["journalctl", "--vacuum-time=30d"]
    off = logs.limit_steps(None)
    assert off[0].cmd == ["rm", "-f", logs.JOURNALD_DROPIN] and off[1].cmd[-1] == "systemd-journald"


# ---------------------------------------------------------------- L4 memory per service, L3 block

def test_parse_show_and_usage(monkeypatch):
    blocks = services.parse_show(fx("systemctl-show.txt"))
    assert [b["Id"] for b in blocks] == ["NetworkManager.service", "docker.service", "snapd.service"]
    assert services.show_num("18874368") == 18874368 and services.show_num("[not set]") is None
    assert services.show_num("18446744073709551615") is None and services.show_num("") is None
    assert services.show_time("@1790290800") == 1790290800.0 and services.show_time("n/a") is None and services.show_time("@0") is None
    calls = []

    def fake_out(cmd, **kw):
        calls.append(cmd)
        return fx("systemctl-show.txt")
    monkeypatch.setattr(services, "out", fake_out)
    use = services.resource_usage(["NetworkManager.service", "docker.service", "snapd.service"])
    assert len(calls) == 1 and calls[0][:3] == ["systemctl", "show", "--timestamp=unix"]  # one batched call
    assert "--" in calls[0] and calls[0][-1] == "snapd.service"
    assert use["NetworkManager.service"]["mem"] == 18874368 and abs(use["NetworkManager.service"]["cpu"] - 4.210334) < 1e-6
    assert use["docker.service"]["mem"] is None and use["docker.service"]["tasks"] is None
    assert use["snapd.service"]["tasks"] == 21


def test_mask_steps():
    sys_svc = services.Service("cups.service", "loaded", "active", "running", "CUPS")
    b = services.mask_steps(sys_svc, True)
    assert b[0].cmd == ["systemctl", "mask", "--now", "cups.service"] and b[0].root
    u = services.mask_steps(services.Service("x.service", "masked", "inactive", "dead", "", "masked", True), False)
    assert u[0].cmd == ["systemctl", "--user", "unmask", "x.service"] and not u[0].root


def test_list_timers_parse():
    rows = services.parse_list_timers(fx("list-timers.txt"))
    by = {r["unit"]: r for r in rows}
    assert len(rows) == 7
    assert by["pc-backup.timer"]["left"] == "18h" and by["pc-backup.timer"]["last"] == ""
    assert by["motd-news.timer"]["next"] == "" and by["motd-news.timer"]["passed"] == "1 day 16h ago"
    assert by["fstrim.timer"]["left"] == "2 days left"
    assert by["anacron.timer"]["left"] == "27min" and by["anacron.timer"]["activates"] == "anacron.service"
    assert by["apt-daily.timer"]["next"].startswith("Fri 2026-09-25 18:23:41")
    assert by["snapd.snap-repair.timer"]["next"] == "" and by["snapd.snap-repair.timer"]["activates"] == "snapd.snap-repair.service"
    assert services.short_time(by["anacron.timer"]["next"]) == "Fri 25 Sep 14:30" and services.short_time("") == ""
    assert services.explain_timer("fstrim.timer").startswith("Keeps SSDs fast")
    assert "Your script" in services.explain_timer("pc-backup.timer")
    assert services.explain_timer("pc-suspend-timer.timer").startswith("Sleep timer")


# ---------------------------------------------------------------- L2 cron

def test_cron_to_english():
    cases = {
        "* * * * *": "every minute",
        "*/15 * * * *": "every 15 minutes",
        "0 * * * *": "every hour, on the hour",
        "30 * * * *": "every hour at 30 minutes past",
        "0 */2 * * *": "every 2 hours, on the hour",
        "30 2 * * *": "every day at 02:30",
        "0 9 * * 1-5": "on weekdays (Mon–Fri) at 09:00",
        "0 9 * * 1": "every Monday at 09:00",
        "0 4 * * sun": "every Sunday at 04:00",
        "25 6 * * 7": "every Sunday at 06:25",
        "0 0 * * 0,6": "on weekends at 00:00",
        "10 3 * * 1,3,5": "on Mon, Wed and Fri at 03:10",
        "0 0 1 * *": "on the 1st of every month at 00:00",
        "0 3 1,15 * *": "on the 1st and 15th of every month at 03:00",
        "0 0 1 1 *": "every year on 1 January at 00:00",
        "0 8,20 * * *": "every day at 08:00 and 20:00",
        "*/5 9-17 * * 1-5": "every 5 minutes from 09:00 to 17:59, on weekdays (Mon–Fri)",
        "0-59/10 * * * *": "every 10 minutes",
        "0 12 * jan,jul *": "every day in Jan and Jul at 12:00",
        "0 0 */2 * *": "every 2 days at 00:00",
        "@reboot": "every time the PC starts",
        "@daily": "every day at 00:00",
        "@weekly": "once a week (Sunday at 00:00)",
    }
    for expr, want in cases.items():
        assert services.cron_to_english(expr) == want, expr
    assert services.cron_to_english("bad * * * *").startswith("cron schedule")
    assert services.cron_to_english("0 0 31 13 *").startswith("cron schedule")
    assert services.cron_values("10-20/5", 0, 59) == [10, 15, 20]
    assert services.cron_values("5/20", 0, 59) == [5, 25, 45]


def test_parse_crontabs(tmp_path):
    user = services.parse_crontab(fx("crontab-user.txt"), False, "Your crontab", "infinite4evr")
    assert [j.schedule for j in user] == ["*/15 * * * *", "0 9 * * 1-5", "@reboot"]  # MAILTO= and comments skipped
    assert user[0].command.startswith("/home/infinite4evr/bin/sync-notes.sh") and user[0].user == "infinite4evr"
    assert user[2].when == "every time the PC starts" and user[2].command == "/home/infinite4evr/.local/bin/start-bot"
    sysjobs = services.parse_crontab(fx("etc-crontab.txt"), True, "/etc/crontab")
    assert len(sysjobs) == 5 and all(j.user == "root" for j in sysjobs)
    assert sysjobs[0].when == "every hour at 17 minutes past" and sysjobs[0].command.startswith("cd / && run-parts")
    assert sysjobs[2].when == "every Sunday at 06:47" and sysjobs[3].when == "on the 1st of every month at 06:52"
    assert sysjobs[4].schedule == "@reboot" and sysjobs[4].command == "/usr/local/bin/boot-hook"
    # a whole /etc tree
    etc = tmp_path / "etc"
    (etc / "cron.d").mkdir(parents=True)
    (etc / "crontab").write_text(fx("etc-crontab.txt"))
    (etc / "cron.d" / "e2scrub_all").write_text("30 3 * * 0 root test -e /run/systemd/system || SERVICE_MODE=1 /usr/lib/x86_64-linux-gnu/e2fsprogs/e2scrub_all_cron\n")
    (etc / "cron.d" / ".placeholder").write_text("# nothing\n")
    (etc / "cron.daily").mkdir()
    for n in ("logrotate", "man-db", "dpkg", ".placeholder", "old.dpkg-old"):
        (etc / "cron.daily" / n).write_text("#!/bin/sh\n")
    got = services.cron_jobs(str(etc))
    assert len(got["system"]) == 6 and got["system"][-1].source == "/etc/cron.d/e2scrub_all"
    assert got["system"][-1].when == "every Sunday at 03:30"
    assert [n for n, _ in got["periodic"]["daily"]] == ["dpkg", "logrotate", "man-db"]
    assert dict(got["periodic"]["daily"])["logrotate"].startswith("Compresses") and got["periodic"]["weekly"] == []


# ---------------------------------------------------------------- L1 your scripts as services

def systemd_unquote(line: str) -> list[str]:
    """Emulates how systemd reads an ExecStart= value: specifiers (%%), then quotes + C escapes, then $$ -> $."""
    import re
    assert not re.search(r"%[^%]", line.replace("%%", "")), "unescaped specifier"
    line = line.replace("%%", "%")
    words, cur, quote, i, started = [], [], None, 0, False
    esc = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
    while i < len(line):
        c = line[i]
        if c == "\\":
            cur.append(esc[line[i + 1]])
            i += 2
            started = True
            continue
        if quote:
            if c == quote:
                quote = None
            else:
                cur.append(c)
        elif c in "\"'":
            quote, started = c, True
        elif c.isspace():
            if started:
                words.append("".join(cur))
                cur, started = [], False
        else:
            cur.append(c)
            started = True
        i += 1
    assert quote is None
    if started:
        words.append("".join(cur))
    return [w.replace("$$", "$") for w in words]


def test_exec_quoting_roundtrip():
    tricky = ['echo "hi $USER" 100% && cd ~/my\\ dir', "python3 bot.py --name 'it''s' ; echo ${HOME}", "printf 'a\\tb\\n'\necho second line",
              "node server.js > log.txt 2>&1 & wait", '"quoted" %n %h $$ \\\\ end']
    for cmd in tricky:
        line = services.exec_line(cmd)
        assert systemd_unquote(line) == ["/bin/bash", "-lc", cmd.strip()], cmd
        assert "\n" not in line


def test_slug_and_validation(tmp_path):
    assert services.slugify("My Discord Bot!!") == "my-discord-bot"
    assert services.slugify("  --a__b--  ") == "a-b" and services.slugify("ßü") == ""
    ok = services.ScriptSpec(name="bot", command="python3 bot.py", folder=str(tmp_path))
    assert services.validate_spec(ok) == ""
    assert "short name" in services.validate_spec(services.ScriptSpec(name="Bad Name", command="x"))
    assert "already" in services.validate_spec(ok, {"bot"}) and services.validate_spec(ok, {"bot"}, editing=True) == ""
    assert "command" in services.validate_spec(services.ScriptSpec(name="bot", command="  "))
    assert "doesn't exist" in services.validate_spec(services.ScriptSpec(name="bot", command="x", folder="/no/such/dir"))
    assert "HH:MM" in services.validate_spec(services.ScriptSpec(name="b", command="x", mode="schedule", kind="daily", at="25:00"))
    assert services.validate_spec(services.ScriptSpec(name="b", command="x", mode="schedule", kind="minutes", every=0)) != ""
    assert services.validate_spec(services.ScriptSpec(name="suspend-timer", command="x")) != ""


def test_schedule_text():
    S = services.ScriptSpec
    assert services.schedule_text(S("a", "x")) == "Keeps running and restarts if it crashes (starts when you log in)"
    assert services.schedule_text(S("a", "x", restart=False, boot=True)) == "Keeps running (starts at boot)"
    assert services.schedule_text(S("a", "x", mode="login")) == "Runs once each time you log in"
    assert services.schedule_text(S("a", "x", mode="schedule", kind="minutes", every=15)) == "Runs every 15 minutes"
    assert services.schedule_text(S("a", "x", mode="schedule", kind="hours", every=1)) == "Runs every hour"
    assert services.schedule_text(S("a", "x", mode="schedule", kind="daily", at="7:05")) == "Runs every day at 07:05"
    assert services.schedule_text(S("a", "x", mode="schedule", kind="weekly", at="21:30", weekday="Fri")) == "Runs every Friday at 21:30"


def test_unit_files_keep_running(tmp_path):
    spec = services.ScriptSpec(name="my-bot", command="python3 bot.py --token $TOKEN", folder=str(tmp_path))
    files = services.unit_files(spec)
    assert list(files) == ["pc-my-bot.service"]
    svc = files["pc-my-bot.service"]
    lines = svc.splitlines()
    assert "Type=simple" in lines and "Restart=on-failure" in lines and "RestartSec=5" in lines and "WantedBy=default.target" in lines
    assert f"WorkingDirectory={tmp_path}" in lines
    assert 'ExecStart=/bin/bash -lc "python3 bot.py --token $$TOKEN"' in lines
    assert services.parse_spec(svc) == spec  # the settings round-trip for editing
    assert "WorkingDirectory=~" in services.unit_files(services.ScriptSpec(name="x", command="ls")).get("pc-x.service")
    login = services.unit_files(services.ScriptSpec(name="x", command="ls", mode="login"))["pc-x.service"]
    assert "Type=oneshot" in login and "Restart=" not in login and "WantedBy=default.target" in login


def test_unit_files_schedules():
    every = services.unit_files(services.ScriptSpec(name="sync", command="./sync.sh", mode="schedule", kind="minutes", every=15))
    svc, tmr = every["pc-sync.service"], every["pc-sync.timer"]
    assert "Type=oneshot" in svc and "[Install]" not in svc and "Restart=" not in svc  # the timer starts it
    assert "OnActiveSec=1min" in tmr and "OnUnitActiveSec=15min" in tmr and "WantedBy=timers.target" in tmr
    hourly = services.unit_files(services.ScriptSpec(name="h", command="x", mode="schedule", kind="hours", every=6))["pc-h.timer"]
    assert "OnUnitActiveSec=6h" in hourly
    daily = services.unit_files(services.ScriptSpec(name="d", command="x", mode="schedule", kind="daily", at="7:05"))["pc-d.timer"]
    assert "OnCalendar=*-*-* 07:05:00" in daily and "Persistent=true" in daily
    weekly = services.unit_files(services.ScriptSpec(name="w", command="x", mode="schedule", kind="weekly", at="21:30", weekday="Fri"))["pc-w.timer"]
    assert "OnCalendar=Fri *-*-* 21:30:00" in weekly


def test_script_steps(tmp_path):
    spec = services.ScriptSpec(name="backup", command="rsync -a ~/Documents /mnt/b", mode="schedule", kind="daily", at="22:00", boot=True)
    steps = services.create_script_steps(spec, folder=tmp_path)
    assert steps[0].cmd[0] == "__python__" and "pc-backup.timer" in steps[0].cmd[1]
    assert [s.cmd for s in steps[1:3]] == [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "pc-backup.timer"]]
    assert steps[3].cmd[:2] == ["loginctl", "enable-linger"] and not any(s.root for s in steps)
    steps[0]._func()
    assert (tmp_path / "pc-backup.service").exists() and (tmp_path / "pc-backup.timer").exists()
    # editing it into a keep-running script stops the old one first and drops the old timer file
    spec2 = services.ScriptSpec(name="backup", command="./serve", mode="always")
    ed = services.create_script_steps(spec2, editing=True, folder=tmp_path)
    assert ed[0].optional and ed[0].cmd[:4] == ["systemctl", "--user", "disable", "--now"]
    ed[1]._func()
    assert not (tmp_path / "pc-backup.timer").exists()
    assert ed[-1].cmd == ["systemctl", "--user", "enable", "--now", "pc-backup.service"]
    login = services.create_script_steps(services.ScriptSpec(name="l", command="x", mode="login"), folder=tmp_path)
    assert "--no-block" in login[-1].cmd
    rm = services.remove_script_steps("backup", folder=tmp_path)
    assert rm[0].optional and rm[2].cmd == ["systemctl", "--user", "daemon-reload"]
    rm[1]._func()
    assert not (tmp_path / "pc-backup.service").exists()
    assert services.script_action_steps("bot", "run")[0].cmd == ["systemctl", "--user", "start", "--no-block", "pc-bot.service"]
    assert services.script_action_steps("bot", "stop", scheduled=True)[0].cmd[-2:] == ["pc-bot.timer", "pc-bot.service"]
    assert services.script_action_steps("bot", "start")[0].cmd[-1] == "pc-bot.service"


def test_script_state():
    S = services.ScriptSpec
    always = S("a", "x")
    assert services.script_state(always, {"ActiveState": "active", "SubState": "running"}, {}) == (("running", "ok"), True)
    assert services.script_state(always, {"ActiveState": "failed", "SubState": "failed"}, {})[0] == ("crashed", "bad")
    assert services.script_state(always, {"ActiveState": "activating", "SubState": "auto-restart"}, {})[0] == ("restarting", "warn")
    assert services.script_state(always, {"ActiveState": "inactive", "SubState": "dead"}, {}) == (("stopped", "neutral"), False)
    sched = S("b", "x", mode="schedule")
    assert services.script_state(sched, {"ActiveState": "inactive"}, {"ActiveState": "active"}) == (("scheduled", "ok"), True)
    assert services.script_state(sched, {"ActiveState": "inactive"}, {"ActiveState": "inactive"}) == (("paused", "neutral"), False)
    assert services.script_state(sched, {"ActiveState": "activating", "SubState": "start"}, {"ActiveState": "active"})[0][0] == "running now"


def test_script_jobs_listing(tmp_path, monkeypatch):
    for name, text in services.unit_files(services.ScriptSpec(name="bot", command="python3 bot.py")).items():
        (tmp_path / name).write_text(text)
    (tmp_path / "pc-old.service").write_text("[Service]\nExecStart=/usr/bin/foo\n")  # made by hand, no saved settings
    (tmp_path / "other.service").write_text("[Service]\nExecStart=/bin/true\n")

    def fake_out(cmd, **kw):
        if "show" in cmd:
            return ("Id=pc-bot.service\nActiveState=active\nSubState=running\nNRestarts=2\nMemoryCurrent=52428800\n"
                    "ActiveEnterTimestamp=@1790290000\nMainPID=4242\n\nId=pc-old.service\nActiveState=inactive\nSubState=dead\n")
        return ""
    monkeypatch.setattr(services, "out", fake_out)
    jobs = services.script_jobs(tmp_path)
    assert [j["name"] for j in jobs] == ["bot", "old"]
    bot = jobs[0]
    assert bot["state"] == ("running", "ok") and bot["restarts"] == 2 and bot["mem"] == 52428800 and bot["since"] == 1790290000.0
    assert bot["pid"] == 4242 and bot["spec"].command == "python3 bot.py"
    assert jobs[1]["spec"].command == "/usr/bin/foo" and jobs[1]["state"][0] == "stopped"
    assert services.script_jobs(tmp_path / "none") == []


def test_guess_command(tmp_path):
    assert services.guess_command("/home/me/bot.py") == "python3 /home/me/bot.py"
    assert services.guess_command("/home/me/my app/run.sh") == "bash '/home/me/my app/run.sh'"
    assert services.guess_command("/srv/server.js") == "node /srv/server.js"
    exe = tmp_path / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert services.guess_command(str(exe)) == str(exe)
