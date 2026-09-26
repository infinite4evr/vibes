from __future__ import annotations

import asyncio
import os
import subprocess
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static, TabbedContent, TabPane

from ...core import dev, maint
from ...core import network as net
from ...core.fmt import C, ago, duration, human
from ...core.run import HOME, Step, has, which
from ..widgets import Btn, ChoiceScreen, Panel, SortTable, muted, plain


class DevPanel(Panel):
    PANEL_ID = "dev"
    TITLE = "Dev"
    ICON = "󰅩"
    PLAIN_ICON = "λ"
    HELP = "Your projects, running dev servers, pm2 bots, containers and language versions"

    DEFAULT_CSS = """
    DevPanel TabbedContent { height: 1fr; }
    DevPanel TabPane { padding: 0; }
    """

    def compose(self) -> ComposeResult:
        yield from self.head()
        with TabbedContent():
            with TabPane("Projects", id="t-proj"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Open in VS Code", id="code", variant="primary")
                    yield Btn("Open in Zed", id="zed")
                    yield Btn("lazygit", id="lazygit")
                    yield Btn("Pull", id="pull")
                    yield Btn("Open folder", id="folder")
                    yield Btn("Rescan", id="rescan")
                yield SortTable([("name", "Project"), ("branch", "Branch"), ("state", "Changes"), ("sync", "Sync"), ("last", "Last commit"),
                                 ("msg", "Message"), ("path", "Folder")], sort="last", id="projects",
                                empty="No git projects found in ~/Documents, ~/Projects, ~/code or ~/dev (folders are set in ~/.config/pc/config.json)")
            with TabPane("Dev servers", id="t-srv"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Stop selected", id="stopsrv", variant="error")
                    yield Btn("Refresh", id="refsrv")
                yield Label("Programs you started that are listening on a port (localhost:3000 and friends).", classes="hint")
                yield SortTable([("port", "Port"), ("kind", "Kind"), ("process", "App"), ("url", "Open at"), ("cmd", "Command")], sort="port",
                                reverse=False, id="servers", empty="No dev servers running")
            with TabPane("pm2 bots", id="t-pm2"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Restart", id="pm2-restart", variant="primary")
                    yield Btn("Stop", id="pm2-stop")
                    yield Btn("Start", id="pm2-start")
                    yield Btn("Logs", id="pm2-logs")
                    yield Btn("Refresh", id="pm2-ref")
                yield SortTable([("name", "Name"), ("status", "Status"), ("cpu", "CPU"), ("mem", "Memory"), ("restarts", "Restarts"),
                                 ("uptime", "Up for"), ("cwd", "Folder")], sort="name", reverse=False, id="pm2")
            with TabPane("Containers", id="t-ct"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Start", id="ct-start")
                    yield Btn("Stop", id="ct-stop")
                    yield Btn("Logs", id="ct-logs")
                    yield Btn("Remove", id="ct-rm", variant="error")
                    yield Btn("Refresh", id="ct-ref")
                yield SortTable([("name", "Name"), ("state", "State"), ("image", "Image"), ("ports", "Ports"), ("status", "Status")], sort="state", id="containers")
            with TabPane("Languages", id="t-lang"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Install latest Node LTS", id="node-lts", variant="primary")
                    yield Btn("Make selected Node default", id="node-default")
                    yield Btn("Remove selected Node", id="node-rm", variant="error")
                yield Static(id="langs")
                yield SortTable([("version", "Node version (nvm)"), ("tags", "Used by")], sort="version", id="nodes",
                                empty="No Node versions installed with nvm")

    def load(self) -> None:
        self.fetch_projects()
        self.fetch_servers()
        self.fetch_pm2()
        self.fetch_containers()
        self.fetch_langs()

    # ---------------------------------------------------------------- projects
    @work(thread=True, exclusive=True, group="proj")
    def fetch_projects(self) -> None:
        repos = dev.repos(maint.project_roots())
        self.app.call_from_thread(self.show_projects, repos)

    def show_projects(self, repos: list[dict]) -> None:
        self.repos = {r["path"]: r for r in repos}
        rows = []
        for r in repos:
            changes = r["changed"] + r["untracked"]
            state = Text(f"{changes} changed", style=C["peach"]) if changes else Text("clean", style=C["green"])
            sync = []
            if r["ahead"]:
                sync.append(f"↑{r['ahead']} to push")
            if r["behind"]:
                sync.append(f"↓{r['behind']} to pull")
            if not r["upstream"]:
                sync.append("no remote" if not r["remote"] else "not tracking")
            rows.append((r["path"], {"name": r["name"].lower(), "branch": r["branch"], "state": changes, "sync": r["ahead"] + r["behind"],
                                     "last": r["last_commit"], "msg": r["message"], "path": r["path"]},
                         [Text(r["name"], style="bold"), Text(r["branch"], style=C["mauve"]), state,
                          Text(" ".join(sync) or "✓", style=C["peach"] if r["ahead"] or r["behind"] else C["overlay1"]),
                          muted(ago(r["last_commit"]) if r["last_commit"] else "-"), plain(r["message"][:50]), muted(r["path"].replace(str(HOME), "~"))]))
        self.query_one("#projects", SortTable).set_rows(rows)

    def _proj(self) -> dict | None:
        return self.query_one("#projects", SortTable).selected()

    def _launch(self, args: list[str]) -> None:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    @on(Button.Pressed, "#code")
    def _code(self) -> None:
        p = self._proj()
        if p and has("code"):
            self._launch(["code", p["path"]])
        elif p:
            self.app.notify("VS Code isn't installed.")

    @on(Button.Pressed, "#zed")
    def _zed(self) -> None:
        p = self._proj()
        z = which("zed")
        if p and z:
            self._launch([z, p["path"]])
        elif p:
            self.app.notify("Zed isn't installed.")

    @on(Button.Pressed, "#folder")
    def _folder(self) -> None:
        p = self._proj()
        if p:
            self._launch(["xdg-open", p["path"]])

    @on(Button.Pressed, "#lazygit")
    def _lazygit(self) -> None:
        p = self._proj()
        if p and has("lazygit"):
            with self.app.suspend():
                subprocess.call(["lazygit", "-p", p["path"]])
            self.fetch_projects()

    @on(Button.Pressed, "#pull")
    @work
    async def _pull(self) -> None:
        p = self._proj()
        if not p:
            return
        ok = await self.run(f"Pull {os.path.basename(p['path'])}", [Step("Get the latest changes", ["git", "-C", p["path"], "pull", "--ff-only"])],
                            "Only fast-forwards, so it never creates merge commits or overwrites your changes.", reload=False)
        if ok:
            self.fetch_projects()

    @on(Button.Pressed, "#rescan")
    def _rescan(self) -> None:
        self.fetch_projects()

    # ---------------------------------------------------------------- dev servers
    @work(thread=True, exclusive=True, group="srv")
    def fetch_servers(self) -> None:
        me = os.environ.get("USER", "")
        items = [p for p in net.ports(with_root=False) if p.pid and p.proto == "tcp" and p.port >= 1024 and (p.user == me or not p.user)]
        self.app.call_from_thread(self.show_servers, items)

    def show_servers(self, items: list[net.Port]) -> None:
        self.servers = items
        rows = []
        seen = set()
        for p in items:
            if (p.port, p.pid) in seen:
                continue
            seen.add((p.port, p.pid))
            url = f"http://localhost:{p.port}"
            rows.append((f"{p.port}:{p.pid}", {"port": p.port, "kind": p.kind, "process": p.process, "url": url, "cmd": p.cmd, "pid": p.pid},
                         [Text(str(p.port), style="bold"), Text(p.kind or "", style=C["mauve"]), plain(p.process), Text(url, style=C["blue"]),
                          plain(p.cmd[:100])]))
        self.query_one("#servers", SortTable).set_rows(rows)

    @on(Button.Pressed, "#refsrv")
    def _refsrv(self) -> None:
        self.fetch_servers()

    @on(Button.Pressed, "#stopsrv")
    @work
    async def _stopsrv(self) -> None:
        s = self.query_one("#servers", SortTable).selected()
        if not s:
            return
        await self.run(f"Stop {s['process']} on port {s['port']}", [Step(f"Stop process {s['pid']}", ["kill", str(s["pid"])])], reload=False)
        await asyncio.sleep(0.5)
        self.fetch_servers()

    @on(SortTable.RowSelected, "#servers")
    def _open_url(self) -> None:
        s = self.query_one("#servers", SortTable).selected()
        if s:
            self._launch(["xdg-open", s["url"]])

    # ---------------------------------------------------------------- pm2
    @work(thread=True, exclusive=True, group="pm2")
    def fetch_pm2(self) -> None:
        items = dev.pm2_list()
        self.app.call_from_thread(self.show_pm2, items)

    def show_pm2(self, items: list[dict]) -> None:
        rows = []
        for p in items:
            st = p["status"]
            rows.append((str(p["name"]), {"name": str(p["name"]).lower(), "status": st, "cpu": p["cpu"], "mem": p["mem"], "restarts": p["restarts"],
                                          "uptime": p["uptime"] or 0, "cwd": p["cwd"], "id": p["name"]},
                         [Text(str(p["name"]), style="bold"), Text(("● " if st == "online" else "■ ") + st, style=C["green"] if st == "online" else C["red"]),
                          Text(f"{p['cpu']}%"), Text(human(p["mem"])), Text(str(p["restarts"]), style=C["peach"] if p["restarts"] > 10 else ""),
                          muted(duration(p["uptime"]) if p["uptime"] else "-"), muted(p["cwd"].replace(str(HOME), "~"))]))
        t = self.query_one("#pm2", SortTable)
        t.empty = "pm2 has nothing running" if dev._nvm_bin("pm2") else "pm2 isn't installed"
        t.set_rows(rows)

    async def _pm2(self, action: str) -> None:
        s = self.query_one("#pm2", SortTable).selected()
        if not s or "id" not in s:
            return
        await self.run(f"pm2 {action} {s['id']}", dev.pm2_steps(action, s["id"]), reload=False)
        self.fetch_pm2()

    @on(Button.Pressed, "#pm2-restart")
    @work
    async def _pm2r(self) -> None:
        await self._pm2("restart")

    @on(Button.Pressed, "#pm2-stop")
    @work
    async def _pm2s(self) -> None:
        await self._pm2("stop")

    @on(Button.Pressed, "#pm2-start")
    @work
    async def _pm2st(self) -> None:
        await self._pm2("start")

    @on(Button.Pressed, "#pm2-logs")
    @work
    async def _pm2l(self) -> None:
        s = self.query_one("#pm2", SortTable).selected()
        if s and "id" in s:
            text = await asyncio.to_thread(dev.pm2_logs, s["id"], 300)
            self.show_text(f"pm2 logs - {s['id']}", text)

    @on(Button.Pressed, "#pm2-ref")
    def _pm2ref(self) -> None:
        self.fetch_pm2()

    # ---------------------------------------------------------------- containers
    @work(thread=True, exclusive=True, group="ct")
    def fetch_containers(self) -> None:
        items = dev.containers()
        self.app.call_from_thread(self.show_containers, items)

    def show_containers(self, items: list[dict]) -> None:
        rows = []
        for c in items:
            running = c["state"] == "running"
            rows.append((c["id"] or c["name"], {"name": c["name"], "state": 0 if running else 1, "image": c["image"], "ports": c["ports"],
                                                "status": c["status"], "id": c["id"] or c["name"]},
                         [Text(c["name"], style="bold"), Text(("● " if running else "○ ") + c["state"], style=C["green"] if running else C["overlay0"]),
                          plain(c["image"][:50]), plain(c["ports"]), muted(c["status"])]))
        t = self.query_one("#containers", SortTable)
        t.empty = "No containers" if dev.container_tool() else "Docker / Podman isn't installed"
        t.set_rows(rows)

    async def _ct(self, action: str) -> None:
        s = self.query_one("#containers", SortTable).selected()
        tool = dev.container_tool()
        if not s or "id" not in s or not tool:
            return
        cmd = [tool, "rm", "-f", s["id"]] if action == "rm" else [tool, action, s["id"]]
        await self.run(f"{action.title()} {s['name']}", [Step(f"{tool} {action} {s['name']}", cmd)], danger=action == "rm", reload=False)
        self.fetch_containers()

    @on(Button.Pressed, "#ct-start")
    @work
    async def _cts(self) -> None:
        await self._ct("start")

    @on(Button.Pressed, "#ct-stop")
    @work
    async def _ctp(self) -> None:
        await self._ct("stop")

    @on(Button.Pressed, "#ct-rm")
    @work
    async def _ctr(self) -> None:
        await self._ct("rm")

    @on(Button.Pressed, "#ct-logs")
    @work
    async def _ctl(self) -> None:
        s = self.query_one("#containers", SortTable).selected()
        tool = dev.container_tool()
        if s and "id" in s and tool:
            from ...core.run import sh
            r = await asyncio.to_thread(sh, [tool, "logs", "--tail", "300", s["id"]], timeout=20)
            self.show_text(f"{s['name']} logs", r.out + r.err)

    @on(Button.Pressed, "#ct-ref")
    def _ctref(self) -> None:
        self.fetch_containers()

    # ---------------------------------------------------------------- languages
    @work(thread=True, exclusive=True, group="lang")
    def fetch_langs(self) -> None:
        rt = dev.runtimes()
        nodes = dev.node_versions()
        pys = dev.python_versions()
        self.app.call_from_thread(self.show_langs, rt, nodes, pys)

    def show_langs(self, rt, nodes, pys) -> None:
        t = Text()
        width = max((len(r["name"]) for r in rt), default=8) + 2
        for i, r in enumerate(rt):
            if i:
                t.append("\n")
            t.append(f"{r['name']:<{width}}", style="bold")
            t.append(f"{r['version']:<14}", style=C["green"])
            t.append(r["path"], style=C["overlay1"])
        if pys:
            t.append("\n\nPython versions: ", style="bold")
            t.append(", ".join(f"{p['version']} ({p['manager']}{', global' if 'global' in p['tags'] else ''})" for p in pys), style=C["subtext0"])
        self.query_one("#langs", Static).update(t)
        rows = [(n["version"], {"version": tuple(int(x) for x in n["version"].lstrip("v").split(".") if x.isdigit()), "tags": ", ".join(n["tags"]),
                                "v": n["version"], "protected": n["protected"]},
                 [Text(n["version"], style="bold"), Text(", ".join(n["tags"]) or "-", style=C["green"] if n["tags"] else C["overlay1"])]) for n in nodes]
        self.query_one("#nodes", SortTable).set_rows(rows)

    @on(Button.Pressed, "#node-lts")
    @work
    async def _lts(self) -> None:
        if not (HOME / ".nvm/nvm.sh").exists():
            self.app.notify("nvm isn't installed.", severity="warning")
            return
        await self.run("Install Node LTS", [Step("Install latest Node LTS", dev.nvm_cmd("install --lts"))], "Your current versions stay installed.", reload=False)
        self.fetch_langs()

    @on(Button.Pressed, "#node-default")
    @work
    async def _ndef(self) -> None:
        s = self.query_one("#nodes", SortTable).selected()
        if s:
            await self.run(f"Make Node {s['v']} the default", [Step("Set default", dev.nvm_cmd(f"alias default {s['v']}"))],
                           "New terminals will use this version. Running apps (like pm2 bots) keep theirs until restarted.", reload=False)
            self.fetch_langs()

    @on(Button.Pressed, "#node-rm")
    @work
    async def _nrm(self) -> None:
        s = self.query_one("#nodes", SortTable).selected()
        if not s:
            return
        if s["protected"]:
            self.app.notify(f"Node {s['v']} is in use ({s['tags']}) - not removing it.", severity="warning")
            return
        await self.run(f"Remove Node {s['v']}", [Step("Uninstall", dev.nvm_cmd(f"uninstall {s['v']}"))], danger=True, reload=False)
        self.fetch_langs()
