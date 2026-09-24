"""Developer: git projects, running dev servers, pm2, containers, language versions and a CLI toolbox."""

from __future__ import annotations

import os
import re

from gi.repository import Gtk

from ...core import dev, maint, network, security
from ...core.fmt import ago, duration
from ...core.run import HOME, Step, has, which
from ..util import button, clear, hbox, label, launch, open_in_terminal, open_path, pill, spacer, vbox
from ..widgets import Column, DataTable
from .base import Page, action_row, group, tabs

APT = {"DEBIAN_FRONTEND": "noninteractive"}
# (command to look for, apt package, name, what it does)
TOOLBOX = [
    ("git", "git", "Git", "Version control."),
    ("gh", "gh", "GitHub CLI", "PRs, issues and repos from the terminal."),
    ("lazygit", "lazygit", "lazygit", "A friendly terminal UI for git."),
    ("rg", "ripgrep", "ripgrep", "Search code insanely fast (rg)."),
    ("fdfind", "fd-find", "fd", "Find files by name, simpler than find."),
    ("fzf", "fzf", "fzf", "Fuzzy finder: Ctrl+R history, Ctrl+T files."),
    ("batcat", "bat", "bat", "cat with syntax highlighting."),
    ("eza", "eza", "eza", "ls with icons, git status and colours."),
    ("zoxide", "zoxide", "zoxide", "Jump to folders you use: z proj."),
    ("btop", "btop", "btop", "Beautiful resource monitor."),
    ("jq", "jq", "jq", "Slice and pretty-print JSON."),
    ("http", "httpie", "HTTPie", "curl for humans: http GET api.example.com."),
    ("tldr", "tldr", "tldr", "Short, practical man pages."),
    ("direnv", "direnv", "direnv", "Per-project environment variables."),
    ("just", "just", "just", "A handy command runner (like make)."),
    ("tmux", "tmux", "tmux", "Keep terminal sessions running."),
    ("shellcheck", "shellcheck", "ShellCheck", "Finds bugs in shell scripts."),
    ("sqlite3", "sqlite3", "SQLite", "Tiny database for local projects."),
]


def github_url(remote: str) -> str:
    m = re.match(r"(?:git@|https://)([^:/]+)[:/](.+?)(?:\.git)?$", remote.strip())
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


class DevPage(Page):
    ID = "dev"
    TITLE = "Developer"
    ICON = "utilities-terminal-symbolic"
    SUBTITLE = "Your projects, running dev servers, pm2 bots, containers, language versions and handy CLI tools."

    def build(self) -> None:
        self.header()
        self.proj = vbox(spacing=10)
        self.srv = vbox(spacing=10)
        self.pm2 = vbox(spacing=10)
        self.ct = vbox(spacing=10)
        self.langs = vbox(spacing=18)
        self.tools = vbox(spacing=10)
        sw, self.stack = tabs(("proj", "Projects", "folder-symbolic", self.proj), ("srv", "Dev servers", "network-server-symbolic", self.srv),
                              ("pm2", "pm2", "system-run-symbolic", self.pm2), ("ct", "Containers", "package-x-generic-symbolic", self.ct),
                              ("langs", "Languages", "applications-engineering-symbolic", self.langs),
                              ("tools", "Toolbox", "applications-utilities-symbolic", self.tools))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_projects()
        self._build_servers()
        self._build_pm2()
        self._build_containers()

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"proj": self.load_projects, "srv": self.load_servers, "pm2": self.load_pm2, "ct": self.load_containers, "langs": self.load_langs,
         "tools": self.show_tools}[name]()

    def _table_sel(self, table: DataTable, fn) -> None:
        r = table.selected()
        if r:
            fn(r)
        else:
            self.toast("Select a row first.")

    # ---------------------------------------------------------------- projects
    def _build_projects(self) -> None:
        self.search_entry = Gtk.SearchEntry(placeholder_text="Find a project…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.ptable.set_filter(e.get_text()))
        self.proj_info = label("", "dim")
        self.proj.append(hbox(self.search_entry, self.proj_info, button(icon="view-refresh-symbolic", tooltip="Rescan", on_click=self.load_projects)))
        self.ptable = DataTable([
            Column("name", "Project", "bold", width=200),
            Column("branch", "Branch", "mono", width=140),
            Column("state", "Changes", "pill", width=120, sort="changes"),
            Column("sync", "Sync", "pill", width=120, sort="syncn"),
            Column("when", "Last commit", "muted", width=110, sort="last"),
            Column("msg", "Message", "text", expand=True),
        ], on_activate=lambda r: self._code(r), empty="No git projects found.", sort="last",
            search=lambda d, q: q in d["name"].lower() or q in d["path"].lower())
        self.ptable.set_size_request(-1, 420)
        self.proj.append(self.ptable)
        t = self.ptable
        self.proj.append(hbox(
            button("VS Code", icon="accessories-text-editor-symbolic", css="suggested-action", on_click=lambda: self._table_sel(t, self._code)),
            button("Zed", on_click=lambda: self._table_sel(t, self._zed)),
            button("Terminal", icon="utilities-terminal-symbolic", on_click=lambda: self._table_sel(t, self._term)),
            button("lazygit", on_click=lambda: self._table_sel(t, lambda r: open_in_terminal(["lazygit", "-p", r["path"]]) if has("lazygit") else self.toast("lazygit isn't installed (Toolbox tab)."))),
            button("Pull", icon="go-down-symbolic", on_click=lambda: self._table_sel(t, self._pull)),
            spacer(),
            button(icon="web-browser-symbolic", css="flat", tooltip="Open on GitHub", on_click=lambda: self._table_sel(t, self._web)),
            button(icon="folder-open-symbolic", css="flat", tooltip="Open folder", on_click=lambda: self._table_sel(t, lambda r: open_path(r["path"]))), spacing=6))
        self.proj.append(label("Searching: " + ", ".join(str(p).replace(str(HOME), "~") for p in maint.project_roots()) +
                               ". Double-click opens a project in VS Code.", "dim", wrap=True))

    def load_projects(self) -> None:
        self.ptable.set_empty("Looking for git projects…")
        self.bg(lambda: dev.repos(maint.project_roots()), self.show_projects)

    def show_projects(self, repos: list[dict]) -> None:
        rows = []
        dirty = 0
        for r in repos:
            changes = r["changed"] + r["untracked"]
            dirty += bool(changes)
            sync = []
            if r["ahead"]:
                sync.append(f"↑{r['ahead']} to push")
            if r["behind"]:
                sync.append(f"↓{r['behind']} to pull")
            sync_pill = (" ".join(sync), "warn") if sync else (("no remote", "neutral") if not r["remote"] else (("not tracking", "neutral") if not r["upstream"] else ("in sync", "ok")))
            rows.append({"key": r["path"], "name": r["name"], "branch": r["branch"], "changes": changes,
                         "state": (f"{changes} changed", "warn") if changes else ("clean", "ok"), "sync": sync_pill, "syncn": r["ahead"] + r["behind"],
                         "last": r["last_commit"], "when": ago(r["last_commit"]) if r["last_commit"] else "-", "msg": r["message"],
                         "path": r["path"], "remote": r["remote"]})
        self.ptable.set_rows(rows)
        self.ptable.set_empty("No git projects found in your project folders.")
        self.proj_info.set_text(f"{len(rows)} projects · {dirty} with uncommitted changes")

    def _code(self, r: dict) -> None:
        exe = which("code") or which("code-insiders") or which("cursor")
        launch([exe, r["path"]]) if exe else self.toast("VS Code isn't installed.")

    def _zed(self, r: dict) -> None:
        exe = which("zed") or which("zeditor")
        launch([exe, r["path"]]) if exe else self.toast("Zed isn't installed.")

    def _term(self, r: dict) -> None:
        for term, args in (("ghostty", [f"--working-directory={r['path']}"]), ("ptyxis", ["--new-window", "-d", r["path"]]),
                           ("gnome-terminal", [f"--working-directory={r['path']}"])):
            if which(term):
                launch([which(term), *args])
                return
        self.toast("No terminal found.")

    def _pull(self, r: dict) -> None:
        self.run(f"Pull {r['name']}", [Step("Get the latest changes", ["git", "-C", r["path"], "pull", "--ff-only"])],
                 "Only fast-forwards: never creates merge commits or touches your uncommitted changes.", ok_label="Pull", reload=False,
                 done=lambda ok: self.load_projects())

    def _web(self, r: dict) -> None:
        url = github_url(r["remote"])
        launch(["xdg-open", url]) if url else self.toast("This project has no remote.")

    # ---------------------------------------------------------------- dev servers
    def _build_servers(self) -> None:
        self.stable = DataTable([
            Column("port", "Port", "bold", width=80),
            Column("kind", "Kind", "pill", width=110),
            Column("process", "Process", "text", width=140),
            Column("reach", "Reachable from", "pill", width=150),
            Column("url", "Address", "mono", width=190),
            Column("cmd", "Command", "mono", expand=True),
        ], on_activate=lambda r: launch(["xdg-open", r["url"]]), empty="No dev servers running.", sort="port", descending=False)
        self.stable.set_size_request(-1, 380)
        self.srv.append(hbox(label("Programs of yours listening on a port (npm run dev, Django, Vite…).", "dim", hexpand=True),
                             button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_servers)))
        self.srv.append(self.stable)
        t = self.stable
        self.srv.append(hbox(button("Open in browser", icon="web-browser-symbolic", css="suggested-action", on_click=lambda: self._table_sel(t, lambda r: launch(["xdg-open", r["url"]]))),
                             button("Test on your phone…", on_click=lambda: self._table_sel(t, self._phone)),
                             spacer(),
                             button("Stop", icon="process-stop-symbolic", css="destructive-action", on_click=lambda: self._table_sel(t, self._stop_srv)), spacing=6))

    def load_servers(self) -> None:
        me = os.environ.get("USER", "")
        self.bg(lambda: [p for p in network.ports(with_root=False) if p.pid and p.proto == "tcp" and p.port >= 1024 and (p.user == me or not p.user)],
                self.show_servers)

    def show_servers(self, items) -> None:
        rows, seen = [], set()
        for p in items:
            if (p.port, p.pid) in seen:
                continue
            seen.add((p.port, p.pid))
            rows.append({"key": f"{p.port}:{p.pid}", "port": p.port, "kind": (p.kind, "accent") if p.kind else ("", "neutral"), "process": p.process,
                         "reach": ("your network", "warn") if p.exposed else ("only this PC", "ok"), "url": f"http://localhost:{p.port}", "cmd": p.cmd,
                         "pid": p.pid, "exposed": p.exposed})
        self.stable.set_rows(rows)
        self.stack.get_page(self.srv).set_badge_number(len(rows))

    def _stop_srv(self, r: dict) -> None:
        self.run(f"Stop {r['process']} on port {r['port']}", [Step(f"Stop process {r['pid']}", ["kill", str(r["pid"])])], ask=False, reload=False,
                 done=lambda ok: self.load_servers())

    def _phone(self, r: dict) -> None:
        ips = [a for i in network.interfaces() if i["up"] for a in i["ipv4"]]
        ip = ips[0] if ips else "?"
        msg = f"On your phone (same Wi-Fi), open:\n\n    http://{ip}:{r['port']}\n\n"
        if not r["exposed"]:
            msg += ("Right now the server only listens on localhost. Start it with host 0.0.0.0, e.g.\n"
                    "    npm run dev -- --host        (Vite)\n    next dev -H 0.0.0.0          (Next.js)\n    python manage.py runserver 0.0.0.0:8000\n\n")
        fw = security.firewall()
        if fw.level == "ok":
            msg += f"Your firewall is on: allow port {r['port']} for your local network on the Security page (or from Network → Open ports)."
        self.text(f"Test port {r['port']} on your phone", msg)

    # ---------------------------------------------------------------- pm2
    def _build_pm2(self) -> None:
        self.pm2table = DataTable([
            Column("name", "App", "bold", width=200),
            Column("st", "Status", "pill", width=100, sort="status"),
            Column("cpu", "CPU", "pct", width=70),
            Column("mem", "Memory", "size", width=90),
            Column("restarts", "Restarts", "num", width=80),
            Column("up", "Up for", "muted", width=100, sort="uptime"),
            Column("script", "Script", "mono", expand=True),
        ], on_activate=lambda r: self._pm2_logs(r), empty="pm2 isn't running any apps.", sort="name", descending=False)
        self.pm2table.set_size_request(-1, 340)
        self.pm2.append(hbox(label("Node apps and bots kept alive by pm2.", "dim", hexpand=True), button(icon="view-refresh-symbolic", on_click=self.load_pm2)))
        self.pm2.append(self.pm2table)
        t = self.pm2table
        self.pm2.append(hbox(*[button(a.title(), on_click=lambda a=a: self._table_sel(t, lambda r: self.run(f"pm2 {a} {r['name']}", dev.pm2_steps(a, r["name"]),
                                                                                                          ask=a in ("stop", "delete"), reload=False, done=lambda ok: self.load_pm2())))
                               for a in ("restart", "stop", "start")],
                             button("Logs", icon="text-x-generic-symbolic", on_click=lambda: self._table_sel(t, self._pm2_logs)), spacer(),
                             button("Remove from pm2", css="destructive-action", on_click=lambda: self._table_sel(t, lambda r: self.run(
                                 f"Remove {r['name']} from pm2", dev.pm2_steps("delete", r["name"]), "pm2 stops it and forgets it. Your code isn't touched.",
                                 danger=True, ok_label="Remove", reload=False, done=lambda ok: self.load_pm2()))), spacing=6))

    def load_pm2(self) -> None:
        self.bg(dev.pm2_list, self.show_pm2)

    def show_pm2(self, items: list[dict]) -> None:
        rows = []
        for p in items:
            kind = "ok" if p["status"] == "online" else ("bad" if p["status"] in ("errored", "stopped") else "neutral")
            rows.append({"key": str(p["id"]), "name": p["name"], "st": (p["status"], kind), "status": p["status"], "cpu": p["cpu"], "mem": p["mem"],
                         "restarts": p["restarts"], "uptime": p["uptime"] or 0,
                         "up": duration(p["uptime"]) if p["uptime"] else "-", "script": p["script"]})
        self.pm2table.set_rows(rows)
        self.pm2table.set_empty("pm2 isn't running any apps." if dev._nvm_bin("pm2") else "pm2 isn't installed.")

    def _pm2_logs(self, r: dict) -> None:
        self.bg(lambda: dev.pm2_logs(r["name"], 300), lambda t: self.text(f"pm2 logs: {r['name']}", t or "No log output."))

    # ---------------------------------------------------------------- containers
    def _build_containers(self) -> None:
        self.cttable = DataTable([
            Column("name", "Container", "bold", width=200),
            Column("st", "State", "pill", width=100, sort="state"),
            Column("image", "Image", "mono", expand=True),
            Column("ports", "Ports", "mono", width=160),
            Column("status", "Status", "muted", width=160),
        ], on_activate=lambda r: self._ct_logs(r), empty="No containers.", sort="state", descending=False)
        self.cttable.set_size_request(-1, 340)
        self.ct_tool = label("", "dim", hexpand=True)
        self.ct.append(hbox(self.ct_tool, button(icon="view-refresh-symbolic", on_click=self.load_containers)))
        self.ct.append(self.cttable)
        t = self.cttable
        self.ct.append(hbox(button("Start", on_click=lambda: self._table_sel(t, lambda r: self._ct("start", r))),
                            button("Stop", on_click=lambda: self._table_sel(t, lambda r: self._ct("stop", r))),
                            button("Restart", on_click=lambda: self._table_sel(t, lambda r: self._ct("restart", r))),
                            button("Logs", icon="text-x-generic-symbolic", on_click=lambda: self._table_sel(t, self._ct_logs)), spacer(),
                            button("Clean up unused…", css="flat", on_click=self._prune),
                            button("Remove", css="destructive-action", on_click=lambda: self._table_sel(t, lambda r: self._ct("rm", r))), spacing=6))

    def load_containers(self) -> None:
        tool = dev.container_tool()
        self.ct_tool.set_text(f"Using {tool}." if tool else "Neither Docker nor Podman is installed.")
        self.bg(dev.containers, self.show_containers)

    def show_containers(self, items: list[dict]) -> None:
        rows = [{"key": c["id"], "name": c["name"], "st": (c["state"], "ok" if c["state"] == "running" else "neutral"), "state": c["state"],
                 "image": c["image"], "ports": c["ports"], "status": c["status"], "id": c["id"]} for c in items]
        self.cttable.set_rows(rows)

    def _ct(self, action: str, r: dict) -> None:
        tool = dev.container_tool()
        args = [tool, action, *(["-f"] if action == "rm" else []), r["id"]]
        self.run(f"{action.title()} {r['name']}", [Step(f"{tool} {action} {r['name']}", args)],
                 "Removes the container (its image stays; data in volumes is kept)." if action == "rm" else "", danger=action == "rm",
                 ask=action == "rm", reload=False, done=lambda ok: self.load_containers())

    def _ct_logs(self, r: dict) -> None:
        from ...core.run import sh
        tool = dev.container_tool()
        self.bg(lambda: sh([tool, "logs", "--tail", "300", r["id"]], timeout=15), lambda res: self.text(f"Logs: {r['name']}", (res.out + res.err) or "No output."))

    def _prune(self) -> None:
        tool = dev.container_tool()
        if not tool:
            return
        self.run("Clean up containers", [Step("Remove stopped containers, unused networks and dangling images", [tool, "system", "prune", "-f"])],
                 "Your running containers, their images and named volumes are kept.", danger=True, ok_label="Clean up", reload=False,
                 done=lambda ok: self.load_containers())

    # ---------------------------------------------------------------- languages
    def load_langs(self) -> None:
        self.loading(self.langs, "Checking installed languages and tools…")
        self.bg(lambda: (dev.runtimes(), dev.node_versions(), dev.python_versions()), self.show_langs)

    def show_langs(self, res) -> None:
        rt, nodes, pys = res
        clear(self.langs)
        self.langs.append(group("Installed", "Versions found on your PATH (and in nvm).",
                                *[action_row(r["name"], f"{r['version']}  ·  {r['path']}") for r in rt] or [action_row("Nothing found", "")]))
        nrows = []
        for n in reversed(nodes):
            tags = [pill(t, "accent" if t == "default" else "info") for t in n["tags"]]
            btns = []
            if "default" not in n["tags"]:
                btns.append(button("Make default", css="flat", on_click=lambda v=n["version"]: self.run(
                    f"Make Node {v} the default", [Step("Set default", dev.nvm_cmd(f"alias default {v}"))],
                    "New terminals use this version. Running apps (like pm2 bots) keep theirs until restarted.", ok_label="Set", reload=False,
                    done=lambda ok: self.load_langs())))
            if not n["protected"]:
                btns.append(button(icon="user-trash-symbolic", css="flat", tooltip="Uninstall", on_click=lambda v=n["version"]: self.run(
                    f"Remove Node {v}", [Step("Uninstall", dev.nvm_cmd(f"uninstall {v}"))], danger=True, ok_label="Remove", reload=False,
                    done=lambda ok: self.load_langs())))
            nrows.append(action_row(f"Node {n['version']}", "", *tags, *btns))
        if (HOME / ".nvm/nvm.sh").exists():
            self.langs.append(group("Node versions (nvm)", "The default and the one pm2 uses are protected.", *nrows,
                                    suffix=button("Install latest LTS", css="flat", on_click=lambda: self.run(
                                        "Install Node LTS", [Step("Install latest Node LTS", dev.nvm_cmd("install --lts"))], "Your current versions stay installed.",
                                        ok_label="Install", reload=False, done=lambda ok: self.load_langs()))))
        if pys:
            self.langs.append(group("Python versions", "Installed with pyenv or uv. Ubuntu's own python3 is separate and never touched.",
                                    *[action_row(f"Python {p['version']}", p["manager"], *[pill(t, "accent") for t in p["tags"]]) for p in pys]))

    # ---------------------------------------------------------------- toolbox
    def show_tools(self) -> None:
        clear(self.tools)
        missing = [t for t in TOOLBOX if not which(t[0])]
        rows = []
        for cmd, pkg, name, what in TOOLBOX:
            have = which(cmd)
            rows.append(action_row(name, what + (f"  ·  {have.replace(str(HOME), '~')}" if have else ""),
                                   pill("installed", "ok") if have else button("Install", css="flat", on_click=lambda p=pkg, n=name: self.run(
                                       f"Install {n}", [Step(f"Install {n}", ["apt-get", "install", "-y", p], root=True, env=APT)], ok_label="Install",
                                       reload=False, done=lambda ok: self.show_tools()))))
        g = group("Command-line toolbox", f"{len(TOOLBOX) - len(missing)} of {len(TOOLBOX)} installed. All come from Ubuntu's repositories.", *rows,
                  suffix=button(f"Install all {len(missing)} missing", css="flat", on_click=lambda: self.run(
                      "Install missing tools", [Step("Install tools", ["apt-get", "install", "-y", *[t[1] for t in missing]], root=True, env=APT)],
                      ", ".join(t[2] for t in missing), ok_label="Install", reload=False, done=lambda ok: self.show_tools())) if missing else None)
        self.tools.append(g)
        self.tools.append(label("Caches these tools leave behind (npm, pip, cargo…) are on the Cleanup page.", "dim"))


PAGE = DevPage
