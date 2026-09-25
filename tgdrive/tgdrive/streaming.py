"""Streaming and chunked, parallel file access.

Any file can be read at any byte range without downloading it first: the range
is mapped to 512 KB chunks, missing chunks are fetched from Telegram (several
at once), kept in a sparse on-disk cache, and the next few chunks are fetched
ahead of playback so video and audio play smoothly and seeking is cheap. The
same chunk fetcher powers parallel downloads.

The cache is bounded (Settings → Streaming) and evicted least-recently-used.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

from telethon import errors
from telethon.tl import types

from .extract import input_location

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.streaming")

CHUNK = 512 * 1024


class StreamError(Exception):
    pass


@dataclass
class Source:
    chat_id: int
    msg_id: int
    key: str                  # cache file stem (media id)
    size: int
    mime: str
    name: str
    dc_id: int = 0
    location: object = None
    local: Optional[Path] = None       # a finished download on disk
    fetched_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def chunks(self) -> int:
        return max(1, (self.size + CHUNK - 1) // CHUNK)


class ChunkCache:
    """Sparse cache file + bitmap per media."""

    def __init__(self, directory: Path, key: str, chunks: int):
        self.path = directory / f"{key}.bin"
        self.map_path = directory / f"{key}.map"
        self.chunks = chunks
        try:
            data = self.map_path.read_bytes()
            self.bits = bytearray(data) if len(data) == (chunks + 7) // 8 else bytearray((chunks + 7) // 8)
        except FileNotFoundError:
            self.bits = bytearray((chunks + 7) // 8)
        if not self.path.exists():
            self.bits = bytearray((chunks + 7) // 8)
        self._dirty = 0

    def has(self, i: int) -> bool:
        return bool(self.bits[i >> 3] & (1 << (i & 7)))

    def complete(self) -> bool:
        return all(self.has(i) for i in range(self.chunks))

    def count(self) -> int:
        return sum(bin(b).count("1") for b in self.bits)

    def read(self, i: int) -> bytes:
        with open(self.path, "rb") as fh:
            fh.seek(i * CHUNK)
            return fh.read(CHUNK)

    def write(self, i: int, data: bytes) -> None:
        mode = "r+b" if self.path.exists() else "wb"
        with open(self.path, mode) as fh:
            fh.seek(i * CHUNK)
            fh.write(data)
        self.bits[i >> 3] |= 1 << (i & 7)
        self._dirty += 1
        if self._dirty >= 8 or self.complete():
            self.flush()

    def flush(self) -> None:
        if self._dirty:
            tmp = self.map_path.with_suffix(".tmp")
            tmp.write_bytes(bytes(self.bits))
            tmp.replace(self.map_path)
            self._dirty = 0


class Streamer:
    SOURCE_TTL = 900

    def __init__(self, account: "Account"):
        self.acc = account
        self.dir = account.dir / "stream-cache"
        self.dir.mkdir(exist_ok=True)
        self.sources: dict[tuple[int, int], Source] = {}
        self.caches: dict[str, ChunkCache] = {}
        self.inflight: dict[tuple[str, int], asyncio.Future] = {}
        self.sem = asyncio.Semaphore(8)
        self.last_evict = 0.0
        self.stats = {"hits": 0, "fetched": 0, "bytes_fetched": 0}

    # ---------------------------------------------------------------- sources
    async def source(self, chat_id: int, msg_id: int, fresh: bool = False) -> Source:
        k = (chat_id, msg_id)
        src = self.sources.get(k)
        if src and not fresh and time.time() - src.fetched_at < self.SOURCE_TTL:
            return src
        row = self.acc.db.get_file(chat_id, msg_id)
        if not row:
            raise StreamError("That file isn't in the index.")
        local = self._local_copy(chat_id, msg_id, row.get("size") or 0)
        name = row.get("alias") or row.get("name") or "file"
        mime = row.get("mime") or "application/octet-stream"
        if local and not fresh:
            src = Source(chat_id, msg_id, str(row.get("media_id") or f"{chat_id}_{msg_id}"), local.stat().st_size,
                         mime, name, local=local, fetched_at=time.time())
            self.sources[k] = src
            return src
        msg = await self.acc.get_message(chat_id, msg_id, fresh=fresh)
        try:
            dc_id, location, size = input_location(msg.media)
        except ValueError:
            raise StreamError("This message has no file to stream.")
        media = msg.media
        key = str(media.document.id if isinstance(media, types.MessageMediaDocument) else media.photo.id)
        src = Source(chat_id, msg_id, key, size or row.get("size") or 0, mime, name, dc_id=dc_id,
                     location=location, fetched_at=time.time())
        self.sources[k] = src
        if len(self.sources) > 500:
            for old in sorted(self.sources, key=lambda x: self.sources[x].fetched_at)[:100]:
                self.sources.pop(old, None)
        return src

    def _local_copy(self, chat_id: int, msg_id: int, size: int) -> Optional[Path]:
        row = self.acc.db.one("SELECT path FROM transfers WHERE direction='down' AND chat_id=? AND msg_id=? "
                              "AND status='done' ORDER BY id DESC LIMIT 1", (chat_id, msg_id))
        if row and row["path"]:
            p = Path(row["path"])
            if p.exists() and (not size or p.stat().st_size == size):
                return p
        return None

    def cache_for(self, src: Source) -> ChunkCache:
        c = self.caches.get(src.key)
        if c is None or c.chunks != src.chunks:
            c = self.caches[src.key] = ChunkCache(self.dir, src.key, src.chunks)
        return c

    # ----------------------------------------------------------------- chunks
    async def chunk(self, src: Source, i: int, cache: bool = True) -> bytes:
        """Bytes of chunk i (from the local copy, the cache, or Telegram)."""
        if src.local:
            with open(src.local, "rb") as fh:
                fh.seek(i * CHUNK)
                return fh.read(CHUNK)
        cc = self.cache_for(src) if cache else None
        if cc and cc.has(i):
            self.stats["hits"] += 1
            try:
                return cc.read(i)
            except OSError:
                pass
        key = (src.key, i)
        fut = self.inflight.get(key)
        if fut is None:
            fut = asyncio.ensure_future(self._fetch(src, i, cc))
            self.inflight[key] = fut
            fut.add_done_callback(lambda _f, k=key: self.inflight.pop(k, None))
        return await asyncio.shield(fut)

    async def _fetch(self, src: Source, i: int, cc: Optional[ChunkCache]) -> bytes:
        self.acc.require_online()
        async with self.sem:
            for attempt in range(4):
                try:
                    data = b""
                    async for part in self.acc.client.iter_download(
                            src.location, offset=i * CHUNK, request_size=CHUNK, limit=1,
                            file_size=src.size, dc_id=src.dc_id):
                        data = bytes(part)
                        break
                    expected = min(CHUNK, max(0, src.size - i * CHUNK))
                    if len(data) < expected and attempt < 3:
                        await asyncio.sleep(0.5)
                        continue
                    self.stats["fetched"] += 1
                    self.stats["bytes_fetched"] += len(data)
                    if cc is not None:
                        try:
                            await asyncio.get_running_loop().run_in_executor(None, cc.write, i, data)
                        except OSError as exc:
                            log.warning("stream cache write failed: %s", exc)
                        self._maybe_evict()
                    return data
                except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
                    async with src.lock:
                        fresh = await self.source(src.chat_id, src.msg_id, fresh=True)
                        src.location, src.dc_id = fresh.location, fresh.dc_id
                except errors.FloodWaitError as exc:
                    if exc.seconds > 30:
                        raise StreamError(f"Telegram asks to wait {exc.seconds}s before reading more of this file.")
                    await asyncio.sleep(exc.seconds + 1)
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    await asyncio.sleep(1 + attempt)
        raise StreamError("Telegram didn't return this part of the file. Try again.")

    def prefetch(self, src: Source, start: int, n: int) -> None:
        if src.local or n <= 0:
            return
        cc = self.cache_for(src)
        for i in range(start, min(src.chunks, start + n)):
            if not cc.has(i) and (src.key, i) not in self.inflight:
                fut = asyncio.ensure_future(self._fetch(src, i, cc))
                self.inflight[(src.key, i)] = fut
                fut.add_done_callback(lambda f, k=(src.key, i): (self.inflight.pop(k, None),
                                                                  f.cancelled() or f.exception()))

    async def iter_range(self, src: Source, start: int, end: int, prefetch: int = 4) -> AsyncIterator[bytes]:
        """Yield bytes [start, end] (inclusive)."""
        i = start // CHUNK
        last = end // CHUNK
        while i <= last:
            self.prefetch(src, i + 1, prefetch)
            data = await self.chunk(src, i)
            lo = start - i * CHUNK if i == start // CHUNK else 0
            hi = end - i * CHUNK + 1 if i == last else len(data)
            piece = data[lo:hi]
            if piece:
                yield piece
            i += 1

    # --------------------------------------------------------------- eviction
    def _maybe_evict(self) -> None:
        if time.time() - self.last_evict < 30:
            return
        self.last_evict = time.time()
        from .settings import settings
        limit = int(settings.get("stream_cache_mb") or 0) * 1024 * 1024
        try:
            files = [(p, p.stat()) for p in self.dir.glob("*.bin")]
        except OSError:
            return
        total = sum(st.st_blocks * 512 for _, st in files)
        if total <= limit:
            return
        busy = {k for k, _ in self.inflight}
        for p, st in sorted(files, key=lambda x: x[1].st_mtime):
            if total <= limit * 0.8:
                break
            if p.stem in busy:
                continue
            total -= st.st_blocks * 512
            for q in (p, p.with_suffix(".map")):
                try:
                    q.unlink()
                except OSError:
                    pass
            self.caches.pop(p.stem, None)

    def cache_usage(self) -> dict:
        size, n = 0, 0
        for p in self.dir.glob("*.bin"):
            try:
                size += p.stat().st_blocks * 512
                n += 1
            except OSError:
                pass
        return {"bytes": size, "files": n, **self.stats}

    def clear_cache(self) -> int:
        n = 0
        busy = {k for k, _ in self.inflight}
        for p in list(self.dir.glob("*.bin")) + list(self.dir.glob("*.map")):
            if p.stem in busy:
                continue
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        self.caches.clear()
        return n

    def cached_copy(self, src: Source) -> Optional[Path]:
        """The cache file, if every chunk is present (used to finish a download instantly)."""
        cc = self.cache_for(src)
        if cc.complete():
            cc.flush()
            return cc.path
        return None


def parse_range(header: Optional[str], size: int) -> Optional[tuple[int, int]]:
    """Parse a single 'bytes=a-b' range. Returns (start, end) inclusive, or None for the whole file."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[6:].split(",")[0].strip()
    a, _, b = spec.partition("-")
    try:
        if a == "":
            n = int(b)
            if n <= 0:
                raise ValueError
            return max(0, size - n), size - 1
        start = int(a)
        end = int(b) if b else size - 1
    except ValueError:
        raise StreamError("Bad range")
    if start >= size or start > end:
        raise StreamError("Range not satisfiable")
    return start, min(end, size - 1)


def fadvise_sparse_size(path: Path) -> int:
    try:
        return os.stat(path).st_blocks * 512
    except OSError:
        return 0
