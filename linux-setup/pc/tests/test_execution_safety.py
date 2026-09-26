import os
import subprocess
import tempfile
from pathlib import Path

from pcctl.core import debug, tasks
from pcctl.core.run import Step
from pcctl.gui.runner import build_root_batch


def test_step_display_redacts_sensitive_argument():
    s = Step("hotspot", ["nmcli", "dev", "wifi", "hotspot", "password", "SuperSecret123"], sensitive_args=(5,))
    shown = s.display()
    assert "SuperSecret123" not in shown
    assert "<redacted>" in shown
    assert s.argv()[-1] == "SuperSecret123"


def test_root_batch_accepts_only_declared_nonzero_codes():
    steps = [Step("allowed", ["bash", "-c", "exit 10"], ok_codes=(0, 10)),
             Step("must not run", ["bash", "-c", "exit 0"])]
    script = build_root_batch(steps)
    p = subprocess.run(["bash"], input=script, text=True, capture_output=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "::pc-rc 0 10" in p.stdout
    assert "::pc-step 1" in p.stdout


def test_root_batch_rejects_undeclared_nonzero_code():
    steps = [Step("bad", ["bash", "-c", "exit 5"], ok_codes=(0, 10)),
             Step("must not run", ["bash", "-c", "exit 0"])]
    script = build_root_batch(steps)
    p = subprocess.run(["bash"], input=script, text=True, capture_output=True)
    assert p.returncode == 100
    assert "::pc-rc 0 5" in p.stdout
    assert "::pc-step 1" not in p.stdout


def test_optional_root_batch_failure_can_continue():
    steps = [Step("optional", ["bash", "-c", "exit 44"], optional=True),
             Step("next", ["bash", "-c", "exit 0"])]
    p = subprocess.run(["bash"], input=build_root_batch(steps), text=True, capture_output=True)
    assert p.returncode == 0
    assert "::pc-step 1" in p.stdout


def test_task_registry_can_cancel_cancellable_task():
    called = []
    tid = tasks.start("x", cancellable=True, cancel=lambda: called.append(True))
    try:
        assert tasks.cancel(tid)
        assert called == [True]
        tasks.finish(tid, False, cancelled=True)
        snap = next(t for t in tasks.snapshots() if t.id == tid)
        assert snap.status == "cancelled"
    finally:
        tasks.clear_finished()


def test_redact_argv_hides_password_flag_value():
    argv = debug.redact_argv(["nmcli", "wifi", "password", "HorseBatteryStaple"])
    assert "HorseBatteryStaple" not in argv
    assert "<redacted>" in argv


def test_cleanup_does_not_follow_symlinked_parent(tmp_path, monkeypatch):
    from pcctl.core import junk

    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir(); outside.mkdir()
    victim = outside / "keep.txt"
    victim.write_text("important")
    (home / "cache-link").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(junk, "HOME", home)
    msg = junk._rm_paths([str(home / "cache-link" / "keep.txt")])()  # noqa: SLF001
    assert victim.exists()
    assert "skipped" in msg


def test_cleanup_can_unlink_symlink_without_touching_target(tmp_path, monkeypatch):
    from pcctl.core import junk

    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir(); outside.mkdir()
    victim = outside / "keep.txt"
    victim.write_text("important")
    link = home / "link"
    link.symlink_to(victim)

    monkeypatch.setattr(junk, "HOME", home)
    junk._rm_paths([str(link)])()  # noqa: SLF001
    assert not link.exists()
    assert victim.read_text() == "important"


def test_restore_rejects_archive_symlink(tmp_path, monkeypatch):
    import io
    import tarfile
    from pcctl.core import maint

    home = tmp_path / "home"; home.mkdir()
    backups = tmp_path / "backups"
    monkeypatch.setattr(maint, "HOME", home)
    monkeypatch.setattr(maint, "BACKUP_DIR", backups)
    monkeypatch.setattr(maint, "STATE_DIR", home / ".local/state/pc")
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(".config/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/tmp"
        tf.addfile(info)
    step = maint.restore_settings_steps(str(archive))[0]
    try:
        step._func()  # type: ignore[attr-defined]
        assert False, "symlink member should be rejected"
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)


def test_restore_rejects_preexisting_symlink_parent(tmp_path, monkeypatch):
    import io
    import tarfile
    from pcctl.core import maint

    home = tmp_path / "home"; home.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    (home / ".config").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(maint, "HOME", home)
    monkeypatch.setattr(maint, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(maint, "STATE_DIR", home / ".local/state/pc")
    archive = tmp_path / "bad-parent.tar.gz"
    payload = b"do not write outside home"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(".config/tool/settings.txt")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    step = maint.restore_settings_steps(str(archive))[0]
    try:
        step._func()  # type: ignore[attr-defined]
        assert False, "symlinked restore parent should be rejected"
    except ValueError as exc:
        assert "symlink" in str(exc).lower()
    assert not (outside / "tool/settings.txt").exists()


def test_debug_files_are_private(tmp_path, monkeypatch):
    import stat
    from pcctl.core import debug

    debug.configure(False)
    monkeypatch.setattr(debug, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(debug, "LOG_FILE", tmp_path / "logs/debug.log")
    debug.configure(True)
    debug.log("hello password super-secret")
    for h in list(debug._logger.handlers):  # noqa: SLF001
        h.flush()
    assert stat.S_IMODE(debug.LOG_FILE.stat().st_mode) == 0o600
    assert "super-secret" not in debug.LOG_FILE.read_text()
    bundle = debug.export_bundle(tmp_path / "support.zip")
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600
    debug.configure(False)
    debug.clear()
