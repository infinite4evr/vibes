"""Native media player window (Qt Multimedia with its FFmpeg backend).

Plays what the embedded web view can't decode (H.264, H.265, AAC, AC-3, MKV …),
streaming from TG Drive's local stream URL, so seeking works without
downloading the whole file.
"""
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QSlider, QStyle,
                             QToolButton, QVBoxLayout, QWidget)


def fmt(ms: int) -> str:
    s = max(0, int(ms // 1000))
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ClickVideo(QVideoWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_fullscreen()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.toggle_play()


class PlayerWindow(QMainWindow):
    def __init__(self, url: str, title: str, icon: QIcon, start_ms: int = 0, on_progress=None):
        super().__init__()
        self.start_ms = start_ms
        self.on_progress = on_progress
        self._resumed = False
        self.setWindowTitle(f"{title} — TG Drive")
        self.setWindowIcon(icon)
        self.resize(1100, 680)
        self.setStyleSheet("""
            QMainWindow, QWidget#bar { background: #0e1117; color: #e8ecf2; }
            QLabel { color: #c5ccd6; font-size: 13px; }
            QPushButton, QToolButton { background: transparent; color: #e8ecf2; border: 0; padding: 6px; border-radius: 6px; }
            QPushButton:hover, QToolButton:hover { background: #262c36; }
            QSlider::groove:horizontal { height: 5px; background: #333a46; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #5aa7e8; border-radius: 2px; }
            QSlider::handle:horizontal { background: #fff; width: 13px; margin: -5px 0; border-radius: 6px; }
        """)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = ClickVideo(self)
        self.video.setStyleSheet("background: #000;")
        self.player.setVideoOutput(self.video)

        self.status = QLabel("Connecting…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style = self.style()
        self.play_btn = QPushButton()
        self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.play_btn.clicked.connect(self.toggle_play)
        back = QPushButton()
        back.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
        back.setToolTip("Back 10 s (←)")
        back.clicked.connect(lambda: self.skip(-10_000))
        fwd = QPushButton()
        fwd.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward))
        fwd.setToolTip("Forward 10 s (→)")
        fwd.clicked.connect(lambda: self.skip(10_000))
        self.pos = QSlider(Qt.Orientation.Horizontal)
        self.pos.setRange(0, 0)
        self.pos.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00 / 0:00")
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(100)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.audio.setVolume(0.8)
        speed = QToolButton()
        speed.setText("1×")
        speed.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(speed)
        for r in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
            act = QAction(f"{r:g}×", menu)
            act.triggered.connect(lambda _=False, r=r: (self.player.setPlaybackRate(r), speed.setText(f"{r:g}×")))
            menu.addAction(act)
        speed.setMenu(menu)
        full = QPushButton("⛶")
        full.setToolTip("Full screen (F)")
        full.clicked.connect(self.toggle_fullscreen)

        bar = QWidget()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 8)
        for w in (back, self.play_btn, fwd):
            row.addWidget(w)
        row.addWidget(self.pos, 1)
        row.addWidget(self.time)
        row.addWidget(QLabel("🔊"))
        row.addWidget(self.vol)
        row.addWidget(speed)
        row.addWidget(full)
        self.bar = bar

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.video, 1)
        col.addWidget(self.status)
        col.addWidget(bar)
        self.setCentralWidget(central)

        self.player.durationChanged.connect(lambda d: (self.pos.setRange(0, int(d)), self._time()))
        self.player.positionChanged.connect(self._on_pos)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.hasVideoChanged.connect(lambda has: self.video.setVisible(has) or self.resize(self.width(), 680 if has else 160))

        for key, fn in ((Qt.Key.Key_Space, self.toggle_play), (Qt.Key.Key_F, self.toggle_fullscreen),
                        (Qt.Key.Key_Left, lambda: self.skip(-10_000)), (Qt.Key.Key_Right, lambda: self.skip(10_000)),
                        (Qt.Key.Key_Escape, self._esc), (Qt.Key.Key_Home, lambda: self.player.setPosition(0))):
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(fn)
            self.addAction(act)

        self.save_timer = QTimer(self)
        self.save_timer.setInterval(10_000)
        self.save_timer.timeout.connect(self._report)
        self.save_timer.start()

        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(2500)
        self.hide_timer.timeout.connect(lambda: self.isFullScreen() and self.bar.hide())
        self.setMouseTracking(True)
        self.player.setSource(QUrl(url))
        self.player.play()

    def _esc(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        else:
            self.close()

    def _time(self):
        self.time.setText(f"{fmt(self.player.position())} / {fmt(self.player.duration())}")

    def _on_pos(self, p):
        if not self.pos.isSliderDown():
            self.pos.setValue(int(p))
        self._time()

    def _on_state(self, st):
        icon = QStyle.StandardPixmap.SP_MediaPause if st == QMediaPlayer.PlaybackState.PlayingState \
            else QStyle.StandardPixmap.SP_MediaPlay
        self.play_btn.setIcon(self.style().standardIcon(icon))

    def _report(self, done: bool = False):
        if self.on_progress and (done or self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
            self.on_progress(int(self.player.position()), int(self.player.duration()), done)

    def _on_status(self, st):
        S = QMediaPlayer.MediaStatus
        if st in (S.LoadedMedia, S.BufferedMedia) and not self._resumed:
            self._resumed = True
            if self.start_ms > 5000 and self.player.isSeekable() and \
                    (not self.player.duration() or self.start_ms < self.player.duration() - 5000):
                self.player.setPosition(self.start_ms)
                self.status.setText(f"Continuing from {fmt(self.start_ms)}  ·  press Home to start over")
                self.status.setVisible(True)
                QTimer.singleShot(5000, lambda: self.status.setVisible(False))
                return
        if st == S.EndOfMedia:
            self._report(done=True)
        text = {S.LoadingMedia: "Connecting to Telegram…", S.BufferingMedia: "Buffering…", S.StalledMedia: "Waiting for data…"}.get(st)
        self.status.setText(text or "")
        self.status.setVisible(bool(text))

    def _on_error(self, err, msg):
        self.status.setText(f"Can't play this file: {msg or err}")
        self.status.setVisible(True)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def skip(self, ms):
        self.player.setPosition(max(0, self.player.position() + ms))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.bar.show()
            self.hide_timer.stop()
        else:
            self.showFullScreen()
            self.hide_timer.start()

    def mouseMoveEvent(self, e):
        self.bar.show()
        if self.isFullScreen():
            self.hide_timer.start()

    def closeEvent(self, e):
        if self.on_progress and self.player.duration() and \
                self.player.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia:
            self.on_progress(int(self.player.position()), int(self.player.duration()), False)
        self.save_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(e)
