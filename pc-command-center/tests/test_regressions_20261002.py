"""Regression tests for the 2026-10-02 production pass (bugs found by running the app on real GTK/hardware)."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pcctl.core import diagnose, network
from pcctl.core.run import Result

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "src" / "pcctl" / "gui"

# GObject/GtkWidget API that a Python subclass must never shadow: GTK and our
# own code call these on every widget, so an override silently breaks the page.
GOBJECT_API = {"connect", "connect_after", "disconnect", "emit", "notify", "get_property", "set_property",
               "freeze_notify", "thaw_notify", "bind_property", "handler_block", "handler_unblock"}


def _gui_sources() -> list[Path]:
    return sorted(GUI.rglob("*.py"))


def test_gui_classes_do_not_shadow_gobject_api() -> None:
    offenders = []
    for path in _gui_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in GOBJECT_API:
                        offenders.append(f"{path.relative_to(ROOT)}:{item.lineno} {node.name}.{item.name}")
    assert not offenders, "shadows GObject API (page fails to construct): " + ", ".join(offenders)


def test_no_notify_on_nonexistent_size_properties() -> None:
    # GTK 4 widgets have no "width"/"height" properties, so these handlers never fire.
    bad = [str(p.relative_to(ROOT)) for p in _gui_sources()
           if re.search(r"notify::(width|height)\b", p.read_text(encoding="utf-8"))]
    assert not bad


def test_gui_smoke_test_covers_every_sidebar_page() -> None:
    tree = ast.parse((GUI / "window.py").read_text(encoding="utf-8"))
    sections = next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SECTIONS")
    ids = {pid for _title, pids in ast.literal_eval(sections) for pid in pids}
    smoke = ast.parse((ROOT / "tests" / "test_gui_smoke.py").read_text(encoding="utf-8"))
    pages = next(n.value for n in smoke.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "PAGES")
    assert set(ast.literal_eval(pages)) == ids


def test_connectivity_check_pings_bare_gateway_address(monkeypatch) -> None:
    pinged = []
    monkeypatch.setattr(network, "default_gateway", lambda: "192.168.1.1 (wlp0s20f3)")
    monkeypatch.setattr(network, "ping", lambda host: pinged.append(host) or {"ok": True, "loss": 0.0, "avg_ms": 0.4})
    monkeypatch.setattr(network, "dns_check", lambda *a: True)
    import pcctl.core.run as run
    monkeypatch.setattr(run, "sh", lambda *a, **k: Result(0))
    res = network.diagnose_connectivity()
    assert pinged[0] == "192.168.1.1"
    # sub-millisecond replies are still replies
    assert res[0][1] is True and "0 ms" in res[0][2]


@pytest.mark.parametrize("security,expected", [("WPA2", "wpa-psk"), ("WPA1 WPA2", "wpa-psk"), ("WPA2 WPA3", "wpa-psk"),
                                               ("WPA3", "sae"), ("WPA2 802.1X", None), ("WEP", None)])
def test_wifi_key_management(security, expected) -> None:
    assert network._wifi_key_mgmt(security) == expected


def test_wifi_password_never_on_command_line(monkeypatch, tmp_path) -> None:
    calls, seen_files = [], []
    secret = "hunter2-very-secret"

    def fake_sh(args, **_k):
        calls.append(list(args))
        if "add" in args:
            return Result(0, "Connection 'Cafe' (0a1b2c3d-1111-2222-3333-444455556666) successfully added.\n")
        if "up" in args:
            path = args[args.index("passwd-file") + 1]
            seen_files.append((path, Path(path).read_text(), os.stat(path).st_mode & 0o777))
            return Result(4, "", "Secrets were required")
        return Result(0)
    monkeypatch.setattr(network, "sh", fake_sh)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    r = network.wifi_connect("Cafe", secret, "WPA2")
    assert not r.ok
    assert all(secret not in " ".join(c) for c in calls)
    path, content, mode = seen_files[0]
    assert content == f"802-11-wireless-security.psk:{secret}\n" and mode == 0o600
    assert not Path(path).exists(), "password file must be removed"
    assert calls[-1][:3] == ["nmcli", "connection", "delete"], "a failed join must not leave a broken profile"
    assert "0a1b2c3d-1111-2222-3333-444455556666" in calls[-1]


def test_idle_unattended_upgrades_helper_is_not_installing(monkeypatch) -> None:
    def procs(items):
        return lambda _attrs: [SimpleNamespace(info={"name": n, "cmdline": c}) for n, c in items]
    idle = ("unattended-upgr", ["/usr/bin/python3", "/usr/share/unattended-upgrades/unattended-upgrade-shutdown", "--wait-for-signal"])
    monkeypatch.setattr(diagnose.psutil, "process_iter", procs([idle]))
    assert diagnose._installing_updates() is False
    monkeypatch.setattr(diagnose.psutil, "process_iter", procs([idle, ("unattended-upgr", ["/usr/bin/python3", "/usr/bin/unattended-upgrade"])]))
    assert diagnose._installing_updates() is True
    monkeypatch.setattr(diagnose.psutil, "process_iter", procs([("dpkg", ["dpkg", "--configure", "-a"])]))
    assert diagnose._installing_updates() is True


@pytest.mark.skipif(not Path("/usr/share/icons/Adwaita").is_dir(), reason="needs the Adwaita icon theme")
@pytest.mark.skipif(not Path("/usr/share/icons/Yaru").is_dir(), reason="needs Ubuntu's Yaru icon theme")
def test_symbolic_icons_exist_in_adwaita() -> None:
    names = set()
    for p in _gui_sources():
        names |= set(re.findall(r'"([a-z0-9-]+-symbolic)"', p.read_text(encoding="utf-8")))
    # Ubuntu (the supported platform) layers Yaru over Adwaita.
    themes = [Path("/usr/share/icons", t) for t in ("Adwaita", "Yaru", "hicolor") if Path("/usr/share/icons", t).is_dir()]
    have = {f.stem for t in themes for f in t.rglob("*-symbolic.*")}
    assert not sorted(names - have)
