"""Two-way sync between a folder on this computer and a TG Drive folder (Dropbox-style).

Each pair keeps a record of how every file looked after the last sync (size and
modification time on disk, which Telegram message on the other side). Comparing
both sides with that record tells what changed where:

  new or changed on disk        → uploaded into the matching TG Drive folder
  new or changed in TG Drive    → downloaded
  changed on both sides         → the disk version is kept as "name (conflicted copy …)"
                                  and uploaded too; the TG Drive version takes the name
  deleted on disk               → taken out of the TG Drive folder (the message stays in
                                  Telegram unless "also delete from Telegram" is on)
  removed from the TG Drive folder → the file moves to <folder>/.tgdrive-trash, never deleted

Safety: a new pair only shows what it would do until you approve it, and a run that
would remove more than a handful of files (e.g. a disconnected drive) stops and asks.
Uploads and downloads go through the normal transfer queue (pause, resume, retry).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .transfers import TransferError, safe_filename

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.sync")

TRASH = ".tgdrive-trash"
MAX_REMOVALS = 25          # more than this in one run needs approval …
MAX_REMOVAL_SHARE = 0.3    # … or more than 30% of the pair's files
IGNORE_SUFFIXES = (".part", ".part.map", "~", ".swp", ".tmp", ".crdownload")


class SyncError(Exception):
    pass


def _ignored(name: str) -> bool:
    return name.startswith(".") or name.endswith(IGNORE_SUFFIXES) or name in ("desktop.ini", "Thumbs.db")


class SyncEngine:
    def __init__(self, account: "Account"):
        self.acc = account
        self.task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self.live: dict[int, dict] = {}   # pair id -> {"state", "plan", "progress"}
        self._lock = asyncio.Lock()

    @property
    def db(self):
        return self.acc.db

    # -------------------------------------------------------------- control
    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    def poke(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        from .settings import settings
        await asyncio.sleep(8)
        while True:
            try:
                if settings.get("sync_enabled", True) and self.acc.status == "online":
                    for pair in self.db.q("SELECT * FROM sync_pairs WHERE enabled=1 AND approved=1"):
                        await self.run_pair(pair["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sync loop failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), int(settings.get("sync_interval") or 60))
                await asyncio.sleep(2)
            except asyncio.TimeoutError:
                pass

    # ---------------------------------------------------------------- pairs
    def pairs(self) -> list[dict]:
        out = []
        for p in self.db.q("SELECT * FROM sync_pairs ORDER BY id"):
            p["stats"] = json.loads(p["stats"] or "{}")
            p["folder_path"] = self.acc.drive.path(p["folder_id"])
            p["files"] = self.db.one("SELECT COUNT(*) AS n FROM sync_files WHERE pair_id=? AND rel NOT LIKE '%/'",
                                     (p["id"],))["n"]
            p["pending"] = self.db.one("SELECT COUNT(*) AS n FROM sync_files WHERE pair_id=? AND pending IS NOT NULL",
                                       (p["id"],))["n"]
            live = self.live.get(p["id"], {})
            p["plan"] = live.get("plan")
            if live.get("state"):
                p["state"] = live["state"]
            out.append(p)
        return out

    async def add_pair(self, local_path: str, folder_id: str) -> dict:
        root = Path(local_path).expanduser()
        if not root.is_absolute():
            raise SyncError("Choose a full folder path, like /home/you/Documents/Notes.")
        root = root.resolve()
        if not root.is_dir():
            raise SyncError("That folder doesn't exist on this computer.")
        if root == Path.home().resolve() or str(root) == "/":
            raise SyncError("Choose a specific folder, not your whole home folder.")
        if not self.db.get_folder(folder_id):
            raise SyncError("That TG Drive folder no longer exists.")
        for p in self.db.q("SELECT local_path, folder_id FROM sync_pairs"):
            other = Path(p["local_path"])
            if root == other or root in other.parents or other in root.parents:
                raise SyncError(f"{other} is already synced; synced folders can't overlap.")
            if p["folder_id"] == folder_id:
                raise SyncError("That TG Drive folder is already synced with another folder.")
        cur = self.db.x("INSERT INTO sync_pairs(local_path, folder_id, enabled, created, state, approved) "
                        "VALUES(?,?,1,?,?,0)", (str(root), folder_id, int(time.time()), "needs approval"))
        pid = cur.lastrowid
        await self.run_pair(pid, dry=True)
        return next(p for p in self.pairs() if p["id"] == pid)

    def approve(self, pid: int) -> None:
        self.db.x("UPDATE sync_pairs SET approved=1, state='waiting', error=NULL WHERE id=?", (pid,))
        self.live.pop(pid, None)
        self.poke()

    def set_enabled(self, pid: int, on: bool) -> None:
        self.db.x("UPDATE sync_pairs SET enabled=? WHERE id=?", (int(on), pid))
        self.poke()

    def remove(self, pid: int) -> None:
        self.db.x("DELETE FROM sync_pairs WHERE id=?", (pid,))
        self.db.x("DELETE FROM sync_files WHERE pair_id=?", (pid,))
        self.live.pop(pid, None)

    # -------------------------------------------------------------- scanning
    def _scan_local(self, root: Path) -> tuple[dict[str, tuple[int, float]], set[str]]:
        files: dict[str, tuple[int, float]] = {}
        dirs: set[str] = set()
        for cur, dnames, fnames in os.walk(root):
            dnames[:] = sorted(d for d in dnames if not _ignored(d) and d != TRASH)
            rel_dir = os.path.relpath(cur, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
            if rel_dir:
                dirs.add(rel_dir)
            for n in fnames:
                if _ignored(n):
                    continue
                p = Path(cur) / n
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size == 0 or not p.is_file():
                    continue
                files[rel_dir + n] = (st.st_size, st.st_mtime)
        return files, dirs

    def _scan_remote(self, folder_id: str) -> tuple[dict[str, dict], dict[str, str]]:
        """rel path -> file row; rel dir ('a/b/') -> folder id."""
        kids: dict[Optional[str], list[dict]] = {}
        for f in self.db.q("SELECT id, parent_id, name FROM folders"):
            kids.setdefault(f["parent_id"], []).append(f)
        dirs: dict[str, str] = {"": folder_id}
        stack = [(folder_id, "")]
        while stack:
            fid, rel = stack.pop()
            for k in sorted(kids.get(fid, []), key=lambda x: x["name"].lower()):
                r = f"{rel}{safe_filename(k['name'])}/"
                if r not in dirs:
                    dirs[r] = k["id"]
                    stack.append((k["id"], r))
        by_folder = {v: k for k, v in dirs.items()}
        marks = ",".join("?" * len(by_folder))
        rows = self.db.q(f"SELECT p.folder_id, f.chat_id, f.msg_id, COALESCE(f.alias, f.name) AS name, f.size, f.date "
                         f"FROM placements p JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id "
                         f"WHERE p.folder_id IN ({marks}) ORDER BY f.chat_id, f.msg_id", list(by_folder))
        files: dict[str, dict] = {}
        for r in rows:
            base = by_folder[r["folder_id"]]
            name = safe_filename(r["name"] or "file")
            rel, n = base + name, 1
            while rel in files:
                n += 1
                stem, dot, ext = name.rpartition(".")
                rel = base + (f"{stem} ({n}).{ext}" if dot else f"{name} ({n})")
            files[rel] = r
        return files, dirs

    # ------------------------------------------------------------------ run
    async def run_pair(self, pid: int, dry: bool = False, force: bool = False) -> dict:
        async with self._lock:
            pair = self.db.one("SELECT * FROM sync_pairs WHERE id=?", (pid,))
            if not pair:
                raise SyncError("Unknown sync pair.")
            if not dry and not pair["approved"]:
                dry = True
            try:
                t0 = time.time()
                log.debug("sync pair %s (%s) run: dry=%s force=%s", pid, pair["local_path"], dry, force)
                plan = await self._run(pair, dry=dry or False, force=force)
                log.debug("sync pair %s finished in %.1f s: %s", pid, time.time() - t0,
                          {k: (len(v) if isinstance(v, list) else v) for k, v in (plan or {}).items()})
                return plan
            except SyncError as exc:
                self._state(pid, "stopped", str(exc))
                return {"error": str(exc)}
            except Exception as exc:
                log.exception("sync of %s failed", pair["local_path"])
                self._state(pid, "error", f"{exc.__class__.__name__}: {exc}")
                return {"error": str(exc)}

    def _state(self, pid: int, state: str, error: Optional[str] = None, stats: Optional[dict] = None) -> None:
        self.db.x("UPDATE sync_pairs SET state=?, error=?, last_run=?" + (", stats=?" if stats is not None else "") +
                  " WHERE id=?", (state, error, int(time.time()), *([json.dumps(stats)] if stats is not None else []),
                                  pid))
        self.live.setdefault(pid, {})["state"] = state

    async def _run(self, pair: dict, dry: bool, force: bool) -> dict:
        pid = pair["id"]
        root = Path(pair["local_path"])
        if not root.is_dir():
            raise SyncError(f"{root} isn't available (unplugged or moved). Nothing was changed.")
        if not self.acc.drive.loaded:
            await self.acc.drive.load()
        folder_id = pair["folder_id"]
        if not self.db.get_folder(folder_id):
            raise SyncError("The TG Drive folder of this pair was deleted. Remove the pair or choose another folder.")
        loop = asyncio.get_running_loop()
        local, ldirs = await loop.run_in_executor(None, self._scan_local, root)
        remote, rdirs = self._scan_remote(folder_id)
        base = {r["rel"]: r for r in self.db.q("SELECT * FROM sync_files WHERE pair_id=?", (pid,))}

        plan: dict[str, list] = {"upload": [], "download": [], "conflict": [], "unfile": [], "trash": [],
                                 "mkdir_local": [], "mkdir_remote": [], "same": [], "busy": []}
        # 1) finish transfers that were started by an earlier run
        finished = False
        for rel, b in list(base.items()):
            if b["pending"]:
                st = self.db.one("SELECT status, chat_id, msg_id FROM transfers WHERE id=?", (b["tid"],)) \
                    if b["tid"] else None
                if st and st["status"] in ("queued", "running", "paused", "error"):
                    plan["busy"].append(rel)
                    continue
                if not dry:
                    await self._finish(pid, root, rel, b, st)
                    finished = True
        if finished:
            base = {r["rel"]: r for r in self.db.q("SELECT * FROM sync_files WHERE pair_id=?", (pid,))}
            remote, rdirs = self._scan_remote(folder_id)
            local, ldirs = await loop.run_in_executor(None, self._scan_local, root)
        busy = set(plan["busy"])
        # 2) compare the three sides
        for rel in sorted(set(local) | set(remote) | {k for k in base if not k.endswith("/")}):
            if rel in busy or rel.endswith("/"):
                continue
            L, R, B = local.get(rel), remote.get(rel), base.get(rel)
            lch = bool(L and (not B or B["size"] != L[0] or abs((B["mtime"] or 0) - L[1]) > 2))
            rch = bool(R and (not B or (B["chat_id"], B["msg_id"]) != (R["chat_id"], R["msg_id"])))
            if L and R and not B:
                plan["same" if L[0] == R["size"] else "conflict"].append(rel)
            elif L and not R and not B:
                plan["upload"].append(rel)
            elif R and not L and not B:
                plan["download"].append(rel)
            elif L and R and B:
                if lch and rch:
                    plan["conflict"].append(rel)
                elif lch:
                    plan["upload"].append(rel)
                elif rch:
                    plan["download"].append(rel)
            elif L and B and not R:
                plan["upload" if lch else "trash"].append(rel)
            elif R and B and not L:
                plan["download" if rch else "unfile"].append(rel)
            elif B and not L and not R:
                if not dry:
                    self.db.x("DELETE FROM sync_files WHERE pair_id=? AND rel=?", (pid, rel))
        plan["mkdir_local"] = sorted(d for d in rdirs if d and d not in ldirs)
        plan["mkdir_remote"] = sorted(d for d in ldirs if d not in rdirs)
        summary = {k: len(v) for k, v in plan.items()}
        summary["upload_bytes"] = sum(local[r][0] for r in plan["upload"] if r in local)
        summary["download_bytes"] = sum(remote[r]["size"] or 0 for r in plan["download"] if r in remote)
        self.live.setdefault(pid, {})["plan"] = {**summary, "examples": {k: v[:8] for k, v in plan.items()
                                                                          if v and k != "same"}}
        if dry:
            self._state(pid, "needs approval" if not pair["approved"] else "preview", None, summary)
            return summary
        removals = len(plan["trash"]) + len(plan["unfile"])
        known = max(1, len([k for k in base if not k.endswith("/")]))
        if not force and removals > MAX_REMOVALS and removals > known * MAX_REMOVAL_SHARE:
            self.db.x("UPDATE sync_pairs SET approved=0 WHERE id=?", (pid,))
            self._state(pid, "needs approval", f"This run would remove {removals} files. Check the folder, then "
                                               f"approve to continue.", summary)
            return summary
        # 3) act
        for d in plan["mkdir_local"]:
            (root / d).mkdir(parents=True, exist_ok=True)
        for d in plan["mkdir_remote"]:
            await self.acc.drive.ensure_path(folder_id, [p for p in d.split("/") if p])
        if plan["mkdir_remote"]:
            remote, rdirs = self._scan_remote(folder_id)
        for rel in plan["same"]:
            self._record(pid, rel, local[rel], remote[rel])
        for rel in plan["conflict"]:
            p = root / rel
            stem, dot, ext = p.name.rpartition(".")
            tag = time.strftime("%Y-%m-%d %H%M")
            copy_name = f"{stem} (conflicted copy {tag}).{ext}" if dot else f"{p.name} (conflicted copy {tag})"
            try:
                p.rename(p.with_name(copy_name))
            except OSError as exc:
                log.warning("sync: could not keep conflicted copy of %s: %s", p, exc)
                continue
            self._download(pid, root, rel, remote[rel])
        for rel in plan["upload"]:
            dir_rel = rel.rpartition("/")[0]
            fid = rdirs.get(dir_rel + "/" if dir_rel else "") or await self.acc.drive.ensure_path(
                folder_id, [x for x in dir_rel.split("/") if x])
            old = remote.get(rel)
            try:
                tid = self.acc.transfers._add_path(root / rel, fid, "", None, batch=f"sync:{pid}")
            except (TransferError, OSError) as exc:
                log.warning("sync: can't upload %s: %s", rel, exc)
                continue
            self._pending(pid, rel, "up" + (f":{old['chat_id']}:{old['msg_id']}" if old else ""), tid,
                          local.get(rel))
        for rel in plan["download"]:
            self._download(pid, root, rel, remote[rel])
        for rel in plan["trash"]:
            self._to_trash(root, rel)
            self.db.x("DELETE FROM sync_files WHERE pair_id=? AND rel=?", (pid, rel))
        if plan["unfile"]:
            await self._remove_remote(pid, [remote[r] for r in plan["unfile"]])
            for rel in plan["unfile"]:
                self.db.x("DELETE FROM sync_files WHERE pair_id=? AND rel=?", (pid, rel))
        pending = self.db.one("SELECT COUNT(*) AS n FROM sync_files WHERE pair_id=? AND pending IS NOT NULL",
                              (pid,))["n"]
        acted = sum(summary[k] for k in ("upload", "download", "conflict", "trash", "unfile"))
        self._state(pid, "syncing" if pending else "up to date", None, summary)
        if acted:
            self.db.log_activity("sync", f"{root.name}: {summary['upload']} up, {summary['download']} down, "
                                         f"{summary['conflict']} conflicts, {summary['trash'] + summary['unfile']} removed")
        return summary

    # ---------------------------------------------------------------- helpers
    def _record(self, pid: int, rel: str, lstat: tuple[int, float], r: dict) -> None:
        self.db.x("INSERT OR REPLACE INTO sync_files(pair_id, rel, size, mtime, chat_id, msg_id, pending, tid) "
                  "VALUES(?,?,?,?,?,?,NULL,NULL)", (pid, rel, lstat[0], lstat[1], r["chat_id"], r["msg_id"]))

    def _pending(self, pid: int, rel: str, what: str, tid: int, lstat=None, r: Optional[dict] = None) -> None:
        cur = self.db.one("SELECT * FROM sync_files WHERE pair_id=? AND rel=?", (pid, rel)) or {}
        self.db.x("INSERT OR REPLACE INTO sync_files(pair_id, rel, size, mtime, chat_id, msg_id, pending, tid) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (pid, rel, cur.get("size"), cur.get("mtime"),
                   (r or {}).get("chat_id", cur.get("chat_id")), (r or {}).get("msg_id", cur.get("msg_id")), what, tid))

    def _download(self, pid: int, root: Path, rel: str, r: dict) -> None:
        tid = self.acc.transfers.add_download(r["chat_id"], r["msg_id"], batch=f"sync:{pid}",
                                              exact_path=str(root / rel))
        self._pending(pid, rel, "down", tid, r=r)

    async def _finish(self, pid: int, root: Path, rel: str, b: dict, st: Optional[dict]) -> None:
        """A transfer from an earlier run ended: record the new state (or forget it to retry)."""
        ok = st and st["status"] == "done"
        p = root / rel
        if not ok or not p.exists():
            self.db.x("UPDATE sync_files SET pending=NULL, tid=NULL WHERE pair_id=? AND rel=?", (pid, rel))
            if not b["size"]:  # never synced before: forget it entirely, next run starts over
                self.db.x("DELETE FROM sync_files WHERE pair_id=? AND rel=?", (pid, rel))
            return
        stt = p.stat()
        if b["pending"].startswith("up"):
            cid, mid = st["chat_id"], st["msg_id"]
            parts = b["pending"].split(":")
            if len(parts) == 3:  # a newer version replaced this file: take the old one out of the folder
                old = (int(parts[1]), int(parts[2]))
                if old != (cid, mid) and self.db.get_file(*old):
                    await self.acc.drive.place([old], None, undo=False)
        else:
            cid, mid = b["chat_id"], b["msg_id"]
        self.db.x("UPDATE sync_files SET size=?, mtime=?, chat_id=?, msg_id=?, pending=NULL, tid=NULL "
                  "WHERE pair_id=? AND rel=?", (stt.st_size, stt.st_mtime, cid, mid, pid, rel))

    def _to_trash(self, root: Path, rel: str) -> None:
        src = root / rel
        if not src.exists():
            return
        dst = root / TRASH / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst = dst.with_name(f"{dst.stem} {time.strftime('%Y%m%d-%H%M%S')}{dst.suffix}")
        try:
            shutil.move(str(src), str(dst))
        except OSError as exc:
            log.warning("sync: could not move %s to the sync trash: %s", src, exc)

    async def _remove_remote(self, pid: int, rows: list[dict]) -> None:
        from .settings import settings
        items = [(r["chat_id"], r["msg_id"]) for r in rows]
        if settings.get("sync_delete_remote"):
            drive_items = [i for i in items if i[0] == self.acc.drive.channel_id]
            if drive_items:
                try:
                    peer = await self.acc.peer(self.acc.drive.channel_id)
                    await self.acc.client.delete_messages(peer, [m for _, m in drive_items], revoke=True)
                    self.db.delete_files(self.acc.drive.channel_id, [m for _, m in drive_items])
                except Exception as exc:
                    log.warning("sync: could not delete from Telegram: %s", exc)
        await self.acc.drive.place(items, None, undo=False)
