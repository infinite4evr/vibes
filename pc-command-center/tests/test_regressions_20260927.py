"""Regression tests for the 2026-09-27 reliability pass."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pcctl import cli
from pcctl.core import logs, maint, system, watch
from pcctl.core.run import Result, Step


def test_battery_probe_failures_are_optional(monkeypatch):
    for exc in (FileNotFoundError('/sys/class/power_supply'), NotImplementedError()):
        monkeypatch.setattr(system.psutil, 'sensors_battery', lambda exc=exc: (_ for _ in ()).throw(exc))
        assert system.battery() is None


def test_journal_parser_skips_bad_numeric_records():
    text = '\n'.join([
        '{"__REALTIME_TIMESTAMP":"bad","PRIORITY":3,"MESSAGE":"bad ts"}',
        '{"__REALTIME_TIMESTAMP":"1000000","PRIORITY":"bad","MESSAGE":"bad priority"}',
        '{"__REALTIME_TIMESTAMP":"2000000","PRIORITY":4,"MESSAGE":"good","_COMM":"demo"}',
    ])
    parsed = logs.parse_journal_json(text)
    assert len(parsed) == 1
    assert parsed[0].message == 'good'


@pytest.mark.parametrize('text', ['2hblah', 'abc2hxyz', '1h30mgarbage', '2hours'])
def test_duration_rejects_partial_matches(text):
    with pytest.raises(ValueError):
        cli._parse_duration(text)


def test_duration_still_accepts_compound_values():
    assert cli._parse_duration('1h 30m 5s') == 5405


def test_maintenance_does_not_report_failed_command_as_ok(monkeypatch, tmp_path):
    step = Step('Cleanup demo', ['false'])
    monkeypatch.setattr(maint, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(maint.junk, 'auto_candidates', lambda: {})
    monkeypatch.setattr(maint.junk, 'safe_user_steps', lambda _found: [step])
    monkeypatch.setattr(maint, 'sh', lambda *_a, **_kw: Result(1, '', 'permission denied'))
    monkeypatch.setattr(maint.shutil, 'disk_usage', lambda _p: SimpleNamespace(free=1000))
    monkeypatch.setattr(maint.system, 'mounts', lambda: [])
    monkeypatch.setattr(maint.packages, 'parse_apt_upgradable', lambda _x: [])
    monkeypatch.setattr(maint, 'out', lambda *_a, **_kw: '')
    monkeypatch.setattr(maint.services, 'failed', lambda: [])
    monkeypatch.setattr(maint.system, 'reboot_required', lambda: None)
    monkeypatch.setattr(maint, 'notify', lambda *_a, **_kw: None)
    maint.maintain_auto()
    log = (tmp_path / 'maintain.log').read_text()
    assert 'Cleanup demo: permission denied' in log
    assert 'Cleanup demo: ok' not in log


def test_watch_trash_scan_tolerates_disappearing_file(monkeypatch, tmp_path):
    trash_files = tmp_path / '.local/share/Trash/files'
    trash_files.mkdir(parents=True)
    victim = trash_files / 'gone'
    victim.write_bytes(b'x')
    original_stat = type(victim).stat

    def flaky_stat(self, *args, **kwargs):
        if self == victim:
            raise FileNotFoundError(self)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(watch, 'HOME', tmp_path)
    monkeypatch.setattr(type(victim), 'stat', flaky_stat)
    monkeypatch.setattr(watch.system, 'mounts', lambda: [])
    monkeypatch.setattr(watch.system, 'reboot_required', lambda: None)
    monkeypatch.setattr(watch.system, 'battery', lambda: None)
    monkeypatch.setattr(watch.system, 'cpu_temp', lambda: None)
    cfg = {**watch.DEFAULTS, 'security_updates': False, 'failed_services': False, 'trash_gb': 1}
    assert watch.checks(cfg) == []


def test_timer_execstart_is_safely_quoted(monkeypatch, tmp_path):
    monkeypatch.setattr(maint, 'UNIT_DIR', tmp_path)
    monkeypatch.setattr(maint, 'pc_command', lambda: '/tmp/My Tools/pc')
    step = maint.enable_timer_steps()[0]
    step._func()
    text = (tmp_path / 'pc-maintain.service').read_text()
    assert 'ExecStart=/bin/bash -lc "' in text
    assert '/tmp/My Tools/pc maintain --auto' in text
