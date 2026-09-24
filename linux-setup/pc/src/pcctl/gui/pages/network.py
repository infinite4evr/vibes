"""Network: live traffic, connections and Wi-Fi, open ports (with firewall + stop), diagnostics and speed test."""

from __future__ import annotations

import os
import time

import psutil
from gi.repository import Gtk

from ...core import network, security
from ...core.fmt import human, rate
from ...core.run import Step, has, out, sh
from ..dialogs import ask_text
from ..util import button, clear, hbox, idle, label, launch, pill, spacer, vbox
from ..widgets import Column, DataTable, LineGraph, MiniBar, card
from .base import Page, action_row, boxed_list, group, stat, switch_row, tabs

ME = os.environ.get("USER", "")


def saved_wifi() -> set[str]:
    res = set()
    for line in out(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"]).splitlines():
        name, _, typ = line.rpartition(":")
        if "wireless" in typ:
            res.add(name.replace("\\:", ":"))
    return res


class NetworkPage(Page):
    ID = "network"
    TITLE = "Network"
    ICON = "network-wireless-symbolic"
    SUBTITLE = "Live traffic, Wi-Fi, which apps are listening for connections, and quick fixes when the internet acts up."
    AUTO_REFRESH = 1.0

    def build(self) -> None:
        self.header()
        self.last = psutil.net_io_counters()
        self.last_t = time.monotonic()
        self.graph = LineGraph(("teal", "peach"), points=90, height=110, maximum=None)
        self.down = label("", ["big-num", "teal-text"])
        self.up = label("", ["big-num", "peach-text"])
        self.totals = label("", "dim")
        self.conn = label("…", "mid-num", wrap=True)
        self.conn_sub = label("", "subtle", wrap=True)
        left = vbox(hbox(vbox(label("DOWNLOAD", "tile-title"), self.down, spacing=0), vbox(label("UPLOAD", "tile-title"), self.up, spacing=0),
                         spacing=30), self.totals, spacing=4)
        right = vbox(self.conn, self.conn_sub, spacing=4)
        right.set_hexpand(True)
        hero = card(hbox(left, right, spacing=30), self.graph, spacing=12)
        hero.add_css_class("hero")
        self.body.append(hero)

        self.conn_box = vbox(spacing=18)
        self.ports_box = vbox(spacing=10)
        self.diag_box = vbox(spacing=18)
        sw, self.stack = tabs(("conn", "Connections", "network-wired-symbolic", self.conn_box),
                              ("ports", "Open ports", "network-server-symbolic", self.ports_box),
                              ("diag", "Diagnose & speed", "network-workgroup-symbolic", self.diag_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_ports()
        self._build_diag()

    def load(self) -> None:
        self.tab_loaded.clear()
        self._tab()
        self.bg(lambda: (network.interfaces(), network.default_gateway(), network.dns_servers(), network.wifi() if has("nmcli") else {}),
                self.show_summary)

    def tick(self) -> bool:
        now, t = psutil.net_io_counters(), time.monotonic()
        dt = max(0.1, t - self.last_t)
        rx, tx = (now.bytes_recv - self.last.bytes_recv) / dt, (now.bytes_sent - self.last.bytes_sent) / dt
        self.last, self.last_t = now, t
        self.graph.push(rx, tx)
        self.down.set_text(f"↓ {rate(rx)}")
        self.up.set_text(f"↑ {rate(tx)}")
        self.totals.set_text(f"Since boot: {human(now.bytes_recv)} down, {human(now.bytes_sent)} up")
        return True

    def _tab(self, *_a) -> None:
        name = self.stack.get_visible_child_name()
        if name in self.tab_loaded:
            return
        self.tab_loaded.add(name)
        if name == "conn":
            self.load_conn()
        elif name == "ports":
            self.load_ports()

    # ---------------------------------------------------------------- summary + connections
    def show_summary(self, res) -> None:
        ifaces, gw, dns, wf = res
        up = [i for i in ifaces if i["up"] and i["ipv4"]]
        active_wifi = next((n for n in wf.get("networks", []) if n["active"]), None) if wf else None
        if active_wifi:
            self.conn.set_text(f"Wi-Fi: {active_wifi['ssid']}")
        elif up:
            self.conn.set_text(f"{up[0]['kind']}: {up[0]['name']}")
        else:
            self.conn.set_text("Not connected")
        parts = []
        if up:
            parts.append("IP " + ", ".join(up[0]["ipv4"]))
        if gw:
            parts.append(f"router {gw}")
        if dns:
            parts.append("DNS " + ", ".join(dns[:3]))
        if active_wifi:
            parts.append(f"signal {active_wifi['signal']}%")
        self.conn_sub.set_text(" · ".join(parts))

    def load_conn(self) -> None:
        self.loading(self.conn_box)
        self.bg(lambda: (network.interfaces(), network.wifi() if has("nmcli") else {"available": False}, saved_wifi() if has("nmcli") else set()),
                self.show_conn)

    def show_conn(self, res) -> None:
        ifaces, wf, saved = res
        self.saved = saved
        clear(self.conn_box)
        rows = []
        for i in ifaces:
            icon = {"Wi-Fi": "network-wireless-symbolic", "Ethernet": "network-wired-symbolic", "VPN": "network-vpn-symbolic"}.get(i["kind"], "network-workgroup-symbolic")
            sub = []
            if i["ipv4"]:
                sub.append("IPv4 " + ", ".join(i["ipv4"]))
            if i["ipv6"]:
                sub.append("IPv6 " + i["ipv6"][0])
            if i["speed"]:
                sub.append(f"{i['speed']} Mb/s link")
            if i["mac"]:
                sub.append(f"MAC {i['mac']}")
            sub.append(f"used {human(i['rx'])} down / {human(i['tx'])} up since boot")
            rows.append(action_row(f"{i['kind']} · {i['name']}", " · ".join(sub), pill("connected" if i["up"] and i["ipv4"] else ("up" if i["up"] else "off"),
                                                                               "ok" if i["up"] and i["ipv4"] else "neutral"),
                                   prefix=Gtk.Image.new_from_icon_name(icon)))
        self.conn_box.append(group("Network adapters", "", *rows) if rows else label("No network adapters found.", "dim"))

        if wf.get("available"):
            def toggle(on: bool, settle) -> None:
                r = sh(["nmcli", "radio", "wifi", "on" if on else "off"], timeout=10)
                settle(r.ok)
                if r.ok:
                    self.load_conn()
            g = group("Wi-Fi", "Networks nearby. Saved networks connect without asking for the password again.",
                      switch_row("Wi-Fi", "Turn the Wi-Fi radio on or off.", wf.get("enabled", False), toggle),
                      suffix=button(icon="view-refresh-symbolic", css="flat", tooltip="Scan again", on_click=self.rescan))
            for n in wf.get("networks", [])[:25]:
                bar = MiniBar(width=60, height=6, warn=101, crit=101, color="green" if n["signal"] > 60 else ("peach" if n["signal"] > 30 else "red"))
                bar.set(n["signal"] / 100)
                extra = [pill("connected", "ok")] if n["active"] else [button("Connect", css="flat", on_click=lambda nn=n: self.connect(nn))]
                if n["ssid"] in saved and not n["active"]:
                    extra.insert(0, pill("saved", "neutral"))
                row = action_row(n["ssid"], f"{n['signal']}% signal · {n['security']}", bar, *extra,
                                 prefix=Gtk.Image.new_from_icon_name("network-wireless-signal-" + ("excellent" if n["signal"] > 75 else "good" if n["signal"] > 50 else "ok" if n["signal"] > 25 else "weak") + "-symbolic"))
                g.add(row)
            self.conn_box.append(g)
        self.conn_box.append(group("Settings", "", action_row("Network settings", "VPNs, proxies, hotspot and advanced options live in GNOME Settings.",
                                                                  button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "network"])))))

    def rescan(self) -> None:
        self.loading(self.conn_box, "Scanning for Wi-Fi networks…")
        self.bg(lambda: (network.interfaces(), network.wifi(rescan=True), saved_wifi()), self.show_conn)

    def connect(self, n: dict) -> None:
        ssid = n["ssid"]

        def attempt(args: list[str]) -> None:
            self.toast(f"Connecting to {ssid}…")
            self.bg(lambda: sh(args, timeout=45), lambda r: (self.toast(f"Connected to {ssid}." if r.ok else f"Couldn't connect: {(r.err or r.out).strip()[:120]}", 5),
                                                             self.load_conn(), self.load()))
        if ssid in getattr(self, "saved", set()):
            attempt(["nmcli", "con", "up", "id", ssid])
        elif n["security"] in ("open", "--", ""):
            attempt(["nmcli", "dev", "wifi", "connect", ssid])
        else:
            ask_text(self.win, f"Connect to {ssid}", "Enter the Wi-Fi password.", on_done=lambda pw: pw and attempt(
                ["nmcli", "dev", "wifi", "connect", ssid, "password", pw]), password=True, ok_label="Connect")

    # ---------------------------------------------------------------- ports
    def _build_ports(self) -> None:
        self.fw_banner = vbox()
        self.ports_box.append(self.fw_banner)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filter by port, app…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.ptable.set_filter(e.get_text()))
        self.only_exposed = Gtk.CheckButton(label="Only reachable from other devices")
        self.only_exposed.connect("toggled", lambda *_: self.show_ports(self.port_items))
        self.ports_box.append(hbox(self.search_entry, self.only_exposed, button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_ports)))
        self.ptable = DataTable([
            Column("port", "Port", "bold", width=80),
            Column("proto", "Type", "muted", width=60),
            Column("reach", "Who can reach it", "pill", width=150),
            Column("process", "App", "text", width=150),
            Column("kind", "Kind", "muted", width=90),
            Column("pid", "PID", "num", width=70),
            Column("user", "User", "muted", width=90),
            Column("cmd", "Command", "mono", expand=True),
        ], on_activate=self._port_open, empty="Nothing is listening.", sort="port", descending=False)
        self.ptable.set_size_request(-1, 400)
        self.ports_box.append(self.ptable)
        self.ports_box.append(hbox(label("“Only this PC” is private. “Your network” means phones and laptops on the same Wi-Fi can connect.", "dim", wrap=True, hexpand=True),
                                   button("Open in browser", css="flat", on_click=lambda: self._port_sel(self._port_open)),
                                   button("Allow in firewall…", css="flat", on_click=lambda: self._port_sel(self.allow)),
                                   button("Stop app…", icon="process-stop-symbolic", css="destructive-action", on_click=lambda: self._port_sel(self.stop_port))))
        self.port_items: list[network.Port] = []

    def load_ports(self) -> None:
        self.ptable.set_empty("Looking at open ports…")
        self.bg(lambda: (network.ports(with_root=False), security.firewall()), self._ports_loaded)

    def _ports_loaded(self, res) -> None:
        items, fw = res
        self.fw = fw
        clear(self.fw_banner)
        if fw.level != "ok":
            b = hbox(label(fw.detail, None, wrap=True, hexpand=True), css="banner-bad")
            if fw.steps:
                fix = button(fw.fix_label or "Turn on", css="suggested-action", on_click=lambda: self.run(fw.fix_label or "Firewall", fw.steps, fw.detail))
                fix.set_valign(Gtk.Align.CENTER)
                b.append(fix)
            self.fw_banner.append(b)
        self.show_ports(items)

    def show_ports(self, items: list[network.Port]) -> None:
        self.port_items = items
        fw_on = getattr(self, "fw", None) is not None and self.fw.level == "ok"
        rows = []
        for p in items:
            if self.only_exposed.get_active() and not p.exposed:
                continue
            reach = ("only this PC", "ok") if not p.exposed else (("network (firewalled)", "info") if fw_on else ("your network", "warn"))
            rows.append({"key": f"{p.proto}:{p.port}:{p.pid}:{p.address}", "port": p.port, "proto": p.proto, "reach": reach, "process": p.process or "?",
                         "kind": p.kind, "pid": p.pid or 0, "user": p.user, "cmd": p.cmd or p.address, "_p": p})
        self.ptable.set_rows(rows)
        self.ptable.set_empty("Nothing is listening.")
        exposed = [p for p in items if p.exposed and p.proto == "tcp"]
        page = self.stack.get_page(self.ports_box)
        page.set_badge_number(len(exposed) if not fw_on else 0)
        page.set_needs_attention(bool(exposed) and not fw_on)

    def _port_sel(self, fn) -> None:
        r = self.ptable.selected()
        if r:
            fn(r)
        else:
            self.toast("Select a port first.")

    def _port_open(self, r: dict) -> None:
        p = r["_p"]
        if p.proto == "tcp":
            launch(["xdg-open", f"http://localhost:{p.port}"])

    def stop_port(self, r: dict) -> None:
        p = r["_p"]
        steps = network.kill_port_steps(p.port, self.port_items)
        if not steps:
            self.toast("Can't tell which app owns that port (it may belong to the system).")
            return
        self.run(f"Stop what's using port {p.port}", steps, f"{p.process or 'The app'} will be asked to close.", danger=True, ok_label="Stop",
                 reload=False, done=lambda ok: self.load_ports())

    def allow(self, r: dict) -> None:
        p = r["_p"]
        self.run(f"Allow port {p.port} in the firewall", security.ufw_allow_steps(str(p.port), p.proto, True),
                 "Lets devices on your local network (home/office Wi-Fi) reach this port, e.g. to test a site on your phone. "
                 "The internet at large still can't. You can remove the rule on the Security page.", ok_label="Allow", reload=False)

    # ---------------------------------------------------------------- diagnose
    def _build_diag(self) -> None:
        self.check_list = boxed_list()
        self.diag_btn = button("Run checks", icon="system-run-symbolic", css="suggested-action", on_click=self.diagnose)
        self.diag_box.append(group("Is the internet working?", "Checks each step from this PC to the internet, so you know where it breaks.",
                                   suffix=self.diag_btn))
        self.diag_box.append(self.check_list)

        self.sp_down, self.sp_up, self.sp_ping = stat("-", "download Mbps", "teal-text"), stat("-", "upload Mbps", "peach-text"), stat("-", "latency ms")
        self.sp_status = label("Uses Cloudflare's speed test (about 30 MB of data).", "dim", wrap=True)
        self.sp_btn = button("Start speed test", icon="media-playback-start-symbolic", css="suggested-action", on_click=self.speed)
        self.diag_box.append(card(hbox(self.sp_down, self.sp_up, self.sp_ping, spacer(), self.sp_btn, spacing=34), self.sp_status, title="Speed test"))

        fixes = [
            action_row("Flush DNS cache", "Fixes “site not found” after a website or your router changed.",
                       button("Flush", css="flat", on_click=lambda: self.run("Flush DNS cache", [Step("Flush DNS cache", ["resolvectl", "flush-caches"], root=True)],
                                                                          ok_label="Flush", reload=False))),
            action_row("Restart networking", "Turns the network off and on again. Fixes most stuck connections.",
                       button("Restart", css="flat", on_click=lambda: self.run("Restart networking", [Step("Restart NetworkManager", ["systemctl", "restart", "NetworkManager"], root=True)],
                                                                              "You'll be offline for a few seconds.", ok_label="Restart"))),
            action_row("Show public IP address", "The address websites see (your router's, usually).", button("Show", css="flat", on_click=self.public_ip)),
            action_row("Hosts file", "Local name overrides in /etc/hosts.", button("View", css="flat", on_click=lambda: self.text("/etc/hosts", out(["cat", "/etc/hosts"])))),
        ]
        self.diag_box.append(group("Quick fixes", "", *fixes))

    def diagnose(self) -> None:
        clear(self.check_list)
        self.diag_btn.set_sensitive(False)
        self.check_list.append(action_row("Checking…", ""))

        def work():
            res = []
            ifaces = [i for i in network.interfaces() if i["up"] and i["ipv4"]]
            res.append(("Connected to a network", bool(ifaces), ", ".join(f"{i['name']} {i['ipv4'][0]}" for i in ifaces) or "No network adapter has an address. Check Wi-Fi or the cable."))
            gw = network.default_gateway()
            gip = gw.split(" ")[0] if gw else ""
            if gip:
                p = network.ping(gip)
                res.append(("Router answers", p["ok"], f"{gw}: {p['avg_ms']:.0f} ms, {p['loss']:.0f}% lost" if p["avg_ms"] else f"{gw} doesn't answer. Restart the router or reconnect."))
            else:
                res.append(("Router answers", False, "No router (default gateway) found."))
            p = network.ping("1.1.1.1")
            res.append(("Internet reachable", p["ok"], f"1.1.1.1: {p['avg_ms']:.0f} ms, {p['loss']:.0f}% lost" if p["avg_ms"] else "Can't reach the internet. The router or provider has a problem."))
            dns = network.dns_check()
            res.append(("Names resolve (DNS)", dns, "ubuntu.com found." if dns else "Can't look up names. Try Flush DNS cache, or set DNS to 1.1.1.1 in Settings."))
            r = sh(["curl", "-fsSI", "--max-time", "8", "https://www.google.com"], timeout=10)
            res.append(("Websites load (HTTPS)", r.ok, "https://www.google.com responded." if r.ok else "HTTPS fails. A proxy, captive portal (hotel/café login page) or firewall may be in the way."))
            return res
        self.bg(work, self.show_diag)

    def show_diag(self, res) -> None:
        clear(self.check_list)
        self.diag_btn.set_sensitive(True)
        from ..util import status_icon
        for title, ok, detail in res:
            self.check_list.append(action_row(title, detail, prefix=status_icon("ok" if ok else "bad")))

    def speed(self) -> None:
        self.sp_btn.set_sensitive(False)
        for s in (self.sp_down, self.sp_up, self.sp_ping):
            s._value.set_text("…")
        self.sp_status.set_text("Measuring latency…")
        self.bg(lambda: network.speed_test(progress=lambda m: idle(self.sp_status.set_text, m)), self.show_speed)

    def show_speed(self, r: dict) -> None:
        self.sp_btn.set_sensitive(True)
        self.sp_down._value.set_text(f"{r['down_mbps']:.0f}" if r.get("down_mbps") else "-")
        self.sp_up._value.set_text(f"{r['up_mbps']:.0f}" if r.get("up_mbps") else "-")
        self.sp_ping._value.set_text(f"{r['latency_ms']:.0f}" if r.get("latency_ms") else "-")
        if r.get("error"):
            self.sp_status.set_text(f"Test failed: {r['error'][:150]}")
        else:
            d = r.get("down_mbps") or 0
            verdict = "Great for 4K video and big downloads." if d > 100 else ("Fine for HD video calls and streaming." if d > 25 else
                                                                                   "Slow: video calls may stutter.")
            self.sp_status.set_text(f"{verdict}  Measured {time.strftime('%H:%M')} via {r['server']}.")

    def public_ip(self) -> None:
        self.toast("Asking the internet…", 1)
        self.bg(network.public_ip, lambda ip: self.toast(f"Your public IP is {ip}" if ip else "Couldn't find out (offline?)", 6))


PAGE = NetworkPage
