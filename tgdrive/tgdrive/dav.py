"""TG Drive as a drive: a small WebDAV server, so any app can open your Telegram files.

Mount it from Settings → Drive on this computer (GNOME Files / Nemo / Caja through
GVfs, Dolphin through KIO, or davfs2/rclone for a real mount point):

    dav://127.0.0.1:<port>/dav/<secret>/

Layout:
    My Drive/…          your folders (read-write: copy files in to upload, make folders,
                        rename and move; deleting takes a file out of the folder, it stays in Telegram)
    Starred/            starred files
    Chats/<chat>/       every chat's files (by year for big chats)
    Saved searches/<name>/
    Subjects/<subject>/
With several accounts, each account is a top-level folder.

Files stream straight from Telegram with byte ranges (seeking in videos works),
reusing the same cache as the app. The address carries a random secret and only
answers on 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from email.utils import formatdate
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from .tasks import spawn
from .settings import settings
from .streaming import StreamError, parse_range
from .transfers import TransferError, ensure_space, safe_filename

log = logging.getLogger("tgdrive.dav")
router = APIRouter()

CACHE_TTL = 20.0
BIG_CHAT = 3000
MAX_LIST = 20000

MY_DRIVE, STARRED, CHATS, SAVED, SUBJECTS = "My Drive", "Starred", "Chats", "Saved searches", "Subjects"


def manager():
    from .api import manager as m
    return m


def dav_secret() -> str:
    s = settings.get("dav_secret")
    if not s:
        s = secrets.token_urlsafe(12)
        settings.update({"dav_secret": s})
    return s


def dav_url(port: int) -> str:
    return f"dav://127.0.0.1:{port}/dav/{dav_secret()}/"


# ------------------------------------------------------------------ nodes
class Node:
    __slots__ = ("name", "is_dir", "size", "mtime", "chat_id", "msg_id", "folder_id", "kind", "mime", "writable",
                 "pending")

    def __init__(self, name: str, is_dir: bool, size: int = 0, mtime: int = 0, chat_id: int = 0, msg_id: int = 0,
                 folder_id: Optional[str] = None, kind: str = "", mime: str = "", writable: bool = False,
                 pending: bool = False):
        self.name, self.is_dir, self.size, self.mtime = name, is_dir, size, mtime
        self.chat_id, self.msg_id, self.folder_id, self.kind = chat_id, msg_id, folder_id, kind
        self.mime, self.writable, self.pending = mime, writable, pending


def _dedupe(rows: list[dict]) -> list[Node]:
    out: list[Node] = []
    seen: set[str] = set()
    for r in rows:
        name = safe_filename(r.get("alias") or r.get("name") or "file")
        cand, n = name, 1
        while cand.lower() in seen:
            n += 1
            stem, dot, ext = name.rpartition(".")
            cand = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
        seen.add(cand.lower())
        out.append(Node(cand, False, r.get("size") or 0, r.get("date") or 0, r["chat_id"], r["msg_id"],
                        mime=r.get("mime") or ""))
    return out


class Tree:
    """Resolves DAV paths to nodes for one account; listings are cached briefly."""

    # (account, folder) -> {name: [size, transfer id]} for uploads still on their way to Telegram
    uploads: dict[tuple[int, Optional[str]], dict[str, list]] = {}

    def __init__(self, acc):
        self.acc = acc
        self.db = acc.db
        self.cache: dict[tuple, tuple[float, list[Node]]] = {}

    def _cached(self, key: tuple, fn) -> list[Node]:
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        val = fn()
        self.cache[key] = (time.time(), val)
        if len(self.cache) > 200:
            self.cache.pop(next(iter(self.cache)))
        return val

    def invalidate(self) -> None:
        self.cache.clear()

    FILE_COLS = "f.chat_id, f.msg_id, f.name, f.alias, f.size, f.date, f.mime, f.kind"

    # ---------------------------------------------------------- listings
    def root(self) -> list[Node]:
        return [Node(n, True, writable=(n == MY_DRIVE)) for n in (MY_DRIVE, STARRED, CHATS, SAVED, SUBJECTS)]

    def drive_folder(self, folder_id: Optional[str]) -> list[Node]:
        def build():
            subs = self.db.q("SELECT id, name FROM folders WHERE parent_id IS ? ORDER BY name COLLATE NOCASE",
                             (folder_id,))
            nodes = [Node(safe_filename(f["name"]), True, folder_id=f["id"], writable=True) for f in subs]
            if folder_id:
                rows = self.db.q(f"SELECT {self.FILE_COLS} FROM placements p JOIN files f ON f.chat_id=p.chat_id "
                                 f"AND f.msg_id=p.msg_id WHERE p.folder_id=? ORDER BY f.chat_id, f.msg_id",
                                 (folder_id,))
            else:
                ch = self.acc.drive.channel_id
                rows = self.db.q(f"SELECT {self.FILE_COLS} FROM files f WHERE f.chat_id=? AND NOT EXISTS (SELECT 1 "
                                 f"FROM placements p WHERE p.chat_id=f.chat_id AND p.msg_id=f.msg_id AND p.folder_id "
                                 f"IS NOT NULL) ORDER BY f.msg_id LIMIT ?", (ch, MAX_LIST)) if ch else []
            files = _dedupe(rows)
            for n in files:
                n.writable = True
                n.folder_id = folder_id
            return nodes + files
        nodes = self._cached(("drive", folder_id), build)
        pend = self.uploads.get((self.acc.uid, folder_id)) or {}
        finished = False
        for name, (_, tid) in list(pend.items()):
            t = self.db.get_transfer(tid) if tid else None
            if not t or t["status"] in ("done", "cancelled", "error"):
                pend.pop(name, None)  # finished: the real file (if any) is in the listing now
                finished = True
        if finished:
            self.cache.pop(("drive", folder_id), None)
            nodes = self._cached(("drive", folder_id), build)
        have = {n.name.lower() for n in nodes}
        extra = [Node(name, False, size, int(time.time()), folder_id=folder_id, writable=True, pending=True)
                 for name, (size, _) in pend.items() if name.lower() not in have]
        return nodes + extra

    def chats(self) -> list[Node]:
        def build():
            rows = self.db.q("SELECT id, title FROM chats WHERE file_count > 0 AND excluded=0 ORDER BY title COLLATE NOCASE")
            seen, out = set(), []
            for r in rows:
                name = safe_filename(r["title"] or str(r["id"]))
                if name.lower() in seen:
                    name = f"{name} ({r['id']})"
                seen.add(name.lower())
                n = Node(name, True)
                n.chat_id = r["id"]
                out.append(n)
            return out
        return self._cached(("chats",), build)

    def chat_files(self, chat_id: int, year: Optional[str] = None) -> list[Node]:
        def build():
            n = self.db.one("SELECT file_count FROM chats WHERE id=?", (chat_id,)) or {"file_count": 0}
            if year is None and (n["file_count"] or 0) > BIG_CHAT:
                years = self.db.q("SELECT DISTINCT strftime('%Y', date, 'unixepoch', 'localtime') AS y FROM files "
                                  "WHERE chat_id=? ORDER BY y DESC", (chat_id,))
                out = []
                for y in years:
                    node = Node(y["y"] or "Undated", True)
                    node.chat_id = chat_id
                    out.append(node)
                return out
            if year:
                rows = self.db.q(f"SELECT {self.FILE_COLS} FROM files f WHERE f.chat_id=? AND "
                                 f"strftime('%Y', f.date, 'unixepoch', 'localtime') IS ? ORDER BY f.msg_id LIMIT ?",
                                 (chat_id, None if year == "Undated" else year, MAX_LIST))
            else:
                rows = self.db.q(f"SELECT {self.FILE_COLS} FROM files f WHERE f.chat_id=? ORDER BY f.msg_id LIMIT ?",
                                 (chat_id, MAX_LIST))
            return _dedupe(rows)
        return self._cached(("chat", chat_id, year), build)

    def starred(self) -> list[Node]:
        return self._cached(("starred",), lambda: _dedupe(self.db.q(
            f"SELECT {self.FILE_COLS} FROM placements p JOIN files f ON f.chat_id=p.chat_id AND f.msg_id=p.msg_id "
            f"WHERE p.starred=1 ORDER BY f.date DESC LIMIT ?", (MAX_LIST,))))

    def saved_list(self) -> list[Node]:
        return [Node(safe_filename(s["name"]), True, folder_id=s["id"]) for s in self.acc.drive.saved_searches()]

    def subjects_list(self) -> list[Node]:
        names = {s["id"]: s["name"] for s in self.acc.subjects.info()}
        rows = self.db.q("SELECT subject, COUNT(*) AS n FROM file_subjects GROUP BY subject ORDER BY n DESC")
        return [Node(safe_filename(names.get(r["subject"], r["subject"])), True, folder_id=r["subject"]) for r in rows]

    async def search_files(self, key: tuple, params: dict) -> list[Node]:
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        p = {**params, "limit": "500", "sort": "date", "order": "desc"}
        rows: list[dict] = []
        cursor = None
        while len(rows) < 2000:
            if cursor:
                p["cursor"] = cursor
            res = await self.acc.search.files(p)
            rows += res["items"]
            cursor = res.get("next")
            if not cursor:
                break
        val = _dedupe(rows)
        self.cache[key] = (time.time(), val)
        return val

    # ---------------------------------------------------------- resolve
    async def children(self, parts: list[str]) -> Optional[list[Node]]:
        """Children of the directory at `parts`, or None if it isn't a directory."""
        if not parts:
            return self.root()
        top, rest = parts[0], parts[1:]
        if top == MY_DRIVE:
            fid: Optional[str] = None
            for name in rest:
                sub = next((n for n in self.drive_folder(fid) if n.is_dir and n.name == name), None)
                if not sub:
                    return None
                fid = sub.folder_id
            return self.drive_folder(fid)
        if top == STARRED:
            return self.starred() if not rest else None
        if top == CHATS:
            if not rest:
                return self.chats()
            chat = next((n for n in self.chats() if n.name == rest[0]), None)
            if not chat:
                return None
            if len(rest) == 1:
                return self.chat_files(chat.chat_id)
            if len(rest) == 2:
                if not any(n.is_dir and n.name == rest[1] for n in self.chat_files(chat.chat_id)):
                    return None
                return self.chat_files(chat.chat_id, rest[1])
            return None
        if top == SAVED:
            if not rest:
                return self.saved_list()
            s = next((n for n in self.saved_list() if n.name == rest[0]), None)
            if not s or len(rest) > 1:
                return None
            saved = next(x for x in self.acc.drive.saved_searches() if x["id"] == s.folder_id)
            params = {k: str(v) for k, v in (saved.get("params") or {}).items()}
            if saved.get("q"):
                params["q"] = saved["q"]
            return await self.search_files(("saved", s.folder_id), params)
        if top == SUBJECTS:
            if not rest:
                return self.subjects_list()
            s = next((n for n in self.subjects_list() if n.name == rest[0]), None)
            if not s or len(rest) > 1:
                return None
            return await self.search_files(("subject", s.folder_id), {"subject": s.folder_id})
        return None

    async def node(self, parts: list[str]) -> Optional[Node]:
        if not parts:
            return Node("TG Drive", True)
        kids = await self.children(parts[:-1])
        if kids is None:
            return None
        return next((n for n in kids if n.name == parts[-1]), None)

    def drive_folder_id(self, parts: list[str]) -> tuple[bool, Optional[str]]:
        """(True, folder id) if parts is My Drive or a folder inside it."""
        if not parts or parts[0] != MY_DRIVE:
            return False, None
        fid: Optional[str] = None
        for name in parts[1:]:
            sub = next((n for n in self.drive_folder(fid) if n.is_dir and n.name == name), None)
            if not sub:
                return False, None
            fid = sub.folder_id
        return True, fid


_trees: dict[int, Tree] = {}


def tree_for(acc) -> Tree:
    t = _trees.get(acc.uid)
    if t is None or t.acc is not acc:
        t = _trees[acc.uid] = Tree(acc)
    return t


def invalidate_all() -> None:
    for t in _trees.values():
        t.invalidate()


# --------------------------------------------------------------- helpers
def _split(path: str) -> list[str]:
    return [unquote(p) for p in path.split("/") if p]


def _resolve_account(parts: list[str]):
    """With one account the tree starts at its content; with several, each is a top-level folder."""
    accs = list(manager().accounts.values())
    if not accs:
        return None, parts, []
    if len(accs) == 1:
        return accs[0], parts, []
    names = {}
    for a in accs:
        names[safe_filename(a.info()["name"])] = a
    if not parts:
        return None, parts, list(names)
    a = names.get(parts[0])
    return a, parts[1:], [parts[0]]


def _httpdate(ts: int) -> str:
    return formatdate(ts or 0, usegmt=True)


def _prop_xml(href: str, n: Node) -> str:
    if not n.mtime:  # folders have no date of their own; "now" beats 1970 in file managers
        n.mtime = int(time.time())
    if n.is_dir:
        rt = "<D:resourcetype><D:collection/></D:resourcetype>"
        extra = ""
    else:
        rt = "<D:resourcetype/>"
        extra = (f"<D:getcontentlength>{n.size}</D:getcontentlength>"
                 f"<D:getcontenttype>{escape(n.mime or 'application/octet-stream')}</D:getcontenttype>"
                 f"<D:getetag>\"{n.chat_id}-{n.msg_id}-{n.size}\"</D:getetag>")
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(n.mtime or 0))
    return (f"<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>"
            f"<D:displayname>{escape(n.name)}</D:displayname>{rt}{extra}"
            f"<D:getlastmodified>{_httpdate(n.mtime)}</D:getlastmodified><D:creationdate>{created}</D:creationdate>"
            f"<D:supportedlock><D:lockentry><D:lockscope><D:exclusive/></D:lockscope><D:locktype><D:write/>"
            f"</D:locktype></D:lockentry></D:supportedlock>"
            f"</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>")


def _multistatus(body: str) -> Response:
    xml = f'<?xml version="1.0" encoding="utf-8"?>\n<D:multistatus xmlns:D="DAV:">{body}</D:multistatus>'
    return Response(xml, status_code=207, media_type='application/xml; charset="utf-8"')


def _check(secret: str) -> Optional[Response]:
    from . import maintenance
    if not settings.get("dav_enabled"):
        return Response("TG Drive's drive access is off (Settings → Drive on this computer).", status_code=403)
    if not secrets.compare_digest(secret, dav_secret()):
        return Response(status_code=404)
    if maintenance.app_lock.locked():
        return Response("TG Drive is locked.", status_code=423)
    return None


# ----------------------------------------------------------------- routes
DAV_METHODS = ["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "MKCOL", "DELETE", "MOVE", "COPY", "LOCK", "UNLOCK",
               "PROPPATCH"]


@router.api_route("/dav/{secret}", methods=DAV_METHODS)
@router.api_route("/dav/{secret}/{path:path}", methods=DAV_METHODS)
async def dav(secret: str, request: Request, path: str = ""):
    bad = _check(secret)
    if bad:
        return bad
    m = request.method
    if m == "OPTIONS":
        return Response(headers={"DAV": "1, 2", "MS-Author-Via": "DAV",
                                 "Allow": ", ".join(DAV_METHODS)})
    base = f"/dav/{secret}/"
    parts = _split(path)
    acc, sub, prefix = _resolve_account(parts)
    if acc is None:
        if m == "PROPFIND":
            body = _prop_xml(base, Node("TG Drive", True))
            if request.headers.get("depth", "1") != "0":
                for name in prefix or []:
                    body += _prop_xml(base + quote(name) + "/", Node(name, True))
            return _multistatus(body)
        return Response(status_code=404 if parts else 200)
    tree = tree_for(acc)
    handler = {"PROPFIND": _propfind, "GET": _get, "HEAD": _get, "PUT": _put, "MKCOL": _mkcol, "DELETE": _delete,
               "MOVE": _move, "COPY": _copy, "LOCK": _lock, "UNLOCK": _unlock, "PROPPATCH": _proppatch}[m]
    return await handler(request, tree, sub, base + "".join(quote(p) + "/" for p in prefix))


async def _propfind(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    node = await tree.node(parts)
    if node is None:
        return Response(status_code=404)
    href = base + "/".join(quote(p) for p in parts) + ("/" if node.is_dir and parts else "")
    body = _prop_xml(href, node)
    if node.is_dir and request.headers.get("depth", "1") != "0":
        kids = await tree.children(parts) or []
        prefix = href if href.endswith("/") else href + "/"
        body += "".join(_prop_xml(prefix + quote(k.name) + ("/" if k.is_dir else ""), k) for k in kids)
    return _multistatus(body)


async def _get(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    node = await tree.node(parts)
    if node is None:
        return Response(status_code=404)
    if node.is_dir:
        kids = await tree.children(parts) or []
        rows = "".join(f'<li><a href="{quote(k.name)}{"/" if k.is_dir else ""}">{escape(k.name)}{"/" if k.is_dir else ""}'
                       f'</a></li>' for k in kids)
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>TG Drive</title><ul>{rows}</ul>",
                            headers={"Content-Security-Policy": "default-src 'none'"})
    if node.pending:
        return Response("Still uploading to Telegram.", status_code=409)
    acc = tree.acc
    try:
        src = await acc.streamer.source(node.chat_id, node.msg_id)
    except Exception as exc:
        return Response(str(exc), status_code=404)
    mime = src.mime or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "ETag": f'"{node.chat_id}-{node.msg_id}-{node.size}"',
               "Last-Modified": _httpdate(node.mtime), "Content-Type": mime}
    if src.local:
        return FileResponse(src.local, media_type=mime, headers={k: v for k, v in headers.items() if k != "Content-Type"})
    size = src.size
    try:
        rng = parse_range(request.headers.get("range"), size)
    except StreamError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = rng if rng else (0, size - 1)
    headers["Content-Length"] = str(max(0, end - start + 1))
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    code = 206 if rng else 200
    if request.method == "HEAD" or size == 0:
        return Response(status_code=code, headers=headers)
    prefetch = int(settings.get("stream_prefetch") or 4)
    return StreamingResponse(acc.streamer.iter_range(src, start, end, prefetch=prefetch), status_code=code,
                             headers=headers, media_type=mime)


def _writable(tree: Tree, parts: list[str]) -> tuple[bool, Optional[str]]:
    if not settings.get("dav_write", True):
        return False, None
    return tree.drive_folder_id(parts)


async def _put(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    if not parts:
        return Response(status_code=405)
    ok, fid = _writable(tree, parts[:-1])
    if not ok:
        return Response("Only My Drive can take new files.", status_code=403)
    acc = tree.acc
    name = parts[-1]
    if name.startswith(".") or name.endswith(("~", ".part")) or name.startswith(".goutputstream"):
        # editors' temporary files: accept and drop, never upload
        async for _ in request.stream():
            pass
        return Response(status_code=201)
    acc.require_online()
    existing = await tree.node(parts)
    old = (existing.chat_id, existing.msg_id) if existing and not existing.is_dir and not existing.pending else None
    tmp = acc.transfers.new_upload_path()
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    try:
        ensure_space(tmp, length, f"“{name}”")
    except TransferError as exc:
        return Response(str(exc), status_code=507)
    size = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
                size += len(chunk)
    except BaseException:   # the client went away mid-upload: don't leave the partial copy behind
        Path(tmp).unlink(missing_ok=True)
        raise
    if size == 0:
        Path(tmp).unlink(missing_ok=True)
        return Response(status_code=201)  # clients create empty files first; the real PUT follows
    key = (acc.uid, fid)
    try:
        tid = acc.transfers.add_upload(Path(tmp), name, fid)
    except Exception as exc:
        Path(tmp).unlink(missing_ok=True)
        return Response(str(exc), status_code=507)
    Tree.uploads.setdefault(key, {})[name] = [size, tid]
    spawn(_forget_when_done(acc, tid, key, name, old), f"webdav upload {tid}")
    tree.invalidate()
    return Response(status_code=204 if old else 201)


async def _forget_when_done(acc, tid: int, key, name: str, old=None) -> None:
    t = None
    for _ in range(24 * 3600 // 2):
        await asyncio.sleep(2)
        t = acc.db.get_transfer(tid)
        if not t or t["status"] in ("done", "cancelled", "error"):
            break
    if old and t and t["status"] == "done":  # a new version replaced the old file: take the old one out
        try:
            await acc.drive.place([old], None, undo=False)
        except Exception as exc:
            log.warning("dav: could not unfile the replaced file: %s", exc)
    Tree.uploads.get(key, {}).pop(name, None)
    tree_for(acc).invalidate()


async def _mkcol(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    if not parts:
        return Response(status_code=405)
    ok, fid = _writable(tree, parts[:-1])
    if not ok:
        return Response(status_code=403)
    try:
        await tree.acc.drive.create_folder(parts[-1], fid)
    except Exception as exc:
        return Response(str(exc), status_code=405)
    tree.invalidate()
    return Response(status_code=201)


async def _delete(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    node = await tree.node(parts)
    if node is None:
        return Response(status_code=404)
    ok, _ = _writable(tree, parts[:-1])
    if not ok:
        return Response(status_code=403)
    drive = tree.acc.drive
    if node.is_dir:
        if not node.folder_id:
            return Response(status_code=403)
        await drive.delete_folder(node.folder_id)
    elif node.pending:
        return Response(status_code=409)
    else:
        await drive.place([(node.chat_id, node.msg_id)], None)
    tree.invalidate()
    return Response(status_code=204)


async def _move(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    node = await tree.node(parts)
    if node is None:
        return Response(status_code=404)
    dest = request.headers.get("destination") or ""
    dpath = unquote(urlsplit(dest).path)
    marker = base.rstrip("/")
    if not dpath.startswith(unquote(marker)):
        return Response("Moves only work inside TG Drive.", status_code=502)
    dparts = _split(dpath[len(unquote(marker)):])
    ok_src, _ = _writable(tree, parts[:-1])
    ok_dst, dfid = _writable(tree, dparts[:-1])
    if not (ok_src and ok_dst) or not dparts:
        return Response(status_code=403)
    existing = await tree.node(dparts)
    if existing is not None and request.headers.get("overwrite", "T").upper() == "F":
        return Response(status_code=412)
    drive = tree.acc.drive
    new_name = dparts[-1]
    try:
        if node.is_dir:
            if not node.folder_id:
                return Response(status_code=403)
            await drive.update_folder(node.folder_id, name=new_name, parent_id=dfid)
        else:
            if existing is not None and not existing.is_dir and (existing.chat_id, existing.msg_id) != \
                    (node.chat_id, node.msg_id):
                await drive.place([(existing.chat_id, existing.msg_id)], None)
            if dfid != node.folder_id or (dfid is None and parts[:-1] != dparts[:-1]):
                await drive.place([(node.chat_id, node.msg_id)], dfid)
            if new_name != node.name:
                await drive.rename_file(node.chat_id, node.msg_id, new_name)
    except Exception as exc:
        return Response(str(exc), status_code=409)
    tree.invalidate()
    return Response(status_code=201 if existing is None else 204)


async def _copy(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    return Response("A file lives in one TG Drive folder; move it instead, or use “Save a copy to Drive” in the app.",
                    status_code=403)


async def _lock(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    token = f"opaquelocktoken:{secrets.token_hex(16)}"
    xml = ('<?xml version="1.0" encoding="utf-8"?><D:prop xmlns:D="DAV:"><D:lockdiscovery><D:activelock>'
           '<D:locktype><D:write/></D:locktype><D:lockscope><D:exclusive/></D:lockscope><D:depth>0</D:depth>'
           f'<D:timeout>Second-3600</D:timeout><D:locktoken><D:href>{token}</D:href></D:locktoken>'
           '</D:activelock></D:lockdiscovery></D:prop>')
    return Response(xml, status_code=200, media_type='application/xml; charset="utf-8"',
                    headers={"Lock-Token": f"<{token}>"})


async def _unlock(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    return Response(status_code=204)


async def _proppatch(request: Request, tree: Tree, parts: list[str], base: str) -> Response:
    node = await tree.node(parts)
    if node is None:
        return Response(status_code=404)
    href = base + "/".join(quote(p) for p in parts)
    return _multistatus(f"<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop/>"
                        f"<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>")
