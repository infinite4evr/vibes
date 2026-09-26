"""Storage analytics, duplicates, database maintenance, exports, logs, app lock and data import."""
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import config
from .tasks import spawn
from .db import Reader
from .settings import settings

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.maintenance")


# ---------------------------------------------------------------------- logs
# Two files: tgdrive.log (always, INFO and up) and, while "Detailed debug logging" is on,
# tgdrive-debug.log with everything: every request with its timing, what the page did (clicks,
# navigation, errors), transfers, streaming, indexing, search plans, crashes with full tracebacks.
DEBUG_FORMAT = ("%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] %(name)s "
                "%(module)s:%(lineno)d %(funcName)s(): %(message)s")
NOISY = ("telethon", "asyncio", "PIL", "multipart", "python_multipart", "hpack", "httpx", "httpcore",
         "charset_normalizer", "urllib3", "filelock", "uvicorn.access")
_debug_handler: Optional[RotatingFileHandler] = None
_debug_since: float = 0.0


def log_path() -> Path:
    return config.LOG_DIR / "tgdrive.log"


def debug_log_path() -> Path:
    return config.LOG_DIR / "tgdrive-debug.log"


def setup_logging(level: int = logging.INFO) -> Path:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path()
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path for h in root.handlers):
        fh = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"))
        fh.setLevel(level)
        root.addHandler(fh)
    from .diagnostics import ring
    if ring not in root.handlers:
        root.addHandler(ring)   # the last lines go into crash reports
    root.setLevel(level)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    init_debug_logging()
    return path


_listening = False


def init_debug_logging() -> None:
    """Follow the "Detailed debug logging" setting (safe to call more than once)."""
    global _listening
    if not _listening:
        _listening = True
        settings.on_change(lambda changed: "debug_logging" in changed and set_debug_logging(
            bool(settings.get("debug_logging"))))
    set_debug_logging(bool(settings.get("debug_logging")))


def debug_enabled() -> bool:
    return _debug_handler is not None


def set_debug_logging(on: bool) -> None:
    """Turn the detailed debug log on or off, right away (no restart)."""
    global _debug_handler, _debug_since
    root = logging.getLogger()
    if on and _debug_handler is None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Everything that already writes somewhere (the normal log, the terminal) stays at INFO.
        for h in root.handlers:
            if h.level == logging.NOTSET:
                h.setLevel(logging.INFO)
        h = RotatingFileHandler(debug_log_path(), maxBytes=20 * 1024 * 1024, backupCount=4, encoding="utf-8")
        h.setLevel(logging.DEBUG)
        h.setFormatter(logging.Formatter(DEBUG_FORMAT, "%Y-%m-%d %H:%M:%S"))
        root.addHandler(h)
        root.setLevel(logging.DEBUG)
        for name in NOISY:
            logging.getLogger(name).setLevel(logging.INFO if name in ("telethon", "asyncio") else logging.WARNING)
        _debug_handler, _debug_since = h, time.time()
        from . import diagnostics
        info = diagnostics.system_info()
        log.info("===== detailed debug logging ON (TG Drive %s, %s, python %s) =====", config.VERSION,
                 info.get("platform"), (info.get("python") or "").split()[0])
        log.debug("system: %s", json.dumps(info, default=str))
        log.debug("settings: %s", json.dumps({k: v for k, v in settings.public().items()
                                              if k not in ("dav_secret", "proxy_user")}, default=str))
    elif not on and _debug_handler is not None:
        log.info("===== detailed debug logging OFF (was on for %d s) =====", time.time() - _debug_since)
        h, _debug_handler = _debug_handler, None
        root.removeHandler(h)
        h.close()
        root.setLevel(logging.INFO)
        logging.getLogger("telethon").setLevel(logging.WARNING)


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 400_000))
        data = fh.read().decode("utf-8", "replace")
    return "\n".join(data.splitlines()[-lines:])


def tail_log(lines: int = 400) -> str:
    return _tail(log_path(), lines)


def tail_debug_log(lines: int = 400) -> str:
    return _tail(debug_log_path(), lines)


def log_files() -> list[dict]:
    out = []
    for p in sorted(config.LOG_DIR.glob("tgdrive*.log*")):
        try:
            out.append({"name": p.name, "bytes": p.stat().st_size})
        except OSError:
            pass
    return out


def clear_logs() -> dict:
    """Empty every log file (the open ones are truncated in place) and delete rotated copies."""
    freed = 0
    open_files = set()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            p = Path(h.baseFilename)
            open_files.add(p)
            h.acquire()
            try:
                if h.stream:
                    h.stream.flush()
                    freed += p.stat().st_size if p.exists() else 0
                    h.stream.seek(0)
                    h.stream.truncate()
            except OSError as exc:
                log.warning("could not clear %s: %s", p, exc)
            finally:
                h.release()
    for p in config.LOG_DIR.glob("tgdrive*.log*"):
        if p in open_files:
            continue
        try:
            freed += p.stat().st_size
            if p.name in ("tgdrive.log", "tgdrive-debug.log"):
                p.write_text("", encoding="utf-8")
            else:
                p.unlink()
        except OSError:
            pass
    log.info("logs cleared (%d bytes)", freed)
    return {"freed": freed}


# ------------------------------------------------------------------ storage
_storage_cache: dict[int, tuple[float, dict]] = {}


async def storage(acc: "Account") -> dict:
    hit = _storage_cache.get(acc.uid)
    if hit and time.time() - hit[0] < 300:
        return hit[1]

    def job(r: Reader) -> dict:
        by_kind = r.q("SELECT kind, SUM(n) AS n, SUM(bytes) AS bytes FROM stats GROUP BY kind ORDER BY bytes DESC")
        by_chat = r.q("SELECT s.chat_id, c.title, c.kind, SUM(s.n) AS n, SUM(s.bytes) AS bytes FROM stats s "
                      "LEFT JOIN chats c ON c.id=s.chat_id GROUP BY s.chat_id ORDER BY bytes DESC LIMIT 40")
        by_source = r.q("SELECT CASE c.kind WHEN 'supergroup' THEN 'group' ELSE c.kind END AS kind, SUM(s.n) AS n, "
                        "SUM(s.bytes) AS bytes FROM stats s JOIN chats c ON c.id=s.chat_id GROUP BY 1 ORDER BY bytes DESC")
        by_year = r.q("SELECT strftime('%Y', date, 'unixepoch') AS year, COUNT(*) AS n, SUM(size) AS bytes "
                      "FROM files GROUP BY year ORDER BY year")
        by_ext = r.q("SELECT COALESCE(ext, '') AS ext, COUNT(*) AS n, SUM(size) AS bytes FROM files "
                     "GROUP BY ext ORDER BY bytes DESC LIMIT 25")
        largest = r.q("SELECT chat_id, msg_id, COALESCE(alias, name) AS name, size, kind, ext, chat_title, date "
                      "FROM files ORDER BY size DESC LIMIT 50")
        tot = r.one("SELECT COALESCE(SUM(n),0) AS n, COALESCE(SUM(bytes),0) AS bytes FROM stats")
        dup = r.one("SELECT COUNT(*) AS groups, COALESCE(SUM(extra_bytes),0) AS bytes FROM (SELECT (COUNT(*)-1)*MAX(size) "
                    "AS extra_bytes FROM files WHERE media_id IS NOT NULL GROUP BY media_id HAVING COUNT(*)>1)")
        return {"total": tot, "by_kind": by_kind, "by_chat": by_chat, "by_source": by_source, "by_year": by_year,
                "by_ext": by_ext, "largest": largest, "duplicates": dup}

    res = await acc.db.read.run(job, timeout=90)
    res["local"] = {
        "index_db": _size(acc.db.path) + _size(Path(str(acc.db.path) + "-wal")),
        "thumbs": acc.thumbs.usage()["bytes"],
        "stream_cache": acc.streamer.cache_usage()["bytes"],
        "semantic": sum(_size(p) for p in (acc.dir / "semantic").glob("*")),
    }
    _storage_cache[acc.uid] = (time.time(), res)
    return res


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


async def duplicates(acc: "Account", mode: str = "exact", offset: int = 0, limit: int = 50) -> dict:
    """exact: the same Telegram file in several places. similar: same name and size."""
    if mode == "similar":
        group = "COALESCE(alias, name) COLLATE NOCASE, size"
        where = "size > 0"
    else:
        group = "media_id"
        where = "media_id IS NOT NULL"

    def job(r: Reader) -> dict:
        groups = r.q(f"SELECT {group.split(' COLLATE')[0].split(',')[0]} AS k, COUNT(*) AS n, MAX(size) AS size, "
                     f"(COUNT(*)-1)*MAX(size) AS waste, MIN(id) AS any_id FROM files WHERE {where} "
                     f"GROUP BY {group} HAVING COUNT(*)>1 ORDER BY waste DESC LIMIT ? OFFSET ?", (limit, offset))
        out = []
        for g in groups:
            if mode == "similar":
                one = r.one("SELECT COALESCE(alias, name) AS name, size FROM files WHERE id=?", (g["any_id"],))
                rows = r.q("SELECT f.chat_id, f.msg_id, COALESCE(f.alias, f.name) AS name, f.size, f.kind, f.ext, "
                           "f.chat_title, f.date, f.has_thumb, p.folder_id FROM files f LEFT JOIN placements p ON "
                           "p.chat_id=f.chat_id AND p.msg_id=f.msg_id WHERE COALESCE(f.alias, f.name)=? COLLATE "
                           "NOCASE AND f.size=? ORDER BY f.date LIMIT 50", (one["name"], one["size"]))
            else:
                rows = r.q("SELECT f.chat_id, f.msg_id, COALESCE(f.alias, f.name) AS name, f.size, f.kind, f.ext, "
                           "f.chat_title, f.date, f.has_thumb, p.folder_id FROM files f LEFT JOIN placements p ON "
                           "p.chat_id=f.chat_id AND p.msg_id=f.msg_id WHERE f.media_id=? ORDER BY f.date LIMIT 50",
                           (g["k"],))
            out.append({"n": g["n"], "size": g["size"], "waste": g["waste"], "files": rows})
        return {"groups": out, "offset": offset, "more": len(groups) == limit}

    return await acc.db.read.run(job, timeout=90)


# -------------------------------------------------------------- maintenance
async def run_task(acc: "Account", task: str) -> dict:
    db = acc.db
    t0 = time.time()
    if task == "optimize":
        def job(r: Reader):
            r.conn.execute("PRAGMA optimize")
            if db.search_ready:
                r.conn.execute("INSERT INTO search_fts(search_fts) VALUES('optimize')")
                r.conn.execute("INSERT INTO names_tri(names_tri) VALUES('optimize')")
            r.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return {}
        await db.read.run(job, timeout=600)
    elif task == "vacuum":
        def job(r: Reader):
            r.conn.execute("VACUUM")
            return {}
        await db.read.run(job, timeout=1800)
    elif task == "integrity":
        def job(r: Reader):
            res = [row[0] for row in r.conn.execute("PRAGMA quick_check").fetchall()]
            if db.search_ready:
                try:
                    r.conn.execute("INSERT INTO search_fts(search_fts, rank) VALUES('integrity-check', 1)")
                except Exception as exc:
                    res.append(f"search index: {exc}")
            return {"result": res}
        out = await db.read.run(job, timeout=1800)
        return {"ok": out["result"] == ["ok"], "details": out["result"][:20], "seconds": round(time.time() - t0, 1)}
    elif task == "rebuild_search":
        def job(r: Reader):
            r.conn.execute("UPDATE files SET fts_v=0")
            r.conn.execute("INSERT INTO search_fts(search_fts) VALUES('delete-all')")
            r.conn.execute("INSERT INTO names_tri(names_tri) VALUES('delete-all')")
            r.conn.execute("UPDATE meta SET value='building' WHERE key='search_state'")
            r.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('search_total', "
                           "(SELECT COUNT(*) FROM files))")
            return {}
        await db.read.run(job, timeout=600)
        acc.launch_search_rebuild = True
        acc._search_builder = spawn(acc._build_search(), "rebuild search index")
    elif task == "rebuild_semantic":
        acc.semantic.rebuild()
    elif task == "clear_thumbs":
        return {"removed": acc.thumbs.clear()}
    elif task == "clear_stream_cache":
        return {"removed": acc.streamer.clear_cache()}
    elif task == "stats":
        def job(r: Reader):
            r.conn.execute("DELETE FROM stats")
            r.conn.execute("INSERT INTO stats(chat_id, kind, n, bytes) SELECT chat_id, kind, COUNT(*), "
                           "COALESCE(SUM(size),0) FROM files GROUP BY chat_id, kind")
            r.conn.execute("UPDATE chats SET file_count=COALESCE((SELECT SUM(n) FROM stats s WHERE s.chat_id=chats.id),0),"
                           " total_bytes=COALESCE((SELECT SUM(bytes) FROM stats s WHERE s.chat_id=chats.id),0)")
            return {}
        await db.read.run(job, timeout=600)
    else:
        raise ValueError("Unknown maintenance task.")
    return {"ok": True, "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------ export
CSV_COLS = ["name", "original_name", "kind", "ext", "size", "date", "chat", "chat_id", "msg_id", "link",
            "folder", "tags", "starred", "caption"]


async def export_csv(acc: "Account", params: dict, folder_path) -> bytes:
    from .links import message_link
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLS)
    p = dict(params, limit=500, sort=params.get("sort") or "date")
    p.pop("cursor", None)
    n = 0
    while n < 250_000:
        res = await acc.search.files(p)
        for r in res["items"]:
            w.writerow([r.get("alias") or r["name"], r["name"], r["kind"], r.get("ext") or "", r.get("size") or 0,
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("date") or 0)), r.get("chat_title"),
                        r["chat_id"], r["msg_id"],
                        message_link(r["chat_id"], r.get("chat_kind"), r.get("chat_username"), r["msg_id"]) or "",
                        " / ".join(x["name"] for x in folder_path(r.get("folder_id"))) if r.get("folder_id") else "",
                        r.get("tags") or "", int(bool(r.get("starred"))), (r.get("caption") or "")[:1000]])
            n += 1
        if not res.get("next"):
            break
        p["cursor"] = res["next"]
    return ("﻿" + out.getvalue()).encode("utf-8")


# -------------------------------------------------------------------- lock
class AppLock:
    def __init__(self):
        self.unlocked = not settings.get("lock_enabled")
        self.last_activity = time.time()

    @staticmethod
    def _hash(passcode: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", passcode.encode(), bytes.fromhex(salt), 200_000).hex()

    def locked(self) -> bool:
        if not settings.get("lock_enabled") or not settings.get("lock_hash"):
            return False
        mins = int(settings.get("lock_after_minutes") or 0)
        if self.unlocked and mins and time.time() - self.last_activity > mins * 60:
            self.unlocked = False
        return not self.unlocked

    def touch(self) -> None:
        self.last_activity = time.time()

    def unlock(self, passcode: str) -> bool:
        if not settings.get("lock_hash"):
            self.unlocked = True
            return True
        ok = secrets.compare_digest(self._hash(passcode, settings.get("lock_salt")), settings.get("lock_hash"))
        if ok:
            self.unlocked = True
            self.touch()
        else:
            time.sleep(0.6)
        return ok

    def set(self, passcode: Optional[str], old: Optional[str] = None) -> None:
        if settings.get("lock_hash") and not self.unlock(old or ""):
            raise ValueError("The current passcode is wrong.")
        if not passcode:
            settings.update({"lock_enabled": False, "lock_hash": "", "lock_salt": ""})
            self.unlocked = True
            return
        if len(passcode) < 4:
            raise ValueError("Use at least 4 characters.")
        salt = secrets.token_hex(16)
        settings.update({"lock_enabled": True, "lock_salt": salt, "lock_hash": self._hash(passcode, salt)})
        self.unlocked = True

    def lock_now(self) -> None:
        if settings.get("lock_hash"):
            self.unlocked = False


app_lock = AppLock()


# ----------------------------------------------------------------- import
def legacy_candidates() -> list[dict]:
    """Data folders from the TG Drive 0.1 zip that could be imported."""
    home = Path.home()
    seen, out = set(), []
    roots = [home / "tgdrive", home / "Downloads" / "tgdrive", home / "Desktop" / "tgdrive",
             home / "Documents" / "tgdrive", home / "Projects" / "tgdrive", Path.cwd()]
    for base in (home, home / "Downloads", home / "Desktop", home / "Documents"):
        try:
            roots += [p for p in base.iterdir() if p.is_dir() and "tgdrive" in p.name.lower()]
        except OSError:
            pass
    for r in roots:
        for d in (r / "data", r / "tgdrive" / "data"):
            try:
                d = d.resolve()
            except OSError:
                continue
            if d in seen or d == config.DATA_DIR or not (d / "accounts").is_dir():
                continue
            seen.add(d)
            accts = [a.name for a in (d / "accounts").iterdir() if (a / "session.session").exists()]
            if accts:
                out.append({"path": str(d), "accounts": accts, "env": str(d.parent / ".env")
                            if (d.parent / ".env").exists() else None})
    return out


def import_legacy(path: str, move: bool = False) -> dict:
    src = Path(path).expanduser().resolve()
    if not (src / "accounts").is_dir():
        raise ValueError("That folder doesn't contain TG Drive data (no accounts/ folder).")
    dst = config.DATA_DIR / "accounts"
    dst.mkdir(parents=True, exist_ok=True)
    imported = []
    for a in (src / "accounts").iterdir():
        if not (a / "session.session").exists():
            continue
        target = dst / a.name
        if target.exists():
            continue
        (shutil.move if move else shutil.copytree)(str(a), str(target))
        imported.append(a.name)
    env = src.parent / ".env"
    creds = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip().strip('"').strip("'")
    if creds.get("TG_API_ID") and creds.get("TG_API_HASH") and not settings.get("api_hash"):
        try:
            settings.update({"api_id": int(creds["TG_API_ID"]), "api_hash": creds["TG_API_HASH"]})
        except Exception:
            pass
    return {"imported": imported}


def data_summary() -> dict:
    total = 0
    for root, _, files in os.walk(config.DATA_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return {"path": str(config.DATA_DIR), "bytes": total}


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)
