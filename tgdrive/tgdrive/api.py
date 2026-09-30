"""HTTP API and static web UI.

Served on two local ports: the main one for the UI and API, and a media port for
thumbnails, streams and file downloads. Browsers allow only six connections per
host:port, so keeping media on its own port means a page full of loading
thumbnails or a playing video can never hold up a search.

Security: requests must name a loopback Host (blocks DNS-rebinding), state
changes need the X-TGDrive header (blocks cross-site requests), the desktop app
adds a per-launch access token, and an optional passcode locks the app.
"""
import asyncio
import base64
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from .webapp import Body, FastAPI, FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Request, \
    Response, StaticFiles, StreamingResponse
from telethon import errors, utils as tl_utils

from . import config, maintenance
from .accounts import Account, AccountError, AccountManager, events, open_path
from .db import QueryTimeout
from .drive import DriveError
from .links import message_link
from .query import QueryError
from .settings import SettingsError, settings
from .streaming import StreamError, parse_range
from .thumbs import ThumbsBusy
from .transfers import TransferError, ensure_space

log = logging.getLogger("tgdrive.api")
WEB = config.ROOT / "web"

manager = AccountManager()
RUNTIME: dict[str, Any] = {"media_port": None, "port": config.PORT, "desktop": False, "started": time.time()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from . import diagnostics, tasks
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(diagnostics.asyncio_handler)
    maintenance.init_debug_logging()
    diagnostics.add_state_provider("accounts", _crash_state)
    diagnostics.add_state_provider("background tasks", tasks.running)
    watchdog = diagnostics.LoopWatchdog(loop)
    if _apply_autostart not in settings.listeners:
        settings.on_change(_apply_autostart)
    if not settings.get("autostart"):
        _apply_autostart({"autostart"})   # a login entry left from an older version: remove it
    t0 = time.monotonic()
    await manager.startup()
    log.info("accounts opened in %.2f s", time.monotonic() - t0)
    yield
    RUNTIME["stopping"] = True
    t0 = time.monotonic()
    watchdog.stop.set()
    from .api_features import unmount_dav_quietly
    await asyncio.gather(manager.shutdown(), unmount_dav_quietly(), return_exceptions=True)
    log.info("shutdown finished in %.1f s", time.monotonic() - t0)


def _crash_state() -> dict:
    """What each account was doing, for crash reports."""
    out = {}
    for uid, a in list(manager.accounts.items()):
        try:
            out[uid] = {"status": a.status, "error": a.error, "index": a.indexer.phase, "current": a.indexer.current_chat,
                        "transfers": a.transfers.summary(), "drive_error": a.drive.error,
                        "unsaved_folders": a.drive._dirty, "stream_inflight": len(a.streamer.inflight)}
        except Exception as exc:
            out[uid] = repr(exc)
    return out


def _apply_autostart(changed: set) -> None:
    if "autostart" in changed:
        from . import integration
        try:
            integration.set_autostart(bool(settings.get("autostart")))
        except OSError as exc:
            logging.getLogger("tgdrive.api").warning("autostart: %s", exc)


app = FastAPI(title="TG Drive", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------- errors
@app.exception_handler(AccountError)
@app.exception_handler(DriveError)
@app.exception_handler(TransferError)
@app.exception_handler(QueryError)
@app.exception_handler(SettingsError)
@app.exception_handler(StreamError)
async def user_error(_: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(QueryTimeout)
async def timeout_error(_: Request, exc: Exception):
    return JSONResponse({"error": str(exc), "superseded": "Superseded" in str(exc)}, status_code=408)


@app.exception_handler(ThumbsBusy)
async def busy_error(_: Request, exc: ThumbsBusy):
    return Response(status_code=503, headers={"Retry-After": str(exc.retry_after)})


@app.exception_handler(errors.FloodWaitError)
async def flood_error(_: Request, exc: errors.FloodWaitError):
    return JSONResponse({"error": f"Telegram asks to wait {exc.seconds}s before trying that again."},
                        status_code=429)


@app.exception_handler(errors.RPCError)
async def rpc_error(_: Request, exc: errors.RPCError):
    return JSONResponse({"error": f"Telegram refused: {exc.message or exc.__class__.__name__}"}, status_code=400)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """A bug: keep a crash report and give the page a readable message instead of a bare 500."""
    from . import diagnostics
    if "Too little data for declared Content-Length" in repr(exc):
        # A stream that ended early because Telegram stopped feeding it (logged where it happened).
        log.warning("%s %s ended before all its bytes were sent", request.method, request.url.path)
        return JSONResponse({"error": "The stream stopped."}, status_code=502)
    rid = diagnostics.record_exception("server", exc, {"request": f"{request.method} {request.url.path}"})
    log.exception("unhandled error in %s %s", request.method, request.url.path)
    return JSONResponse({"error": f"Something went wrong in TG Drive ({exc.__class__.__name__}). "
                                  f"A crash report was saved{f' ({rid})' if rid else ''}.", "crash": rid},
                        status_code=500)


# ------------------------------------------------------------------- security
LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
OPEN_PATHS = ("/static/", "/favicon", "/dav/")  # /dav/ checks its own secret (file managers can't send tokens)
STREAM_PATH = re.compile(r"^/api/a/\d+/stream/-?\d+/\d+(/[^/]*)?$")


def _host_ok(request: Request) -> bool:
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if config.HOST not in ("127.0.0.1", "localhost", "::1"):
        return True  # served on the network on purpose (password required, see run.py)
    return host in LOOPBACK


def _asset_tag() -> str:
    """Changes whenever the page's code or styles change (new version, or files edited), so the window's
    cache can never keep serving an old copy after an update."""
    import hashlib
    h = hashlib.sha1(config.VERSION.encode())
    for p in sorted(list((WEB / "js").glob("*.js")) + list((WEB / "css").glob("*.css")) + [WEB / "index.html"]):
        try:
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            pass
    return h.hexdigest()[:12]


ASSET_TAG = _asset_tag()
_VERSIONED = re.compile(r"^/static/v/[0-9a-f]{6,40}/")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    versioned = False
    if _VERSIONED.match(path):
        # /static/v/<tag>/js/app.js is /static/js/app.js; the tag only makes the address new after an update.
        path = "/static/" + path.split("/", 4)[4]
        request.scope["path"] = path
        request.scope["raw_path"] = path.encode()
        versioned = True
    if not _host_ok(request):
        return PlainTextResponse("Forbidden host", status_code=403)
    if config.PASSWORD:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                _, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(pw, config.PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="TG Drive"'})
    media_only = False
    if config.ACCESS_TOKEN and not path.startswith(OPEN_PATHS):
        tok = request.cookies.get("tgd") or request.headers.get("x-tgdrive-token") or request.query_params.get("t")
        if not tok or not secrets.compare_digest(tok, config.ACCESS_TOKEN):
            qt = request.query_params.get("t") or ""
            if request.method in ("GET", "HEAD") and STREAM_PATH.match(path) and qt and \
                    secrets.compare_digest(qt, config.MEDIA_TOKEN):
                media_only = True
            else:
                return PlainTextResponse("TG Drive is running in its app. Open it from there.", status_code=401)
    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") and \
            request.headers.get("x-tgdrive") != "1":
        return JSONResponse({"error": "Missing X-TGDrive header."}, status_code=403)
    if path.startswith("/api/") and path not in ("/api/status", "/api/lock/unlock", "/api/events", "/api/stream-events") and \
            maintenance.app_lock.locked():
        return JSONResponse({"error": "TG Drive is locked.", "locked": True}, status_code=423)
    if path.startswith("/api/"):
        RUNTIME["client_seen"] = time.monotonic()   # a TG Drive page is open (browser mode stops without one)
    if path.startswith("/api/") and not _BACKGROUND.match(path) and request.headers.get("x-tgdrive-bg") != "1":
        maintenance.app_lock.touch()   # only what the person does counts as activity (not polling)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except RuntimeError as exc:
        # The page gave up on this request (a newer search replaced it, the window closed): nothing went
        # wrong on this side, so no crash report.
        if str(exc) == "No response returned.":   # starlette: the client disconnected before an answer
            if maintenance.debug_enabled():
                http_log.debug("HTTP %s %s: the client went away after %.1f ms", request.method, path,
                               (time.perf_counter() - t0) * 1000)
            return Response(status_code=499)
        raise
    except Exception:
        if maintenance.debug_enabled():
            http_log.exception("HTTP %s %s failed after %.1f ms", request.method, path, (time.perf_counter() - t0) * 1000)
        raise
    if maintenance.debug_enabled():
        _log_request(request, response, (time.perf_counter() - t0) * 1000)
    if config.ACCESS_TOKEN and not media_only and request.query_params.get("t") == config.ACCESS_TOKEN:
        response.set_cookie("tgd", config.ACCESS_TOKEN, httponly=True, samesite="strict")
    origin = request.headers.get("origin")
    if origin and request.method in ("GET", "HEAD") and ("/thumb/" in path or "/docthumb/" in path or "/inline/" in path or "/stream/" in path):
        o_host = origin.split("://", 1)[-1].rsplit(":", 1)[0].lower()
        if o_host in LOOPBACK or config.HOST not in ("127.0.0.1", "localhost", "::1"):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "Retry-After, Content-Range, Content-Length, X-Doc-Thumb"
            response.headers["Vary"] = "Origin"
    if path.startswith("/static/") and response.status_code < 400:
        if versioned:
            response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        elif path.startswith(("/static/vendor/", "/static/fonts/")):
            response.headers.setdefault("Cache-Control", "private, max-age=86400")
        else:
            response.headers["Cache-Control"] = "no-cache"   # always check for a newer copy
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


http_log = logging.getLogger("tgdrive.http")
# Requests the app makes by itself: they must not keep the app lock from locking.
_BACKGROUND = re.compile(r"^/api/(a/\d+/)?(status|events|stream-events|clientlog|debuglog|crash|lock/state)$")
_POLLS = re.compile(r"^/api/(a/\d+/)?(status|events)$")
_SECRET_Q = re.compile(r"([?&](?:t|token)=)[^&]+")


def _log_request(request: Request, response: Response, ms: float) -> None:
    """Debug log: one line per request. Polling that's fast and fine is left out (it runs every few seconds)."""
    path = request.url.path
    status = response.status_code
    if path in ("/api/clientlog",) or (_POLLS.match(path) and status < 400 and ms < 1000):
        return
    q = _SECRET_Q.sub(r"\1…", ("?" + request.url.query) if request.url.query else "")
    rng = request.headers.get("range")
    size = response.headers.get("content-length")
    level = logging.WARNING if status >= 500 else logging.INFO if status >= 400 or ms > 3000 else logging.DEBUG
    http_log.log(level, "HTTP %s %s%s → %s in %.1f ms%s%s", request.method, path, q[:600], status, ms,
                 f" range={rng}" if rng else "", f" bytes={size}" if size else "")


# -------------------------------------------------------------------- helpers
def acc(aid: int) -> Account:
    return manager.get(aid)


def file_out(row: dict, full: bool = False) -> dict:
    caption = row.get("caption") or ""
    stripped = row.get("stripped")
    return {
        "id": row.get("id"),
        "chat_id": row["chat_id"],
        "msg_id": row["msg_id"],
        "kind": row["kind"],
        "name": row.get("alias") or row["name"],
        "original_name": row["name"],
        "renamed": bool(row.get("alias")),
        "ext": row.get("ext"),
        "mime": row.get("mime"),
        "size": row.get("size") or 0,
        "date": row.get("date"),
        "caption": caption if full else caption[:300],
        "chat_title": row.get("chat_title"),
        "chat_kind": row.get("chat_kind"),
        "sender_name": row.get("sender_name"),
        "fwd_from": row.get("fwd_from") if row.get("is_forward") else None,
        "is_forward": bool(row.get("is_forward")),
        "is_out": bool(row.get("is_out")),
        "width": row.get("width"),
        "height": row.get("height"),
        "duration": row.get("duration"),
        "performer": row.get("performer"),
        "audio_title": row.get("audio_title"),
        "has_thumb": bool(row.get("has_thumb")),
        "inline": base64.b64encode(stripped).decode() if stripped else None,
        "folder_id": row.get("folder_id"),
        "starred": bool(row.get("starred")),
        "tags": [t for t in (row.get("tags") or "").split(",") if t],
        "note": row.get("note") if full else bool(row.get("note")),
        "grouped_id": row.get("grouped_id"),
        "topic_id": row.get("topic_id"),
        "match": row.get("match"),
        "subject": row.get("subject") if row.get("subject") != "_none" else None,
        "play_pos": row.get("play_pos") or 0,
        "play_dur": row.get("play_dur"),
        "watched": bool(row.get("play_done")),
        "copies": row.get("copies") or 0,
        "link": message_link(row["chat_id"], row.get("chat_kind"), row.get("chat_username"), row["msg_id"]),
    }


def items_arg(body: dict) -> list[tuple[int, int]]:
    try:
        return [(int(c), int(m)) for c, m in body.get("items", [])]
    except (TypeError, ValueError):
        raise AccountError("Send items as [[chat_id, msg_id], …].")


def tg_link(chat: Optional[dict], msg_id: int) -> Optional[str]:
    """tg:// deep link that opens the message in the Telegram desktop app."""
    if not chat:
        return None
    if chat.get("username"):
        return f"tg://resolve?domain={chat['username']}&post={msg_id}"
    cid = chat["id"]
    if chat.get("kind") in ("channel", "supergroup") and cid <= -10**12:
        return f"tg://privatepost?channel={-cid - 10**12}&post={msg_id}"
    if chat.get("kind") in ("user", "bot"):
        return f"tg://openmessage?user_id={cid}&message_id={msg_id}"
    return None


# ------------------------------------------------------------------- global
@app.get("/api/status")
async def status():
    locked = maintenance.app_lock.locked()
    out = {"version": config.VERSION, "api_configured": config.api_configured(), "locked": locked,
           "media_port": RUNTIME.get("media_port"), "desktop": RUNTIME.get("desktop"),
           "lock_set": bool(settings.get("lock_hash"))}
    if locked:
        return out
    out["media_token"] = config.MEDIA_TOKEN if config.ACCESS_TOKEN else ""
    out.update(accounts=manager.list(), settings=settings.public(), data_dir=str(config.DATA_DIR),
               download_dir=str(settings.get("download_dir") or config.default_download_dir()),
               env_api=bool(config.ENV_API_ID and config.ENV_API_HASH))
    if not manager.accounts:
        out["legacy"] = maintenance.legacy_candidates()
    return out


@app.get("/api/settings")
async def get_settings():
    return settings.public()


@app.patch("/api/settings")
async def patch_settings(body: dict = Body(...)):
    body = {k: v for k, v in body.items() if k not in ("lock_hash", "lock_salt", "lock_enabled")}
    if body.get("proxy_pass") == "" and settings.get("proxy_pass"):
        body.pop("proxy_pass")  # blank field means "keep"
    changed = settings.update(body)
    return {"changed": sorted(changed), "settings": settings.public()}


@app.post("/api/setup")
async def setup_api(body: dict = Body(...)):
    try:
        api_id = int(str(body.get("api_id", "")).strip())
    except ValueError:
        raise SettingsError("The API ID is a number, e.g. 1234567.")
    api_hash = str(body.get("api_hash", "")).strip().lower()
    if len(api_hash) != 32 or any(c not in "0123456789abcdef" for c in api_hash):
        raise SettingsError("The API hash is 32 letters and digits, from my.telegram.org.")
    settings.update({"api_id": api_id, "api_hash": api_hash})
    return {"ok": True}


@app.get("/api/events")
async def get_events(after: int = 0):
    return {"events": events.since(after), "last": events.seq}


def _stopping() -> bool:
    """TG Drive is quitting: long-lived responses end now so the server can stop without waiting."""
    server = RUNTIME.get("server")
    return bool(RUNTIME.get("stopping") or (server is not None and getattr(server, "should_exit", False)))


@app.get("/api/stream-events")
async def stream_events(request: Request, aid: int = 0, after: int = 0):
    """Server-sent events: one long-lived connection instead of the window polling. Sends
    `events` (notifications, crashes, new files …) as they happen and `status` (the account's status
    panel data) whenever it changes, checked every second. `ping` keeps idle connections alive."""
    async def gen():
        last_seq, last_status, last_ping = after, None, time.monotonic()
        tick = 0
        RUNTIME["clients"] = RUNTIME.get("clients", 0) + 1
        RUNTIME["live_used"] = True
        try:
            async for chunk in _events_loop(request, aid, last_seq, last_status, last_ping, tick):
                yield chunk
        finally:
            RUNTIME["clients"] = max(0, RUNTIME.get("clients", 1) - 1)
            RUNTIME["client_seen"] = time.monotonic()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def _events_loop(request: Request, aid: int, last_seq: int, last_status, last_ping: float, tick: int):
    yield "retry: 3000\n\n"
    while True:
        if _stopping() or await request.is_disconnected():
            return
        if events.seq != last_seq:
            new = events.since(last_seq)
            last_seq = events.seq
            if new:
                yield f"event: events\ndata: {json.dumps({'events': new, 'last': last_seq}, default=str)}\n\n"
        if tick % 4 == 0:   # status: once a second
            if maintenance.app_lock.locked():
                payload = json.dumps({"locked": True})
            else:
                a = manager.accounts.get(aid)
                payload = json.dumps(account_status_payload(a), default=str) if a else json.dumps({"none": True})
            if payload != last_status:
                last_status = payload
                yield f"event: status\ndata: {payload}\n\n"
        if time.monotonic() - last_ping > 15:
            last_ping = time.monotonic()
            yield ": ping\n\n"
        tick += 1
        await asyncio.sleep(0.25)


@app.post("/api/activity")
async def report_activity():
    """The window reports that someone is using it (typing, clicking) so auto-lock waits."""
    return {"ok": True}


@app.post("/api/lock/unlock")
async def lock_unlock(body: dict = Body(...)):
    ok = await asyncio.get_running_loop().run_in_executor(None, maintenance.app_lock.unlock,
                                                          str(body.get("passcode", "")))
    if not ok:
        return JSONResponse({"error": "Wrong passcode."}, status_code=403)
    return {"ok": True}


@app.post("/api/lock/set")
async def lock_set(body: dict = Body(...)):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, maintenance.app_lock.set, body.get("passcode") or None, body.get("old") or None)
    except ValueError as exc:
        raise SettingsError(str(exc))
    return {"ok": True, "lock_set": bool(settings.get("lock_hash"))}


@app.post("/api/lock/now")
async def lock_now():
    maintenance.app_lock.lock_now()
    return {"ok": True}


@app.post("/api/open")
async def open_local(body: dict = Body(...)):
    path = str(body.get("path") or "")
    allowed = [config.DATA_DIR, Path(settings.get("download_dir") or config.default_download_dir())]
    rp = Path(path).expanduser().resolve()
    if not any(str(rp).startswith(str(a.resolve())) for a in allowed):
        known = any(a.transfers.db.one("SELECT 1 FROM transfers WHERE path=?", (path,))
                    for a in manager.accounts.values())
        if not known:
            raise AccountError("TG Drive only opens files it downloaded.")
    open_path(str(rp), reveal=bool(body.get("reveal")))
    return {"ok": True}


@app.get("/api/legacy")
async def legacy():
    return {"candidates": maintenance.legacy_candidates(), "data_dir": str(config.DATA_DIR)}


@app.post("/api/legacy/import")
async def legacy_import(body: dict = Body(...)):
    try:
        res = maintenance.import_legacy(str(body.get("path", "")), move=bool(body.get("move")))
    except (ValueError, OSError) as exc:
        raise AccountError(str(exc))
    await manager.startup_new()
    return res


@app.get("/api/logs")
async def logs(lines: int = 400):
    return PlainTextResponse(maintenance.tail_log(min(lines, 5000)))


@app.get("/api/about")
async def about():
    from . import semantic
    return {"version": config.VERSION, "data": maintenance.data_summary(),
            "semantic_available": semantic.available(), "log": str(maintenance.log_path()),
            "debug_log": str(maintenance.debug_log_path()), "debug_on": maintenance.debug_enabled(),
            "log_files": maintenance.log_files()}


# ------------------------------------------------------------------- login
@app.post("/api/login/start")
async def login_start(body: dict = Body(...)):
    return await manager.login_start(str(body.get("phone", "")))


@app.post("/api/login/code")
async def login_code(body: dict = Body(...)):
    return await manager.login_code(str(body.get("login_id", "")), str(body.get("code", "")))


@app.post("/api/login/password")
async def login_password(body: dict = Body(...)):
    return await manager.login_password(str(body.get("login_id", "")), str(body.get("password", "")))


@app.post("/api/login/qr")
async def login_qr():
    return await manager.login_qr_start()


@app.get("/api/login/qr/{login_id}")
async def login_qr_status(login_id: str):
    return await manager.login_qr_status(login_id)


@app.delete("/api/accounts/{aid}")
async def remove_account(aid: int, keep_data: bool = False):
    await manager.remove(aid, keep_data=keep_data)
    return {"ok": True}


# ------------------------------------------------------------- per account
def account_status_payload(a: Account) -> dict:
    tsum = a.transfers.summary()
    return {"account": a.info(), "index": a.indexer.status(), "drive": a.drive.info(),
            "transfers": tsum, "transfers_active": tsum["active"],
            "search": a.db.search_upgrade_status(), "semantic": a.semantic.status(),
            "dupes": a.dupes.status(), "sync": a.sync.summary(),
            "thumbs_backoff": max(0, int(a.thumbs.backoff_until - time.time()))}


@app.get("/api/a/{aid}/status")
async def account_status(aid: int):
    return account_status_payload(acc(aid))


@app.get("/api/cpu")
async def cpu_use():
    """How much CPU each part of TG Drive's service used since the last time this was asked, and
    what the background jobs are doing. 100 means one whole core."""
    from . import diagnostics, pace
    out = diagnostics.cpu_by_part()
    out["background_work"] = pace.mode()
    out["jobs"] = {}
    for uid, a in manager.accounts.items():
        out["jobs"][uid] = {"meaning index": a.semantic.status().get("state"), "subjects": a.subjects.status().get("state"),
                            "duplicates": a.dupes.status().get("state"), "indexing": a.indexer.phase,
                            "search index": a.db.search_upgrade_status().get("state")}
    return out


@app.get("/api/transfers/active")
async def transfers_active():
    """Running and queued transfers over all accounts (the desktop app asks before quitting)."""
    return {"active": sum(a.transfers.summary()["active"] for a in manager.accounts.values())}


@app.get("/api/a/{aid}/chats")
async def chats(aid: int):
    a = acc(aid)
    rows = await a.db.read.run(lambda r: a.db.list_chats(r), timeout=20)
    return {"chats": rows}


@app.post("/api/a/{aid}/chats/{cid}/exclude")
async def exclude_chat(aid: int, cid: int, body: dict = Body(...)):
    a = acc(aid)
    a.db.set_excluded(cid, bool(body.get("excluded")))
    a.indexer.poke()
    return {"ok": True}


@app.post("/api/a/{aid}/chats/{cid}/pin")
async def pin_chat(aid: int, cid: int, body: dict = Body(...)):
    acc(aid).db.x("UPDATE chats SET pinned=? WHERE id=?", (int(bool(body.get("pinned"))), cid))
    return {"ok": True}


@app.post("/api/a/{aid}/chats/{cid}/rescan")
async def rescan_chat(aid: int, cid: int):
    a = acc(aid)
    a.db.reset_chat_index(cid)
    a.indexer.poke()
    return {"ok": True}


@app.post("/api/a/{aid}/chats/bulk")
async def chats_bulk(aid: int, body: dict = Body(...)):
    """Exclude / include many chats at once (e.g. every bot, or every chat of a Telegram folder)."""
    a = acc(aid)
    ids = [int(x) for x in body.get("chat_ids", [])]
    if body.get("kind"):
        ids += [r["id"] for r in a.db.q("SELECT id FROM chats WHERE kind=?", (body["kind"],))]
    action = body.get("action")
    for cid in ids:
        if action == "exclude":
            a.db.set_excluded(cid, True)
        elif action == "include":
            a.db.set_excluded(cid, False)
        elif action == "rescan":
            a.db.reset_chat_index(cid)
    a.indexer.poke()
    return {"ok": True, "n": len(ids)}


@app.get("/api/a/{aid}/dialog_filters")
async def dialog_filters(aid: int):
    rows = acc(aid).db.q("SELECT id, title, emoticon, chat_ids FROM dialog_filters ORDER BY position")
    for r in rows:
        r["chat_ids"] = json.loads(r["chat_ids"] or "[]")
    return {"filters": rows}


@app.get("/api/a/{aid}/topics/{cid}")
async def topics(aid: int, cid: int):
    a = acc(aid)
    return {"topics": a.db.q("SELECT t.topic_id, t.title, (SELECT COUNT(*) FROM files f WHERE f.chat_id=t.chat_id "
                             "AND f.topic_id=t.topic_id) AS n FROM topics t WHERE t.chat_id=? ORDER BY n DESC",
                             (cid,))}


@app.post("/api/a/{aid}/index/{action}")
async def index_control(aid: int, action: str):
    a = acc(aid)
    if action == "pause":
        a.indexer.pause()
    elif action == "resume":
        a.indexer.resume()
    elif action == "resync":
        a.indexer.poke()
    elif action == "verify":
        await a.indexer.verify_step()
    else:
        raise AccountError("Unknown action.")
    return a.indexer.status()


# ------------------------------------------------------------------- files
@app.get("/api/a/{aid}/files")
async def search_files(aid: int, request: Request):
    a = acc(aid)
    p = dict(request.query_params)
    res = await a.search.files(p, slot=p.pop("slot", None) or None)
    res["items"] = [file_out(r) for r in res["items"]]
    if p.get("q") and not p.get("cursor") and p.get("record") == "1":
        a.db.add_search_history(p["q"])
    return res


@app.get("/api/a/{aid}/files/stats")
async def search_stats(aid: int, request: Request):
    a = acc(aid)
    p = dict(request.query_params)
    slot = p.pop("slot", None)
    return await a.search.stats(p, slot=(slot + ":stats") if slot else None)


@app.get("/api/a/{aid}/suggest")
async def suggest(aid: int, q: str = ""):
    return await acc(aid).search.suggest(q)


@app.delete("/api/a/{aid}/history")
async def clear_history(aid: int, q: Optional[str] = None):
    a = acc(aid)
    if q:
        a.db.x("DELETE FROM search_history WHERE q=?", (q,))
    else:
        a.db.x("DELETE FROM search_history")
    return {"ok": True}


@app.get("/api/a/{aid}/files/{cid}/{mid}")
async def file_detail(aid: int, cid: int, mid: int):
    a = acc(aid)
    row = a.db.get_file(cid, mid)
    if not row:
        raise AccountError("That file isn't in the index.")
    out = file_out(row, full=True)
    chat = a.db.get_chat(cid)
    out["folder_path"] = a.drive.path(row.get("folder_id"))
    out["in_drive_channel"] = cid == a.drive.channel_id
    out["can_copy"] = not row.get("chat_noforwards") and cid != a.drive.channel_id
    out["can_forward"] = not row.get("chat_noforwards")
    out["can_delete"] = bool(row.get("is_out") or row.get("chat_kind") in ("user", "saved", "bot")
                             or row.get("chat_is_admin") or row.get("chat_is_creator"))
    out["tg_link"] = tg_link(chat, mid)
    out["album"] = a.db.one("SELECT COUNT(*) AS n FROM files WHERE grouped_id=? AND chat_id=?",
                            (row["grouped_id"], cid))["n"] if row.get("grouped_id") else 0
    # Every copy of this file (same Telegram file, or same name and size), best first.
    out["copy_list"] = [
        {"chat_id": r["chat_id"], "msg_id": r["msg_id"], "name": r["name"], "chat_title": r["chat_title"],
         "chat_kind": r["chat_kind"], "date": r["date"], "size": r["size"], "rank": r["rank"],
         "this": r["chat_id"] == cid and r["msg_id"] == mid, "folder_id": r["folder_id"], "starred": bool(r["starred"])}
        for r in a.db.q("SELECT f.chat_id, f.msg_id, COALESCE(f.alias, f.name) AS name, f.chat_title, f.date, f.size, "
                        "d2.rank, c.kind AS chat_kind, p.folder_id, p.starred FROM dups d JOIN dups d2 ON d2.grp=d.grp "
                        "JOIN files f ON f.id=d2.file_id LEFT JOIN chats c ON c.id=f.chat_id "
                        "LEFT JOIN placements p ON p.chat_id=f.chat_id AND p.msg_id=f.msg_id "
                        "WHERE d.file_id=? ORDER BY d2.rank LIMIT 60", (row["id"],))]
    out["duplicates"] = max(0, len(out["copy_list"]) - 1) if out["copy_list"] else (
        a.db.one("SELECT COUNT(*) - 1 AS n FROM files WHERE media_id=?", (row["media_id"],))["n"]
        if row.get("media_id") else 0)
    t = a.db.one("SELECT id, path FROM transfers WHERE direction='down' AND chat_id=? AND msg_id=? AND status='done' "
                 "ORDER BY id DESC LIMIT 1", (cid, mid))
    out["local_path"] = t["path"] if t and t["path"] and Path(t["path"]).exists() else None
    if row.get("topic_id"):
        tp = a.db.one("SELECT title FROM topics WHERE chat_id=? AND topic_id=?", (cid, row["topic_id"]))
        out["topic"] = tp["title"] if tp else None
    a.db.touch_recent(cid, mid, "view")
    return out


@app.post("/api/a/{aid}/files/delete")
async def delete_files(aid: int, body: dict = Body(...)):
    """Delete messages in Telegram itself (for everyone, where Telegram allows it)."""
    a = acc(aid)
    a.require_online()
    by_chat: dict[int, list[int]] = {}
    for cid, mid in items_arg(body):
        by_chat.setdefault(cid, []).append(mid)
    deleted, failed = 0, []
    for cid, mids in by_chat.items():
        try:
            peer = await a.peer(cid)
            await a.client.delete_messages(peer, mids, revoke=True)
            a.db.delete_files(cid, mids)
            marks = ",".join("?" * len(mids))
            if a.db.x(f"DELETE FROM placements WHERE chat_id=? AND msg_id IN ({marks})", [cid, *mids]).rowcount:
                now_ms = int(time.time() * 1000)
                a.db.conn.executemany("INSERT OR REPLACE INTO tombstones(kind, id, at) VALUES('item', ?, ?)",
                                      [(f"{cid}:{m}", now_ms) for m in mids])
                a.drive._schedule()
            for mid in mids:
                a.fetcher.forget(cid, mid)
            deleted += len(mids)
        except errors.RPCError as exc:
            chat = a.db.get_chat(cid)
            failed.append(f"{chat['title'] if chat else cid} ({exc.__class__.__name__})")
    if deleted:
        a.db.log_activity("delete", f"Deleted {deleted} files from Telegram")
    return {"deleted": deleted, "failed": failed}


@app.post("/api/a/{aid}/files/forget")
async def forget_files(aid: int, body: dict = Body(...)):
    """Remove files from the index only (e.g. junk you never want to see); Telegram is untouched."""
    a = acc(aid)
    by_chat: dict[int, list[int]] = {}
    for cid, mid in items_arg(body):
        by_chat.setdefault(cid, []).append(mid)
    n = sum(a.db.delete_files(cid, mids) for cid, mids in by_chat.items())
    return {"removed": n}


@app.post("/api/a/{aid}/files/place")
async def place_files(aid: int, body: dict = Body(...)):
    a = acc(aid)
    await a.drive.place(items_arg(body), body.get("folder_id") or None)
    return {"ok": True, "undo": a.drive.info()["undo"][:1]}


@app.post("/api/a/{aid}/files/{cid}/{mid}/rename")
async def rename_file(aid: int, cid: int, mid: int, body: dict = Body(...)):
    await acc(aid).drive.rename_file(cid, mid, str(body.get("name", "")))
    return {"ok": True}


@app.post("/api/a/{aid}/files/rename")
async def bulk_rename(aid: int, body: dict = Body(...)):
    n = await acc(aid).drive.bulk_rename(items_arg(body), str(body.get("pattern", "")), int(body.get("start", 1)))
    return {"renamed": n}


@app.post("/api/a/{aid}/files/meta")
async def files_meta(aid: int, body: dict = Body(...)):
    """Star / unstar, tags, notes (synced to other devices)."""
    await acc(aid).drive.set_meta_items(
        items_arg(body), starred=body.get("starred"), tags_add=body.get("tags_add"),
        tags_remove=body.get("tags_remove"), tags_set=body.get("tags"), note=body.get("note"))
    return {"ok": True}


@app.get("/api/a/{aid}/tags")
async def tags(aid: int):
    return {"tags": acc(aid).drive.all_tags()}


@app.post("/api/a/{aid}/files/copy")
async def copy_files(aid: int, body: dict = Body(...)):
    a = acc(aid)
    out, failed = [], []
    for cid, mid in items_arg(body):
        try:
            out.append(await a.drive.copy_to_drive(cid, mid, body.get("folder_id") or None))
        except (AccountError, DriveError, errors.RPCError) as exc:
            failed.append(str(exc))
    return {"copied": out, "failed": failed}


@app.post("/api/a/{aid}/files/send")
async def send_files(aid: int, body: dict = Body(...)):
    return await acc(aid).drive.send_to(items_arg(body), int(body.get("chat_id")), body.get("mode") or "copy")


@app.get("/api/a/{aid}/thumb/{cid}/{mid}")
async def thumb(aid: int, cid: int, mid: int, v: str = "s"):
    a = acc(aid)
    if v not in ("s", "b", "full"):
        v = "s"
    try:
        path = await a.thumbs.get(cid, mid, v)
    except AccountError:
        path = None
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "private, max-age=3600"})
    media_type = "image/jpeg"
    if v == "full":
        row = a.db.get_file(cid, mid)
        media_type = (row or {}).get("mime") or "image/jpeg"
        if not media_type.startswith("image/"):
            media_type = "image/jpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/a/{aid}/docthumb/{cid}/{mid}")
async def doc_thumb(aid: int, cid: int, mid: int):
    """First page of a PDF as a picture, if the window has rendered it before. Otherwise 204 (no
    content, so the browser doesn't log an error for every new PDF) with X-Doc-Thumb "missing" (render
    it) or "none" (it couldn't be rendered; don't try again)."""
    path, failed = acc(aid).thumbs.doc_state(cid, mid)
    if not path:
        return Response(status_code=204, headers={"X-Doc-Thumb": "none" if failed else "missing",
                                                  "Access-Control-Expose-Headers": "X-Doc-Thumb",
                                                  "Cache-Control": "no-store"})
    head = path.read_bytes()[:4]
    media = "image/webp" if head == b"RIFF" else "image/png" if head.startswith(b"\x89PN") else "image/jpeg"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=604800"})


@app.put("/api/a/{aid}/docthumb/{cid}/{mid}")
async def doc_thumb_save(aid: int, cid: int, mid: int, request: Request):
    a = acc(aid)
    if not a.db.get_file(cid, mid):
        return JSONResponse({"error": "That file isn't in the index."}, status_code=404)
    data = await request.body()
    try:
        a.thumbs.save_doc(cid, mid, data)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True}


@app.post("/api/a/{aid}/docthumb/{cid}/{mid}/failed")
async def doc_thumb_failed(aid: int, cid: int, mid: int):
    acc(aid).thumbs.doc_failed(cid, mid)
    return {"ok": True}


@app.get("/api/a/{aid}/inline/{cid}/{mid}")
async def inline_preview(aid: int, cid: int, mid: int):
    row = acc(aid).db.one("SELECT stripped FROM files WHERE chat_id=? AND msg_id=?", (cid, mid))
    if not row or not row["stripped"]:
        return Response(status_code=404)
    return Response(tl_utils.stripped_photo_to_jpg(row["stripped"]), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=604800"})


# --------------------------------------------------------------- streaming
ACTIVE_TYPES = ("text/html", "application/xhtml+xml", "image/svg+xml", "application/xml", "text/xml",
                "application/javascript", "text/javascript", "application/ecmascript", "application/x-shockwave-flash")


def _is_active(mime: str) -> bool:
    m = (mime or "").split(";")[0].strip().lower()
    return m in ACTIVE_TYPES or m.endswith("+xml") or "javascript" in m


@app.api_route("/api/a/{aid}/stream/{cid}/{mid}/{name:path}", methods=["GET", "HEAD"])
async def stream(aid: int, cid: int, mid: int, name: str, request: Request, dl: int = 0):
    """Byte-range streaming straight from Telegram (video, audio, PDFs, images, anything)."""
    a = acc(aid)
    src = await a.streamer.source(cid, mid)
    size = src.size
    mime = src.mime or "application/octet-stream"
    if mime == "audio/ogg" and name.endswith(".oga"):
        mime = "audio/ogg"
    disp = "attachment" if dl else "inline"
    from urllib.parse import quote
    headers = {"Accept-Ranges": "bytes", "Content-Type": mime,
               "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(src.name)}",
               "Cache-Control": "private, max-age=3600"}
    if _is_active(mime):
        # Files from Telegram are untrusted: an HTML or SVG opened from here must not run scripts
        # on TG Drive's own address. (Images still display: <img> never runs them anyway.)
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    if src.local:
        return FileResponse(src.local, media_type=mime, headers={k: v for k, v in headers.items()
                                                                  if k != "Content-Type"})
    try:
        rng = parse_range(request.headers.get("range"), size)
    except StreamError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = rng if rng else (0, size - 1)
    headers["Content-Length"] = str(end - start + 1)
    status_code = 206 if rng else 200
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.method == "HEAD" or size == 0:
        return Response(status_code=status_code, headers=headers)
    prefetch = int(settings.get("stream_prefetch") or 4)
    # The first piece is fetched before answering: if Telegram can't give it, the player gets a clear
    # error instead of a response that stops at once.
    from .streaming import CHUNK
    first = await a.streamer.chunk(src, start // CHUNK)
    a.db.touch_recent(cid, mid, "play")

    async def body():
        lo = start - (start // CHUNK) * CHUNK
        hi = min(len(first), end - (start // CHUNK) * CHUNK + 1)
        yield first[lo:hi]
        nxt = (start // CHUNK + 1) * CHUNK
        if nxt > end:
            return
        try:
            async for piece in a.streamer.iter_range(src, nxt, end, prefetch=prefetch):
                yield piece
        except (StreamError, AccountError, ConnectionError, OSError) as exc:
            # Telegram stopped answering mid-way: the player sees the connection end and asks again.
            # That's the network, not a bug, so it's logged and not kept as a crash report.
            log.warning("stream %s:%s cut short at a later part: %s", cid, mid, exc)
            raise

    return StreamingResponse(body(), status_code=status_code, headers=headers, media_type=mime)



def _stream_link(aid: int, cid: int, mid: int, name: str) -> str:
    from urllib.parse import quote
    base = f"http://127.0.0.1:{RUNTIME.get('media_port') or RUNTIME.get('port')}"
    tok = f"?t={config.MEDIA_TOKEN}" if config.ACCESS_TOKEN else ""
    return f"{base}/api/a/{aid}/stream/{cid}/{mid}/{quote(name)}{tok}"


@app.post("/api/a/{aid}/play_external/{cid}/{mid}")
async def play_external(aid: int, cid: int, mid: int):
    """Open a stream in the player chosen in Settings → Streaming (VLC, mpv, …)."""
    import shlex
    import shutil
    import subprocess
    from .accounts import clean_env
    a = acc(aid)
    row = a.db.get_file(cid, mid)
    if not row:
        return JSONResponse({"error": "File not found."}, status_code=404)
    cmd = (settings.get("external_player") or "").strip()
    if not cmd:
        for exe in ("vlc", "mpv", "celluloid", "totem", "smplayer", "haruna"):
            if shutil.which(exe):
                cmd = exe
                break
    if not cmd:
        return JSONResponse({"error": "No video player found. Install VLC or mpv, or set one in Settings → Streaming."},
                            status_code=400)
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return JSONResponse({"error": "The player command in Settings → Streaming isn't valid."}, status_code=400)
    if not shutil.which(argv[0]):
        return JSONResponse({"error": f"“{argv[0]}” isn't installed or isn't on the PATH."}, status_code=400)
    url = _stream_link(aid, cid, mid, row.get("alias") or row["name"])
    try:
        subprocess.Popen([*argv, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True, env=clean_env())
    except OSError as exc:
        return JSONResponse({"error": f"Couldn't start the player: {exc}"}, status_code=500)
    return {"ok": True, "player": argv[0]}


@app.get("/api/a/{aid}/playback/{cid}/{mid}")
async def get_playback(aid: int, cid: int, mid: int):
    return acc(aid).db.get_playback(cid, mid) or {"pos": 0, "dur": None, "done": 0}


@app.put("/api/a/{aid}/playback/{cid}/{mid}")
async def put_playback(aid: int, cid: int, mid: int, body: dict = Body(...)):
    """Where playback stopped (seconds). {"done": true/false} marks watched / unwatched."""
    a = acc(aid)
    try:
        pos = float(body.get("pos") or 0)
        dur = float(body["dur"]) if body.get("dur") else None
    except (TypeError, ValueError):
        return JSONResponse({"error": "pos and dur are seconds."}, status_code=400)
    done = body.get("done")
    return a.db.set_playback(cid, mid, pos, dur, None if done is None else bool(done))


@app.delete("/api/a/{aid}/playback/{cid}/{mid}")
async def delete_playback(aid: int, cid: int, mid: int):
    acc(aid).db.clear_playback(cid, mid)
    return {"ok": True}


@app.get("/api/a/{aid}/playlist.m3u")
async def playlist(aid: int, request: Request):
    """An .m3u of stream URLs (open a whole folder or search in VLC / mpv)."""
    a = acc(aid)
    p = dict(request.query_params)
    p.setdefault("limit", "500")
    res = await a.search.files(p)
    base = f"http://127.0.0.1:{RUNTIME.get('media_port') or RUNTIME.get('port')}"
    tok = f"?t={config.MEDIA_TOKEN}" if config.ACCESS_TOKEN else ""
    from urllib.parse import quote
    lines = ["#EXTM3U"]
    for r in res["items"]:
        if r["kind"] in ("video", "audio", "voice", "round", "gif"):
            n = r.get("alias") or r["name"]
            lines.append(f"#EXTINF:{int(r.get('duration') or -1)},{n}")
            lines.append(f"{base}/api/a/{aid}/stream/{r['chat_id']}/{r['msg_id']}/{quote(n)}{tok}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="audio/x-mpegurl",
                             headers={"Content-Disposition": 'attachment; filename="tgdrive.m3u"'})


# ------------------------------------------------------------------ folders
@app.get("/api/a/{aid}/folders")
async def folders(aid: int):
    a = acc(aid)
    drive_chat = a.db.get_chat(a.drive.channel_id) if a.drive.channel_id else None
    rows = await a.db.read.run(lambda r: a.db.list_folders(r), timeout=20)
    return {"folders": rows, "drive": a.drive.info(),
            "drive_title": drive_chat["title"] if drive_chat else config.DRIVE_CHANNEL_TITLE,
            "saved": a.drive.saved_searches(),
            "starred": a.db.one("SELECT COUNT(*) AS n FROM placements WHERE starred=1")["n"],
            "recent": a.db.one("SELECT COUNT(*) AS n FROM recent")["n"],
            "continue": a.db.one("SELECT COUNT(*) AS n FROM playback WHERE done=0 AND pos>0")["n"]}


@app.post("/api/a/{aid}/folders")
async def create_folder(aid: int, body: dict = Body(...)):
    a = acc(aid)
    f = await a.drive.create_folder(str(body.get("name", "")), body.get("parent_id") or None,
                                    str(body.get("color") or ""), str(body.get("description") or ""),
                                    emoji=str(body.get("emoji") or ""), rules=body.get("rules") or None)
    if f.get("kind") == "auto":
        a.autofile.poke()
    dav_invalidate()
    return f


@app.patch("/api/a/{aid}/folders/{fid}")
async def update_folder(aid: int, fid: str, body: dict = Body(...)):
    kwargs: dict[str, Any] = {}
    for k in ("name", "color", "description", "emoji", "cover"):
        if k in body:
            kwargs[k] = str(body[k] or "")
    if "parent_id" in body:
        kwargs["parent_id"] = body["parent_id"] or None
    if "rules" in body:
        kwargs["rules"] = body["rules"] or None
    a = acc(aid)
    await a.drive.update_folder(fid, **kwargs)
    if "rules" in body:
        a.autofile.poke()
    dav_invalidate()
    return {"ok": True}


def dav_invalidate() -> None:
    from . import dav
    dav.invalidate_all()


@app.delete("/api/a/{aid}/folders/{fid}")
async def delete_folder(aid: int, fid: str):
    n = await acc(aid).drive.delete_folder(fid)
    return {"ok": True, "unfiled": n}


@app.post("/api/a/{aid}/folders/{fid}/download")
async def download_folder(aid: int, fid: str, body: dict = Body(default={})):
    a = acc(aid)
    folder = a.db.get_folder(fid)
    if not folder:
        raise DriveError("That folder no longer exists.")
    ids = [fid, *a.drive._descendants(fid)]
    marks = ",".join("?" * len(ids))
    items = [(r["chat_id"], r["msg_id"]) for r in a.db.q(
        f"SELECT p.chat_id, p.msg_id FROM placements p JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id "
        f"WHERE p.folder_id IN ({marks})", ids)]
    if not items:
        raise DriveError("That folder is empty.")
    return a.transfers.add_folder_download(fid, items, as_zip=bool(body.get("zip")), name=folder["name"])


@app.get("/api/a/{aid}/saved")
async def saved_list(aid: int):
    return {"saved": acc(aid).drive.saved_searches()}


@app.post("/api/a/{aid}/saved")
async def saved_create(aid: int, body: dict = Body(...)):
    return await acc(aid).drive.save_search(str(body.get("name", "")), str(body.get("q", "")),
                                            body.get("params") or {}, str(body.get("icon") or ""),
                                            body.get("id") or None)


@app.delete("/api/a/{aid}/saved/{sid}")
async def saved_delete(aid: int, sid: str):
    await acc(aid).drive.delete_search(sid)
    return {"ok": True}


@app.get("/api/a/{aid}/drive/manifest")
async def export_manifest(aid: int):
    return JSONResponse(acc(aid).drive.export(),
                        headers={"Content-Disposition": 'attachment; filename="tgdrive-manifest.json"'})


@app.post("/api/a/{aid}/drive/manifest")
async def import_manifest(aid: int, body: dict = Body(...), mode: str = "merge"):
    await acc(aid).drive.import_manifest(body, mode=mode)
    return {"ok": True}


@app.post("/api/a/{aid}/drive/undo")
async def drive_undo(aid: int):
    return {"undone": await acc(aid).drive.undo()}


@app.get("/api/a/{aid}/drive/backups")
async def drive_backups(aid: int):
    return {"backups": acc(aid).drive.backups()}


@app.post("/api/a/{aid}/drive/backups/{bid}/restore")
async def drive_restore(aid: int, bid: int):
    await acc(aid).drive.restore_backup(bid)
    return {"ok": True}


@app.post("/api/a/{aid}/drive/sync")
async def drive_sync(aid: int):
    a = acc(aid)
    a.drive._dirty = True
    await a.drive.flush_now()
    return a.drive.info()


# ---------------------------------------------------------------- transfers
@app.get("/api/a/{aid}/transfers")
async def transfers(aid: int):
    t = acc(aid).transfers
    return {"transfers": t.list(), "summary": t.summary()}


@app.post("/api/a/{aid}/transfers/download")
async def start_downloads(aid: int, body: dict = Body(...)):
    a = acc(aid)
    items = items_arg(body)
    if body.get("zip") or (body.get("keep_structure") and len(items) > 1):
        return a.transfers.add_folder_download(None, items, as_zip=bool(body.get("zip")),
                                               name=str(body.get("name") or "TG Drive files"))
    return {"ids": [a.transfers.add_download(c, m, dest_dir=body.get("dest_dir")) for c, m in items]}


@app.put("/api/a/{aid}/upload")
async def upload(aid: int, request: Request, name: str, folder_id: Optional[str] = None, rel: str = "",
                 caption: str = "", chat_id: Optional[int] = None):
    a = acc(aid)
    a.require_online()
    a.drive.require_files_folder(folder_id or None)   # before reading the file, not after
    tmp = a.transfers.new_upload_path()
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    ensure_space(tmp, length, f"“{name}”")
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
        fid = folder_id or None
        parts = [p for p in rel.split("/")[:-1] if p.strip()]
        if parts:
            fid = await a.drive.ensure_path(fid, parts)
        return {"id": a.transfers.add_upload(tmp, name, fid, caption=caption, target_chat=chat_id)}
    except BaseException:   # also a closed connection or a cancelled request: never leave the copy behind
        Path(tmp).unlink(missing_ok=True)
        raise


@app.post("/api/a/{aid}/upload/paths")
async def upload_paths(aid: int, body: dict = Body(...)):
    """Upload files or folders straight from disk (desktop app; no temporary copy)."""
    a = acc(aid)
    a.require_online()
    a.drive.require_files_folder(body.get("folder_id") or None)
    return await a.transfers.add_upload_paths([str(p) for p in body.get("paths", [])], body.get("folder_id") or None,
                                              caption=str(body.get("caption") or ""),
                                              target_chat=body.get("chat_id") or None)


@app.post("/api/a/{aid}/transfers/bulk/{action}")
async def transfers_bulk(aid: int, action: str):
    return {"n": acc(aid).transfers.bulk(action)}


@app.post("/api/a/{aid}/transfers/clear")
async def clear_transfers(aid: int):
    return {"n": acc(aid).transfers.bulk("clear")}


@app.post("/api/a/{aid}/transfers/{tid}/{action}")
async def transfer_action(aid: int, tid: int, action: str):
    a = acc(aid)
    t = a.transfers
    if action == "pause":
        t.pause(tid)
    elif action == "resume":
        t.resume(tid)
    elif action == "cancel":
        t.cancel(tid)
    elif action in ("open", "reveal"):
        a.open_path(str(t.file_path(tid)), reveal=action == "reveal")
    else:
        raise TransferError("Unknown action.")
    return {"ok": True}


@app.delete("/api/a/{aid}/transfers/{tid}")
async def remove_transfer(aid: int, tid: int, delete_file: bool = False):
    acc(aid).transfers.remove(tid, delete_file)
    return {"ok": True}


@app.get("/api/a/{aid}/transfers/{tid}/file")
async def transfer_file(aid: int, tid: int):
    t = acc(aid).transfers
    path = t.file_path(tid)
    row = t.db.get_transfer(tid)
    return FileResponse(path, filename=Path(row["path"]).name)


# ---------------------------------------------------------------- insights
@app.get("/api/a/{aid}/storage")
async def storage(aid: int):
    return await maintenance.storage(acc(aid))


@app.get("/api/a/{aid}/duplicates")
async def duplicates(aid: int, mode: str = "exact", offset: int = 0):
    return await maintenance.duplicates(acc(aid), mode, offset)


@app.get("/api/a/{aid}/activity")
async def activity(aid: int):
    return {"activity": acc(aid).db.q("SELECT at, action, detail FROM activity ORDER BY id DESC LIMIT 300")}


@app.post("/api/a/{aid}/maintenance/{task}")
async def maintenance_task(aid: int, task: str):
    try:
        return await maintenance.run_task(acc(aid), task)
    except ValueError as exc:
        raise AccountError(str(exc))


@app.get("/api/a/{aid}/export.csv")
async def export(aid: int, request: Request):
    a = acc(aid)
    data = await maintenance.export_csv(a, dict(request.query_params), a.drive.path)
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="tgdrive-{time.strftime("%Y%m%d-%H%M")}.csv"'})


# --------------------------------------------------------------- more routes
from .api_features import router as _features  # noqa: E402  (they use the helpers above)
from .dav import router as _dav  # noqa: E402

app.include_router(_features)
app.include_router(_dav)


# ------------------------------------------------------------------------ web
if WEB.is_dir():   # the Android app has its own interface and ships without the web one
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
async def index(request: Request):
    if config.ACCESS_TOKEN and request.query_params.get("t"):
        resp = RedirectResponse("/")
        resp.set_cookie("tgd", config.ACCESS_TOKEN, httponly=True, samesite="strict")
        return resp
    mp = RUNTIME.get("media_port")
    host = (request.url.hostname or "127.0.0.1").strip("[]")
    media = f" http://{'[' + host + ']' if ':' in host else host}:{mp}" if mp else ""
    csp = (f"default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
           f"font-src 'self' data:; img-src 'self' data: blob:{media}; media-src 'self' blob:{media}; "
           f"connect-src 'self'{media}; frame-src 'self'{media}; object-src 'none'; base-uri 'none'; "
           f"form-action 'self'; frame-ancestors 'self'")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/css/', f'"/static/v/{ASSET_TAG}/css/').replace('"/static/js/', f'"/static/v/{ASSET_TAG}/js/')
    return Response(html, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store", "Content-Security-Policy": csp})


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(WEB / "icon.svg", media_type="image/svg+xml")


@app.get("/manifest.webmanifest")
async def webmanifest():
    return JSONResponse({"name": "TG Drive", "short_name": "TG Drive", "start_url": "/", "display": "standalone",
                         "background_color": "#edf0f3", "theme_color": "#2a7fc9",
                         "icons": [{"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}]})
