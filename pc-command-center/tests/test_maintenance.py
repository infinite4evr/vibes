"""Maintenance: troubleshooter parsers, Timeshift list, report redaction and rendering."""

import time
from types import SimpleNamespace

from pcctl.core import maint, report, troubleshoot


def test_wpctl_volume():
    assert troubleshoot.parse_wpctl_volume("Volume: 0.40 [MUTED]") == {"volume": 0.4, "muted": True}
    assert troubleshoot.parse_wpctl_volume("Volume: 1.00") == {"volume": 1.0, "muted": False}
    assert troubleshoot.parse_wpctl_volume("") == {}


WPCTL = """\
PipeWire 'pipewire-0' [1.4.7, ashu@ashu-pc, cookie:12345]
 └─ Clients:
        33. WirePlumber                         [1.4.7, ashu@ashu-pc, pid:1601]

Audio
 ├─ Devices:
 │      47. Built-in Audio                      [alsa]
 │
 ├─ Sinks:
 │      52. Built-in Audio Analog Stereo        [vol: 0.45]
 │  *   61. HDMI / DisplayPort 1 Output         [vol: 1.00 MUTED]
 │
 ├─ Sources:
 │  *   53. Built-in Audio Analog Stereo        [vol: 0.80]
 │
 ├─ Filters:
 │
 └─ Streams:

Video
 ├─ Devices:
 │      60. Integrated Camera                   [v4l2]
"""


def test_wpctl_status():
    st = troubleshoot.parse_wpctl_status(WPCTL)
    assert [s["name"] for s in st["sinks"]] == ["Built-in Audio Analog Stereo", "HDMI / DisplayPort 1 Output"]
    hdmi = st["sinks"][1]
    assert hdmi["default"] and hdmi["muted"] and hdmi["volume"] == 1.0
    assert st["sinks"][0]["volume"] == 0.45 and not st["sinks"][0]["default"]
    assert st["sources"][0]["default"] and st["sources"][0]["id"] == 53


def test_rfkill():
    text = """\
0: hci0: Bluetooth
	Soft blocked: yes
	Hard blocked: no
1: phy0: Wireless LAN
	Soft blocked: no
	Hard blocked: yes
"""
    devs = troubleshoot.parse_rfkill(text)
    assert devs[0] == {"name": "hci0", "type": "bluetooth", "soft": True, "hard": False}
    assert devs[1]["type"] == "wireless lan" and devs[1]["hard"] and not devs[1]["soft"]


def test_timedatectl():
    t = troubleshoot.parse_timedatectl("Timezone=Asia/Kolkata\nLocalRTC=no\nNTP=yes\nNTPSynchronized=no\n")
    assert t["Timezone"] == "Asia/Kolkata" and t["NTPSynchronized"] == "no"


def test_dpkg_broken():
    text = """\
Desired=Unknown/Install/Remove/Purge/Hold
| Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
|/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
||/ Name           Version      Architecture Description
+++-==============-============-============-=================================
ii  bash           5.2.37-1     amd64        GNU Bourne Again SHell
iU  code           1.104.0      amd64        Code editing. Redefined.
iF  nvidia-dkms    580.1        amd64        NVIDIA DKMS package
rc  oldthing       1.0          all          removed, config left
iHR brokenpkg      2.0          amd64        half installed, reinst required
"""
    assert troubleshoot.parse_dpkg_broken(text) == ["code", "nvidia-dkms", "brokenpkg"]


def test_troubleshooters_have_unique_ids():
    ids = [t.id for t in troubleshoot.TROUBLESHOOTERS]
    assert len(ids) == len(set(ids)) and {"internet", "sound", "apt", "slow"} <= set(ids)


TS = """\
Mounted '/dev/nvme0n1p2' at '/run/timeshift/1234/backup'
Device : /dev/nvme0n1p2
UUID   : 5f3c
Path   : /run/timeshift/1234/backup
Mode   : RSYNC
Status : OK
3 snapshots, 212.4 GB free

Num     Name                 Tags  Description
------------------------------------------------------------------------------
0    >  2026-05-01_10-00-01  W
1    >  2026-09-20_09-12-44  O     before nvidia driver
2    >  2026-09-24_08-00-01  DB
"""


def test_timeshift_list():
    info = maint.parse_timeshift_list(TS)
    assert info["device"] == "/dev/nvme0n1p2" and info["free"] == "212.4 GB" and info["configured"]
    names = [s["name"] for s in info["snapshots"]]
    assert names == ["2026-09-24_08-00-01", "2026-09-20_09-12-44", "2026-05-01_10-00-01"]  # newest first
    assert info["snapshots"][1]["comment"] == "before nvidia driver" and info["snapshots"][1]["kinds"] == ["made by hand"]
    assert info["snapshots"][0]["kinds"] == ["daily", "at start-up"] and info["snapshots"][0]["time"]
    assert not maint.parse_timeshift_list("First run mode (config file not found)\n")["configured"]


def test_timeshift_delete_steps():
    s = maint.timeshift_delete_steps(["2026-05-01_10-00-01"])
    assert s[0].root and s[0].cmd == ["timeshift", "--delete", "--snapshot", "2026-05-01_10-00-01", "--scripted"]


def test_redact():
    t = ("ashu-pc infinite4evr /home/infinite4evr/x 192.168.1.23 10.0.0.5 8.8.8.8 127.0.0.1 "
         "aa:bb:cc:dd:ee:ff fe80::1c2b:3a4d:5e6f:7a8b")
    r = report.redact(t, "ashu-pc", "infinite4evr")
    assert "ashu-pc" not in r and "infinite4evr" not in r and "/home/user/x" in r
    assert "192.168.x.x" in r and "10.0.x.x" in r and "x.x.x.x" in r and "127.0.0.1" in r
    assert "aa:bb" not in r and "fe80::1c2b" not in r


def _fake_data():
    Check = troubleshoot.Check
    mem = SimpleNamespace(total=16 * 1024 ** 3, available=8 * 1024 ** 3, percent=50.0)
    sw = SimpleNamespace(total=4 * 1024 ** 3, used=0)
    mount = SimpleNamespace(mountpoint="/", used=100 * 1024 ** 3, total=500 * 1024 ** 3, free=400 * 1024 ** 3, pct=20.0, fstype="ext4")
    return {"made": time.time(), "identity": {"host": "ashu-pc", "user": "infinite4evr", "model": "Lenovo ThinkPad", "os": "Ubuntu 26.04 LTS",
                                              "kernel": "7.0.0-10-generic", "desktop": "GNOME", "session": "wayland"},
            "hardware": {"cpu": "AMD Ryzen 7", "cores": 8, "threads": 16, "ram": 16 * 1024 ** 3, "gpus": [], "board": "", "bios": "", "arch": "x86_64"},
            "gpus": [{"name": "AMD Radeon 780M", "driver": "amdgpu"}], "uptime": 3600, "temp": 55.0,
            "checks": [Check("fw", "Firewall", "warn", "Off on ashu-pc"), Check("mem", "Memory", "ok", "fine")], "score": 93,
            "mounts": [mount], "memory": mem, "swap": sw, "battery": None, "updates": [], "errors": [{"count": 3, "source": "gnome-shell",
                                                                                                     "message": "JS ERROR at /home/infinite4evr/x"}],
            "failed": [], "reboot": None, "snaps": 12, "flatpaks": 3, "top": [{"name": "code", "mem": 2 * 1024 ** 3}],
            "net": [{"name": "wlp1s0", "up": True, "speed": 0, "ips": ["192.168.1.40"], "mac": "aa:bb:cc:dd:ee:ff"}], "quick": False}


def test_report_text_and_html():
    d = _fake_data()
    txt = report.text(d, redacted=True)
    assert "Health score: 93/100" in txt and "Lenovo ThinkPad" in txt and "AMD Radeon 780M (amdgpu)" in txt
    assert "ashu-pc" not in txt and "infinite4evr" not in txt and "192.168.x.x" in txt
    assert "all up to date" in txt and "12 snaps, 3 flatpaks" in txt
    html = report.build_html(d, redacted=False)
    assert html.startswith("<!doctype html>") and "ashu-pc" in html and "<script" not in html and "http" not in html.split("<style>")[0]
    shared = report.build_html(d, redacted=True)
    assert "ashu-pc" not in shared and "prefers-color-scheme: dark" in shared


def _fake_tree(root, layout):
    setup = root / ("ubuntu-setup" if layout == "split" else "linux-setup")
    setup.mkdir(parents=True)
    (setup / "setup.sh").write_text("#!/bin/bash\n")
    app = root / "pc-command-center" if layout == "split" else setup / "pc"
    (app / "src/pcctl").mkdir(parents=True)
    (app / "src/pcctl/__init__.py").write_text('__version__ = "9.9.9"\n')
    return setup, app


def test_update_source_found_next_to_ubuntu_setup(tmp_path, monkeypatch):
    from pcctl.core import selfupdate
    setup, app = _fake_tree(tmp_path, "split")
    monkeypatch.setattr(maint, "config", lambda: {"setup_dir": str(setup)})
    assert maint.setup_dir() == setup
    assert selfupdate.source_dir() == app


def test_update_source_still_found_in_old_linux_setup_layout(tmp_path, monkeypatch):
    from pcctl.core import selfupdate
    setup, app = _fake_tree(tmp_path, "legacy")
    monkeypatch.setattr(maint, "config", lambda: {"setup_dir": str(setup)})
    assert selfupdate.source_dir() == app
