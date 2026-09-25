"""An in-memory stand-in for TelegramClient, good enough to exercise indexing,
folders, transfers and the API without a network connection."""
import io
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon.tl import functions, types

from tgdrive.accounts import Account
from tgdrive.extract import MANIFEST_NAME, extract

CH = 1_000_000_000_000


def peer_of(cid: int):
    if cid <= -CH:
        return types.PeerChannel(-cid - CH)
    if cid < 0:
        return types.PeerChat(-cid)
    return types.PeerUser(cid)


def thumbs():
    return [types.PhotoSize(type="m", w=320, h=240, size=9000), types.PhotoSize(type="x", w=800, h=600, size=40000)]


def doc_msg(cid, mid, name, mime, size, date, attrs=(), caption="", thumb=False, out=False, fwd=None):
    doc = types.Document(id=abs(cid) * 100000 + mid, access_hash=1, file_reference=b"r", date=date,
                         mime_type=mime, size=size, dc_id=2,
                         attributes=[*([types.DocumentAttributeFilename(name)] if name else []), *attrs],
                         thumbs=thumbs() if thumb else None)
    return types.Message(id=mid, peer_id=peer_of(cid), date=date, message=caption,
                         media=types.MessageMediaDocument(document=doc), out=out,
                         fwd_from=types.MessageFwdHeader(date=date, from_name=fwd) if fwd else None)


def photo_msg(cid, mid, date, caption="", w=1280, h=960):
    photo = types.Photo(id=abs(cid) * 100000 + mid, access_hash=1, file_reference=b"r", date=date, dc_id=2,
                        sizes=[types.PhotoStrippedSize(type="i", bytes=b"\x01\x28\x28" + bytes(60)),
                               types.PhotoSize(type="m", w=320, h=240, size=9000),
                               types.PhotoSize(type="y", w=w, h=h, size=210000)])
    return types.Message(id=mid, peer_id=peer_of(cid), date=date, message=caption,
                         media=types.MessageMediaPhoto(photo=photo))


def text_msg(cid, mid, date, text="hello"):
    return types.Message(id=mid, peer_id=peer_of(cid), date=date, message=text)


def video_attr(dur=30, round_=False):
    return types.DocumentAttributeVideo(duration=dur, w=1920, h=1080, round_message=round_)


def audio_attr(dur=200, voice=False, title=None, performer=None):
    return types.DocumentAttributeAudio(duration=dur, voice=voice, title=title, performer=performer)


def _kind(msg):
    rec = extract(msg, 0)
    return rec["kind"] if rec else None


FILTER_KINDS = {
    types.InputMessagesFilterPhotoVideo: lambda m: _kind(m) == "video" or isinstance(m.media, types.MessageMediaPhoto),
    types.InputMessagesFilterDocument: lambda m: _kind(m) == "document" or (
        _kind(m) == "photo" and isinstance(m.media, types.MessageMediaDocument)),
    types.InputMessagesFilterMusic: lambda m: _kind(m) == "audio",
    types.InputMessagesFilterRoundVoice: lambda m: _kind(m) in ("voice", "round"),
    types.InputMessagesFilterGif: lambda m: _kind(m) == "gif",
}


class Dialog:
    def __init__(self, entity, message):
        self.entity, self.message = entity, message


class FakeClient:
    def __init__(self, chats: dict, entities: dict, content: dict | None = None):
        self.chats = chats            # cid -> list[Message]
        self.entities = entities      # cid -> TL entity
        self.content = content or {}  # document/photo id -> bytes
        self.handlers = []
        self.parts: dict[int, dict[int, bytes]] = {}
        self.requests = []
        self.pinned: dict[int, int] = {}
        self.fail_iter_after = None
        self.iter_calls = 0

    # ---- entities
    async def get_input_entity(self, cid):
        if cid not in self.entities:
            raise ValueError("unknown")
        return cid

    async def get_dialogs(self):
        return []

    async def iter_dialogs(self):
        for cid, ent in self.entities.items():
            msgs = self.chats.get(cid, [])
            yield Dialog(ent, max(msgs, key=lambda m: m.id) if msgs else None)

    def add_event_handler(self, fn, ev):
        self.handlers.append((fn, ev))

    # ---- messages
    async def iter_messages(self, peer, limit=None, *, filter=None, min_id=0, offset_id=0, search=None,
                            wait_time=None):
        self.iter_calls += 1
        msgs = sorted(self.chats.get(peer, []), key=lambda m: -m.id)
        n = 0
        for m in msgs:
            if m.id <= min_id or (offset_id and m.id >= offset_id):
                continue
            if filter and not FILTER_KINDS[filter](m):
                continue
            if search and not (_kind(m) and search in (extract(m, 0) or {}).get("name", "")) \
                    and not _is_manifest_msg(m, search):
                continue
            if self.fail_iter_after is not None and n >= self.fail_iter_after:
                raise ConnectionError("simulated drop")
            n += 1
            yield m
            if limit and n >= limit:
                return

    async def get_messages(self, peer, ids=None):
        by_id = {m.id: m for m in self.chats.get(peer, [])}
        if isinstance(ids, types.InputMessagePinned):
            return by_id.get(self.pinned.get(peer))
        if isinstance(ids, list):
            return [by_id.get(i) for i in ids]
        return by_id.get(ids)

    def _new_id(self, peer):
        return max([m.id for m in self.chats.get(peer, [])] + [0]) + 1

    async def send_file(self, peer, file, caption="", attributes=None, force_document=False, **kw):
        mid = self._new_id(peer)
        now = datetime.now(timezone.utc)
        if isinstance(file, io.BytesIO):
            data = file.getvalue()
            msg = doc_msg(peer, mid, file.name, "application/json", len(data), now, caption=caption)
            self.content[msg.media.document.id] = data
        else:  # re-sending existing media
            media = file
            msg = types.Message(id=mid, peer_id=peer_of(peer), date=now, message=caption, media=media, out=True)
        self.chats.setdefault(peer, []).append(msg)
        return msg

    async def edit_message(self, peer, mid, file=None, **kw):
        msgs = self.chats[peer]
        old = next(m for m in msgs if m.id == mid)
        data = file.getvalue()
        new = doc_msg(peer, mid, file.name, "application/json", len(data), old.date)
        new.media.document.id += random.randint(1, 10**6)
        self.content[new.media.document.id] = data
        msgs[msgs.index(old)] = new
        return new

    async def pin_message(self, peer, msg, notify=False):
        self.pinned[peer] = msg.id if hasattr(msg, "id") else msg

    async def delete_messages(self, peer, ids, revoke=True):
        self.chats[peer] = [m for m in self.chats.get(peer, []) if m.id not in ids]
        return []

    async def download_media(self, msg, file=None, thumb=None):
        media = msg.media
        key = media.document.id if isinstance(media, types.MessageMediaDocument) else media.photo.id
        data = self.content.get(key, b"\xff\xd8thumb" if thumb else b"x" * 100)
        if file is bytes:
            return data
        Path(file).write_bytes(data)
        return file

    async def iter_download(self, location, offset=0, request_size=512 * 1024, file_size=None, dc_id=None,
                            limit=None):
        self.download_calls = getattr(self, "download_calls", 0) + 1
        sent = 0
        if location.id not in self.content:  # demo: synthesise the file at a believable speed
            import asyncio
            pos = offset
            while pos < (file_size or 0) and (limit is None or sent < limit):
                n = min(request_size, file_size - pos)
                await asyncio.sleep(0.03)
                yield b"\0" * n
                pos += n
                sent += 1
            return
        data = self.content[location.id]
        pos = offset
        while pos < len(data) and (limit is None or sent < limit):
            yield data[pos:pos + request_size]
            pos += request_size
            sent += 1

    async def forward_messages(self, target, ids, source):
        out = []
        for mid in ids:
            msg = next(m for m in self.chats.get(source, []) if m.id == mid)
            new = await self.send_file(target, msg.media, caption=msg.message)
            out.append(new)
        return out

    # ---- raw requests
    async def __call__(self, req):
        self.requests.append(req)
        if isinstance(req, functions.messages.GetSearchCountersRequest):
            out = []
            for f in req.filters:
                n = sum(1 for m in self.chats.get(req.peer, []) if FILTER_KINDS[type(f)](m))
                out.append(types.messages.SearchCounter(filter=f, count=n))
            return out
        if isinstance(req, functions.upload.SaveFilePartRequest):
            self.parts.setdefault(req.file_id, {})[req.file_part] = req.bytes
            return True
        if isinstance(req, functions.upload.SaveBigFilePartRequest):
            self.parts.setdefault(req.file_id, {})[req.file_part] = req.bytes
            return True
        if isinstance(req, functions.messages.SendMediaRequest):
            f = req.media.file
            data = b"".join(v for _, v in sorted(self.parts[f.id].items()))
            mid = self._new_id(req.peer)
            name = req.media.attributes[0].file_name
            msg = doc_msg(req.peer, mid, name, req.media.mime_type, len(data), datetime.now(timezone.utc), out=True)
            self.content[msg.media.document.id] = data
            self.chats.setdefault(req.peer, []).append(msg)
            return types.Updates(updates=[types.UpdateNewChannelMessage(message=msg, pts=1, pts_count=1)],
                                 users=[], chats=[], date=datetime.now(timezone.utc), seq=0)
        if isinstance(req, functions.messages.GetDialogFiltersRequest):
            return types.messages.DialogFilters(filters=[
                types.DialogFilterDefault(),
                types.DialogFilter(id=2, title=types.TextWithEntities(text="Study", entities=[]),
                                   pinned_peers=[], include_peers=[types.InputPeerChannel(102, 1)],
                                   exclude_peers=[], broadcasts=False),
                types.DialogFilter(id=3, title=types.TextWithEntities(text="Bots", entities=[]),
                                   pinned_peers=[], include_peers=[], exclude_peers=[], bots=True),
            ])
        if isinstance(req, functions.channels.CreateChannelRequest):
            ch = types.Channel(id=999, title=req.title, photo=types.ChatPhotoEmpty(),
                               date=datetime.now(timezone.utc), broadcast=True, creator=True, access_hash=5)
            cid = -CH - 999
            self.entities[cid] = ch
            self.chats[cid] = []
            return types.Updates(updates=[], users=[], chats=[ch], date=datetime.now(timezone.utc), seq=0)
        raise NotImplementedError(type(req).__name__)


def _is_manifest_msg(m, search):
    return search == MANIFEST_NAME and isinstance(m.media, types.MessageMediaDocument) and any(
        getattr(a, "file_name", None) == MANIFEST_NAME for a in m.media.document.attributes)


def channel(cid_raw, title, username=None, creator=False, megagroup=False):
    return types.Channel(id=cid_raw, title=title, photo=types.ChatPhotoEmpty(), date=datetime.now(timezone.utc),
                         broadcast=not megagroup, megagroup=megagroup, creator=creator, username=username,
                         access_hash=1)


def user(uid, first, last=None, bot=False, is_self=False):
    return types.User(id=uid, first_name=first, last_name=last, bot=bot, is_self=is_self, access_hash=1)


def sample_world(seed: int = 7, scale: int = 1):
    """A small but varied set of chats and files."""
    rnd = random.Random(seed)
    base = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    ents = {
        -CH - 101: channel(101, "Design Resources", username="designres"),
        -CH - 102: channel(102, "Physics Lectures"),
        -CH - 103: channel(103, "Family Photos", megagroup=True),
        -55: types.Chat(id=55, title="Flatmates", photo=types.ChatPhotoEmpty(), participants_count=4,
                        date=base, version=1),
        777: user(777, "Priya", "Sharma"),
        888: user(888, "Invoice Bot", bot=True),
        1: user(1, "Me", is_self=True),
    }
    chats = {cid: [] for cid in ents}
    content = {}

    def add(cid, msg, data_len=None):
        chats[cid].append(msg)
        if isinstance(msg.media, types.MessageMediaDocument) and data_len:
            content[msg.media.document.id] = bytes(rnd.getrandbits(8) for _ in range(data_len))

    mid = {cid: 0 for cid in ents}

    def nid(cid):
        mid[cid] += 1
        return mid[cid]

    for i in range(18 * scale):
        d = base - timedelta(days=i * 3, hours=rnd.randint(0, 20))
        cid = -CH - 101
        name = rnd.choice(["brand-guidelines", "icon-set", "ui-kit", "poster-mockup", "type-specimen"])
        ext, mime = rnd.choice([("pdf", "application/pdf"), ("zip", "application/zip"),
                                ("fig", "application/octet-stream"), ("png", "image/png")])
        add(cid, doc_msg(cid, nid(cid), f"{name}-v{i}.{ext}", mime, rnd.randint(200_000, 900_000_000), d,
                         caption=rnd.choice(["", "New drop for this week", "Free for commercial use"]),
                         thumb=ext in ("png", "pdf")), 2000)
        add(cid, text_msg(cid, nid(cid), d, "discussion"))
    for i in range(10 * scale):
        d = base - timedelta(days=i * 5)
        cid = -CH - 102
        add(cid, doc_msg(cid, nid(cid), f"Lecture {i + 1:02d} - Quantum Mechanics.mp4", "video/mp4",
                         rnd.randint(300, 1900) * 1024 * 1024, d, attrs=[video_attr(rnd.randint(2400, 5400))],
                         thumb=True, caption=f"Lecture {i + 1}: wave functions and operators"))
        add(cid, doc_msg(cid, nid(cid), f"Problem set {i + 1}.pdf", "application/pdf",
                         rnd.randint(100, 900) * 1024, d, thumb=True))
    for i in range(24 * scale):
        d = base - timedelta(days=i * 2, hours=3)
        cid = -CH - 103
        add(cid, photo_msg(cid, nid(cid), d, caption=rnd.choice(["", "Diwali at home", "Goa trip", "Birthday"])))
    for i in range(6 * scale):
        d = base - timedelta(days=i * 7)
        add(-55, doc_msg(-55, nid(-55), None, "audio/ogg", rnd.randint(20, 90) * 1024, d,
                         attrs=[audio_attr(rnd.randint(5, 80), voice=True)]))
        add(-55, doc_msg(-55, nid(-55), f"electricity-bill-{d:%b-%Y}.pdf", "application/pdf", 180_000, d,
                         thumb=True))
    for i in range(8 * scale):
        d = base - timedelta(days=i * 4)
        add(777, doc_msg(777, nid(777), f"Track {i + 1}.mp3", "audio/mpeg", rnd.randint(3, 9) * 1024 * 1024, d,
                         attrs=[audio_attr(rnd.randint(150, 320), title=f"Monsoon {i + 1}", performer="Anoushka")]))
        add(777, doc_msg(777, nid(777), "animation.mp4", "video/mp4", 400_000, d,
                         attrs=[types.DocumentAttributeAnimated(), video_attr(4)], thumb=True))
    for i in range(12 * scale):
        d = base - timedelta(days=i * 30)
        add(888, doc_msg(888, nid(888), f"Invoice-2026-{i + 1:03d}.pdf", "application/pdf", 64_000, d,
                         thumb=True, caption=f"Invoice #{i + 1} for September hosting"))
    add(1, doc_msg(1, nid(1), "passport-scan.jpg", "image/jpeg", 2_300_000, base, thumb=True, out=True), 5000)
    add(1, doc_msg(1, nid(1), "resume-2026.docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   84_000, base - timedelta(days=40), out=True, fwd="Career Center"), 3000)
    return chats, ents, content


def make_account(tmp: Path, world=None, uid: int = 1) -> tuple[Account, FakeClient]:
    chats, ents, content = world or sample_world()
    client = FakeClient(chats, ents, content)
    acc = Account(uid, tmp / str(uid), client=client)
    acc.status = "online"
    acc.me = ents.get(1) or user(uid, "Me", is_self=True)
    acc.db.set_meta("name", "Aarav Mehta")
    acc.db.set_meta("username", "aarav")
    acc._dialogs_loaded = True
    return acc, client
