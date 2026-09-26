"""Convert raw Telethon messages into flat file records for the index.

Works on raw TL attributes only, so it behaves the same for messages coming
from history iteration, live updates, and upload responses.
"""
import mimetypes
from typing import Optional

from telethon import utils
from telethon.tl import types

MANIFEST_NAME = "tgdrive-manifest.json"

KINDS = ["photo", "video", "document", "audio", "voice", "round", "gif"]

_REAL_SIZES = (types.PhotoSize, types.PhotoCachedSize, types.PhotoSizeProgressive)


def size_bytes(s) -> int:
    if isinstance(s, types.PhotoSize):
        return s.size or 0
    if isinstance(s, types.PhotoCachedSize):
        return len(s.bytes or b"")
    if isinstance(s, types.PhotoSizeProgressive):
        return max(s.sizes) if s.sizes else 0
    return 0


def real_sizes(sizes) -> list:
    return [s for s in (sizes or []) if isinstance(s, _REAL_SIZES)]


def largest_size(sizes):
    real = real_sizes(sizes)
    if not real:
        return None
    return max(real, key=lambda s: (s.w * s.h, size_bytes(s)))


def stripped_bytes(sizes) -> Optional[bytes]:
    """Telegram's ~200-byte inline preview (rebuilt into a tiny JPEG by the UI)."""
    for s in sizes or []:
        if isinstance(s, types.PhotoStrippedSize) and s.bytes and len(s.bytes) < 2048:
            return bytes(s.bytes)
    return None


def topic_of(msg) -> Optional[int]:
    rt = getattr(msg, "reply_to", None)
    if rt is not None and getattr(rt, "forum_topic", False):
        return getattr(rt, "reply_to_top_id", None) or getattr(rt, "reply_to_msg_id", None)
    return None


def pick_thumb(sizes, target: int):
    """Smallest real size whose longer side is >= target; else the largest available."""
    real = real_sizes(sizes)
    if not real:
        return None
    real.sort(key=lambda s: max(s.w, s.h))
    for s in real:
        if max(s.w, s.h) >= target:
            return s
    return real[-1]


def _ext_for(mime: str, name: Optional[str]) -> str:
    if name and "." in name:
        ext = name.rsplit(".", 1)[1].lower()
        if 0 < len(ext) <= 10 and ext.isalnum():
            return ext
    guess = mimetypes.guess_extension(mime or "") or ""
    return {".jpe": "jpg", ".jpeg": "jpg", ".oga": "ogg"}.get(guess, guess.lstrip("."))


def _stamp(msg) -> str:
    d = getattr(msg, "date", None)
    return d.strftime("%Y-%m-%d_%H-%M-%S") if d else str(msg.id)


def extract(msg, chat_id: int, chat_title: str = "", sender_name: str = "") -> Optional[dict]:
    """Return a file record for a message with a real file, or None."""
    if not isinstance(msg, types.Message):
        return None
    media = msg.media
    rec = {
        "chat_id": chat_id,
        "msg_id": msg.id,
        "date": int(msg.date.timestamp()) if msg.date else 0,
        "caption": msg.message or None,
        "sender_id": utils.get_peer_id(msg.from_id) if msg.from_id else None,
        "sender_name": sender_name or msg.post_author or None,
        "chat_title": chat_title,
        "grouped_id": msg.grouped_id,
        "is_forward": int(msg.fwd_from is not None),
        "fwd_from": (msg.fwd_from.from_name if msg.fwd_from else None),
        "is_out": int(bool(msg.out)),
        "width": None,
        "height": None,
        "duration": None,
        "performer": None,
        "audio_title": None,
        "topic_id": topic_of(msg),
    }

    if isinstance(media, types.MessageMediaPhoto):
        photo = media.photo
        if not isinstance(photo, types.Photo):
            return None  # expired self-destructing photo
        big = largest_size(photo.sizes)
        rec.update(
            kind="photo",
            mime="image/jpeg",
            ext="jpg",
            name=f"photo_{_stamp(msg)}.jpg",
            size=size_bytes(big) if big else 0,
            width=getattr(big, "w", None),
            height=getattr(big, "h", None),
            media_id=photo.id,
            has_thumb=int(bool(real_sizes(photo.sizes))),
            stripped=stripped_bytes(photo.sizes),
        )
        return rec

    if not isinstance(media, types.MessageMediaDocument):
        return None
    doc = media.document
    if not isinstance(doc, types.Document):
        return None

    mime = doc.mime_type or "application/octet-stream"
    name = None
    kind = None
    for attr in doc.attributes or []:
        if isinstance(attr, types.DocumentAttributeFilename):
            name = attr.file_name
        elif isinstance(attr, (types.DocumentAttributeSticker, types.DocumentAttributeCustomEmoji)):
            return None  # stickers are not files
        elif isinstance(attr, types.DocumentAttributeAnimated):
            kind = "gif"
        elif isinstance(attr, types.DocumentAttributeVideo):
            rec["width"], rec["height"], rec["duration"] = attr.w, attr.h, attr.duration
            if kind != "gif":
                kind = "round" if attr.round_message else "video"
        elif isinstance(attr, types.DocumentAttributeAudio):
            rec["duration"] = attr.duration
            rec["performer"] = attr.performer
            rec["audio_title"] = attr.title
            if kind is None:
                kind = "voice" if attr.voice else "audio"
        elif isinstance(attr, types.DocumentAttributeImageSize):
            rec["width"], rec["height"] = attr.w, attr.h

    if kind is None:
        kind = "photo" if mime.startswith("image/") else "document"

    if name == MANIFEST_NAME:
        return None  # TG Drive's own bookkeeping file

    ext = _ext_for(mime, name)
    if not name:
        if kind == "audio" and (rec["performer"] or rec["audio_title"]):
            base = " - ".join(x for x in (rec["performer"], rec["audio_title"]) if x)
        else:
            base = f"{kind}_{_stamp(msg)}"
        name = f"{base}.{ext}" if ext else base

    rec.update(
        kind=kind,
        mime=mime,
        ext=ext or None,
        name=name,
        size=doc.size or 0,
        media_id=doc.id,
        has_thumb=int(bool(real_sizes(doc.thumbs))),
        stripped=stripped_bytes(doc.thumbs),
    )
    return rec


def input_location(media):
    """(dc_id, InputFileLocation, size) for the full file behind a message's media."""
    if isinstance(media, types.MessageMediaPhoto):
        photo = media.photo
        big = largest_size(photo.sizes)
        loc = types.InputPhotoFileLocation(
            id=photo.id, access_hash=photo.access_hash,
            file_reference=photo.file_reference, thumb_size=big.type,
        )
        return photo.dc_id, loc, size_bytes(big)
    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        loc = types.InputDocumentFileLocation(
            id=doc.id, access_hash=doc.access_hash,
            file_reference=doc.file_reference, thumb_size="",
        )
        return doc.dc_id, loc, doc.size
    raise ValueError("Message has no downloadable file")


def thumb_sizes(media) -> list:
    if isinstance(media, types.MessageMediaPhoto) and isinstance(media.photo, types.Photo):
        return media.photo.sizes
    if isinstance(media, types.MessageMediaDocument) and isinstance(media.document, types.Document):
        return media.document.thumbs or []
    return []
