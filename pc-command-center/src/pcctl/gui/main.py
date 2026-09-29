"""Entry point: `pc-gui` (or `python3 -m pcctl.gui`)."""

from __future__ import annotations

import argparse
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Graphene, Gtk  # noqa: E402

from .. import __version__  # noqa: E402

APP_ID = "io.github.infinite4evr.PcCommandCenter"


def screenshot(win: Gtk.Window, path: str) -> None:
    w, h = win.get_width(), win.get_height()
    p = Gtk.WidgetPaintable(widget=win)
    snap = Gtk.Snapshot()
    p.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        return
    tex = win.get_native().get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    tex.save_to_png(path)


def _install_crash_guard() -> None:
    """Unexpected errors go to ~/.local/state/pc/gui-errors.log and show as a toast instead of vanishing."""
    import traceback

    from .activity import log_error

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.__stderr__.write(text)
        log_error(text)
        app = Gio.Application.get_default()
        win = app.props.active_window if app else None
        if win is not None and hasattr(win, "toast"):
            GLib.idle_add(lambda: (win.toast(f"Something went wrong: {exc}. Details are in ~/.local/state/pc/gui-errors.log", 6), False)[1])
    sys.excepthook = hook


class App(Adw.Application):
    def __init__(self, start: str | None = None, shots: str | None = None, pages: list[str] | None = None, wait: float = 3.0,
                 shot_width: int | None = None, shot_height: int | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE if shots else Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.start, self.shots, self.shot_pages, self.wait = start, shots, pages, wait
        self.shot_width, self.shot_height = shot_width, shot_height
        if shots:
            # Screenshot runs must neither inherit nor overwrite the user's window state/preferences.
            import tempfile
            from pathlib import Path

            from . import prefs
            prefs.FILE = Path(tempfile.mkdtemp(prefix="pcctl-shots-")) / "gui.json"
            prefs._cache = {"welcomed": True}
        GLib.set_application_name("PC Command Center")

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display is not None:  # our icon, also when running straight from the source folder
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(os.path.dirname(__file__), "data"))
        Gtk.Window.set_default_icon_name(APP_ID)
        from . import prefs, theme
        from ..core import debug
        debug_on = str(os.environ.get("PC_DEBUG", "")).lower() in ("1", "true", "yes", "on") or bool(prefs.get("debug_logging"))
        debug.configure(debug_on)
        debug.event("app.startup", app=APP_ID, debug=debug_on)
        theme.setup(os.environ.get("PC_STYLE") or prefs.get("appearance"), os.environ.get("PC_LOOK") or prefs.get("look"))
        _install_crash_guard()
        q = Gio.SimpleAction.new("quit", None)
        q.connect("activate", lambda *_: self.quit())
        self.add_action(q)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            from .window import MainWindow
            win = MainWindow(self, self.start)
            if self.shots and self.shot_width and self.shot_height:
                win.set_default_size(max(760, self.shot_width), max(520, self.shot_height))
            from . import prefs
            if not self.shots and not prefs.get("welcomed") and not os.environ.get("PC_NO_WELCOME"):
                GLib.timeout_add(900, lambda: (win.welcome(), False)[1])
        win.present()
        if self.shots:
            self._shoot(win)

    def do_command_line(self, cmdline) -> int:
        """Also runs in the already-open app when you launch it again (e.g. 'Clean up' from the dock menu)."""
        args = cmdline.get_arguments()[1:]
        page = action = None
        for i, a in enumerate(args):
            if a in ("--page", "--action") and i + 1 < len(args):
                if a == "--page":
                    page = args[i + 1]
                else:
                    action = args[i + 1]
            elif a.startswith("--page="):
                page = a.split("=", 1)[1]
            elif a.startswith("--action="):
                action = a.split("=", 1)[1]
        first = self.props.active_window is None
        if first and page:
            self.start = page
        self.activate()
        win = self.props.active_window
        if not first and page:
            win.goto(page)
        if action and win is not None:  # e.g. from GNOME search or the dock menu: "maintenance:fix-sound", "app:palette"
            GLib.timeout_add(700 if first else 50, lambda: (win.run_action(action), False)[1])
        return 0

    # testing helper: visit pages and save PNGs
    def _shoot(self, win) -> None:
        os.makedirs(self.shots, exist_ok=True)
        pages = self.shot_pages or list(win.pages)
        state = {"i": 0}

        def step() -> bool:
            if state["i"] >= len(pages):
                self.quit()
                return False
            pid = pages[state["i"]]
            win.goto(pid)

            def snap(tries: int = 0) -> bool:
                path = os.path.join(self.shots, f"{pid}.png")
                screenshot(win, path)
                if not os.path.exists(path) and tries < 4:  # nothing rendered yet (mid-relayout); try again shortly
                    GLib.timeout_add(400, lambda: snap(tries + 1))
                    return False
                print("shot", pid, flush=True)
                state["i"] += 1
                GLib.timeout_add(100, step)
                return False
            GLib.timeout_add(int(self.wait * 1000), snap)
            return False
        GLib.timeout_add(800, step)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pc-gui", description="PC Command Center")
    ap.add_argument("--version", action="version", version=f"PC Command Center {__version__}")
    ap.add_argument("--page", default=None, help="page to open (default: the one you had open last)")
    ap.add_argument("--action", default=None, help="run a palette action, e.g. maintenance:fix-sound or app:palette")
    ap.add_argument("--debug", action="store_true", help="enable detailed, privacy-redacted diagnostic logging for this run")
    ap.add_argument("--screenshots", help=argparse.SUPPRESS)
    ap.add_argument("--pages", help=argparse.SUPPRESS)
    ap.add_argument("--wait", type=float, default=3.0, help=argparse.SUPPRESS)
    ap.add_argument("--width", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--height", type=int, help=argparse.SUPPRESS)
    args = argv if argv is not None else sys.argv[1:]
    a = ap.parse_args(args)
    if a.debug:
        os.environ["PC_DEBUG"] = "1"
    if a.screenshots:
        return App(a.page, a.screenshots, a.pages.split(",") if a.pages else None, a.wait, a.width, a.height).run([sys.argv[0]])
    return App(a.page).run([sys.argv[0], *args])


if __name__ == "__main__":
    sys.exit(main())
