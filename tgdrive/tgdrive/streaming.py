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
import threading
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
    """Sparse cache file + bitmap per media.

    Safe to use from several threads at once: data is written with pwrite() into a file that is
    created without truncation, the bitmap is guarded by a lock, and the bitmap only reaches disk
    after the data it describes has been synced. A cache that was evicted is marked dead, so a late
    write can't bring back a file whose bitmap no longer matches it."""

    def __init__(self, directory: Path, key: str, chunks: int, size: int = 0):
        self.path = directory / f"{key}.bin"
        self.map_path = directory / f"{key}.map"
        self.chunks = chunks
        self.size = size or chunks * CHUNK
        self.lock = threading.Lock()
        self.dead = False
        n = (chunks + 7) // 8
        try:
            data = self.map_path.read_bytes()
            self.bits = bytearray(data) if len(data) == n else bytearray(n)
        except OSError:
            self.bits = bytearray(n)
        try:
            have = self.path.stat().st_size
        except OSError:
            have = -1
        if have < 0:
            self.bits = bytearray(n)
        else:
            # Never trust a bit for a chunk that lies (partly) beyond the end of the cache file.
            for i in range(chunks):
                if self.has(i) and have < i * CHUNK + self.expected(i):
                    self.bits[i >> 3] &= ~(1 << (i & 7)) & 0xFF
        self._dirty = 0

    def expected(self, i: int) -> int:
        """How many bytes chunk i must hold."""
        return max(0, min(CHUNK, self.size - i * CHUNK))

    def has(self, i: int) -> bool:
        return bool(self.bits[i >> 3] & (1 << (i & 7)))

    def complete(self) -> bool:
        full, rest = divmod(self.chunks, 8)
        if any(b != 0xFF for b in self.bits[:full]):
            return False
        return not rest or (self.bits[full] & ((1 << rest) - 1)) == (1 << rest) - 1

    def count(self) -> int:
        return sum(bin(b).count("1") for b in self.bits)

    def read(self, i: int) -> bytes:
        fd = os.open(self.path, os.O_RDONLY)
        try:
            data = os.pread(fd, CHUNK, i * CHUNK)
        finally:
            os.close(fd)
        if len(data) < self.expected(i):
            with self.lock:   # the file lost data (truncated or replaced): forget the chunk
                self.bits[i >> 3] &= ~(1 << (i & 7)) & 0xFF
            raise OSError(f"cache chunk {i} of {self.path.name} is short ({len(data)} bytes)")
        return data[:self.expected(i)]

    def write(self, i: int, data: bytes) -> None:
        if self.dead:
            return
        if len(data) != self.expected(i):
            raise ValueError(f"chunk {i} has {len(data)} bytes, expected {self.expected(i)}")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.pwrite(fd, data, i * CHUNK)
            with self.lock:
                if self.dead:
                    return
                self.bits[i >> 3] |= 1 << (i & 7)
                self._dirty += 1
                if self._dirty >= 8 or self.complete():
                    os.fdatasync(fd) if hasattr(os, "fdatasync") else os.fsync(fd)
                    self._flush_locked()
        finally:
            os.close(fd)

    def flush(self) -> None:
        with self.lock:
            if self._dirty and not self.dead:
                try:
                    fd = os.open(self.path, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError:
                    return
                self._flush_locked()

    def _flush_locked(self) -> None:
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
        self.sem = asyncio.Semaphore(8)        # playback, previews, thumbnails of documents
        self.bulk_sem = asyncio.Semaphore(6)   # downloads: separate, so they never starve playback
        self.last_evict = 0.0
        self.low_space = False   # the disk is nearly full: stream without caching
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
        if c is None or c.chunks != src.chunks or c.dead:
            c = self.caches[src.key] = ChunkCache(self.dir, src.key, src.chunks, src.size)
        return c

    # ----------------------------------------------------------------- chunks
    async def chunk(self, src: Source, i: int, cache: bool = True) -> bytes:
        """Bytes of chunk i (from the local copy, the cache, or Telegram)."""
        if src.local:
            return await asyncio.get_running_loop().run_in_executor(None, _read_local, src.local, i)
        cc = self.cache_for(src) if cache else None
        if cc and cc.has(i):
            log.debug("stream %s chunk %d: cache hit", src.key, i)
            self.stats["hits"] += 1
            try:
                return await asyncio.get_running_loop().run_in_executor(None, cc.read, i)
            except OSError as exc:
                log.debug("stream %s chunk %d: cache read failed (%s), fetching again", src.key, i, exc)
        key = (src.key, i)
        fut = self.inflight.get(key)
        if fut is None:
            fut = asyncio.ensure_future(self._fetch(src, i, cc))
            self.inflight[key] = fut
            fut.add_done_callback(lambda _f, k=key: self.inflight.pop(k, None))
        return await asyncio.shield(fut)

    async def _fetch(self, src: Source, i: int, cc: Optional[ChunkCache], bulk: bool = False) -> bytes:
        """Fetch chunk i from Telegram. Returns exactly the bytes the chunk must hold, or raises.

        bulk=True (downloads) uses its own slots, so a big download never takes the slots that
        playback and previews need."""
        self.acc.require_online()
        expected = max(0, min(CHUNK, src.size - i * CHUNK))
        async with (self.bulk_sem if bulk else self.sem):
            t0 = time.perf_counter()
            problem = "no answer"
            for attempt in range(5):
                try:
                    data = b""
                    async for part in self.acc.client.iter_download(
                            src.location, offset=i * CHUNK, request_size=CHUNK, limit=1,
                            file_size=src.size, dc_id=src.dc_id):
                        data = bytes(part)
                        break
                    if len(data) > expected:
                        data = data[:expected]
                    if len(data) < expected:
                        # Never hand out (or cache) a short chunk: it would corrupt playback and downloads.
                        problem = f"short answer ({len(data)} of {expected} bytes)"
                        log.debug("stream %s chunk %d: %s, attempt %d", src.key, i, problem, attempt + 1)
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    self.stats["fetched"] += 1
                    self.stats["bytes_fetched"] += len(data)
                    log.debug("stream %s chunk %d: %d bytes from Telegram (dc %s) in %.0f ms, attempt %d", src.key, i,
                              len(data), src.dc_id, (time.perf_counter() - t0) * 1000, attempt + 1)
                    if cc is not None and not cc.dead and not self.low_space:
                        try:
                            await asyncio.get_running_loop().run_in_executor(None, cc.write, i, data)
                        except (OSError, ValueError) as exc:
                            log.warning("stream cache write failed: %s", exc)
                        self._maybe_evict()
                    return data
                except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
                    problem = "file reference expired"
                    log.debug("stream %s chunk %d: file reference expired, refreshing", src.key, i)
                    async with src.lock:
                        fresh = await self.source(src.chat_id, src.msg_id, fresh=True)
                        src.location, src.dc_id = fresh.location, fresh.dc_id
                except errors.FloodWaitError as exc:
                    log.info("stream %s chunk %d: flood wait %d s", src.key, i, exc.seconds)
                    if exc.seconds > 30:
                        raise StreamError(f"Telegram asks to wait {exc.seconds}s before reading more of this file.")
                    problem = f"flood wait {exc.seconds}s"
                    await asyncio.sleep(exc.seconds + 1)
                except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                    problem = repr(exc)
                    log.debug("stream %s chunk %d: attempt %d failed: %r", src.key, i, attempt + 1, exc)
                    await asyncio.sleep(1 + attempt)
        log.warning("stream %s chunk %d: gave up after 5 attempts (%s)", src.key, i, problem)
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
        """At most every 30 s, in a worker thread: keep the cache under its size limit, and stop caching
        (and shrink the cache) when the disk is nearly full."""
        if time.time() - self.last_evict < 30:
            return
        self.last_evict = time.time()
        busy = {k for k, _ in self.inflight}
        try:
            asyncio.get_running_loop().run_in_executor(None, self._evict, busy)
        except RuntimeError:
            self._evict(busy)

    def _evict(self, busy: set) -> None:
        from .settings import settings
        from .transfers import RESERVE_BYTES, free_bytes
        limit = int(settings.get("stream_cache_mb") or 0) * 1024 * 1024
        try:
            files = [(p, p.stat()) for p in self.dir.glob("*.bin")]
        except OSError:
            return
        total = sum(st.st_blocks * 512 for _, st in files)
        low = free_bytes(self.dir) < 2 * RESERVE_BYTES
        if low != self.low_space:
            log.warning("stream cache: disk nearly full, %s", "caching paused" if low else "caching again")
        self.low_space = low
        if low:
            limit = min(limit, total // 2)
        if total <= limit:
            return
        for p, st in sorted(files, key=lambda x: x[1].st_mtime):
            if total <= limit * 0.8:
                break
            if p.stem in busy:
                continue
            total -= st.st_blocks * 512
            c = self.caches.pop(p.stem, None)
            if c is not None:
                c.dead = True
            for q in (p, p.with_suffix(".map")):
                try:
                    q.unlink()
                except OSError:
                    pass

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
            c = self.caches.pop(p.stem, None)
            if c is not None:
                c.dead = True
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n

    def cached_copy(self, src: Source) -> Optional[Path]:
        """The cache file, if every chunk is present (used to finish a download instantly)."""
        cc = self.cache_for(src)
        if cc.complete():
            cc.flush()
            return cc.path
        return None


def _read_local(path: Path, i: int) -> bytes:
    with open(path, "rb") as fh:
        fh.seek(i * CHUNK)
        return fh.read(CHUNK)


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
