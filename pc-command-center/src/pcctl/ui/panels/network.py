from __future__ import annotations

import asyncio

import psutil
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static, TabbedContent, TabPane

from ...core import network as net
from ...core.fmt import C, rate
from ...core.run import Step, has, py_step
from ..widgets import Btn, Card, InputScreen, Panel, SortTable, kv, muted, plain


class NetworkPanel(Panel):
    PANEL_ID = "network"
    TITLE = "Network"
    ICON = "󰖩"
    PLAIN_ICON = "⇅"
    HELP = "Connections, Wi-Fi, and which apps are listening on which ports"
    AUTO_REFRESH = 2.0

    DEFAULT_CSS = """
    NetworkPanel #cards { height: auto; margin-bottom: 1; }
    NetworkPanel #cards > Card { width: 1fr; margin-right: 1; }
    NetworkPanel TabbedContent { height: 1fr; }
    NetworkPanel TabPane { padding: 0; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.prev = psutil.net_io_counters(pernic=True)
        self.ports: list[net.Port] = []
        self.pub_ip = ""

    def compose(self) -> ComposeResult:
        yield from self.head()
        with Horizontal(id="cards"):
            yield Card("Connections", Static(id="ifaces"))
            yield Card("Internet", Static(id="inet"))
        with TabbedContent():
            with TabPane("Ports in use", id="tab-ports"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Stop the app on this port", id="killport", variant="error")
                    yield Btn("Free a port by number…", id="killnum")
                    yield Btn("Refresh", id="refports")
                yield SortTable([("port", "Port"), ("proto", "Type"), ("process", "App"), ("kind", "Kind"), ("open", "Reachable from"),
                                 ("pid", "PID"), ("user", "User"), ("cmd", "Command")], sort="port", reverse=False, id="ports",
                                empty="Nothing is listening")
            with TabPane("Wi-Fi", id="tab-wifi"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Scan", id="scan")
                    yield Btn("Connect…", id="connect", variant="primary")
                    yield Btn("Wi-Fi on/off", id="radio")
                yield SortTable([("active", ""), ("ssid", "Network"), ("signal", "Signal"), ("security", "Security")], sort="active", id="wifi",
                                empty="No Wi-Fi networks found (Wi-Fi may be off, or this PC has no Wi-Fi)")
            with TabPane("Tools", id="tab-tools"):
                with Horizontal(classes="toolbar"):
                    yield Btn("Test connection", id="test", variant="primary")
                    yield Btn("Show public IP", id="pubip")
                    yield Btn("Flush DNS cache", id="flush")
                    yield Btn("Restart networking", id="restart")
                yield Static("", id="tool-out")

    def load(self) -> None:
        self.tick()
        self.fetch_ports()
        self.fetch_wifi(False)

    def tick(self) -> None:
        now = psutil.net_io_counters(pernic=True)
        ifs = net.interfaces()
        t = Text()
        for i, f in enumerate([x for x in ifs if x["up"] or x["ipv4"]][:5]):
            if i:
                t.append("\n")
            p, c = self.prev.get(f["name"]), now.get(f["name"])
            rx = (c.bytes_recv - p.bytes_recv) / self.AUTO_REFRESH if p and c else 0
            tx = (c.bytes_sent - p.bytes_sent) / self.AUTO_REFRESH if p and c else 0
            t.append("● ", style=C["green"] if f["up"] else C["overlay0"])
            t.append(f"{f['kind']} ", style="bold")
            t.append(f"{f['name']}  ", style=C["subtext0"])
            t.append(f"{(f['ipv4'] or ['no address'])[0]}  ")
            t.append(f"↓{rate(rx)} ↑{rate(tx)}", style=C["teal"])
        self.prev = now
        self.query_one("#ifaces", Static).update(t or Text("No network connections", style=C["red"]))
        if not getattr(self, "_inet_done", False):
            self._inet_done = True
            self.fetch_inet()

    @work(thread=True, group="inet")
    def fetch_inet(self) -> None:
        gw, dns = net.default_gateway(), net.dns_servers()
        online = net.dns_check()
        self.app.call_from_thread(self._show_inet, gw, dns, online)

    def _show_inet(self, gw, dns, online) -> None:
        self.query_one("#inet", Static).update(kv([
            ("Status", Text("online ✓", style=C["green"]) if online else Text("offline", style=C["red"])),
            ("Router", gw or "-"),
            ("DNS", ", ".join(dns[:3]) or "-"),
            ("Public IP", self.pub_ip or "press 'Show public IP'"),
        ]))

    @work(thread=True, exclusive=True, group="ports")
    def fetch_ports(self) -> None:
        items = net.ports()
        self.app.call_from_thread(self.show_ports, items)

    def show_ports(self, items: list[net.Port]) -> None:
        self.ports = items
        rows = []
        for i, p in enumerate(items):
            rows.append((f"{p.proto}:{p.port}:{p.pid}:{i}", {"port": p.port, "proto": p.proto, "process": p.process, "kind": p.kind,
                                                            "open": p.exposed, "pid": p.pid or 0, "user": p.user, "cmd": p.cmd, "idx": i},
                         [Text(str(p.port), style="bold"), muted(p.proto), plain(p.process or "?"), Text(p.kind, style=C["mauve"]),
                          Text("your network", style=C["peach"]) if p.exposed else muted("this PC only"),
                          muted(p.pid or ""), muted(p.user), plain(p.cmd[:90])]))
        self.query_one("#ports", SortTable).set_rows(rows)

    @work(thread=True, exclusive=True, group="wifi")
    def fetch_wifi(self, rescan: bool) -> None:
        w = net.wifi(rescan)
        self.app.call_from_thread(self.show_wifi, w)

    def show_wifi(self, w: dict) -> None:
        self.wifi_state = w
        t = self.query_one("#wifi", SortTable)
        if not w.get("available"):
            t.set_rows([])
            return
        rows = []
        for n in w["networks"]:
            bars = "▂▄▆█"[: max(1, round(n["signal"] / 25))]
            rows.append((n["ssid"], {"active": 1 if n["active"] else 0, "ssid": n["ssid"].lower(), "signal": n["signal"], "security": n["security"], "name": n["ssid"]},
                         [Text("● connected" if n["active"] else "", style=C["green"]), Text(n["ssid"], style="bold"),
                          Text(f"{bars:<4} {n['signal']}%", style=C["green"] if n["signal"] > 60 else C["peach"]), muted(n["security"])]))
        t.set_rows(rows)

    # ---- actions
    @on(Button.Pressed, "#refports")
    def _refports(self) -> None:
        self.fetch_ports()

    @on(Button.Pressed, "#killport")
    @work
    async def _killport(self) -> None:
        sel = self.query_one("#ports", SortTable).selected()
        if not sel:
            return
        p = self.ports[sel["idx"]]
        await self._kill(p.port)

    @on(Button.Pressed, "#killnum")
    @work
    async def _killnum(self) -> None:
        v = await self.app.push_screen_wait(InputScreen("Free a port", "Stops whatever is using it, e.g. a dev server stuck on 3000.", "3000"))
        if v and v.isdigit():
            await self._kill(int(v))

    async def _kill(self, port: int) -> None:
        steps = net.kill_port_steps(port, self.ports)
        if not steps:
            self.app.notify(f"Nothing is using port {port} (or it's owned by the system).", severity="warning")
            return
        who = ", ".join(sorted({p.process for p in self.ports if p.port == port and p.process}))
        await self.run(f"Free port {port}", steps, f"Stops {who or 'the process'} so port {port} is free again.", reload=False)
        await asyncio.sleep(0.5)
        self.fetch_ports()

    @on(Button.Pressed, "#scan")
    def _scan(self) -> None:
        self.app.notify("Scanning for Wi-Fi networks…")
        self.fetch_wifi(True)

    @on(Button.Pressed, "#radio")
    @work
    async def _radio(self) -> None:
        on_now = getattr(self, "wifi_state", {}).get("enabled", True)
        await self.run("Turn Wi-Fi " + ("off" if on_now else "on"), [Step("Wi-Fi " + ("off" if on_now else "on"), ["nmcli", "radio", "wifi", "off" if on_now else "on"])],
                       reload=False)
        self.fetch_wifi(False)

    @on(Button.Pressed, "#connect")
    @work
    async def _connect(self) -> None:
        sel = self.query_one("#wifi", SortTable).selected()
        ssid = sel["name"] if sel else await self.app.push_screen_wait(InputScreen("Connect to Wi-Fi", "", "Network name"))
        if not ssid:
            return
        security = sel.get("security", "") if sel else "WPA2"
        pw = ""
        if security and security != "open":
            pw = await self.app.push_screen_wait(InputScreen(f"Password for {ssid}", "Leave empty if you've connected before.", "", password=True)) or ""

        def join() -> str:
            # wifi_connect keeps the password off the command line (and out of logs/audit).
            r = net.wifi_connect(ssid, pw, security)
            if not r.ok:
                raise RuntimeError((r.err or r.out).strip()[:200] or f"nmcli exited with {r.code}")
            return r.out.strip()
        step = py_step(f"Connect to {ssid}", join, f"nmcli: join Wi-Fi '{ssid}'" + (" (password supplied privately)" if pw else ""))
        await self.run(f"Connect to {ssid}", [step], reload=False)
        self.fetch_wifi(False)

    @on(Button.Pressed, "#test")
    @work
    async def _test(self) -> None:
        box = self.query_one("#tool-out", Static)
        box.update("Testing…")
        r1 = await asyncio.to_thread(net.ping, "1.1.1.1")
        dns = await asyncio.to_thread(net.dns_check, "ubuntu.com")
        gw = (await asyncio.to_thread(net.default_gateway)).split(" ")[0]
        r0 = await asyncio.to_thread(net.ping, gw) if gw else {"ok": False, "loss": 100, "avg_ms": None}
        def line(label, ok, extra=""):
            return (label, Text(("✓ " if ok else "✗ ") + extra, style=C["green"] if ok else C["red"]))
        rows = [line("Your router", r0["ok"], f"{r0['avg_ms']:.0f} ms" if r0.get("avg_ms") else "no reply"),
                line("Internet", r1["ok"], f"{r1['avg_ms']:.0f} ms, {r1['loss']:.0f}% lost" if r1.get("avg_ms") else "no reply"),
                line("Website names (DNS)", dns, "working" if dns else "not resolving - try 'Flush DNS cache'")]
        verdict = "Everything works." if all(r[1].plain.startswith("✓") for r in rows) else (
            "Your Wi-Fi/router is the problem." if not r0["ok"] else ("Router OK but no internet - the provider may be down." if not r1["ok"] else "DNS problem - flush the cache or change DNS."))
        rows.append(("Verdict", Text(verdict, style="bold")))
        box.update(kv(rows))

    @on(Button.Pressed, "#pubip")
    @work
    async def _pubip(self) -> None:
        self.pub_ip = await asyncio.to_thread(net.public_ip) or "couldn't reach the internet"
        self.fetch_inet()

    @on(Button.Pressed, "#flush")
    @work
    async def _flush(self) -> None:
        if has("resolvectl"):
            await self.run("Flush DNS cache", [Step("Forget cached website addresses", ["resolvectl", "flush-caches"], root=True)], reload=False)

    @on(Button.Pressed, "#restart")
    @work
    async def _restart(self) -> None:
        await self.run("Restart networking", [Step("Restart NetworkManager", ["systemctl", "restart", "NetworkManager"], root=True)],
                       "You'll be offline for a few seconds.", reload=False)
