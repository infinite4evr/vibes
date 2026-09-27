"""Running commands: quick captures for reading state, and Steps for actions the user confirms."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Sequence

from . import debug

HOME = Path.home()
C_ENV = {**os.environ, "LANG": "C", "LC_ALL": "C"}

# Places tools live that aren't always on PATH (uv, pipx, zed, nvm's node, cargo).
EXTRA_PATHS = [HOME / ".local/bin", HOME / ".cargo/bin", Path("/snap/bin")]


def which(cmd: str) -> str | None:
    found = shutil.which(cmd)
    if found:
        return found
    for d in EXTRA_PATHS:
        p = d / cmd
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def du_bin() -> str:
    """GNU du when available. Ubuntu 26.04 ships Rust coreutils as `du` and keeps GNU's as `gnudu`."""
    return which("gnudu") or "du"


def py_size(path: str | Path, one_fs: bool = True, limit_s: float = 60.0) -> int:
    """Pure-Python fallback for du (disk usage in bytes, like du -B1)."""
    import time as _t
    t0 = _t.monotonic()
    p = str(path)
    try:
        st = os.lstat(p)
    except OSError:
        return 0
    if not os.path.isdir(p) or os.path.islink(p):
        return st.st_blocks * 512
    dev = st.st_dev
    total = st.st_blocks * 512
    seen: set[tuple[int, int]] = set()
    for cur, dirs, files in os.walk(p):
        if _t.monotonic() - t0 > limit_s:
            break
        for n in dirs + files:
            fp = os.path.join(cur, n)
            try:
                s2 = os.lstat(fp)
            except OSError:
                continue
            if one_fs and s2.st_dev != dev:
                continue
            key = (s2.st_dev, s2.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += s2.st_blocks * 512
        if one_fs:
            dirs[:] = [d for d in dirs if not os.path.ismount(os.path.join(cur, d))]
    return total


def has(cmd: str) -> bool:
    return which(cmd) is not None


@dataclass
class Result:
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


def sh(
    cmd: Sequence[str] | str,
    *,
    timeout: float = 20,
    root: bool = False,
    env: dict | None = None,
    cwd: str | Path | None = None,
    input: str | None = None,
) -> Result:
    """Run a command and capture its output (C locale so parsers are stable). Never raises."""
    if isinstance(cmd, str):
        args = ["bash", "-c", cmd]
    else:
        args = list(cmd)
    if root and os.geteuid() != 0:
        args = ["sudo", "-n", *args]
    started = time.monotonic()
    if debug.enabled():
        debug.log("probe start root=%s cwd=%s cmd=%s", root, cwd or "", debug.display_argv(args))
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env or C_ENV,
            cwd=cwd,
            input=input,
            errors="replace",
        )
        if debug.enabled():
            debug.log("probe finish rc=%s duration=%.3fs stdout=%sB stderr=%sB cmd=%s", p.returncode,
                      time.monotonic() - started, len(p.stdout or ""), len(p.stderr or ""), debug.display_argv(args))
            # Detailed mode is meant to make parser/probe bugs reproducible. Preserve a
            # bounded, redacted sample for ordinary probes, but suppress output entirely
            # when the command line itself requests a password/token/PSK/credential.
            raw_args = [str(x) for x in args]
            if debug.redact_argv(raw_args) != raw_args:
                debug.log("probe output suppressed because the command accesses sensitive data")
            else:
                if p.stdout:
                    debug.log("probe stdout:\n%s", debug.redact_text(p.stdout[:16000]))
                if p.stderr:
                    debug.log("probe stderr:\n%s", debug.redact_text(p.stderr[:16000]))
        return Result(p.returncode, p.stdout, p.stderr)
    except FileNotFoundError:
        debug.log("probe missing duration=%.3fs cmd=%s", time.monotonic() - started, debug.display_argv(args))
        return Result(127, "", f"{args[0]}: not installed")
    except subprocess.TimeoutExpired:
        debug.log("probe timeout duration=%.3fs cmd=%s", time.monotonic() - started, debug.display_argv(args))
        return Result(124, "", "timed out")
    except OSError as e:  # permission problems etc.
        debug.log("probe os-error duration=%.3fs error=%s cmd=%s", time.monotonic() - started, e, debug.display_argv(args))
        return Result(126, "", str(e))


def out(cmd: Sequence[str] | str, **kw) -> str:
    r = sh(cmd, **kw)
    return r.out.strip() if r.ok else ""


def sudo_ready() -> bool:
    if os.geteuid() == 0:
        return True
    return sh(["sudo", "-n", "true"], timeout=5).ok


def read(path: str | Path, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return default


# ---------------------------------------------------------------- actions


@dataclass
class Step:
    """One command in an action. Shown to the user before it runs."""

    title: str
    cmd: list[str]
    root: bool = False
    env: dict = field(default_factory=dict)
    cwd: str | None = None
    ok_codes: tuple[int, ...] = (0,)
    optional: bool = False  # failure doesn't mark the whole action failed
    sensitive_args: tuple[int, ...] = ()
    sensitive_env: tuple[str, ...] = ()
    cancellable: bool = True
    # Audit metadata. None keeps compatibility with legacy command classification.
    mutates: bool | None = None
    config_key: str = ""
    timeout: float | None = None

    def argv(self) -> list[str]:
        args = list(self.cmd)
        if self.env:
            args = ["env", *[f"{k}={v}" for k, v in self.env.items()], *args]
        if self.root and os.geteuid() != 0:
            args = ["sudo", "-n", *args]
        return args

    def sensitive_values(self) -> tuple[str, ...]:
        values: list[str] = []
        for i in self.sensitive_args:
            if 0 <= i < len(self.cmd):
                values.append(str(self.cmd[i]))
        for key in self.sensitive_env:
            if key in self.env:
                values.append(str(self.env[key]))
        return tuple(v for v in values if v)

    def safe_cmd(self) -> list[str]:
        args = [str(v) for v in self.cmd]
        for i in self.sensitive_args:
            if 0 <= i < len(args):
                args[i] = "<redacted>"
        return args

    def display(self) -> str:
        if self.cmd and self.cmd[0] == "__python__":
            return self.cmd[1]
        args = self.safe_cmd()
        if self.env:
            args = [*[f"{k}={'<redacted>' if k in self.sensitive_env else v}" for k, v in self.env.items()], *args]
        text = shlex.join(args)
        text = debug.redact_text(text, self.sensitive_values())
        return ("sudo " + text) if self.root else text

    def redact(self, text: object) -> str:
        return debug.redact_text(text, self.sensitive_values())


def py_step(title: str, func: Callable[[], str | None], shown: str) -> Step:
    """A step done in Python (e.g. moving files). `shown` describes it for the confirm dialog."""
    s = Step(title=title, cmd=["__python__", shown])
    s._func = func  # type: ignore[attr-defined]
    return s


def needs_root(steps: Iterable[Step]) -> bool:
    return any(s.root for s in steps)


LineCallback = Callable[[str], Awaitable[None] | None]


async def stream(step: Step, on_line: LineCallback) -> int:
    """Run a step, calling on_line for every output line. Returns the exit code."""
    func = getattr(step, "_func", None)
    if func is not None:
        try:
            msg = await asyncio.to_thread(func)
            if msg:
                for line in str(msg).splitlines():
                    r = on_line(line)
                    if asyncio.iscoroutine(r):
                        await r
            return 0
        except Exception as e:  # noqa: BLE001 - report any failure to the user
            r = on_line(f"error: {e}")
            if asyncio.iscoroutine(r):
                await r
            return 1
    try:
        debug.event("step.start", title=step.title, command=step.display(), root=step.root)
        proc = await asyncio.create_subprocess_exec(
            *step.argv(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=step.cwd,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", "NO_COLOR": "1"},
        )
    except FileNotFoundError:
        r = on_line(f"{step.cmd[0]}: not installed")
        if asyncio.iscoroutine(r):
            await r
        return 127
    assert proc.stdout is not None
    buf = b""
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        # Bound even newline-free output so a broken/noisy command cannot grow RAM forever.
        while len(buf) > 65536 and b"\n" not in buf[:65536] and b"\r" not in buf[:65536]:
            part, buf = buf[:65536], buf[65536:]
            r = on_line(step.redact(part.decode(errors="replace")))
            if asyncio.iscoroutine(r):
                await r
        # apt uses \r for progress; treat it as a line break
        parts = buf.replace(b"\r", b"\n").split(b"\n")
        buf = parts.pop()
        for part in parts:
            line = part.decode(errors="replace").rstrip()
            if line:
                r = on_line(step.redact(line))
                if asyncio.iscoroutine(r):
                    await r
    if buf.strip():
        r = on_line(step.redact(buf.decode(errors="replace").rstrip()))
        if asyncio.iscoroutine(r):
            await r
    code = await proc.wait()
    debug.event("step.finish", title=step.title, code=code)
    return code


def run_steps_blocking(steps: Sequence[Step], echo: Callable[[str], None] = print) -> bool:
    """For the CLI: run steps in the foreground with live output. Returns True if all succeeded."""
    ok = True
    for s in steps:
        echo(f"\n\033[1;38;2;203;166;247m▸ {s.title}\033[0m  \033[2m{s.display()}\033[0m")
        func = getattr(s, "_func", None)
        if func is not None:
            try:
                msg = func()
                if msg:
                    echo(str(msg))
                code = 0
            except Exception as e:  # noqa: BLE001
                echo(f"error: {e}")
                code = 1
        else:
            args = list(s.argv())  # root steps use `sudo -n`; the CLI primes sudo before calling this
            try:
                code = subprocess.call(args, cwd=s.cwd, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
            except FileNotFoundError:
                echo(f"{s.cmd[0]}: not installed")
                code = 127
        if code in s.ok_codes:
            try:
                from .config_audit import record_steps
                record_steps(s.title, [s], interface="cli")
            except Exception:
                pass
        elif not s.optional:
            ok = False
            echo(f"\033[38;2;243;139;168m✗ failed (exit {code})\033[0m")
            # Required steps are dependencies for what follows. Match the desktop
            # runner: do not continue into a partially valid action.
            break
    return ok
