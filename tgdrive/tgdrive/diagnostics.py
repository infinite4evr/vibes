"""Crash reports, diagnostics bundles and settings export / import.

Crashes (Python errors that reach the top, errors in background tasks, the web page's
own errors and the window's renderer dying) are written to <data>/crashes as small
text files. The app shows a notice after one happens, and everything stays on this
computer: a diagnostics bundle is a .zip you create yourself (Settings → About) and
decide whether to send. Bundles are redacted: phone numbers, API keys, tokens and
e-mail addresses are removed, and chat and file names too unless you include them.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from . import config

log = logging.getLogger("tgdrive.diagnostics")

MAX_REPORTS = 60
_lock = threading.Lock()
_recent: dict[str, float] = {}


def crash_dir() -> Path:
    d = config.DATA_DIR / "crashes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seen_path() -> Path:
    return crash_dir() / "seen.json"


def record_crash(kind: str, text: str, context: Optional[dict] = None) -> Optional[str]:
    """Save one crash report; identical reports within a minute are counted once."""
    from .settings import settings
    if not settings.get("crash_reports", True):
        return None
    sig = f"{kind}:{text[-600:]}"
    with _lock:
        now = time.time()
        if now - _recent.get(sig, 0) < 60:
            return None
        _recent[sig] = now
        if len(_recent) > 200:
            _recent.clear()
        rid = f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{int(now * 1000) % 100000:05d}"
        body = [f"TG Drive {config.VERSION} crash report", f"kind: {kind}",
                f"time: {time.strftime('%Y-%m-%d %H:%M:%S %z')}", f"python: {sys.version.split()[0]}",
                f"system: {platform.platform()}"]
        for k, v in (context or {}).items():
            body.append(f"{k}: {str(v)[:2000]}")
        body += ["", text.rstrip()[:50_000], ""]
        body += _state_sections()
        try:
            (crash_dir() / f"{rid}.txt").write_text("\n".join(body), encoding="utf-8")
            reports = sorted(crash_dir().glob("*.txt"))
            for old in reports[:-MAX_REPORTS]:
                old.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not save crash report: %s", exc)
            return None
    log.error("crash recorded (%s): %s", kind, text.strip().splitlines()[-1][:300] if text.strip() else kind)
    log.debug("crash report %s in full:\n%s", rid, "\n".join(body))
    try:
        from .accounts import events
        events.push("crash", id=rid, kind=kind)
    except Exception:
        pass
    return rid


# ------------------------------------------------------- context for reports
# Every crash report ends with what the app was doing: a snapshot from each registered provider
# (accounts, transfers, running background tasks, threads, memory) and the last log lines, so a
# report on its own is usually enough to see what went wrong.
_providers: dict[str, Callable[[], Any]] = {}
_STARTED = time.time()


def add_state_provider(name: str, fn: Callable[[], Any]) -> None:
    _providers[name] = fn


def _state_sections() -> list[str]:
    out = ["--- state ---", f"uptime: {int(time.time() - _STARTED)} s", f"pid: {os.getpid()}"]
    try:
        rss = next((ln.split()[1] for ln in Path("/proc/self/status").read_text().splitlines()
                    if ln.startswith("VmRSS:")), None)
        if rss:
            out.append(f"memory (RSS): {int(rss) // 1024} MB")
    except (OSError, ValueError):
        pass
    out.append("threads: " + ", ".join(sorted(th.name for th in threading.enumerate())))
    for name, fn in list(_providers.items()):
        try:
            out.append(f"{name}: {json.dumps(fn(), default=str)[:4000]}")
        except Exception as exc:  # a provider must never stop a report
            out.append(f"{name}: (unavailable: {exc!r})")
    lines = ring.lines()
    if lines:
        out += ["", f"--- last {len(lines)} log lines ---", *lines]
    return out + [""]


class RingHandler(logging.Handler):
    """Keeps the last few hundred log lines in memory for crash reports."""

    def __init__(self, size: int = 300):
        super().__init__(logging.DEBUG)
        from collections import deque
        self.buf: "deque[str]" = deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s %(name)s [%(threadName)s] %(message)s",
                                            "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if record.exc_info and "Traceback" not in msg:
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info))[-3000:]
            self.buf.append(msg[:4000])
        except Exception:
            pass

    def lines(self, n: int = 120) -> list[str]:
        return list(self.buf)[-n:]


ring = RingHandler()


def enable_faulthandler(name: str) -> None:
    """Hard crashes (a segfault in a native library) leave no Python traceback; faulthandler writes the
    stacks of all threads to a file instead. A non-empty file found at the next start becomes a crash
    report. `kill -USR1 <pid>` also dumps the stacks there (for a hang)."""
    import faulthandler
    import signal
    path = crash_dir() / f"faulthandler-{name}.log"
    try:
        if path.exists() and path.stat().st_size > 0:
            text = path.read_text(encoding="utf-8", errors="replace")
            if "Fatal Python error" in text or "Segmentation fault" in text or "Aborted" in text:
                record_crash("native", text, {"process": name, "note": "found at startup: the previous run "
                                                                     "crashed inside native code"})
            path.unlink(missing_ok=True)
        fh = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=fh, all_threads=True)
        if hasattr(signal, "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=fh, all_threads=True, chain=False)
        global _fault_file
        _fault_file = fh   # keep it open for the life of the process
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("faulthandler unavailable: %s", exc)


_fault_file = None


class LoopWatchdog:
    """Notices when the event loop stops answering (something blocking it) and records a "hang" report
    with the stack of the loop's thread, which shows exactly what blocked it."""

    def __init__(self, loop, threshold: float = 10.0):
        self.loop = loop
        self.threshold = threshold
        self.loop_thread = threading.get_ident()
        self.stop = threading.Event()
        self.reported = False
        threading.Thread(target=self._run, name="tgdrive-loop-watchdog", daemon=True).start()

    def _stamp(self) -> None:   # runs on the loop: it answered
        self.waiting_since = 0.0
        self.reported = False

    def _run(self) -> None:
        # One ping at a time: the loop answers it at its next turn. How long the oldest unanswered ping has
        # waited is how long the loop has been stuck (an idle loop answers at once).
        self.waiting_since = 0.0
        while not self.stop.wait(0.5):
            now = time.monotonic()
            if not self.waiting_since:
                self.waiting_since = now
                try:
                    self.loop.call_soon_threadsafe(self._stamp)
                except RuntimeError:   # loop closed
                    return
                continue
            late = now - self.waiting_since
            if late > self.threshold and not self.reported:
                self.reported = True
                frame = sys._current_frames().get(self.loop_thread)
                stack = "".join(traceback.format_stack(frame)) if frame else "(no stack)"
                record_crash("hang", f"The service stopped responding for {late:.0f} s. What it was doing:\n{stack}",
                             {"blocked_for": f"{late:.1f} s"})


def record_exception(kind: str, exc: BaseException, context: Optional[dict] = None) -> Optional[str]:
    return record_crash(kind, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), context)


def install_hooks() -> None:
    """Catch errors nobody handled: main thread, other threads."""
    prev = sys.excepthook

    def hook(t, v, tb):
        if not issubclass(t, KeyboardInterrupt):
            record_crash("python", "".join(traceback.format_exception(t, v, tb)))
        prev(t, v, tb)

    sys.excepthook = hook

    def thook(args):
        if args.exc_type is not SystemExit:
            record_crash("thread", "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                                    args.exc_traceback)),
                         {"thread": getattr(args.thread, "name", "?")})

    threading.excepthook = thook


def asyncio_handler(loop, context: dict) -> None:
    exc = context.get("exception")
    msg = context.get("message", "")
    if exc is None or isinstance(exc, (ConnectionError, TimeoutError)) or "Task was destroyed" in msg:
        log.debug("asyncio: %s (%r)", msg, exc, exc_info=exc if isinstance(exc, BaseException) else None)
        loop.default_exception_handler(context)
        return
    record_exception("background", exc, {"message": msg})
    loop.default_exception_handler(context)


def list_crashes() -> dict:
    seen = set()
    try:
        seen = set(json.loads(_seen_path().read_text()))
    except (OSError, ValueError):
        pass
    out = []
    for p in sorted(crash_dir().glob("*.txt"), reverse=True):
        try:
            head = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [ln for ln in head.splitlines() if ln.strip()]
        last = next((ln for ln in reversed(lines) if not ln.startswith(" ")), "")
        kind = next((ln[6:] for ln in lines if ln.startswith("kind: ")), "")
        out.append({"id": p.stem, "kind": kind, "at": int(p.stat().st_mtime), "summary": last[:300],
                    "new": p.stem not in seen})
    return {"reports": out, "unseen": sum(1 for r in out if r["new"])}


def read_crash(rid: str) -> str:
    if not re.fullmatch(r"[\w\-]+", rid):
        raise ValueError("Unknown report.")
    p = crash_dir() / f"{rid}.txt"
    if not p.exists():
        raise ValueError("That report no longer exists.")
    return p.read_text(encoding="utf-8", errors="replace")


def mark_seen() -> None:
    ids = [p.stem for p in crash_dir().glob("*.txt")]
    _seen_path().write_text(json.dumps(ids))


def clear_crashes() -> int:
    n = 0
    for p in crash_dir().glob("*.txt"):
        p.unlink(missing_ok=True)
        n += 1
    _seen_path().unlink(missing_ok=True)
    return n


# --------------------------------------------------------------- redaction
PHONE = re.compile(r"(?<![\w.])\+?\d[\d \-]{8,16}\d(?![\w.])")
HEX32 = re.compile(r"\b[0-9a-f]{32}\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
TOKEN = re.compile(r"([?&](?:t|token)=|tgd=|X-TGDrive-Token: ?|/dav/)[\w\-]{8,}", re.I)
QUOTED = re.compile(r"“[^”]{1,200}”|\"(?![^\"\n]*\.py\")[^\"\n]{1,200}\"")  # keeps traceback paths
# Telegram file names in log lines ("… Lecture 10 - Quantum Mechanics.mp4"): up to six words before the extension.
FILE_NAME = re.compile(r"(?:[^\s/\\\"“”<>|:=]+ ){0,6}[^\s/\\\"“”<>|:=]+\.(?:pdf|mp4|mkv|avi|mov|webm|m4v|jpe?g|png|webp|heic|"
                       r"gif|bmp|tiff?|mp3|m4a|aac|ogg|oga|opus|flac|wav|docx?|xlsx?|pptx?|odt|ods|odp|rtf|epub|mobi|"
                       r"djvu|zip|rar|7z|tar|gz|apk|csv|txt|srt)\b", re.I)


def redact(text: str, names: list[str], include_names: bool) -> str:
    from .settings import settings
    text = TOKEN.sub(lambda m: m.group(1) + "…", text)
    for secret in (settings.get("api_hash"), settings.get("proxy_pass"), settings.get("dav_secret"),
                   config.ACCESS_TOKEN, config.MEDIA_TOKEN):
        if secret and len(str(secret)) >= 6:
            text = text.replace(str(secret), "[secret]")
    text = HEX32.sub("[hex]", text)
    text = EMAIL.sub("[email]", text)
    text = PHONE.sub("[number]", text)
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    if not include_names:
        for n in sorted({n for n in names if n and len(n) >= 4}, key=len, reverse=True):
            text = text.replace(n, "[name]")
        text = QUOTED.sub("“[name]”", text)
        text = FILE_NAME.sub("[file]", text)
    return text


# ------------------------------------------------------------ system info
def system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "tgdrive": config.VERSION, "python": sys.version, "platform": platform.platform(),
        "machine": platform.machine(), "libc": " ".join(platform.libc_ver()),
        "packaged": config.PACKAGED, "appimage": bool(os.environ.get("APPIMAGE")),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP"), "session": os.environ.get("XDG_SESSION_TYPE"),
        "wayland": bool(os.environ.get("WAYLAND_DISPLAY")), "lang": os.environ.get("LANG"),
        "data_dir_free_gb": None, "memory": None, "packages": {},
    }
    try:
        st = os.statvfs(config.DATA_DIR)
        info["data_dir_free_gb"] = round(st.f_bavail * st.f_frsize / 1024 ** 3, 1)
    except OSError:
        pass
    try:
        mem = Path("/proc/meminfo").read_text().splitlines()[:3]
        info["memory"] = "; ".join(" ".join(x.split()) for x in mem)
    except OSError:
        pass
    try:
        from importlib import metadata
        for pkg in ("telethon", "cryptg", "fastapi", "uvicorn", "numpy", "rapidfuzz", "tokenizers", "PyQt6",
                    "PyQt6-WebEngine", "segno", "hachoir", "python-socks", "indic-transliteration"):
            try:
                info["packages"][pkg] = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                info["packages"][pkg] = None
    except Exception:
        pass
    try:
        from PyQt6.QtCore import QT_VERSION_STR
        info["qt"] = QT_VERSION_STR
    except Exception:
        info["qt"] = None
    return info


def account_info(acc) -> dict:
    db = acc.db
    out = {"status": acc.status, "error": acc.error, "premium": acc.premium,
           "schema": db.conn.execute("PRAGMA user_version").fetchone()[0],
           "files": db.totals(), "chats": db.one("SELECT COUNT(*) AS n FROM chats")["n"],
           "folders": db.one("SELECT COUNT(*) AS n FROM folders")["n"],
           "placements": db.one("SELECT COUNT(*) AS n FROM placements")["n"],
           "index": acc.indexer.status(), "search": db.search_upgrade_status(), "semantic": acc.semantic.status(),
           "subjects": acc.subjects.status(), "drive": acc.drive.info(), "transfers": acc.transfers.summary(),
           "transfer_errors": db.q("SELECT error, COUNT(*) AS n FROM transfers WHERE status='error' GROUP BY error "
                                   "LIMIT 20"),
           "sync_pairs": [{k: p[k] for k in ("id", "state", "error", "enabled", "approved", "files", "pending")}
                          for p in acc.sync.pairs()],
           "db_bytes": db.path.stat().st_size if db.path.exists() else 0}
    return out


def build_bundle(accounts: list, include_names: bool = False, dest_dir: Optional[Path] = None) -> Path:
    from . import maintenance
    from .settings import settings, SECRET
    names: list[str] = []
    for acc in accounts:
        try:
            names += [r["title"] for r in acc.db.q("SELECT title FROM chats")]
            names += [r["name"] for r in acc.db.q("SELECT name FROM folders")]
            info = acc.info()
            names += [str(info.get("name") or ""), str(info.get("username") or "")]
        except Exception:
            pass
    dest_dir = dest_dir or Path(settings.get("download_dir") or config.default_download_dir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"tgdrive-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    def r(text: str) -> str:
        return redact(text, names, include_names)

    pub = {k: v for k, v in settings.data.items() if k not in SECRET and k not in ("dav_secret",)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "TG Drive diagnostics bundle. Created on request; nothing was sent anywhere.\n"
                                 f"Names {'included' if include_names else 'removed'}. Phone numbers, keys, tokens and "
                                 "e-mail addresses removed.\n")
        z.writestr("system.json", r(json.dumps(system_info(), indent=2, default=str)))
        z.writestr("settings.json", r(json.dumps(pub, indent=2, ensure_ascii=False, default=str)))
        for i, acc in enumerate(accounts, 1):
            try:
                z.writestr(f"account-{i}.json", r(json.dumps(account_info(acc), indent=2, default=str)))
            except Exception as exc:
                z.writestr(f"account-{i}.json", json.dumps({"error": str(exc)}))
        for p in sorted(config.LOG_DIR.glob("tgdrive*.log*")):
            try:
                z.writestr(f"logs/{p.name}", r(p.read_text(encoding="utf-8", errors="replace")[-3_000_000:]))
            except OSError:
                pass
        for p in sorted(crash_dir().glob("*.txt"))[-30:]:
            try:
                z.writestr(f"crashes/{p.name}", r(p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
        z.writestr("data.json", json.dumps(maintenance.data_summary()).replace(str(Path.home()), "~"))
    return path


# ---------------------------------------------------------- settings export
NOT_EXPORTED = {"lock_enabled", "lock_hash", "lock_salt", "dav_secret", "proxy_pass", "proxy_secret", "api_hash"}


def export_settings(include_api: bool = False) -> dict:
    from .settings import settings
    data = {k: v for k, v in settings.data.items() if k not in NOT_EXPORTED}
    if include_api:
        data["api_hash"] = settings.get("api_hash")
        data["proxy_pass"] = settings.get("proxy_pass")
        data["proxy_secret"] = settings.get("proxy_secret")
    else:
        data.pop("api_id", None)
    return {"app": "tgdrive-settings", "version": 1, "tgdrive": config.VERSION, "exported": int(time.time()),
            "settings": data}


def import_settings(doc: dict) -> dict:
    from .settings import DEFAULTS, settings, SettingsError
    if not isinstance(doc, dict) or doc.get("app") != "tgdrive-settings" or not isinstance(doc.get("settings"), dict):
        raise ValueError("That file isn't a TG Drive settings export.")
    good, skipped = {}, []
    for k, v in doc["settings"].items():
        if k in ("lock_enabled", "lock_hash", "lock_salt", "dav_secret") or k not in DEFAULTS:
            skipped.append(k)
            continue
        if k == "download_dir" and v and not Path(str(v)).expanduser().parent.exists():
            skipped.append(k)
            continue
        try:
            good[k] = settings._clean(k, v)
        except SettingsError:
            skipped.append(k)
    changed = settings.update(good) if good else set()
    return {"applied": sorted(good), "changed": sorted(changed), "skipped": skipped}
