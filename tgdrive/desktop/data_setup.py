"""First-run native data-folder selection, before any database is opened."""
def choose(default):
    import os
    import sys
    try:
        from PyQt6 import QtWebEngineWidgets  # load before QApplication
        from PyQt6.QtWidgets import QApplication,QMessageBox,QFileDialog
        # Keep the application alive; main() reuses this instance.
        global app
        app=QApplication.instance() or QApplication(['tgdrive'])
        box=QMessageBox();box.setWindowTitle('TG Drive — data folder')
        box.setText('Choose where TG Drive keeps your settings, API credentials, Telegram sessions and files.')
        box.setInformativeText(f'Default: {default}\nAn existing TG Drive folder restores its accounts and settings. Keep this folder private.')
        default_button=box.addButton('Use default folder',QMessageBox.ButtonRole.AcceptRole)
        other=box.addButton('Choose folder…',QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel);box.exec()
        if box.clickedButton()==default_button:return default
        if box.clickedButton()==other:
            from tgdrive.data_location import validate, existing
            while True:
                picked=QFileDialog.getExistingDirectory(None,'Choose TG Drive data folder',str(default.parent))
                if not picked:return None
                try:
                    folder=validate(picked)
                    if any(folder.iterdir()) and not existing(folder):
                        raise ValueError('Choose an empty folder or an existing TG Drive data folder.')
                    return folder
                except (OSError,ValueError) as e:
                    QMessageBox.warning(None,'Data folder',str(e))
        return None
    except ImportError:
        if sys.stdin.isatty():
            return input(f'TG Drive data folder [{default}]: ').strip() or default
        # A headless launch can explicitly select with --data; keep the platform default otherwise.
        return default
