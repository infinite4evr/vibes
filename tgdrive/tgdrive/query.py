"""Search language and filters, compiled to SQL fragments over `files f`.

Free text is handled by tgdrive.search (smart matching). Operators:

  type:photo,video   ext:pdf,zip   mime:image/*   in:"chat title"   from:alice
  size>10mb  size<1g  dur>5m  w>=1920  h>=1080
  after:2024-01  before:2024-06-15  date:2023  after:7d  (d/w/m/y relative)
  source:channel|group|private|bot|saved   folder:"Tax"   tag:exam   topic:"Doubts"
  is:forwarded  is:mine  is:filed  is:unfiled  is:starred  is:album  is:watched  is:unwatched  is:inprogress
  has:caption  has:thumb  has:note  has:tags   name:"exact words"  caption:words
  match:exact  (turn off smart matching)   "exact phrase"   -excluded   -type:gif   -in:spam
"""
import json
import re

# type:pdf, type:mp3 … are read as extensions (people write file types that way too).
FILE_TYPE_EXTS = set("""pdf doc docx odt rtf txt md epub mobi azw3 djvu xls xlsx ods csv ppt pptx odp zip rar 7z tar gz
    tgz bz2 xz iso apk exe msi deb rpm appimage dmg jpg jpeg png webp heic bmp tif tiff svg psd mp3 m4a aac flac ogg opus
    wav wma mp4 mkv avi mov webm m4v flv wmv ts srt vtt ass json xml html htm py js java c cpp torrent""".split())
import time
from datetime import datetime, timedelta
from typing import Any, Optional

KIND_WORDS = {
    "photo": "photo", "photos": "photo", "image": "photo", "images": "photo", "pic": "photo", "pics": "photo",
    "video": "video", "videos": "video", "movie": "video",
    "document": "document", "documents": "document", "doc": "document", "docs": "document",
    "file": "document", "files": "document",
    "audio": "audio", "music": "audio", "song": "audio", "songs": "audio",
    "voice": "voice", "voices": "voice",
    "round": "round", "videonote": "round",
    "gif": "gif", "gifs": "gif", "animation": "gif",
}
SOURCE_WORDS = {
    "channel": ["channel"], "channels": ["channel"],
    "group": ["group", "supergroup"], "groups": ["group", "supergroup"],
    "private": ["user"], "user": ["user"], "users": ["user"], "dm": ["user"],
    "bot": ["bot"], "bots": ["bot"],
    "saved": ["saved"],
}
# Sort keys: SQL expression (never NULL, for keyset paging) and value type.
SORTS = {
    "date": "COALESCE(f.date, 0)",
    "name": "COALESCE(f.alias, f.name, '') COLLATE NOCASE",
    "size": "COALESCE(f.size, 0)",
    "chat": "COALESCE(f.chat_title, '') COLLATE NOCASE",
    "type": "f.kind",
    "duration": "COALESCE(f.duration, -1)",
    "ext": "COALESCE(f.ext, '')",
    "recent": "COALESCE((SELECT r.at FROM recent r WHERE r.chat_id=f.chat_id AND r.msg_id=f.msg_id), 0)",
    "played": "COALESCE((SELECT pb.at FROM playback pb WHERE pb.chat_id=f.chat_id AND pb.msg_id=f.msg_id), 0)",
}

TOKEN = re.compile(r'(-?)(?:([A-Za-z_]+)(:|>=|<=|>|<|=))?("([^"]*)"?|\S+)')
SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(b|k|kb|m|mb|g|gb|t|tb)?$", re.I)
UNITS = {"b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3,
         "t": 1024**4, "tb": 1024**4}


class QueryError(ValueError):
    pass


def parse_size(v: str) -> int:
    m = SIZE_RE.match(v.strip())
    if not m:
        raise QueryError(f"Can't read size '{v}'. Try 10mb, 500k or 1.5g.")
    unit = (m.group(2) or "mb").lower()  # a bare number means megabytes
    return int(float(m.group(1)) * UNITS[unit])


def parse_duration(v: str) -> float:
    v = v.strip().lower()
    if ":" in v:
        secs = 0.0
        for p in v.split(":"):
            try:
                secs = secs * 60 + float(p)
            except ValueError:
                raise QueryError(f"Can't read duration '{v}'. Try 90, 5m or 1:30.")
        return secs
    m = re.match(r"^(\d+(?:\.\d+)?)(s|m|h)?$", v)
    if not m:
        raise QueryError(f"Can't read duration '{v}'. Try 90, 5m or 1:30.")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2) or "s"]


RELATIVE_WORDS = {"today": 0, "yesterday": 1, "week": 7, "month": 30, "year": 365}


def parse_date_range(v: str) -> tuple[int, int]:
    """Return [start, end) unix timestamps for YYYY, YYYY-MM, YYYY-MM-DD, 7d/2w/3m/1y, today, yesterday."""
    v = v.strip().lower()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if v == "today":
        return int(today.timestamp()), int((today + timedelta(days=1)).timestamp())
    if v == "yesterday":
        return int((today - timedelta(days=1)).timestamp()), int(today.timestamp())
    rel = re.match(r"^(\d+)([dwmy])$", v)
    if rel:
        n, unit = int(rel.group(1)), rel.group(2)
        days = n * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
        start = datetime.now() - timedelta(days=days)
        return int(start.timestamp()), int(time.time()) + 1
    for fmt, step in (("%Y-%m-%d", "day"), ("%Y-%m", "month"), ("%Y", "year"), ("%d-%m-%Y", "day"),
                      ("%d/%m/%Y", "day")):
        try:
            d = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if step == "day":
            end = d + timedelta(days=1)
        elif step == "month":
            end = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)
        else:
            end = d.replace(year=d.year + 1)
        return int(d.timestamp()), int(end.timestamp())
    raise QueryError(f"Can't read date '{v}'. Try 2024, 2024-05, 2024-05-17, 7d, today or yesterday.")


def _split_list(v: str) -> list[str]:
    return [x.strip() for x in str(v).split(",") if x.strip()]


def empty_filters() -> dict:
    return {
        "terms": [], "phrases": [], "neg_terms": [], "name_terms": [], "caption_terms": [],
        "kinds": set(), "not_kinds": set(), "exts": set(), "not_exts": set(),
        "mimes": [], "chat_ids": [], "not_chat_ids": [], "chat_like": [], "not_chat_like": [], "chat_kinds": set(),
        "sender_like": [], "folder_like": [], "tags": [], "topic_like": [], "topic_ids": [],
        "size_min": None, "size_max": None, "date_from": None, "date_to": None,
        "dur_min": None, "dur_max": None, "w_min": None, "w_max": None, "h_min": None, "h_max": None,
        "folder_id": None, "folder_tree": False, "filed": None, "forwarded": None, "mine": None,
        "has_caption": None, "has_thumb": None, "starred": None, "has_note": None, "has_tags": None,
        "album": None, "recent": None, "match": None, "dialog_filter": None, "grouped_id": None,
        "watched": None, "in_progress": None,
        "media_id": None, "ids": None, "subjects": [], "not_subjects": [],
        "copies": None,   # "hide": one card per file (see dupes.py) · "show": every copy
    }


def _range(f: dict, lo: str, hi: str, op: str, value: float) -> None:
    if op in (">", ">="):
        f[lo] = value + (1 if op == ">" and isinstance(value, int) else 0)
    elif op in ("<", "<="):
        f[hi] = value + (1 if op == "<=" and isinstance(value, int) else 0)
    else:  # ':' or '='  -> exact-ish: treat as minimum
        f[lo] = value


def parse(text: str, f: Optional[dict] = None) -> dict:
    f = f or empty_filters()
    for m in TOKEN.finditer(text or ""):
        neg, key, op, raw, quoted = m.group(1) == "-", m.group(2), m.group(3), m.group(4), m.group(5)
        value = quoted if quoted is not None else raw
        if value.startswith((">", "<")) and op == ":":  # size:>10mb
            op = ">=" if value[1:2] == "=" and value[0] == ">" else "<=" if value[1:2] == "=" else value[0]
            value = value.lstrip("<>=")
        k = (key or "").lower()
        if not key:
            if quoted is not None:
                (f["neg_terms"] if neg else f["phrases"]).append(value)
            elif value:
                (f["neg_terms"] if neg else f["terms"]).append(value)
            continue
        if not value and k not in ("is", "has"):
            continue
        if k in ("type", "kind"):
            for w in _split_list(value):
                kind = KIND_WORDS.get(w.lower())
                if not kind and w.lower().lstrip(".") in FILE_TYPE_EXTS:
                    # type:pdf, type:mp3 … people write file types this way too: same as ext:pdf
                    (f["not_exts"] if neg else f["exts"]).add(w.lower().lstrip("."))
                    continue
                if not kind:
                    raise QueryError(f"Unknown type '{w}'. Use photo, video, document, audio, voice, round or gif "
                                     f"(or a file extension like pdf).")
                (f["not_kinds"] if neg else f["kinds"]).add(kind)
        elif k in ("ext", "extension"):
            for e in _split_list(value):
                (f["not_exts"] if neg else f["exts"]).add(e.lower().lstrip("."))
        elif k == "mime":
            f["mimes"].append(value.lower().replace("*", "%"))
        elif k in ("in", "chat"):
            (f["not_chat_like"] if neg else f["chat_like"]).append(value)
        elif k in ("from", "sender", "by"):
            f["sender_like"].append(value)
        elif k in ("source", "src"):
            kinds = SOURCE_WORDS.get(value.lower())
            if not kinds:
                raise QueryError(f"Unknown source '{value}'. Use channel, group, private, bot or saved.")
            f["chat_kinds"].update(kinds)
        elif k == "folder":
            f["folder_like"].append(value)
        elif k in ("tag", "label"):
            f["tags"].append(value.lower())
        elif k == "topic":
            f["topic_like"].append(value)
        elif k in ("subject", "subj"):
            for v in _split_list(value):
                (f["not_subjects"] if neg else f["subjects"]).append(subject_slug(v))
        elif k == "name":
            f["name_terms"].append(value)
        elif k in ("caption", "text"):
            f["caption_terms"].append(value)
        elif k == "size":
            _range(f, "size_min", "size_max", op, parse_size(value))
        elif k in ("dur", "duration", "len", "length"):
            _range(f, "dur_min", "dur_max", op, parse_duration(value))
        elif k in ("w", "width"):
            _range(f, "w_min", "w_max", op, _int(value))
        elif k in ("h", "height"):
            _range(f, "h_min", "h_max", op, _int(value))
        elif k in ("after", "since"):
            f["date_from"] = parse_date_range(value)[0]
        elif k in ("before", "until"):
            f["date_to"] = parse_date_range(value)[0]
        elif k in ("date", "on"):
            f["date_from"], f["date_to"] = parse_date_range(value)
        elif k in ("copies", "dupes", "duplicates"):
            v = value.lower()
            if v in ("show", "all", "yes", "on"):
                f["copies"] = "show"
            elif v in ("hide", "one", "unique", "no", "off"):
                f["copies"] = "hide"
            else:
                raise QueryError(f"Unknown value 'copies:{value}'. Use copies:show or copies:hide.")
        elif k == "match":
            f["match"] = "exact" if value.lower() in ("exact", "strict", "words") else "smart"
        elif k == "is":
            v = value.lower()
            if v in ("forwarded", "fwd", "forward"):
                f["forwarded"] = not neg
            elif v in ("mine", "out", "sent", "own"):
                f["mine"] = not neg
            elif v == "filed":
                f["filed"] = not neg
            elif v == "unfiled":
                f["filed"] = neg
            elif v in ("starred", "star", "fav", "favorite", "favourite"):
                f["starred"] = not neg
            elif v in ("album", "grouped"):
                f["album"] = not neg
            elif v in ("watched", "played", "seen", "done"):
                f["watched"] = not neg
            elif v in ("unwatched", "unplayed", "unseen", "new"):
                f["watched"] = neg
            elif v in ("inprogress", "in-progress", "started", "partial", "continue"):
                f["in_progress"] = not neg
            elif v in KIND_WORDS:
                (f["not_kinds"] if neg else f["kinds"]).add(KIND_WORDS[v])
            else:
                raise QueryError(f"Unknown flag 'is:{value}'. Use forwarded, mine, filed, unfiled, starred, album, "
                                 "watched, unwatched or inprogress.")
        elif k == "has":
            v = value.lower()
            if v in ("caption", "text"):
                f["has_caption"] = not neg
            elif v in ("thumb", "preview", "thumbnail"):
                f["has_thumb"] = not neg
            elif v in ("note", "notes"):
                f["has_note"] = not neg
            elif v in ("tag", "tags", "label"):
                f["has_tags"] = not neg
            else:
                raise QueryError(f"Unknown flag 'has:{value}'. Use caption, thumb, note or tags.")
        else:
            # Not an operator (e.g. a URL fragment or "C:"): treat as plain text.
            (f["neg_terms"] if neg else f["terms"]).append(m.group(0).lstrip("-"))
    return f


def _int(v: str) -> int:
    try:
        return int(v)
    except ValueError:
        raise QueryError(f"'{v}' should be a whole number.")


def subject_slug(v: str) -> str:
    from .textproc import fold
    return re.sub(r"[^\w]+", "_", fold(v.strip())).strip("_")


def _like(v: str) -> str:
    return "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


PL = "(f.chat_id, f.msg_id) IN (SELECT chat_id, msg_id FROM placements WHERE {})"


_F_ALIAS = re.compile(r"\bf\.")


def dedupe_clause(where: str, params: list, in_cand: bool = False) -> tuple[str, list]:
    """Hide a file when a better-ranked copy of it (dups.rank) is also in this list: the same filters hold for
    that copy (and, for a text search, it is one of the matches too). So every list shows one card per file,
    and a chat or folder still shows its own files."""
    other = _F_ALIAS.sub("g.", where)
    cand = " AND EXISTS (SELECT 1 FROM cand c2 WHERE c2.id=g.id)" if in_cand else ""
    return (f"NOT EXISTS (SELECT 1 FROM dups d JOIN dups d2 ON d2.grp=d.grp AND d2.rank<d.rank "
            f"JOIN files g ON g.id=d2.file_id WHERE d.file_id=f.id AND ({other}){cand})"), list(params)


def build_where(f: dict, skip_kinds: bool = False, descendants=None, dedupe: bool = True) -> tuple[str, list]:
    """WHERE clause over `files f` for every non-text filter. No joins needed.
    With copies=hide (and dedupe), extra copies of a file are left out (see dedupe_clause)."""
    where: list[str] = []
    params: list = []

    def in_list(col: str, values, negate: bool = False):
        values = list(values)
        if values:
            where.append(f"{col} {'NOT ' if negate else ''}IN ({','.join('?' * len(values))})")
            params.extend(values)

    if not skip_kinds:
        in_list("f.kind", f["kinds"])
    in_list("f.kind", f["not_kinds"], negate=True)
    in_list("f.ext", f["exts"])
    if f["not_exts"]:
        where.append(f"COALESCE(f.ext,'') NOT IN ({','.join('?' * len(f['not_exts']))})")
        params.extend(f["not_exts"])
    in_list("f.chat_id", f["chat_ids"])
    in_list("f.chat_id", f["not_chat_ids"], negate=True)
    if f["chat_kinds"]:
        where.append(f"f.chat_id IN (SELECT id FROM chats WHERE kind IN ({','.join('?' * len(f['chat_kinds']))}))")
        params.extend(f["chat_kinds"])
    for v in f["chat_like"]:
        where.append("f.chat_id IN (SELECT id FROM chats WHERE title LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\')")
        params += [_like(v), _like(v)]
    for v in f["not_chat_like"]:
        where.append("f.chat_id NOT IN (SELECT id FROM chats WHERE title LIKE ? ESCAPE '\\' OR "
                     "COALESCE(username,'') LIKE ? ESCAPE '\\')")
        params += [_like(v), _like(v)]
    if f["dialog_filter"] is not None:
        where.append("f.chat_id IN (SELECT value FROM json_each((SELECT chat_ids FROM dialog_filters WHERE id=?)))")
        params.append(f["dialog_filter"])
    if f["mimes"]:
        where.append("(" + " OR ".join("f.mime LIKE ?" for _ in f["mimes"]) + ")")
        params.extend(f["mimes"])
    for v in f["sender_like"]:
        where.append("(f.sender_name LIKE ? ESCAPE '\\' OR f.fwd_from LIKE ? ESCAPE '\\')")
        params += [_like(v), _like(v)]
    for v in f["folder_like"]:
        where.append(PL.format("folder_id IN (SELECT id FROM folders WHERE name LIKE ? ESCAPE '\\')"))
        params.append(_like(v))
    for t in f["tags"]:
        where.append(PL.format("(',' || LOWER(COALESCE(tags,'')) || ',') LIKE ?"))
        params.append(f"%,{t.strip()},%")
    for v in f["topic_like"]:
        where.append("(f.chat_id, f.topic_id) IN (SELECT chat_id, topic_id FROM topics WHERE title LIKE ? ESCAPE '\\')")
        params.append(_like(v))
    if f["topic_ids"]:
        where.append(f"f.topic_id IN ({','.join('?' * len(f['topic_ids']))})")
        params.extend(f["topic_ids"])
    for t in f["name_terms"]:
        where.append("(COALESCE(f.alias, f.name) LIKE ? ESCAPE '\\')")
        params.append(_like(t))
    for t in f["caption_terms"]:
        where.append("(f.caption LIKE ? ESCAPE '\\')")
        params.append(_like(t))

    for col, lo, hi in (("f.size", "size_min", "size_max"), ("f.date", "date_from", "date_to"),
                        ("f.duration", "dur_min", "dur_max"), ("f.width", "w_min", "w_max"),
                        ("f.height", "h_min", "h_max")):
        if f[lo] is not None:
            where.append(f"{col} >= ?")
            params.append(f[lo])
        if f[hi] is not None:
            where.append(f"{col} < ?")
            params.append(f[hi])

    if f["folder_id"]:
        ids = [f["folder_id"], *(descendants(f["folder_id"]) if f["folder_tree"] and descendants else [])]
        where.append(PL.format(f"folder_id IN ({','.join('?' * len(ids))})"))
        params.extend(ids)
    if f["filed"] is True:
        where.append(PL.format("folder_id IS NOT NULL"))
    elif f["filed"] is False:
        where.append("NOT " + PL.format("folder_id IS NOT NULL"))
    if f["starred"] is True:
        where.append(PL.format("starred=1"))
    elif f["starred"] is False:
        where.append("NOT " + PL.format("starred=1"))
    if f["has_note"] is not None:
        where.append(("" if f["has_note"] else "NOT ") + PL.format("COALESCE(note,'')<>''"))
    if f["has_tags"] is not None:
        where.append(("" if f["has_tags"] else "NOT ") + PL.format("COALESCE(tags,'')<>''"))
    if f["recent"]:
        where.append("(f.chat_id, f.msg_id) IN (SELECT chat_id, msg_id FROM recent)")
    PB = "(f.chat_id, f.msg_id) IN (SELECT chat_id, msg_id FROM playback WHERE {})"
    if f["watched"] is True:
        where.append(PB.format("done=1"))
    elif f["watched"] is False:
        where.append("f.kind IN ('video','audio','voice','round') AND NOT " + PB.format("done=1"))
    if f["in_progress"] is True:
        where.append(PB.format("done=0 AND pos>0"))
    elif f["in_progress"] is False:
        where.append("NOT " + PB.format("done=0 AND pos>0"))
    def subj_like(v: str) -> str:
        return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    pos = [v for v in f["subjects"] if v]
    if pos:
        none = [v for v in pos if v in ("none", "unknown", "unclassified", "other")]
        named = [v for v in pos if v not in none]
        alts = []
        if named:
            alts.append("f.id IN (SELECT file_id FROM file_subjects WHERE " +
                        " OR ".join("subject LIKE ? ESCAPE '\\'" for _ in named) + ")")
            params.extend(subj_like(v) for v in named)
        if none:
            alts.append("f.id NOT IN (SELECT file_id FROM file_subjects WHERE subject<>'_none')")
        where.append("(" + " OR ".join(alts) + ")")
    for v in f["not_subjects"]:
        if v in ("none", "unknown", "unclassified", "other"):
            where.append("f.id IN (SELECT file_id FROM file_subjects WHERE subject<>'_none')")
        elif v:
            where.append("f.id NOT IN (SELECT file_id FROM file_subjects WHERE subject LIKE ? ESCAPE '\\')")
            params.append(subj_like(v))
    if f["grouped_id"] is not None:
        where.append("f.grouped_id = ?")
        params.append(f["grouped_id"])
    if f["media_id"] is not None:
        where.append("f.media_id = ?")
        params.append(f["media_id"])
    if f["ids"] is not None:
        where.append("f.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(f["ids"])))
    for key, sql_true, sql_false in (
        ("forwarded", "f.is_forward=1", "f.is_forward=0"),
        ("mine", "f.is_out=1", "f.is_out=0"),
        ("has_caption", "COALESCE(f.caption,'')<>''", "COALESCE(f.caption,'')=''"),
        ("has_thumb", "f.has_thumb=1", "f.has_thumb=0"),
        ("album", "f.grouped_id IS NOT NULL", "f.grouped_id IS NULL"),
    ):
        if f[key] is True:
            where.append(sql_true)
        elif f[key] is False:
            where.append(sql_false)
    base = " AND ".join(where) or "1"
    if dedupe and f.get("copies") == "hide":
        clause, cparams = dedupe_clause(base, params)
        return f"{base} AND {clause}", params + cparams
    return base, params


def has_text(f: dict) -> bool:
    return bool(f["terms"] or f["phrases"])


def only_scope_filters(f: dict) -> Optional[tuple[Optional[list[int]], set]]:
    """If the filters are just chat ids and/or kinds, return (chat_ids, kinds) so stats can answer counts."""
    simple = {"chat_ids", "kinds"}
    for k, v in f.items():
        if k in simple:
            continue
        # Unset filters are None or empty. False is a real filter (filed=0 = only unfiled files, is:mine
        # negated …) except for folder_tree, a plain on/off switch that means nothing without folder_id.
        if v is None or (isinstance(v, (list, set, str)) and not v) or (k == "folder_tree" and v is False):
            continue
        if k in ("match", "copies"):
            continue
        return None
    return (list(f["chat_ids"]) or None, set(f["kinds"]))


def from_params(p: dict[str, Any]) -> dict:
    """Merge explicit API parameters (from the filter panel) with the parsed text query."""
    f = parse(p.get("q") or "")
    if p.get("kinds"):
        for k in _split_list(p["kinds"]):
            if k not in KIND_WORDS and k not in KIND_WORDS.values():
                raise QueryError(f"Unknown type '{k}'.")
            f["kinds"].add(KIND_WORDS.get(k, k))
    if p.get("exts"):
        f["exts"].update(e.lower().lstrip(".") for e in _split_list(p["exts"]))
    if p.get("chat_ids"):
        try:
            f["chat_ids"].extend(int(x) for x in _split_list(p["chat_ids"]))
        except ValueError:
            raise QueryError("chat_ids must be numbers.")
    if p.get("chat_kinds"):
        for w in _split_list(p["chat_kinds"]):
            f["chat_kinds"].update(SOURCE_WORDS.get(w, [w]))
    if p.get("sender"):
        f["sender_like"].append(p["sender"])
    if p.get("tag"):
        f["tags"].append(str(p["tag"]).lower())
    if p.get("subject"):
        f["subjects"].extend(subject_slug(v) for v in _split_list(p["subject"]))
    if p.get("ids"):
        try:
            f["ids"] = [int(x) for x in _split_list(p["ids"])][:5000]
        except ValueError:
            raise QueryError("ids must be numbers.")
    if p.get("size_min"):
        f["size_min"] = parse_size(str(p["size_min"]))
    if p.get("size_max"):
        f["size_max"] = parse_size(str(p["size_max"]))
    if p.get("date_from"):
        f["date_from"] = parse_date_range(p["date_from"])[0]
    if p.get("date_to"):
        f["date_to"] = parse_date_range(p["date_to"])[1]  # inclusive of that day
    if p.get("dur_min"):
        f["dur_min"] = parse_duration(str(p["dur_min"]))
    if p.get("dur_max"):
        f["dur_max"] = parse_duration(str(p["dur_max"]))
    if p.get("folder_id"):
        f["folder_id"] = p["folder_id"]
        f["folder_tree"] = str(p.get("folder_tree", "")) in ("1", "true")
    if p.get("dialog_filter"):
        f["dialog_filter"] = int(p["dialog_filter"])
    if p.get("topic_id"):
        f["topic_ids"].append(int(p["topic_id"]))
    if p.get("grouped_id"):
        f["grouped_id"] = int(p["grouped_id"])
    if p.get("copies") in ("show", "hide") and f["copies"] is None:   # a copies: word in the query wins
        f["copies"] = p["copies"]
    if p.get("match"):
        f["match"] = "exact" if p["match"] == "exact" else "smart"
    for key in ("filed", "forwarded", "mine", "has_caption", "has_thumb", "starred", "has_note", "has_tags",
                "album", "recent", "watched", "in_progress"):
        v = p.get(key)
        if v in ("1", "true", True):
            f[key] = True
        elif v in ("0", "false", False):
            f[key] = False
    return f
