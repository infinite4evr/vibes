"""Per-account SQLite index.

* One writer connection lives on the asyncio thread (writes are small and batched).
* Heavy reads (search, counts, lists) run on a pool of reader threads with their
  own connections (WAL lets them read while the indexer writes), so a slow query
  never freezes the server. Readers can be interrupted and have a time limit.
* The schema is versioned (PRAGMA user_version). Upgrading an existing index is
  done in place; the new full-text indexes are filled in the background in small
  batches, so a large index keeps working during the upgrade.
"""
import asyncio
import itertools
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import textproc

log = logging.getLogger("tgdrive.db")

SCHEMA_VERSION = 6

# ------------------------------------------------------------------ schema v1
V1 = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, username TEXT,
  is_creator INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0, noforwards INTEGER DEFAULT 0,
  excluded INTEGER DEFAULT 0, latest_msg_id INTEGER DEFAULT 0, index_state TEXT DEFAULT 'pending',
  index_error TEXT, file_count INTEGER DEFAULT 0, updated_at INTEGER);
CREATE TABLE IF NOT EXISTS index_progress(
  chat_id INTEGER NOT NULL, filter TEXT NOT NULL, newest_id INTEGER DEFAULT 0, oldest_id INTEGER DEFAULT 0,
  done INTEGER DEFAULT 0, PRIMARY KEY(chat_id, filter));
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, kind TEXT NOT NULL,
  name TEXT, alias TEXT, ext TEXT, mime TEXT, size INTEGER DEFAULT 0, date INTEGER, caption TEXT,
  sender_id INTEGER, sender_name TEXT, chat_title TEXT, width INTEGER, height INTEGER, duration REAL,
  performer TEXT, audio_title TEXT, media_id INTEGER, grouped_id INTEGER, is_forward INTEGER DEFAULT 0,
  fwd_from TEXT, has_thumb INTEGER DEFAULT 0, is_out INTEGER DEFAULT 0, UNIQUE(chat_id, msg_id));
CREATE INDEX IF NOT EXISTS files_date ON files(date DESC);
CREATE INDEX IF NOT EXISTS files_chat_date ON files(chat_id, date DESC);
CREATE INDEX IF NOT EXISTS files_kind_date ON files(kind, date DESC);
CREATE INDEX IF NOT EXISTS files_size ON files(size);
CREATE INDEX IF NOT EXISTS files_ext ON files(ext);
CREATE INDEX IF NOT EXISTS files_media ON files(media_id);
CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL, created INTEGER);
CREATE TABLE IF NOT EXISTS placements(
  chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, folder_id TEXT, alias TEXT, PRIMARY KEY(chat_id, msg_id));
CREATE INDEX IF NOT EXISTS placements_folder ON placements(folder_id);
CREATE TABLE IF NOT EXISTS transfers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL, chat_id INTEGER, msg_id INTEGER, name TEXT,
  size INTEGER DEFAULT 0, done INTEGER DEFAULT 0, path TEXT, folder_id TEXT, status TEXT NOT NULL, error TEXT,
  upload_file_id INTEGER, created INTEGER, updated INTEGER);
"""

FTS_TOKENIZER = "porter unicode61 remove_diacritics 2 categories 'L* N* Co M*'"
SEARCH_COLS = ["name", "alias", "caption", "chat_title", "sender_name", "keywords"]


def run_script(c: sqlite3.Connection, script: str) -> None:
    """Execute a multi-statement script inside the caller's transaction (executescript would commit)."""
    buf = ""
    for part in script.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \n;"):
                c.execute(buf)
            buf = ""
    if buf.strip(" \n;"):
        c.execute(buf)


def _v2(c: sqlite3.Connection) -> None:
    def add(table: str, col: str, decl: str) -> None:
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    for col, decl in (("keywords", "TEXT"), ("fts_v", "INTEGER DEFAULT 0"), ("topic_id", "INTEGER"),
                      ("stripped", "BLOB"), ("loc", "TEXT"), ("checked_at", "INTEGER")):
        add("files", col, decl)
    for col, decl in (("starred", "INTEGER DEFAULT 0"), ("tags", "TEXT"), ("note", "TEXT"),
                      ("mtime", "INTEGER DEFAULT 0")):
        add("placements", col, decl)
    for col, decl in (("color", "TEXT"), ("mtime", "INTEGER DEFAULT 0"), ("description", "TEXT")):
        add("folders", col, decl)
    for col, decl in (("is_forum", "INTEGER DEFAULT 0"), ("pinned", "INTEGER DEFAULT 0"),
                      ("total_bytes", "INTEGER DEFAULT 0"), ("last_indexed", "INTEGER"),
                      ("verified_until", "INTEGER DEFAULT 0"), ("index_kinds", "TEXT"),
                      ("archived", "INTEGER DEFAULT 0"), ("members", "INTEGER")):
        add("chats", col, decl)
    add("transfers", "dest", "TEXT")
    add("transfers", "source_path", "TEXT")
    add("transfers", "batch", "TEXT")
    add("transfers", "caption", "TEXT")
    add("transfers", "target_chat", "INTEGER")
    run_script(c, f"""
    CREATE INDEX IF NOT EXISTS files_ext_date ON files(ext, date DESC);
    CREATE INDEX IF NOT EXISTS files_chat_kind_date ON files(chat_id, kind, date DESC);
    CREATE INDEX IF NOT EXISTS files_name_nocase ON files(COALESCE(alias, name) COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS files_fts_v ON files(fts_v) WHERE fts_v=0;
    CREATE INDEX IF NOT EXISTS files_grouped ON files(grouped_id) WHERE grouped_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS files_dupe ON files(size, kind);
    CREATE INDEX IF NOT EXISTS placements_starred ON placements(starred) WHERE starred=1;

    CREATE TABLE IF NOT EXISTS stats(
      chat_id INTEGER NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(chat_id, kind));
    DELETE FROM stats;
    INSERT INTO stats(chat_id, kind, n, bytes)
      SELECT chat_id, kind, COUNT(*), COALESCE(SUM(size), 0) FROM files GROUP BY chat_id, kind;
    CREATE TRIGGER IF NOT EXISTS files_st_ai AFTER INSERT ON files BEGIN
      INSERT INTO stats(chat_id, kind, n, bytes) VALUES(new.chat_id, new.kind, 1, COALESCE(new.size, 0))
      ON CONFLICT(chat_id, kind) DO UPDATE SET n=n+1, bytes=bytes+excluded.bytes;
    END;
    CREATE TRIGGER IF NOT EXISTS files_st_ad AFTER DELETE ON files BEGIN
      UPDATE stats SET n=n-1, bytes=bytes-COALESCE(old.size, 0) WHERE chat_id=old.chat_id AND kind=old.kind;
    END;
    CREATE TRIGGER IF NOT EXISTS files_st_au AFTER UPDATE OF kind, size, chat_id ON files
      WHEN old.kind IS NOT new.kind OR old.size IS NOT new.size OR old.chat_id IS NOT new.chat_id BEGIN
      UPDATE stats SET n=n-1, bytes=bytes-COALESCE(old.size, 0) WHERE chat_id=old.chat_id AND kind=old.kind;
      INSERT INTO stats(chat_id, kind, n, bytes) VALUES(new.chat_id, new.kind, 1, COALESCE(new.size, 0))
      ON CONFLICT(chat_id, kind) DO UPDATE SET n=n+1, bytes=bytes+excluded.bytes;
    END;

    CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
      {', '.join(SEARCH_COLS)}, content='files', content_rowid='id',
      tokenize="{FTS_TOKENIZER}", prefix='2 3');
    CREATE VIRTUAL TABLE IF NOT EXISTS names_tri USING fts5(
      name, alias, content='files', content_rowid='id', tokenize='trigram remove_diacritics 1');
    CREATE TRIGGER IF NOT EXISTS files_s_ai AFTER INSERT ON files WHEN new.fts_v=1 BEGIN
      INSERT INTO search_fts(rowid, {', '.join(SEARCH_COLS)})
        VALUES (new.id, {', '.join('new.' + c for c in SEARCH_COLS)});
      INSERT INTO names_tri(rowid, name, alias) VALUES (new.id, new.name, new.alias);
    END;
    CREATE TRIGGER IF NOT EXISTS files_s_ad AFTER DELETE ON files WHEN old.fts_v=1 BEGIN
      INSERT INTO search_fts(search_fts, rowid, {', '.join(SEARCH_COLS)})
        VALUES ('delete', old.id, {', '.join('old.' + c for c in SEARCH_COLS)});
      INSERT INTO names_tri(names_tri, rowid, name, alias) VALUES ('delete', old.id, old.name, old.alias);
    END;
    CREATE TRIGGER IF NOT EXISTS files_s_au AFTER UPDATE ON files
      WHEN old.fts_v=1 AND new.fts_v=1 AND ({' OR '.join(f'old.{c} IS NOT new.{c}' for c in SEARCH_COLS)}) BEGIN
      INSERT INTO search_fts(search_fts, rowid, {', '.join(SEARCH_COLS)})
        VALUES ('delete', old.id, {', '.join('old.' + c for c in SEARCH_COLS)});
      INSERT INTO names_tri(names_tri, rowid, name, alias) VALUES ('delete', old.id, old.name, old.alias);
      INSERT INTO search_fts(rowid, {', '.join(SEARCH_COLS)})
        VALUES (new.id, {', '.join('new.' + c for c in SEARCH_COLS)});
      INSERT INTO names_tri(rowid, name, alias) VALUES (new.id, new.name, new.alias);
    END;

    CREATE TABLE IF NOT EXISTS tombstones(kind TEXT NOT NULL, id TEXT NOT NULL, at INTEGER NOT NULL,
      PRIMARY KEY(kind, id));
    CREATE TABLE IF NOT EXISTS saved_searches(id TEXT PRIMARY KEY, name TEXT NOT NULL, q TEXT, params TEXT,
      icon TEXT, created INTEGER, mtime INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS recent(chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, action TEXT,
      at INTEGER NOT NULL, PRIMARY KEY(chat_id, msg_id));
    CREATE INDEX IF NOT EXISTS recent_at ON recent(at DESC);
    CREATE TABLE IF NOT EXISTS search_history(q TEXT PRIMARY KEY, at INTEGER NOT NULL, n INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS dialog_filters(id INTEGER PRIMARY KEY, title TEXT NOT NULL, emoticon TEXT,
      position INTEGER, chat_ids TEXT);
    CREATE TABLE IF NOT EXISTS topics(chat_id INTEGER NOT NULL, topic_id INTEGER NOT NULL, title TEXT,
      icon_color INTEGER, PRIMARY KEY(chat_id, topic_id));
    CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
      action TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS manifest_backups(id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
      reason TEXT, data BLOB NOT NULL);
    """)
    has_old_fts = c.execute("SELECT 1 FROM sqlite_master WHERE name='files_fts'").fetchone()
    empty = not c.execute("SELECT 1 FROM files LIMIT 1").fetchone()
    if empty:
        for t in ("files_ai", "files_ad", "files_au"):
            c.execute(f"DROP TRIGGER IF EXISTS {t}")
        c.execute("DROP TABLE IF EXISTS files_fts")
    c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('search_state', ?)",
              ("ready" if empty else "migrating" if has_old_fts else "building",))
    c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('search_total', ?)",
              (str(c.execute("SELECT COUNT(*) FROM files WHERE fts_v=0").fetchone()[0]),))
    c.execute("UPDATE chats SET file_count=COALESCE((SELECT SUM(n) FROM stats s WHERE s.chat_id=chats.id), 0),"
              " total_bytes=COALESCE((SELECT SUM(bytes) FROM stats s WHERE s.chat_id=chats.id), 0)")


def _v3(c: sqlite3.Connection) -> None:
    """Playback positions: resume videos and audio where you stopped; watched / in-progress filters."""
    run_script(c, """
        CREATE TABLE IF NOT EXISTS playback (
            chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL,
            pos REAL NOT NULL DEFAULT 0, dur REAL, done INTEGER NOT NULL DEFAULT 0, at INTEGER NOT NULL,
            PRIMARY KEY (chat_id, msg_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS playback_at ON playback(at);
    """)


def _v4(c: sqlite3.Connection) -> None:
    """Folder icons, covers and rules (smart folders); subjects; folder sync."""
    have = {r[1] for r in c.execute("PRAGMA table_info(folders)")}
    for col in ("emoji", "cover", "rules", "kind"):
        if col not in have:
            c.execute(f"ALTER TABLE folders ADD COLUMN {col} TEXT")
    run_script(c, """
        CREATE TABLE IF NOT EXISTS file_subjects (
            file_id INTEGER PRIMARY KEY, subject TEXT NOT NULL, score REAL, src TEXT);
        CREATE INDEX IF NOT EXISTS file_subjects_subject ON file_subjects(subject);
        CREATE TRIGGER IF NOT EXISTS files_extra_ad AFTER DELETE ON files BEGIN
          DELETE FROM file_subjects WHERE file_id=old.id;
        END;
        CREATE TABLE IF NOT EXISTS sync_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, local_path TEXT NOT NULL, folder_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created INTEGER, last_run INTEGER, state TEXT, error TEXT,
            stats TEXT, approved INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sync_files (
            pair_id INTEGER NOT NULL, rel TEXT NOT NULL, size INTEGER, mtime REAL, chat_id INTEGER, msg_id INTEGER,
            pending TEXT, tid INTEGER, PRIMARY KEY (pair_id, rel));
    """)


def _v5(c: sqlite3.Connection) -> None:
    """Duplicate copies: which files are the same file (see dupes.py). Only files that have copies get a row.
    grp: the group; rank: 0 for the copy shown when duplicates are hidden; n: copies in the group;
    xc: 1 when a better copy exists in the same chat (for fast per-chat counts)."""
    run_script(c, """
        CREATE TABLE IF NOT EXISTS dups (
            file_id INTEGER PRIMARY KEY, grp INTEGER NOT NULL, rank INTEGER NOT NULL, n INTEGER NOT NULL,
            xc INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS dups_grp ON dups(grp, rank);
        CREATE TABLE IF NOT EXISTS dups_stats (
            chat_id INTEGER NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL, bytes INTEGER NOT NULL,
            PRIMARY KEY (chat_id, kind)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS files_name_size ON files(name COLLATE NOCASE, size) WHERE size >= 10240;
        CREATE TRIGGER IF NOT EXISTS files_dups_ad AFTER DELETE ON files BEGIN
          DELETE FROM dups WHERE file_id=old.id;
        END;
    """)


def _v6(c: sqlite3.Connection) -> None:
    """TG Drive 2.3 dropped photo places and PDF highlights/bookmarks/reading position: remove their data.
    Uploads remember the id of the message they send (so a retry can't post the file twice)."""
    have = {r[1] for r in c.execute("PRAGMA table_info(transfers)")}
    if "send_id" not in have:
        c.execute("ALTER TABLE transfers ADD COLUMN send_id INTEGER")
    run_script(c, """
        DROP TRIGGER IF EXISTS files_extra_ad;
        DROP TABLE IF EXISTS geo;
        DROP TABLE IF EXISTS marks;
        DROP TABLE IF EXISTS reading;
        DELETE FROM tombstones WHERE kind='mark';
        CREATE TRIGGER IF NOT EXISTS files_extra_ad AFTER DELETE ON files BEGIN
          DELETE FROM file_subjects WHERE file_id=old.id;
        END;
    """)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    lambda c: run_script(c, V1),    # -> 1
    _v2,                            # -> 2
    _v3,                            # -> 3
    _v4,                            # -> 4
    _v5,                            # -> 5
    _v6,                            # -> 6
]

FILE_COLS = [
    "chat_id", "msg_id", "kind", "name", "ext", "mime", "size", "date", "caption",
    "sender_id", "sender_name", "chat_title", "width", "height", "duration",
    "performer", "audio_title", "media_id", "grouped_id", "is_forward", "fwd_from",
    "has_thumb", "is_out", "topic_id", "stripped", "loc", "keywords",
]
# Written on INSERT only / never overwritten with NULL on UPDATE:
KEEP_IF_NULL = {"stripped", "loc", "topic_id"}

CHAT_COLS = ["id", "title", "kind", "username", "is_creator", "is_admin", "noforwards", "latest_msg_id"]
CHAT_EXTRA = ["is_forum", "archived", "members"]

TRANSFER_COLS = [
    "direction", "chat_id", "msg_id", "name", "size", "done", "path", "folder_id",
    "status", "error", "upload_file_id", "dest", "source_path", "batch", "caption", "target_chat", "send_id",
]


def now() -> int:
    return int(time.time())


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-32000")
    if readonly:
        conn.execute("PRAGMA query_only=1")
    return conn


class QueryTimeout(Exception):
    """A read took longer than its time limit (or was superseded)."""


class Reader:
    """A worker thread that owns one read connection."""

    def __init__(self, path: Path, n: int):
        self.path = path
        self.n = n
        self.jobs: "queue.Queue[tuple[Callable, tuple, Future, float] | None]" = queue.Queue()
        self.conn: Optional[sqlite3.Connection] = None
        self.current: Optional[Future] = None
        self.deadline = 0.0
        self.cache: dict[str, Any] = {}  # per-connection scratch (e.g. search candidate tables)
        self.thread = threading.Thread(target=self._loop, name=f"tgdrive-reader-{n}", daemon=True)
        self.thread.start()

    def _progress(self) -> int:
        return 1 if self.deadline and time.monotonic() > self.deadline else 0

    def _loop(self) -> None:
        self.conn = _connect(self.path, readonly=False)  # needs TEMP tables, so not query_only
        self.conn.set_progress_handler(self._progress, 20_000)
        while True:
            job = self.jobs.get()
            if job is None:
                break
            fn, args, fut, timeout = job
            if not fut.set_running_or_notify_cancel():
                continue
            self.current = fut
            self.deadline = time.monotonic() + timeout if timeout else 0.0
            try:
                fut.set_result(fn(self, *args))
            except sqlite3.OperationalError as exc:
                if "interrupt" in str(exc):
                    fut.set_exception(QueryTimeout("The search took too long and was stopped."))
                else:
                    fut.set_exception(exc)
            except BaseException as exc:  # noqa: BLE001 - hand every error to the caller
                fut.set_exception(exc)
            finally:
                self.current = None
                self.deadline = 0.0
        try:
            self.conn.close()
        except Exception:
            pass

    # Convenience for job functions.
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def interrupt(self, fut: Future) -> None:
        if self.current is fut and self.conn is not None:
            self.conn.interrupt()


class ReadPool:
    def __init__(self, path: Path, size: int = 4):
        self.readers = [Reader(path, i) for i in range(size)]
        self._rr = itertools.count()
        self.slots: dict[str, tuple[Reader, Future]] = {}

    def submit(self, fn: Callable, *args, key: Optional[str] = None, slot: Optional[str] = None,
               timeout: float = 30.0) -> Future:
        if key is not None:
            reader = self.readers[hash(key) % len(self.readers)]
        else:
            reader = min(self.readers, key=lambda r: (r.jobs.qsize() + (r.current is not None), next(self._rr) % 7))
        fut: Future = Future()
        if slot:
            prev = self.slots.get(slot)
            if prev and not prev[1].done():
                prev[1].superseded = True   # the waiting request answers "superseded" (408), not nothing
                prev[1].cancel()
                prev[0].interrupt(prev[1])
            self.slots[slot] = (reader, fut)
        reader.jobs.put((fn, args, fut, timeout))
        return fut

    async def run(self, fn: Callable, *args, key: Optional[str] = None, slot: Optional[str] = None,
                  timeout: float = 30.0):
        fut = self.submit(fn, *args, key=key, slot=slot, timeout=timeout)
        try:
            return await asyncio.wrap_future(fut)
        except asyncio.CancelledError:
            if getattr(fut, "superseded", False):
                # A newer request took this one's place: say so, rather than letting the cancellation
                # end the HTTP request without any answer.
                raise QueryTimeout("Superseded by a newer search.")
            for r in self.readers:
                r.interrupt(fut)
            fut.cancel()
            raise
        except __import__("concurrent.futures").futures.CancelledError:
            raise QueryTimeout("Superseded by a newer search.")

    def close(self) -> None:
        for r in self.readers:
            r.jobs.put(None)


def prefetch_files(*paths) -> None:
    for p in paths:
        try:
            fd = os.open(p, os.O_RDONLY)
        except OSError:
            continue
        try:
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_WILLNEED)
        except OSError:
            pass
        finally:
            os.close(fd)


class Database:
    def __init__(self, path: Path, readers: int = 4):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = _connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        # One writer at a time inside this process. Every write transaction (the main connection, the
        # writer thread, and the background workers' connections) takes this lock first, so nobody spins in
        # SQLite's busy handler and a wait is never longer than one short transaction.
        self.wlock = threading.RLock()
        self._wexec: Optional[ThreadPoolExecutor] = None
        self._wconn: Optional[sqlite3.Connection] = None
        self.migrate()
        self._read: Optional[ReadPool] = None
        self._readers = readers
        self._aliases_cache: dict[int, dict[int, str]] = {}

    @property
    def read(self) -> ReadPool:
        if self._read is None:
            self._read = ReadPool(self.path, self._readers)
        return self._read

    def close(self) -> None:
        if self._read:
            self._read.close()
        if self._wexec is not None:
            self._wexec.submit(self._close_writer).result(timeout=30)
            self._wexec.shutdown(wait=True)
            self._wexec = None
        self.conn.close()

    # ------------------------------------------------------------ writer thread
    async def write(self, fn: Callable, *args):
        """Run fn(conn, *args) in one transaction on the writer thread, off the event loop. Use it for
        the frequent writes (indexing pages, live updates) so a slow disk never freezes the app."""
        if self._wexec is None:
            self._wexec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tgdrive-writer")
        return await asyncio.get_running_loop().run_in_executor(self._wexec, self._write_job, fn, args)

    def _write_job(self, fn: Callable, args: tuple):
        if self._wconn is None:
            self._wconn = _connect(self.path)
        c = self._wconn
        with self.wlock:
            c.execute("BEGIN IMMEDIATE")
            try:
                out = fn(c, *args)
                c.execute("COMMIT")
                return out
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def _close_writer(self) -> None:
        if self._wconn is not None:
            self._wconn.close()
            self._wconn = None

    def prewarm(self) -> None:
        """Ask the OS to pull the index into its file cache in the background, so the first search
        after starting doesn't wait on the disk (400k files is a few hundred MB). Costs nothing to call."""
        prefetch_files(self.path, self.path.with_name(self.path.name + "-wal"))

    # --------------------------------------------------------------- migrate
    def migrate(self) -> None:
        c = self.conn
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and c.execute("SELECT 1 FROM sqlite_master WHERE name='files'").fetchone():
            version = 1  # created by TG Drive 0.1 (before versioning)
            c.execute("PRAGMA user_version=1")
        for target in range(version + 1, SCHEMA_VERSION + 1):
            log.info("upgrading index %s to schema v%s", self.path, target)
            t0 = time.time()
            c.execute("BEGIN IMMEDIATE")
            try:
                MIGRATIONS[target - 1](c)
                c.execute(f"PRAGMA user_version={target}")
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            log.info("schema v%s ready in %.1fs", target, time.time() - t0)

    @property
    def search_ready(self) -> bool:
        return self.get_meta("search_state") == "ready"

    def search_upgrade_status(self) -> dict:
        state = self.get_meta("search_state") or "ready"
        if state == "ready":
            return {"state": "ready"}
        total = int(self.get_meta("search_total") or 0)
        # Counting the rows still to do reads the whole table: at most every 5 s (every open window asks
        # every second while the upgrade runs).
        cached = getattr(self, "_upgrade_left", None)
        if cached and time.monotonic() - cached[0] < 5:
            left = cached[1]
        else:
            left = self.one("SELECT COUNT(*) AS n FROM files WHERE fts_v=0")["n"]
            self._upgrade_left = (time.monotonic(), left)
        return {"state": state, "total": total, "done": max(0, total - left)}

    def build_search_batch(self, conn: Optional[sqlite3.Connection] = None, batch: int = 2000) -> int:
        """Fill the new search indexes for up to `batch` rows; returns rows processed (0 = finished)."""
        c = conn or self.conn
        rows = c.execute(
            "SELECT f.id, f.name, f.caption, f.alias FROM files f WHERE f.fts_v=0 LIMIT ?", (batch,)).fetchall()
        if not rows:
            self._finish_search_build(c)
            return 0
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        kw = [(textproc.keywords(r["name"], r["caption"], r["alias"]), r["id"]) for r in rows]   # outside the lock
        with self.wlock:
            self._build_batch_tx(c, kw, ids, marks)
        return len(rows)

    def _build_batch_tx(self, c: sqlite3.Connection, kw: list, ids: list, marks: str) -> None:
        c.execute("BEGIN IMMEDIATE")
        try:
            c.executemany("UPDATE files SET keywords=?, fts_v=1 WHERE id=? AND fts_v=0", kw)
            c.execute(f"INSERT INTO search_fts(rowid, {', '.join(SEARCH_COLS)}) "
                      f"SELECT id, {', '.join(SEARCH_COLS)} FROM files WHERE id IN ({marks})", ids)
            c.execute(f"INSERT INTO names_tri(rowid, name, alias) SELECT id, name, alias FROM files "
                      f"WHERE id IN ({marks})", ids)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise

    def _finish_search_build(self, c: sqlite3.Connection) -> None:
        if (c.execute("SELECT value FROM meta WHERE key='search_state'").fetchone() or [None])[0] == "ready":
            return
        with self.wlock:
            self._finish_search_tx(c)
        self._optimize_search(c)

    def _finish_search_tx(self, c: sqlite3.Connection) -> None:
        c.execute("BEGIN IMMEDIATE")
        try:
            for t in ("files_ai", "files_ad", "files_au"):
                c.execute(f"DROP TRIGGER IF EXISTS {t}")
            c.execute("DROP TABLE IF EXISTS files_fts")
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('search_state', 'ready')")
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise

    def _optimize_search(self, c: sqlite3.Connection) -> None:
        try:
            c.execute("INSERT INTO search_fts(search_fts) VALUES('optimize')")
            c.execute("INSERT INTO names_tri(names_tri) VALUES('optimize')")
        except sqlite3.Error:
            pass
        log.info("search index upgrade finished")

    def build_search_all(self) -> None:
        """Synchronous full build (tests, small indexes)."""
        while self.build_search_batch(batch=5000):
            pass

    # ----------------------------------------------------------------- basics
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def x(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.wlock:
            return self.conn.execute(sql, tuple(params))

    def tx(self):
        """Usage: with db.tx(): ... (explicit transaction for batched writes)."""
        return _Tx(self.conn, self.wlock)

    # ------------------------------------------------------------------- meta
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        self.x(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, None if value is None else str(value)),
        )

    def log_activity(self, action: str, detail: str = "") -> None:
        self.x("INSERT INTO activity(at, action, detail) VALUES(?,?,?)", (now(), action, detail[:500]))
        if int(time.time()) % 50 == 0:
            self.x("DELETE FROM activity WHERE id < (SELECT MAX(id) - 5000 FROM activity)")

    # ------------------------------------------------------------------ chats
    def upsert_chat(self, chat: dict) -> None:
        cols = CHAT_COLS + [c for c in CHAT_EXTRA if c in chat]
        vals = [chat.get(c) for c in cols]
        extra_set = "".join(f", {c}=excluded.{c}" for c in CHAT_EXTRA if c in chat)
        self.x(
            f"""INSERT INTO chats({','.join(cols)}, updated_at) VALUES({','.join('?' * len(cols))}, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title, kind=excluded.kind, username=excluded.username,
                  is_creator=excluded.is_creator, is_admin=excluded.is_admin,
                  noforwards=excluded.noforwards,
                  latest_msg_id=MAX(chats.latest_msg_id, excluded.latest_msg_id),
                  index_state=CASE chats.index_state WHEN 'gone' THEN 'pending' ELSE chats.index_state END,
                  updated_at=excluded.updated_at{extra_set}""",
            vals + [now()],
        )
        # Keep the denormalised chat title on files in sync after a rename.
        self.x("UPDATE files SET chat_title=? WHERE chat_id=? AND chat_title IS NOT ?",
               (chat["title"], chat["id"], chat["title"]))

    def get_chat(self, chat_id: int) -> Optional[dict]:
        return self.one("SELECT * FROM chats WHERE id=?", (chat_id,))

    def list_chats(self, conn=None) -> list[dict]:
        return (conn or self).q(
            "SELECT id, title, kind, username, is_creator, is_admin, noforwards, excluded, pinned, archived, "
            "is_forum, index_state, index_error, file_count, total_bytes, last_indexed, latest_msg_id, "
            "index_kinds, members FROM chats ORDER BY file_count DESC, title COLLATE NOCASE"
        )

    def chats_needing_index(self) -> list[dict]:
        """Chats whose backfill is unfinished, or that have messages newer than what we indexed."""
        return self.q(
            """SELECT c.* FROM chats c WHERE c.excluded=0 AND c.index_state<>'gone' AND (
                 c.index_state IN ('pending','running','error')
                 OR c.latest_msg_id > COALESCE((SELECT MIN(p.newest_id) FROM index_progress p WHERE p.chat_id=c.id), 0)
               )
               ORDER BY c.pinned DESC,
                        CASE c.index_state WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                        c.latest_msg_id DESC"""
        )

    def set_chat_state(self, chat_id: int, state: str, error: Optional[str] = None) -> None:
        extra = ", last_indexed=?" if state == "done" else ""
        self.x(f"UPDATE chats SET index_state=?, index_error=?{extra} WHERE id=?",
               (state, error, *([now()] if extra else []), chat_id))

    def bump_latest(self, chat_id: int, msg_id: int) -> None:
        self.x("UPDATE chats SET latest_msg_id=MAX(latest_msg_id, ?) WHERE id=?", (msg_id, chat_id))

    def refresh_file_count(self, chat_id: int, conn: Optional[sqlite3.Connection] = None) -> None:
        (conn.execute if conn is not None else self.x)(
            "UPDATE chats SET file_count=COALESCE((SELECT SUM(n) FROM stats WHERE chat_id=?), 0), "
            "total_bytes=COALESCE((SELECT SUM(bytes) FROM stats WHERE chat_id=?), 0) WHERE id=?",
            (chat_id, chat_id, chat_id),
        )

    def set_excluded(self, chat_id: int, excluded: bool) -> None:
        with self.tx():
            self.x("UPDATE chats SET excluded=? WHERE id=?", (int(excluded), chat_id))
            if excluded:
                self.x("DELETE FROM files WHERE chat_id=?", (chat_id,))
                self.x("DELETE FROM index_progress WHERE chat_id=?", (chat_id,))
                self.x("UPDATE chats SET index_state='pending', index_error=NULL WHERE id=?", (chat_id,))
        self.refresh_file_count(chat_id)

    def reset_chat_index(self, chat_id: int) -> None:
        with self.tx():
            self.x("DELETE FROM files WHERE chat_id=?", (chat_id,))
            self.x("DELETE FROM index_progress WHERE chat_id=?", (chat_id,))
            self.x("UPDATE chats SET index_state='pending', index_error=NULL, verified_until=0 WHERE id=?",
                   (chat_id,))
        self.refresh_file_count(chat_id)

    # --------------------------------------------------------------- progress
    def get_progress(self, chat_id: int, filt: str, conn: Optional[sqlite3.Connection] = None) -> dict:
        sql, args = "SELECT * FROM index_progress WHERE chat_id=? AND filter=?", (chat_id, filt)
        if conn is not None:
            r = conn.execute(sql, args).fetchone()
            row = dict(r) if r else None
        else:
            row = self.one(sql, args)
        return row or {"chat_id": chat_id, "filter": filt, "newest_id": 0, "oldest_id": 0, "done": 0}

    def set_progress(self, chat_id: int, filt: str, conn: Optional[sqlite3.Connection] = None, **fields: Any) -> None:
        cur = self.get_progress(chat_id, filt, conn)
        cur.update(fields)
        (conn.execute if conn is not None else self.x)(
            """INSERT INTO index_progress(chat_id, filter, newest_id, oldest_id, done) VALUES(?,?,?,?,?)
               ON CONFLICT(chat_id, filter) DO UPDATE SET newest_id=excluded.newest_id,
                 oldest_id=excluded.oldest_id, done=excluded.done""",
            (chat_id, filt, cur["newest_id"], cur["oldest_id"], cur["done"]),
        )

    # ------------------------------------------------------------------ files
    def _aliases_for(self, chat_id: int) -> dict[int, str]:
        return {r["msg_id"]: r["alias"] for r in self.q(
            "SELECT msg_id, alias FROM placements WHERE chat_id=? AND alias IS NOT NULL", (chat_id,))}

    def upsert_files(self, recs: list[dict], conn: Optional[sqlite3.Connection] = None) -> None:
        if not recs:
            return
        aliases: dict[int, dict[int, str]] = {}
        for r in recs:
            if r["chat_id"] not in aliases:
                if conn is not None:
                    aliases[r["chat_id"]] = {m: a for m, a in conn.execute(
                        "SELECT msg_id, alias FROM placements WHERE chat_id=? AND alias IS NOT NULL", (r["chat_id"],))}
                else:
                    aliases[r["chat_id"]] = self._aliases_for(r["chat_id"])
            alias = aliases[r["chat_id"]].get(r["msg_id"])
            r["keywords"] = textproc.keywords(r.get("name"), r.get("caption"), alias)
        cols = ",".join(FILE_COLS)
        marks = ",".join("?" * len(FILE_COLS))
        updates = ",".join(
            f"{c}=COALESCE(excluded.{c}, files.{c})" if c in KEEP_IF_NULL else f"{c}=excluded.{c}"
            for c in FILE_COLS if c not in ("chat_id", "msg_id"))
        sql = (
            f"INSERT INTO files({cols}, alias, fts_v) VALUES({marks}, "
            f"(SELECT alias FROM placements WHERE chat_id=? AND msg_id=?), 1) "
            f"ON CONFLICT(chat_id, msg_id) DO UPDATE SET {updates}"
        )
        rows = [[r.get(c) for c in FILE_COLS] + [r["chat_id"], r["msg_id"]] for r in recs]
        if conn is not None:
            conn.executemany(sql, rows)
            return
        with self.tx():
            self.conn.executemany(sql, rows)

    def index_page(self, conn: sqlite3.Connection, recs: list[dict], chat_id: int,
                   progress: Optional[tuple[str, dict]] = None) -> None:
        """One indexing step in one transaction (runs on the writer thread via write())."""
        self.upsert_files(recs, conn)
        if progress:
            self.set_progress(chat_id, progress[0], conn, **progress[1])
        self.refresh_file_count(chat_id, conn)

    def delete_files(self, chat_id: Optional[int], msg_ids: list[int]) -> int:
        """Delete by id. chat_id=None means 'any non-channel chat' (Telegram does not say which)."""
        if not msg_ids:
            return 0
        marks = ",".join("?" * len(msg_ids))
        if chat_id is None:
            # Users and basic groups share one message-id space per account; channels are <= -10^12.
            affected = self.q(
                f"SELECT DISTINCT chat_id FROM files WHERE chat_id > -1000000000000 AND msg_id IN ({marks})",
                msg_ids,
            )
            cur = self.x(
                f"DELETE FROM files WHERE chat_id > -1000000000000 AND msg_id IN ({marks})", msg_ids
            )
            for row in affected:
                self.refresh_file_count(row["chat_id"])
        else:
            cur = self.x(f"DELETE FROM files WHERE chat_id=? AND msg_id IN ({marks})", [chat_id, *msg_ids])
            self.refresh_file_count(chat_id)
        return cur.rowcount

    FILE_SELECT = """SELECT f.*, p.folder_id, p.starred, p.tags, p.note, c.kind AS chat_kind,
                      c.username AS chat_username, c.noforwards AS chat_noforwards, c.is_admin AS chat_is_admin,
                      c.is_creator AS chat_is_creator, pb.pos AS play_pos, pb.dur AS play_dur, pb.done AS play_done,
                      (SELECT s.subject FROM file_subjects s WHERE s.file_id=f.id) AS subject,
                      (SELECT d.n FROM dups d WHERE d.file_id=f.id) AS copies
               FROM files f
               LEFT JOIN placements p ON p.chat_id=f.chat_id AND p.msg_id=f.msg_id
               LEFT JOIN chats c ON c.id=f.chat_id
               LEFT JOIN playback pb ON pb.chat_id=f.chat_id AND pb.msg_id=f.msg_id"""

    def get_file(self, chat_id: int, msg_id: int) -> Optional[dict]:
        return self.one(self.FILE_SELECT + " WHERE f.chat_id=? AND f.msg_id=?", (chat_id, msg_id))

    def totals(self) -> dict:
        row = self.one("SELECT COALESCE(SUM(n),0) AS files, COALESCE(SUM(bytes),0) AS bytes FROM stats")
        return row or {"files": 0, "bytes": 0}

    def kind_totals(self, chat_id: Optional[int] = None) -> dict[str, dict]:
        if chat_id is None:
            rows = self.q("SELECT kind, SUM(n) AS n, SUM(bytes) AS bytes FROM stats GROUP BY kind")
        else:
            rows = self.q("SELECT kind, n, bytes FROM stats WHERE chat_id=?", (chat_id,))
        return {r["kind"]: {"n": r["n"], "bytes": r["bytes"]} for r in rows if r["n"]}

    def touch_recent(self, chat_id: int, msg_id: int, action: str) -> None:
        self.x("INSERT INTO recent(chat_id, msg_id, action, at) VALUES(?,?,?,?) "
               "ON CONFLICT(chat_id, msg_id) DO UPDATE SET action=excluded.action, at=excluded.at",
               (chat_id, msg_id, action, now()))

    def get_playback(self, chat_id: int, msg_id: int) -> Optional[dict]:
        return self.one("SELECT pos, dur, done, at FROM playback WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))

    def set_playback(self, chat_id: int, msg_id: int, pos: float, dur: Optional[float] = None,
                     done: Optional[bool] = None) -> dict:
        """Remember where playback stopped. Near the end (last 3% or 20 s) counts as watched."""
        pos = max(0.0, float(pos or 0))
        dur = float(dur) if dur else None
        if done is None:
            done = bool(dur and pos >= min(dur * 0.97, dur - 20))
        if done:
            pos = 0.0
        self.x("INSERT INTO playback(chat_id, msg_id, pos, dur, done, at) VALUES(?,?,?,?,?,?) "
               "ON CONFLICT(chat_id, msg_id) DO UPDATE SET pos=excluded.pos, dur=COALESCE(excluded.dur, dur), "
               "done=excluded.done, at=excluded.at", (chat_id, msg_id, pos, dur, int(bool(done)), now()))
        return {"pos": pos, "dur": dur, "done": bool(done)}

    def clear_playback(self, chat_id: int, msg_id: int) -> None:
        self.x("DELETE FROM playback WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))

    def add_search_history(self, q: str) -> None:
        q = q.strip()
        if not q:
            return
        self.x("INSERT INTO search_history(q, at) VALUES(?, ?) ON CONFLICT(q) DO UPDATE SET at=excluded.at, n=n+1",
               (q[:200], now()))
        self.x("DELETE FROM search_history WHERE q NOT IN (SELECT q FROM search_history ORDER BY at DESC LIMIT 200)")

    # ---------------------------------------------------------------- folders
    def list_folders(self, conn=None) -> list[dict]:
        return (conn or self).q(
            """SELECT fo.id, fo.parent_id, fo.name, fo.created, fo.color, fo.description, fo.mtime,
                      fo.emoji, fo.cover, fo.rules, fo.kind,
                      COALESCE(s.n, 0) AS file_count, COALESCE(s.bytes, 0) AS bytes
               FROM folders fo LEFT JOIN (
                 SELECT p.folder_id, COUNT(*) AS n, SUM(f.size) AS bytes FROM placements p
                 JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id
                 WHERE p.folder_id IS NOT NULL GROUP BY p.folder_id) s ON s.folder_id=fo.id
               ORDER BY fo.name COLLATE NOCASE"""
        )

    def get_folder(self, folder_id: str) -> Optional[dict]:
        return self.one("SELECT * FROM folders WHERE id=?", (folder_id,))

    PLACEMENT_COLS = ["chat_id", "msg_id", "folder_id", "alias", "starred", "tags", "note", "mtime"]

    FOLDER_COLS = ["id", "parent_id", "name", "created", "color", "description", "mtime", "emoji", "cover", "rules",
                   "kind"]

    def replace_drive_state(self, folders: list[dict], placements: list[dict],
                            saved: Optional[list[dict]] = None, tombstones: Optional[list[dict]] = None) -> None:
        """Replace the local mirror with the contents of a manifest."""
        old_alias = {(r["chat_id"], r["msg_id"]): r["alias"] for r in self.q(
            "SELECT chat_id, msg_id, alias FROM placements WHERE alias IS NOT NULL")}
        with self.tx():
            self.x("DELETE FROM folders")
            self.x("DELETE FROM placements")
            self.conn.executemany(
                f"INSERT INTO folders({','.join(self.FOLDER_COLS)}) VALUES({','.join('?' * len(self.FOLDER_COLS))})",
                [(f["id"], f.get("parent_id"), f["name"], f.get("created"), f.get("color"), f.get("description"),
                  f.get("mtime") or 0, f.get("emoji") or None, f.get("cover") or None,
                  (json.dumps(f["rules"]) if isinstance(f.get("rules"), dict) else f.get("rules")) or None,
                  f.get("kind") or None) for f in folders],
            )
            self.conn.executemany(
                f"INSERT INTO placements({','.join(self.PLACEMENT_COLS)}) VALUES({','.join('?' * 8)})",
                [(p["chat_id"], p["msg_id"], p.get("folder_id"), p.get("alias"), int(bool(p.get("starred"))),
                  p.get("tags"), p.get("note"), p.get("mtime") or 0) for p in placements],
            )
            if saved is not None:
                self.x("DELETE FROM saved_searches")
                self.conn.executemany(
                    "INSERT INTO saved_searches(id, name, q, params, icon, created, mtime) VALUES(?,?,?,?,?,?,?)",
                    [(s["id"], s["name"], s.get("q"), s.get("params"), s.get("icon"), s.get("created"),
                      s.get("mtime") or 0) for s in saved])
            if tombstones is not None:
                self.x("DELETE FROM tombstones")
                self.conn.executemany("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES(?,?,?)",
                                      [(t["kind"], t["id"], t["at"]) for t in tombstones])
            new_alias = {(p["chat_id"], p["msg_id"]): p.get("alias") for p in placements if p.get("alias")}
            changed = {k for k in set(old_alias) | set(new_alias) if old_alias.get(k) != new_alias.get(k)}
            for cid, mid in changed:
                self._set_alias(cid, mid, new_alias.get((cid, mid)))

    def _set_alias(self, chat_id: int, msg_id: int, alias: Optional[str]) -> None:
        row = self.one("SELECT name, caption FROM files WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
        if row:
            self.x("UPDATE files SET alias=?, keywords=? WHERE chat_id=? AND msg_id=?",
                   (alias or None, textproc.keywords(row["name"], row["caption"], alias), chat_id, msg_id))

    def all_placements(self) -> list[dict]:
        return self.q(f"SELECT {','.join(self.PLACEMENT_COLS)} FROM placements")

    def get_placement(self, chat_id: int, msg_id: int) -> dict:
        return self.one("SELECT * FROM placements WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)) or {}

    def set_placement(self, chat_id: int, msg_id: int, folder_id: Optional[str] = None,
                      alias: Optional[str] = None, keep_alias: bool = True, keep_folder: bool = False,
                      **extra: Any) -> None:
        """Update one placement. extra may hold starred / tags / note (None = keep)."""
        cur = self.get_placement(chat_id, msg_id)
        if keep_alias and alias is None:
            alias = cur.get("alias")
        if keep_folder:
            folder_id = cur.get("folder_id")
        starred = int(bool(extra["starred"])) if extra.get("starred") is not None else int(cur.get("starred") or 0)
        tags = extra["tags"] if "tags" in extra and extra["tags"] is not None else cur.get("tags")
        note = extra["note"] if "note" in extra and extra["note"] is not None else cur.get("note")
        tags = tags or None
        note = note or None
        if folder_id is None and not alias and not starred and not tags and not note:
            self.x("DELETE FROM placements WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
            if cur:
                self.x("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('item', ?, ?)",
                       (f"{chat_id}:{msg_id}", now()))
        else:
            self.x(
                f"""INSERT INTO placements({','.join(self.PLACEMENT_COLS)}) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id, msg_id) DO UPDATE SET folder_id=excluded.folder_id, alias=excluded.alias,
                     starred=excluded.starred, tags=excluded.tags, note=excluded.note, mtime=excluded.mtime""",
                (chat_id, msg_id, folder_id, alias or None, starred, tags, note, int(time.time() * 1000)),
            )
            self.x("DELETE FROM tombstones WHERE kind='item' AND id=?", (f"{chat_id}:{msg_id}",))
        if (cur.get("alias") or None) != (alias or None):
            self._set_alias(chat_id, msg_id, alias)

    # -------------------------------------------------------------- transfers
    def add_transfer(self, **fields: Any) -> int:
        cols = [c for c in TRANSFER_COLS if c in fields]
        cur = self.x(
            f"INSERT INTO transfers({','.join(cols)}, created, updated) VALUES({','.join('?' * len(cols))}, ?, ?)",
            [fields[c] for c in cols] + [now(), now()],
        )
        return cur.lastrowid

    def update_transfer(self, tid: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE transfers SET {sets}, updated=? WHERE id=?", [*fields.values(), now(), tid])

    def get_transfer(self, tid: int) -> Optional[dict]:
        return self.one("SELECT * FROM transfers WHERE id=?", (tid,))

    def list_transfers(self) -> list[dict]:
        return self.q("SELECT * FROM transfers ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 "
                      "WHEN 'paused' THEN 2 WHEN 'error' THEN 3 ELSE 4 END, id DESC LIMIT 1000")


class _Tx:
    def __init__(self, conn: sqlite3.Connection, lock=None):
        self.conn = conn
        self.lock = lock
        self.nested = False

    def __enter__(self):
        if self.lock is not None:
            self.lock.acquire()
        if self.conn.in_transaction:
            self.nested = True
            return self
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            if self.lock is not None:
                self.lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not self.nested:
                self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            if self.lock is not None:
                self.lock.release()
        return False
