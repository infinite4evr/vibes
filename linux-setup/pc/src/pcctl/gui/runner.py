"""Runs action steps from the desktop app.

Your-account steps run directly. Steps that need admin rights are batched into ONE `pkexec` call, so Ubuntu shows
its normal password popup once per action. Markers printed by the batch script tell us which step is running.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import threading
from typing import Callable

from ..core.run import Step

STEP_MARK = "::pc-step "
RC_MARK = "::pc-rc "


def raw_argv(step: Step) -> list[str]:
    args = list(step.cmd)
    if step.env:
        args = ["env", *[f"{k}={v}" for k, v in step.env.items()], *args]
    return args


HELPER = "/usr/local/libexec/pc-command-center/pc-admin"
POLICY = "/usr/share/polkit-1/actions/io.github.infinite4evr.PcCommandCenter.policy"


def root_prefix() -> list[str]:
    """How to become root: pkexec (password popup) normally; PC_ROOT_RUNNER=sudo for testing."""
    if os.geteuid() == 0:
        return []
    if os.environ.get("PC_ROOT_RUNNER") == "sudo":
        return ["sudo", "-n"]
    return ["pkexec"]


def batch_prefix() -> list[str]:
    """Command that runs our admin batch script as root.

    With the app's polkit policy installed, the password popup names PC Command Center and remembers the password
    for a few minutes; otherwise plain `pkexec /bin/bash` still works."""
    if os.geteuid() == 0:
        return ["/bin/bash"]
    if os.environ.get("PC_ROOT_RUNNER") == "sudo":
        return ["sudo", "-n", "/bin/bash"]
    if os.path.exists(HELPER) and os.path.exists(POLICY):
        return ["pkexec", HELPER]
    return ["pkexec", "/bin/bash"]


class Runner:
    def __init__(self, steps: list[Step], on_step: Callable[[int, str, int | None], None], on_line: Callable[[str], None],
                 on_done: Callable[[bool, str], None]):
        self.steps = steps
        self.on_step = on_step      # (index, state: running|ok|failed|skipped, exit code)
        self.on_line = on_line
        self.on_done = on_done
        self.proc: subprocess.Popen | None = None
        self.cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass

    # ----------------------------------------------------------------
    def _run(self) -> None:
        ok = True
        note = ""
        i = 0
        n = len(self.steps)
        while i < n and not self.cancelled:
            s = self.steps[i]
            is_py = getattr(s, "_func", None) is not None
            if s.root and not is_py and os.geteuid() != 0:
                j = i
                while j < n and self.steps[j].root and getattr(self.steps[j], "_func", None) is None:
                    j += 1
                good, note = self._run_root_batch(i, j)
                if not good:
                    ok = False
                    break
                i = j
                continue
            self.on_step(i, "running", None)
            code = self._run_one(s)
            if code in s.ok_codes:
                self.on_step(i, "ok", code)
            elif s.optional:
                self.on_step(i, "skipped", code)
            else:
                self.on_step(i, "failed", code)
                ok = False
                break
            i += 1
        if self.cancelled:
            ok, note = False, "Stopped."
        self.on_done(ok, note)

    def _stream(self, args: list[str], cwd: str | None = None) -> int:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "NO_COLOR": "1", "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8")}
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         cwd=cwd, env=env, bufsize=0)
        except FileNotFoundError:
            self.on_line(f"{args[0]}: not installed")
            return 127
        buf = b""
        assert self.proc.stdout is not None
        while True:
            chunk = self.proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = buf.replace(b"\r", b"\n").split(b"\n")
            buf = parts.pop()
            for p in parts:
                line = p.decode(errors="replace").rstrip()
                if line:
                    self._handle_line(line)
        if buf.strip():
            self._handle_line(buf.decode(errors="replace").rstrip())
        return self.proc.wait()

    def _handle_line(self, line: str) -> None:
        self.on_line(line)

    def _run_one(self, s: Step) -> int:
        func = getattr(s, "_func", None)
        self.on_line(f"$ {s.display()}")
        if func is not None:
            try:
                msg = func()
                for line in str(msg or "").splitlines():
                    self.on_line(line)
                return 0
            except Exception as e:  # noqa: BLE001
                self.on_line(f"error: {e}")
                return 1
        args = raw_argv(s) if (not s.root or os.geteuid() == 0) else [*root_prefix(), *raw_argv(s)]
        return self._stream(args, s.cwd)

    def _run_root_batch(self, start: int, end: int) -> tuple[bool, str]:
        lines = ["#!/bin/bash", "export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8",
                 '__run() { idx=$1; opt=$2; shift 2; echo "::pc-step $idx"; "$@"; rc=$?; echo "::pc-rc $idx $rc";'
                 ' if [ "$rc" -ne 0 ] && [ "$opt" = 0 ]; then exit 100; fi; }']
        for k in range(start, end):
            s = self.steps[k]
            opt = "1" if s.optional or any(c != 0 for c in s.ok_codes) else "0"
            lines.append(f"__run {k} {opt} {shlex.join(raw_argv(s))}")
        fd, path = tempfile.mkstemp(prefix="pc-admin-", suffix=".sh", dir="/tmp")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o644)
        for k in range(start, end):
            self.on_line(f"$ sudo {self.steps[k].display().removeprefix('sudo ')}")
        self.on_line("(asking for your password…)")
        self._current = start
        self._batch_rc: dict[int, int] = {}
        self._batch_range = (start, end)
        orig = self._handle_line

        def handle(line: str) -> None:
            if line.startswith(STEP_MARK):
                idx = int(line[len(STEP_MARK):].strip() or 0)
                self._current = idx
                self.on_step(idx, "running", None)
                return
            if line.startswith(RC_MARK):
                parts = line[len(RC_MARK):].split()
                idx, rc = int(parts[0]), int(parts[1])
                self._batch_rc[idx] = rc
                st = self.steps[idx]
                self.on_step(idx, "ok" if rc in st.ok_codes else ("skipped" if st.optional else "failed"), rc)
                return
            orig(line)

        self._handle_line = handle  # type: ignore[method-assign]
        try:
            code = self._stream([*batch_prefix(), path])
        finally:
            self._handle_line = orig  # type: ignore[method-assign]
            try:
                os.unlink(path)
            except OSError:
                pass
        if code in (126, 127) and not self._batch_rc:
            self.on_step(start, "failed", code)
            return False, "The password prompt was cancelled, so nothing that needs admin rights was changed."
        if code != 0:
            last = max(self._batch_rc) if self._batch_rc else start
            if self._batch_rc.get(last, 0) == 0:
                self.on_step(last, "failed", code)
            return False, ""
        return True, ""


def capture(steps: list[Step], done: Callable[[bool, list[str]], None]) -> None:
    """Run steps without a dialog (still asks for the password if needed) and hand back their output lines."""
    from gi.repository import GLib
    lines: list[str] = []

    def on_line(line: str) -> None:
        if not line.startswith("$ ") and line != "(asking for your password…)":
            lines.append(line)

    def on_done(ok: bool, _note: str) -> None:
        GLib.idle_add(lambda: (done(ok, lines), False)[1])
    Runner(steps, lambda *_a: None, on_line, on_done).start()
