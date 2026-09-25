"""Duplicate copies: which indexed files are the same file, and which copy to show.

Two files are copies when
  * Telegram says so: the same document or photo id (a file forwarded or shared into other chats), or
  * they have the same original name and the same size (the same file downloaded and uploaded again),
    for files of 10 KB and more that have a real name.
Matches chain: if A and B are the same Telegram file and B and C have the same name and size, all three are
one group.

In each group the copies are ranked; with "Hide duplicates" on, a list shows only the best-ranked copy among
the files it would show (so a chat still shows its own files, and a search shows one card per file):
  1. a copy you put in a Drive folder     4. a copy in your own Drive channel or Saved Messages
  2. a starred copy                       5. the oldest copy
  3. a copy you downloaded

The table is rebuilt in the background whenever files, stars, folders or downloads change (a few seconds
for hundreds of thousands of files); only the rows that changed are written.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.dupes")

MIN_NAME_SIZE = 10 * 1024
CHECK_EVERY = 20      # seconds between "did anything change?" checks


def find_groups(rows: list[tuple]) -> dict[int, tuple[int, int, int, int]]:
    """rows: (id, chat_id, media_id, lname, size, date, filed, starred, downloaded, own).
    Returns {file_id: (group, rank, n, xc)} for files that have at least one copy."""
    parent: dict = {}

    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:   # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in rows:
        fid, _, media_id, lname, size = r[0], r[1], r[2], r[3], r[4]
        node = ("f", fid)
        if media_id is not None:
            union(node, ("m", media_id))
        if lname and size and size >= MIN_NAME_SIZE:
            union(node, ("n", lname, size))
    groups: dict = {}
    for r in rows:
        groups.setdefault(find(("f", r[0])), []).append(r)
    out: dict[int, tuple[int, int, int, int]] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        # Best first: in a folder, starred, downloaded, in your own channel / Saved Messages, oldest.
        members.sort(key=lambda r: (not r[6], not r[7], not r[8], not r[9], r[5] or 0, r[0]))
        grp = members[0][0]
        n = len(members)
        seen_chats: set = set()
        for rank, r in enumerate(members):
            xc = 1 if r[1] in seen_chats else 0
            seen_chats.add(r[1])
            out[r[0]] = (grp, rank, n, xc)
    return out


def extra_counts(groups: dict[int, tuple], info: dict[int, tuple]) -> dict[tuple, list]:
    """How many files (and bytes) hiding duplicates leaves out, for instant list totals.
    Keys (chat_id, kind): chat 0 = anywhere, else within that chat; kind '*' = all kinds together, else only
    copies of that kind (the tab for photos hides a photo only when a better *photo* copy exists)."""
    out: dict[tuple, list] = {}
    by_group: dict[int, list] = {}
    for fid, (grp, rank, _, _) in groups.items():
        by_group.setdefault(grp, []).append((rank, fid))

    def add(key, size):
        v = out.setdefault(key, [0, 0])
        v[0] += 1
        v[1] += size

    for members in by_group.values():
        members.sort()
        seen: set = set()
        for _, fid in members:
            chat, kind, size = info[fid]
            for key in ((0, "*"), (0, kind), (chat, "*"), (chat, kind)):
                if key in seen:
                    add(key, size)
                else:
                    seen.add(key)
    return out


class DupeIndex:
    def __init__(self, account: "Account"):
        self.acc = account
        self.state = "idle"
        self.error: Optional[str] = None
        self.stats: dict = {}
        self._sig = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def db_path(self) -> Path:
        return self.acc.db.path

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tgdrive-dupes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def poke(self) -> None:
        self._sig = None
        self._wake.set()

    def status(self) -> dict:
        return {"state": self.state, "error": self.error, **self.stats}

    # ------------------------------------------------------------- worker
    def _loop(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            try:
                self.stats = json.loads((conn.execute("SELECT value FROM meta WHERE key='dups_stats'").fetchone()
                                         or ["{}"])[0] or "{}")
            except (sqlite3.Error, ValueError):
                self.stats = {}
            while not self._stop.is_set():
                try:
                    sig = self._signature(conn)
                    if sig != self._sig:
                        self.rebuild(conn)
                        self._sig = sig
                    self.state, self.error = "ready", None
                except sqlite3.OperationalError as exc:
                    log.info("duplicates: retrying (%s)", exc)
                    time.sleep(3)
                    continue
                except Exception as exc:  # keep the app running; report in status
                    log.exception("finding duplicates failed")
                    self.state, self.error = "error", str(exc)
                    self._wake.wait(120)
                    self._wake.clear()
                    continue
                # Big libraries take a few seconds per pass: check less often while files keep arriving.
                self._wake.wait(max(CHECK_EVERY, 10 * float(self.stats.get("seconds") or 0)))
                self._wake.clear()
        finally:
            conn.close()

    @staticmethod
    def _signature(conn: sqlite3.Connection) -> tuple:
        """Cheap summary of everything the groups and ranks depend on."""
        files = conn.execute("SELECT TOTAL(n), TOTAL(bytes) FROM stats").fetchone()
        top = conn.execute("SELECT MAX(id) FROM files").fetchone()
        pl = conn.execute("SELECT COUNT(*), TOTAL(starred), MAX(mtime), COUNT(folder_id) FROM placements").fetchone()
        tr = conn.execute("SELECT COUNT(*) FROM transfers WHERE direction='down' AND status='done'").fetchone()
        return (tuple(files), top[0], tuple(pl), tr[0])

    def rebuild(self, conn: sqlite3.Connection) -> dict:
        t0 = time.time()
        self.state = "building"
        own = {r[0] for r in conn.execute("SELECT id FROM chats WHERE kind='saved'")}
        drive = conn.execute("SELECT value FROM meta WHERE key='drive_channel_id'").fetchone()
        if drive and str(drive[0]).lstrip("-").isdigit():
            own.add(int(drive[0]))
        downloaded = {(r[0], r[1]) for r in conn.execute(
            "SELECT chat_id, msg_id FROM transfers WHERE direction='down' AND status='done' AND chat_id IS NOT NULL")}
        # Only files that can have a copy: a shared Telegram id, or a shared (name, size).
        rows = conn.execute(f"""
            SELECT f.id, f.chat_id, f.media_id, LOWER(f.name), f.size, f.date,
                   p.folder_id IS NOT NULL, COALESCE(p.starred, 0), f.msg_id, f.kind
            FROM files f LEFT JOIN placements p ON p.chat_id=f.chat_id AND p.msg_id=f.msg_id
            WHERE f.media_id IN (SELECT media_id FROM files WHERE media_id IS NOT NULL
                                 GROUP BY media_id HAVING COUNT(*) > 1)
               OR (f.size >= {MIN_NAME_SIZE} AND COALESCE(f.name, '') <> '' AND (f.name COLLATE NOCASE, f.size) IN (
                   SELECT name COLLATE NOCASE, size FROM files WHERE size >= {MIN_NAME_SIZE} AND COALESCE(name, '') <> ''
                   GROUP BY name COLLATE NOCASE, size HAVING COUNT(*) > 1))""").fetchall()
        full = [(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6]), bool(r[7]), (r[1], r[8]) in downloaded, r[1] in own)
                for r in rows]
        new = find_groups(full)
        counts = extra_counts(new, {r[0]: (r[1], r[9], r[4] or 0) for r in rows})
        old = {r[0]: (r[1], r[2], r[3], r[4]) for r in conn.execute("SELECT file_id, grp, rank, n, xc FROM dups")}
        gone = [(k,) for k in old if k not in new]
        changed = [(k, *v) for k, v in new.items() if old.get(k) != v]
        extra = sum(1 for v in new.values() if v[1] > 0)
        size_of = {r[0]: r[4] or 0 for r in rows}
        saved = sum(size_of.get(k, 0) for k, v in new.items() if v[1] > 0)
        groups = len({v[0] for v in new.values()})
        stats = {"groups": groups, "extra": extra, "extra_bytes": saved, "built_at": int(time.time()),
                 "seconds": round(time.time() - t0, 2)}
        if gone or changed or stats.get("extra") != self.stats.get("extra"):
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Counts of the copies that hidden duplicates leave out, so list totals stay instant:
                # chat_id 0 = anywhere (all files), otherwise repeats within that one chat.
                conn.execute("CREATE TABLE IF NOT EXISTS dups_stats (chat_id INTEGER NOT NULL, kind TEXT NOT NULL, "
                             "n INTEGER NOT NULL, bytes INTEGER NOT NULL, PRIMARY KEY (chat_id, kind)) WITHOUT ROWID")
                conn.executemany("DELETE FROM dups WHERE file_id=?", gone)
                conn.executemany("INSERT INTO dups(file_id, grp, rank, n, xc) VALUES(?,?,?,?,?) ON CONFLICT(file_id) "
                                 "DO UPDATE SET grp=excluded.grp, rank=excluded.rank, n=excluded.n, xc=excluded.xc",
                                 changed)
                conn.execute("DELETE FROM dups_stats")
                conn.executemany("INSERT INTO dups_stats(chat_id, kind, n, bytes) VALUES(?,?,?,?)",
                                 [(c, k, n, b) for (c, k), (n, b) in counts.items()])
                conn.execute("INSERT INTO meta(key, value) VALUES('dups_stats', ?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(stats),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        self.stats = stats
        log.info("duplicates: %d groups, %d extra copies (%d changed, %d removed) in %.2f s",
                 groups, extra, len(changed), len(gone), time.time() - t0)
        return stats
