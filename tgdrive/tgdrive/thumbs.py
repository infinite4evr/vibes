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
        self.sem = asyncio.Semaphore(8)
        self.inflight: dict[str, asyncio.Future] = {}
        self.backoff_until = 0.0

    def _path(self, chat_id: int, msg_id: int, variant: str) -> Path:
        sub = self.dir / str(abs(chat_id) % 256)
        sub.mkdir(exist_ok=True)
        return sub / f"{chat_id}_{msg_id}_{variant}"

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
        try:
            result = await asyncio.wait_for(self._fetch(chat_id, msg_id, variant, path), TIMEOUT)
            fut.set_result(result)
            return result
        except errors.FloodWaitError as exc:
            self.backoff_until = time.time() + exc.seconds
            err = ThumbsBusy(exc.seconds)
            fut.set_exception(err)
            fut.exception()
            raise err
        except asyncio.TimeoutError:
            err = ThumbsBusy(10)
            fut.set_exception(err)
            fut.exception()
            raise err
        except Exception as exc:
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
