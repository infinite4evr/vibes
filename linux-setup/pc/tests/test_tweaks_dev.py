"""Tweaks + Developer pages: parsers and the exact Steps actions would run (nothing here changes the system)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from pcctl.core import desktop, dev, devsetup, extensions, shortcuts, tweaks

FX = Path(__file__).parent / "fixtures" / "tweaksdev"


def fx(name: str) -> str:
    return (FX / name).read_text()


# ---------------------------------------------------------------- O1 GNOME extensions

def test_parse_extension_details():
    items = extensions.parse_details(fx("gnome-extensions-details.txt"))
    by = {e.uuid: e for e in items}
    assert list(by) == ["ubuntu-dock@ubuntu.com", "ding@rastersoft.com", "blur-my-shell@aunetx", "clipboard-indicator@tudmotu.com",
                        "caffeine@patapon.info", "gsconnect@andyholmes.github.io"]
    dock = by["ubuntu-dock@ubuntu.com"]
    assert dock.name == "Ubuntu Dock" and dock.enabled and dock.state == "ACTIVE" and dock.version == "101"
    assert dock.builtin and not dock.user and "Dock tab" in dock.friendly
    assert not by["ding@rastersoft.com"].enabled and by["ding@rastersoft.com"].builtin
    blur = by["blur-my-shell@aunetx"]
    assert blur.user and not blur.builtin and blur.version == "1.2 (68)"
    assert "sponsoring me" in blur.description and "github.com/sponsors" in blur.description  # description kept across lines
    assert blur.path.endswith("blur-my-shell@aunetx")
    assert by["clipboard-indicator@tudmotu.com"].state_kind == "bad" and "crashed" in by["clipboard-indicator@tudmotu.com"].problem
    assert by["caffeine@patapon.info"].state_text == "needs an update"
    gs = by["gsconnect@andyholmes.github.io"]
    assert not gs.user and not gs.builtin and "package" in extensions.remove_blocker(gs)
    assert extensions.remove_blocker(dock).startswith("This one is part of Ubuntu")
    assert extensions.remove_steps(dock) == []


def test_extension_steps():
    e = extensions.Extension("blur-my-shell@aunetx", name="Blur my Shell", user=True)
    assert [s.cmd for s in extensions.toggle_steps(e, True)] == [["gnome-extensions", "enable", "blur-my-shell@aunetx"]]
    assert [s.cmd for s in extensions.toggle_steps("x@y", False)] == [["gnome-extensions", "disable", "x@y"]]
    rm = extensions.remove_steps(e)
    assert rm[-1].cmd == ["gnome-extensions", "uninstall", "blur-my-shell@aunetx"] and not any(s.root for s in rm)
    assert extensions.prefs_cmd(e) == ["gnome-extensions", "prefs", "blur-my-shell@aunetx"]
    assert extensions.global_steps(False)[0].cmd == ["gsettings", "set", "org.gnome.shell", "disable-user-extensions", "true"]
    assert extensions.global_steps(True)[0].cmd[-1] == "false"
    on_not_running = extensions.Extension("a@b", enabled=True, state="INACTIVE")
    assert "log out" in on_not_running.problem


def test_scan_extension_dirs(tmp_path):
    user = tmp_path / "user"
    system = tmp_path / "system"
    for base, uuid, name, prefs in ((user, "caffeine@patapon.info", "Caffeine", True), (system, "ubuntu-dock@ubuntu.com", "Ubuntu Dock", True),
                                    (system, "ding@rastersoft.com", "DING", False), (system, "caffeine@patapon.info", "Old copy", False)):
        d = base / uuid
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(f'{{"uuid": "{uuid}", "name": "{name}", "version": 7}}')
        if prefs:
            (d / "prefs.js").write_text("")
    (system / "broken@x").mkdir()  # no metadata.json -> ignored
    items = extensions.scan_dirs(user, [system], enabled={"caffeine@patapon.info"}, disabled={"ding@rastersoft.com"},
                                 mode={"ubuntu-dock@ubuntu.com", "ding@rastersoft.com"})
    by = {e.uuid: e for e in items}
    assert set(by) == {"caffeine@patapon.info", "ubuntu-dock@ubuntu.com", "ding@rastersoft.com"}
    assert by["caffeine@patapon.info"].name == "Caffeine" and by["caffeine@patapon.info"].user  # user copy wins
    assert by["caffeine@patapon.info"].enabled and by["caffeine@patapon.info"].has_prefs
    assert by["ubuntu-dock@ubuntu.com"].enabled and by["ubuntu-dock@ubuntu.com"].builtin  # on through the Ubuntu session mode
    assert not by["ding@rastersoft.com"].enabled  # explicitly disabled
    paused = extensions.scan_dirs(user, [system], {"caffeine@patapon.info"}, set(), set(), user_off=True)
    assert not {e.uuid: e for e in paused}["caffeine@patapon.info"].enabled


def test_mode_extensions(tmp_path):
    (tmp_path / "ubuntu.json").write_text('{"parentMode": "user", "enabledExtensions": ["ubuntu-dock@ubuntu.com", "ding@rastersoft.com"]}')
    (tmp_path / "bad.json").write_text("{not json")
    assert extensions.mode_extensions(tmp_path) == {"ubuntu-dock@ubuntu.com", "ding@rastersoft.com"}


def test_parse_strv():
    assert extensions.parse_strv("@as []") == []
    assert extensions.parse_strv("['a@b', 'c@d']") == ["a@b", "c@d"]
    assert extensions.parse_strv("garbage") == []


# ---------------------------------------------------------------- O2 shortcuts

def test_accelerators():
    assert shortcuts.pretty("<Control><Shift>Escape") == "Ctrl+Shift+Esc"
    assert shortcuts.pretty("<Primary><Alt>t") == "Ctrl+Alt+T"
    assert shortcuts.pretty("<Super>Return") == "Super+Enter"
    assert shortcuts.pretty("") == "" and shortcuts.pretty("disabled") == ""
    assert shortcuts.same_accel("<Ctrl><Shift>Escape", "<Shift><Control>escape")
    assert not shortcuts.same_accel("<Super>t", "<Super><Shift>t")
    assert shortcuts.valid_accel("<Super>t") and shortcuts.valid_accel("F12") and shortcuts.valid_accel("<Control><Alt>Delete")
    assert not shortcuts.valid_accel("<Super>") and not shortcuts.valid_accel("Ctrl+T") and not shortcuts.valid_accel("")


def test_find_conflicts():
    text = ("org.gnome.desktop.wm.keybindings close ['<Alt>F4']\n"
            "org.gnome.settings-daemon.plugins.media-keys home ['<Super>e']\n"
            "org.gnome.settings-daemon.plugins.media-keys custom-keybindings ['/x/']\n"
            "org.gnome.shell.keybindings toggle-overview @as []\n"
            "org.gnome.mutter.keybindings toggle-tiled-left ['<Super>Left']\n"
            "org.gnome.settings-daemon.plugins.media-keys logout '<Control><Alt>Delete'\n")
    settings = shortcuts.parse_list_recursively(text)
    assert settings[("org.gnome.desktop.wm.keybindings", "close")] == "['<Alt>F4']"
    custom = [shortcuts.Shortcut("/p/custom0/", "Terminal", "ghostty", "<Super>Return")]
    assert shortcuts.find_conflicts("<Super>e", settings, custom) == ["GNOME: home"]
    assert shortcuts.find_conflicts("<Primary><Alt>Delete", settings, custom) == ["GNOME: logout"]
    assert shortcuts.find_conflicts("<Super>Return", settings, custom) == ["Your shortcut “Terminal”"]
    assert shortcuts.find_conflicts("<Super>Return", settings, custom, skip_path="/p/custom0/") == []
    assert shortcuts.find_conflicts("<Control><Shift>Escape", settings, custom) == []


def test_shortcut_steps_append_and_remove_only_ours():
    mine = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
    steps = shortcuts.add_steps([mine], "pc-taskmgr", "Open Processes (task manager)", "/home/u/.local/bin/pc-gui --page processes",
                                "<Control><Shift>Escape")
    loc = f"{shortcuts.CK}:{shortcuts.BASE}pc-taskmgr/"
    assert steps[0].cmd == ["gsettings", "set", loc, "name", "Open Processes (task manager)"]
    assert steps[1].cmd == ["gsettings", "set", loc, "command", "/home/u/.local/bin/pc-gui --page processes"]
    assert steps[2].cmd == ["gsettings", "set", loc, "binding", "<Control><Shift>Escape"]
    new_list = steps[3].cmd[-1]
    assert steps[3].cmd[:4] == ["gsettings", "set", shortcuts.MK, "custom-keybindings"]
    assert extensions.parse_strv(new_list) == [mine, f"{shortcuts.BASE}pc-taskmgr/"]  # the user's own shortcut stays first
    assert not any(s.root for s in steps)
    # adding again (edit) doesn't duplicate the list entry
    again = shortcuts.add_steps([mine, f"{shortcuts.BASE}pc-taskmgr/"], "pc-taskmgr", "x", "y", "<Super>y")
    assert len(again) == 3
    rm = shortcuts.remove_steps([mine, f"{shortcuts.BASE}pc-taskmgr/"], f"{shortcuts.BASE}pc-taskmgr/")
    assert extensions.parse_strv(rm[0].cmd[-1]) == [mine]
    assert all(s.cmd[:3] == ["gsettings", "reset", loc] for s in rm[1:]) and all(s.optional for s in rm[1:])
    assert shortcuts.remove_steps([f"{shortcuts.BASE}pc-taskmgr/"], f"{shortcuts.BASE}pc-taskmgr/")[0].cmd[-1] == "@as []"


def test_shortcut_quoting_and_ids():
    assert shortcuts._q("Open 'stuff'") == "Open 'stuff'"            # plain text is fine for gsettings string keys
    assert shortcuts._q("'quoted'") == "'\\'quoted\\''"               # starts with a quote -> GVariant quoting
    assert shortcuts.strv(["/a/", "/b'c/"]) == "['/a/', '/b\\'c/']"
    assert shortcuts.new_id(["/x/pc-custom0/", "/x/pc-custom1/", "/x/custom0/"]) == "pc-custom2"
    assert shortcuts.gv_string("'Open Processes'") == "Open Processes"
    assert shortcuts.gv_string('"Ashu\'s terminal"') == "Ashu's terminal"
    assert shortcuts.gv_string("''") == "" and shortcuts.gv_string("plain") == "plain"
    assert shortcuts.accels_in('"<Super>e"') == ["<Super>e"] and shortcuts.accels_in("''") == []
    s = shortcuts.Shortcut(f"{shortcuts.BASE}pc-custom0/", "n", "c", "<Super>t")
    assert s.ours and s.id == "pc-custom0" and s.keys == "Super+T"
    assert not shortcuts.Shortcut(f"{shortcuts.BASE}custom3/", "n", "c", "").ours


def test_shortcut_presets_and_commands():
    ps = shortcuts.presets()
    assert ps[0]["id"] == shortcuts.TASKMGR_ID and ps[0]["binding"] == "<Control><Shift>Escape"
    assert ps[0]["command"].endswith("pc-gui --page processes")
    assert shortcuts.command_ok("sh -c true") == ""
    assert "wasn't found" in shortcuts.command_ok("definitely-not-a-program-xyz --flag")
    assert shortcuts.command_ok("") == "Type a command to run."
    assert "quote" in shortcuts.command_ok("echo 'oops")


# ---------------------------------------------------------------- O3-O5 desktop options

def _values():
    D = desktop.DOCK
    return {(D, "dock-position"): "'BOTTOM'", (D, "dash-max-icon-size"): "48", (D, "dock-fixed"): "false", (D, "autohide"): "true",
            (D, "intellihide"): "true", (D, "extend-height"): "false", (D, "show-trash"): "true", (D, "click-action"): "'cycle-windows'",
            (desktop.GTK4_FC, "show-hidden"): "false", (desktop.GTK3_FC, "show-hidden"): "false", (desktop.WM, "button-layout"): "'appmenu:close'",
            (D, "running-indicator-style"): "'CILIORA'"}


def test_option_current_values():
    v = _values()
    by = {o.id: o for o in desktop.ALL_OPTS}
    assert desktop.current(by["dock-pos"], v) == 0                  # Bottom
    assert desktop.current(by["dock-size"], v) == 48.0
    assert desktop.current(by["dock-hide"], v) == 1                 # hides when a window is near
    assert desktop.current(by["dock-trash"], v) is True
    assert desktop.current(by["dock-extend"], v) is False
    assert desktop.current(by["dock-click"], v) == 3
    assert desktop.current(by["dock-dots"], v) == -1                # a style we don't list -> "custom"
    assert desktop.current(by["win-buttons"], v) == 2               # close only
    assert desktop.present(by["files-hidden"], v) == [(desktop.GTK4_FC, "show-hidden"), (desktop.GTK3_FC, "show-hidden")]
    assert desktop.present(by["files-perm-delete"], v) == []         # no Nautilus schema -> option skipped
    assert desktop.current(by["files-perm-delete"], v) is None
    assert desktop.norm("uint32 48") == desktop.norm("48") and desktop.norm("0.80000000000000004") == desktop.norm("0.8")


def test_option_steps():
    v = _values()
    by = {o.id: o for o in desktop.ALL_OPTS}
    hide = desktop.set_steps(by["dock-hide"], 2, v)
    assert [s.cmd for s in hide] == [["gsettings", "set", desktop.DOCK, "dock-fixed", "false"], ["gsettings", "set", desktop.DOCK, "autohide", "true"],
                                     ["gsettings", "set", desktop.DOCK, "intellihide", "false"]]
    assert desktop.set_steps(by["dock-hide"], 0, v)[0].cmd[-2:] == ["dock-fixed", "true"]
    assert desktop.set_steps(by["dock-pos"], 1, v)[0].cmd == ["gsettings", "set", desktop.DOCK, "dock-position", "LEFT"]
    assert desktop.set_steps(by["dock-size"], 99, v)[0].cmd[-1] == "64"   # clamped to the allowed range
    hidden = desktop.set_steps(by["files-hidden"], True, v)
    assert [s.cmd[2:] for s in hidden] == [[desktop.GTK4_FC, "show-hidden", "true"], [desktop.GTK3_FC, "show-hidden", "true"]]
    assert desktop.set_steps(by["win-buttons"], 0, v)[0].cmd[-1] == "appmenu:minimize,maximize,close"
    assert not any(s.root for s in hidden + hide)
    reset = desktop.reset_steps(desktop.DOCK_OPTS)
    assert ["gsettings", "reset", desktop.DOCK, "intellihide"] in [s.cmd for s in reset]
    assert len({tuple(s.cmd) for s in reset}) == len(reset)
    assert len({o.id for o in desktop.ALL_OPTS}) == len(desktop.ALL_OPTS)


def test_desktop_switches_compat():
    ids = [s.id for s in tweaks.DESKTOP]
    assert len(ids) == len(set(ids)) and "clock-24h" in ids
    assert all(s.title and s.group for s in tweaks.DESKTOP)        # the window's command palette uses these
    s = next(s for s in tweaks.DESKTOP if s.id == "clock-24h")
    assert tweaks.switch_steps(s, True)[0].cmd == ["gsettings", "set", "org.gnome.desktop.interface", "clock-format", "'24h'"]
    assert desktop.norm("'24h'") == desktop.norm(s.on)


def test_run_quiet():
    from pcctl.core.run import Step, py_step
    ok, lines = desktop.run_quiet([Step("say", ["echo", "hello"]), py_step("py", lambda: "from python", "shown")])
    assert ok and lines == ["hello", "from python"]
    ok, _ = desktop.run_quiet([Step("fail", ["false"], optional=True), Step("ok", ["true"])])
    assert ok
    ok, _ = desktop.run_quiet([Step("fail", ["false"]), Step("never", ["echo", "x"])])
    assert not ok
    ok, lines = desktop.run_quiet([Step("admin", ["true"], root=True)])
    assert not ok and "admin" in lines[0]


# ---------------------------------------------------------------- O6 name and time

def test_hostname_rules_and_steps(tmp_path):
    assert desktop.hostname_problem("ashu-pc") == ""
    assert "letters" in desktop.hostname_problem("ashu pc")
    assert "dash" in desktop.hostname_problem("-ashu")
    assert desktop.hostname_problem("") and desktop.hostname_problem("x" * 64) and desktop.hostname_problem("1234")
    assert desktop.suggest_hostname("Ashu's Laptop 2") == "ashus-laptop-2"
    steps = desktop.hostname_steps("ashu-pc")
    assert steps[0].cmd == ["hostnamectl", "set-hostname", "ashu-pc"] and all(s.root for s in steps)
    assert desktop.hostname_steps("bad name") == []
    with pytest.raises(ValueError):
        desktop.hosts_cmd("x; rm -rf /")
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n127.0.1.1\told-name\n::1\tip6-localhost\n")
    subprocess.run(desktop.hosts_cmd("ashu-pc", str(hosts)), check=True)
    assert hosts.read_text() == "127.0.0.1\tlocalhost\n127.0.1.1\tashu-pc\n::1\tip6-localhost\n"
    hosts.write_text("127.0.0.1\tlocalhost\n")
    subprocess.run(desktop.hosts_cmd("ashu-pc", str(hosts)), check=True)
    assert hosts.read_text() == "127.0.0.1\tlocalhost\n127.0.1.1\tashu-pc\n"


def test_time_parsers():
    kv = desktop.parse_kv("Timezone=Asia/Kolkata\nLocalRTC=no\nNTP=yes\nNTPSynchronized=yes\nTimeUSec=Thu 2026-09-24\n")
    assert kv["Timezone"] == "Asia/Kolkata" and kv["NTP"] == "yes"
    assert desktop.parse_zone_tab(fx("zone1970.tab")) == ["America/New_York", "Asia/Dubai", "Asia/Kolkata", "Europe/Berlin"]
    t = desktop.parse_chrony_tracking(fx("chronyc-tracking.txt"))
    assert t["synced"] and t["source"] == "time.cloudflare.com" and t["offset"] == "0.2 ms slow" and t["leap"] == "Normal"
    u = desktop.parse_chrony_tracking(fx("chronyc-tracking-unsynced.txt"))
    assert not u["synced"]
    assert desktop.timezone_steps("Asia/Kolkata")[0].cmd == ["timedatectl", "set-timezone", "Asia/Kolkata"]
    assert desktop.ntp_steps(True)[0].cmd == ["timedatectl", "set-ntp", "true"] and desktop.ntp_steps(True)[0].root
    auto = desktop.auto_tz_steps(True)[0]
    assert auto.cmd == ["gsettings", "set", "org.gnome.desktop.datetime", "automatic-timezone", "true"] and not auto.root


# ---------------------------------------------------------------- P1 PATH doctor

def _exe(path: Path, version_line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_path_report(tmp_path):
    usr = tmp_path / "usr/bin"
    nvm = tmp_path / ".nvm/versions/node/v22.18.0/bin"
    _exe(usr / "node", "v18.19.1")
    _exe(nvm / "node", "v22.18.0")
    _exe(nvm / "npm", "10.9.3")
    _exe(usr / "git", "git version 2.51.0")
    (usr / "git-link").symlink_to(usr / "git")
    path = ":".join([str(usr), str(nvm), str(tmp_path / "gone"), str(usr), ""])
    rep = devsetup.path_report(path, session_path=str(usr), tools=["node", "npm", "git", "python3"])
    entries = rep["entries"]
    assert [e["exists"] for e in entries] == [True, True, False, True, False]
    assert entries[3]["dup_of"] == 0 and entries[4]["relative"]
    assert [e["dir"] for e in rep["missing"]] == [str(tmp_path / "gone")]
    tools = {t["name"]: t["copies"] for t in rep["tools"]}
    assert [c["version"] for c in tools["node"]] == ["18.19.1", "22.18.0"] and tools["node"][0]["wins"]
    assert tools["git"][0]["version"] == "2.51.0" and len(tools["git"]) == 1  # same file twice on PATH counts once
    assert tools["python3"] == []
    assert rep["terminal_only"] == [str(nvm), str(tmp_path / "gone")]
    levels = [lvl for lvl, _ in rep["tips"]]
    text = " ".join(t for _, t in rep["tips"])
    assert "bad" in levels and "security hole" in text               # empty PATH entry
    assert "2 copies of node" in text and "(18.19.1) is the one that runs" in text
    assert "doesn't exist" in text and "more than once" in text and "Only your terminal sees" in text


def test_path_tips_nvm_shadowed_and_clean():
    rep = {"entries": [{"dir": "/usr/bin", "dup_of": None, "exists": True, "relative": False}], "missing": [], "dups": [], "relative": [],
           "terminal_only": [],
           "tools": [{"name": "node", "copies": [
               {"path": "/usr/bin/node", "shown": "/usr/bin/node", "version": "18.19.1", "real": "/usr/bin/node"},
               {"path": "/home/u/.nvm/versions/node/v22.18.0/bin/node", "shown": "~/.nvm/versions/node/v22.18.0/bin/node", "version": "22.18.0",
                "real": "/home/u/.nvm/versions/node/v22.18.0/bin/node"}]}]}
    tips = devsetup.path_tips(rep)
    assert any(lvl == "warn" and "beating nvm" in t for lvl, t in tips)
    clean = {"entries": [], "missing": [], "dups": [], "relative": [], "terminal_only": [], "tools": []}
    assert [lvl for lvl, _ in devsetup.path_tips(clean)] == ["ok"] or all(lvl in ("ok", "warn") for lvl, _ in devsetup.path_tips(clean))


def test_path_helpers():
    assert devsetup.extract_path("Welcome to fastfetch!\n\n__PCPATH__/a:/b\n") == "/a:/b"
    assert devsetup.extract_path("no marker") == ""
    assert devsetup.parse_version("go version go1.24.7 linux/amd64") == "1.24.7"
    assert devsetup.parse_version('openjdk version "21.0.4" 2024-07-16') == "21.0.4"
    assert devsetup.parse_version("Python 3.14.0rc2") == "3.14.0rc2"
    assert devsetup.parse_version("v22.18.0") == "22.18.0"


# ---------------------------------------------------------------- P3 GitHub

def test_gh_status_formats():
    new = devsetup.parse_gh_status(fx("gh-auth-status-new.txt"))
    assert new["logged_in"] and new["account"] == "infinite4evr" and new["protocol"] == "ssh" and new["source"] == "keyring"
    assert new["scopes"] == ["gist", "read:org", "repo", "workflow"] and devsetup.needs_key_scope(new["scopes"])
    old = devsetup.parse_gh_status(fx("gh-auth-status-old.txt"))
    assert old["logged_in"] and old["protocol"] == "https" and not devsetup.needs_key_scope(old["scopes"])
    bad = devsetup.parse_gh_status(fx("gh-auth-status-bad.txt"))
    assert not bad["logged_in"] and "Log in again" in bad["error"]
    none = devsetup.parse_gh_status("You are not logged into any GitHub hosts. To log in, run: gh auth login")
    assert not none["logged_in"] and none["error"]
    assert not devsetup.needs_key_scope([])


def test_ssh_test_parse():
    ok = devsetup.parse_ssh_test(1, "Hi infinite4evr! You've successfully authenticated, but GitHub does not provide shell access.")
    assert ok["ok"] and ok["user"] == "infinite4evr"
    assert "Upload your key" in devsetup.parse_ssh_test(255, "git@github.com: Permission denied (publickey).")["message"]
    assert "internet" in devsetup.parse_ssh_test(255, "ssh: Could not resolve hostname github.com: Temporary failure")["message"]
    assert "known_hosts" in devsetup.parse_ssh_test(255, "Host key verification failed.")["message"]


def test_ssh_keys_and_steps(tmp_path):
    d = tmp_path / ".ssh"
    d.mkdir()
    (d / "id_ed25519.pub").write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample ashu@ashu-pc\n")
    (d / "id_ed25519").write_text("private")
    (d / "old_rsa.pub").write_text("ssh-rsa AAAAB3Nza\n")
    (d / "junk.pub").write_text("\n")
    keys = devsetup.ssh_keys(d)
    assert [(Path(k.path).name, k.type, k.comment, k.private) for k in keys] == [
        ("id_ed25519.pub", "ssh-ed25519", "ashu@ashu-pc", True), ("old_rsa.pub", "ssh-rsa", "", False)]
    assert keys[0].kind.startswith("Ed25519")
    assert devsetup.keygen_steps("a@b.c", str(d / "id_ed25519")) == []  # never overwrites a key
    new = devsetup.keygen_steps("a@b.c", str(d / "id_new"))
    assert new[-1].cmd == ["ssh-keygen", "-t", "ed25519", "-C", "a@b.c", "-f", str(d / "id_new"), "-N", ""]
    assert "-N" not in devsetup.keygen_cmd("a@b.c", str(d / "k"), passphrase=True)
    up = devsetup.upload_key_steps(str(d / "id_ed25519.pub"), title="ashu-pc")
    assert up[0].cmd == ["gh", "ssh-key", "add", str(d / "id_ed25519.pub"), "--title", "ashu-pc"]
    sign = devsetup.upload_key_steps(str(d / "id_ed25519.pub"), title="ashu-pc", signing=True)
    assert sign[0].cmd[-2:] == ["--type", "signing"]


# ---------------------------------------------------------------- P4 git config

def test_git_config_parse_and_steps():
    z = "user.name\nAshu\0user.email\nashu@example.com\0credential.https://github.com.helper\n\0credential.https://github.com.helper\n!/usr/bin/gh auth git-credential\0pull.rebase\nfalse\0"
    cfg = devsetup.parse_git_config(z)
    assert devsetup.gget(cfg, "user.name") == "Ashu" and devsetup.gget(cfg, "User.Email") == "ashu@example.com"
    assert devsetup.credential_helper(cfg) == "gh" and devsetup.pull_mode(cfg) == "merge"
    plain = devsetup.parse_git_config("user.name=Ashu Kumar\ncore.editor=code --wait\npull.ff=only\nalias.lg=log --graph --format=%h=%s\n")
    assert devsetup.gget(plain, "alias.lg") == "log --graph --format=%h=%s" and devsetup.pull_mode(plain) == "ff-only"
    assert devsetup.credential_helper({"credential.helper": ["cache --timeout=3600"]}) == "cache"
    assert devsetup.pull_mode({}) == ""
    steps = devsetup.pull_steps("ff-only")
    assert [s.cmd for s in steps] == [["git", "config", "--global", "pull.ff", "only"], ["git", "config", "--global", "--unset-all", "pull.rebase"]]
    assert steps[1].ok_codes == (0, 5)  # unsetting a key that isn't set is fine
    assert devsetup.git_set("user.email", "x@y.z").cmd == ["git", "config", "--global", "user.email", "x@y.z"]
    sig = devsetup.signing_steps("/h/.ssh/id_ed25519.pub", True)
    assert [s.cmd[3:] for s in sig] == [["gpg.format", "ssh"], ["user.signingkey", "/h/.ssh/id_ed25519.pub"], ["commit.gpgsign", "true"],
                                        ["tag.gpgsign", "true"]]
    assert devsetup.signing_state({"commit.gpgsign": ["true"], "gpg.format": ["ssh"]})["on"]
    assert all(k and v and t and w for k, v, t, w in devsetup.GIT_SWITCHES)


# ---------------------------------------------------------------- P5 global packages

def test_global_package_parsers():
    npm = devsetup.parse_npm_ls(fx("npm-ls.json"))
    assert [(p.name, p.version, p.removable) for p in npm] == [("corepack", "0.33.0", False), ("npm", "11.4.2", False), ("pm2", "6.0.8", True),
                                                                ("typescript", "5.9.2", True)]
    pnpm = devsetup.parse_pnpm_ls(fx("pnpm-ls.json"))
    assert pnpm[0].name == "vercel" and pnpm[0].version == "44.2.0" and pnpm[0].path.endswith("node_modules/vercel")
    assert devsetup.parse_pnpm_ls('[{"path": "/x", "private": false}]') == []
    pipx = devsetup.parse_pipx_list("nothing has been installed with pipx 😴\n" + fx("pipx-list.json"))
    assert pipx[0].name == "gnome-extensions-cli" and pipx[0].version == "0.10.4" and "gext" in pipx[0].note
    uv = devsetup.parse_uv_tools(fx("uv-tool-list.txt"))
    assert [(p.name, p.version) for p in uv] == [("black", "26.3.1"), ("ruff", "0.15.11")]
    assert uv[0].note == "black, blackd" and uv[0].path.endswith("uv/tools/black")
    assert devsetup.parse_uv_tools("No tools installed") == []
    cargo = devsetup.parse_cargo_list(fx("cargo-install-list.txt"))
    assert [(p.name, p.version, p.note) for p in cargo] == [("cargo-watch", "8.5.2", "cargo-watch"), ("ripgrep", "14.1.0", "rg"), ("zoxide", "0.9.4", "zoxide")]
    out = devsetup.parse_npm_outdated(fx("npm-outdated.json"))
    assert out["typescript"]["latest"] == "6.0.3"
    assert devsetup.parse_npm_outdated("") == {}


def test_global_package_steps():
    G = devsetup.GlobalPkg
    assert devsetup.uninstall_steps(G("npm", "npm", removable=False)) == []
    assert devsetup.uninstall_steps(G("pipx", "gnome-extensions-cli", extra={"venv": "gnome-extensions-cli"}))[0].cmd == ["pipx", "uninstall", "gnome-extensions-cli"]
    assert devsetup.uninstall_steps(G("uv", "ruff"))[0].cmd == ["uv", "tool", "uninstall", "ruff"]
    assert devsetup.uninstall_steps(G("cargo", "ripgrep"))[0].cmd == ["cargo", "uninstall", "ripgrep"]
    assert devsetup.uninstall_steps(G("pnpm", "vercel"))[0].cmd == ["pnpm", "remove", "-g", "vercel"]
    assert devsetup.uninstall_steps(G("go", "gopls", path="/h/go/bin/gopls"))[0].cmd == ["rm", "-f", "/h/go/bin/gopls"]
    npm = devsetup.uninstall_steps(G("npm", "typescript"))[0]
    assert npm.cmd[1:] == ["uninstall", "-g", "typescript"] and not npm.root
    ups = devsetup.update_all_steps({"npm": False, "pipx": True, "uv": True, "cargo": True})
    assert [s.cmd for s in ups] == [["pipx", "upgrade-all"], ["uv", "tool", "upgrade", "--all"]] and all(s.optional for s in ups)


# ---------------------------------------------------------------- P8 uv Pythons

def test_uv_python_list():
    rows = devsetup.parse_uv_python_list(fx("uv-python-list.txt"))
    managed = [r for r in rows if r["managed"]]
    assert [(r["version"], r["minor"]) for r in managed] == [("3.13.7", "3.13")]
    system = [r for r in rows if r["system"]]
    assert [r["path"] for r in system] == ["/usr/bin/python3.12", "/usr/bin/python3"]
    ft = [r for r in rows if r["variant"]]
    assert ft and all(r["variant"] == "freethreaded" for r in ft)
    assert {r["impl"] for r in rows} == {"cpython", "pypy", "graalpy"}
    assert any(r["version"] == "3.15.0a1" and not r["installed"] for r in rows)
    assert devsetup.uv_python_install("3.13")[0].cmd == ["uv", "python", "install", "3.13"]
    assert devsetup.uv_python_uninstall("3.13.7")[0].cmd == ["uv", "python", "uninstall", "3.13.7"]
    assert devsetup.uv_python_pin("3.13")[0].cmd == ["uv", "python", "pin", "--global", "3.13"]
    assert devsetup.uv_install_steps()[0].cmd[0] in ("pipx", "bash")


# ---------------------------------------------------------------- P2 Docker disk usage

def test_docker_df():
    assert dev.parse_size("1.29GB") == 1_290_000_000 and dev.parse_size("512.3kB") == 512_300 and dev.parse_size("0B") == 0
    assert dev.parse_size("12.5MB (45%)") == 12_500_000 and dev.parse_size("") == 0 and dev.parse_size(42) == 42
    s = {x["type"]: x for x in dev.parse_docker_df(fx("docker-df.jsonl"))}
    assert set(s) == {"images", "containers", "volumes", "cache"}
    assert s["images"]["count"] == 5 and s["images"]["active"] == 2 and s["images"]["reclaimable"] == 1_083_000_000
    assert s["cache"]["size"] == 2_400_000_000 and s["volumes"]["label"] == "Volumes"
    podman = dev.parse_docker_df('[{"Type":"Images","Total":3,"Active":1,"RawSize":1000,"RawReclaimable":400,"Size":"1kB","Reclaimable":"400B (40%)"}]')
    assert podman == [{"type": "images", "label": "Images", "count": 3, "active": 1, "size": 1000, "reclaimable": 400}]
    v = dev.parse_docker_df_verbose(fx("docker-df-v.json"))
    unused = [i for i in v["images"] if not i["used_by"]]
    assert [i["name"] for i in unused] == ["node:20", "<untagged>"] and unused[1]["dangling"]
    assert [c["name"] for c in v["containers"] if not c["running"]] == ["old-web"]
    vols = {x["name"]: x for x in v["volumes"]}
    assert vols["pgdata"]["links"] == 1 and vols["oldproj_mysql"]["links"] == 0 and not vols["pgdata"]["anonymous"]
    assert sum(x["anonymous"] for x in v["volumes"]) == 1
    assert v["cache"][0]["size"] == 812_000_000
    assert dev.parse_docker_df_verbose("") == {"images": [], "containers": [], "volumes": [], "cache": []}


def test_docker_problems_and_steps():
    assert dev.docker_problem(127, "docker: not installed") == "missing"
    assert dev.docker_problem(1, "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock") == "permission"
    assert dev.docker_problem(1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?") == "stopped"
    assert dev.docker_problem(1, "failed to connect to the docker API at unix:///var/run/docker.sock") == "stopped"
    assert dev.docker_problem(0, "") == ""
    steps, why, danger = dev.docker_prune_steps("volumes")
    assert steps[0].cmd == ["docker", "volume", "prune", "-f"] and danger and "can't be recovered" in why
    assert dev.docker_prune_steps("images")[0][0].cmd == ["docker", "image", "prune", "-a", "-f"]
    assert dev.docker_prune_steps("containers")[0][0].cmd == ["docker", "container", "prune", "-f"]
    assert dev.docker_prune_steps("cache")[0][0].cmd == ["docker", "builder", "prune", "-a", "-f"]
    assert not dev.docker_prune_steps("cache")[2]
    assert dev.docker_remove_steps("volumes", {"name": "pgdata"})[0].cmd == ["docker", "volume", "rm", "pgdata"]
    assert dev.docker_remove_steps("images", {"name": "node:20", "id": "sha256:aa11"})[0].cmd == ["docker", "rmi", "sha256:aa11"]
    fix, why = dev.docker_fix_steps("permission")
    assert fix[0].cmd[:3] == ["usermod", "-aG", "docker"] and fix[0].root and "Log out" in why
    assert dev.docker_fix_steps("stopped")[0][0].cmd[:3] == ["systemctl", "enable", "--now"]
    assert dev.docker_fix_steps("error") == ([], "")


# ---------------------------------------------------------------- P6 projects

def test_branches_and_attention():
    br = dev.parse_branches(fx("for-each-ref.txt"))
    local = {b["name"]: b for b in br["local"]}
    assert local["main"]["ahead"] == 2 and local["main"]["upstream"] == "origin/main"
    assert local["old"]["ahead"] == 1 and local["old"]["behind"] == 3
    assert local["fix-typo"]["gone"] and not local["feature/login"]["upstream"] and not local["feature/login"]["on_remote"]
    assert local["pushed-no-track"]["on_remote"]
    assert "origin/HEAD" not in br["remote"]
    repo = {"name": "shop", "path": "/p/shop", "branch": "main", "upstream": "origin/main", "ahead": 2, "behind": 0, "changed": 1, "untracked": 2,
            "remote": "git@github.com:me/shop.git", "branches": br["local"], "stashes": 1}
    att = dev.attention(repo)
    texts = [t for _, t in att]
    assert "3 uncommitted changes" in texts and "2 commits not pushed" in texts
    assert any("2 other branches with unpushed work (feature/login, old)" == t for t in texts)
    assert any(t.startswith("1 branch deleted on the remote") for t in texts)
    assert "1 stash (changes you set aside)" in texts
    fresh = {"branch": "new-idea", "upstream": "", "remote": "git@github.com:me/x.git", "ahead": 0, "behind": 0, "changed": 0, "untracked": 0}
    assert ("warn", "branch new-idea isn't on the remote yet") in dev.attention(fresh)
    local_only = {"branch": "main", "upstream": "", "remote": "", "ahead": 0, "behind": 0, "changed": 0, "untracked": 0}
    assert dev.attention(local_only) == [("info", "not backed up anywhere (no remote)")]


def test_fetch_all_steps():
    steps = dev.fetch_all_steps([{"name": "a", "path": "/p/a", "remote": "git@github.com:me/a.git"}, {"name": "b", "path": "/p/b", "remote": ""}])
    assert len(steps) == 1 and steps[0].cmd == ["git", "-C", "/p/a", "fetch", "--all", "--prune"]
    assert steps[0].env["GIT_TERMINAL_PROMPT"] == "0" and "BatchMode=yes" in steps[0].env["GIT_SSH_COMMAND"] and steps[0].optional


def test_repo_status_full_real_repo(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode:
        pytest.skip("git missing")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = tmp_path / "proj"
    r.mkdir()
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "commit", "-q", "--allow-empty", "-m", "first"], ["git", "branch", "side"]):
        subprocess.run(cmd, cwd=r, env=env, check=True)
    (r / "new.txt").write_text("x")
    st = dev.repo_status_full(str(r))
    assert st["untracked"] == 1 and {b["name"] for b in st["branches"]} == {"main", "side"} and st["stashes"] == 0
    assert st["needs_you"] and ("info", "not backed up anywhere (no remote)") in st["attention"]


# ---------------------------------------------------------------- P7 stop all dev servers

def test_dev_server_detection_and_steps():
    assert dev.is_dev_server("node", "node /p/app/node_modules/.bin/vite")
    assert dev.is_dev_server("python3", "python3 manage.py runserver")
    assert dev.is_dev_server("sh", "sh -c npm run dev")
    assert not dev.is_dev_server("code", "/usr/share/code/code --type=utility")
    assert not dev.is_dev_server("docker-proxy", "")
    assert not dev.is_dev_server("spotify", "spotify")
    rows = [{"pid": 999991, "process": "node", "cmd": "node server.js", "port": 3000},
            {"pid": 999991, "process": "node", "cmd": "node server.js", "port": 3001},   # same process, second port
            {"pid": 999992, "process": "code", "cmd": "code", "port": 45000},
            {"pid": None, "process": "?", "cmd": "", "port": 8080}]
    stop, skipped = dev.stop_targets(rows)
    assert [r["pid"] for r in stop] == [999991] and skipped[0]["why"] == "not a dev server"
    steps = dev.stop_steps(stop)
    assert steps[0].cmd == ["kill", "-TERM", "999991"] and steps[0].optional and not steps[0].root
    assert dev.stop_steps(stop, force=True)[0].cmd == ["kill", "-KILL", "999991"]
    assert dev.still_running([999991, os.getpid()]) == [os.getpid()]
