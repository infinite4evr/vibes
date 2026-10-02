"""Parsers against real-world command output (Ubuntu 24.04/26.04 formats)."""

from pcctl.core import dev, junk, logs, network, packages, services, system


def test_ss():
    text = """\
tcp   LISTEN 0      511        127.0.0.1:3000       0.0.0.0:*    users:(("node",pid=4242,fd=21))
tcp   LISTEN 0      4096   127.0.0.53%lo:53         0.0.0.0:*    users:(("systemd-resolve",pid=812,fd=15))
tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*    users:(("sshd",pid=1001,fd=3))
tcp   LISTEN 0      128             [::]:22            [::]:*    users:(("sshd",pid=1001,fd=4))
tcp   LISTEN 0      511                *:5173             *:*    users:(("node",pid=5000,fd=30))
tcp   ESTAB  0      0        192.168.1.5:5555   1.2.3.4:443
udp   UNCONN 0      0            0.0.0.0:5353       0.0.0.0:*    users:(("avahi-daemon",pid=700,fd=12))
tcp   LISTEN 0      4096           [::1]:631           [::]:*
"""
    ports = network.parse_ss(text)
    by = {(p.proto, p.port, p.exposed): p for p in ports}
    assert by[("tcp", 3000, False)].process == "node" and by[("tcp", 3000, False)].pid == 4242
    assert by[("tcp", 53, False)].address == "127.0.0.53"
    assert by[("tcp", 22, True)].process == "sshd"
    assert by[("tcp", 5173, True)].kind == "Node"
    assert by[("udp", 5353, True)].process == "avahi-daemon"
    assert by[("tcp", 631, False)].pid is None
    assert not any(p.port == 5555 for p in ports)  # established connections are not listeners
    assert sum(1 for p in ports if p.port == 22) == 1  # v4+v6 duplicates collapse


def test_apt_upgradable():
    text = """\
Listing...
firefox/noble-updates 1:1snap1-0ubuntu5 amd64 [upgradable from: 1:1snap1-0ubuntu4]
libssl3t64/noble-security,noble-updates 3.0.13-0ubuntu3.5 amd64 [upgradable from: 3.0.13-0ubuntu3.4]
code/stable 1.104.0-1758000000 amd64 [upgradable from: 1.103.2-1757000000]
"""
    ups = packages.parse_apt_upgradable(text)
    assert [u.name for u in ups] == ["firefox", "libssl3t64", "code"]
    assert ups[1].security and not ups[0].security
    assert ups[2].current == "1.103.2-1757000000" and ups[2].new == "1.104.0-1758000000"


def test_snap_refresh_and_list():
    assert packages.parse_snap_refresh("All snaps up to date.") == []
    ups = packages.parse_snap_refresh("Name     Version  Rev   Size   Publisher  Notes\nfirefox  143.0    6800  260MB  mozilla✓   -\n")
    assert ups[0].name == "firefox" and ups[0].new == "143.0"
    text = """\
Name                       Version          Rev    Tracking         Publisher      Notes
anki-desktop               25.02.5          120    latest/stable    ankitects      -
bare                       1.0              5      latest/stable    canonical✓     base
core22                     20250822         2133   latest/stable    canonical✓     base
firmware-updater           0+git.22198be    167    1/stable/…       canonical✓     -
gnome-42-2204              0+git.38ea591    202    latest/stable    canonical✓     -
snap-store                 0+git.ad8a3e5    1270   2/stable/…       canonical✓     -
snapd                      2.71             25202  latest/stable    canonical✓     snapd
"""
    names = [a.id for a in packages.parse_snap_list(text)]
    assert names == ["anki-desktop", "firmware-updater", "snap-store"]


def test_flatpak():
    ups = packages.parse_flatpak_updates("org.telegram.desktop\t6.1.3\ncom.spotify.Client\t1.2.60\n")
    assert [u.name for u in ups] == ["org.telegram.desktop", "com.spotify.Client"]
    apps = packages.parse_flatpak_list("org.telegram.desktop\tTelegram\t6.1.3\t312.4\xa0MB\tsystem\ncom.github.tchx84.Flatseal\tFlatseal\t2.3.0\t1.2 MB\tuser\n")
    assert apps[0].name == "Telegram" and apps[0].size == 312_400_000 and apps[0].location == "system"
    assert apps[1].location == "user"


def test_nmcli_wifi():
    text = "yes:HomeNet:82:WPA2\nno:HomeNet:40:WPA2\nno:Cafe\\:Guest:55:\nno::30:WPA2\nno:Neighbor:20:WPA1 WPA2\n"
    nets = network.parse_nmcli_wifi(text)
    assert nets[0]["ssid"] == "HomeNet" and nets[0]["active"] and nets[0]["signal"] == 82
    assert any(n["ssid"] == "Cafe:Guest" and n["security"] == "open" for n in nets)
    assert len([n for n in nets if n["ssid"] == "HomeNet"]) == 1


def test_upower():
    text = """\
  native-path:          BAT0
  vendor:               SMP
  model:                5B10W13930
  power supply:         yes
  battery
    present:             yes
    state:               discharging
    energy:              38,52 Wh
    energy-full:         45,6 Wh
    energy-full-design:  57 Wh
    energy-rate:         8,123 W
    time to empty:       4,7 hours
    percentage:          84%
    capacity:            80%
    technology:          lithium-polymer
    charge-cycles:       312
"""
    b = system.parse_upower(text)
    assert b["health"] == 80.0 and b["cycles"] == 312 and b["state"] == "discharging"
    assert b["rate"] == 8.123 and b["time_to_empty"] == "4,7 hours"


def test_boot():
    t = system.parse_boot_time("Startup finished in 7.310s (firmware) + 2.115s (loader) + 3.2s (kernel) + 1min 2.5s (userspace) = 1min 15.125s\ngraphical.target reached after 1min 2s in userspace.")
    assert round(t["total"], 3) == 75.125 and t["userspace"] == 62.5 and t["firmware"] == 7.31
    blame = system.parse_blame("  1min 3.120s plymouth-quit-wait.service\n     6.301s NetworkManager-wait-online.service\n   812ms snapd.service\n")
    assert blame[0] == (63.12, "plymouth-quit-wait.service") and blame[2] == (0.812, "snapd.service")


def test_pm2():
    text = 'some warning\n[{"name":"wa-bot","pm_id":0,"monit":{"memory":123456789,"cpu":2.5},"pm2_env":{"status":"online","pm_uptime":1700000000000,"restart_time":3,"pm_cwd":"/home/u/wa","pm_exec_path":"/home/u/wa/index.js"}}]'
    p = dev.parse_pm2(text)[0]
    assert p["name"] == "wa-bot" and p["status"] == "online" and p["restarts"] == 3 and p["mem"] == 123456789 and p["uptime"] > 0


def test_containers():
    podman = '[{"Id":"abc123def4567890","Names":["pg"],"Image":"docker.io/library/postgres:16","State":"running","Status":"Up 2 hours","Ports":[{"host_port":5432,"container_port":5432}]}]'
    c = dev.parse_containers(podman)[0]
    assert c["name"] == "pg" and c["state"] == "running" and c["ports"] == "5432→5432"
    docker = '{"ID":"0123456789ab","Names":"redis","Image":"redis:7","State":"exited","Status":"Exited (0) 3 days ago","Ports":""}\n'
    d = dev.parse_containers(docker)[0]
    assert d["name"] == "redis" and d["state"] == "exited"


def test_git_status():
    text = """\
# branch.oid 1234abcd
# branch.head main
# branch.upstream origin/main
# branch.ab +2 -1
1 .M N... 100644 100644 100644 aaa bbb src/app.js
2 R. N... 100644 100644 100644 ccc ddd R100 new.js\told.js
? notes.txt
? scratch/
"""
    s = dev.parse_git_status(text)
    assert s == {"branch": "main", "ahead": 2, "behind": 1, "changed": 2, "untracked": 2, "upstream": "origin/main"}


def test_systemctl():
    units = services.parse_units("""\
  accounts-daemon.service  loaded active   running Accounts Service
● cups.service             loaded failed   failed  CUPS Scheduler
  ModemManager.service     loaded inactive dead    Modem Manager
  foo.service              not-found inactive dead foo.service
""")
    assert [u.unit for u in units][:3] == ["accounts-daemon.service", "cups.service", "ModemManager.service"]
    assert units[1].active == "failed" and units[0].description == "Accounts Service"
    files = services.parse_unit_files("cups.service  enabled  enabled\nssh.service disabled enabled\n")
    assert files == {"cups.service": "enabled", "ssh.service": "disabled"}
    assert services.explain("NetworkManager.service").startswith("Keeps you connected")


def test_journal_json():
    text = '{"__REALTIME_TIMESTAMP":"1758700000000000","PRIORITY":"3","SYSLOG_IDENTIFIER":"gnome-shell","MESSAGE":"JS ERROR: something","_PID":"1234"}\n' \
           '{"__REALTIME_TIMESTAMP":"1758700001000000","PRIORITY":"2","_TRANSPORT":"kernel","MESSAGE":[104,105]}\n' \
           '{"__REALTIME_TIMESTAMP":"1758700002000000","PRIORITY":"3","SYSLOG_IDENTIFIER":"gnome-shell","MESSAGE":"another"}\n'
    lines = logs.parse_journal_json(text)
    assert lines[1].source == "kernel" and lines[1].message == "hi"
    g = logs.grouped(lines, hide_noise=False)
    assert g[0]["source"] == "kernel" and g[1]["count"] == 2 and g[1]["message"] == "another"


def test_junk_parsers():
    assert junk.parse_autoremove("NOTE: This is only a simulation!\nRemv linux-image-6.8.0-40-generic [6.8.0-40.40]\nRemv libfoo1 [1.2]\n") == ["linux-image-6.8.0-40-generic", "libfoo1"]
    assert junk.parse_journal_usage("Archived and active journals take up 1.2G in the file system.") == int(1.2 * 1024**3)
    assert junk.parse_snap_disabled("Name Version Rev Tracking Publisher Notes\nfirefox 142 6700 latest/stable mozilla✓ disabled\nfirefox 143 6800 latest/stable mozilla✓ -\n") == [("firefox", "6700")]


def test_storage_parse_du():
    from pcctl.core import storage
    items = storage.parse_du("100\t/tmp/x/a\n300\t/tmp/x/b\n400\t/tmp/x\n", "/tmp/x")
    assert [e.name for e in items] == ["b", "a"]


def test_apt_history():
    text = """Start-Date: 2026-09-20  10:01:02
Commandline: apt-get install -y ghostty
Requested-By: ashu (1000)
Install: ghostty:amd64 (1.3.0~us1-0ubuntu1), libfoo:amd64 (1.0, automatic)
End-Date: 2026-09-20  10:01:30

Start-Date: 2026-09-21  06:12:00
Upgrade: libssl3t64:amd64 (3.0.13-0ubuntu3.4, 3.0.13-0ubuntu3.5)
End-Date: 2026-09-21  06:12:10
"""
    h = packages.parse_apt_history(text)
    assert h[0]["installed"] == ["ghostty", "libfoo"] and "[ashu" in h[0]["cmd"]
    assert h[1]["upgraded"] == ["libssl3t64"] and h[1]["cmd"].startswith("automatic")


def test_dupes(tmp_path):
    from pcctl.core import dupes
    a = tmp_path / "a"
    a.mkdir()
    data = b"x" * (2 * 1024 * 1024)
    (a / "one.bin").write_bytes(data)
    (a / "two.bin").write_bytes(data)
    (a / "three.bin").write_bytes(data[:-1] + b"y")
    groups = dupes.find_duplicates([tmp_path])
    assert len(groups) == 1 and len(groups[0]) == 2


def test_rm_guard(tmp_path):
    from pcctl.core import junk
    msg = junk._rm_paths(["/etc/hostname", "/"])()
    assert "skipped" in msg


def test_ufw_rules_parse():
    from pcctl.core.security import parse_ufw_rules
    text = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 3000/tcp                   ALLOW IN    192.168.0.0/16
[ 3] 22/tcp (v6)                ALLOW IN    Anywhere (v6)
"""
    rules = parse_ufw_rules(text)
    assert [r["num"] for r in rules] == [1, 2, 3]
    assert rules[1]["to"] == "3000/tcp" and rules[1]["from"] == "192.168.0.0/16" and rules[1]["action"] == "ALLOW"


def test_privacy_int_setting_parses_uint32(monkeypatch):
    from pcctl.core import privacy
    s = privacy.Setting("idle", "Blank", "", "org.gnome.desktop.session", "idle-delay", kind="int")
    monkeypatch.setattr(privacy, "out", lambda cmd, **kw: "uint32 300")
    assert s.read().value == 300


def test_github_url():
    import importlib.util
    if importlib.util.find_spec("gi") is None:
        return
    try:
        from pcctl.gui.pages.dev import github_url
    except Exception:  # GTK not importable in this environment
        return
    assert github_url("git@github.com:me/proj.git") == "https://github.com/me/proj"
    assert github_url("https://github.com/me/proj.git") == "https://github.com/me/proj"
    assert github_url("") == ""
