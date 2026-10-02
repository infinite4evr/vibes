"""Indexes every file in every chat, then keeps the index current.

Per chat and per Telegram search filter we keep a window (oldest_id, newest_id]
that is known to be indexed:

* backfill walks from newest to oldest and saves oldest_id every page, so a
  restart resumes where it stopped;
* incremental catch-up scans ids above newest_id when the dialog list shows the
  chat has newer messages (e.g. after the app was offline);
* live updates index new, edited and deleted messages as they happen and
  advance newest_id when there is no known gap;
* a slow background check re-reads indexed message ids in batches of 100 and
  drops files that were deleted while TG Drive was not running.

messages.getSearchCounters tells us up front which filters have any files at
all, so empty chats cost one request. Settings decide which file types and
which kinds of chats are indexed.
"""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

from telethon import errors, events, utils
from telethon.tl import functions, types

from . import config
from .tasks import spawn
from .extract import extract
from .settings import settings

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.indexer")

FILTERS = {
    "media": types.InputMessagesFilterPhotoVideo,
    "document": types.InputMessagesFilterDocument,
    "music": types.InputMessagesFilterMusic,
    "roundvoice": types.InputMessagesFilterRoundVoice,
    "gif": types.InputMessagesFilterGif,
}
FILTER_KINDS = {
    "media": {"photo", "video"},
    "document": {"document", "photo"},  # images sent as files are "photo" kind
    "music": {"audio"},
    "roundvoice": {"voice", "round"},
    "gif": {"gif"},
}

PAGE = 100
VERIFY_BATCH = 100

SKIP_ERRORS = (
    errors.ChannelPrivateError, errors.ChatAdminRequiredError, errors.ChannelInvalidError,
    errors.UserBannedInChannelError, errors.ChatForbiddenError,
)


def chat_row(entity) -> dict:
    cid = utils.get_peer_id(entity)
    if isinstance(entity, types.User):
        if entity.is_self:
            kind, title = "saved", "Saved Messages"
        else:
            kind = "bot" if entity.bot else "user"
            title = utils.get_display_name(entity) or ("Deleted account" if entity.deleted else str(entity.id))
    elif isinstance(entity, (types.Chat, types.ChatForbidden)):
        kind, title = "group", entity.title
    elif isinstance(entity, (types.Channel, types.ChannelForbidden)):
        kind = "channel" if getattr(entity, "broadcast", False) else "supergroup"
        title = entity.title
    else:
        kind, title = "group", utils.get_display_name(entity) or str(cid)
    username = getattr(entity, "username", None)
    if not username:
        for u in getattr(entity, "usernames", None) or []:
            if getattr(u, "active", False):
                username = u.username
                break
    return {
        "id": cid,
        "title": title or str(cid),
        "kind": kind,
        "username": username,
        "is_creator": int(bool(getattr(entity, "creator", False))),
        "is_admin": int(bool(getattr(entity, "creator", False) or getattr(entity, "admin_rights", None))),
        "noforwards": int(bool(getattr(entity, "noforwards", False))),
        "latest_msg_id": 0,
        "is_forum": int(bool(getattr(entity, "forum", False))),
        "members": getattr(entity, "participants_count", None),
    }


def wanted_filters() -> dict[str, type]:
    kinds = set(settings.get("index_kinds") or [])
    return {name: cls for name, cls in FILTERS.items() if FILTER_KINDS[name] & kinds}


class Indexer:
    def __init__(self, account: "Account"):
        self.acc = account
        self.task: Optional[asyncio.Task] = None
        self.verify_task: Optional[asyncio.Task] = None
        self._run_gate = asyncio.Event()
        self._run_gate.set()
        self._wake = asyncio.Event()
        self.paused = False
        self.phase = "idle"
        self.current_title: Optional[str] = None
        self.current_chat: Optional[int] = None
        self.last_sync = 0.0
        self.error: Optional[str] = None
        self._handlers = False
        self.rate: list[tuple[float, int]] = []   # (time, files indexed so far) samples
        self.indexed_this_run = 0
        self.verify_state = {"checked": 0, "removed": 0, "chat": None}
        if settings.get("index_paused"):
            self.pause()

    @property
    def db(self):
        return self.acc.db

    @property
    def client(self):
        return self.acc.client

    # ---------------------------------------------------------------- control
    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = spawn(self._loop(), "indexer")
        if not self.verify_task or self.verify_task.done():
            self.verify_task = spawn(self._verify_loop(), "verify deleted files")

    async def stop(self) -> None:
        for task in (self.task, self.verify_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    def pause(self) -> None:
        self.paused = True
        self._run_gate.clear()

    def resume(self) -> None:
        self.paused = False
        self._run_gate.set()
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def _sample(self) -> None:
        now = time.time()
        self.rate.append((now, self.indexed_this_run))
        self.rate = [r for r in self.rate if now - r[0] < 300][-60:]

    def speed(self) -> float:
        """Files per minute over the last few minutes."""
        if len(self.rate) < 2:
            return 0.0
        (t0, n0), (t1, n1) = self.rate[0], self.rate[-1]
        return (n1 - n0) / max(1e-6, (t1 - t0)) * 60

    def status(self) -> dict:
        counts = {r["index_state"]: r["n"] for r in self.db.q(
            "SELECT index_state, COUNT(*) AS n FROM chats WHERE excluded=0 GROUP BY index_state")}
        totals = self.db.totals()
        return {
            "phase": "paused" if self.paused else self.phase,
            "current": self.current_title,
            "current_chat": self.current_chat,
            "chats_total": sum(counts.values()),
            "chats_done": counts.get("done", 0) + counts.get("gone", 0),
            "chats_error": counts.get("error", 0),
            "chats_pending": counts.get("pending", 0) + counts.get("running", 0),
            "files": totals["files"],
            "bytes": totals["bytes"],
            "files_per_min": round(self.speed()),
            "last_sync": int(self.last_sync) or None,
            "verify": self.verify_state,
            "error": self.error,
        }

    # ------------------------------------------------------------------- loop
    async def _loop(self) -> None:
        while True:
            try:
                await self._run_gate.wait()
                self.phase = "syncing chats"
                await self.sync_dialogs()
                await self.sync_dialog_filters()
                if not self.acc.drive.loaded:
                    try:
                        await self.acc.drive.load()
                    except Exception as exc:
                        log.warning("loading drive manifest failed: %s", exc)
                        self.acc.drive.error = f"Couldn't load folders: {exc}"
                if self.acc.drive.loaded:
                    self.acc.drive.resume_pending()
                attempted: set[int] = set()
                skip_kinds = set(settings.get("index_skip_kinds_of_chat") or [])
                while True:
                    todo = [c for c in self.db.chats_needing_index()
                            if c["id"] not in attempted and c["kind"] not in skip_kinds]
                    if not todo:
                        break
                    for chat in todo:
                        await self._run_gate.wait()
                        attempted.add(chat["id"])
                        fresh = self.db.get_chat(chat["id"])
                        if fresh and not fresh["excluded"]:
                            await self.index_chat(fresh)
                self.phase, self.current_title, self.current_chat, self.error = "idle", None, None, None
                for part in ("autofile", "subjects"):
                    obj = getattr(self.acc, part, None)
                    if obj is not None:
                        obj.poke()
                self._wake.clear()
                interval = max(300, int(settings.get("resync_minutes") or 30) * 60)
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=min(interval, config.RESYNC_INTERVAL))
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("indexer loop failed")
                self.error = f"Indexing stopped: {exc}. Retrying in 30s."
                self.phase = "error"
                await asyncio.sleep(30)

    async def sync_dialogs(self) -> None:
        started = int(time.time())
        rows = []
        async for d in self.client.iter_dialogs():
            row = chat_row(d.entity)
            row["latest_msg_id"] = d.message.id if d.message else 0
            row["archived"] = int(getattr(d, "archived", False) or getattr(d, "folder_id", None) == 1)
            if row["kind"] == "saved":
                row["title"] = "Saved Messages"
            rows.append(row)
        await self.db.write(self.db.sync_chats, rows, started)
        self.acc._dialogs_loaded = True
        self.last_sync = time.time()
        forums = [row["id"] for row in rows if row.get("is_forum")]
        if forums:
            spawn(self._sync_all_topics(forums), "sync forum topics")

    async def sync_dialog_filters(self) -> None:
        """Mirror the user's Telegram chat folders (Personal, Work, …) as sources."""
        try:
            res = await self.client(functions.messages.GetDialogFiltersRequest())
        except (errors.RPCError, NotImplementedError, AttributeError, TypeError):
            return
        filters = getattr(res, "filters", res) or []
        chats = self.db.q("SELECT id, kind, archived FROM chats")
        out = []
        for pos, flt in enumerate(filters):
            if not isinstance(flt, (types.DialogFilter, getattr(types, "DialogFilterChatlist", types.DialogFilter))):
                continue
            title = flt.title
            title = getattr(title, "text", title)
            include = {utils.get_peer_id(p) for p in (flt.include_peers or []) + (flt.pinned_peers or [])
                       if not isinstance(p, types.InputPeerEmpty)}
            exclude = {utils.get_peer_id(p) for p in (getattr(flt, "exclude_peers", None) or [])}
            for c in chats:
                k = c["kind"]
                if ((getattr(flt, "contacts", False) or getattr(flt, "non_contacts", False)) and k == "user") or \
                        (getattr(flt, "groups", False) and k in ("group", "supergroup")) or \
                        (getattr(flt, "broadcasts", False) and k == "channel") or \
                        (getattr(flt, "bots", False) and k == "bot"):
                    if getattr(flt, "exclude_archived", False) and c["archived"]:
                        continue
                    include.add(c["id"])
            ids = sorted(include - exclude)
            out.append((flt.id, str(title), getattr(flt, "emoticon", None), pos, json.dumps(ids)))
        with self.db.tx():
            self.db.x("DELETE FROM dialog_filters")
            self.db.conn.executemany(
                "INSERT INTO dialog_filters(id, title, emoticon, position, chat_ids) VALUES(?,?,?,?,?)", out)

    async def _sync_all_topics(self, ids: list[int]) -> None:
        # A few at a time: hundreds of forums at once would only earn flood waits.
        sem = asyncio.Semaphore(3)

        async def one(cid: int) -> None:
            async with sem:
                await self._sync_topics(cid)
        await asyncio.gather(*(one(c) for c in ids))

    async def _sync_topics(self, cid: int) -> None:
        try:
            peer = await self.acc.peer(cid)
            res = await self.client(functions.channels.GetForumTopicsRequest(
                channel=peer, offset_date=None, offset_id=0, offset_topic=0, limit=100))
            rows = [(cid, t.id, t.title, getattr(t, "icon_color", None)) for t in res.topics
                    if isinstance(t, types.ForumTopic)]
            with self.db.tx():
                self.db.x("DELETE FROM topics WHERE chat_id=?", (cid,))
                self.db.conn.executemany("INSERT OR REPLACE INTO topics(chat_id, topic_id, title, icon_color) "
                                         "VALUES(?,?,?,?)", rows)
        except Exception as exc:
            log.debug("topics for %s: %s", cid, exc)

    # ---------------------------------------------------------------- per chat
    async def _counters(self, peer, filters: dict) -> Optional[dict]:
        try:
            res = await self.client(functions.messages.GetSearchCountersRequest(
                peer=peer, filters=[cls() for cls in filters.values()]))
        except errors.FloodWaitError:
            raise
        except errors.RPCError:
            return None
        out = {}
        for sc in res:
            for name, cls in filters.items():
                if isinstance(sc.filter, cls):
                    out[name] = sc.count
        return out

    async def index_chat(self, chat: dict) -> None:
        cid = chat["id"]
        self.current_title = chat["title"]
        self.current_chat = cid
        self.phase = "indexing"
        self.db.set_chat_state(cid, "running")
        filters = wanted_filters()
        t0 = time.time()
        log.debug("indexing chat %s %r (%s, latest msg %s, kinds %s)", cid, chat["title"], chat.get("kind"),
                  chat.get("latest_msg_id"), ",".join(filters))
        try:
            peer = await self.acc.peer(cid)
            counts = await self._counters(peer, filters)
            latest = chat["latest_msg_id"]
            for name, cls in filters.items():
                prog = self.db.get_progress(cid, name)
                if counts is not None and counts.get(name, 1) == 0:
                    self.db.set_progress(cid, name, newest_id=max(prog["newest_id"], latest),
                                         oldest_id=0, done=1)
                    continue
                if prog["newest_id"] and latest > prog["newest_id"]:
                    top = await self._scan(peer, chat, cls, min_id=prog["newest_id"])
                    self.db.set_progress(cid, name, newest_id=max(latest, top))
                if not prog["done"]:
                    if not prog["newest_id"]:
                        self.db.set_progress(cid, name, newest_id=latest)
                    await self._scan(peer, chat, cls, offset_id=prog["oldest_id"], backfill=name)
                    self.db.set_progress(cid, name, done=1)
            self.db.refresh_file_count(cid)
            self.db.set_chat_state(cid, "done")
            log.debug("indexed chat %s %r in %.1f s (counters %s)", cid, chat["title"], time.time() - t0, counts)
        except asyncio.CancelledError:
            self.db.refresh_file_count(cid)
            raise
        except errors.FloodWaitError as exc:
            log.info("indexing %s: Telegram asks to wait %d s", cid, exc.seconds)
            self.db.set_chat_state(cid, "pending")
            self.phase = f"rate limited by Telegram, waiting {exc.seconds}s"
            await asyncio.sleep(exc.seconds + 1)
        except SKIP_ERRORS as exc:
            log.debug("indexing %s skipped: no access (%s)", cid, exc.__class__.__name__)
            self.db.set_chat_state(cid, "error", f"No access: {exc.__class__.__name__}")
        except Exception as exc:
            log.warning("indexing %s failed: %s", chat["title"], exc)
            log.debug("indexing %s traceback", cid, exc_info=exc)
            self.db.set_chat_state(cid, "error", str(exc)[:300])
        finally:
            self.db.refresh_file_count(cid)
            self.current_title = None
            self.current_chat = None

    async def _scan(self, peer, chat: dict, filter_cls, min_id: int = 0, offset_id: int = 0,
                    backfill: Optional[str] = None) -> int:
        """Iterate one filter newest→oldest. Returns the highest message id seen."""
        cid = chat["id"]
        kinds = set(settings.get("index_kinds") or [])
        top, low, seen, batch = 0, None, 0, []
        wait = float(settings.get("index_wait") or 0.5)
        async for msg in self.client.iter_messages(peer, filter=filter_cls, min_id=min_id,
                                                   offset_id=offset_id, wait_time=wait):
            top = max(top, msg.id)
            low = msg.id
            seen += 1
            rec = self.record(msg, cid, chat["title"])
            if rec and rec["kind"] in kinds:
                batch.append(rec)
            if seen % PAGE == 0:
                # Files, progress and counts in one transaction, on the writer thread (never blocks the loop).
                await self.db.write(self.db.index_page, batch, cid,
                                    (backfill, {"oldest_id": low}) if backfill else None)
                self.indexed_this_run += len(batch)
                self._sample()
                batch = []
                await self._run_gate.wait()
        await self.db.write(self.db.index_page, batch, cid,
                            (backfill, {"oldest_id": low}) if backfill and low else None)
        self.indexed_this_run += len(batch)
        return top

    def record(self, msg, cid: int, chat_title: str) -> Optional[dict]:
        sender = getattr(msg, "sender", None)
        sender_name = utils.get_display_name(sender) if sender else ""
        rec = extract(msg, cid, chat_title, sender_name)
        if rec and msg.fwd_from and not rec["fwd_from"]:
            try:
                fwd = msg.forward
                ent = fwd.sender or fwd.chat
                rec["fwd_from"] = utils.get_display_name(ent) if ent else None
            except Exception:
                pass
        if rec and not settings.get("save_inline_previews", True):
            rec["stripped"] = None
        return rec

    # ------------------------------------------------------------- verifier
    async def _verify_loop(self) -> None:
        """Drop files whose messages were deleted while TG Drive wasn't running."""
        await asyncio.sleep(120)
        while True:
            try:
                per_hour = int(settings.get("verify_per_hour") or 0)
                if not settings.get("verify_deleted", True) or per_hour <= 0 or self.paused:
                    await asyncio.sleep(300)
                    continue
                if self.phase not in ("idle",) or self.acc.status != "online":
                    await asyncio.sleep(60)
                    continue
                did = await self.verify_step()
                pause = 3600 / max(1, per_hour / VERIFY_BATCH)
                await asyncio.sleep(pause if did else 900)
            except asyncio.CancelledError:
                raise
            except errors.FloodWaitError as exc:
                await asyncio.sleep(exc.seconds + 5)
            except Exception:
                log.exception("verify step failed")
                await asyncio.sleep(300)

    async def verify_step(self) -> bool:
        chat = self.db.one(
            "SELECT c.id, c.title, c.verified_until FROM chats c WHERE c.excluded=0 AND c.file_count>0 "
            "AND c.index_state='done' AND EXISTS(SELECT 1 FROM files f WHERE f.chat_id=c.id AND "
            "f.msg_id > c.verified_until) ORDER BY c.verified_until=0 DESC, RANDOM() LIMIT 1")
        if not chat:
            self.db.x("UPDATE chats SET verified_until=0 WHERE excluded=0")  # start a new round later
            return False
        cid = chat["id"]
        ids = [r["msg_id"] for r in self.db.q(
            "SELECT msg_id FROM files WHERE chat_id=? AND msg_id>? ORDER BY msg_id LIMIT ?",
            (cid, chat["verified_until"], VERIFY_BATCH))]
        if not ids:
            return False
        self.verify_state["chat"] = chat["title"]
        try:
            peer = await self.acc.peer(cid)
            msgs = await self.client.get_messages(peer, ids=ids)
        except SKIP_ERRORS:
            self.db.x("UPDATE chats SET verified_until=? WHERE id=?", (ids[-1], cid))
            return True
        gone = [mid for mid, m in zip(ids, msgs) if not isinstance(m, types.Message) or m.media is None]
        if gone:  # access problems raise instead of returning empty slots, so these really are deleted
            n = self.db.delete_files(cid, gone)
            self.verify_state["removed"] += n
            if n:
                self.db.log_activity("verify", f"Removed {n} deleted files from {chat['title']}")
        self.verify_state["checked"] += len(ids)
        self.db.x("UPDATE chats SET verified_until=? WHERE id=?", (ids[-1], cid))
        return True

    # --------------------------------------------------------------- live
    def install_handlers(self) -> None:
        if self._handlers:
            return
        self._handlers = True
        self.client.add_event_handler(self._on_new, events.NewMessage())
        self.client.add_event_handler(self._on_edit, events.MessageEdited())
        self.client.add_event_handler(self._on_delete, events.MessageDeleted())

    async def _chat_for(self, ev) -> Optional[dict]:
        cid = ev.chat_id
        chat = self.db.get_chat(cid)
        if chat is None:
            try:
                ent = await ev.get_chat()
            except Exception:
                ent = None
            if ent is None:
                return None
            row = chat_row(ent)
            self.db.upsert_chat(row)
            chat = self.db.get_chat(cid)
        if chat["excluded"] or chat["kind"] in set(settings.get("index_skip_kinds_of_chat") or []):
            return None
        return chat

    async def _on_new(self, ev) -> None:
        try:
            chat = await self._chat_for(ev)
            if not chat:
                return
            msg = ev.message
            cid = chat["id"]
            # Advance the indexed window only when there is no known gap before this message.
            if self.last_sync:
                self.db.x(
                    """UPDATE index_progress SET newest_id=MAX(newest_id, ?)
                       WHERE chat_id=? AND newest_id>0 AND newest_id >= ?""",
                    (msg.id, cid, chat["latest_msg_id"]),
                )
            self.db.bump_latest(cid, msg.id)
            rec = self.record(msg, cid, chat["title"])
            log.debug("live: new message %s in %s%s", msg.id, cid, f" with {rec['kind']} {rec.get('name')!r}" if rec else "")
            if rec and rec["kind"] in set(settings.get("index_kinds") or []):
                await self.db.write(self.db.index_page, [rec], cid)
                self.acc.notify_new_file(rec)
            await self.acc.drive.on_message(cid, msg)
        except Exception:
            log.exception("live new-message handler failed")

    async def _on_edit(self, ev) -> None:
        try:
            chat = await self._chat_for(ev)
            if not chat:
                return
            msg = ev.message
            log.debug("live: edited message %s in %s", msg.id, chat["id"])
            self.acc.fetcher.forget(chat["id"], msg.id)
            rec = self.record(msg, chat["id"], chat["title"])
            if rec:
                self.db.upsert_files([rec])
            else:
                self.db.delete_files(chat["id"], [msg.id])
            await self.acc.drive.on_message(chat["id"], msg)
        except Exception:
            log.exception("live edit handler failed")

    async def _on_delete(self, ev) -> None:
        try:
            ids = list(ev.deleted_ids or [])
            log.debug("live: %d message(s) deleted in %s: %s", len(ids), ev.chat_id, ids[:50])
            self.db.delete_files(ev.chat_id, ids)
            for mid in ids:
                if ev.chat_id is not None:
                    self.acc.fetcher.forget(ev.chat_id, mid)
        except Exception:
            log.exception("live delete handler failed")
