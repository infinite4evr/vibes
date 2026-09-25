"""Accounts: login flows, per-account runtime, desktop hooks and batched message fetching."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Optional

from telethon import TelegramClient, connection, errors
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl import functions, types

from . import config
from .db import Database
from .drive import Drive
from .indexer import Indexer
from .search import SearchEngine
from .semantic import SemanticIndex
from .settings import settings
from .streaming import Streamer
from .thumbs import Thumbs
from .transfers import Transfers

log = logging.getLogger("tgdrive.accounts")


def accounts_dir() -> Path:
    return config.DATA_DIR / "accounts"


def proxy_args() -> dict:
    if not settings.get("proxy_enabled") or not settings.get("proxy_host"):
        return {}
    host, port = settings.get("proxy_host"), int(settings.get("proxy_port") or 1080)
    kind = settings.get("proxy_type")
    if kind == "mtproto":
        return {"connection": connection.ConnectionTcpMTProxyRandomizedIntermediate,
                "proxy": (host, port, settings.get("proxy_secret") or "00000000000000000000000000000000")}
    return {"proxy": {"proxy_type": kind, "addr": host, "port": port, "rdns": True,
                      "username": settings.get("proxy_user") or None,
                      "password": settings.get("proxy_pass") or None}}


def make_client(session) -> TelegramClient:
    api_id, api_hash = config.api_credentials()
    return TelegramClient(
        session, api_id, api_hash,
        flood_sleep_threshold=30,
        device_model="TG Drive Desktop", app_version=config.VERSION,
        system_version=f"{platform.system()} {platform.release()}"[:60],
        request_retries=6, connection_retries=None, retry_delay=2, auto_reconnect=True,
        **proxy_args(),
    )


class AccountError(Exception):
    """A user-facing problem with an account operation."""


class Events:
    """Small in-memory event feed the UI and the desktop shell poll (notifications, progress)."""

    def __init__(self):
        self.items: deque = deque(maxlen=300)
        self.seq = 0
        self.lock = threading.Lock()

    def push(self, kind: str, **data) -> None:
        with self.lock:
            self.seq += 1
            self.items.append({"id": self.seq, "at": int(time.time()), "kind": kind, **data})

    def since(self, after: int) -> list[dict]:
        with self.lock:
            return [e for e in self.items if e["id"] > after]


events = Events()


def open_path(path: str, reveal: bool = False) -> None:
    """Open a file with the default app, or show it in the file manager."""
    p = Path(path)
    if not p.exists():
        raise AccountError("That file isn't on this computer any more.")
    if sys.platform.startswith("linux"):
        if reveal:
            uri = p.resolve().as_uri()
            for cmd in (["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                         "--object-path", "/org/freedesktop/FileManager1", "--method",
                         "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", ""],
                        ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                         "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                         f"array:string:{uri}", "string:"]):
                if shutil.which(cmd[0]):
                    try:
                        if subprocess.run(cmd, timeout=5, capture_output=True).returncode == 0:
                            return
                    except Exception:
                        pass
            target = str(p.parent)
        else:
            target = str(p)
        if not xdg_open(target):
            raise AccountError("No program to open files with was found (xdg-open is missing).")
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if reveal else ["open", str(p)])
    elif sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # type: ignore[attr-defined]


_BUNDLE_VARS = ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QTWEBENGINEPROCESS_PATH", "PYTHONHOME", "PYTHONPATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH", "GIO_MODULE_DIR", "GDK_PIXBUF_MODULE_FILE")
_OWN_VARS = ("PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE", "PYTHONUTF8", "TGDRIVE_PACKAGED", "TGDRIVE_LAUNCHER",
             "QTWEBENGINE_DISABLE_SANDBOX", "QTWEBENGINE_CHROMIUM_FLAGS", "QT_QUICK_BACKEND")


def clean_env() -> dict:
    """Environment for programs started from TG Drive (file manager, player, browser): the caller's
    original environment, without the AppImage's library paths or the app's own Qt/Python settings."""
    env = dict(os.environ)
    packaged = bool(getattr(sys, "frozen", False) or env.get("APPIMAGE") or env.get("TGDRIVE_PACKAGED"))
    for k in _BUNDLE_VARS:
        orig = env.pop(k + "_ORIG", None)
        if orig:
            env[k] = orig
        elif orig is not None or packaged:
            env.pop(k, None)
    for k in _OWN_VARS:
        env.pop(k, None)
    for k in env.get("TGDRIVE_ENV_ADDED", "").split(","):
        if k:
            env.pop(k, None)
    env.pop("TGDRIVE_ENV_ADDED", None)
    for k in [k for k in env if k.endswith("_ORIG")]:
        env.pop(k, None)
    return env


def xdg_open(target: str) -> bool:
    """Open a URL or path with the desktop's default app, from a clean environment."""
    for exe in ("xdg-open", "gio"):
        path = shutil.which(exe)
        if path:
            cmd = [path, target] if exe == "xdg-open" else [path, "open", target]
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True, env=clean_env())
                return True
            except OSError:
                continue
    return False


class MessageFetcher:
    """Coalesces single-message lookups into batched get_messages calls per chat.

    A grid of 100 thumbnails becomes one request instead of 100.
    """

    TTL = 600
    MAX = 5000

    def __init__(self, account: "Account"):
        self.acc = account
        self.cache: "OrderedDict[tuple[int,int], tuple[float, object]]" = OrderedDict()
        self.pending: dict[int, dict[int, list[asyncio.Future]]] = {}
        self.flushers: dict[int, asyncio.Task] = {}

    def forget(self, chat_id: int, msg_id: int) -> None:
        self.cache.pop((chat_id, msg_id), None)

    async def get(self, chat_id: int, msg_id: int, fresh: bool = False):
        key = (chat_id, msg_id)
        hit = self.cache.get(key)
        if hit and not fresh and time.time() - hit[0] < self.TTL:
            self.cache.move_to_end(key)
            return hit[1]
        fut = asyncio.get_running_loop().create_future()
        self.pending.setdefault(chat_id, {}).setdefault(msg_id, []).append(fut)
        if chat_id not in self.flushers:
            self.flushers[chat_id] = asyncio.create_task(self._flush(chat_id))
        return await fut

    async def _flush(self, chat_id: int) -> None:
        await asyncio.sleep(0.04)
        batch = self.pending.pop(chat_id, {})
        self.flushers.pop(chat_id, None)
        ids = list(batch)
        try:
            peer = await self.acc.peer(chat_id)
            for i in range(0, len(ids), 100):
                chunk = ids[i:i + 100]
                msgs = await self.acc.client.get_messages(peer, ids=chunk)
                for mid, msg in zip(chunk, msgs):
                    if not isinstance(msg, types.Message):
                        msg = None
                    self.cache[(chat_id, mid)] = (time.time(), msg)
                    for fut in batch[mid]:
                        if not fut.done():
                            fut.set_result(msg)
            while len(self.cache) > self.MAX:
                self.cache.popitem(last=False)
        except Exception as exc:  # propagate to every waiter
            for futs in batch.values():
                for fut in futs:
                    if not fut.done():
                        fut.set_exception(exc)


class Account:
    def __init__(self, uid: int, path: Path, client: Optional[TelegramClient] = None):
        self.uid = uid
        self.dir = path
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(path / "index.db")
        self.client = client or make_client(str(path / "session"))
        self.me = None
        self.status = "starting"   # starting|online|offline|logged_out
        self.error: Optional[str] = None
        self.fetcher = MessageFetcher(self)
        self.indexer = Indexer(self)
        self.drive = Drive(self)
        self.transfers = Transfers(self)
        self.thumbs = Thumbs(self)
        self.streamer = Streamer(self)
        self.search = SearchEngine(self)
        self.semantic = SemanticIndex(path / "semantic", path / "index.db")
        self.semantic.enabled = bool(settings.get("search_semantic", True))
        self._runner: Optional[asyncio.Task] = None
        self._search_builder: Optional[asyncio.Task] = None
        self._dialogs_loaded = False

    # --------------------------------------------------------------- lifecycle
    def launch(self) -> None:
        self.db.prewarm()
        self.semantic.prewarm()
        self._runner = asyncio.create_task(self._run())
        if not self.db.search_ready and (self._search_builder is None or self._search_builder.done()):
            self._search_builder = asyncio.create_task(self._build_search())
        else:
            self.search.warm_up()
        self.semantic.start()

    async def _build_search(self) -> None:
        """Fill the upgraded search index in the background (keeps the app usable meanwhile)."""
        import sqlite3
        loop = asyncio.get_running_loop()
        conn = sqlite3.connect(str(self.db.path), timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            while True:
                n = await loop.run_in_executor(None, self.db.build_search_batch, conn, 2000)
                if not n:
                    break
                await asyncio.sleep(0.05)
            events.push("search_ready", account=self.uid)
            self.search.vocab.built = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("search index upgrade failed")
        finally:
            conn.close()

    async def _run(self) -> None:
        delay = 5
        while True:
            try:
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    self.status = "logged_out"
                    self.error = "This session was signed out. Remove the account and sign in again."
                    return
                self.me = await self.client.get_me()
                self.db.set_meta("name", " ".join(x for x in (self.me.first_name, self.me.last_name) if x))
                self.db.set_meta("username", self.me.username or "")
                self.db.set_meta("phone", self.me.phone or "")
                self.db.set_meta("premium", int(bool(self.me.premium)))
                self.status, self.error = "online", None
                self.indexer.install_handlers()
                self.indexer.start()
                self.transfers.restore()
                return
            except asyncio.CancelledError:
                raise
            except (errors.AuthKeyUnregisteredError, errors.SessionRevokedError, errors.UserDeactivatedError):
                self.status = "logged_out"
                self.error = "Telegram signed this session out. Remove the account and sign in again."
                return
            except (OSError, ConnectionError, errors.RPCError, asyncio.TimeoutError) as exc:
                self.status, self.error = "offline", f"Can't reach Telegram ({exc}). Retrying in {delay}s."
                log.warning("account %s offline: %s", self.uid, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    async def stop(self) -> None:
        if self._runner:
            self._runner.cancel()
        if self._search_builder:
            self._search_builder.cancel()
        await self.indexer.stop()
        await self.transfers.stop()
        try:
            await asyncio.wait_for(self.drive.flush_now(), 15)
        except Exception:
            pass
        await asyncio.get_running_loop().run_in_executor(None, self.semantic.stop)
        try:
            await self.client.disconnect()
        except Exception:
            pass
        self.db.close()

    async def reconnect(self) -> None:
        """Recreate the Telegram connection (after proxy or API settings change)."""
        await self.indexer.stop()
        await self.transfers.stop()
        try:
            await self.client.disconnect()
        except Exception:
            pass
        self.client = make_client(str(self.dir / "session"))
        self.indexer._handlers = False
        self.status = "starting"
        self._runner = asyncio.create_task(self._run())

    @property
    def premium(self) -> bool:
        return bool(self.me.premium) if self.me else self.db.get_meta("premium") == "1"

    def info(self) -> dict:
        return {
            "id": self.uid,
            "name": self.db.get_meta("name") or str(self.uid),
            "username": self.db.get_meta("username") or None,
            "phone": self.db.get_meta("phone") or None,
            "premium": self.premium,
            "status": self.status,
            "error": self.error,
        }

    def require_online(self) -> None:
        if self.status != "online":
            raise AccountError(self.error or "This account isn't connected to Telegram yet.")

    # ------------------------------------------------------------ desktop hooks
    def notify(self, title: str, body: str = "", path: Optional[str] = None) -> None:
        if settings.get("notifications", True):
            events.push("notify", account=self.uid, title=title, body=body, path=path)

    def notify_new_file(self, rec: dict) -> None:
        events.push("new_file", account=self.uid, chat_id=rec["chat_id"])

    def open_path(self, path: str, reveal: bool = False) -> None:
        open_path(path, reveal)

    # ----------------------------------------------------------------- helpers
    async def peer(self, chat_id: int):
        try:
            return await self.client.get_input_entity(chat_id)
        except ValueError:
            if self._dialogs_loaded:
                raise AccountError("Telegram doesn't recognise this chat any more.")
            await self.client.get_dialogs()  # fills the entity cache
            self._dialogs_loaded = True
            return await self.client.get_input_entity(chat_id)

    async def get_message(self, chat_id: int, msg_id: int, fresh: bool = False):
        """Fetch a live message; drops it from the index if it was deleted."""
        self.require_online()
        msg = await self.fetcher.get(chat_id, msg_id, fresh=fresh)
        if msg is None or msg.media is None:
            self.db.delete_files(chat_id, [msg_id])
            raise AccountError("This file was deleted from Telegram. It has been removed from the index.")
        return msg


class Login:
    def __init__(self, phone: str = ""):
        self.id = secrets.token_hex(8)
        self.phone = phone
        self.client = make_client(StringSession())
        self.phone_code_hash: Optional[str] = None
        self.created = time.time()
        self.qr = None
        self.qr_task: Optional[asyncio.Task] = None
        self.qr_state = "waiting"   # waiting|password|done|expired|error
        self.qr_error: Optional[str] = None
        self.result: Optional[dict] = None
        self.hint = ""


class AccountManager:
    def __init__(self):
        self.accounts: dict[int, Account] = {}
        self.logins: dict[str, Login] = {}
        settings.on_change(self._on_settings)

    def _on_settings(self, changed: set[str]) -> None:
        net = {"proxy_enabled", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass",
               "proxy_secret", "api_id", "api_hash"}
        if changed & net:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            for acc in list(self.accounts.values()):
                loop.create_task(acc.reconnect())
        if "search_semantic" in changed:
            for acc in self.accounts.values():
                acc.semantic.enabled = bool(settings.get("search_semantic"))
                acc.semantic.poke()
        if "index_paused" in changed:
            for acc in self.accounts.values():
                acc.indexer.pause() if settings.get("index_paused") else acc.indexer.resume()
        if changed & {"index_kinds", "index_skip_kinds_of_chat"}:
            for acc in self.accounts.values():
                acc.indexer.poke()

    async def startup(self) -> None:
        d = accounts_dir()
        d.mkdir(parents=True, exist_ok=True)
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and sub.name.isdigit() and (sub / "session.session").exists():
                acc = Account(int(sub.name), sub)
                self.accounts[acc.uid] = acc
                acc.launch()

    async def startup_new(self) -> None:
        """Start accounts that appeared on disk (after importing data)."""
        d = accounts_dir()
        for sub in sorted(d.iterdir()) if d.exists() else []:
            if sub.is_dir() and sub.name.isdigit() and (sub / "session.session").exists() \
                    and int(sub.name) not in self.accounts:
                acc = Account(int(sub.name), sub)
                self.accounts[acc.uid] = acc
                acc.launch()

    async def shutdown(self) -> None:
        for acc in list(self.accounts.values()):
            await acc.stop()
        for login in list(self.logins.values()):
            if login.qr_task:
                login.qr_task.cancel()
            await login.client.disconnect()

    def get(self, uid: int) -> Account:
        acc = self.accounts.get(uid)
        if not acc:
            raise AccountError("Unknown account.")
        return acc

    def list(self) -> list[dict]:
        return [a.info() for a in self.accounts.values()]

    # ------------------------------------------------------------------ login
    def _login(self, login_id: str) -> Login:
        for lid, lg in list(self.logins.items()):  # expire abandoned attempts
            if time.time() - lg.created > 900:
                if lg.qr_task:
                    lg.qr_task.cancel()
                asyncio.create_task(lg.client.disconnect())
                self.logins.pop(lid, None)
        lg = self.logins.get(login_id)
        if not lg:
            raise AccountError("This sign-in attempt expired. Start again.")
        return lg

    def _require_api(self) -> None:
        if not config.api_configured():
            raise AccountError("Add your Telegram API ID and hash first (from my.telegram.org).")

    async def login_start(self, phone: str) -> dict:
        self._require_api()
        phone = phone.strip().replace(" ", "").replace("-", "")
        lg = Login(phone)
        await lg.client.connect()
        try:
            sent = await lg.client.send_code_request(phone)
        except errors.PhoneNumberInvalidError:
            await lg.client.disconnect()
            raise AccountError("Telegram doesn't recognise that phone number. Include the country code, e.g. +91…")
        except errors.ApiIdInvalidError:
            await lg.client.disconnect()
            raise AccountError("Telegram rejected the API ID / hash. Check them at my.telegram.org.")
        except errors.FloodWaitError as exc:
            await lg.client.disconnect()
            raise AccountError(f"Too many sign-in attempts. Telegram asks to wait {exc.seconds // 60 + 1} minutes.")
        lg.phone_code_hash = sent.phone_code_hash
        self.logins[lg.id] = lg
        via = type(sent.type).__name__.replace("SentCodeType", "").lower()
        return {"login_id": lg.id, "sent_via": via}

    async def login_code(self, login_id: str, code: str) -> dict:
        lg = self._login(login_id)
        try:
            await lg.client.sign_in(lg.phone, code.strip(), phone_code_hash=lg.phone_code_hash)
        except errors.SessionPasswordNeededError:
            pwd = await lg.client(functions.account.GetPasswordRequest())
            return {"need_password": True, "hint": pwd.hint or ""}
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
            raise AccountError("That code is wrong. Check the latest code Telegram sent you.")
        except errors.PhoneCodeExpiredError:
            raise AccountError("That code expired. Start again to get a new one.")
        return {"account": await self._finish(lg)}

    async def login_password(self, login_id: str, password: str) -> dict:
        lg = self._login(login_id)
        try:
            await lg.client.sign_in(password=password)
        except errors.PasswordHashInvalidError:
            raise AccountError("That two-step verification password is wrong.")
        if lg.qr_task:
            lg.qr_state = "done"
        return {"account": await self._finish(lg)}

    # QR login: scan with Telegram on your phone (Settings → Devices → Link Desktop Device).
    async def login_qr_start(self) -> dict:
        self._require_api()
        lg = Login()
        await lg.client.connect()
        lg.qr = await lg.client.qr_login()
        self.logins[lg.id] = lg
        lg.qr_task = asyncio.create_task(self._qr_wait(lg))
        return {"login_id": lg.id, **self._qr_payload(lg)}

    def _qr_payload(self, lg: Login) -> dict:
        import segno
        buf = io.BytesIO()
        segno.make(lg.qr.url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#1c2331", light="#ffffff")
        return {"svg": buf.getvalue().decode(), "expires": int(lg.qr.expires.timestamp()), "url": lg.qr.url}

    async def _qr_wait(self, lg: Login) -> None:
        while lg.qr_state == "waiting":
            try:
                await lg.qr.wait(timeout=max(5, int(lg.qr.expires.timestamp() - time.time())))
                lg.result = await self._finish(lg)
                lg.qr_state = "done"
                return
            except asyncio.TimeoutError:
                try:
                    await lg.qr.recreate()
                except Exception as exc:
                    lg.qr_state, lg.qr_error = "error", str(exc)
                    return
            except errors.SessionPasswordNeededError:
                pwd = await lg.client(functions.account.GetPasswordRequest())
                lg.hint = pwd.hint or ""
                lg.qr_state = "password"
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                lg.qr_state, lg.qr_error = "error", str(exc)
                return

    async def login_qr_status(self, login_id: str) -> dict:
        lg = self._login(login_id)
        out = {"state": lg.qr_state, "error": lg.qr_error, "hint": lg.hint}
        if lg.qr_state == "waiting":
            out.update(self._qr_payload(lg))
        if lg.qr_state == "done":
            out["account"] = lg.result
        return out

    async def _finish(self, lg: Login) -> dict:
        me = await lg.client.get_me()
        string = lg.client.session.save()
        await lg.client.disconnect()
        self.logins.pop(lg.id, None)

        path = accounts_dir() / str(me.id)
        if me.id in self.accounts:  # signing in again to an existing account
            await self.accounts.pop(me.id).stop()
        path.mkdir(parents=True, exist_ok=True)
        session_file = path / "session.session"
        if session_file.exists():
            session_file.unlink()
        src = StringSession(string)
        dst = SQLiteSession(str(path / "session"))
        dst.set_dc(src.dc_id, src.server_address, src.port)
        dst.auth_key = src.auth_key
        dst.save()
        dst.close()
        os.chmod(session_file, 0o600)

        acc = Account(me.id, path)
        self.accounts[me.id] = acc
        acc.launch()
        await asyncio.sleep(0)  # let it begin connecting
        return acc.info()

    async def remove(self, uid: int, keep_data: bool = False) -> None:
        acc = self.get(uid)
        if acc.status == "online":
            try:
                await acc.client.log_out()
            except Exception as exc:
                log.warning("log_out failed: %s", exc)
        await acc.stop()
        self.accounts.pop(uid, None)
        if keep_data:
            (acc.dir / "session.session").unlink(missing_ok=True)
        else:
            shutil.rmtree(acc.dir, ignore_errors=True)
