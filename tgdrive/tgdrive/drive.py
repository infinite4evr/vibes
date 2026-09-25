"""Folders and file metadata, synced through a private "TG Drive" channel.

The channel holds:
  * a pinned document `tgdrive-manifest.json` describing the folder tree, which
    file lives in which folder (one folder per file), renamed display names,
    stars, tags, notes, folder colours and saved searches;
  * files uploaded through TG Drive, and copies saved from other chats.

Files from other chats are placed into folders by reference (chat id + message
id), so nothing is duplicated unless you ask for a copy.

Sync (manifest v2): every folder, item and saved search carries a modification
time, deletions leave tombstones, and two devices' changes are merged entity by
entity (newest wins) before every write and whenever another device writes.
Large manifests are gzip-compressed. The last 30 versions are kept locally
(Settings → Advanced → Folder backups) and every change can be undone.
"""
import asyncio
import gzip
import hashlib
import io
import json
import logging
import re
import secrets
import time
from typing import TYPE_CHECKING, Optional

from telethon import errors, utils
from telethon.tl import functions, types

from . import config
from .extract import MANIFEST_NAME

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.drive")

FLUSH_DELAY = 2.0
ABOUT = "Storage for TG Drive. The pinned tgdrive-manifest.json holds your folders — keep it."
GZIP_OVER = 256 * 1024
TOMBSTONE_DAYS = 120
MAX_BACKUPS = 30
COLORS = {"", "red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "grey"}


class DriveError(Exception):
    pass


def ms() -> int:
    return int(time.time() * 1000)


def _is_manifest(msg) -> bool:
    if not isinstance(msg, types.Message) or not isinstance(msg.media, types.MessageMediaDocument):
        return False
    doc = msg.media.document
    return isinstance(doc, types.Document) and any(
        isinstance(a, types.DocumentAttributeFilename) and a.file_name == MANIFEST_NAME
        for a in doc.attributes or [])


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise DriveError("Give it a name.")
    if len(name) > 120:
        raise DriveError("Names can be at most 120 characters.")
    if name in (".", ".."):
        raise DriveError("That name isn't allowed.")
    return name


def clean_tags(tags) -> Optional[str]:
    if tags is None:
        return None
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for t in tags:
        t = " ".join(str(t).split()).lower()[:40]
        if t and t not in out:
            out.append(t)
    return ",".join(out[:30])


RULE_MODES = {"smart", "auto"}


def clean_emoji(e: Optional[str]) -> Optional[str]:
    e = " ".join(str(e or "").split())
    if not e:
        return None
    if len(e) > 16:
        raise DriveError("Use a single emoji (or up to a few characters).")
    return e


def clean_rules(rules: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """Folder rules: {"q": "...", "params": {...}, "mode": "smart"|"auto"}.
    smart = the folder shows every matching file (nothing is moved);
    auto  = matching files that aren't in a folder yet are filed here automatically."""
    if not rules:
        return None, None
    if not isinstance(rules, dict):
        raise DriveError("Folder rules must be an object.")
    mode = rules.get("mode") or "smart"
    if mode not in RULE_MODES:
        raise DriveError("Rules mode is smart or auto.")
    q = str(rules.get("q") or "").strip()[:500]
    params = rules.get("params") or {}
    if not isinstance(params, dict):
        raise DriveError("Rule filters must be an object.")
    params = {str(k): str(v) for k, v in params.items() if v not in (None, "") and not str(k).startswith("_")}
    for bad in ("cursor", "limit", "sort", "order", "folder_id", "slot"):
        params.pop(bad, None)
    if not q and not params:
        raise DriveError("Add at least one word or filter for the folder's rule.")
    from . import query
    try:  # validate now, not at every listing
        query.from_params({**params, "q": q})
    except query.QueryError as exc:
        raise DriveError(f"The rule has a problem: {exc}")
    return json.dumps({"q": q, "params": params, "mode": mode}, ensure_ascii=False), mode


def encode_manifest(data: dict) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, 6) if len(raw) > GZIP_OVER else raw


def decode_manifest(data: bytes) -> dict:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))


def item_key(it: dict) -> str:
    return f"{int(it['chat_id'])}:{int(it['msg_id'])}"


def merge_manifests(local: dict, remote: dict) -> dict:
    """Entity-level merge: newest modification wins; tombstones newer than an entity delete it."""
    tombs: dict[tuple[str, str], int] = {}
    for m in (local, remote):
        for t in m.get("tombstones", []) or []:
            k = (t["kind"], str(t["id"]))
            tombs[k] = max(tombs.get(k, 0), int(t.get("at") or 0))

    def merge(kind: str, key, a: list, b: list) -> list:
        out: dict[str, dict] = {}
        for src in (a or [], b or []):
            for e in src:
                try:
                    k = key(e)
                except (KeyError, TypeError, ValueError):
                    continue
                cur = out.get(k)
                if cur is None or int(e.get("mtime") or 0) > int(cur.get("mtime") or 0):
                    out[k] = e
        return [e for k, e in out.items() if tombs.get((kind, k), -1) < int(e.get("mtime") or 0)
                or (kind, k) not in tombs]

    folders = merge("folder", lambda e: str(e["id"]), local.get("folders"), remote.get("folders"))
    items = merge("item", item_key, local.get("items"), remote.get("items"))
    saved = merge("saved", lambda e: str(e["id"]), local.get("saved"), remote.get("saved"))
    marks = merge("mark", lambda e: str(e["id"]), local.get("marks"), remote.get("marks"))
    cutoff = ms() - TOMBSTONE_DAYS * 86400 * 1000
    return {
        "app": "tgdrive", "version": 2, "updated": int(time.time()),
        "folders": folders, "items": items, "saved": saved, "marks": marks,
        "tombstones": [{"kind": k, "id": i, "at": at} for (k, i), at in tombs.items() if at > cutoff],
    }


class Drive:
    def __init__(self, account: "Account"):
        self.acc = account
        self.loaded = False
        self.error: Optional[str] = None
        self.session_tag = secrets.token_hex(4)
        self._load_lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._dirty = False
        self._last_hash: Optional[str] = None
        self._remote_marker: Optional[tuple] = None
        self._undo: list[tuple[str, dict]] = []
        self.last_saved: Optional[int] = None

    @property
    def db(self):
        return self.acc.db

    @property
    def client(self):
        return self.acc.client

    @property
    def channel_id(self) -> int:
        return int(self.db.get_meta("drive_channel_id") or 0)

    @property
    def manifest_msg_id(self) -> int:
        return int(self.db.get_meta("manifest_msg_id") or 0)

    def info(self) -> dict:
        return {"channel_id": self.channel_id or None, "loaded": self.loaded, "pending_save": self._dirty,
                "error": self.error, "last_saved": self.last_saved,
                "undo": [label for label, _ in self._undo[-5:]][::-1]}

    # ------------------------------------------------------------ manifest io
    def snapshot(self) -> dict:
        return {
            "app": "tgdrive", "version": 2, "updated": int(time.time()), "writer": self.session_tag,
            "folders": [_folder_out(f) for f in self.db.q(f"SELECT {','.join(self.db.FOLDER_COLS)} FROM folders")],
            "items": self.db.all_placements(),
            "saved": self.db.q("SELECT id, name, q, params, icon, created, mtime FROM saved_searches"),
            "marks": [_mark_out(m) for m in self.db.q(f"SELECT {','.join(self.db.MARK_COLS)} FROM marks")],
            "tombstones": self.db.q("SELECT kind, id, at FROM tombstones"),
        }

    def apply(self, manifest: dict) -> None:
        if manifest.get("app") != "tgdrive":
            raise DriveError("That file isn't a TG Drive manifest.")
        folders = [f for f in manifest.get("folders", []) if f.get("id") and f.get("name")]
        ids = {f["id"] for f in folders}
        by_id = {f["id"]: f for f in folders}
        for f in folders:  # drop dangling parents and break cycles rather than lose the folder
            if f.get("parent_id") not in ids:
                f["parent_id"] = None
            seen, cur = {f["id"]}, f.get("parent_id")
            while cur:
                if cur in seen:
                    f["parent_id"] = None
                    break
                seen.add(cur)
                cur = by_id.get(cur, {}).get("parent_id")
        items = []
        for it in manifest.get("items", []):
            try:
                items.append({"chat_id": int(it["chat_id"]), "msg_id": int(it["msg_id"]),
                              "folder_id": it.get("folder_id") if it.get("folder_id") in ids else None,
                              "alias": it.get("alias"), "starred": int(bool(it.get("starred"))),
                              "tags": clean_tags(it.get("tags")) or None, "note": it.get("note") or None,
                              "mtime": int(it.get("mtime") or 0)})
            except (KeyError, TypeError, ValueError):
                continue
        items = [i for i in items if i["folder_id"] or i["alias"] or i["starred"] or i["tags"] or i["note"]]
        saved = [s for s in manifest.get("saved", []) or [] if s.get("id") and s.get("name")]
        marks = None
        if "marks" in manifest:
            marks = []
            for m in manifest.get("marks") or []:
                try:
                    if m.get("id") and int(m["chat_id"]) and int(m["msg_id"]):
                        marks.append(m)
                except (KeyError, TypeError, ValueError):
                    continue
        for f in folders:
            if f.get("emoji") and len(str(f["emoji"])) > 16:
                f["emoji"] = None
        self.db.replace_drive_state(folders, items, saved=saved, tombstones=manifest.get("tombstones") or [],
                                    marks=marks)

    def _backup(self, data: bytes, reason: str) -> None:
        try:
            self.db.x("INSERT INTO manifest_backups(at, reason, data) VALUES(?,?,?)",
                      (int(time.time()), reason, gzip.compress(data) if data[:2] != b"\x1f\x8b" else data))
            self.db.x("DELETE FROM manifest_backups WHERE id NOT IN (SELECT id FROM manifest_backups "
                      "ORDER BY id DESC LIMIT ?)", (MAX_BACKUPS,))
        except Exception:
            log.exception("manifest backup failed")

    def backups(self) -> list[dict]:
        return self.db.q("SELECT id, at, reason, length(data) AS bytes FROM manifest_backups ORDER BY id DESC")

    async def restore_backup(self, backup_id: int) -> None:
        row = self.db.one("SELECT data FROM manifest_backups WHERE id=?", (backup_id,))
        if not row:
            raise DriveError("That backup no longer exists.")
        self.push_undo("Restore backup")
        manifest = decode_manifest(row["data"])
        self._force_local(manifest)
        self._schedule()

    def _force_local(self, manifest: dict) -> None:
        """Make `manifest` the state, stamped now so it wins merges; everything else is tombstoned."""
        now = ms()
        cur = self.snapshot()
        keep_f = {f["id"] for f in manifest.get("folders", [])}
        keep_i = {item_key(i) for i in manifest.get("items", [])}
        keep_s = {s["id"] for s in manifest.get("saved", []) or []}
        keep_m = {m["id"] for m in manifest.get("marks", []) or []}
        tombs = [t for t in manifest.get("tombstones", []) or []]
        tombs += [{"kind": "mark", "id": m["id"], "at": now} for m in cur.get("marks", []) if m["id"] not in keep_m]
        tombs += [{"kind": "folder", "id": f["id"], "at": now} for f in cur["folders"] if f["id"] not in keep_f]
        tombs += [{"kind": "item", "id": item_key(i), "at": now} for i in cur["items"] if item_key(i) not in keep_i]
        tombs += [{"kind": "saved", "id": s["id"], "at": now} for s in cur["saved"] if s["id"] not in keep_s]
        for coll in ("folders", "items", "saved", "marks"):
            for e in manifest.get(coll, []) or []:
                e["mtime"] = now
        self.apply({**manifest, "app": "tgdrive", "tombstones": tombs, "marks": manifest.get("marks") or []})

    async def load(self) -> None:
        async with self._load_lock:
            if self.loaded:
                return
            self.acc.require_online()
            cid = self.channel_id or await self._find_channel()
            if cid:
                self.db.set_meta("drive_channel_id", cid)
                await self._read_manifest(cid)
            self.loaded = True

    async def _find_channel(self) -> int:
        """Look for an existing TG Drive channel created by this account (e.g. on another device)."""
        title = config.DRIVE_CHANNEL_TITLE
        candidates = [r["id"] for r in self.db.q(
            "SELECT id FROM chats WHERE kind='channel' AND is_creator=1 AND title=?", (title,))]
        if not candidates:
            async for d in self.client.iter_dialogs():
                ent = d.entity
                if isinstance(ent, types.Channel) and ent.broadcast and ent.creator and ent.title == title:
                    candidates.append(utils.get_peer_id(ent))
        for cid in candidates:
            if await self._manifest_message(cid):
                return cid
        return candidates[0] if candidates else 0

    async def _manifest_message(self, cid: int):
        peer = await self.acc.peer(cid)
        if self.manifest_msg_id and self.channel_id == cid:
            msg = await self.client.get_messages(peer, ids=self.manifest_msg_id)
            if _is_manifest(msg):
                return msg
        try:
            msg = await self.client.get_messages(peer, ids=types.InputMessagePinned())
            if _is_manifest(msg):
                return msg
        except errors.RPCError:
            pass
        async for msg in self.client.iter_messages(peer, search=MANIFEST_NAME, limit=10,
                                                   filter=types.InputMessagesFilterDocument):
            if _is_manifest(msg):
                return msg
        return None

    @staticmethod
    def _marker(msg) -> tuple:
        doc = msg.media.document
        return (msg.id, doc.id, getattr(msg, "edit_date", None))

    async def _read_manifest(self, cid: int) -> None:
        msg = await self._manifest_message(cid)
        if not msg:
            if self.db.get_meta("drive_seeded") and (self.db.all_placements() or
                                                     self.db.one("SELECT 1 FROM folders LIMIT 1")):
                self._dirty = True  # local state exists but manifest vanished: write it back
                self._schedule()
            return
        data = await self.client.download_media(msg, file=bytes)
        self._merge_remote(data, "Loaded from Telegram")
        self._remote_marker = self._marker(msg)
        self.db.set_meta("manifest_msg_id", msg.id)

    def _merge_remote(self, data: bytes, reason: str) -> bool:
        """Merge a remote manifest into local state. Returns True if local now differs from remote."""
        digest = hashlib.sha1(data).hexdigest()
        if digest == self._last_hash:
            return False
        remote = decode_manifest(data)
        if remote.get("app") != "tgdrive":
            raise DriveError("The pinned manifest isn't a TG Drive manifest.")
        local = self.snapshot()
        self._backup(encode_manifest(local), "Before merging changes from another device")
        seeded = self.db.get_meta("drive_seeded")
        merged = merge_manifests(local, remote) if seeded else {**remote, "tombstones": remote.get("tombstones", [])}
        self.apply(merged)
        self._last_hash = digest
        self.db.set_meta("drive_seeded", 1)
        differs = _norm(merged) != _norm(remote)
        if differs:
            self._schedule()
        return differs

    async def on_message(self, cid: int, msg) -> None:
        """Live hook: another device changed the manifest."""
        if cid != self.channel_id or not _is_manifest(msg):
            return
        try:
            data = await self.client.download_media(msg, file=bytes)
            manifest = decode_manifest(data)
            if manifest.get("writer") == self.session_tag:
                return
            self._merge_remote(data, "Changed on another device")
            self._remote_marker = self._marker(msg)
            self.db.set_meta("manifest_msg_id", msg.id)
            self.db.log_activity("sync", "Folders updated from another device")
        except Exception:
            log.exception("could not apply remote manifest")

    def _schedule(self) -> None:
        self._dirty = True
        if not self._flush_task or self._flush_task.done():
            try:
                self._flush_task = asyncio.get_running_loop().create_task(self._delayed_flush())
            except RuntimeError:
                pass

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(FLUSH_DELAY)
        await self.flush_now()

    async def flush_now(self) -> None:
        async with self._flush_lock:
            if not self._dirty or self.acc.status != "online":
                return
            self._dirty = False
            try:
                peer = await self.ensure_channel()
                # Someone else may have written since we last looked: merge first.
                if self.manifest_msg_id:
                    try:
                        msg = await self.client.get_messages(peer, ids=self.manifest_msg_id)
                        if _is_manifest(msg) and self._marker(msg) != self._remote_marker:
                            remote = await self.client.download_media(msg, file=bytes)
                            self._merge_remote(remote, "Changed on another device")
                            self._remote_marker = self._marker(msg)
                            self._dirty = False
                    except errors.RPCError:
                        pass
                data = encode_manifest(self.snapshot())
                await self._write_manifest(peer, data)
                self._last_hash = hashlib.sha1(data).hexdigest()
                self.db.set_meta("drive_seeded", 1)
                self.error = None
                self.last_saved = int(time.time())
            except Exception as exc:
                log.exception("saving manifest failed")
                self.error = f"Couldn't save folders to Telegram ({exc}). Retrying."
                self._dirty = True
                asyncio.get_running_loop().call_later(30, self._schedule)

    async def _write_manifest(self, peer, data: bytes) -> None:
        def as_file():
            f = io.BytesIO(data)
            f.name = MANIFEST_NAME
            return f

        attrs = [types.DocumentAttributeFilename(MANIFEST_NAME)]
        old = self.manifest_msg_id
        if old:
            try:
                msg = await self.client.edit_message(peer, old, file=as_file(), attributes=attrs,
                                                     force_document=True)
                if msg is not None and _is_manifest(msg):
                    self._remote_marker = self._marker(msg)
                return
            except errors.MessageNotModifiedError:
                return
            except (errors.MessageIdInvalidError, errors.MessageEditTimeExpiredError):
                pass
        msg = await self.client.send_file(peer, as_file(), attributes=attrs, force_document=True,
                                          caption="TG Drive folders. Keep this pinned.")
        await self.client.pin_message(peer, msg, notify=False)
        self.db.set_meta("manifest_msg_id", msg.id)
        if _is_manifest(msg):
            self._remote_marker = self._marker(msg)
        if old:
            try:
                await self.client.delete_messages(peer, [old])
            except errors.RPCError:
                pass

    async def ensure_channel(self):
        await self.load()
        cid = self.channel_id
        if cid:
            return await self.acc.peer(cid)
        from .indexer import chat_row
        res = await self.client(functions.channels.CreateChannelRequest(
            title=config.DRIVE_CHANNEL_TITLE, about=ABOUT, broadcast=True))
        ch = next(c for c in res.chats if isinstance(c, types.Channel))
        row = chat_row(ch)
        self.db.upsert_chat(row)
        self.db.set_meta("drive_channel_id", row["id"])
        self.db.log_activity("drive", "Created the TG Drive channel")
        return await self.acc.peer(row["id"])

    def export(self) -> dict:
        return self.snapshot()

    async def import_manifest(self, manifest: dict, mode: str = "merge") -> None:
        await self.load()
        if manifest.get("app") != "tgdrive":
            raise DriveError("That file isn't a TG Drive manifest.")
        self.push_undo("Import folders")
        if mode == "replace":
            self._force_local(manifest)
        else:
            now = ms()
            for coll in ("folders", "items", "saved", "marks"):
                for e in manifest.get(coll, []) or []:
                    e.setdefault("mtime", now)
            self.apply(merge_manifests(self.snapshot(), manifest))
        self._schedule()

    # ------------------------------------------------------------------- undo
    def push_undo(self, label: str) -> None:
        self._undo.append((label, self.snapshot()))
        del self._undo[:-20]

    async def undo(self) -> str:
        if not self._undo:
            raise DriveError("Nothing to undo.")
        label, snap = self._undo.pop()
        snap = {**snap, "marks": self.snapshot()["marks"]}  # highlights aren't part of folder undo
        self._force_local(snap)
        self._schedule()
        self.db.log_activity("undo", label)
        return label

    # ---------------------------------------------------------------- folders
    def folders(self) -> list[dict]:
        return self.db.list_folders()

    def path(self, folder_id: Optional[str]) -> list[dict]:
        out, seen = [], set()
        while folder_id and folder_id not in seen:
            seen.add(folder_id)
            f = self.db.get_folder(folder_id)
            if not f:
                break
            out.append({"id": f["id"], "name": f["name"]})
            folder_id = f["parent_id"]
        return list(reversed(out))

    def _descendants(self, folder_id: str) -> set[str]:
        children: dict[Optional[str], list[str]] = {}
        for f in self.db.q("SELECT id, parent_id FROM folders"):
            children.setdefault(f["parent_id"], []).append(f["id"])
        out, stack = set(), [folder_id]
        while stack:
            cur = stack.pop()
            for c in children.get(cur, []):
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    def _check_unique(self, name: str, parent_id: Optional[str], exclude: Optional[str] = None) -> None:
        clash = self.db.one(
            "SELECT id FROM folders WHERE parent_id IS ? AND name=? COLLATE NOCASE AND id IS NOT ?",
            (parent_id, name, exclude))
        if clash:
            raise DriveError(f"There's already a folder called “{name}” here.")

    def _require_folder(self, folder_id: Optional[str]) -> None:
        if folder_id and not self.db.get_folder(folder_id):
            raise DriveError("That folder no longer exists.")

    async def create_folder(self, name: str, parent_id: Optional[str], color: str = "",
                            description: str = "", emoji: str = "", rules: Optional[dict] = None) -> dict:
        await self.load()
        name = clean_name(name)
        self._require_folder(parent_id)
        self._check_unique(name, parent_id)
        if color not in COLORS:
            raise DriveError("Unknown colour.")
        rules_json, kind = clean_rules(rules)
        self.push_undo(f"Create folder “{name}”")
        fid = secrets.token_hex(6)
        self.db.x("INSERT INTO folders(id, parent_id, name, created, color, description, mtime, emoji, rules, kind) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (fid, parent_id or None, name, int(time.time()), color or None, description or None, ms(),
                   clean_emoji(emoji), rules_json, kind))
        self._schedule()
        self.db.log_activity("folder", f"Created “{name}”")
        return {"id": fid, "parent_id": parent_id or None, "name": name, "kind": kind, "color": color or None,
                "description": description or None, "emoji": clean_emoji(emoji), "rules": rules_json}

    async def ensure_path(self, parent_id: Optional[str], names: list[str]) -> Optional[str]:
        """Find or create nested folders parent/names[0]/names[1]/… (used by folder uploads)."""
        await self.load()
        cur = parent_id
        for raw in names:
            name = clean_name(raw)
            row = self.db.one("SELECT id FROM folders WHERE parent_id IS ? AND name=? COLLATE NOCASE", (cur, name))
            if row:
                cur = row["id"]
            else:
                fid = secrets.token_hex(6)
                self.db.x("INSERT INTO folders(id, parent_id, name, created, mtime) VALUES(?,?,?,?,?)",
                          (fid, cur, name, int(time.time()), ms()))
                cur = fid
        self._schedule()
        return cur

    async def update_folder(self, folder_id: str, name: Optional[str] = None,
                            parent_id: Optional[str] = "__keep__", color: Optional[str] = None,
                            description: Optional[str] = None, emoji: Optional[str] = None,
                            cover: Optional[str] = None, rules: Optional[object] = "__keep__") -> None:
        await self.load()
        f = self.db.get_folder(folder_id)
        if not f:
            raise DriveError("That folder no longer exists.")
        new_name = clean_name(name) if name is not None else f["name"]
        new_parent = f["parent_id"] if parent_id == "__keep__" else (parent_id or None)
        if new_parent:
            self._require_folder(new_parent)
            if new_parent == folder_id or new_parent in self._descendants(folder_id):
                raise DriveError("A folder can't go inside itself.")
        self._check_unique(new_name, new_parent, exclude=folder_id)
        if color is not None and color not in COLORS:
            raise DriveError("Unknown colour.")
        if cover is not None and cover and cover != "none" and not re.fullmatch(r"-?\d+:\d+", cover):
            raise DriveError("A cover is a file (chat:message).")
        if rules == "__keep__":
            rules_json, kind = f.get("rules"), f.get("kind")
        else:
            rules_json, kind = clean_rules(rules)  # type: ignore[arg-type]
        self.push_undo(f"Change folder “{f['name']}”")
        self.db.x("UPDATE folders SET name=?, parent_id=?, color=?, description=?, emoji=?, cover=?, rules=?, kind=?, "
                  "mtime=? WHERE id=?",
                  (new_name, new_parent, (color if color is not None else f.get("color")) or None,
                   (description if description is not None else f.get("description")) or None,
                   clean_emoji(emoji) if emoji is not None else f.get("emoji"),
                   (cover if cover is not None else f.get("cover")) or None, rules_json, kind, ms(), folder_id))
        self._schedule()

    async def delete_folder(self, folder_id: str) -> int:
        """Delete a folder and its subfolders. Files inside go back to 'not in a folder'."""
        await self.load()
        f = self.db.get_folder(folder_id)
        if not f:
            raise DriveError("That folder no longer exists.")
        self.push_undo(f"Delete folder “{f['name']}”")
        ids = [folder_id, *self._descendants(folder_id)]
        marks = ",".join("?" * len(ids))
        now = ms()
        with self.db.tx():
            n = self.db.x(f"UPDATE placements SET folder_id=NULL, mtime=? WHERE folder_id IN ({marks})",
                          [now, *ids]).rowcount
            gone = self.db.q("SELECT chat_id, msg_id FROM placements WHERE folder_id IS NULL AND alias IS NULL "
                             "AND COALESCE(starred,0)=0 AND tags IS NULL AND note IS NULL")
            self.db.x("DELETE FROM placements WHERE folder_id IS NULL AND alias IS NULL AND COALESCE(starred,0)=0 "
                      "AND tags IS NULL AND note IS NULL")
            self.db.conn.executemany("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('item', ?, ?)",
                                     [(f"{g['chat_id']}:{g['msg_id']}", now) for g in gone])
            self.db.x(f"DELETE FROM folders WHERE id IN ({marks})", ids)
            self.db.conn.executemany("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('folder', ?, ?)",
                                     [(i, now) for i in ids])
        self._schedule()
        self.db.log_activity("folder", f"Deleted “{f['name']}”")
        return n

    # ------------------------------------------------------------------ items
    async def place(self, items: list[tuple[int, int]], folder_id: Optional[str], undo: bool = True) -> None:
        await self.load()
        self._require_folder(folder_id)
        if undo:
            self.push_undo("Move files" if folder_id else "Take files out of folders")
        with self.db.tx():
            for chat_id, msg_id in items:
                self.db.set_placement(int(chat_id), int(msg_id), folder_id or None)
        self._schedule()

    async def rename_file(self, chat_id: int, msg_id: int, name: str) -> None:
        await self.load()
        name = (name or "").strip()
        f = self.db.get_file(chat_id, msg_id)
        if not f:
            raise DriveError("That file isn't in the index.")
        alias = clean_name(name) if name and name != f["name"] else None
        self.push_undo("Rename file")
        self.db.set_placement(chat_id, msg_id, alias=alias, keep_alias=False, keep_folder=True)
        self._schedule()
        for part in ("semantic", "subjects"):
            obj = getattr(self.acc, part, None)
            if obj and f.get("id"):
                obj.poke(f["id"])

    async def bulk_rename(self, items: list[tuple[int, int]], pattern: str, start: int = 1) -> int:
        """Rename with a pattern: {name} {ext} {n} {n:03} {date} {chat}."""
        await self.load()
        if not pattern or "{" not in pattern and len(items) > 1:
            raise DriveError("Use a pattern with {n} or {name} so the names differ, e.g. “Lecture {n:02}”.")
        self.push_undo(f"Rename {len(items)} files")
        n = 0
        for i, (cid, mid) in enumerate(items):
            f = self.db.get_file(cid, mid)
            if not f:
                continue
            stem, dot, ext = (f.get("alias") or f["name"] or "").rpartition(".")
            if not dot:
                stem, ext = ext, ""
            try:
                new = pattern.format(name=stem, ext=ext, n=start + i, date=time.strftime(
                    "%Y-%m-%d", time.localtime(f.get("date") or 0)), chat=f.get("chat_title") or "")
            except (KeyError, IndexError, ValueError) as exc:
                raise DriveError(f"The pattern has a problem: {exc}")
            if ext and not new.lower().endswith("." + ext.lower()):
                new = f"{new}.{ext}"
            alias = clean_name(new)
            self.db.set_placement(cid, mid, alias=None if alias == f["name"] else alias, keep_alias=False,
                                  keep_folder=True)
            n += 1
        self._schedule()
        return n

    async def set_meta_items(self, items: list[tuple[int, int]], starred: Optional[bool] = None,
                             tags_add: Optional[list[str]] = None, tags_remove: Optional[list[str]] = None,
                             tags_set: Optional[list[str]] = None, note: Optional[str] = None) -> None:
        await self.load()
        self.push_undo("Star" if starred else "Unstar" if starred is False else "Edit tags" if
                       (tags_add or tags_remove or tags_set is not None) else "Edit note")
        with self.db.tx():
            for cid, mid in items:
                cur = self.db.get_placement(cid, mid)
                tags = None
                if tags_set is not None or tags_add or tags_remove:
                    existing = [t for t in (cur.get("tags") or "").split(",") if t]
                    base = list(tags_set) if tags_set is not None else existing
                    base += [t for t in (tags_add or [])]
                    rm = {t.strip().lower() for t in (tags_remove or [])}
                    tags = clean_tags([t for t in base if t.strip().lower() not in rm]) or ""
                self.db.set_placement(cid, mid, keep_alias=True, keep_folder=True,
                                      starred=starred, tags=tags,
                                      note=(note.strip()[:2000] if note is not None else None))
        self._schedule()

    def all_tags(self) -> list[dict]:
        counts: dict[str, int] = {}
        for r in self.db.q("SELECT tags FROM placements WHERE tags IS NOT NULL AND tags<>''"):
            for t in r["tags"].split(","):
                if t:
                    counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "n": n} for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    # --------------------------------------------------------- saved searches
    async def save_search(self, name: str, q: str, params: dict, icon: str = "",
                          search_id: Optional[str] = None) -> dict:
        await self.load()
        name = clean_name(name)
        sid = search_id or secrets.token_hex(5)
        self.db.x("INSERT INTO saved_searches(id, name, q, params, icon, created, mtime) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET name=excluded.name, q=excluded.q, params=excluded.params, "
                  "icon=excluded.icon, mtime=excluded.mtime",
                  (sid, name, q or "", json.dumps(params or {}), icon or None, int(time.time()), ms()))
        self.db.x("DELETE FROM tombstones WHERE kind='saved' AND id=?", (sid,))
        self._schedule()
        return {"id": sid, "name": name}

    async def delete_search(self, search_id: str) -> None:
        await self.load()
        self.push_undo("Delete saved search")
        self.db.x("DELETE FROM saved_searches WHERE id=?", (search_id,))
        self.db.x("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('saved', ?, ?)", (search_id, ms()))
        self._schedule()

    def saved_searches(self) -> list[dict]:
        rows = self.db.q("SELECT id, name, q, params, icon FROM saved_searches ORDER BY name COLLATE NOCASE")
        for r in rows:
            try:
                r["params"] = json.loads(r["params"] or "{}")
            except ValueError:
                r["params"] = {}
        return rows

    # ------------------------------------------------------- PDF marks
    MARK_KINDS = {"bookmark", "highlight", "note"}

    def marks_for(self, chat_id: int, msg_id: int) -> list[dict]:
        return [_mark_out(m) for m in self.db.q(
            f"SELECT {','.join(self.db.MARK_COLS)} FROM marks WHERE chat_id=? AND msg_id=? ORDER BY page, created",
            (chat_id, msg_id))]

    async def save_mark(self, chat_id: int, msg_id: int, mark: dict) -> dict:
        kind = mark.get("kind") or "highlight"
        if kind not in self.MARK_KINDS:
            raise DriveError("Unknown mark type.")
        try:
            page = max(1, int(mark.get("page") or 1))
        except (TypeError, ValueError):
            raise DriveError("page must be a number.")
        data = mark.get("data")
        raw = json.dumps(data, ensure_ascii=False) if data is not None else None
        if raw and len(raw) > 20000:
            raise DriveError("That highlight is too long.")
        mid = str(mark.get("id") or secrets.token_hex(6))[:32]
        note = (str(mark.get("note") or "")[:4000]) or None
        color = (str(mark.get("color") or "")[:20]) or None
        cur = self.db.one("SELECT created FROM marks WHERE id=?", (mid,))
        self.db.x(f"INSERT OR REPLACE INTO marks({','.join(self.db.MARK_COLS)}) VALUES({','.join('?' * 10)})",
                  (mid, chat_id, msg_id, kind, page, raw, color, note, (cur or {}).get("created") or int(time.time()),
                   ms()))
        self.db.x("DELETE FROM tombstones WHERE kind='mark' AND id=?", (mid,))
        self._schedule()
        return _mark_out(self.db.one(f"SELECT {','.join(self.db.MARK_COLS)} FROM marks WHERE id=?", (mid,)))

    async def delete_mark(self, mark_id: str) -> None:
        self.db.x("DELETE FROM marks WHERE id=?", (mark_id,))
        self.db.x("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('mark', ?, ?)", (mark_id, ms()))
        self._schedule()

    # ------------------------------------------------------------ copy / send
    async def copy_to_drive(self, chat_id: int, msg_id: int, folder_id: Optional[str]) -> dict:
        """Re-send a file into the Drive channel (no re-upload) so you own a copy."""
        from .accounts import AccountError
        self._require_folder(folder_id)
        chat = self.db.get_chat(chat_id)
        if chat and chat["noforwards"]:
            raise AccountError("This chat restricts saving content, so Telegram won't allow a copy.")
        peer = await self.ensure_channel()
        msg = await self.acc.get_message(chat_id, msg_id)
        try:
            new = await self.client.send_file(peer, msg.media, caption=msg.message or "")
        except errors.ChatForwardsRestrictedError:
            raise AccountError("This chat restricts saving content, so Telegram won't allow a copy.")
        drive_chat = self.db.get_chat(self.channel_id)
        title = drive_chat["title"] if drive_chat else config.DRIVE_CHANNEL_TITLE
        rec = self.acc.indexer.record(new, self.channel_id, title)
        if rec:
            self.db.upsert_files([rec])
            self.db.refresh_file_count(self.channel_id)
        old = self.db.get_placement(chat_id, msg_id)
        alias = old.get("alias")
        if folder_id or alias or old.get("tags") or old.get("starred"):
            self.db.set_placement(self.channel_id, new.id, folder_id or None, alias=alias,
                                  tags=old.get("tags"), starred=old.get("starred"), note=old.get("note"))
            self._schedule()
        self.db.log_activity("copy", f"Saved a copy of {rec['name'] if rec else msg_id} to Drive")
        return {"chat_id": self.channel_id, "msg_id": new.id}

    async def send_to(self, items: list[tuple[int, int]], target_chat: int, mode: str = "copy") -> dict:
        """Send files to another chat: 'copy' (no 'forwarded from' header) or 'forward'."""
        from .accounts import AccountError
        target = await self.acc.peer(target_chat)
        sent, failed = 0, []
        by_chat: dict[int, list[int]] = {}
        for cid, mid in items:
            by_chat.setdefault(cid, []).append(mid)
        for cid, mids in by_chat.items():
            try:
                chat = self.db.get_chat(cid)
                if chat and chat["noforwards"]:
                    raise AccountError(f"“{chat['title']}” restricts forwarding.")
                if mode == "forward":
                    src = await self.acc.peer(cid)
                    await self.client.forward_messages(target, mids, src)
                    sent += len(mids)
                else:
                    for mid in mids:
                        msg = await self.acc.get_message(cid, mid)
                        await self.client.send_file(target, msg.media, caption=msg.message or "")
                        sent += 1
            except (AccountError, errors.RPCError) as exc:
                failed.append(str(exc))
        tchat = self.db.get_chat(target_chat)
        self.db.log_activity("send", f"Sent {sent} files to {tchat['title'] if tchat else target_chat}")
        return {"sent": sent, "failed": failed}


def _norm(m: dict) -> str:
    def key(coll, e):
        return json.dumps(e, sort_keys=True, default=str)
    return json.dumps({c: sorted(key(c, e) for e in m.get(c, []) or []) for c in ("folders", "items", "saved", "marks")})


def _folder_out(f: dict) -> dict:
    out = {k: v for k, v in f.items() if v is not None or k in ("parent_id",)}
    if isinstance(out.get("rules"), str):
        try:
            out["rules"] = json.loads(out["rules"])
        except ValueError:
            out.pop("rules", None)
    return out


def _mark_out(m: dict) -> dict:
    out = {k: v for k, v in m.items() if v is not None}
    if isinstance(out.get("data"), str):
        try:
            out["data"] = json.loads(out["data"])
        except ValueError:
            pass
    return out
