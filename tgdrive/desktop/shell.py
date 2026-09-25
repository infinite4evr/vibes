"""The Qt side of the desktop app: window, bridge, tray, notifications, downloads, single instance."""
import json
import re
import logging
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QEvent, QFile, QIODevice, QObject, QSettings, Qt, QTimer, QUrl, pyqtSlot
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                   QWebEngineSettings)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QSplashScreen, QSystemTrayIcon

from .app import APP_ID, ROOT, ensure_desktop_entry, notify_system, set_autostart

log = logging.getLogger("tgdrive.desktop")
SOCKET = f"tgdrive-{os.getuid()}" if hasattr(os, "getuid") else "tgdrive"


def load_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        p = ROOT / "packaging" / "icons" / f"tgdrive-{size}.png"
        if p.exists():
            icon.addFile(str(p))
    svg = ROOT / "web" / "icon.svg"
    if icon.isNull() and svg.exists():
        icon = QIcon(str(svg))
    return icon


def icon_path() -> str:
    p = ROOT / "packaging" / "icons" / "tgdrive-256.png"
    return str(p if p.exists() else ROOT / "web" / "icon.svg")


class Page(QWebEnginePage):
    """Keeps TG Drive inside the window; everything else opens in the system browser / Telegram app."""

    def __init__(self, profile, parent, local_prefixes):
        super().__init__(profile, parent)
        self.local = local_prefixes

    def is_local(self, url: QUrl) -> bool:
        u = url.toString()
        return url.scheme() in ("data", "blob", "about", "qrc") or any(u.startswith(p) for p in self.local)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if self.is_local(url) or not is_main_frame:
            return True
        open_external(url)
        return False

    def createWindow(self, _type):
        return ExternalPage(self.profile(), self)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log.warning("page: %s (%s:%s)", message, source, line)


EXTERNAL_SCHEMES = {"http", "https", "tg", "mailto"}


def open_external(url: QUrl) -> None:
    """Hand a link to the desktop (browser / Telegram app). Only web, tg:// and mail links:
    the page never gets to open local files or run programs this way."""
    if url.scheme().lower() not in EXTERNAL_SCHEMES:
        log.warning("refused to open %s", url.toString()[:200])
        return
    from tgdrive.accounts import xdg_open
    if not xdg_open(url.toString()):
        QDesktopServices.openUrl(url)


class ExternalPage(QWebEnginePage):
    """Target for window.open / target=_blank: hands the URL to the desktop, then disappears."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        parent = self.parent()
        if isinstance(parent, Page) and parent.is_local(url):
            parent.setUrl(url)
        else:
            open_external(url)
        self.deleteLater()
        return False


class Bridge(QObject):
    """Native services for the web UI (window.qt → QWebChannel object 'tgd')."""

    def __init__(self, shell):
        super().__init__()
        self.shell = shell

    @pyqtSlot(result=list)
    def pickFiles(self):
        paths, _ = QFileDialog.getOpenFileNames(self.shell.win, "Upload files to TG Drive", self.shell.last_dir())
        if paths:
            self.shell.remember_dir(str(Path(paths[0]).parent))
        return paths

    @pyqtSlot(result=str)
    def pickFolder(self):
        d = QFileDialog.getExistingDirectory(self.shell.win, "Choose a folder", self.shell.last_dir())
        if d:
            self.shell.remember_dir(d)
        return d or ""

    @pyqtSlot(str)
    def openExternal(self, url):
        open_external(QUrl(url))

    @pyqtSlot(str, str, result=bool)
    def playNative(self, url, title):
        return self.shell.play_native(url, title)

    @pyqtSlot(str)
    def setTheme(self, theme):
        self.shell.theme = theme

    @pyqtSlot(str, str)
    def notify(self, title, body):
        self.shell.notify(title, body, force=True)


class MainWindow(QMainWindow):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setWindowTitle("TG Drive")
        self.setWindowIcon(shell.icon)
        self.resize(1360, 860)
        self.setMinimumSize(420, 480)

    def closeEvent(self, e):
        if self.shell.quitting:
            e.accept()
            return
        self.shell.save_geometry()
        if self.shell.close_to_tray():
            e.ignore()
            self.hide()
            self.shell.tray_hint()
            return
        if not self.shell.confirm_quit():
            e.ignore()
            return
        e.accept()
        self.shell.quit()


class Shell:
    def __init__(self, app: QApplication, args, log_path):
        self.app = app
        self.args = args
        self.log_path = log_path
        self.quitting = False
        self.theme = "system"
        self.players = []
        self.icon = load_icon()
        self.qs = QSettings("tgdrive", "desktop")
        self.token = secrets.token_urlsafe(24)
        self.server = self.thread = None
        self.port = self.media = 0
        self.last_event = 0
        self.tray = None
        self.win = None

    # ------------------------------------------------------------- startup
    def start(self) -> int:
        app = self.app
        app.setApplicationName("TG Drive")
        app.setApplicationDisplayName("TG Drive")
        app.setOrganizationName("tgdrive")
        app.setDesktopFileName(APP_ID)
        app.setWindowIcon(self.icon)
        app.setQuitOnLastWindowClosed(False)
        if self.already_running():
            return 0
        splash = None
        if not self.args.minimized and not self.args.screenshot:
            pm = QPixmap(str(ROOT / "packaging" / "icons" / "tgdrive-256.png"))
            if not pm.isNull():
                splash = QSplashScreen(pm)
                splash.showMessage("Starting TG Drive…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
                splash.show()
                app.processEvents()
        ensure_desktop_entry()
        if not self.start_server():
            if splash:
                splash.close()
            QMessageBox.critical(None, "TG Drive couldn't start",
                                 f"The TG Drive service didn't start. Details are in the log:\n{self.log_path}")
            return 1
        self.build_window()
        self.build_tray()
        from tgdrive.settings import settings
        settings.on_change(self.on_settings)
        if splash:
            splash.finish(self.win)
        start_hidden = (self.args.minimized or settings.get("start_minimized")) and self.tray is not None
        if not start_hidden:
            self.show()
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_events)
        self.timer.start(2000)
        app.aboutToQuit.connect(self.shutdown)
        if self.args.screenshot:
            QTimer.singleShot(9000, self.take_screenshot)
        return app.exec()

    def already_running(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(SOCKET)
        if sock.waitForConnected(500):
            sock.write(b"show\n")
            sock.flush()
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            print("TG Drive is already running; showing its window.")
            return True
        QLocalServer.removeServer(SOCKET)
        self.listener = QLocalServer()
        self.listener.listen(SOCKET)
        self.listener.newConnection.connect(self.on_second_instance)
        return False

    def on_second_instance(self):
        conn = self.listener.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(300)
            conn.readAll()
            conn.close()
        self.show()

    def start_server(self) -> bool:
        import run
        try:
            self.server, self.thread, self.port, self.media = run.serve_in_thread(
                port=self.args.port, token=self.token, desktop=True)
        except OSError as exc:
            log.error("server failed: %s", exc)
            return False
        deadline = time.time() + 300
        while time.time() < deadline:
            if self.server.started:
                return True
            if not self.thread.is_alive():
                return False
            self.app.processEvents()
            time.sleep(0.05)
        return False

    def build_window(self):
        self.win = MainWindow(self)
        data = Path(os.environ.get("TGDRIVE_DATA") or "")
        from tgdrive import config
        profile = QWebEngineProfile("tgdrive", self.app)  # outlives the window and its pages
        store = config.DATA_DIR / "webengine"
        profile.setPersistentStoragePath(str(store / "storage"))
        profile.setCachePath(str(store / "cache"))
        profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        profile.downloadRequested.connect(self.on_download)
        s = profile.settings()
        for attr in ("PdfViewerEnabled", "PluginsEnabled", "LocalStorageEnabled", "JavascriptCanAccessClipboard",
                     "JavascriptCanPaste", "FullScreenSupportEnabled", "ScrollAnimatorEnabled"):
            if hasattr(QWebEngineSettings.WebAttribute, attr):
                s.setAttribute(getattr(QWebEngineSettings.WebAttribute, attr), True)
        if hasattr(QWebEngineSettings.WebAttribute, "PlaybackRequiresUserGesture"):
            s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        local = [f"http://127.0.0.1:{self.port}/", f"http://127.0.0.1:{self.media}/"]
        page = Page(profile, self.win, local)
        self.page = page
        if hasattr(page, "permissionRequested"):
            page.permissionRequested.connect(lambda perm: perm.grant())
        if hasattr(page, "featurePermissionRequested"):
            page.featurePermissionRequested.connect(
                lambda origin, feature: page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.PermissionGrantedByUser))
        page.fullScreenRequested.connect(self.on_fullscreen)
        # QWebChannel bridge (qwebchannel.js injected so no qrc access is needed from the page).
        self.bridge = Bridge(self)
        channel = QWebChannel(page)
        channel.registerObject("tgd", self.bridge)
        page.setWebChannel(channel)
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.OpenModeFlag.ReadOnly):
            js = bytes(f.readAll()).decode()
            f.close()
            script = QWebEngineScript()
            script.setName("qwebchannel")
            script.setSourceCode(js)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(False)
            page.scripts().insert(script)
        view = QWebEngineView(self.win)
        view.setPage(page)
        view.setZoomFactor(float(self.qs.value("zoom", 1.0)))
        self.view = view
        self.win.setCentralWidget(view)
        geo = self.qs.value("geometry")
        if geo is not None:
            self.win.restoreGeometry(geo)
        view.setUrl(QUrl(f"http://127.0.0.1:{self.port}/?t={self.token}"))
        page.loadFinished.connect(lambda ok: ok or log.warning("page failed to load"))
        self.shortcuts()
        del data

    def shortcuts(self):
        def add(keys, fn):
            for k in keys:
                act = QAction(self.win)
                act.setShortcut(QKeySequence(k))
                act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
                act.triggered.connect(fn)
                self.win.addAction(act)
        add(["Ctrl+=", "Ctrl++"], lambda: self.zoom(0.1))
        add(["Ctrl+-"], lambda: self.zoom(-0.1))
        add(["Ctrl+0"], lambda: self.zoom(None))
        add(["F11"], self.toggle_fullscreen)
        add(["Ctrl+Q"], self.quit_confirmed)
        add(["Ctrl+Shift+R"], lambda: self.view.reload())

    def zoom(self, d):
        z = 1.0 if d is None else max(0.5, min(2.5, self.view.zoomFactor() + d))
        self.view.setZoomFactor(z)
        self.qs.setValue("zoom", z)

    def toggle_fullscreen(self):
        self.win.showNormal() if self.win.isFullScreen() else self.win.showFullScreen()

    def on_fullscreen(self, req):
        req.accept()
        self.win.showFullScreen() if req.toggleOn() else self.win.showNormal()

    # ---------------------------------------------------------------- tray
    def build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("no system tray: closing the window quits TG Drive")
            return
        tray = QSystemTrayIcon(self.icon)
        tray.setToolTip("TG Drive")
        menu = QMenu()
        show = menu.addAction("Show TG Drive")
        show.triggered.connect(self.show)
        self.pause_act = menu.addAction("Pause indexing")
        self.pause_act.triggered.connect(self.toggle_indexing)
        menu.addAction("Open downloads folder").triggered.connect(self.open_downloads)
        menu.addSeparator()
        menu.addAction("Quit TG Drive").triggered.connect(self.quit_confirmed)
        menu.aboutToShow.connect(self.refresh_tray_menu)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.toggle_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        self.tray = tray
        self.tray_menu = menu

    def refresh_tray_menu(self):
        from tgdrive.settings import settings
        self.pause_act.setText("Resume indexing" if settings.get("index_paused") else "Pause indexing")

    def api(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-TGDrive": "1", "X-TGDrive-Token": self.token,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"null")

    def toggle_indexing(self):
        from tgdrive.settings import settings
        try:
            self.api("PATCH", "/api/settings", {"index_paused": not settings.get("index_paused")})
        except Exception as exc:
            log.warning("tray action failed: %s", exc)

    def open_downloads(self):
        from tgdrive import config
        from tgdrive.settings import settings
        d = Path(settings.get("download_dir") or config.default_download_dir())
        d.mkdir(parents=True, exist_ok=True)
        from tgdrive.accounts import xdg_open
        if not xdg_open(str(d)):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def toggle_window(self):
        if self.win.isVisible() and self.win.isActiveWindow():
            self.win.hide()
        else:
            self.show()

    def tray_hint(self):
        if self.tray and not self.qs.value("tray_hint_shown", False, type=bool):
            self.tray.showMessage("TG Drive is still running",
                                  "Indexing and transfers continue. Quit from the tray icon.", self.icon, 6000)
            self.qs.setValue("tray_hint_shown", True)

    def close_to_tray(self) -> bool:
        from tgdrive.settings import settings
        return bool(self.tray and settings.get("close_to_tray", True))

    # --------------------------------------------------------------- misc
    def show(self):
        self.win.show()
        if self.win.isMinimized():
            self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def last_dir(self) -> str:
        return str(self.qs.value("last_dir", str(Path.home())))

    def remember_dir(self, d: str):
        self.qs.setValue("last_dir", d)

    def save_geometry(self):
        if self.win:
            self.qs.setValue("geometry", self.win.saveGeometry())

    def play_native(self, url: str, title: str) -> bool:
        try:
            from .player import PlayerWindow
        except Exception as exc:
            log.warning("native player unavailable: %s", exc)
            return False
        from tgdrive import config
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        u = urlsplit(url)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or \
                u.port not in (self.port, self.media) or "/stream/" not in u.path:
            log.warning("refused to play %s", url[:200])
            return False
        q = [(k, v) for k, v in parse_qsl(u.query) if k != "t"] + [("t", config.MEDIA_TOKEN)]
        start_ms, on_progress = 0, None
        m = re.match(r"^/api/a/(\d+)/stream/(-?\d+)/(\d+)", u.path)
        if m:
            pb_path = f"/api/a/{m.group(1)}/playback/{m.group(2)}/{m.group(3)}"
            try:
                pb = self.api("GET", pb_path) or {}
                if pb.get("pos") and not pb.get("done"):
                    start_ms = int(float(pb["pos"]) * 1000)
            except Exception as exc:
                log.debug("no playback position: %s", exc)

            def report(pos_ms: int, dur_ms: int, done: bool = False, path=pb_path):
                if dur_ms < 30_000 and not done:
                    return
                body = {"pos": pos_ms / 1000, "dur": dur_ms / 1000 if dur_ms else None}
                if done:
                    body["done"] = True
                try:
                    self.api("PUT", path, body)
                except Exception as exc:
                    log.debug("could not save playback position: %s", exc)
            on_progress = report
        w = PlayerWindow(urlunsplit(u._replace(query=urlencode(q))), title, self.icon, start_ms=start_ms,
                         on_progress=on_progress)
        w.show()
        self.players = [p for p in self.players if p.isVisible()] + [w]
        return True

    def notify(self, title: str, body: str, force: bool = False):
        from tgdrive.settings import settings
        if not settings.get("notifications", True):
            return
        if not force and self.win.isVisible() and self.win.isActiveWindow():
            return  # the window shows its own message
        if not notify_system(title, body, icon_path()) and self.tray:
            self.tray.showMessage(title, body, self.icon, 5000)

    def poll_events(self):
        from tgdrive.accounts import events
        for ev in events.since(self.last_event):
            self.last_event = ev["id"]
            if ev["kind"] == "notify":
                self.notify(ev["title"], ev.get("body", ""))

    def on_settings(self, changed):
        from tgdrive.settings import settings
        if "autostart" in changed:
            try:
                set_autostart(bool(settings.get("autostart")))
            except OSError as exc:
                log.warning("autostart: %s", exc)

    def on_download(self, req: QWebEngineDownloadRequest):
        """Exports and saved files from inside the page (CSV, manifest, playlists)."""
        from tgdrive import config
        from tgdrive.settings import settings
        d = Path(settings.get("download_dir") or config.default_download_dir())
        d.mkdir(parents=True, exist_ok=True)
        name = req.downloadFileName() or "download"
        stem, dot, ext = name.rpartition(".")
        n, candidate = 1, name
        while (d / candidate).exists():
            candidate = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
            n += 1
        req.setDownloadDirectory(str(d))
        req.setDownloadFileName(candidate)
        req.isFinishedChanged.connect(lambda: req.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
                                      and self.notify("Saved", f"{candidate} is in {d}", force=True))
        req.accept()

    def active_transfers(self) -> int:
        try:
            from tgdrive import api
            return sum(a.transfers.summary()["active"] for a in api.manager.accounts.values())
        except Exception:
            return 0

    def confirm_quit(self) -> bool:
        n = self.active_transfers()
        if not n:
            return True
        r = QMessageBox.question(self.win, "Quit TG Drive?",
                                 f"{n} transfer{'s are' if n != 1 else ' is'} still running. They continue where "
                                 f"they stopped the next time you open TG Drive.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def quit_confirmed(self):
        if self.confirm_quit():
            self.quit()

    def quit(self):
        self.quitting = True
        self.save_geometry()
        for p in self.players:
            p.close()
        self.app.quit()

    def shutdown(self):
        for w in getattr(self, "players", []):
            w.close()   # saves playback positions while the server still runs
        if self.server:
            self.server.should_exit = True
            self.thread.join(40)
        if self.tray:
            self.tray.hide()
        # Web pages must go before their profile, or Chromium complains on exit.
        view = getattr(self, "view", None)
        if view is not None:
            view.setPage(QWebEnginePage(view))
        if getattr(self, "page", None) is not None:
            self.page.deleteLater()
            self.page = None

    def take_screenshot(self):
        path = self.args.screenshot
        self.view.grab().save(path)
        log.info("screenshot saved to %s", path)

        def done(result):
            log.info("page check: %s", result)
            self.quitting = True
            self.app.quit()
        self.page.runJavaScript("JSON.stringify({desktop: !!(window.tgdrive && window.tgdrive.S.desktop), "
                                "channel: !!window.QWebChannel, view: window.tgdrive && window.tgdrive.S.view.type})", 0, done)


def run(app: QApplication, args, log_path) -> None:
    shell = Shell(app, args, log_path)
    code = shell.start()
    # run pending deleteLater() calls (the page) before Python tears everything down
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    sys.exit(code)
