from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, LoadingIndicator, Select, Switch

from ...core import packages
from ...core.fmt import C, human
from ...core.run import out
from ..widgets import Btn, Choice, ChoiceScreen, InputScreen, Panel, SearchInput, SortTable, muted, plain

SOURCE_COLOR = {"apt": C["blue"], "snap": C["peach"], "flatpak": C["teal"], "appimage": C["pink"], "manual": C["overlay2"]}


class AppsPanel(Panel):
    PANEL_ID = "apps"
    TITLE = "Apps"
    ICON = "󰀻"
    PLAIN_ICON = "▦"
    HELP = "Everything installed, from every source. Enter shows details"

    DEFAULT_CSS = """
    AppsPanel .toolbar Select { width: 22; }
    AppsPanel .toolbar Label { margin: 0 1; }
    AppsPanel LoadingIndicator { height: 3; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.apps: list[packages.App] = []
        self.show_all = False

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(classes="toolbar"):
            yield SearchInput(placeholder="Search installed apps…", id="filter")
            yield Choice([("All sources", "all"), ("System (apt)", "apt"), ("Snap", "snap"), ("Flatpak", "flatpak"), ("AppImage / manual", "appimage")],
                         value="all", allow_blank=False, id="source")
            yield Label("All packages")
            yield Switch(value=False, id="allpkgs")
        with Horizontal(classes="toolbar"):
            yield Btn("Install new app…", id="install", variant="primary")
            yield Btn("Uninstall", id="remove", variant="error")
            yield Btn("Details", id="info")
        yield LoadingIndicator()
        yield SortTable([("name", "App"), ("source", "From"), ("version", "Version"), ("size", "Size"), ("summary", "Description")], sort="size", empty="No apps match")
        yield Label("", id="foot", classes="hint")

    def load(self) -> None:
        self.query_one(LoadingIndicator).display = True
        self.fetch()

    @work(thread=True, exclusive=True, group="apps")
    def fetch(self) -> None:
        apps = packages.all_apps()
        if self.show_all:
            known = {a.id for a in apps}
            apps += [a for a in packages.apt_manual() if a.id not in known]
        self.app.call_from_thread(self.show, apps)

    def show(self, apps: list[packages.App]) -> None:
        self.query_one(LoadingIndicator).display = False
        self.apps = apps
        self.render_rows()

    def render_rows(self) -> None:
        q = self.query_one("#filter", Input).value.strip().lower()
        src = self.query_one("#source", Select).value
        rows = []
        for i, a in enumerate(self.apps):
            if src != "all" and not (a.source == src or (src == "appimage" and a.source == "manual")):
                continue
            if q and q not in a.name.lower() and q not in a.id.lower() and q not in a.summary.lower():
                continue
            rows.append((f"{a.source}:{a.id}:{i}", {"name": a.name.lower(), "source": a.source, "version": a.version, "size": a.size,
                                                   "summary": a.summary, "idx": i},
                         [Text(a.name, style="bold"), Text(a.source, style=SOURCE_COLOR.get(a.source, "")), muted(a.version[:24]),
                          Text(human(a.size) if a.size else "", style=C["subtext0"]), plain(a.summary[:80])]))
        self.query_one(SortTable).set_rows(rows)
        total = sum(a.size for a in self.apps)
        by = {}
        for a in self.apps:
            by[a.source] = by.get(a.source, 0) + 1
        self.query_one("#foot", Label).update(f"{len(self.apps)} apps · {human(total)} · " + " · ".join(f"{n} {s}" for s, n in sorted(by.items())))

    def _selected(self) -> packages.App | None:
        sel = self.query_one(SortTable).selected()
        return self.apps[sel["idx"]] if sel else None

    @on(Input.Changed, "#filter")
    @on(Select.Changed, "#source")
    def _refilter(self) -> None:
        if self.apps:
            self.render_rows()

    @on(Switch.Changed, "#allpkgs")
    def _all(self, e: Switch.Changed) -> None:
        self.show_all = e.value
        self.load()

    @on(Button.Pressed, "#remove")
    @work
    async def _remove(self) -> None:
        a = self._selected()
        if not a:
            return
        await self.run(f"Uninstall {a.name}", packages.remove_steps(a),
                       f"Removes {a.name} ({a.source})" + (f" and frees about {human(a.size)}." if a.size else ".")
                       + (" Its settings in your home folder are kept." if a.source == "apt" else ""), danger=True, ok_label="Uninstall")

    @on(Button.Pressed, "#info")
    @on(SortTable.RowSelected)
    @work
    async def _info(self) -> None:
        a = self._selected()
        if not a:
            return
        cmd = {"apt": ["apt-cache", "show", "--no-all-versions", a.id], "snap": ["snap", "info", a.id],
               "flatpak": ["flatpak", "info", a.id]}.get(a.source)
        text = await asyncio.to_thread(out, cmd, timeout=20) if cmd else f"{a.name}\n{a.location}"
        self.show_text(f"{a.name} ({a.source})", text)

    @on(Button.Pressed, "#install")
    @work
    async def _install(self) -> None:
        q = await self.app.push_screen_wait(InputScreen("Install a new app", "Search Ubuntu, Snap Store and Flathub. Example: vlc, obsidian, postman", "App name"))
        if not q:
            return
        self.app.notify(f"Searching for “{q}”…")
        results = await asyncio.to_thread(packages.search, q)
        if not results:
            self.app.notify("Nothing found. Try a shorter name.", severity="warning")
            return
        rows = []
        for i, a in enumerate(results):
            rows.append((str(i), [Text(a.name, style="bold"), Text(a.source, style=SOURCE_COLOR.get(a.source, "")), muted(a.version[:20]),
                                  Text("installed", style=C["green"]) if a.location == "installed" else Text(""), plain(a.summary[:70])]))
        choice = await self.app.push_screen_wait(ChoiceScreen(f"Results for “{q}”", ["Name", "From", "Version", "", "Description"], rows,
                                                               "Snap and Flatpak apps are sandboxed and update themselves; apt apps come from Ubuntu."))
        if choice is None:
            return
        a = results[int(choice)]
        if a.location == "installed":
            self.app.notify(f"{a.name} is already installed.")
            return
        await self.run(f"Install {a.name}", packages.install_steps(a), f"Installs {a.name} from {a.source}.")
