"""HTTP routes for: subjects, smart/auto folders, photo timeline, chat context,
folder sync, drive-as-a-disk (WebDAV), crash reports,
diagnostics, settings export/import and desktop integration.

Kept apart from api.py (core browsing, files, folders, streaming, transfers) so each
file stays readable; both share the same app, security middleware and helpers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from .webapp import APIRouter, Body, JSONResponse, PlainTextResponse, Request
from telethon import utils as tl_utils
from telethon.tl import types

from . import autofile, config, diagnostics, integration, query
from .accounts import AccountError, events
from .db import Reader
from .drive import DriveError
from .settings import settings

router = APIRouter()


def core():
    from . import api
    return api


def acc(aid: int):
    return core().acc(aid)


def items_arg(body: dict):
    return core().items_arg(body)


# ------------------------------------------------------------------ subjects
@router.get("/api/a/{aid}/subjects")
async def subjects(aid: int):
    a = acc(aid)
    counts = {r["subject"]: r["n"] for r in await a.db.read.run(
        lambda r: r.q("SELECT subject, COUNT(*) AS n FROM file_subjects GROUP BY subject"), timeout=20)}
    out = [{**s, "n": counts.get(s["id"], 0)} for s in a.subjects.info()]
    known = {s["id"] for s in out}
    out += [{"id": k, "name": k.replace("_", " ").title(), "emoji": "", "n": n} for k, n in counts.items()
            if k not in known]
    return {"subjects": out, "status": a.subjects.status(), "enabled": bool(settings.get("subjects_enabled", True))}


@router.post("/api/a/{aid}/subjects/set")
async def subjects_set(aid: int, body: dict = Body(...)):
    """Set (or clear, with subject null) the subject of files by hand; the tagger won't change it again."""
    a = acc(aid)
    items = items_arg(body)
    sid = body.get("subject") or None
    ids = []
    for cid, mid in items:
        row = a.db.one("SELECT id FROM files WHERE chat_id=? AND msg_id=?", (cid, mid))
        if row:
            ids.append(row["id"])
    with a.db.tx():
        for fid in ids:
            if sid:
                a.db.x("INSERT OR REPLACE INTO file_subjects(file_id, subject, score, src) VALUES(?,?,?, 'manual')",
                       (fid, str(sid)[:60], 99.0))
            else:
                a.db.x("DELETE FROM file_subjects WHERE file_id=?", (fid,))
                a.db.x("INSERT INTO file_subjects(file_id, subject, score, src) VALUES(?, '_none', 0, 'manual')", (fid,))
    return {"n": len(ids)}


@router.post("/api/a/{aid}/subjects/tags")
async def subjects_to_tags(aid: int, body: dict = Body(...)):
    """Turn subjects into real (synced) tags for the given files or for every file matching params."""
    a = acc(aid)
    names = {s["id"]: s["name"].lower() for s in a.subjects.info()}
    if body.get("items"):
        items = items_arg(body)
    else:
        p = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
        p.update(limit="500", sort="date")
        items, cursor = [], None
        while len(items) < 20000:
            if cursor:
                p["cursor"] = cursor
            res = await a.search.files(p)
            items += [(r["chat_id"], r["msg_id"]) for r in res["items"]]
            cursor = res.get("next")
            if not cursor:
                break
    by_subject: dict[str, list] = {}
    for cid, mid in items:
        row = a.db.one("SELECT s.subject FROM files f JOIN file_subjects s ON s.file_id=f.id "
                       "WHERE f.chat_id=? AND f.msg_id=?", (cid, mid))
        if row and row["subject"] in names:
            by_subject.setdefault(names[row["subject"]], []).append((cid, mid))
    n = 0
    for tag, its in by_subject.items():
        for i in range(0, len(its), 1000):
            await a.drive.set_meta_items(its[i:i + 1000], tags_add=[tag])
        n += len(its)
    return {"tagged": n, "tags": sorted(by_subject)}


@router.post("/api/a/{aid}/subjects/rebuild")
async def subjects_rebuild(aid: int):
    acc(aid).subjects.rebuild()
    return {"ok": True}


# --------------------------------------------------------------- rule folders
@router.post("/api/a/{aid}/folders/{fid}/apply-rules")
async def apply_rules(aid: int, fid: str):
    a = acc(aid)
    f = a.db.get_folder(fid)
    if not f:
        raise DriveError("That folder no longer exists.")
    if not autofile.folder_rules(f):
        raise DriveError("This folder has no rule.")
    n = await a.autofile.run_folder(f)
    core().dav_invalidate()
    return {"filed": n}


@router.post("/api/a/{aid}/rules/preview")
async def rules_preview(aid: int, body: dict = Body(...)):
    """How many files a rule matches (and how many are not in a folder yet)."""
    a = acc(aid)
    p = {str(k): str(v) for k, v in (body.get("params") or {}).items() if v not in (None, "")}
    if body.get("q"):
        p["q"] = str(body["q"])
    if not p:
        return {"total": 0, "unfiled": 0}
    st = await a.search.stats(dict(p))
    un = await a.search.stats({**p, "filed": "0"})
    sample = await a.search.files({**p, "limit": "6"})
    return {"total": st["total"], "unfiled": un["total"],
            "sample": [core().file_out(r) for r in sample["items"] if r.get("match") != "related"]}


_cover_cache: dict[int, tuple[float, dict]] = {}


@router.get("/api/a/{aid}/folders/covers")
async def folder_covers(aid: int):
    """Up to four recent pictures per folder, for folder cards without a chosen cover."""
    a = acc(aid)
    hit = _cover_cache.get(aid)
    if hit and time.time() - hit[0] < 30:
        return hit[1]

    def job(r: Reader) -> dict:
        rows = r.q("SELECT folder_id, chat_id, msg_id, stripped, kind FROM (SELECT p.folder_id, f.chat_id, f.msg_id, "
                   "f.stripped, f.kind, ROW_NUMBER() OVER (PARTITION BY p.folder_id ORDER BY f.date DESC) AS rn "
                   "FROM placements p JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id "
                   "WHERE p.folder_id IS NOT NULL AND f.has_thumb=1 AND f.kind IN ('photo','video','gif','round',"
                   "'document')) WHERE rn <= 4")
        out: dict[str, list] = {}
        import base64
        for row in rows:
            out.setdefault(row["folder_id"], []).append(
                {"chat_id": row["chat_id"], "msg_id": row["msg_id"], "kind": row["kind"], "has_thumb": True,
                 "inline": base64.b64encode(row["stripped"]).decode() if row["stripped"] else None})
        return out

    res = {"covers": await a.db.read.run(job, timeout=30)}
    _cover_cache[aid] = (time.time(), res)
    return res


# ------------------------------------------------------------- photo timeline
@router.get("/api/a/{aid}/timeline")
async def timeline(aid: int, request: Request):
    """Files per month (newest first) for the photo timeline and its date scrubber."""
    a = acc(aid)
    p = dict(request.query_params)
    p.setdefault("kinds", "photo,video")
    f = query.from_params(p)
    where, params = query.build_where(f, descendants=a.drive._descendants)
    rows = await a.db.read.run(lambda r: r.q(
        f"SELECT strftime('%Y-%m', f.date, 'unixepoch', 'localtime') AS ym, COUNT(*) AS n FROM files f "
        f"WHERE {where} GROUP BY ym ORDER BY ym DESC", params), timeout=30)
    return {"months": [r for r in rows if r["ym"]], "total": sum(r["n"] for r in rows)}


# ------------------------------------------------------------- chat context
def _media_label(m) -> Optional[str]:
    media = getattr(m, "media", None)
    if media is None:
        return None
    if isinstance(media, types.MessageMediaWebPage):
        return None
    if isinstance(media, types.MessageMediaPoll):
        return "Poll"
    if isinstance(media, (types.MessageMediaGeo, types.MessageMediaGeoLive, types.MessageMediaVenue)):
        return "Location"
    if isinstance(media, types.MessageMediaContact):
        return "Contact"
    if isinstance(media, types.MessageMediaDocument) and media.document and any(
            isinstance(x, types.DocumentAttributeSticker) for x in getattr(media.document, "attributes", []) or []):
        return "Sticker"
    return "File"


@router.get("/api/a/{aid}/context/{cid}/{mid}")
async def chat_context(aid: int, cid: int, mid: int, before: int = 15, after: int = 15):
    """The messages around a file in its chat (text, replies, other files), fetched live from Telegram."""
    a = acc(aid)
    a.require_online()
    before, after = max(0, min(before, 60)), max(0, min(after, 60))
    peer = await a.peer(cid)
    older = [m async for m in a.client.iter_messages(peer, limit=before, offset_id=mid)] if before else []
    newer = [m async for m in a.client.iter_messages(peer, limit=after, min_id=mid, reverse=True)] if after else []
    target = await a.client.get_messages(peer, ids=mid)
    msgs = [m for m in list(reversed(older)) + ([target] if target else []) + newer
            if isinstance(m, types.Message)]
    chat = a.db.get_chat(cid) or {}
    out = []
    for m in msgs:
        sender = getattr(m, "sender", None)
        name = tl_utils.get_display_name(sender) if sender else (getattr(m, "post_author", None) or
                                                                   (chat.get("title") if chat.get("kind") == "channel"
                                                                    else ""))
        row = a.db.get_file(cid, m.id) if m.media else None
        fwd = None
        if m.fwd_from:
            fwd = getattr(m.fwd_from, "from_name", None) or "Forwarded"
        out.append({"id": m.id, "date": int(m.date.timestamp()) if m.date else None, "text": (m.message or "")[:4000],
                    "out": bool(m.out), "sender": name or "", "sender_id": getattr(m, "sender_id", None),
                    "reply_to": getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None), "fwd": fwd,
                    "media": _media_label(m), "file": core().file_out(row) if row else None,
                    "target": m.id == mid})
    return {"chat": {"id": cid, "title": chat.get("title"), "kind": chat.get("kind"), "username": chat.get("username")},
            "messages": out, "has_older": len(older) == before and before > 0,
            "has_newer": len(newer) == after and after > 0}


# -------------------------------------------------------------------- sync
@router.get("/api/a/{aid}/sync")
async def sync_list(aid: int):
    return {"pairs": acc(aid).sync.pairs(), "enabled": bool(settings.get("sync_enabled", True))}


@router.post("/api/a/{aid}/sync")
async def sync_add(aid: int, body: dict = Body(...)):
    from .sync import SyncError
    try:
        return await acc(aid).sync.add_pair(str(body.get("local_path") or ""), str(body.get("folder_id") or ""))
    except SyncError as exc:
        raise AccountError(str(exc))


@router.post("/api/a/{aid}/sync/{pid}/{action}")
async def sync_action(aid: int, pid: int, action: str, body: dict = Body(default={})):
    a = acc(aid)
    s = a.sync
    if action == "approve":
        s.approve(pid)
    elif action == "run":
        return await s.run_pair(pid, force=bool(body.get("force")))
    elif action == "preview":
        return await s.run_pair(pid, dry=True)
    elif action == "enable":
        s.set_enabled(pid, bool(body.get("on", True)))
    elif action == "open":
        row = a.db.one("SELECT local_path FROM sync_pairs WHERE id=?", (pid,))
        if row:
            from .accounts import xdg_open
            xdg_open(row["local_path"])
    else:
        raise AccountError("Unknown action.")
    return {"ok": True}


@router.delete("/api/a/{aid}/sync/{pid}")
async def sync_remove(aid: int, pid: int):
    acc(aid).sync.remove(pid)
    return {"ok": True}


# ----------------------------------------------------------- drive as a disk
def _dav_info() -> dict:
    from . import dav
    port = core().RUNTIME.get("port") or config.PORT
    return {"enabled": bool(settings.get("dav_enabled")), "write": bool(settings.get("dav_write", True)),
            "url": dav.dav_url(port), "http": f"http://127.0.0.1:{port}/dav/{dav.dav_secret()}/",
            "gio": bool(shutil.which("gio")), "desktop": bool(core().RUNTIME.get("desktop"))}


@router.get("/api/dav")
async def dav_get():
    return _dav_info()


@router.post("/api/dav")
async def dav_set(body: dict = Body(...)):
    ch = {}
    if "enabled" in body:
        ch["dav_enabled"] = bool(body["enabled"])
    if "write" in body:
        ch["dav_write"] = bool(body["write"])
    if body.get("reset_secret"):
        import secrets
        ch["dav_secret"] = secrets.token_urlsafe(12)
    if ch:
        settings.update(ch)
    return _dav_info()


@router.post("/api/dav/mount")
async def dav_mount(body: dict = Body(default={})):
    """Mount with GVfs (GNOME Files, Nemo, Caja) and open it in the file manager."""
    from .accounts import clean_env, xdg_open
    info = _dav_info()
    if not info["enabled"]:
        settings.update({"dav_enabled": True})
        info = _dav_info()
    url = info["url"]
    if not info["gio"]:
        return {"mounted": False, "url": url, "message": "GVfs (gio) isn't installed. Use the address in your file "
                                                         "manager or with davfs2/rclone."}

    def run() -> tuple[int, str]:
        p = subprocess.run(["gio", "mount", url], capture_output=True, text=True, timeout=20, env=clean_env(),
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stderr or p.stdout or "").strip()
    try:
        code, msg = await asyncio.get_running_loop().run_in_executor(None, run)
    except (OSError, subprocess.SubprocessError) as exc:
        code, msg = 1, str(exc)
    already = "already mounted" in msg.lower()
    if code == 0 or already:
        if body.get("open", True):
            xdg_open(url)
        return {"mounted": True, "url": url}
    return {"mounted": False, "url": url, "message": msg[:300] or "gio mount failed."}


async def unmount_dav_quietly() -> None:
    """Quitting: take TG Drive's drive out of the file manager (a GVfs mount of a server that is gone
    only hangs file dialogs). Does nothing if it isn't mounted."""
    from .accounts import clean_env
    try:
        info = _dav_info()
    except Exception:
        return
    if not info["enabled"] or not info["gio"]:
        return
    try:
        p = await asyncio.create_subprocess_exec("gio", "mount", "-u", info["url"], stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env())
    except OSError:
        return
    try:
        await asyncio.wait_for(p.wait(), 5)
    except asyncio.TimeoutError:
        p.kill()


@router.post("/api/dav/unmount")
async def dav_unmount():
    from .accounts import clean_env
    info = _dav_info()
    if info["gio"]:
        subprocess.run(["gio", "mount", "-u", info["url"]], capture_output=True, timeout=20, env=clean_env())
    return {"ok": True}


# ------------------------------------------------------ crashes / diagnostics
_js_reports = {"n": 0}


@router.get("/api/crashes")
async def crashes():
    return diagnostics.list_crashes()


@router.get("/api/crashes/{rid}")
async def crash_read(rid: str):
    try:
        return PlainTextResponse(diagnostics.read_crash(rid))
    except ValueError as exc:
        raise AccountError(str(exc))


@router.post("/api/crashes/seen")
async def crashes_seen():
    diagnostics.mark_seen()
    return {"ok": True}


@router.delete("/api/crashes")
async def crashes_clear():
    return {"removed": diagnostics.clear_crashes()}


@router.post("/api/issue-context")
async def issue_context(body: dict = Body(default={})):
    """For "Create GitHub issue" in the window's error dialog: the error texts and the end of the log,
    with secrets, numbers, e-mail addresses and chat/file names removed, and what the app runs on."""
    def build() -> dict:
        from . import maintenance
        texts = [diagnostics.redact(str(t or "")[:20000], [], False) for t in (body.get("texts") or [])[:4]]
        tail = ""
        try:
            with open(maintenance.log_path(), "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 16384))
                tail = "\n".join(f.read().decode("utf-8", "replace").splitlines()[1:][-40:])
        except OSError:
            pass
        info = diagnostics.system_info()
        env = {k: info.get(k) for k in ("tgdrive", "python", "platform", "desktop", "session", "packaged", "appimage")}
        return {"texts": texts, "log": diagnostics.redact(tail, [], False), "env": env}
    return await asyncio.get_running_loop().run_in_executor(None, build)


@router.post("/api/crash")
async def crash_from_page(body: dict = Body(...)):
    """Errors in the web page (sent by the page itself, a few per session at most)."""
    if _js_reports["n"] >= 20:
        return {"ok": False}
    _js_reports["n"] += 1
    text = f"{str(body.get('message') or '')[:2000]}\n\n{str(body.get('stack') or '')[:20000]}"
    rid = diagnostics.record_crash("page", text, {"view": str(body.get("view") or "")[:200],
                                                  "source": str(body.get("source") or "")[:300],
                                                  "agent": str(body.get("agent") or "")[:300]})
    return {"ok": True, "id": rid}


# ------------------------------------------------------------ debug logging
_page_log = logging.getLogger("tgdrive.page")
_PAGE_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "warning": logging.WARNING,
                "error": logging.ERROR}


@router.get("/api/debuglog")
async def debug_log(lines: int = 400, which: str = "debug"):
    from . import maintenance
    text = maintenance.tail_debug_log(min(lines, 20000)) if which == "debug" else maintenance.tail_log(min(lines, 20000))
    return {"on": maintenance.debug_enabled(), "text": text, "files": maintenance.log_files(),
            "path": str(maintenance.debug_log_path() if which == "debug" else maintenance.log_path())}


@router.get("/api/logs/download")
async def download_log(which: str = "debug"):
    from .webapp import FileResponse
    from . import maintenance
    p = maintenance.debug_log_path() if which == "debug" else maintenance.log_path()
    if not p.exists():
        return PlainTextResponse("", headers={"Content-Disposition": f'attachment; filename="{p.name}"'})
    return FileResponse(p, media_type="text/plain; charset=utf-8", filename=f"{p.stem}-{time.strftime('%Y%m%d-%H%M%S')}.log")


@router.delete("/api/logs")
async def clear_logs(crashes: int = 0):
    from . import maintenance
    res = await asyncio.get_running_loop().run_in_executor(None, maintenance.clear_logs)
    if crashes:
        res["crashes"] = diagnostics.clear_crashes()
    return res


@router.post("/api/clientlog")
async def client_log(body: dict = Body(default={})):
    """What the page did (clicks, navigation, requests, errors), written to the debug log while it's on."""
    from . import maintenance
    if not maintenance.debug_enabled():
        return {"ok": False, "on": False}
    entries = body.get("entries") or []
    for e in entries[:500]:
        if not isinstance(e, dict):
            continue
        level = _PAGE_LEVELS.get(str(e.get("level") or "debug"), logging.DEBUG)
        cat = str(e.get("cat") or "page")[:24]
        msg = str(e.get("msg") or "")[:4000]
        data = e.get("data")
        at = e.get("t")
        stamp = time.strftime("%H:%M:%S", time.localtime(float(at))) + f".{int((float(at) % 1) * 1000):03d}" \
            if isinstance(at, (int, float)) else "?"
        extra = ""
        if data not in (None, "", {}, []):
            try:
                extra = " | " + json.dumps(data, ensure_ascii=False, default=str)[:6000]
            except (TypeError, ValueError):
                extra = " | " + str(data)[:6000]
        _page_log.log(level, "[%s] %s (page %s)%s", cat, msg, stamp, extra)
    return {"ok": True, "on": True}


@router.post("/api/diagnostics")
async def diagnostics_bundle(body: dict = Body(default={})):
    accs = list(core().manager.accounts.values())
    path = await asyncio.get_running_loop().run_in_executor(
        None, lambda: diagnostics.build_bundle(accs, include_names=bool(body.get("include_names"))))
    return {"path": str(path), "bytes": path.stat().st_size}


@router.get("/api/system")
async def system():
    return diagnostics.system_info()


# --------------------------------------------------------- settings backup
@router.get("/api/settings/export")
async def settings_export(include_api: int = 0):
    data = diagnostics.export_settings(include_api=bool(include_api))
    name = f"tgdrive-settings-{time.strftime('%Y%m%d')}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/settings/import")
async def settings_import(body: dict = Body(...)):
    try:
        res = diagnostics.import_settings(body)
    except ValueError as exc:
        raise AccountError(str(exc))
    return {**res, "settings": settings.public()}


# ------------------------------------------------------- desktop integration
@router.get("/api/integration")
async def integration_status():
    return integration.status()


@router.post("/api/integration/{action}")
async def integration_action(action: str):
    try:
        if action == "install-menu":
            integration.install_menu()
        elif action == "uninstall-menu":
            integration.uninstall_menu()
        elif action == "install-file-managers":
            integration.install_file_manager_actions()
        elif action == "uninstall-file-managers":
            integration.uninstall_file_manager_actions()
        else:
            raise AccountError("Unknown action.")
    except OSError as exc:
        raise AccountError(f"Couldn't change the desktop setup: {exc}")
    return integration.status()


@router.post("/api/focus")
async def focus_window():
    events.push("focus")
    return {"ok": True}


@router.get("/api/paths/check")
async def paths_check(paths: str):
    """Sizes of local paths handed over by the file manager (for the upload dialog)."""
    out = []
    for raw in json.loads(paths)[:500]:
        p = Path(raw)
        try:
            if p.is_dir():
                n = size = 0
                for f in p.rglob("*"):
                    if f.is_file() and not any(part.startswith(".") for part in f.relative_to(p).parts):
                        n += 1
                        size += f.stat().st_size
                        if n > 100000:
                            break
                out.append({"path": raw, "name": p.name, "dir": True, "files": n, "bytes": size})
            elif p.is_file():
                out.append({"path": raw, "name": p.name, "dir": False, "files": 1, "bytes": p.stat().st_size})
        except OSError:
            continue
    return {"items": out}
