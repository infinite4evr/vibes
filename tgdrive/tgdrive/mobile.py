"""Running TG Drive's service inside the Android app.

The app embeds this package with Chaquopy (Python 3.13 in the app's own process) and talks to it
over HTTP on 127.0.0.1, exactly like the desktop window does. The app calls:

    start(options_json) -> '{"port": …, "media_port": …, …}'   once, from a background thread
    stop()                                                     when the service is shutting down

What is different from a computer, and handled here:
  * SQLite in the Android build of Python has no full-text search. The app ships SQLite's own
    FTS5 module (built from SQLite 3.50.4 with the NDK); it is registered with
    sqlite3_auto_extension before any database opens, so every connection has it.
  * cryptg has no Android build: Telethon is pointed at OpenSSL's AES (fastcrypto.py).
  * Paths come from the app (its private storage, the phone's Download folder, the bundled
    meaning model), and the server runs on a thread, not as its own process.
  * No faulthandler: Android's runtime owns SIGSEGV/SIGUSR1 in the app process.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("tgdrive.mobile")

_lock = threading.Lock()
_state: dict[str, Any] = {"server": None, "thread": None}


def enable_fts5(library: str) -> str:
    """Make FTS5 available on every SQLite connection opened from now on. Returns how: "builtin" or
    "extension". Raises RuntimeError if FTS5 still isn't there."""
    import ctypes
    import sqlite3
    if _has_fts5():
        return "builtin"
    ext = ctypes.CDLL(library)
    core = _sqlite_core(ctypes)
    core.sqlite3_auto_extension.argtypes = [ctypes.c_void_p]
    core.sqlite3_auto_extension.restype = ctypes.c_int
    rc = core.sqlite3_auto_extension(ctypes.cast(ext.sqlite3_fts5_init, ctypes.c_void_p))
    if rc != 0:
        raise RuntimeError(f"sqlite3_auto_extension failed ({rc})")
    if not _has_fts5():
        raise RuntimeError(f"FTS5 did not load (SQLite {sqlite3.sqlite_version})")
    return "extension"


def _has_fts5() -> bool:
    import sqlite3
    c = sqlite3.connect(":memory:")
    try:
        c.execute("CREATE VIRTUAL TABLE temp.t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


def _sqlite_core(ctypes):
    """The libsqlite3 that Python's sqlite3 module is linked to (already loaded in this process)."""
    import sqlite3  # noqa: F401  (loads it)
    for name in ("libsqlite3_python.so", "libsqlite3_chaquopy.so", "libsqlite3.so", "libsqlite3.so.0"):
        try:
            lib = ctypes.CDLL(name)
            lib.sqlite3_auto_extension
            return lib
        except (OSError, AttributeError):
            continue
    raise RuntimeError("the SQLite library Python uses wasn't found")


def start(options: str) -> str:
    """Start the service. `options` is JSON:
        data_dir       where accounts, the index and caches live (app-private storage)
        download_dir   where downloads go
        model_dir      the meaning model (tokenizer JSON + weights), shipped in the app
        fts5_library   path or name of the FTS5 SQLite extension
        token          secret every request must carry (x-tgdrive-token header or ?t=)
        media_token    secret that only allows playing streams (for other apps: VLC, MX Player …)
        demo           true: a made-up account instead of Telegram ("Try it with sample data")
    Returns JSON with the ports and what the runtime could set up."""
    opts = json.loads(options)
    with _lock:
        if _state["server"] is not None and not _state["server"].should_exit:
            return json.dumps(_state["info"])
        data_dir = Path(opts["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TGDRIVE_DATA"] = str(data_dir)
        os.environ["TGDRIVE_PACKAGED"] = "1"
        os.environ["TGDRIVE_TOKEN"] = opts["token"]
        os.environ["TGDRIVE_MEDIA_TOKEN"] = opts["media_token"]
        if opts.get("download_dir"):
            os.environ["TGDRIVE_DOWNLOADS"] = str(opts["download_dir"])
        if opts.get("model_dir"):
            os.environ["TGDRIVE_MODEL_DIR"] = str(opts["model_dir"])
        os.environ.setdefault("HOME", str(data_dir))
        info: dict[str, Any] = {"fts5": enable_fts5(opts.get("fts5_library") or "libtgfts5.so")}

        from . import config, diagnostics, fastcrypto, maintenance
        maintenance.setup_logging()
        diagnostics.install_hooks()
        info["crypto"] = fastcrypto.install()
        from . import semantic
        info["numpy"] = semantic.np is not None
        log.info("android service %s starting: %s", config.VERSION, info)

        import run
        from . import api
        demo = bool(opts.get("demo"))
        if demo:
            _prepare_demo(data_dir, opts.get("download_dir") or "")
        api.RUNTIME["platform"] = "android"
        server, thread, port, media = run.serve_in_thread(host="127.0.0.1", port=0, media_port=0,
                                                         token=opts["token"], desktop=False)
        deadline = time.monotonic() + 60
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            server.should_exit = True
            raise RuntimeError("the service didn't start (see the log)")
        info.update(port=port, media_port=media, version=config.VERSION, demo=demo,
                    data_dir=str(config.DATA_DIR), log=str(maintenance.log_path()))
        _state.update(server=server, thread=thread, info=info)
        return json.dumps(info)


def _prepare_demo(data_dir: Path, download_dir: str) -> None:
    import asyncio
    import shutil
    from tests import demo_server
    world = data_dir / "demo"
    shutil.rmtree(world, ignore_errors=True)
    world.mkdir(parents=True)
    loop = asyncio.new_event_loop()
    try:
        demo_server.prepare(world, download_dir=download_dir, loop=loop)
    finally:
        loop.close()


def stop(timeout: float = 20.0) -> bool:
    """Stop the service and wait (up to `timeout` s) for everything to be saved. True if it stopped."""
    with _lock:
        server: Optional[Any] = _state.get("server")
        thread: Optional[threading.Thread] = _state.get("thread")
        if server is None:
            return True
        from . import api
        api.RUNTIME["stopping"] = True
        server.should_exit = True
        if thread is not None:
            thread.join(timeout)
        stopped = thread is None or not thread.is_alive()
        _state.update(server=None, thread=None)
        api.RUNTIME["stopping"] = False
        log.info("android service stopped%s", "" if stopped else " (timed out)")
        for h in logging.getLogger().handlers:
            h.flush()
        return stopped


def running() -> bool:
    server = _state.get("server")
    return bool(server is not None and server.started and not server.should_exit)
