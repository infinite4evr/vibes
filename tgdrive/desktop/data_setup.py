"""Data-folder selection at startup, before any database is opened: the first-run choice, and
recovery when the selected folder can't be used (a failed move, an unplugged drive)."""
import logging
import os
import sys

log = logging.getLogger("tgdrive.desktop")


def _qt_env():
    """Qt's platform/sandbox defaults, only when a dialog is about to be shown (app.py records which
    of them TG Drive added, so programs it starts later don't inherit them)."""
    from .app import sandbox_usable
    if not sandbox_usable():
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb" if os.environ.get("WAYLAND_DISPLAY") else "xcb")


def _qt():
    _qt_env()
    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must load before QApplication exists)
    from PyQt6.QtWidgets import QApplication
    # Keep the application alive; main() reuses this instance.
    global app
    app = QApplication.instance() or QApplication(['tgdrive'])
    return app


def notify(title, text):
    log.warning("%s: %s", title, text)
    try:
        _qt()
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(None, title, text)
    except ImportError:
        print(f"{title}: {text}", file=sys.stderr)


def choose(default, message=None):
    try:
        _qt()
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        box = QMessageBox()
        box.setWindowTitle('TG Drive — data folder')
        box.setText(message or 'Choose where TG Drive keeps your settings, API credentials, Telegram sessions and files.')
        box.setInformativeText(f'Default: {default}\nAn existing TG Drive folder restores its accounts and settings. Keep this folder private.')
        default_button = box.addButton('Use default folder', QMessageBox.ButtonRole.AcceptRole)
        other = box.addButton('Choose folder…', QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() == default_button:
            return default
        if box.clickedButton() == other:
            from tgdrive.data_location import validate, existing
            while True:
                picked = QFileDialog.getExistingDirectory(None, 'Choose TG Drive data folder', str(default.parent))
                if not picked:
                    return None
                try:
                    folder = validate(picked)
                    if any(folder.iterdir()) and not existing(folder):
                        raise ValueError('Choose an empty folder or an existing TG Drive data folder.')
                    return folder
                except (OSError, ValueError) as e:
                    QMessageBox.warning(None, 'Data folder', str(e))
        return None
    except ImportError:
        if message:
            print(message, file=sys.stderr)
        if sys.stdin.isatty():
            return input(f'TG Drive data folder [{default}]: ').strip() or default
        if message:
            return None   # never switch folders silently: start again with --data DIR
        # A headless launch can explicitly select with --data; keep the platform default otherwise.
        return default


def open_data_folder(legacy):
    """The data folder this launch uses (also exported as TGDRIVE_DATA for the service)."""
    from tgdrive.data_location import DataInUse, activate, default_dir, rebase_owned_paths, use
    try:
        location = activate(choose, legacy=legacy)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as exc:
        log.warning("data folder could not be opened", exc_info=True)
        try:
            # A failed move has been cancelled by now: the current folder still works.
            location = activate(None, legacy=legacy)
            notify('TG Drive — data folder', f'TG Drive could not move its data: {exc}\n\n'
                                             f'It keeps using {location}. Your data there is unchanged.')
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as again:
            problem = again
            while True:
                picked = choose(default_dir(), message=f'TG Drive can’t open its data folder.\n\n{problem}')
                if picked is None:
                    raise SystemExit(1)
                try:
                    location = use(picked)
                    break
                except (OSError, ValueError) as e:
                    problem = e
    os.environ["TGDRIVE_DATA"] = str(location)
    try:
        rebase_owned_paths(location)
    except DataInUse:
        pass   # the running TG Drive opened (and repaired) this folder already; this launch hands over to it
    return location
