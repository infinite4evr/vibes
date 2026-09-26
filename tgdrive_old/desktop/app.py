"""TG Drive desktop app: a native window around the local TG Drive server.

    tgdrive                     open the app (or focus the running one)
    tgdrive --minimized         start in the tray
    tgdrive --browser           open in your web browser instead of a window
    tgdrive --data DIR          use another data folder
    tgdrive --port N            preferred local port (default 8765; any free port if taken)
    tgdrive --install-desktop-entry / --uninstall-desktop-entry
"""
import argparse
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP_ID = "tgdrive"
log = logging.getLogger("tgdrive.desktop")


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="tgdrive", description="TG Drive — your Telegram files as a drive.")
    p.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    p.add_argument("--browser", action="store_true", help="open in the web browser instead of a window")
    p.add_argument("--data", help="data folder (default ~/.local/share/tgdrive)")
    p.add_argument("--port", type=int, default=int(os.environ.get("TGDRIVE_PORT", "8765")))
    p.add_argument("--no-gpu", action="store_true", help="software rendering (for graphics driver problems)")
    p.add_argument("--install-desktop-entry", action="store_true")
    p.add_argument("--uninstall-desktop-entry", action="store_true")
    p.add_argument("--send", nargs="+", metavar="PATH", help="upload files or folders (file manager menus use this)")
    p.add_argument("--open", choices=["search", "upload", "new-window"], help="open TG Drive at a task")
    p.add_argument("--screenshot", help=argparse.SUPPRESS)
    p.add_argument("--version", action="store_true")
    p.add_argument("paths", nargs="*", help=argparse.SUPPRESS)  # files dropped on the app icon: upload them
    return p.parse_args(argv)


# ------------------------------------------------------------- desktop entry
def _integration():
    sys.path.insert(0, str(ROOT))
    from tgdrive import integration
    return integration


def install_desktop_entry(quiet: bool = False) -> None:
    ig = _integration()
    entry = ig.install_menu()
    added = ig.install_file_manager_actions()
    if not quiet:
        print(f"Installed {entry}")
        if added:
            print("Added “Send to TG Drive” to: " + ", ".join(added))


def uninstall_desktop_entry() -> None:
    ig = _integration()
    ig.uninstall_menu()
    ig.uninstall_file_manager_actions()
    print("Removed TG Drive from the applications menu and file managers.")


def ensure_desktop_entry() -> None:
    """Running as an AppImage: add TG Drive to the applications menu (and keep the path current)."""
    if not os.environ.get("APPIMAGE"):
        return
    f = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications" / f"{APP_ID}.desktop"
    try:
        if not f.exists() or os.environ["APPIMAGE"] not in f.read_text():
            install_desktop_entry(quiet=True)
    except OSError as exc:
        log.warning("could not install desktop entry: %s", exc)


def set_autostart(on: bool) -> None:
    _integration().set_autostart(on)


# ----------------------------------------------------------------- sandbox
def sandbox_usable() -> bool:
    """Can Chromium's renderer sandbox start here? It needs unprivileged user namespaces, which
    some distros switch off (Debian sysctl, Ubuntu 24.04 AppArmor rule) and it refuses to run as root."""
    if os.environ.get("TGDRIVE_NO_SANDBOX"):
        return False
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return False

    def read(path: str):
        try:
            return Path(path).read_text().strip()
        except OSError:
            return None

    if read("/proc/sys/kernel/unprivileged_userns_clone") == "0" or read("/proc/sys/user/max_user_namespaces") == "0":
        return False
    if read("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") == "1":
        return False
    exe = shutil.which("unshare")
    if exe:
        try:
            return subprocess.run([exe, "-Ur", "true"], capture_output=True, timeout=3).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return True


# --------------------------------------------------------------- fallbacks
def open_in_browser(url: str, data_dir: Path) -> None:
    for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge",
              "vivaldi"):
        exe = shutil.which(b)
        if exe:
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={data_dir / 'browser-profile'}", f"--class={APP_ID}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    webbrowser.open(url)


def notify_system(title: str, body: str, icon: str) -> bool:
    exe = shutil.which("notify-send")
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "-a", "TG Drive", "-i", icon, title, body], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# -------------------------------------------------------------------- main
def main(argv=None) -> None:
    args = parse_args(argv)
    from urllib.parse import unquote
    dropped = [unquote(x[7:]) if x.startswith("file://") else x for x in args.paths if x and not x.startswith("-")]
    dropped = [x for x in dropped if Path(x).exists()]
    if dropped:
        args.send = (args.send or []) + dropped
    if args.data:
        os.environ["TGDRIVE_DATA"] = str(Path(args.data).expanduser())
    if args.send:
        args.send = [str(Path(p).expanduser().resolve()) for p in args.send if p and not p.startswith("-")]
    if args.install_desktop_entry:
        install_desktop_entry()
        return
    if args.uninstall_desktop_entry:
        uninstall_desktop_entry()
        return

    from tgdrive import config, maintenance
    if args.version:
        print(f"TG Drive {config.VERSION}")
        return
    log_path = maintenance.setup_logging()
    log.info("TG Drive %s starting (data %s)", config.VERSION, config.DATA_DIR)
    from tgdrive import diagnostics
    diagnostics.install_hooks()

    if args.browser:
        return run_browser_mode(args, config)

    # Qt must be configured before it is imported.
    added = [k for k in ("QT_QPA_PLATFORM",) if k not in os.environ]
    if "QTWEBENGINE_DISABLE_SANDBOX" not in os.environ and not sandbox_usable():
        # Keep the renderer sandbox wherever the system allows it; without it Chromium won't start at all.
        log.info("renderer sandbox unavailable on this system; running without it")
        os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if args.no_gpu or os.environ.get("TGDRIVE_NO_GPU"):
        flags += " --disable-gpu --disable-gpu-compositing"
        os.environ["QT_QUICK_BACKEND"] = "software"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --autoplay-policy=no-user-gesture-required").strip()
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb" if os.environ.get("WAYLAND_DISPLAY") else "xcb")
    os.environ["TGDRIVE_ENV_ADDED"] = ",".join(added)  # removed again for programs TG Drive starts
    try:
        import importlib
        importlib.import_module("PyQt6.QtWebEngineWidgets")  # must load before QApplication exists
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:  # Qt unusable on this system: fall back to the browser
        log.warning("native window unavailable (%s); opening in the browser", exc)
        print(f"Native window unavailable ({exc}). Opening TG Drive in your browser.")
        return run_browser_mode(args, config)

    from . import shell
    sys.argv[0] = APP_ID
    app = QApplication([APP_ID, *sys.argv[1:]])
    shell.run(app, args, log_path)


def run_browser_mode(args, config) -> None:
    import run
    token = secrets.token_urlsafe(24)
    server, t, port, media = run.serve_in_thread(port=args.port, token=token, desktop=False)
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.1)
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"TG Drive is running at http://127.0.0.1:{port} — close this window or press Ctrl+C to stop.")
    open_in_browser(url, config.DATA_DIR)
    try:
        while t.is_alive():
            t.join(1)
    except KeyboardInterrupt:
        server.should_exit = True
        t.join(30)


if __name__ == "__main__":
    main()
