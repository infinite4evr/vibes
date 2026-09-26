"""Runs action steps from the desktop app.

User-account steps run directly. Consecutive admin steps are batched into one
``pkexec`` call, so Ubuntu normally asks for the password once per action.

The runner is also the bridge to the global task centre: every command action is
visible there, output is redacted before it reaches history/debug logs, and Stop uses
process groups so child processes are not accidentally left behind.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import tempfile
import threading
from typing import Callable

from ..core import debug, tasks
from ..core.run import Step

STEP_MARK = "::pc-step "
RC_MARK = "::pc-rc "


def raw_argv(step: Step) -> list[str]:
    """Real argv used for execution. Never display or log this directly."""
    args = list(step.cmd)
    if step.env:
        args = ["env", *[f"{k}={v}" for k, v in step.env.items()], *args]
    return args


HELPER = "/usr/local/libexec/pc-command-center/pc-admin"
POLICY = "/usr/share/polkit-1/actions/io.github.infinite4evr.PcCommandCenter.policy"

# Interrupting these in the middle can leave package, boot or filesystem state broken.
# A Stop request waits for the current unsafe step/batch and prevents subsequent steps.
_NO_HARD_CANCEL = {
    "apt", "apt-get", "dpkg", "fwupdmgr", "update-grub", "grub-mkconfig",
    "mkfs", "mkswap", "swapoff", "swapon", "resize2fs", "xfs_growfs", "fsck",
}


def root_prefix() -> list[str]:
    """How to become root: pkexec normally; PC_ROOT_RUNNER=sudo for tests."""
    if os.geteuid() == 0:
        return []
    if os.environ.get("PC_ROOT_RUNNER") == "sudo":
        return ["sudo", "-n"]
    return ["pkexec"]


def batch_prefix() -> list[str]:
    """Command that runs our private admin batch script as root."""
    if os.geteuid() == 0:
        return ["/bin/bash"]
    if os.environ.get("PC_ROOT_RUNNER") == "sudo":
        return ["sudo", "-n", "/bin/bash"]
    if os.path.exists(HELPER) and os.path.exists(POLICY):
        return ["pkexec", HELPER]
    return ["pkexec", "/bin/bash"]


def _hard_cancel_safe(steps: list[Step]) -> bool:
    for s in steps:
        if not s.cancellable:
            return False
        if s.cmd and os.path.basename(s.cmd[0]) in _NO_HARD_CANCEL:
            return False
    return True


def build_root_batch(steps: list[Step], start: int = 0, end: int | None = None, cancel_path: str | None = None) -> str:
    """Build the private root batch script. Kept pure so the safety rule is testable."""
    end = len(steps) if end is None else end
    lines = [
        "#!/bin/bash",
        "set +e",
        "export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8",
        '__run() { idx=$1; opt=$2; allowed=$3; shift 3; echo "::pc-step $idx"; "$@"; rc=$?; '
        'echo "::pc-rc $idx $rc"; case ",$allowed," in *",$rc,"*) good=1 ;; *) good=0 ;; esac; '
        'if [ "$good" -ne 1 ] && [ "$opt" = 0 ]; then exit 100; fi; }',
    ]
    for k in range(start, end):
        s = steps[k]
        opt = "1" if s.optional else "0"
        allowed = ",".join(str(c) for c in s.ok_codes)
        lines.append(f"__run {k} {opt} {shlex.quote(allowed)} {shlex.join(raw_argv(s))}")
        if cancel_path:
            # A critical root command must be allowed to finish, but a cancellation
            # request must stop the batch before the next root command begins.
            lines.append(f'[ "$(cat {shlex.quote(cancel_path)} 2>/dev/null)" = 1 ] && exit 130')
    return "\n".join(lines) + "\n"


class Runner:
    def __init__(self, steps: list[Step], on_step: Callable[[int, str, int | None], None], on_line: Callable[[str], None],
                 on_done: Callable[[bool, str], None], title: str = "PC Command Center task"):
        self.steps = steps
        self.title = title
        self.on_step = on_step      # (index, state: running|ok|failed|skipped, exit code)
        self.on_line = on_line
        self.on_done = on_done
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self._current_steps: list[Step] = []
        self._task_id: str | None = None
        self._cancel_lock = threading.RLock()
        self._batch_cancel_path: str | None = None
        self._secrets = tuple(v for s in steps for v in s.sensitive_values())

    @property
    def task_id(self) -> str | None:
        return self._task_id

    def start(self) -> None:
        if self._task_id is None:
            self._task_id = tasks.start(self.title, kind="command", cancellable=True, cancel=self.cancel,
                                        detail=f"{len(self.steps)} step{'s' if len(self.steps) != 1 else ''}")
        debug.event("runner.start", title=self.title, steps=len(self.steps))
        threading.Thread(target=self._run, name=f"pc-runner-{self._task_id}", daemon=True).start()

    def cancel(self) -> None:
        """Request cancellation. Unsafe package/boot/filesystem steps finish first."""
        with self._cancel_lock:
            self.cancelled = True
            unsafe = not _hard_cancel_safe(self._current_steps)
            if unsafe:
                self._emit("Stop requested. The current system-critical step will finish safely; later steps will not start.")
                if self._batch_cancel_path:
                    try:
                        with open(self._batch_cancel_path, "w", encoding="ascii") as f:
                            f.write("1\n")
                            f.flush()
                            os.fsync(f.fileno())
                    except OSError:
                        pass
                if self._task_id:
                    tasks.update(self._task_id, status="cancelling", detail="Waiting for a system-critical step to finish safely…")
                return
            proc = self.proc
            if proc and proc.poll() is None:
                self._emit("Stopping the running process…")
                try:
                    # _stream creates a new session, so this stops its descendants too.
                    os.killpg(proc.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    try:
                        proc.terminate()
                    except OSError:
                        pass

    # ----------------------------------------------------------------
    def _run(self) -> None:
        ok = True
        note = ""
        i = 0
        n = len(self.steps)
        try:
            while i < n and not self.cancelled:
                s = self.steps[i]
                is_py = getattr(s, "_func", None) is not None
                if s.root and not is_py and os.geteuid() != 0:
                    j = i
                    while j < n and self.steps[j].root and getattr(self.steps[j], "_func", None) is None:
                        j += 1
                    self._current_steps = self.steps[i:j]
                    good, note = self._run_root_batch(i, j)
                    self._current_steps = []
                    if not good:
                        ok = False
                        break
                    i = j
                    continue
                self._current_steps = [s]
                self._step(i, "running", None)
                code = self._run_one(s)
                self._current_steps = []
                if code in s.ok_codes:
                    self._step(i, "ok", code)
                elif s.optional:
                    self._step(i, "skipped", code)
                else:
                    self._step(i, "failed", code)
                    ok = False
                    break
                i += 1
        except Exception as e:  # noqa: BLE001
            ok = False
            note = f"Unexpected runner error: {e}"
            debug.exception("runner", e)
            self._emit(note)
        if self.cancelled:
            ok, note = False, "Stopped."
        if self._task_id:
            tasks.finish(self._task_id, ok, cancelled=self.cancelled, detail=note or ("Completed" if ok else "Failed"))
        debug.event("runner.finish", title=self.title, ok=ok, cancelled=self.cancelled, note=note)
        self.on_done(ok, note)

    def _step(self, index: int, state: str, code: int | None) -> None:
        if self._task_id:
            title = self.steps[index].title if index < len(self.steps) else self.title
            tasks.update(self._task_id, detail=(f"{title}" if state == "running" else f"{title} · {state}"))
        debug.event("runner.step", title=self.title, index=index, state=state, code=code if code is not None else "")
        self.on_step(index, state, code)

    def _emit(self, line: object) -> None:
        safe = debug.redact_text(line, self._secrets)
        if self._task_id:
            tasks.log(self._task_id, safe)
        debug.log("task[%s] %s", self.title, safe)
        self.on_line(safe)

    def _stream(self, args: list[str], cwd: str | None = None) -> int:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "NO_COLOR": "1", "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8")}
        safe_cmd = debug.display_argv(args, extra_values=self._secrets)
        debug.log("exec start cwd=%s cmd=%s", cwd or "", safe_cmd)
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         cwd=cwd, env=env, bufsize=0, start_new_session=True)
            if self._task_id:
                tasks.update(self._task_id, pid=self.proc.pid)
        except FileNotFoundError:
            self._emit(f"{debug.redact_text(args[0])}: not installed")
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
        code = self.proc.wait()
        debug.log("exec finish rc=%s cmd=%s", code, safe_cmd)
        if self._task_id:
            tasks.update(self._task_id, pid=0)
        return code

    def _handle_line(self, line: str) -> None:
        self._emit(line)

    def _run_one(self, s: Step) -> int:
        func = getattr(s, "_func", None)
        self._emit(f"$ {s.display()}")
        if func is not None:
            try:
                msg = func()
                for line in str(msg or "").splitlines():
                    self._emit(s.redact(line))
                return 0
            except Exception as e:  # noqa: BLE001
                self._emit(f"error: {s.redact(e)}")
                debug.exception(f"python step: {s.title}", e)
                return 1
        args = raw_argv(s) if (not s.root or os.geteuid() == 0) else [*root_prefix(), *raw_argv(s)]
        return self._stream(args, s.cwd)

    def _run_root_batch(self, start: int, end: int) -> tuple[bool, str]:
        # IMPORTANT: exact allowed return codes are enforced in the root process too.
        # Older code treated "has any non-zero allowed code" as "all failures are OK".
        # Keep the batch under /tmp for compatibility with already-installed pc-admin
        # helpers. A second private flag lets a Stop request halt a root batch *between*
        # critical steps without killing apt/dpkg/boot/filesystem tools mid-transaction.
        cfd, cancel_path = tempfile.mkstemp(prefix="pc-admin-cancel-", suffix=".flag", dir="/tmp")
        with os.fdopen(cfd, "w", encoding="ascii") as cf:
            cf.write("0\n")
            cf.flush()
            os.fsync(cf.fileno())
        os.chmod(cancel_path, 0o600)
        self._batch_cancel_path = cancel_path
        script = build_root_batch(self.steps, start, end, cancel_path)
        fd, path = tempfile.mkstemp(prefix="pc-admin-", suffix=".sh", dir="/tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(script)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(path, 0o600)
            for k in range(start, end):
                self._emit(f"$ sudo {self.steps[k].display().removeprefix('sudo ')}")
            self._emit("(asking for your password…)")
            self._current = start
            self._batch_rc: dict[int, int] = {}
            self._batch_range = (start, end)
            orig = self._handle_line

            def handle(line: str) -> None:
                if line.startswith(STEP_MARK):
                    idx = int(line[len(STEP_MARK):].strip() or 0)
                    self._current = idx
                    self._step(idx, "running", None)
                    return
                if line.startswith(RC_MARK):
                    parts = line[len(RC_MARK):].split()
                    idx, rc = int(parts[0]), int(parts[1])
                    self._batch_rc[idx] = rc
                    st = self.steps[idx]
                    self._step(idx, "ok" if rc in st.ok_codes else ("skipped" if st.optional else "failed"), rc)
                    return
                orig(line)

            self._handle_line = handle  # type: ignore[method-assign]
            try:
                code = self._stream([*batch_prefix(), path])
            finally:
                self._handle_line = orig  # type: ignore[method-assign]
        finally:
            self._batch_cancel_path = None
            for tmp in (path, cancel_path):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        if self.cancelled:
            return False, "Stopped."
        if code in (126, 127) and not self._batch_rc:
            self._step(start, "failed", code)
            return False, "The password prompt was cancelled, so nothing that needs admin rights was changed."
        if code != 0:
            last = max(self._batch_rc) if self._batch_rc else start
            if self._batch_rc.get(last, 0) == 0:
                self._step(last, "failed", code)
            return False, ""
        return True, ""


def capture(steps: list[Step], done: Callable[[bool, list[str]], None], title: str = "Background command") -> None:
    """Run steps without a dialog and hand back their redacted output lines."""
    from gi.repository import GLib
    lines: list[str] = []

    def on_line(line: str) -> None:
        if not line.startswith("$ ") and line != "(asking for your password…)":
            lines.append(line)

    def on_done(ok: bool, _note: str) -> None:
        GLib.idle_add(lambda: (done(ok, lines), False)[1])
    Runner(steps, lambda *_a: None, on_line, on_done, title=title).start()
