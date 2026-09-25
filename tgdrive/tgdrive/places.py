"""Where photos were taken: GPS coordinates from EXIF, for the Map view.

Telegram strips EXIF from photos sent as *photos*, but images sent as files (JPEG,
HEIC, TIFF, DNG, …) keep it. When you switch on “Find photo locations”, TG Drive
reads the first 128 KB of each such file (where EXIF lives), stores latitude,
longitude and the time the photo was taken, and never downloads the rest.
It runs slowly in the background and stops for Telegram's rate limits.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from telethon import errors

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.places")

HEAD = 128 * 1024
IMAGE_EXTS = ("jpg", "jpeg", "jpe", "heic", "heif", "tif", "tiff", "dng", "nef", "cr2", "arw", "orf", "rw2", "webp",
              "png")


# ----------------------------------------------------------------------- EXIF
def _tiff_values(buf: bytes, base: int, endian: str, typ: int, count: int, value_off: int):
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    size = sizes.get(typ, 1) * count
    off = value_off if size > 4 else None
    raw = buf[base + off: base + off + size] if off is not None else None
    return size, raw


def parse_exif_tiff(buf: bytes, base: int) -> dict:
    """Parse a TIFF structure starting at buf[base] (EXIF payload). Returns lat, lon, taken."""
    if buf[base:base + 2] == b"II":
        e = "<"
    elif buf[base:base + 2] == b"MM":
        e = ">"
    else:
        return {}
    if struct.unpack(e + "H", buf[base + 2:base + 4])[0] != 42:
        return {}

    def ifd(offset: int) -> dict[int, tuple[int, int, bytes]]:
        out = {}
        p = base + offset
        if p + 2 > len(buf):
            return out
        n = struct.unpack(e + "H", buf[p:p + 2])[0]
        if n > 500:
            return out
        for i in range(n):
            q = p + 2 + i * 12
            if q + 12 > len(buf):
                break
            tag, typ, count = struct.unpack(e + "HHI", buf[q:q + 8])
            out[tag] = (typ, count, buf[q + 8:q + 12])
        return out

    def rationals(entry, k: int) -> Optional[list[float]]:
        typ, count, raw4 = entry
        if typ not in (5, 10) or count < k:
            return None
        off = struct.unpack(e + "I", raw4)[0]
        vals = []
        for i in range(k):
            q = base + off + i * 8
            if q + 8 > len(buf):
                return None
            num, den = struct.unpack(e + ("ii" if typ == 10 else "II"), buf[q:q + 8])
            vals.append(num / den if den else 0.0)
        return vals

    def ascii_val(entry) -> str:
        typ, count, raw4 = entry
        if typ != 2:
            return ""
        if count <= 4:
            raw = raw4[:count]
        else:
            off = struct.unpack(e + "I", raw4)[0]
            raw = buf[base + off: base + off + count]
        return raw.split(b"\0")[0].decode("ascii", "ignore")

    try:
        first = struct.unpack(e + "I", buf[base + 4:base + 8])[0]
        ifd0 = ifd(first)
        out: dict = {}
        if 0x8769 in ifd0:
            exif = ifd(struct.unpack(e + "I", ifd0[0x8769][2])[0])
            for tag in (0x9003, 0x9004):
                if tag in exif:
                    s = ascii_val(exif[tag])
                    try:
                        out["taken"] = int(datetime.strptime(s, "%Y:%m:%d %H:%M:%S").timestamp())
                        break
                    except ValueError:
                        pass
        if "taken" not in out and 0x0132 in ifd0:
            try:
                out["taken"] = int(datetime.strptime(ascii_val(ifd0[0x0132]), "%Y:%m:%d %H:%M:%S").timestamp())
            except ValueError:
                pass
        if 0x8825 in ifd0:
            gps = ifd(struct.unpack(e + "I", ifd0[0x8825][2])[0])
            if 2 in gps and 4 in gps:
                la, lo = rationals(gps[2], 3), rationals(gps[4], 3)
                if la and lo:
                    lat = la[0] + la[1] / 60 + la[2] / 3600
                    lon = lo[0] + lo[1] / 60 + lo[2] / 3600
                    if 1 in gps and gps[1][2][:1] == b"S":
                        lat = -lat
                    if 3 in gps and gps[3][2][:1] == b"W":
                        lon = -lon
                    if -90 <= lat <= 90 and -180 <= lon <= 180 and (abs(lat) > 1e-6 or abs(lon) > 1e-6):
                        out["lat"], out["lon"] = round(lat, 6), round(lon, 6)
        return out
    except (struct.error, IndexError, ZeroDivisionError):
        return {}


def parse_exif(data: bytes) -> dict:
    """Find EXIF in the start of a JPEG/HEIC/TIFF/PNG/WebP file and parse it."""
    if data[:4] in (b"II*\0", b"MM\0*"):
        return parse_exif_tiff(data, 0)
    i = data.find(b"Exif\0\0")
    while i >= 0:
        res = parse_exif_tiff(data, i + 6)
        if res:
            return res
        i = data.find(b"Exif\0\0", i + 6)
    for marker in (b"II*\0", b"MM\0*"):  # HEIC Exif items, PNG eXIf chunks
        j = data.find(marker)
        if j >= 0:
            res = parse_exif_tiff(data, j)
            if res:
                return res
    return {}


# --------------------------------------------------------------------- scanner
class PlaceScanner:
    def __init__(self, account: "Account"):
        self.acc = account
        self.task: Optional[asyncio.Task] = None
        self.state = "off"
        self.checked = 0
        self.found = 0
        self.error: Optional[str] = None
        self._wake = asyncio.Event()

    @property
    def db(self):
        return self.acc.db

    def candidates_sql(self) -> str:
        exts = ",".join(f"'{e}'" for e in IMAGE_EXTS)
        return (f"FROM files f WHERE f.kind='document' AND (f.ext IN ({exts}) OR f.mime LIKE 'image/%') "
                f"AND f.id NOT IN (SELECT file_id FROM geo)")

    def status(self) -> dict:
        from .settings import settings
        left = self.db.one(f"SELECT COUNT(*) AS n {self.candidates_sql()}")["n"]
        with_geo = self.db.one("SELECT COUNT(*) AS n FROM geo WHERE lat IS NOT NULL")["n"]
        checked = self.db.one("SELECT COUNT(*) AS n FROM geo")["n"]
        return {"enabled": bool(settings.get("places_scan")), "state": self.state, "left": left,
                "checked": checked, "found": with_geo, "error": self.error}

    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._loop())

    def poke(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        from .settings import settings
        while True:
            try:
                if not settings.get("places_scan") or self.acc.status != "online":
                    self.state = "off" if not settings.get("places_scan") else "waiting"
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), 60)
                    except asyncio.TimeoutError:
                        pass
                    continue
                rows = self.db.q(f"SELECT f.id, f.chat_id, f.msg_id {self.candidates_sql()} ORDER BY f.date DESC LIMIT 40")
                if not rows:
                    self.state = "done"
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), 600)
                    except asyncio.TimeoutError:
                        pass
                    continue
                self.state = "scanning"
                for r in rows:
                    if not settings.get("places_scan"):
                        break
                    info = await self.scan_one(r["chat_id"], r["msg_id"])
                    self.db.x("INSERT OR REPLACE INTO geo(file_id, lat, lon, taken, checked) VALUES(?,?,?,?,?)",
                              (r["id"], info.get("lat"), info.get("lon"), info.get("taken"), int(time.time())))
                    self.checked += 1
                    if info.get("lat") is not None:
                        self.found += 1
                    await asyncio.sleep(0.35)
            except asyncio.CancelledError:
                raise
            except errors.FloodWaitError as exc:
                self.state = f"waiting {exc.seconds}s for Telegram"
                await asyncio.sleep(exc.seconds + 1)
            except Exception as exc:
                log.warning("place scan: %s", exc)
                self.error = str(exc)
                await asyncio.sleep(30)

    async def scan_one(self, chat_id: int, msg_id: int) -> dict:
        try:
            src = await self.acc.streamer.source(chat_id, msg_id)
            if src.local:
                with open(src.local, "rb") as fh:
                    return parse_exif(fh.read(HEAD))
            data = b""
            async for part in self.acc.client.iter_download(src.location, offset=0, request_size=HEAD, limit=1,
                                                            file_size=src.size, dc_id=src.dc_id):
                data = bytes(part)
                break
            return parse_exif(data)
        except errors.FloodWaitError:
            raise
        except Exception as exc:
            log.debug("no EXIF for %s:%s: %s", chat_id, msg_id, exc)
            return {}
