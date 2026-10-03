"""Durable offline pins, bounded automatic downloads, and actionable recovery state.

Pinned bytes live outside streaming/thumbnail caches and are never evicted by cache cleanup.
The index is additive and stored in the account database; no manual migration is needed.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from .settings import settings
from .transfers import TransferError, safe_filename
from .drive import DriveError

MB = 1024 * 1024


class Offline:
    def __init__(self, account):
        self.acc = account
        self.db = account.db
        self.root = account.dir / "offline"
        self.root.mkdir(exist_ok=True)
        self.db.x("CREATE TABLE IF NOT EXISTS offline_pins (chat_id INTEGER, msg_id INTEGER, name TEXT NOT NULL, "
                  "size INTEGER NOT NULL, path TEXT NOT NULL, tid INTEGER, error TEXT, PRIMARY KEY(chat_id,msg_id))")
        self.db.x("CREATE TABLE IF NOT EXISTS offline_exclusions (chat_id INTEGER, msg_id INTEGER, PRIMARY KEY(chat_id,msg_id))")
        self.db.x("CREATE TABLE IF NOT EXISTS offline_folders (id TEXT PRIMARY KEY)")
        self.db.x("CREATE TABLE IF NOT EXISTS offline_budget (day TEXT PRIMARY KEY, reserved INTEGER NOT NULL)")
        self.db.x("CREATE TABLE IF NOT EXISTS upload_receipts (key TEXT PRIMARY KEY, tid INTEGER NOT NULL)")

    def rows(self):
        rows = self.db.q("SELECT * FROM offline_pins ORDER BY name")
        for r in rows:
            p = Path(r["path"])
            t = self.db.get_transfer(r["tid"]) if r["tid"] else None
            ready = p.is_file() and p.stat().st_size == r["size"]
            r.update(status="ready" if ready else (t["status"] if t and t["status"] != "done" else "missing"),
                     done=r["size"] if ready else (t.get("done", 0) if t else 0),
                     error=r["error"] or (t.get("error") if t else None))
            # Authenticated native clients use this private path through Android FileProvider.
            r["local_path"] = r.pop("path")
        return rows

    def summary(self):
        rows = self.rows()
        day = dt.date.today().isoformat()
        budget = self.db.one("SELECT reserved FROM offline_budget WHERE day=?", (day,))
        return {"items": rows, "folders": self.db.q("SELECT id FROM offline_folders"),
                "reserved_bytes": sum(r["size"] for r in rows),
                "ready_bytes": sum(r["size"] for r in rows if r["status"] == "ready"),
                "automatic_today_bytes": budget["reserved"] if budget else 0,
                "limit_mb": settings.get("offline_limit_mb"), "automatic_daily_mb": settings.get("automatic_download_daily_mb")}

    def pin(self, items, folder_id=None, automatic=False):
        items = list(dict.fromkeys(items))
        explicit = set(items)
        for cid, mid in explicit:
            self.db.x("DELETE FROM offline_exclusions WHERE chat_id=? AND msg_id=?", (cid, mid))
        if folder_id is not None:
            self.acc.drive.require_files_folder(folder_id)
            if not self.db.get_folder(folder_id):
                raise TransferError("That folder no longer exists.")
            ids = [folder_id, *self.acc.drive._descendants(folder_id)]
            marks = ",".join("?" * len(ids))
            items += [(r["chat_id"], r["msg_id"]) for r in self.db.q(
                f"SELECT p.chat_id,p.msg_id FROM placements p JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id "
                f"WHERE p.folder_id IN ({marks})", ids)]
        files = []
        for cid, mid in dict.fromkeys(items):
            if (cid, mid) not in explicit and self.db.one("SELECT 1 FROM offline_exclusions WHERE chat_id=? AND msg_id=?", (cid, mid)):
                continue
            if self.db.one("SELECT 1 FROM offline_pins WHERE chat_id=? AND msg_id=?", (cid, mid)):
                continue
            f = self.db.get_file(cid, mid)
            if not f:
                raise TransferError("A selected file is no longer indexed.")
            files.append((cid, mid, f))
        used = self.db.one("SELECT COALESCE(SUM(size),0) AS n FROM offline_pins")["n"]
        limit = int(settings.get("offline_limit_mb")) * MB
        if used + sum(f["size"] for _, _, f in files) > limit:
            raise TransferError("Offline storage limit reached. Increase the limit or remove an offline copy.")
        if folder_id is not None:
            self.db.x("INSERT OR IGNORE INTO offline_folders(id) VALUES(?)", (folder_id,))
        for cid, mid, f in files:
            name = safe_filename(f.get("alias") or f["name"])
            path = self.root / f"{cid}_{mid}" / name
            self.db.x("INSERT INTO offline_pins(chat_id,msg_id,name,size,path) VALUES(?,?,?,?,?)",
                      (cid, mid, name, f["size"], str(path)))
        return self.refresh(automatic=automatic)

    def refresh(self, automatic=False):
        for row in self.db.q("SELECT * FROM offline_pins"):
            p = Path(row["path"])
            if p.is_file() and p.stat().st_size == row["size"]:
                continue
            t = self.db.get_transfer(row["tid"]) if row["tid"] else None
            if t and t["status"] in ("queued", "running"):
                continue
            if t and t["status"] == "paused":
                if not automatic: self.acc.transfers.resume(t["id"])
                continue
            if automatic and t and t["status"] == "error":
                continue  # errors need explicit retry; don't repeatedly spend a person's data
            try:
                day = dt.date.today().isoformat()
                used = self.db.one("SELECT reserved FROM offline_budget WHERE day=?", (day,))
                if automatic and (used["reserved"] if used else 0) + row["size"] > int(settings.get("automatic_download_daily_mb")) * MB:
                    raise TransferError("Daily automatic download budget reached. Retry manually or wait until tomorrow.")
                if automatic:
                    self.db.x("INSERT INTO offline_budget(day,reserved) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET reserved=reserved+excluded.reserved",
                              (day, row["size"]))
                tid = self.acc.transfers.add_download(row["chat_id"], row["msg_id"], exact_path=str(p))
                self.db.x("UPDATE offline_pins SET tid=?,error=NULL WHERE chat_id=? AND msg_id=?", (tid,row["chat_id"],row["msg_id"]))
            except (TransferError, OSError) as exc:
                self.db.x("UPDATE offline_pins SET error=? WHERE chat_id=? AND msg_id=?", (str(exc),row["chat_id"],row["msg_id"]))
        return self.summary()

    def sync_folders(self):
        self.acc._offline_error = ""
        for f in self.db.q("SELECT id FROM offline_folders"):
            try:
                self.pin([], folder_id=f["id"], automatic=True)
            except (TransferError, DriveError) as exc:
                # Surface the reason in Recovery without breaking the Telegram indexer.
                self.acc._offline_error = str(exc)
        self.refresh(automatic=True)

    def unpin(self, cid, mid):
        r = self.db.one("SELECT * FROM offline_pins WHERE chat_id=? AND msg_id=?", (cid,mid))
        if r:
            if r["tid"] and self.db.get_transfer(r["tid"]):
                self.acc.transfers.cancel(r["tid"])
            Path(r["path"]).unlink(missing_ok=True)
            self.db.x("INSERT OR IGNORE INTO offline_exclusions(chat_id,msg_id) VALUES(?,?)", (cid,mid))
            self.db.x("DELETE FROM offline_pins WHERE chat_id=? AND msg_id=?", (cid,mid))
        return self.summary()

    def file(self, cid, mid):
        r = self.db.one("SELECT * FROM offline_pins WHERE chat_id=? AND msg_id=?", (cid,mid))
        if not r or not Path(r["path"]).is_file() or Path(r["path"]).stat().st_size != r["size"]:
            raise TransferError("This offline copy is incomplete. Retry its download in Recovery.")
        return Path(r["path"])


def store(account):
    if not hasattr(account, "_offline_store"):
        account._offline_store = Offline(account)
    return account._offline_store


def recovery(account):
    issues = []
    for t in account.transfers.list():
        if t["status"] in ("error", "paused"):
            issues.append({"kind":"transfer", "id":str(t["id"]), "title":t["name"],
                           "detail":t.get("error") or "Transfer paused", "action":"resume"})
    if account.indexer.paused or account.indexer.phase in ("error", "paused") or account.indexer.error:
        issues.append({"kind":"index", "id":"index", "title":"Indexing needs attention",
                       "detail":account.indexer.error or "Indexing paused", "action":"resync"})
    if account.drive._dirty or account.drive.error:
        issues.append({"kind":"drive", "id":"drive", "title":"Folder changes need saving",
                       "detail":account.drive.error or "Changes are waiting to sync", "action":"sync"})
    offline = store(account)
    for row in offline.rows():
        if row["status"] in ("error", "missing", "cancelled") or row["error"]:
            issues.append({"kind":"offline", "id":f'{row["chat_id"]}:{row["msg_id"]}', "title":row["name"],
                           "detail":row["error"] or "Offline copy missing", "action":"retry"})
    if getattr(account, "_offline_error", ""):
        issues.append({"kind":"offline", "id":"folders", "title":"Pinned folder needs attention", "detail":account._offline_error, "action":"retry"})
    return {"issues":issues, "offline":offline.summary()}
