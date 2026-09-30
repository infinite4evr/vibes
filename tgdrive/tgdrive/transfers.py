"""Download and upload queue with pause / resume.

Downloads fetch 512 KB chunks in parallel (reusing anything already streamed),
write them into `<name>.part` and remember finished chunks in `<name>.part.map`,
so pausing, quitting or losing the connection never loses progress. Finished
files land in the download folder (Settings → Downloads), keeping the TG Drive
folder structure when a whole folder is downloaded; a batch can also be packed
into a .zip.

Uploads send parts ourselves (saveFilePart / saveBigFilePart, several at once)
and remember how many are done, so a paused upload continues with the same file
id. Uploads read straight from a path on disk (desktop app, folders included)
or from a temporary copy (browser uploads). Everything survives a restart.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from telethon import errors, helpers, utils
from telethon.tl import functions, types

from . import config
from .tasks import spawn
from .settings import settings
from .streaming import CHUNK

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.transfers")

BIG_FILE = 10 * 1024 * 1024      # above this, uploads must use saveBigFilePart
MAX_PARTS = {False: 4000, True: 8000}  # ≈2 GB normal, ≈4 GB Premium
ACTIVE = ("queued", "running")


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "file").strip(" .") or "file"
    if len(name) > 180:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:170] + dot + ext) if dot and len(ext) <= 10 else name[:180]
    return name


RESERVE_BYTES = 256 * 1024 * 1024   # always leave this much free on a disk we write to


def free_bytes(path: Path) -> int:
    """Free space on the disk that holds `path` (or its nearest existing parent)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 1 << 62   # unknown: don't block


def ensure_space(path: Path, need: int, what: str = "this") -> None:
    """Refuse to start writing `need` bytes when that would fill the disk."""
    free = free_bytes(path)
    if need + RESERVE_BYTES > free:
        raise TransferError(f"Not enough free space for {what}: it needs {_fmt(need)} and only "
                            f"{_fmt(max(0, free - RESERVE_BYTES))} is available on that disk. Free some space, "
                            f"then press resume.")


def _fmt(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


OFFLINE_ERROR = "Waiting for the connection to Telegram. It continues by itself."



_map_locks: dict[str, threading.Lock] = {}
_map_locks_guard = threading.Lock()


def _map_lock(mpath: Path) -> threading.Lock:
    """One lock per download map file (see Transfers._download)."""
    with _map_locks_guard:
        return _map_locks.setdefault(str(mpath), threading.Lock())

class TransferError(Exception):
    pass


class Transfers:
    def __init__(self, account: "Account"):
        self.acc = account
        self.up_dir = account.dir / "upload-tmp"
        self.up_dir.mkdir(exist_ok=True)
        self._limit = int(settings.get("parallel_transfers") or 3)
        self.sem = asyncio.Semaphore(self._limit)
        self.tasks: dict[int, asyncio.Task] = {}
        self.live: dict[int, dict] = {}  # id -> {"done": int, "speed": float}
        self.batches: dict[str, dict] = {}
        settings.on_change(self._on_settings)

    @property
    def db(self):
        return self.acc.db

    @property
    def client(self):
        return self.acc.client

    def _on_settings(self, changed: set[str]) -> None:
        if "parallel_transfers" in changed:
            new = int(settings.get("parallel_transfers") or 3)
            diff = new - self._limit
            self._limit = new
            for _ in range(max(0, diff)):
                self.sem.release()
            if diff < 0:
                async def shrink(n=-diff):
                    for _ in range(n):
                        await self.sem.acquire()
                try:
                    spawn(shrink(), "shrink transfer slots")
                except RuntimeError:
                    pass

    @property
    def down_dir(self) -> Path:
        d = Path(settings.get("download_dir") or config.default_download_dir()).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ api
    def restore(self) -> None:
        """After a restart, continue whatever was queued or running."""
        for t in self.db.q("SELECT id FROM transfers WHERE status IN ('queued','running') OR "
                           "(status='error' AND error=?)", (OFFLINE_ERROR,)):
            self.db.update_transfer(t["id"], status="queued")
            self._spawn(t["id"])

    async def stop(self) -> None:
        for tid, task in list(self.tasks.items()):
            task.cancel()
        for task in list(self.tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Leave them 'queued' so restore() picks them up next time.
        self.db.x("UPDATE transfers SET status='queued' WHERE status='running'")

    def list(self) -> list[dict]:
        rows = self.db.list_transfers()
        for r in rows:
            live = self.live.get(r["id"])
            if live and r["status"] == "running":
                r["done"] = live["done"]
                r["speed"] = round(live["speed"])
            r["upload_file_id"] = None
            if r["direction"] == "up":
                r["path"] = r.get("source_path")
        return rows

    def summary(self) -> dict:
        row = self.db.one("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS size, COALESCE(SUM(done),0) AS done "
                          "FROM transfers WHERE status IN ('queued','running','paused')")
        speed = sum(v.get("speed", 0) for v in self.live.values())
        return {"active": row["n"], "size": row["size"], "done": row["done"], "speed": round(speed)}

    def _unique_path(self, directory: Path, name: str) -> Path:
        base = safe_filename(name)
        stem, dot, ext = base.rpartition(".")
        if not dot:
            stem, ext = base, ""
        taken = {r["path"] for r in self.db.q(
            "SELECT path FROM transfers WHERE direction='down' AND status NOT IN ('cancelled')")}
        n = 0
        while True:
            candidate = directory / (base if n == 0 else f"{stem} ({n}){'.' + ext if ext else ''}")
            if not candidate.exists() and str(candidate) not in taken and \
                    not Path(str(candidate) + ".part").exists():
                return candidate
            n += 1

    def add_download(self, chat_id: int, msg_id: int, subdir: Optional[str] = None,
                     batch: Optional[str] = None, dest_dir: Optional[str] = None,
                     exact_path: Optional[str] = None) -> int:
        f = self.db.get_file(chat_id, msg_id)
        if not f:
            raise TransferError("That file isn't in the index.")
        existing = self.db.one(
            "SELECT id FROM transfers WHERE direction='down' AND chat_id=? AND msg_id=? "
            "AND status IN ('queued','running','paused')", (chat_id, msg_id))
        if existing:
            return existing["id"]
        name = f["alias"] or f["name"]
        if exact_path:  # folder sync: this exact file (an existing one is replaced when the download finishes)
            target = Path(exact_path)
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            directory = Path(dest_dir).expanduser() if dest_dir else self.down_dir
            if subdir:
                parts = [safe_filename(p) for p in subdir.split("/") if p.strip()]
                directory = directory.joinpath(*parts)
            directory.mkdir(parents=True, exist_ok=True)
            target = self._unique_path(directory, name)
        tid = self.db.add_transfer(direction="down", chat_id=chat_id, msg_id=msg_id, name=name,
                                   size=f["size"], path=str(target), status="queued", batch=batch)
        self.db.touch_recent(chat_id, msg_id, "download")
        self._spawn(tid)
        return tid

    def add_folder_download(self, folder_id: Optional[str], items: list[tuple[int, int]],
                            as_zip: bool = False, name: str = "Files") -> dict:
        """Download files keeping the folder tree below `folder_id` (or a flat selection)."""
        batch = f"{'zip' if as_zip else 'dir'}:{secrets.token_hex(4)}:{safe_filename(name)}"
        root = self.down_dir / safe_filename(name) if as_zip else self.down_dir
        ids = []
        drive = self.acc.drive
        base = drive.path(folder_id) if folder_id else []
        for cid, mid in items:
            sub = None
            if settings.get("keep_structure", True):
                row = self.db.get_placement(cid, mid)
                full = drive.path(row.get("folder_id")) if row.get("folder_id") else []
                rel = [p["name"] for p in full[len(base):]] if full[:len(base)] == base else []
                top = [safe_filename(name)] if (folder_id and not as_zip) else []
                sub = "/".join(top + rel) or None
            ids.append(self.add_download(cid, mid, subdir=sub, batch=batch,
                                         dest_dir=str(root) if as_zip else None))
        self.batches[batch] = {"ids": ids, "zip": as_zip, "root": str(root), "name": name}
        return {"batch": batch, "ids": ids}

    def new_upload_path(self) -> Path:
        return self.up_dir / f"{int(time.time() * 1000)}-{os.getpid()}-{secrets.token_hex(3)}.bin"

    def _check_size(self, size: int) -> None:
        if size == 0:
            raise TransferError("That file is empty.")
        limit = MAX_PARTS[self.acc.premium] * CHUNK
        if size > limit:
            raise TransferError(f"Telegram's limit for this account is {limit // 1024**2:,} MB per file.")

    def add_upload(self, tmp_path: Path, name: str, folder_id: Optional[str], caption: str = "",
                   target_chat: Optional[int] = None) -> int:
        size = tmp_path.stat().st_size
        try:
            self._check_size(size)
        except TransferError:
            tmp_path.unlink(missing_ok=True)
            raise
        tid = self.db.add_transfer(direction="up", name=safe_filename(name), size=size, path=str(tmp_path),
                                   folder_id=folder_id, status="queued", caption=caption or None,
                                   target_chat=target_chat, upload_file_id=helpers.generate_random_long())
        self._spawn(tid)
        return tid

    async def add_upload_paths(self, paths: list[str], folder_id: Optional[str], caption: str = "",
                               target_chat: Optional[int] = None) -> dict:
        """Upload files or whole folders straight from disk (no temporary copy)."""
        ids, skipped = [], []
        for raw in paths:
            p = Path(raw).expanduser()
            if p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                    rel = Path(root).relative_to(p.parent).parts
                    fid = await self.acc.drive.ensure_path(folder_id, list(rel)) \
                        if settings.get("keep_structure", True) else folder_id
                    for name in sorted(files):
                        if name.startswith("."):
                            continue
                        fp = Path(root) / name
                        try:
                            ids.append(self._add_path(fp, fid, caption, target_chat))
                        except (TransferError, OSError) as exc:
                            skipped.append(f"{fp.name}: {exc}")
            elif p.is_file():
                try:
                    ids.append(self._add_path(p, folder_id, caption, target_chat))
                except (TransferError, OSError) as exc:
                    skipped.append(f"{p.name}: {exc}")
            else:
                skipped.append(f"{p}: not found")
        return {"ids": ids, "skipped": skipped}

    def _add_path(self, p: Path, folder_id: Optional[str], caption: str, target_chat: Optional[int],
                  batch: Optional[str] = None) -> int:
        size = p.stat().st_size
        self._check_size(size)
        tid = self.db.add_transfer(direction="up", name=safe_filename(p.name), size=size, path=None,
                                   source_path=str(p), folder_id=folder_id, status="queued",
                                   caption=caption or None, target_chat=target_chat,
                                   upload_file_id=helpers.generate_random_long(), batch=batch)
        self._spawn(tid)
        return tid

    def pause(self, tid: int) -> None:
        t = self._get(tid)
        if t["status"] in ACTIVE:
            done = self._done(tid, t)
            self._cancel_task(tid)
            self.db.update_transfer(tid, status="paused", done=done)

    def resume(self, tid: int) -> None:
        t = self._get(tid)
        if t["status"] in ("paused", "error"):
            self.db.update_transfer(tid, status="queued", error=None)
            self._spawn(tid)

    def cancel(self, tid: int) -> None:
        t = self._get(tid)
        self._cancel_task(tid)
        if t["status"] == "done":
            return
        self.db.update_transfer(tid, status="cancelled")
        self._cleanup_partial(t)

    def remove(self, tid: int, delete_file: bool = False) -> None:
        t = self._get(tid)
        self._cancel_task(tid)
        self._cleanup_partial(t)
        if delete_file and t["direction"] == "down" and t["status"] == "done" and t["path"]:
            Path(t["path"]).unlink(missing_ok=True)
        self.db.x("DELETE FROM transfers WHERE id=?", (tid,))

    def bulk(self, action: str) -> int:
        if action == "pause":
            rows = self.db.q("SELECT id FROM transfers WHERE status IN ('queued','running')")
            for r in rows:
                self.pause(r["id"])
        elif action == "resume":
            rows = self.db.q("SELECT id FROM transfers WHERE status='paused'")
            for r in rows:
                self.resume(r["id"])
        elif action == "retry":
            rows = self.db.q("SELECT id FROM transfers WHERE status='error'")
            for r in rows:
                self.resume(r["id"])
        elif action == "cancel":
            rows = self.db.q("SELECT id FROM transfers WHERE status IN ('queued','running','paused','error')")
            for r in rows:
                self.cancel(r["id"])
        elif action == "clear":
            return self.db.x("DELETE FROM transfers WHERE status IN ('done','cancelled')").rowcount
        else:
            raise TransferError("Unknown action.")
        return len(rows)

    def file_path(self, tid: int) -> Path:
        t = self._get(tid)
        if t["direction"] != "down" or t["status"] != "done" or not Path(t["path"]).exists():
            raise TransferError("This download isn't finished.")
        return Path(t["path"])

    # ------------------------------------------------------------- internals
    def _get(self, tid: int) -> dict:
        t = self.db.get_transfer(tid)
        if not t:
            raise TransferError("Unknown transfer.")
        return t

    def _done(self, tid: int, t: dict) -> int:
        live = self.live.get(tid)
        return live["done"] if live else t["done"]

    def _cancel_task(self, tid: int) -> None:
        task = self.tasks.pop(tid, None)
        if task:
            task.cancel()

    def _cleanup_partial(self, t: dict) -> None:
        if t["direction"] == "down" and t["status"] != "done" and t["path"]:
            Path(t["path"] + ".part").unlink(missing_ok=True)
            Path(t["path"] + ".part.map").unlink(missing_ok=True)
        if t["direction"] == "up" and t["path"] and Path(t["path"]).parent == self.up_dir:
            Path(t["path"]).unlink(missing_ok=True)

    def _spawn(self, tid: int) -> None:
        if tid in self.tasks and not self.tasks[tid].done():
            return
        self.tasks[tid] = spawn(self._run(tid), f"transfer {tid}")

    async def _run(self, tid: int) -> None:
        t: Optional[dict] = None
        try:
            async with self.sem:
                t = self.db.get_transfer(tid)
                if not t or t["status"] != "queued":
                    return
                self.db.update_transfer(tid, status="running", error=None)
                started = time.time()
                log.debug("transfer %s start: %s %r (%d bytes, done %d) chat=%s msg=%s path=%s", tid, t["direction"],
                          t.get("name"), t.get("size") or 0, t.get("done") or 0, t.get("chat_id"), t.get("msg_id"),
                          t.get("path"))
                self.live[tid] = {"done": t["done"], "speed": 0.0, "mark": (time.time(), t["done"]),
                                  "task": asyncio.current_task()}
                if t["direction"] == "down":
                    await self._download(t)
                else:
                    await self._upload(t)
                self.db.update_transfer(tid, status="done", done=t["size"])
                secs = max(0.001, time.time() - started)
                log.debug("transfer %s done in %.1f s (%.0f KB/s)", tid, secs, (t.get("size") or 0) / 1024 / secs)
                self._finished(t)
        except asyncio.CancelledError:
            log.debug("transfer %s paused or cancelled", tid)
            live = self.live.get(tid)
            if live and live.get("task") is asyncio.current_task():
                self.db.update_transfer(tid, done=live["done"])
            raise
        except Exception as exc:
            log.warning("transfer %s failed: %s", tid, exc)
            log.debug("transfer %s traceback", tid, exc_info=exc)
            msg = str(exc) if isinstance(exc, (TransferError,)) or exc.__class__.__name__ in (
                "AccountError", "StreamError") else f"{exc.__class__.__name__}: {exc}"
            if self.acc.status != "online" or isinstance(exc, (ConnectionError, asyncio.TimeoutError)):
                msg = OFFLINE_ERROR   # resumed automatically when the connection is back
            live = self.live.get(tid)
            self.db.update_transfer(tid, status="error", error=msg[:300], **({"done": live["done"]} if live else {}))
            self.acc.notify("Transfer failed", f"{(t or {}).get('name', tid)}: {msg[:120]}")
        finally:
            me = asyncio.current_task()
            if self.tasks.get(tid) is me:
                self.tasks.pop(tid, None)
            if self.live.get(tid, {}).get("task") is me:
                self.live.pop(tid, None)

    def _finished(self, t: dict) -> None:
        batch = t.get("batch") or ""
        if batch.startswith("sync:"):  # folder sync reports its own progress
            sync = getattr(self.acc, "sync", None)
            if sync is not None:
                sync.poke()
            return
        if t["direction"] == "down":
            self.acc.notify("Download finished", t["name"], path=t["path"])
            if settings.get("open_after_download") and not batch:
                self.acc.open_path(t["path"])
            if batch:
                left = self.db.one("SELECT COUNT(*) AS n FROM transfers WHERE batch=? AND status NOT IN "
                                   "('done','cancelled')", (batch,))
                if left and left["n"] == 0:
                    spawn(self._batch_done(batch), f"finish batch {batch}")
        else:
            self.acc.notify("Upload finished", t["name"])

    async def _batch_done(self, batch: str) -> None:
        kind, _, rest = batch.partition(":")
        name = rest.partition(":")[2] or "Files"
        rows = self.db.q("SELECT path FROM transfers WHERE batch=? AND status='done'", (batch,))
        if kind != "zip" or not rows:
            self.acc.notify("Folder downloaded", name)
            return
        root = Path(self.batches.get(batch, {}).get("root") or Path(rows[0]["path"]).parent)
        zpath = self._unique_path(self.down_dir, f"{name}.zip")

        need = sum(Path(r["path"]).stat().st_size for r in rows if Path(r["path"]).exists())
        try:
            ensure_space(zpath, need, f"the zip “{zpath.name}”")
        except TransferError as exc:
            self.acc.notify("Zip not made", str(exc))
            return

        def pack() -> None:
            tmp = Path(str(zpath) + ".part")
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
                for r in rows:
                    p = Path(r["path"])
                    if p.exists():
                        try:
                            arc = p.relative_to(root)
                        except ValueError:
                            arc = Path(p.name)
                        z.write(p, str(arc))
            os.replace(tmp, zpath)
            for r in rows:
                Path(r["path"]).unlink(missing_ok=True)
            for d in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass
            try:
                root.rmdir()
            except OSError:
                pass

        await asyncio.get_running_loop().run_in_executor(None, pack)
        self.db.x("UPDATE transfers SET path=? WHERE batch=?", (str(zpath), batch))
        self.acc.notify("Zip ready", zpath.name, path=str(zpath))

    def _progress(self, tid: int, done: int) -> None:
        live = self.live.get(tid)
        if not live:
            return
        live["done"] = done
        now = time.time()
        t0, d0 = live["mark"]
        if now - t0 >= 1.0:
            live["speed"] = (done - d0) / (now - t0) * 0.7 + live.get("speed", 0) * 0.3
            live["mark"] = (now, done)
            self.db.update_transfer(tid, done=done)

    async def _download(self, t: dict) -> None:
        self.acc.require_online()
        tid, path = t["id"], Path(t["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        part = Path(str(path) + ".part")
        mpath = Path(str(path) + ".part.map")
        streamer = self.acc.streamer
        src = await streamer.source(t["chat_id"], t["msg_id"])
        if src.local and src.local != path:  # already on disk (earlier download): copy it
            await asyncio.get_running_loop().run_in_executor(None, _copy, src.local, path)
            return
        size = src.size
        if size and size != t["size"]:
            self.db.update_transfer(tid, size=size)
            t["size"] = size
        n = src.chunks
        cached = streamer.cached_copy(src)
        if cached:  # fully streamed before: just copy the cache file
            ensure_space(path, size, f"“{t['name']}”")
            await asyncio.get_running_loop().run_in_executor(None, _copy, cached, path, size)
            return
        bits = bytearray((n + 7) // 8)
        if part.exists() and mpath.exists():
            data = mpath.read_bytes()
            if len(data) == len(bits):
                bits = bytearray(data)
        elif part.exists():  # older contiguous .part (TG Drive 0.1): keep whole chunks
            have = part.stat().st_size // CHUNK
            for i in range(min(have, n)):
                bits[i >> 3] |= 1 << (i & 7)

        def has(i: int) -> bool:
            return bool(bits[i >> 3] & (1 << (i & 7)))

        def expected(i: int) -> int:
            return max(0, min(CHUNK, size - i * CHUNK))

        if part.exists():  # a bit is only trusted if the .part file really reaches that far
            have = part.stat().st_size
            for i in range(n):
                if has(i) and have < i * CHUNK + expected(i):
                    bits[i >> 3] &= ~(1 << (i & 7)) & 0xFF

        todo = [i for i in range(n) if not has(i)]
        done_bytes = sum(expected(i) for i in range(n) if has(i))
        ensure_space(part, sum(expected(i) for i in todo), f"“{t['name']}”")
        self._progress(tid, done_bytes)
        cc = streamer.cache_for(src)
        fd = os.open(part, os.O_RDWR | os.O_CREAT, 0o644)
        lock = asyncio.Lock()
        queue: asyncio.Queue[int] = asyncio.Queue()
        for i in todo:
            queue.put_nowait(i)
        dirty = 0
        loop = asyncio.get_running_loop()
        # A paused download's last saves can still be running in a worker thread when it is resumed:
        # every save of this file's map, and closing its .part, take the same lock.
        map_lock = _map_lock(mpath)
        closed = False

        def save_map() -> None:
            # Data first, then the map that describes it (atomically), so a crash never leaves
            # chunks marked done that are not on disk.
            with map_lock:
                if closed:
                    return
                os.fsync(fd)
                tmp = mpath.with_name(mpath.name + ".tmp")
                tmp.write_bytes(bytes(bits))
                os.replace(tmp, mpath)

        def close_part() -> None:
            nonlocal closed
            with map_lock:
                closed = True
                os.close(fd)

        async def worker() -> None:
            nonlocal done_bytes, dirty
            while True:
                try:
                    i = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                data = None
                if cc.has(i):
                    try:
                        data = await loop.run_in_executor(None, cc.read, i)
                    except OSError:
                        data = None
                if data is None:
                    data = await streamer._fetch(src, i, None, bulk=True)
                if len(data) != expected(i):
                    raise TransferError(f"Part {i + 1} of {n} came back with the wrong size. Press resume to retry.")
                await loop.run_in_executor(None, os.pwrite, fd, data, i * CHUNK)
                async with lock:
                    bits[i >> 3] |= 1 << (i & 7)
                    done_bytes += len(data)
                    dirty += 1
                    if dirty >= 8:
                        dirty = 0
                        await loop.run_in_executor(None, save_map)
                    self._progress(tid, done_bytes)

        try:
            workers = max(1, int(settings.get("download_workers") or 4))
            await asyncio.gather(*(worker() for _ in range(min(workers, max(1, len(todo))))))
        finally:
            try:
                await loop.run_in_executor(None, save_map)
            finally:
                close_part()
        if not all(has(i) for i in range(n)):
            raise TransferError("Some parts are missing. Press resume to fetch them.")
        os.truncate(part, size)
        if part.stat().st_size != size:
            raise TransferError("The downloaded file has the wrong size. Press resume to fetch it again.")
        os.replace(part, path)
        mpath.unlink(missing_ok=True)

    async def _find_sent(self, peer, name: str, size: int):
        """The message an earlier attempt already sent (same file name and size), among the latest ones."""
        async for m in self.client.iter_messages(peer, limit=50):
            f = getattr(m, "file", None)
            if f is not None and (f.name or "") == name and (f.size or 0) == size:
                return m
        return None

    async def _upload(self, t: dict) -> None:
        self.acc.require_online()
        tid = t["id"]
        src = Path(t.get("source_path") or t["path"])
        if not src.exists():
            raise TransferError("The file to upload is no longer there. Upload it again.")
        size = src.stat().st_size
        if t["size"] and size != t["size"]:
            raise TransferError("The file changed on disk since the upload started. Upload it again.")
        parts = math.ceil(size / CHUNK)
        big = size > BIG_FILE
        file_id = t["upload_file_id"]
        start = min(t["done"] // CHUNK, parts)

        async def send_part(i: int, data: bytes) -> None:
            for attempt in range(6):
                try:
                    if big:
                        ok = await self.client(functions.upload.SaveBigFilePartRequest(file_id, i, parts, data))
                    else:
                        ok = await self.client(functions.upload.SaveFilePartRequest(file_id, i, data))
                    if ok:
                        return
                except errors.FloodWaitError as exc:
                    await asyncio.sleep(exc.seconds + 1)
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    await asyncio.sleep(2 * (attempt + 1))
            raise TransferError(f"Telegram didn't accept part {i + 1} of {parts}.")

        # A pool of workers takes parts from a queue, so one slow part never holds the others up.
        # Progress (and resume) is the contiguous prefix of finished parts.
        workers = max(1, int(settings.get("upload_workers") or 4))
        loop = asyncio.get_running_loop()
        st0 = src.stat()
        queue: asyncio.Queue[int] = asyncio.Queue()
        for i in range(start, parts):
            queue.put_nowait(i)
        finished: set[int] = set()
        mark = [start]   # first part not yet known to be sent
        fd = os.open(src, os.O_RDONLY)

        async def worker() -> None:
            while True:
                try:
                    i = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                data = await loop.run_in_executor(None, os.pread, fd, CHUNK, i * CHUNK)
                await send_part(i, data)
                finished.add(i)
                while mark[0] in finished:
                    finished.discard(mark[0])
                    mark[0] += 1
                done = min(mark[0] * CHUNK, size)
                self._progress(tid, done)

        try:
            await asyncio.gather(*(worker() for _ in range(min(workers, max(1, parts - start)))))
        finally:
            os.close(fd)
            self.db.update_transfer(tid, done=min(mark[0] * CHUNK, size))
        st1 = src.stat()
        if (st1.st_size, st1.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns):
            # Parts from before and after the change would make a broken file on Telegram.
            self.db.update_transfer(tid, done=0, size=st1.st_size, upload_file_id=helpers.generate_random_long())
            raise TransferError("The file changed while it was uploading. Press resume to upload the new version.")

        name = t["name"]
        if big:
            input_file = types.InputFileBig(id=file_id, parts=parts, name=name)
        else:
            md5 = await loop.run_in_executor(None, _md5, src)
            input_file = types.InputFile(id=file_id, parts=parts, name=name, md5_checksum=md5)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        as_media = bool(settings.get("upload_as_media"))

        def build_media(photo: bool):
            if photo:
                return types.InputMediaUploadedPhoto(file=input_file)
            try:
                attrs, mime2 = utils.get_attributes(str(src), mime_type=mime, force_document=not as_media,
                                                    supports_streaming=as_media)
            except Exception:
                attrs, mime2 = [types.DocumentAttributeFilename(name)], mime
            attrs = [a for a in attrs if not isinstance(a, types.DocumentAttributeFilename)]
            attrs.append(types.DocumentAttributeFilename(name))
            return types.InputMediaUploadedDocument(
                file=input_file, mime_type=mime2 or mime, force_file=not as_media, attributes=attrs)

        as_photo = as_media and mime.startswith("image/") and mime != "image/gif" and size < 10 * 1024 * 1024

        drive = self.acc.drive
        target = t.get("target_chat")
        peer = await self.acc.peer(target) if target else await drive.ensure_channel()
        cid = target or drive.channel_id

        # The id of the message is stored before sending: if the answer is lost and the upload is retried,
        # Telegram recognises the same id and the file is not posted twice.
        send_id = t.get("send_id") or helpers.generate_random_long()
        if not t.get("send_id"):
            self.db.update_transfer(tid, send_id=send_id)
            t["send_id"] = send_id

        async def send(photo: bool):
            try:
                return await self.client(functions.messages.SendMediaRequest(
                    peer=peer, media=build_media(photo), message=t.get("caption") or "", random_id=send_id))
            except errors.RandomIdDuplicateError:
                found = await self._find_sent(peer, name, size)
                if found is None:
                    raise TransferError("Telegram says this file was already sent, but it can't be found. "
                                        "Check the chat before uploading it again.")
                return types.Updates(updates=[types.UpdateNewMessage(found, 0, 0)], users=[], chats=[], date=0, seq=0)

        try:
            try:
                res = await send(as_photo)
            except (errors.PhotoInvalidDimensionsError, errors.PhotoExtInvalidError, errors.PhotoSaveFileInvalidError,
                    errors.ImageProcessFailedError, errors.PhotoInvalidError):
                if not as_photo:
                    raise
                res = await send(False)  # Telegram won't take it as a photo (size/shape): keep it as a file
        except (errors.FilePartMissingError, errors.FilePartsInvalidError, errors.FilePartInvalidError):
            # Telegram forgot the parts (paused too long). Start over with a new file id.
            self.db.update_transfer(tid, done=0, upload_file_id=helpers.generate_random_long())
            raise TransferError("Telegram expired the partial upload. Press resume to upload it again.")

        new_msg = None
        for u in getattr(res, "updates", []) or []:
            if isinstance(u, (types.UpdateNewChannelMessage, types.UpdateNewMessage)) and \
                    isinstance(u.message, types.Message):
                new_msg = u.message
        if new_msg is not None:
            chat = self.db.get_chat(cid)
            rec = self.acc.indexer.record(new_msg, cid, chat["title"] if chat else config.DRIVE_CHANNEL_TITLE)
            if rec:
                self.db.upsert_files([rec])
                self.db.refresh_file_count(cid)
            # Into its folder; one that became a smart folder (or was removed) meanwhile leaves it in My Drive.
            if t["folder_id"] and drive.accepts_files(t["folder_id"]):
                await drive.place([(cid, new_msg.id)], t["folder_id"], undo=False)
            self.db.update_transfer(tid, chat_id=cid, msg_id=new_msg.id)
            self.db.touch_recent(cid, new_msg.id, "upload")
        if not t.get("source_path"):
            src.unlink(missing_ok=True)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _copy(src: Path, dst: Path, size: Optional[int] = None) -> None:
    import shutil
    tmp = Path(str(dst) + ".part")
    shutil.copyfile(src, tmp)
    if size is not None:
        with open(tmp, "r+b") as f:
            f.truncate(size)
    os.replace(tmp, dst)
