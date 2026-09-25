"""Developer: git projects (fetch all, unpushed work), running dev servers (stop all), pm2, containers with Docker disk
usage, language versions with a PATH doctor and uv Pythons, git + GitHub setup, global packages and a CLI toolbox."""

from __future__ import annotations

import os
import re

from gi.repository import Adw, GLib, Gtk

from ...core import dev, devsetup, maint, network, security
from ...core.desktop import run_quiet
from ...core.fmt import ago, duration, human
from ...core.run import HOME, Step, has, which
from ..util import (button, clear, esc, flow, hbox, label, launch, open_in_terminal, open_path, pill, spacer, status_icon,
                    vbox)
from ..widgets import Column, DataTable, card
from .base import Page, action_row, banner, group, switch_row, tabs
from .tweaks import combo_row, compact_tabs

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
MANAGER_KIND = {"npm": "accent", "pnpm": "accent", "pipx": "info", "uv": "info", "cargo": "warn", "go": "ok"}


def github_url(remote: str) -> str:
    m = re.match(r"(?:git@|https://)([^:/]+)[:/](.+?)(?:\.git)?$", remote.strip())
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


class DevPage(Page):
    ID = "dev"
    TITLE = "Developer"
    ICON = "utilities-terminal-symbolic"
    SUBTITLE = "Your projects, running dev servers, pm2 bots, containers, language versions, git and GitHub setup, and handy CLI tools."
    PALETTE = [("path", "PATH doctor: which node / python actually runs"), ("docker", "Docker disk usage and cleanup"),
               ("github", "GitHub connection and SSH key"), ("git", "Git name, email and defaults"), ("fetch", "Fetch all projects"),
               ("unpushed", "Projects with unpushed work"), ("stopall", "Stop all dev servers"),
               ("python", "Install a Python version (uv)"), ("globals", "Global packages: npm -g, pipx, uv tools, cargo")]

    def build(self) -> None:
        self.header()
        self.proj = vbox(spacing=10)
        self.srv = vbox(spacing=10)
        self.pm2 = vbox(spacing=10)
        self.ct = vbox(spacing=14)
        self.langs = vbox(spacing=18)
        self.git = vbox(spacing=18)
        self.tools = vbox(spacing=14)
        sw, self.stack = tabs(("proj", "Projects", "folder-symbolic", self.proj), ("srv", "Servers", "network-server-symbolic", self.srv),
                              ("ct", "Containers", "package-x-generic-symbolic", self.ct),
                              ("langs", "Languages", "applications-engineering-symbolic", self.langs),
                              ("git", "Git", "emblem-shared-symbolic", self.git),
                              ("tools", "Tools", "applications-utilities-symbolic", self.tools))
        self.body.append(sw)
        self.body.append(self.stack)
        compact_tabs(self, sw, 6)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self.repos: list[dict] = []
        self.globals: dict = {"items": [], "managers": {}}
        self.outdated: dict[str, dict] = {}
        self._pending: str | None = None
        self._build_projects()
        self._build_servers()
        self._build_pm2()
        self.srv.append(self.pm2)
        self._build_containers()
        self._build_tools()

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        {"proj": self.load_projects, "srv": lambda: (self.load_servers(), self.load_pm2()), "ct": self.load_containers, "langs": self.load_langs,
         "git": self.load_git, "tools": self.load_tools}[name]()

    def palette_action(self, key: str) -> None:
        tab = {"path": "langs", "python": "langs", "docker": "ct", "github": "git", "git": "git", "fetch": "proj", "unpushed": "proj",
               "stopall": "srv", "globals": "tools"}.get(key)
        if not tab:
            return
        self.stack.set_visible_child_name(tab)
        if key == "unpushed":
            self.attn_btn.set_active(True)
        elif key == "fetch":
            if self.repos:
                self.fetch_all()
            else:
                self._pending = "fetch"
        elif key == "stopall":
            self._pending = "stopall"
            self.load_servers()

    def _table_sel(self, table: DataTable, fn) -> None:
        r = table.selected()
        if r:
            fn(r)
        else:
            self.toast("Select a row first.")

    def _quiet(self, title: str, steps: list[Step], done=None, ok_toast: str = "") -> None:
        """Small per-user changes (git config) run straight away without a dialog; still recorded in Activity history."""
        def fin(res) -> None:
            ok, lines = res
            try:
                from ..activity import record
                record(title, [s.display() for s in steps], ok, "" if ok else (lines[-1] if lines else ""), lines)
            except Exception:  # noqa: BLE001
                pass
            if not ok:
                self.toast(f"Couldn't change it: {lines[-1] if lines else 'unknown error'}", 5)
            elif ok_toast:
                self.toast(ok_toast)
            if done:
                done(ok)
        self.bg(lambda: run_quiet(steps), fin)

    # ---------------------------------------------------------------- projects
    def _build_projects(self) -> None:
        self.search_entry = Gtk.SearchEntry(placeholder_text="Find a project…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.ptable.set_filter(e.get_text()))
        self.proj_info = label("", "dim")
        self.attn_btn = Gtk.ToggleButton(label="Needs attention")
        self.attn_btn.set_tooltip_text("Only projects with uncommitted changes or work that isn't on GitHub yet")
        self.attn_btn.connect("toggled", lambda *_: self.show_projects(self.repos))
        self.proj.append(hbox(self.search_entry, self.attn_btn,
                              button("Fetch all", icon="emblem-synchronizing-symbolic", tooltip="Check every project for new commits on GitHub",
                                     on_click=self.fetch_all),
                              button(icon="view-refresh-symbolic", tooltip="Rescan", on_click=self.load_projects), spacing=6))
        self.proj_banner = vbox()
        self.proj.append(self.proj_banner)
        self.ptable = DataTable([
            Column("name", "Project", "bold", width=190),
            Column("branch", "Branch", "mono", width=120),
            Column("state", "Changes", "pill", width=110, sort="changes"),
            Column("sync", "Sync", "pill", width=130, sort="syncn"),
            Column("when", "Last commit", "muted", width=100, sort="last"),
            Column("msg", "Message", "text", expand=True),
        ], on_activate=lambda r: self._code(r), on_select=self._proj_selected, empty="No git projects found.", sort="last",
            search=lambda d, q: q in d["name"].lower() or q in d["path"].lower())
        self.ptable.set_size_request(-1, 380)
        self.proj.append(self.ptable)
        self.proj_detail = label("", "dim", wrap=True)
        self.proj.append(self.proj_detail)
        t = self.ptable
        self.proj.append(flow(
            button("VS Code", icon="accessories-text-editor-symbolic", css="suggested-action", on_click=lambda: self._table_sel(t, self._code)),
            button("Zed", on_click=lambda: self._table_sel(t, self._zed)),
            button("Terminal", icon="utilities-terminal-symbolic", on_click=lambda: self._table_sel(t, self._term)),
            button("lazygit", on_click=lambda: self._table_sel(t, lambda r: open_in_terminal(["lazygit", "-p", r["path"]]) if has("lazygit") else self.toast("lazygit isn't installed (Tools tab)."))),
            button("Pull", icon="go-down-symbolic", on_click=lambda: self._table_sel(t, self._pull)),
            button("Push", icon="go-up-symbolic", on_click=lambda: self._table_sel(t, self._push)),
            button(icon="web-browser-symbolic", css="flat", tooltip="Open on GitHub", on_click=lambda: self._table_sel(t, self._web)),
            button(icon="folder-open-symbolic", css="flat", tooltip="Open folder", on_click=lambda: self._table_sel(t, lambda r: open_path(r["path"]))),
            spacing=6, max_per_line=8))
        self.proj.append(label("Searching: " + ", ".join(str(p).replace(str(HOME), "~") for p in maint.project_roots()) +
                               ". Double-click opens a project in VS Code.", "dim", wrap=True))

    def load_projects(self) -> None:
        self.ptable.set_empty("Looking for git projects…")
        self.bg(lambda: dev.repos_full(maint.project_roots()), self._got_projects)

    def _got_projects(self, repos: list[dict]) -> None:
        self.repos = repos
        self.show_projects(repos)
        if self._pending == "fetch":
            self._pending = None
            self.fetch_all()

    def show_projects(self, repos: list[dict]) -> None:
        rows = []
        dirty = unpushed = 0
        only = self.attn_btn.get_active()
        for r in repos:
            changes = r["changed"] + r["untracked"]
            dirty += bool(changes)
            unpushed += any(k == "warn" and ("push" in t or "isn't on the remote" in t) for k, t in r.get("attention", []))
            if only and not r.get("needs_you"):
                continue
            sync = []
            if r["ahead"]:
                sync.append(f"↑{r['ahead']} to push")
            if r["behind"]:
                sync.append(f"↓{r['behind']} to pull")
            if sync:
                sync_pill = (" ".join(sync), "warn")
            elif not r["remote"]:
                sync_pill = ("no remote", "neutral")
            elif not r["upstream"]:
                sync_pill = ("not on remote", "warn")
            else:
                sync_pill = ("in sync", "ok")
            rows.append({"key": r["path"], "name": r["name"], "branch": r["branch"], "changes": changes,
                         "state": (f"{changes} changed", "warn") if changes else ("clean", "ok"), "sync": sync_pill, "syncn": r["ahead"] + r["behind"],
                         "last": r["last_commit"], "when": ago(r["last_commit"]) if r["last_commit"] else "-", "msg": r["message"],
                         "path": r["path"], "remote": r["remote"], "attention": r.get("attention", []), "upstream": r["upstream"]})
        self.ptable.set_rows(rows)
        self.ptable.set_empty("Every project is committed and pushed." if only else "No git projects found in your project folders.")
        self.proj_info.set_text(f"{len(repos)} projects")
        clear(self.proj_banner)
        if unpushed and not only:
            self.proj_banner.append(banner(f"{unpushed} project{'s have' if unpushed != 1 else ' has'} work that isn't on GitHub yet - if this "
                                           "laptop died today, it would be lost.", "warn",
                                           button("Show them", css="flat", on_click=lambda: self.attn_btn.set_active(True))))
        elif dirty and not only:
            self.proj_info.set_text(f"{len(repos)} projects · {dirty} with uncommitted changes")

    def _proj_selected(self, r: dict | None) -> None:
        if not r:
            self.proj_detail.set_text("")
            return
        att = r.get("attention") or []
        self.proj_detail.set_text(f"{r['name']}: " + ("; ".join(t for _, t in att) if att else "all committed and pushed.") +
                                  (f"  ·  {r['remote']}" if r["remote"] else ""))

    def fetch_all(self) -> None:
        steps = dev.fetch_all_steps(self.repos)
        if not steps:
            self.toast("No projects with a remote to fetch.")
            return
        self.run(f"Fetch {len(steps)} projects", steps,
                 "Downloads news from GitHub (new commits and branches) for every project. It never changes your files or branches, and "
                 "never asks for a password - projects that would need one are skipped.", ok_label="Fetch all", reload=False,
                 done=lambda ok: self.load_projects())

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
        self.run(f"Pull {r['name']}", [Step("Get the latest changes", ["git", "-C", r["path"], "pull", "--ff-only"], env=dev.FETCH_ENV)],
                 "Only fast-forwards: never creates merge commits or touches your uncommitted changes.", ok_label="Pull", reload=False,
                 done=lambda ok: self.load_projects())

    def _push(self, r: dict) -> None:
        if not r["remote"]:
            self.toast("This project has no remote to push to. Create a repo on GitHub first (gh repo create).", 5)
            return
        cmd = ["git", "-C", r["path"], "push"] + ([] if r["upstream"] else ["-u", "origin", "HEAD"])
        self.run(f"Push {r['name']}", [Step("Send your commits to the remote", cmd, env=dev.FETCH_ENV)],
                 "Uploads the commits of the current branch. Uncommitted changes stay on this PC - commit them first.", ok_label="Push",
                 reload=False, done=lambda ok: self.load_projects())

    def _web(self, r: dict) -> None:
        url = github_url(r["remote"])
        launch(["xdg-open", url]) if url else self.toast("This project has no remote.")

    # ---------------------------------------------------------------- dev servers
    def _build_servers(self) -> None:
        self.stable = DataTable([
            Column("port", "Port", "bold", width=70),
            Column("kind", "Kind", "pill", width=100),
            Column("process", "Process", "text", width=130),
            Column("reach", "Reachable from", "pill", width=140),
            Column("url", "Address", "mono", width=170),
            Column("cmd", "Command", "mono", expand=True),
        ], on_activate=lambda r: launch(["xdg-open", r["url"]]), empty="No dev servers running.", sort="port", descending=False)
        self.stable.set_size_request(-1, 280)
        self.srv.append(hbox(label("Dev servers", "section-title"), label("Programs of yours listening on a port (npm run dev, Django, Vite…).", "dim",
                                                                          hexpand=True, wrap=True),
                             button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_servers)))
        self.srv.append(self.stable)
        t = self.stable
        self.srv.append(flow(button("Open in browser", icon="web-browser-symbolic", css="suggested-action", on_click=lambda: self._table_sel(t, lambda r: launch(["xdg-open", r["url"]]))),
                             button("Test on your phone…", on_click=lambda: self._table_sel(t, self._phone)),
                             button("Stop", icon="process-stop-symbolic", on_click=lambda: self._table_sel(t, self._stop_srv)),
                             button("Stop all dev servers", icon="process-stop-symbolic", css="destructive-action", on_click=self.stop_all),
                             spacing=6, max_per_line=4))

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
        if self._pending == "stopall":
            self._pending = None
            self.stop_all()

    def _stop_srv(self, r: dict) -> None:
        self.run(f"Stop {r['process']} on port {r['port']}", [Step(f"Stop process {r['pid']}", ["kill", str(r["pid"])])], ask=False, reload=False,
                 done=lambda ok: self.load_servers())

    def stop_all(self) -> None:
        rows = self.stable.rows()

        def work():
            return dev.stop_targets(rows)

        def go(res) -> None:
            stop, skipped = res
            if not stop:
                self.toast("No dev servers to stop." + (f" ({len(skipped)} other listening programs were left alone.)" if skipped else ""), 5)
                return
            explain = "Asks each one to shut down cleanly (like pressing Ctrl+C in its terminal)."
            if skipped:
                explain += "\n\nLeft alone: " + ", ".join(f"{s['process']} :{s['port']} ({s['why']})" for s in skipped[:6]) + \
                           (" - pm2 apps restart themselves - stop them in the pm2 list below." if any(s["why"] == "managed by pm2" for s in skipped) else "")
            self.run(f"Stop {len(stop)} dev server{'s' if len(stop) != 1 else ''}", dev.stop_steps(stop), explain, danger=True,
                     ok_label="Stop all", reload=False, done=lambda ok: GLib.timeout_add(1500, lambda: (self._after_stop(stop), False)[1]))
        self.bg(work, go)

    def _after_stop(self, stop: list[dict]) -> None:
        def fin(alive: list[int]) -> None:
            self.load_servers()
            if not alive:
                self.toast(f"Stopped {len(stop)} dev server{'s' if len(stop) != 1 else ''}.")
                return
            left = [s for s in stop if s["pid"] in alive]
            d = Adw.AlertDialog(heading=f"{len(left)} didn't stop", body="These ignored the polite request: " +
                                ", ".join(f"{s['process']} on port {s['port']}" for s in left) + ". Force-stop them? Unsaved work in them is lost.")
            d.add_response("cancel", "Leave them")
            d.add_response("force", "Force stop")
            d.set_response_appearance("force", Adw.ResponseAppearance.DESTRUCTIVE)
            d.connect("response", lambda _d, r: r == "force" and self.run("Force-stop dev servers", dev.stop_steps(left, force=True), ask=False,
                                                                          reload=False, done=lambda ok: self.load_servers()))
            d.present(self.win)
        self.bg(lambda: dev.still_running([s["pid"] for s in stop]), fin)

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
        self.pm2table.set_size_request(-1, 240)
        self.pm2.set_margin_top(12)
        self.pm2.append(hbox(label("pm2", "section-title"), label("Node apps and bots kept alive by pm2 (they restart by themselves if stopped here).", "dim",
                                                                  hexpand=True, wrap=True),
                             button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_pm2)))
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

    # ---------------------------------------------------------------- containers + docker disk usage
    def _build_containers(self) -> None:
        self.disk_box = vbox(spacing=12)
        self.ct.append(self.disk_box)
        self.cttable = DataTable([
            Column("name", "Container", "bold", width=190),
            Column("st", "State", "pill", width=100, sort="state"),
            Column("image", "Image", "mono", expand=True),
            Column("ports", "Ports", "mono", width=150),
            Column("status", "Status", "muted", width=150),
        ], on_activate=lambda r: self._ct_logs(r), empty="No containers.", sort="state", descending=False)
        self.cttable.set_size_request(-1, 300)
        self.ct_tool = label("", "dim", hexpand=True, wrap=True)
        self.ct.append(hbox(label("Containers", "section-title"), self.ct_tool, button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_containers)))
        self.ct.append(self.cttable)
        t = self.cttable
        self.ct.append(flow(button("Start", on_click=lambda: self._table_sel(t, lambda r: self._ct("start", r))),
                            button("Stop", on_click=lambda: self._table_sel(t, lambda r: self._ct("stop", r))),
                            button("Restart", on_click=lambda: self._table_sel(t, lambda r: self._ct("restart", r))),
                            button("Logs", icon="text-x-generic-symbolic", on_click=lambda: self._table_sel(t, self._ct_logs)),
                            button("Remove", css="destructive-action", on_click=lambda: self._table_sel(t, lambda r: self._ct("rm", r))),
                            spacing=6, max_per_line=5))

    def load_containers(self) -> None:
        tool = dev.container_tool()
        self.ct_tool.set_text(f"Using {tool}." if tool else "Neither Docker nor Podman is installed.")
        self.bg(dev.containers, self.show_containers)
        self.loading(self.disk_box, "Measuring Docker's disk usage…")
        self.bg(dev.docker_disk, self.show_disk)

    def show_containers(self, items: list[dict]) -> None:
        rows = [{"key": c["id"], "name": c["name"], "st": (c["state"], "ok" if c["state"] == "running" else "neutral"), "state": c["state"],
                 "image": c["image"], "ports": c["ports"], "status": c["status"], "id": c["id"]} for c in items]
        self.cttable.set_rows(rows)

    def show_disk(self, d: dict) -> None:
        clear(self.disk_box)
        prob = d["problem"]
        if prob:
            steps, why = dev.docker_fix_steps(prob)
            text = {"missing": "Docker isn't installed. Install it to run databases and other services for your projects in containers.",
                    "permission": "Docker is installed, but your account isn't allowed to use it (you're not in the “docker” group).",
                    "stopped": "Docker is installed but its background service isn't running.",
                    "error": f"Docker didn't answer: {d['message']}"}[prob]
            btns = [button({"missing": "Install Docker", "permission": "Fix it", "stopped": "Start Docker"}[prob], css="suggested-action",
                           on_click=lambda: self.run(steps[0].title, steps, why, ok_label="Go", reload=False, done=lambda ok: ok and self.load_containers()))] if steps else []
            self.disk_box.append(banner(text, "info" if prob == "missing" else "warn", *btns))
            return
        total = sum(s["size"] for s in d["summary"])
        rec = sum(s["reclaimable"] for s in d["summary"])
        self.disk_box.append(hbox(label("Disk usage", "section-title"), label(f"{human(total)} used by {d['tool']} · {human(rec)} can be freed", "dim",
                                                                              hexpand=True, wrap=True)))
        tiles = []
        hints = {"images": "Downloaded base images", "containers": "Writable layers of containers", "volumes": "Saved data (databases…)",
                 "cache": "Leftovers from docker build"}
        for s in d["summary"]:
            btn = button("Clean up…", css="flat", on_click=lambda k=s["type"]: self._prune(k, d["tool"]))
            btn.set_sensitive(s["reclaimable"] > 0 or s["type"] == "cache" and s["size"] > 0)
            tiles.append(card(label(s["label"].upper(), "tile-title"), label(human(s["size"]), "mid-num"),
                              label(f"{s['count']} total · {s['active']} in use", "dim"),
                              label(f"{human(s['reclaimable'])} can be freed", "ok-text" if s["reclaimable"] else "dim"),
                              label(hints.get(s["type"], ""), "dim", wrap=True), btn, spacing=4))
        if tiles:
            self.disk_box.append(flow(*tiles, spacing=10, min_per_line=2, max_per_line=4, homogeneous=True))
        rows = []
        unused = [i for i in d["images"] if not i["used_by"]]
        if unused:
            ex = Adw.ExpanderRow(title=esc(f"Unused images ({len(unused)})"),
                                 subtitle=esc(f"{human(sum(i['unique'] for i in unused))} · no container uses them; they download again when needed"))
            for i in sorted(unused, key=lambda x: -x["size"])[:40]:
                ex.add_row(action_row(i["name"], f"{human(i['size'])} · {i['age']}" if i["age"] else human(i["size"]),
                                      button(icon="user-trash-symbolic", css="flat", tooltip="Remove this image",
                                             on_click=lambda ii=i: self._rm("images", ii, d["tool"]))))
            rows.append(ex)
        stopped = [c for c in d["containers"] if not c["running"]]
        if stopped:
            ex = Adw.ExpanderRow(title=esc(f"Stopped containers ({len(stopped)})"), subtitle=esc("Not running. Removing one keeps its image."))
            for c in stopped[:40]:
                ex.add_row(action_row(c["name"], f"{c['image']} · {c['status']}" + (f" · {human(c['size'])}" if c["size"] else ""),
                                      button(icon="user-trash-symbolic", css="flat", tooltip="Remove this container",
                                             on_click=lambda cc=c: self._rm("containers", cc, d["tool"]))))
            rows.append(ex)
        if d["volumes"]:
            ex = Adw.ExpanderRow(title=esc(f"Volumes ({len(d['volumes'])})"),
                                 subtitle=esc("Where containers keep data such as databases. Deleting one deletes that data for good."))
            for v in sorted(d["volumes"], key=lambda x: -x["size"])[:40]:
                ex.add_row(action_row(v["name"][:48] + ("…" if len(v["name"]) > 48 else ""),
                                      f"{human(v['size'])} · " + ("used by a container" if v["links"] else "not used by any container") +
                                      (" · unnamed" if v["anonymous"] else ""),
                                      button(icon="user-trash-symbolic", css="flat", tooltip="Delete this volume",
                                             on_click=lambda vv=v: self._rm("volumes", vv, d["tool"]))))
            rows.append(ex)
        if rows:
            self.disk_box.append(group("", "", *rows))

    def _prune(self, kind: str, tool: str) -> None:
        steps, why, danger = dev.docker_prune_steps(kind, tool)
        self.run(steps[0].title, steps, why, danger=danger, ok_label="Clean up", reload=False, done=lambda ok: self.load_containers())

    def _rm(self, kind: str, item: dict, tool: str) -> None:
        steps = dev.docker_remove_steps(kind, item, tool)
        why = {"images": "The image downloads again the next time something needs it.", "containers": "Its image stays.",
               "volumes": "Everything stored in this volume (for example a database) is deleted and can't be recovered."}[kind]
        self.run(steps[0].title, steps, why, danger=kind == "volumes", ok_label="Remove", reload=False, done=lambda ok: self.load_containers())

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

    # ---------------------------------------------------------------- languages, PATH doctor, uv Pythons
    def load_langs(self) -> None:
        self.loading(self.langs, "Checking installed languages and tools…")
        self.bg(lambda: (dev.runtimes(), dev.node_versions(), dev.python_versions(), devsetup.uv_pythons()), self.show_langs)

    def show_langs(self, res) -> None:
        rt, nodes, pys, uvp = res
        clear(self.langs)
        self.path_box = vbox(spacing=12)
        self.langs.append(self.path_box)
        self.load_path()
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
        self.langs.append(self._uv_group(uvp))
        pyenv = [p for p in pys if p["manager"] == "pyenv"]
        if pyenv:
            self.langs.append(group("Python versions (pyenv)", "", *[action_row(f"Python {p['version']}", p["manager"], *[pill(t, "accent") for t in p["tags"]])
                                                                      for p in pyenv]))

    def _uv_group(self, u: dict) -> Adw.PreferencesGroup:
        desc = ("uv downloads ready-made Pythons into your home folder, side by side, without touching Ubuntu's own python3 "
                "(which system tools need). Projects pick their version with uv venv / uv run.")
        if not u["uv"]:
            steps = devsetup.uv_install_steps()
            how = "with pipx" if steps[0].cmd[0] == "pipx" else "with uv's official installer from astral.sh (it puts one program in ~/.local/bin)"
            return group("Python versions (uv)", desc, action_row("uv isn't installed", f"uv is the fast, modern Python tool: versions, "
                                                                  f"virtual environments and packages in one. Installs {how}.",
                                                                  button("Install uv", css="suggested-action", on_click=lambda: self.run(
                                                                      "Install uv", steps, "Installs for your account only - no password needed.",
                                                                      ok_label="Install", reload=False, done=lambda ok: self.load_langs()))))
        rows = []
        pin = u["global_pin"]
        for p in u["installed"]:
            tags = []
            sub = p["path"].replace(str(HOME), "~")
            if p["system"]:
                tags.append(pill("Ubuntu's", "neutral"))
            if pin and p["version"].startswith(pin):
                tags.append(pill("default for new projects", "accent"))
            btns = []
            if u["pin_global"] and not (pin and p["version"].startswith(pin)):
                btns.append(button("Use for new projects", css="flat", on_click=lambda m=p["minor"]: self.run(
                    f"Use Python {m} for new projects", devsetup.uv_python_pin(m), "uv uses this version when a project doesn't ask for a specific one. "
                    "Ubuntu's python3 command doesn't change.", ok_label="Set", reload=False, done=lambda ok: self.load_langs())))
            if p["managed"]:
                btns.append(button(icon="user-trash-symbolic", css="flat", tooltip="Remove", on_click=lambda v=p["version"]: self.run(
                    f"Remove Python {v}", devsetup.uv_python_uninstall(v), "Projects that use this version will download it again when needed.",
                    danger=True, ok_label="Remove", reload=False, done=lambda ok: self.load_langs())))
            rows.append(action_row(f"Python {p['version']}", sub, *tags, *btns))
        avail = [a for a in u["available"]][:6]
        if avail:
            combo = combo_row("Install another version", "Downloads in a few seconds; nothing else changes.",
                              [f"Python {a['minor']} (latest {a['version']})" for a in avail])
            inst = button("Install", css="suggested-action", on_click=lambda: self.run(
                f"Install Python {avail[combo.get_selected()]['minor']}", devsetup.uv_python_install(avail[combo.get_selected()]["minor"]),
                "Stored in ~/.local/share/uv/python. Remove it here any time.", ok_label="Install", reload=False, done=lambda ok: self.load_langs()))
            inst.set_valign(Gtk.Align.CENTER)
            combo.add_suffix(inst)
            rows.append(combo)
        return group("Python versions (uv)", desc, *rows or [action_row("No Pythons found", "")])

    def load_path(self) -> None:
        self.loading(self.path_box, "PATH doctor: opening a login shell to see what your terminal sees…")
        self.bg(devsetup.path_doctor, self.show_path)

    def show_path(self, rep: dict) -> None:
        clear(self.path_box)
        rows = []
        for level, text in rep["tips"]:
            r = Adw.ActionRow(title=esc(text))
            r.set_title_lines(0)
            r.add_prefix(status_icon(level))
            rows.append(r)
        self.path_box.append(group("PATH doctor", f"PATH is the list of folders your {rep['shell']} terminal searches for commands, in order. "
                                                  "The first match wins.", *rows,
                                   suffix=button(icon="view-refresh-symbolic", css="flat", tooltip="Check again", on_click=self.load_path)))
        ex = Adw.ExpanderRow(title="Which version runs?", subtitle="Every copy of common tools on your PATH. The first one is what you get.")
        for t in rep["tools"]:
            if not t["copies"]:
                continue
            win = t["copies"][0]
            sub = win["shown"] + (f"  ({win['version']})" if win["version"] else "")
            if len(t["copies"]) > 1:
                sub += "\nhidden: " + ", ".join(c["shown"] + (f" ({c['version']})" if c["version"] else "") for c in t["copies"][1:])
            row = Adw.ActionRow(title=esc(t["name"]), subtitle=esc(sub))
            row.set_subtitle_lines(4)
            if len(t["copies"]) > 1:
                row.add_suffix(pill(f"{len(t['copies'])} copies", "warn" if len({c['version'] for c in t['copies']}) > 1 else "neutral"))
            ex.add_row(row)
        ex2 = Adw.ExpanderRow(title="Your PATH, in order", subtitle=esc(f"{len(rep['entries'])} folders"))
        for e in rep["entries"]:
            tags = []
            if e["dup_of"] is not None:
                tags.append(pill("duplicate", "neutral"))
            elif e["relative"]:
                tags.append(pill("unsafe", "bad"))
            elif not e["exists"]:
                tags.append(pill("missing", "warn"))
            if e["dir"] in rep["terminal_only"]:
                tags.append(pill("terminal only", "info"))
            ex2.add_row(action_row(f"{e['index'] + 1}. {e['shown']}", "", *tags))
        copy = button("Copy PATH", icon="edit-copy-symbolic", css="flat", on_click=lambda: (self.get_clipboard().set(rep["path"]), self.toast("Copied.")))
        self.path_box.append(group("", "", ex, ex2))
        self.path_box.append(hbox(label("Change PATH in ~/.zshrc (or ~/.bashrc) and open a new terminal.", "dim", hexpand=True, wrap=True), copy))

    # ---------------------------------------------------------------- git & GitHub
    def load_git(self) -> None:
        self.loading(self.git, "Checking git and your GitHub connection…")
        self.bg(lambda: (devsetup.git_config(), devsetup.gh_status(), devsetup.ssh_keys(), has("git")), self.show_git)

    def show_git(self, res) -> None:
        cfg, gh, keys, have_git = res
        self.cfg, self.gh, self.keys = cfg, gh, keys
        clear(self.git)
        if not have_git:
            self.git.append(banner("Git isn't installed.", "warn", button("Install git", css="suggested-action", on_click=lambda: self.run(
                "Install git", [Step("Install git", ["apt-get", "install", "-y", "git"], root=True, env=APT)], ok_label="Install", reload=False,
                done=lambda ok: self.load_git()))))
            return
        self.git.append(self._github_group(gh, keys))
        self.git.append(self._keys_group(keys, gh))
        self.git.append(self._identity_group(cfg, gh))
        self.git.append(self._defaults_group(cfg))
        self.git.append(self._signing_group(cfg, keys))

    def _github_group(self, gh: dict, keys: list) -> Adw.PreferencesGroup:
        rows = []
        if not gh["installed"]:
            rows.append(action_row("GitHub CLI (gh) isn't installed", "gh logs you in to GitHub once, then git, pull requests and uploads just work.",
                                   button("Install gh", css="suggested-action", on_click=lambda: self.run(
                                       "Install GitHub CLI", [Step("Install gh", ["apt-get", "install", "-y", "gh"], root=True, env=APT)], ok_label="Install",
                                       reload=False, done=lambda ok: self.load_git())), prefix=status_icon("info")))
        elif gh["logged_in"]:
            extra = []
            if gh["protocol"]:
                extra.append(f"git uses {gh['protocol'].upper()}")
            if gh["scopes"]:
                extra.append("permissions: " + ", ".join(gh["scopes"]))
            rows.append(action_row(f"Logged in as {gh['account']}", " · ".join(extra) or "github.com", prefix=status_icon("ok")))
        else:
            rows.append(action_row(gh["error"] or "Not logged in to GitHub", "Opens a terminal: pick GitHub.com, then “Login with a web browser”.",
                                   button("Log in…", css="suggested-action", on_click=self._gh_login), prefix=status_icon("warn")))
        self.ssh_icon = status_icon("info")
        self.ssh_row = action_row("SSH connection to GitHub", "Tests whether git can talk to GitHub with your SSH key (git@github.com:… addresses).",
                                  button("Test", on_click=self._ssh_test), prefix=self.ssh_icon)
        rows.append(self.ssh_row)
        return group("GitHub connection", "", *rows)

    def _gh_login(self) -> None:
        if not open_in_terminal(["gh", "auth", "login", "--hostname", "github.com"]):
            self.toast("No terminal found. Run: gh auth login")
        else:
            self.toast("Finish logging in in the terminal, then press refresh here.", 6)

    def _ssh_test(self) -> None:
        self.ssh_row.set_subtitle("Connecting to github.com…")

        def show(r: dict) -> None:
            self.ssh_row.set_subtitle(esc(r["message"]))
            lvl = "ok" if r["ok"] else "warn"
            self.ssh_icon.set_from_icon_name("emblem-ok-symbolic" if r["ok"] else "dialog-warning-symbolic")
            for c in ("lvl-ok", "lvl-warn", "lvl-info", "lvl-bad"):
                self.ssh_icon.remove_css_class(c)
            self.ssh_icon.add_css_class(f"lvl-{lvl}")
        self.bg(devsetup.ssh_test, show)

    def _keys_group(self, keys: list, gh: dict) -> Adw.PreferencesGroup:
        rows = []
        for k in keys:
            sub = f"{k.kind}" + (f" · {k.comment}" if k.comment else "") + ("" if k.private else " · private half missing")
            btns = [button(icon="edit-copy-symbolic", css="flat", tooltip="Copy the public key (safe to share)", on_click=lambda kk=k: self._copy_key(kk))]
            if gh.get("logged_in"):
                btns.append(button("Upload to GitHub", css="flat", on_click=lambda kk=k: self._upload_key(kk)))
            rows.append(action_row(os.path.basename(k.path), sub, *btns))
        have_default = (HOME / ".ssh/id_ed25519").exists()
        if not keys:
            rows.append(action_row("No SSH keys yet", "An SSH key is like a password that never leaves this PC. GitHub uses it to know it's you.",
                                   prefix=status_icon("info")))
        suffix = None if have_default else button("Create an SSH key…", icon="list-add-symbolic", css="flat", on_click=self._create_key)
        return group("SSH keys", "The .pub half is public - copy or upload it freely. Never share the file without .pub.", *rows, suffix=suffix)

    def _copy_key(self, k) -> None:
        from ...core.run import read
        self.get_clipboard().set(read(k.path).strip())
        self.toast("Public key copied - paste it into GitHub → Settings → SSH keys.", 5)

    def _upload_key(self, k) -> None:
        steps = devsetup.upload_key_steps(k.path)
        if devsetup.needs_key_scope(self.gh.get("scopes", [])):
            cmd = ["bash", "-c", "gh auth refresh -h github.com -s admin:public_key && " + " ".join(GLib.shell_quote(c) for c in steps[0].cmd)]
            open_in_terminal(cmd)
            self.toast("gh needs one more permission to upload keys - approve it in the terminal.", 6)
            return
        self.run("Upload SSH key to GitHub", steps, "Adds this PC's public key to your GitHub account, so git over SSH works without passwords.",
                 ok_label="Upload", reload=False, done=lambda ok: ok and self._ssh_test())

    def _create_key(self) -> None:
        email = devsetup.gget(self.cfg, "user.email")
        d = Adw.AlertDialog(heading="Create an SSH key",
                            body="A passphrase protects the key if someone copies your files. Ubuntu remembers it after you type it once per login.\n\n"
                                 "Without one, anyone with your home folder could use the key - fine for most personal laptops with disk encryption.")
        d.add_response("cancel", "Cancel")
        d.add_response("pass", "With a passphrase…")
        d.add_response("nopass", "Without passphrase")
        d.set_response_appearance("nopass", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r: str) -> None:
            if r == "nopass":
                self.run("Create an SSH key", devsetup.keygen_steps(email), "Makes ~/.ssh/id_ed25519 (private) and id_ed25519.pub (public).",
                         ok_label="Create", reload=False, done=lambda ok: self.load_git())
            elif r == "pass":
                if not open_in_terminal(["bash", "-c", "mkdir -p ~/.ssh && chmod 700 ~/.ssh && " +
                                         " ".join(GLib.shell_quote(c) for c in devsetup.keygen_cmd(email, passphrase=True))]):
                    self.toast("No terminal found.")
                else:
                    self.toast("Type your passphrase in the terminal, then press refresh here.", 6)
        d.connect("response", resp)
        d.present(self.win)

    def _entry(self, title: str, value: str, key: str, check=None) -> Adw.EntryRow:
        row = Adw.EntryRow(title=esc(title))
        row.set_text(value)
        row.set_show_apply_button(True)

        def apply(r) -> None:
            v = r.get_text().strip()
            if check:
                problem = check(v)
                if problem:
                    self.toast(problem, 5)
                    return
            self._quiet(f"git: {title}", [devsetup.git_set(key, v)], ok_toast=f"Saved: {title}")
        row.connect("apply", apply)
        return row

    def _identity_group(self, cfg: dict, gh: dict) -> Adw.PreferencesGroup:
        name = self._entry("Your name (shown on commits)", devsetup.gget(cfg, "user.name"), "user.name", lambda v: "" if v else "Type your name.")
        mail = self._entry("Email (shown on commits)", devsetup.gget(cfg, "user.email"), "user.email",
                           lambda v: "" if re.fullmatch(r"[^@\s]+@[^@\s]+", v) else "That doesn't look like an email address.")
        rows = [name, mail]
        if gh.get("logged_in"):
            def private() -> None:
                from ...core.run import out
                self.bg(lambda: out(devsetup.private_email_cmd(), timeout=15).strip('"'),
                        lambda e: (mail.set_text(e), self.toast("Press ✓ to save it.")) if e else self.toast("Couldn't ask GitHub for it."))
            rows.append(action_row("Keep your real email private", "GitHub gives you a no-reply address that still links commits to your profile.",
                                   button("Use my private GitHub email", css="flat", on_click=private)))
        return group("Who you are", "Git stamps this on every commit. Use the email of your GitHub account so commits show your profile. "
                                    "Press ✓ to save.", *rows)

    def _defaults_group(self, cfg: dict) -> Adw.PreferencesGroup:
        rows = []
        cur = devsetup.pull_mode(cfg)
        ids = [m[0] for m in devsetup.PULL_MODES]
        pull = combo_row("When you pull and both sides changed", "How git combines GitHub's new commits with yours.",
                         [m[1] for m in devsetup.PULL_MODES] + ([] if cur else ["Not set (git asks every time)"]))
        pull.set_selected(ids.index(cur) if cur in ids else len(ids))
        pull.set_subtitle(devsetup.PULL_MODES[ids.index(cur)][2] if cur in ids else "Not set: git prints a warning and asks you to choose.")

        def pick_pull(r, _p) -> None:
            i = r.get_selected()
            if i < len(ids) and ids[i] != devsetup.pull_mode(self.cfg):
                r.set_subtitle(devsetup.PULL_MODES[i][2])
                self._quiet(f"git pull: {devsetup.PULL_MODES[i][1]}", devsetup.pull_steps(ids[i]), done=lambda ok: ok and self._refresh_cfg())
        pull.connect("notify::selected", pick_pull)
        rows.append(pull)
        eds = devsetup.editors()
        cur_ed = devsetup.gget(cfg, "core.editor")
        labels = [e[0] for e in eds]
        vals = [e[1] for e in eds]
        if cur_ed and cur_ed not in vals:
            labels.append(f"{cur_ed} (current)")
            vals.append(cur_ed)
        if not cur_ed:
            labels.append("Not set (git uses nano or vi)")
            vals.append("")
        if eds:
            ed = combo_row("Editor for commit messages", "Opens when git needs you to write something (merge messages, rebase).", labels)
            ed.set_selected(vals.index(cur_ed) if cur_ed in vals else len(vals) - 1)
            ed.connect("notify::selected", lambda r, _p: vals[r.get_selected()] and vals[r.get_selected()] != devsetup.gget(self.cfg, "core.editor") and self._quiet(
                "git editor", [devsetup.git_set("core.editor", vals[r.get_selected()])], done=lambda ok: ok and self._refresh_cfg()))
            rows.append(ed)
        helper = devsetup.credential_helper(cfg)
        cred_sub = {"gh": "GitHub CLI handles it - nothing to type for github.com.", "cache": "Remembered for a while, then asked again.",
                    "store": "Saved in a plain-text file (~/.git-credentials) - works, but anyone with your files can read it.",
                    "libsecret": "Kept in GNOME's password keyring.", "": "Not set: git asks for your username and token on every push over HTTPS."}
        btn = None
        if has("gh") and helper != "gh":
            btn = button("Let GitHub CLI handle it", css="flat", on_click=lambda: self.run(
                "Use GitHub CLI for git passwords", [Step("Set up gh as git's password helper", ["gh", "auth", "setup-git"])],
                "Pushing and pulling over HTTPS to GitHub stops asking for passwords (uses your gh login).", ok_label="Set up", reload=False,
                done=lambda ok: ok and self.load_git()))
        rows.append(action_row("Passwords for HTTPS remotes", cred_sub.get(helper, f"Using: {helper}"), *([btn] if btn else [])))
        for key, want, title, why in devsetup.GIT_SWITCHES:
            on = devsetup.gget(cfg, key).lower() == want.lower()

            def change(v: bool, settle, k=key, w=want, t=title) -> None:
                self._quiet(f"git: {t}", [devsetup.git_set(k, w if v else None)], done=settle)
            rows.append(switch_row(title, why, on, change))
        return group("Handy defaults", "Settings for every project on this PC (git config --global). Take effect immediately.", *rows)

    def _refresh_cfg(self) -> None:
        self.bg(devsetup.git_config, lambda c: setattr(self, "cfg", c))

    def _signing_group(self, cfg: dict, keys: list) -> Adw.PreferencesGroup:
        st = devsetup.signing_state(cfg)
        pubs = [k.path for k in keys if k.private]
        exp = Adw.ExpanderRow(title="Sign your commits (advanced)",
                              subtitle=esc("GitHub shows a green “Verified” badge on signed commits. Uses your SSH key - no GPG needed."))
        if not pubs:
            exp.add_row(action_row("Create an SSH key first", "Signing uses the same key as the SSH connection above."))
            return group("", "", exp)
        key = st["key"] if st["key"] in pubs else pubs[0]

        def change(v: bool, settle) -> None:
            steps = devsetup.signing_steps(key, v)
            if v and self.gh.get("logged_in"):
                steps += devsetup.upload_key_steps(key, signing=True)
                for s in steps[-1:]:
                    s.optional = True
            self.run("Sign commits" if v else "Stop signing commits", steps,
                     f"Every new commit is signed with {key.replace(str(HOME), '~')}." + (" The key is also added to GitHub as a signing key, so "
                                                                                           "commits show as Verified." if v and self.gh.get("logged_in") else ""),
                     ok_label="Turn on" if v else "Turn off", reload=False, done=lambda ok: (settle(ok), ok and self.load_git()))
        exp.add_row(switch_row("Sign every commit", f"With {key.replace(str(HOME), '~')}", st["on"] and st["format"] == "ssh", change))
        return group("", "", exp)

    # ---------------------------------------------------------------- tools: global packages + toolbox
    def _build_tools(self) -> None:
        self.gtable = DataTable([
            Column("name", "Package", "bold", width=200),
            Column("mgr", "From", "pill", width=80, sort="manager"),
            Column("version", "Version", "mono", width=100),
            Column("upd", "Update", "pill", width=110),
            Column("size", "Size", "size", width=80),
            Column("note", "Commands", "muted", expand=True),
        ], empty="Looking for global packages…", sort="size")
        self.gtable.set_size_request(-1, 300)
        self.gtable.set_context(lambda r: [("Uninstall", self._uninstall)], "global-packages")
        self.g_info = label("", "dim", hexpand=True, wrap=True)
        self.tools.append(hbox(label("Global packages", "section-title"), self.g_info,
                               button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_tools)))
        self.tools.append(label("Command-line programs you installed for your whole account with npm -g, pipx, uv tool, cargo install or go install.",
                                "dim", wrap=True))
        self.tools.append(self.gtable)
        t = self.gtable
        self.tools.append(flow(button("Uninstall", icon="user-trash-symbolic", on_click=lambda: self._table_sel(t, self._uninstall)),
                               button("Check npm for updates", icon="software-update-available-symbolic", on_click=self._check_npm),
                               button("Update all", css="suggested-action", on_click=self._update_all), spacing=6, max_per_line=3))
        self.toolbox = vbox(spacing=10)
        self.tools.append(self.toolbox)

    def load_tools(self) -> None:
        self.gtable.set_empty("Looking for global packages…")
        self.bg(devsetup.global_packages, self.show_globals)
        self.show_toolbox()

    def show_globals(self, res: dict) -> None:
        self.globals = res
        rows = []
        for i, p in enumerate(res["items"]):
            o = self.outdated.get(p.name) if p.manager == "npm" else None
            upd = (f"→ {o['latest']}", "warn") if o and o.get("latest") and o["latest"] != p.version else ("", "neutral")
            rows.append({"key": f"{p.manager}:{p.name}:{i}", "name": p.name, "mgr": (p.manager, MANAGER_KIND.get(p.manager, "neutral")),
                         "manager": p.manager, "version": p.version, "upd": upd, "size": p.size, "note": p.note, "pkg": p})
        self.gtable.set_rows(rows)
        have = [m for m, ok in res["managers"].items() if ok]
        self.gtable.set_empty("No global packages installed." if have else "None of npm, pipx, uv, cargo or go is installed.")
        self.g_info.set_text(f"{len(rows)} packages · {human(sum(r['size'] for r in rows))}" + (f" · checked {', '.join(have)}" if have else ""))

    def _uninstall(self, r: dict) -> None:
        p = r["pkg"]
        steps = devsetup.uninstall_steps(p)
        if not steps:
            self.toast(f"{p.name} comes with its tool and can't be removed on its own.")
            return
        self.run(f"Uninstall {p.name}", steps, f"Removes the {p.name} command ({p.manager}). Your projects aren't touched.", ok_label="Uninstall",
                 reload=False, done=lambda ok: ok and self.load_tools())

    def _check_npm(self) -> None:
        if not self.globals["managers"].get("npm"):
            self.toast("npm isn't installed.")
            return
        self.toast("Asking the npm registry… (takes a few seconds)")

        def got(o: dict) -> None:
            self.outdated = o
            self.show_globals(self.globals)
            self.toast(f"{len(o)} npm package{'s' if len(o) != 1 else ''} can be updated." if o else "All npm packages are up to date.")
        self.bg(devsetup.npm_outdated, got)

    def _update_all(self) -> None:
        steps = devsetup.update_all_steps(self.globals["managers"])
        self.run("Update global packages", steps, "Updates every global package to its newest version. cargo and go programs are updated by installing them again.",
                 ok_label="Update", reload=False, done=lambda ok: (setattr(self, "outdated", {}), self.load_tools()))

    def show_toolbox(self) -> None:
        clear(self.toolbox)
        missing = [t for t in TOOLBOX if not which(t[0])]
        rows = []
        for cmd, pkg, name, what in TOOLBOX:
            have = which(cmd)
            rows.append(action_row(name, what + (f"  ·  {have.replace(str(HOME), '~')}" if have else ""),
                                   pill("installed", "ok") if have else button("Install", css="flat", on_click=lambda p=pkg, n=name: self.run(
                                       f"Install {n}", [Step(f"Install {n}", ["apt-get", "install", "-y", p], root=True, env=APT)], ok_label="Install",
                                       reload=False, done=lambda ok: self.show_toolbox()))))
        g = group("Command-line toolbox", f"{len(TOOLBOX) - len(missing)} of {len(TOOLBOX)} installed. All come from Ubuntu's repositories.", *rows,
                  suffix=button(f"Install all {len(missing)} missing", css="flat", on_click=lambda: self.run(
                      "Install missing tools", [Step("Install tools", ["apt-get", "install", "-y", *[t[1] for t in missing]], root=True, env=APT)],
                      ", ".join(t[2] for t in missing), ok_label="Install", reload=False, done=lambda ok: self.show_toolbox())) if missing else None)
        self.toolbox.append(g)
        self.toolbox.append(label("Caches these tools leave behind (npm, pip, cargo…) are on the Cleanup page.", "dim"))


PAGE = DevPage
