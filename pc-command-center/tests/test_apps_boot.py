"""Apps (install from file, AppImages, permissions, duplicates, unused, terminal) and Startup (GRUB, boot speed,
login-app delay, user services) parsers and step builders."""

from pathlib import Path

import pytest

from pcctl.core import appmgr, boot
from pcctl.core.packages import App

FIX = Path(__file__).parent / "fixtures" / "apps_boot"


def fx(name: str) -> str:
    return (FIX / name).read_text()


def run_py(step):
    """Run a py_step's function (what the runner would do)."""
    return step._func()


# ================================================================ E1 install from a file

def test_file_kind():
    assert appmgr.file_kind("/x/code_1.9_amd64.deb") == "deb"
    assert appmgr.file_kind("GIMP.flatpakref") == "flatpakref"
    assert appmgr.file_kind("app.flatpak") == "flatpak"
    assert appmgr.file_kind("Obsidian-1.6.7.AppImage") == "appimage"
    assert appmgr.file_kind("tool.appimage") == "appimage"
    assert appmgr.file_kind("thing_1.0.snap") == "snap"
    assert appmgr.file_kind("notes.txt") is None


def test_deb_fields_and_simulation():
    f = appmgr.parse_deb_fields(fx("dpkg_fields.txt"))
    assert f["Package"] == "code" and f["Version"] == "1.104.0-1758000000"
    assert f["Description"].startswith("Code editing. Redefined.\nVisual Studio Code")
    sim = appmgr.parse_apt_simulate(fx("apt_simulate.txt"))
    assert sim["install"] == [("libxkbfile1", "1:1.1.0-1build4")]
    assert sim["upgrade"] == [("code", "1.104.0-1758000000")]
    assert sim["remove"] == [("code-insiders", "1.105.0-1758100000")]


def test_flatpakref():
    ref = appmgr.parse_flatpakref("[Flatpak Ref]\nName=org.gimp.GIMP\nBranch=stable\nTitle=GIMP from flathub\nUrl=https://dl.flathub.org/repo/\n")
    assert ref["Name"] == "org.gimp.GIMP" and ref["Title"] == "GIMP from flathub"


def test_install_file_steps(monkeypatch):
    monkeypatch.setattr(appmgr, "has", lambda c: True)
    s = appmgr.install_file_steps("/home/u/Downloads/code.deb")
    assert s[0].cmd == ["apt-get", "install", "-y", "/home/u/Downloads/code.deb"] and s[0].root
    s = appmgr.install_file_steps("/d/GIMP.flatpakref")
    assert s[-1].cmd == ["flatpak", "install", "--user", "-y", "--noninteractive", "--from", "/d/GIMP.flatpakref"] and not s[-1].root
    s = appmgr.install_file_steps("/d/app.flatpak")
    assert "--bundle" in s[-1].cmd
    s = appmgr.install_file_steps("/d/thing.snap")
    assert s[-1].cmd == ["snap", "install", "--dangerous", "/d/thing.snap"] and s[-1].root
    monkeypatch.setattr(appmgr, "has", lambda c: False)
    s = appmgr.install_file_steps("/d/app.flatpak")
    assert s[0].cmd[:3] == ["apt-get", "install", "-y"] and s[0].cmd[-1] == "flatpak"


# ================================================================ E2 AppImages

@pytest.mark.parametrize("fname,name", [
    ("Obsidian-1.6.7.AppImage", "Obsidian"),
    ("cursor-0.42.3-x86_64.AppImage", "Cursor"),
    ("LM-Studio-0.3.5-2-x64.AppImage", "LM Studio"),
    ("balenaEtcher-1.19.25-x64.AppImage", "balenaEtcher"),
    ("FreeCAD_1.0.0-conda-Linux-x86_64-py311.AppImage", "FreeCAD"),
    ("nvim.appimage", "Nvim"),
    ("Bitwarden-2024.9.0-x86_64.AppImage", "Bitwarden"),
])
def test_appimage_name(fname, name):
    assert appmgr.appimage_name(fname) == name


def test_desktop_quote_and_exec_target():
    assert appmgr.desktop_quote("/home/u/Applications/a.AppImage") == "/home/u/Applications/a.AppImage"
    q = appmgr.desktop_quote("/home/u/My Apps/a$b.AppImage")
    assert q == '"/home/u/My Apps/a\\\\$b.AppImage"'
    assert appmgr.exec_target('env FOO=1 "/home/u/My Apps/x.AppImage" %U') == "/home/u/My Apps/x.AppImage"
    assert appmgr.desktop_quote("50%") == "50%%"


def test_appimage_type(tmp_path):
    f = tmp_path / "x.AppImage"
    f.write_bytes(b"\x7fELF\x02\x01\x01\x00AI\x02" + b"\0" * 20)
    assert appmgr.appimage_type(str(f)) == 2
    f.write_bytes(b"#!/bin/sh\necho hi\n")
    assert appmgr.appimage_type(str(f)) == 0


def test_pick_icon_follows_diricon(tmp_path):
    root = tmp_path / "squashfs-root"
    (root / "usr/share/icons/hicolor/256x256/apps").mkdir(parents=True)
    png = root / "usr/share/icons/hicolor/256x256/apps/obsidian.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 10)
    (root / "obsidian.png").symlink_to("usr/share/icons/hicolor/256x256/apps/obsidian.png")
    (root / ".DirIcon").symlink_to("obsidian.png")
    assert appmgr.pick_icon(root, "obsidian") == str(png.resolve())
    # a link that escapes the folder is ignored
    (root / ".DirIcon").unlink()
    (root / "obsidian.png").unlink()
    (root / ".DirIcon").symlink_to("/etc/passwd")
    assert appmgr.pick_icon(root, "obsidian") == str(png.resolve())


def test_integrate_and_list(tmp_path, monkeypatch):
    apps_dir, desk_dir, icon_dir = tmp_path / "Applications", tmp_path / "apps", tmp_path / "icons"
    monkeypatch.setattr(appmgr, "APPS_DIR", apps_dir)
    monkeypatch.setattr(appmgr, "DESKTOP_DIR", desk_dir)
    monkeypatch.setattr(appmgr, "ICON_DIR", icon_dir)
    monkeypatch.setattr(appmgr, "has", lambda c: True)
    dl = tmp_path / "Downloads"
    dl.mkdir()
    src = dl / "Obsidian-1.6.7.AppImage"
    src.write_bytes(b"not really")
    steps = appmgr.integrate_steps(str(src), "move")
    cmds = [s.cmd for s in steps]
    assert cmds[0] == ["mkdir", "-p", str(apps_dir)]
    assert cmds[1] == ["mv", "-n", str(src), str(apps_dir / src.name)]
    assert cmds[2] == ["chmod", "+x", str(apps_dir / src.name)]
    assert cmds[3][0] == "__python__" and "appimage-obsidian.desktop" in cmds[3][1]
    assert cmds[4] == ["update-desktop-database", str(desk_dir)] and steps[4].optional
    # an existing file with the same name is never overwritten
    apps_dir.mkdir()
    (apps_dir / src.name).write_text("old")
    assert appmgr.integrate_steps(str(src), "copy")[1].cmd == ["cp", "-n", str(src), str(apps_dir / "Obsidian-1.6.7-2.AppImage")]
    keep = appmgr.integrate_steps(str(src), "keep")
    assert keep[0].cmd == ["chmod", "+x", str(src)]

    msg = appmgr.write_integration(str(src), unpack=False)
    assert "appimage-obsidian.desktop" in msg
    text = (desk_dir / "appimage-obsidian.desktop").read_text()
    assert f"Exec={src} %U" in text and "X-PC-AppImage=true" in text and "Icon=application-x-executable" in text
    integ = appmgr.integrated_appimages(desk_dir)
    assert len(integ) == 1 and integ[0].path == str(src) and integ[0].ours and integ[0].name == "Obsidian"
    other = dl / "cursor-0.42.3-x86_64.AppImage"
    other.write_bytes(b"x")
    loose = appmgr.loose_appimages(integ, dirs=[dl])
    assert [a.name for a in loose] == ["Cursor"]
    rm = appmgr.remove_integration_steps(integ[0], delete_file=True)
    assert rm[0].cmd == ["rm", "-f", str(desk_dir / "appimage-obsidian.desktop")]
    assert ["gio", "trash", str(src)] in [s.cmd for s in rm]


def test_fuse_steps():
    s = appmgr.fuse2_steps("libfuse2t64")
    assert s[0].cmd == ["apt-get", "install", "-y", "libfuse2t64"] and s[0].root


# ================================================================ E3 uninstall several

def test_remove_many(monkeypatch):
    monkeypatch.setattr(appmgr, "integrated_appimages", lambda *a: [])
    apps = [App("apt", "gimp", "GIMP"), App("apt", "vlc", "VLC"), App("snap", "postman", "Postman"), App("snap", "spotify", "Spotify"),
            App("flatpak", "org.a.A", "A", location="user"), App("flatpak", "org.b.B", "B", location="system"),
            App("appimage", "/home/u/Apps/x.AppImage", "x"), App("apt", "gnome-shell", "GNOME Shell")]
    cmds = [(s.cmd, s.root) for s in appmgr.remove_many_steps(apps)]
    assert (["apt-get", "purge", "-y", "gimp", "vlc"], True) in cmds
    assert (["snap", "remove", "--purge", "postman", "spotify"], True) in cmds
    assert (["flatpak", "uninstall", "-y", "--noninteractive", "--delete-data", "--user", "org.a.A"], False) in cmds
    assert (["flatpak", "uninstall", "-y", "--noninteractive", "--delete-data", "--system", "org.b.B"], True) in cmds
    assert (["gio", "trash", "/home/u/Apps/x.AppImage"], False) in cmds
    assert not any("gnome-shell" in c for c, _ in cmds)  # never removes the desktop itself
    keep = [s.cmd for s in appmgr.remove_many_steps(apps, keep_data=True)]
    assert ["apt-get", "remove", "-y", "gimp", "vlc"] in keep and ["snap", "remove", "postman", "spotify"] in keep


# ================================================================ E4 permissions

def test_snap_connections():
    plugs = appmgr.parse_snap_connections(fx("snap_connections.txt"), "firefox")
    by = {p["base"]: p for p in plugs}
    assert by["home"]["connected"] and by["home"]["title"] == "Your home folder"
    assert not by["audio-record"]["connected"] and by["audio-record"]["title"] == "Microphone"
    assert by["camera"]["manual"]
    assert not by["removable-media"]["connected"]
    assert "dbus" not in by  # a slot firefox offers, not a plug
    assert by["content"]["interface"] == "content[gnome-46-2404]" and by["content"]["technical"]
    assert by["browser-support"]["technical"] and not by["camera"]["technical"]
    assert appmgr.parse_snap_connections("error: snap not found", "x") == []
    s = appmgr.snap_plug_steps("firefox:camera", False)
    assert s[0].cmd == ["snap", "disconnect", "firefox:camera"] and s[0].root


def test_flatpak_permissions():
    p = appmgr.parse_flatpak_permissions(fx("flatpak_permissions.txt"))
    assert p["Context"]["sockets"] == ["x11", "wayland", "pulseaudio", "fallback-x11"]
    assert appmgr.flatpak_has(p, "shared", "network")
    assert appmgr.flatpak_has(p, "sockets", "x11")
    assert not appmgr.flatpak_has(p, "filesystems", "home")      # !home
    assert not appmgr.flatpak_has(p, "devices", "all")
    assert appmgr.flatpak_has({"Context": {"filesystems": ["host"]}}, "filesystems", "home")
    words = appmgr.flatpak_summary(p)
    assert "internet" in words and "Music (read-only)" in words and "blocked: your home folder" in words
    assert appmgr.flatpak_override_steps("com.spotify.Client", "--nosocket=x11")[0].cmd == \
        ["flatpak", "override", "--user", "--nosocket=x11", "com.spotify.Client"]
    assert appmgr.flatpak_reset_steps("x.y")[0].cmd == ["flatpak", "override", "--user", "--reset", "x.y"]


# ================================================================ E5 duplicates

def test_find_duplicates():
    apps = [App("snap", "firefox", "Firefox Web Browser", size=300), App("flatpak", "org.mozilla.firefox", "Firefox", size=200),
            App("apt", "firefox", "Firefox", "1:1snap1-0ubuntu5"),  # Ubuntu's empty shell that installs the snap
            App("apt", "code", "Visual Studio Code", size=400), App("flatpak", "com.visualstudio.code", "Visual Studio Code", size=500),
            App("snap", "gitkraken", "GitKraken"), App("flatpak", "com.axosoft.GitKraken", "GitKraken"),
            App("apt", "vim", "Vim"), App("snap", "spotify", "Spotify")]
    groups = {g["key"]: g for g in appmgr.find_duplicates(apps)}
    assert set(groups) == {"firefox", "vscode", "gitkraken"}
    ff = groups["firefox"]
    assert sorted(c["source"] for c in ff["copies"]) == ["flatpak", "snap"]
    assert ff["keep"] == "snap" and "Mozilla" in ff["why"]
    assert groups["vscode"]["keep"] == "apt"
    # the one you actually use wins
    used = {"flatpak:com.visualstudio.code": 1_758_000_000.0, "apt:code": 1_750_000_000.0}
    g = {g["key"]: g for g in appmgr.find_duplicates(apps, used)}["vscode"]
    assert g["keep"] == "flatpak" and "most recently" in g["why"]


def test_remove_copy_keeps_data():
    s = appmgr.remove_copy_steps({"source": "snap", "apps": [App("snap", "firefox", "Firefox")]})
    assert s[0].cmd == ["snap", "remove", "firefox"]
    s = appmgr.remove_copy_steps({"source": "flatpak", "apps": [App("flatpak", "org.mozilla.firefox", "F", location="user")]})
    assert s[0].cmd == ["flatpak", "uninstall", "-y", "--noninteractive", "--user", "org.mozilla.firefox"] and "--delete-data" not in s[0].cmd
    s = appmgr.remove_copy_steps({"source": "apt", "apps": [App("apt", "libreoffice-writer", "W"), App("apt", "libreoffice-calc", "C")]})
    assert s[0].cmd == ["apt-get", "remove", "-y", "libreoffice-calc", "libreoffice-writer"]


# ================================================================ E6 last used

def test_app_state_and_unused(monkeypatch):
    st = appmgr.parse_app_state(fx("application_state.xml"))
    assert st["firefox_firefox.desktop"]["last_seen"] == 1758790000
    assert st["broken"]["last_seen"] == 0
    monkeypatch.setattr(appmgr, "file_last_used", lambda a: 1_700_000_000.0 if a.id == "old" else None)
    monkeypatch.setattr(appmgr, "desktop_ids", lambda a: {"gimp": ["gimp.desktop"], "code": ["code.desktop"],
                                                          "com.spotify.Client": ["com.spotify.Client.desktop"]}.get(a.id, []))
    apps = [App("apt", "gimp", "GIMP", size=100), App("apt", "code", "Code", size=50), App("flatpak", "com.spotify.Client", "Spotify", size=300),
            App("apt", "old", "Old", size=10), App("apt", "never", "Never")]
    used = appmgr.last_used(apps, fx("application_state.xml"))
    assert used["apt:gimp"] == (1720000000.0, "gnome")
    assert used["apt:old"] == (1700000000.0, "files")
    assert used["apt:never"] == (None, "")
    now = 1_758_800_000.0
    un = appmgr.unused_apps(apps, used, days=90, now=now)
    assert [u["app"].id for u in un] == ["com.spotify.Client", "gimp", "old"]  # biggest first
    assert un[1]["days"] == int((now - 1720000000) // 86400)
    assert [u["app"].id for u in appmgr.unused_apps(apps, used, core={"gimp"}, now=now)] == ["com.spotify.Client", "old"]


def test_apt_depends():
    core = appmgr.parse_apt_depends(fx("apt_depends.txt"))
    assert {"gnome-shell", "ptyxis", "gnome-terminal", "firefox", "gnome-text-editor", "thunderbird", "libreoffice-writer"} <= core
    minimal = appmgr.parse_apt_depends(fx("apt_depends.txt"), {"ubuntu-desktop-minimal"})
    assert {"gnome-shell", "ptyxis", "firefox", "gnome-text-editor", "ubuntu-desktop-minimal"} <= minimal
    assert "libreoffice-writer" not in minimal and "thunderbird" not in minimal


# ================================================================ E7 terminal

def _desktop(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("[Desktop Entry]\nType=Application\n" + body)


def test_terminals(tmp_path):
    apps = tmp_path / "share"
    _desktop(apps, "org.gnome.Ptyxis.desktop", "Name=Terminal\nExec=ptyxis --new-window\nCategories=GNOME;GTK;System;TerminalEmulator;\n")
    _desktop(apps, "com.mitchellh.ghostty.desktop", "Name=Ghostty\nExec=/usr/bin/ghostty\nCategories=System;TerminalEmulator;\n")
    _desktop(apps, "firefox.desktop", "Name=Firefox\nExec=firefox %u\nCategories=Network;\n")
    terms = appmgr.installed_terminals([apps])
    assert [t["id"] for t in terms] == ["org.gnome.Ptyxis.desktop", "com.mitchellh.ghostty.desktop"]
    assert terms[1]["name"] == "Ghostty" and terms[1]["program"] == "ghostty"

    home, etc = tmp_path / "config", tmp_path / "etc"
    files = appmgr.terminal_list_files(config_home=home, config_dirs=[etc], desktop="ubuntu:GNOME")
    assert files == [home / "ubuntu-xdg-terminals.list", home / "gnome-xdg-terminals.list", home / "xdg-terminals.list",
                     etc / "ubuntu-xdg-terminals.list", etc / "gnome-xdg-terminals.list", etc / "xdg-terminals.list"]
    etc.mkdir()
    (etc / "ubuntu-xdg-terminals.list").write_text("# Ubuntu default\norg.gnome.Ptyxis.desktop\n")
    assert appmgr.default_terminal(terms, files) == ("org.gnome.Ptyxis.desktop", str(etc / "ubuntu-xdg-terminals.list"))
    assert appmgr.parse_terminal_list("# c\n-kitty.desktop\n+com.mitchellh.ghostty.desktop:new-window\n") == ["com.mitchellh.ghostty.desktop"]
    assert appmgr.put_first("# mine\norg.gnome.Ptyxis.desktop\ncom.mitchellh.ghostty.desktop\n", "com.mitchellh.ghostty.desktop") == \
        "# mine\ncom.mitchellh.ghostty.desktop\norg.gnome.Ptyxis.desktop\n"

    home.mkdir()
    (home / "gnome-xdg-terminals.list").write_text("org.gnome.Ptyxis.desktop\n")
    steps = appmgr.set_terminal_steps(terms[1], config_home=home, with_gsettings=True)
    run_py(steps[0])
    assert (home / "xdg-terminals.list").read_text() == "com.mitchellh.ghostty.desktop\n"
    assert (home / "gnome-xdg-terminals.list").read_text().splitlines()[0] == "com.mitchellh.ghostty.desktop"
    assert steps[1].cmd == ["gsettings", "set", "org.gnome.desktop.default-applications.terminal", "exec", "ghostty"]
    assert steps[2].cmd[-2:] == ["exec-arg", "-e"]
    user_files = [f for f in files if f.parent == home]
    assert appmgr.default_terminal(terms, user_files)[0] == "com.mitchellh.ghostty.desktop"
    assert len(appmgr.set_terminal_steps(terms[1], config_home=home, with_gsettings=False)) == 1


def test_browser_editor_steps():
    assert appmgr.set_browser_steps("firefox_firefox.desktop")[0].cmd == ["xdg-settings", "set", "default-web-browser", "firefox_firefox.desktop"]
    s = appmgr.set_editor_steps("code.desktop")[0].cmd
    assert s[:3] == ["xdg-mime", "default", "code.desktop"] and "text/plain" in s


# ================================================================ F1 GRUB

def test_grub_parse_and_settings():
    vals = boot.parse_grub_default(fx("grub_default.txt"))
    assert vals["GRUB_DEFAULT"] == "0" and vals["GRUB_TIMEOUT"] == "0" and vals["GRUB_CMDLINE_LINUX_DEFAULT"] == "quiet splash"
    assert "GRUB_DISABLE_OS_PROBER" not in vals  # only a comment
    s = boot.grub_settings(vals)
    assert s == {"timeout": 0, "style": "hidden", "default": "0", "remember": False, "quiet": True, "splash": True,
                 "cmdline": "quiet splash", "os_prober": None}


def test_grub_edit_roundtrip():
    text = fx("grub_default.txt")
    vals = boot.parse_grub_default(text)
    ch = boot.settings_changes(vals, {"timeout": 5, "style": "menu", "remember": True, "quiet": False, "splash": True, "os_prober": True})
    assert ch == {"GRUB_TIMEOUT": "5", "GRUB_TIMEOUT_STYLE": "menu", "GRUB_DEFAULT": "saved", "GRUB_SAVEDEFAULT": "true",
                  "GRUB_CMDLINE_LINUX_DEFAULT": "splash", "GRUB_DISABLE_OS_PROBER": "false"}
    new = boot.grub_edit(text, ch)
    nv = boot.parse_grub_default(new)
    assert boot.grub_settings(nv) == {"timeout": 5, "style": "menu", "default": "saved", "remember": True, "quiet": False, "splash": True,
                                      "cmdline": "splash", "os_prober": True}
    lines = new.splitlines()
    # os-prober goes right under Ubuntu's commented example; comments and other keys are kept
    assert lines[lines.index("#GRUB_DISABLE_OS_PROBER=false") + 1] == "GRUB_DISABLE_OS_PROBER=false"
    assert "GRUB_CMDLINE_LINUX_DEFAULT=\"splash\"" in lines and "GRUB_CMDLINE_LINUX=\"\"" in lines
    assert nv["GRUB_DISTRIBUTOR"] == vals["GRUB_DISTRIBUTOR"]
    assert boot.describe_changes(ch) == ["Menu: always show the menu.", "Wait 5 seconds before starting the default.",
                                         "Start the one you picked last time.", "Start options: splash.", "Look for other systems like Windows."]
    assert boot.describe_changes({"GRUB_CMDLINE_LINUX_DEFAULT": "", "GRUB_TIMEOUT": "-1"}) == \
        ["Wait until you choose (no countdown).", "Show the text messages while starting."]
    diff = boot.grub_diff(text, new)
    assert "-GRUB_TIMEOUT=0" in diff and "+GRUB_TIMEOUT=5" in diff and "+GRUB_SAVEDEFAULT=true" in diff
    # nothing to change → no changes
    assert boot.settings_changes(nv, {"timeout": 5, "style": "menu", "remember": True, "quiet": False}) == {}
    # back to a fixed entry drops GRUB_SAVEDEFAULT and quotes titles with spaces
    ch2 = boot.settings_changes(nv, {"remember": False, "default": "Advanced options for Ubuntu>Ubuntu, with Linux 6.17.0-8-generic"})
    assert ch2 == {"GRUB_DEFAULT": "Advanced options for Ubuntu>Ubuntu, with Linux 6.17.0-8-generic", "GRUB_SAVEDEFAULT": None}
    new2 = boot.grub_edit(new, ch2)
    assert 'GRUB_DEFAULT="Advanced options for Ubuntu>Ubuntu, with Linux 6.17.0-8-generic"' in new2
    assert "#GRUB_SAVEDEFAULT=true" in new2
    assert boot.parse_grub_default(new2)["GRUB_DEFAULT"] == "Advanced options for Ubuntu>Ubuntu, with Linux 6.17.0-8-generic"


def test_grub_edit_duplicates_and_quoting():
    text = 'GRUB_TIMEOUT=10\nGRUB_TIMEOUT=3\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1"\n'
    new = boot.grub_edit(text, {"GRUB_TIMEOUT": "7", "GRUB_CMDLINE_LINUX_DEFAULT": boot.cmdline_set("splash nvidia-drm.modeset=1", "quiet", True)})
    assert new.splitlines() == ["GRUB_TIMEOUT=7", "#GRUB_TIMEOUT=3", 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1"']
    assert boot.grub_edit("", {"GRUB_DEFAULT": 'Win "10"'}) == 'GRUB_DEFAULT="Win \\"10\\""\n'
    assert boot.cmdline_set("quiet splash", "splash", False) == "quiet"


def test_grub_cfg_entries():
    entries = boot.parse_grub_cfg(fx("grub.cfg"))
    titles = [e["title"] for e in entries]
    assert titles == ["Ubuntu", "Advanced options for Ubuntu", "Ubuntu, with Linux 7.0.0-12-generic",
                      "Ubuntu, with Linux 7.0.0-12-generic (recovery mode)", "Ubuntu, with Linux 6.17.0-8-generic",
                      "Windows Boot Manager (on /dev/nvme0n1p1)", "UEFI Firmware Settings", "Memory test (memtest86+x64.efi)"]
    by = {e["title"]: e for e in entries}
    assert by["Ubuntu"]["index"] == "0" and by["Ubuntu"]["id"].startswith("gnulinux-simple-")
    sub = by["Ubuntu, with Linux 6.17.0-8-generic"]
    assert sub["index"] == "1>2" and sub["depth"] == 1 and sub["path"] == "Advanced options for Ubuntu>Ubuntu, with Linux 6.17.0-8-generic"
    assert by["Windows Boot Manager (on /dev/nvme0n1p1)"]["index"] == "2"
    assert by["UEFI Firmware Settings"]["index"] == "3" and by["Memory test (memtest86+x64.efi)"]["index"] == "4"
    assert by["Advanced options for Ubuntu"]["kind"] == "submenu"
    env = boot.parse_grubenv(fx("grubenv.txt"))
    assert env["saved_entry"].endswith("6.17.0-8-generic")
    assert boot.find_entry(env["saved_entry"], entries) is sub
    assert boot.find_entry("1>2", entries) is sub
    assert boot.find_entry("0", entries)["title"] == "Ubuntu"
    assert boot.find_entry("osprober-efi-A1B2-C3D4", entries)["title"].startswith("Windows")
    assert boot.find_entry("nope", entries) is None


def test_bootloader_detection(tmp_path):
    info = tmp_path / "LoaderInfo"
    info.write_bytes(b"\x06\x00\x00\x00" + "systemd-boot 257.4".encode("utf-16-le") + b"\0\0")
    grub = tmp_path / "grub"
    grub.write_text("GRUB_TIMEOUT=0\n")
    b = boot.bootloader(info, grub)
    assert b["name"] == "systemd-boot" and b["detail"] == "systemd-boot 257.4"
    assert boot.bootloader(tmp_path / "none", grub)["name"] == "grub"
    assert boot.bootloader(tmp_path / "none", tmp_path / "nogrub")["name"] == "unknown"


def test_grub_steps(monkeypatch, tmp_path):
    monkeypatch.setattr(boot, "has", lambda c: c == "update-grub")
    monkeypatch.setattr(boot, "CACHE", tmp_path)
    monkeypatch.setattr(boot, "STAGED", tmp_path / "grub.new")
    steps = boot.grub_apply_steps("GRUB_TIMEOUT=5\n", refresh_copy=True, diff="-GRUB_TIMEOUT=0\n+GRUB_TIMEOUT=5")
    assert steps[0].cmd[0] == "__python__" and not steps[0].root and "+GRUB_TIMEOUT=5" in steps[0].cmd[1]
    run_py(steps[0])
    assert (tmp_path / "grub.new").read_text() == "GRUB_TIMEOUT=5\n"
    assert steps[1].cmd == ["cp", "-a", "/etc/default/grub", "/etc/default/grub.pc-backup"] and steps[1].root
    assert steps[2].cmd == ["install", "-m", "644", str(tmp_path / "grub.new"), "/etc/default/grub"] and steps[2].root
    assert steps[3].cmd == ["update-grub"] and steps[3].root
    assert steps[4].cmd[:4] == ["install", "-D", "-m", "600"] and steps[4].optional
    monkeypatch.setattr(boot, "has", lambda c: c == "grub-mkconfig")
    assert boot.update_grub_cmd() == ["grub-mkconfig", "-o", "/boot/grub/grub.cfg"]
    r = boot.grub_restore_steps()
    assert r[0].cmd == ["install", "-m", "644", "/etc/default/grub.pc-backup", "/etc/default/grub"] and all(s.root for s in r)


def test_dropins(tmp_path):
    f = tmp_path / "50-cloudimg.cfg"
    f.write_text("GRUB_TIMEOUT=0\nGRUB_TERMINAL=console\n")
    assert boot.dropin_overrides([str(f)]) == {"GRUB_TIMEOUT": str(f)}


# ================================================================ F2 delay a login app

def test_delay_text():
    text = "[Desktop Entry]\nName=Slack\nExec=slack -u\n\n[Desktop Action New]\nX-GNOME-Autostart-Delay=99\n"
    t2 = boot.set_delay_in_text(text, 15)
    assert boot.autostart_delay(t2) == 15 and t2.startswith("[Desktop Entry]\nX-GNOME-Autostart-Delay=15\n")
    assert "X-GNOME-Autostart-Delay=99" in t2  # other sections untouched
    t3 = boot.set_delay_in_text(t2, 0)
    assert boot.autostart_delay(t3) == 0 and "Delay=15" not in t3


def test_set_autostart_delay(tmp_path):
    sysfile = tmp_path / "etc" / "org.gnome.Evolution-alarm-notify.desktop"
    sysfile.parent.mkdir()
    sysfile.write_text("[Desktop Entry]\nType=Application\nName=Evolution Alarm Notify\nExec=/usr/libexec/evolution-data-server/evolution-alarm-notify\n")
    auto, units = tmp_path / "autostart", tmp_path / "units"
    msg = boot.set_autostart_delay(sysfile.name, str(sysfile), 20, auto, units)
    assert "20 s" in msg
    assert boot.autostart_delay((auto / sysfile.name).read_text()) == 20
    assert "Exec=/usr/libexec" in (auto / sysfile.name).read_text()
    unit = boot.autostart_unit(sysfile.name)
    assert unit == "app-org.gnome.Evolution\\x2dalarm\\x2dnotify@autostart.service"
    conf = units / (unit + ".d") / "pc-delay.conf"
    assert "ExecStartPre=" in conf.read_text() and conf.read_text().rstrip().endswith(" 20")
    assert sysfile.read_text().count("Delay") == 0  # Ubuntu's own file is never touched
    boot.set_autostart_delay(sysfile.name, str(sysfile), 0, auto, units)
    assert boot.autostart_delay((auto / sysfile.name).read_text()) == 0 and not conf.exists()


def test_systemd_escape():
    assert boot.systemd_escape("snap-userd-autostart") == "snap\\x2duserd\\x2dautostart"
    assert boot.systemd_escape("a b.c") == "a\\x20b.c"
    assert boot.autostart_unit("gnome-keyring-ssh.desktop") == "app-gnome\\x2dkeyring\\x2dssh@autostart.service"


# ================================================================ F3 boot speed

def test_boot_time_parsers():
    assert boot.parse_span("1min 2.100s") == pytest.approx(62.1)
    assert boot.parse_span("296ms") == pytest.approx(0.296)
    t = boot.parse_time(fx("analyze_time.txt"))
    assert t["firmware"] == pytest.approx(7.215) and t["initrd"] == pytest.approx(4.001)
    assert t["userspace"] == pytest.approx(62.1) and t["total"] == pytest.approx(78.78)
    assert t["target"] == "graphical.target" and t["target_at"] == pytest.approx(62.05)
    assert boot.parse_time("Startup finished in 2.1s (kernel) + 5.3s (userspace) = 7.4s")["total"] == pytest.approx(7.4)
    assert boot.parse_time("") == {}
    bl = boot.parse_blame(fx("blame.txt"))
    assert bl[0] == (pytest.approx(6.09), "NetworkManager-wait-online.service")
    assert bl[2] == (pytest.approx(62.1), "plymouth-quit-wait.service") and bl[3][1] == "NetworkManager.service"


def test_critical_chain():
    ch = boot.parse_critical_chain(fx("critical_chain.txt"))
    assert ch[0] == {"unit": "graphical.target", "at": pytest.approx(12.303), "took": 0.0, "depth": 0}
    wait = next(c for c in ch if c["unit"] == "NetworkManager-wait-online.service")
    assert wait["took"] == pytest.approx(6.09) and wait["at"] == pytest.approx(3.31) and wait["depth"] == 4
    assert ch[-1]["unit"] == "sysinit.target" and len(ch) == 11
    assert "network" in boot.explain_unit("NetworkManager-wait-online.service")
    assert boot.explain_unit("snap-firefox-6800.mount") == "A snap app being attached."


def test_boot_history_and_plot():
    h = boot.parse_boot_history(fx("journal_startup.txt"))
    assert [round(b["total"], 3) for b in h] == [30.001, 25.608]
    assert h[1]["when"] == pytest.approx(1758100000.654321) and h[1]["userspace"] == pytest.approx(9.412)
    steps, dest = boot.plot_steps(Path("/home/u/Pictures/boot-chart.svg"))
    assert steps[0].cmd == ["bash", "-c", "mkdir -p /home/u/Pictures && systemd-analyze plot > /home/u/Pictures/.boot-chart.svg.part && "
                                          "mv -f /home/u/Pictures/.boot-chart.svg.part /home/u/Pictures/boot-chart.svg || "
                                          "{ rm -f /home/u/Pictures/.boot-chart.svg.part; false; }"]
    assert not steps[0].root and dest.name == "boot-chart.svg"


# ================================================================ F4 user services

def test_user_services(tmp_path):
    own = tmp_path / "user"
    own.mkdir()
    (own / "pc-maintain.timer").write_text("")
    (own / "pc-watch.timer").write_text("")
    res = boot.user_services(fx("user_unit_files.txt"), fx("user_units.txt"), own)
    assert res["available"]
    units = {u["unit"]: u for u in res["units"]}
    assert "syncthing@.service" not in units and "dbus.service" not in units and "filter-chain.service" not in units
    assert units["pc-watch.timer"]["state"] == "disabled" and units["pc-watch.timer"]["mine"]  # yours, even when off
    assert units["pipewire.service"]["keep"] and units["pipewire.service"]["active"] == "active"
    assert units["wireplumber.service"]["active"] == "failed"
    assert units["localsearch-3.service"]["what"].startswith("Indexes your files")
    assert "snapd-desktop-integration" in units["snap.snapd-desktop-integration.snapd-desktop-integration.service"]["what"]
    assert units["xdg-user-dirs.service"]["sub"] == "dead"
    assert res["units"][0]["mine"]  # your own ones first
    assert units["pc-maintain.timer"]["title"] == "pc-maintain (schedule)"
    assert units["snap.snapd-desktop-integration.snapd-desktop-integration.service"]["title"] == "snapd-desktop-integration (snap)"
    assert boot.user_unit_title("snap.foo.bar-daemon.service") == "foo: bar-daemon (snap)"
    s = boot.user_unit_steps("localsearch-3.service", "disable --now")
    assert s[0].cmd == ["systemctl", "--user", "disable", "--now", "localsearch-3.service"] and not s[0].root
