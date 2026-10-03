"""Thumbnails and image previews, cached on disk.

Requests for the same thumbnail are de-duplicated, a semaphore keeps Telegram
traffic polite, and no request can hang: each has a time limit, and when
Telegram asks us to slow down, thumbnails pause for that long and answer
"try later" immediately instead of holding a connection. The UI already shows
Telegram's inline preview (stored in the index) while the real one loads.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from telethon import errors
from telethon.tl import types

from .extract import pick_thumb, thumb_sizes

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.thumbs")

SIZES = {"s": 320, "b": 1280}
PREVIEW_LIMIT = 40 * 1024 * 1024
TIMEOUT = 25


class ThumbsBusy(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"Telegram asked to slow down; try again in {retry_after}s.")
        self.retry_after = retry_after


class Thumbs:
    def __init__(self, account: "Account"):
        self.acc = account
        self.dir = account.dir / "thumbs"
        self.dir.mkdir(exist_ok=True)
        self._cache_bytes: Optional[int] = None   # estimate between full scans (see trim)
        self._scanned = 0.0
        self.sem = asyncio.Semaphore(8)
        self.inflight: dict[str, asyncio.Future] = {}
        self.backoff_until = 0.0

    def _path(self, chat_id: int, msg_id: int, variant: str) -> Path:
        sub = self.dir / str(abs(chat_id) % 256)
        # parents: the whole cache may have been deleted while TG Drive runs (a cleaner app on phones);
        # thumbnails are fetched again instead of every one failing until the next start.
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{chat_id}_{msg_id}_{variant}"

    # ---- first pages of PDFs, rendered by the window (pdf.js) and kept here, so the grid shows them
    DOC_MAX = 400 * 1024
    DOC_MAGIC = (b"RIFF", b"\xff\xd8\xff", b"\x89PNG")

    def doc_state(self, chat_id: int, msg_id: int) -> tuple[Optional[Path], bool]:
        """(picture, failed before)."""
        p = self._path(chat_id, msg_id, "pdf")
        if p.exists():
            return p, False
        return None, Path(str(p) + ".none").exists()

    def save_doc(self, chat_id: int, msg_id: int, data: bytes) -> None:
        if not data or len(data) > self.DOC_MAX or not data.startswith(self.DOC_MAGIC):
            raise ValueError("That isn't a small WebP, JPEG or PNG picture.")
        p = self._path(chat_id, msg_id, "pdf")
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
        Path(str(p) + ".none").unlink(missing_ok=True)
        self.trim(p)

    def doc_failed(self, chat_id: int, msg_id: int) -> None:
        Path(str(self._path(chat_id, msg_id, "pdf")) + ".none").touch()

    def cached(self, chat_id: int, msg_id: int, variant: str = "s") -> Optional[Path]:
        p = self._path(chat_id, msg_id, variant)
        return p if p.exists() else None

    async def get(self, chat_id: int, msg_id: int, variant: str = "s") -> Optional[Path]:
        path = self._path(chat_id, msg_id, variant)
        if path.exists():
            return path
        if Path(str(path) + ".none").exists():
            return None
        wait = self.backoff_until - time.time()
        if wait > 0:
            raise ThumbsBusy(int(wait) + 1)
        key = str(path)
        if key in self.inflight:
            return await asyncio.shield(self.inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self.inflight[key] = fut
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(self._fetch(chat_id, msg_id, variant, path), TIMEOUT)
            await asyncio.to_thread(self.trim, result)
            fut.set_result(result)
            log.debug("preview %s:%s/%s %s in %.0f ms", chat_id, msg_id, variant, "fetched" if result else "none",
                      (time.perf_counter() - t0) * 1000)
            return result
        except errors.FloodWaitError as exc:
            log.info("preview %s:%s/%s: flood wait %d s", chat_id, msg_id, variant, exc.seconds)
            self.backoff_until = time.time() + exc.seconds
            err = ThumbsBusy(exc.seconds)
            fut.set_exception(err)
            fut.exception()
            raise err
        except asyncio.TimeoutError:
            log.debug("preview %s:%s/%s timed out after %.0f s", chat_id, msg_id, variant, TIMEOUT)
            err = ThumbsBusy(10)
            fut.set_exception(err)
            fut.exception()
            raise err
        except Exception as exc:
            log.debug("preview %s:%s/%s failed: %r", chat_id, msg_id, variant, exc)
            fut.set_exception(exc)
            fut.exception()  # mark retrieved
            raise
        finally:
            self.inflight.pop(key, None)

    async def _fetch(self, chat_id: int, msg_id: int, variant: str, path: Path) -> Optional[Path]:
        async with self.sem:
            for attempt in range(2):
                msg = await self.acc.get_message(chat_id, msg_id, fresh=attempt > 0)
                try:
                    if variant == "full":
                        return await self._full(msg, path, chat_id, msg_id)
                    size = pick_thumb(thumb_sizes(msg.media), SIZES.get(variant, 320))
                    if size is None:
                        Path(str(path) + ".none").touch()
                        return None
                    tmp = Path(str(path) + ".tmp")
                    got = await self.acc.client.download_media(msg, file=str(tmp), thumb=size.type)
                    if not got:
                        Path(str(path) + ".none").touch()
                        return None
                    Path(got).replace(path)
                    return path
                except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
                    continue
        return None

    async def _full(self, msg, path: Path, chat_id: int, msg_id: int) -> Optional[Path]:
        media = msg.media
        if isinstance(media, types.MessageMediaPhoto):
            ok = True
        elif isinstance(media, types.MessageMediaDocument):
            doc = media.document
            ok = (doc.mime_type or "").startswith("image/") and doc.size <= PREVIEW_LIMIT
        else:
            ok = False
        if not ok:
            return None
        streamer = self.acc.streamer
        src = await streamer.source(chat_id, msg_id)
        chunks = []
        async for piece in streamer.iter_range(src, 0, max(0, src.size - 1), prefetch=6):
            chunks.append(piece)
        tmp = Path(str(path) + ".tmp")
        tmp.write_bytes(b"".join(chunks))
        tmp.replace(path)
        return path

    def trim(self, keep=None) -> None:
        """Keep the cache near its target size. The folder is scanned only when the running estimate
        says it may be over, or every few minutes: never once per thumbnail."""
        from .settings import settings
        limit = int(settings.get("thumb_cache_mb")) * 1024 * 1024
        now = time.monotonic()
        if self._cache_bytes is not None:
            try:
                self._cache_bytes += keep.stat().st_size if keep else 0
            except OSError:
                pass
            if self._cache_bytes <= limit and now - self._scanned < 300:
                return
        files = []
        for p in self.dir.rglob("*"):
            try:
                if p.is_file() and not p.name.endswith(".tmp"):
                    st = p.stat(); files.append((st.st_mtime, st.st_size, p))
            except OSError:
                continue
        total = sum(size for _, size, _ in files)
        for _, size, p in sorted(files):
            if total <= limit: break
            if p == keep: continue  # current response must remain readable
            try: p.unlink(missing_ok=True); total -= size
            except OSError: pass
        self._cache_bytes, self._scanned = total, now

    def usage(self) -> dict:
        n = size = 0
        for p in self.dir.rglob("*"):
            if p.is_file():
                n += 1
                size += p.stat().st_size
        return {"files": n, "bytes": size}

    def clear(self) -> int:
        n = 0
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
                n += 1
        self.backoff_until = 0
        return n
