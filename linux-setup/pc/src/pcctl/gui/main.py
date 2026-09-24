"""Entry point: `pc-gui` (or `python3 -m pcctl.gui`)."""

from __future__ import annotations

import argparse
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Graphene, Gtk  # noqa: E402

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


class App(Adw.Application):
    def __init__(self, start: str | None = None, shots: str | None = None, pages: list[str] | None = None, wait: float = 3.0):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE if shots else Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.start, self.shots, self.shot_pages, self.wait = start, shots, pages, wait
        GLib.set_application_name("PC Command Center")

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display is not None:  # our icon, also when running straight from the source folder
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(os.path.dirname(__file__), "data"))
        Gtk.Window.set_default_icon_name(APP_ID)
        from .window import load_css
        load_css()
        q = Gio.SimpleAction.new("quit", None)
        q.connect("activate", lambda *_: self.quit())
        self.add_action(q)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            from .window import MainWindow
            win = MainWindow(self, self.start)
        win.present()
        if self.shots:
            self._shoot(win)

    def do_command_line(self, cmdline) -> int:
        """Also runs in the already-open app when you launch it again (e.g. 'Clean up' from the dock menu)."""
        args = cmdline.get_arguments()[1:]
        page = None
        for i, a in enumerate(args):
            if a == "--page" and i + 1 < len(args):
                page = args[i + 1]
            elif a.startswith("--page="):
                page = a.split("=", 1)[1]
        first = self.props.active_window is None
        if first and page:
            self.start = page
        self.activate()
        if not first and page:
            self.props.active_window.goto(page)
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

            def snap() -> bool:
                screenshot(win, os.path.join(self.shots, f"{pid}.png"))
                print("shot", pid, flush=True)
                state["i"] += 1
                GLib.timeout_add(100, step)
                return False
            GLib.timeout_add(int(self.wait * 1000), snap)
            return False
        GLib.timeout_add(800, step)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pc-gui", description="PC Command Center")
    ap.add_argument("--page", default=None, help="page to open (default: the one you had open last)")
    ap.add_argument("--screenshots", help=argparse.SUPPRESS)
    ap.add_argument("--pages", help=argparse.SUPPRESS)
    ap.add_argument("--wait", type=float, default=3.0, help=argparse.SUPPRESS)
    args = argv if argv is not None else sys.argv[1:]
    a = ap.parse_args(args)
    if a.screenshots:
        return App(a.page, a.screenshots, a.pages.split(",") if a.pages else None, a.wait).run([sys.argv[0]])
    return App(a.page).run([sys.argv[0], *args])


if __name__ == "__main__":
    sys.exit(main())
