"""Network: live traffic, connections and Wi-Fi, open ports (with firewall + stop), diagnostics and speed test."""

from __future__ import annotations

import os
import socket
import time

import psutil
from gi.repository import Adw, Gtk

from ...core import network, security
from ...core.fmt import human, rate
from ...core.run import Step, has, out, sh
from ..dialogs import ask_text
from ..util import button, clear, flow, hbox, idle, label, launch, pill, vbox
from ..widgets import Column, DataTable, LineGraph, MiniBar, card
from .base import Page, action_row, banner, boxed_list, group, stat, switch_row, tabs

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
        hero = card(flow(left, right, spacing=24, min_per_line=1, max_per_line=2), self.graph, spacing=12)
        hero.add_css_class("hero")
        self.body.append(hero)

        self.conn_box = vbox(spacing=18)
        self.ports_box = vbox(spacing=10)
        self.diag_box = vbox(spacing=18)
        self.talk_box = vbox(spacing=10)
        self.lan_box = vbox(spacing=10)
        sw, self.stack = tabs(("conn", "Wi-Fi & DNS", "network-wireless-symbolic", self.conn_box),
                              ("talk", "Talking to", "network-transmit-receive-symbolic", self.talk_box),
                              ("ports", "Open ports", "network-server-symbolic", self.ports_box),
                              ("lan", "Devices nearby", "network-workgroup-symbolic", self.lan_box),
                              ("diag", "Fix & speed", "emblem-system-symbolic", self.diag_box))
        self.body.append(sw)
        self.body.append(self.stack)
        self.stack.connect("notify::visible-child-name", self._tab)
        self.tab_loaded: set[str] = set()
        self._build_ports()
        self._build_diag()
        self._build_talk()
        self._build_lan()

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
        elif name == "talk":
            self.load_talk()

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
        self.bg(self._conn_data, self.show_conn)

    def _conn_data(self, rescan: bool = False):
        nm = has("nmcli")
        con = network.active_connection() if nm else {}
        return (network.interfaces(), network.wifi(rescan=rescan) if nm else {"available": False}, saved_wifi() if nm else set(),
                con, network.current_dns_preset(con) if con else "auto", network.vpns() if nm else [],
                [c for c in network.nm_connections() if c["type"] == "802-11-wireless"] if nm else [])

    def show_conn(self, res) -> None:
        ifaces, wf, saved, con, dns_now, vpns, saved_list = res
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
                extra = [pill("connected", "ok")] if n["active"] else [button("Connect", css="flat", on_click=lambda nn=n: self.connect_wifi(nn))]
                if n["ssid"] in saved and not n["active"]:
                    extra.insert(0, pill("saved", "neutral"))
                row = action_row(n["ssid"], f"{n['signal']}% signal · {n['security']}", bar, *extra,
                                 prefix=Gtk.Image.new_from_icon_name("network-wireless-signal-" + ("excellent" if n["signal"] > 75 else "good" if n["signal"] > 50 else "ok" if n["signal"] > 25 else "weak") + "-symbolic"))
                g.add(row)
            self.conn_box.append(g)
        # DNS
        if con:
            keys = [k for k, *_ in network.DNS_PRESETS]
            names = [t for _, t, *_ in network.DNS_PRESETS] + (["Custom (set elsewhere)"] if dns_now == "custom" else [])
            combo = Adw.ComboRow(model=Gtk.StringList.new(names))
            combo.set_use_markup(False)
            combo.set_title("Look up websites with")
            combo.set_subtitle(f"DNS for “{con['name']}”. A different DNS can be faster, more private, or block ads and malware for every app.")
            combo.set_selected(keys.index(dns_now) if dns_now in keys else len(names) - 1)

            def pick(r, _p) -> None:
                i = r.get_selected()
                if i >= len(keys) or keys[i] == dns_now:
                    return
                self.run("Change DNS", network.dns_steps(keys[i], con), "Your connection reconnects for a second.", ok_label="Change",
                         reload=False, done=lambda ok: self.load_conn())
            combo.connect("notify::selected", pick)
            self.conn_box.append(group("DNS", "", combo))

        # VPN
        if vpns:
            vg = group("VPN", "Your saved VPN connections.")
            for v in vpns:
                if v["type"] == "tailscale":
                    vg.add(action_row("Tailscale", "connected" if v["active"] else "stopped",
                                      button("Disconnect" if v["active"] else "Connect", css="flat", on_click=lambda on=v["active"]: self.run(
                                          "Tailscale", [Step("Tailscale " + ("down" if on else "up"), ["tailscale", "down" if on else "up"])], ask=False,
                                          reload=False, done=lambda ok: self.load_conn()))))
                    continue

                def toggle_vpn(on: bool, settle, vv=v) -> None:
                    r = sh(["nmcli", "con", "up" if on else "down", vv["uuid"]], timeout=45)
                    settle(r.ok)
                    if not r.ok:
                        self.toast(f"Couldn't {'connect' if on else 'disconnect'}: {(r.err or r.out).strip()[:120]}", 5)
                vg.add(switch_row(v["name"], v["type"], v["active"], toggle_vpn))
            self.conn_box.append(vg)

        # saved networks + hotspot
        if saved_list:
            sg = Adw.ExpanderRow(title=f"Saved Wi-Fi networks ({len(saved_list)})", subtitle="Forget old networks, or see a password to share it.")
            for c in sorted(saved_list, key=lambda c: c["last"], reverse=True):
                r = action_row(c["name"], f"last used {c['last']}" if c["last"] and c["last"] != "never" else "never used",
                               button("Password", css="flat", on_click=lambda cc=c: self.show_password(cc)),
                               button(icon="user-trash-symbolic", css="flat", tooltip="Forget this network",
                                      on_click=lambda cc=c: self.run(f"Forget {cc['name']}", [Step(f"Forget {cc['name']}", ["nmcli", "con", "delete", cc["uuid"]])],
                                                                     "The PC won't join it automatically anymore.", danger=True, ok_label="Forget",
                                                                     reload=False, done=lambda ok: self.load_conn())))
                sg.add_row(r)
            hot = action_row("Wi-Fi hotspot", "Share this PC's internet with your phone or another laptop.",
                             button("Start…", css="flat", on_click=self.hotspot),
                             button("Stop", css="flat", on_click=lambda: self.run("Stop hotspot", network.hotspot_steps(False), ask=False, reload=False)))
            self.conn_box.append(group("Wi-Fi extras", "", sg, hot))

        self.conn_box.append(group("Settings", "", action_row("Network settings", "Proxies, VPN setup and advanced options live in GNOME Settings.",
                                                                  button("Open", css="flat", on_click=lambda: launch(["gnome-control-center", "network"])))))

    def show_password(self, c: dict) -> None:
        pw = network.wifi_password(c["uuid"])
        if not pw:
            self.toast("No saved password (open network, or it's stored in your keyring only).")
            return
        self.text(f"Wi-Fi password: {c['name']}", f"Network:  {c['name']}\nPassword: {pw}\n\nOn a phone you can also scan the QR code in "
                  "GNOME Settings → Wi-Fi → ⋮ → Share network.")

    def hotspot(self) -> None:
        def got(pw: str | None) -> None:
            if pw is None:
                return
            if len(pw) < 8:
                self.toast("The password needs at least 8 characters.")
                return
            self.run("Start hotspot", network.hotspot_steps(True, f"{socket.gethostname()}-hotspot", pw), "Your Wi-Fi disconnects from its "
                     "current network while the hotspot runs (unless you're on a cable).", ok_label="Start", reload=False)
        ask_text(self.win, "Wi-Fi hotspot", "Choose a password (8+ characters) for the hotspot.", "password", got, ok_label="Start")

    def rescan(self) -> None:
        self.loading(self.conn_box, "Scanning for Wi-Fi networks…")
        self.bg(lambda: self._conn_data(rescan=True), self.show_conn)

    # ---------------------------------------------------------------- who the PC is talking to
    def _build_talk(self) -> None:
        self.talk_status = label("Apps with an open connection to the internet right now.", "dim", hexpand=True)
        self.talk_box.append(flow(self.talk_status, button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_talk), spacing=8, max_per_line=2))
        self.ttable = DataTable([
            Column("process", "App", "bold", width=170),
            Column("host", "Talking to", "text", expand=True),
            Column("ip", "Address", "mono", width=170),
            Column("svc", "Kind", "muted", width=110, sort="port"),
            Column("pid", "PID", "num", width=70),
        ], empty="No open connections.", sort="process", descending=False,
            on_activate=lambda r: self.text(f"{r['process']} → {r['host'] or r['ip']}", f"App: {r['process']} (pid {r['pid']})\n"
                                                                                       f"Remote: {r['ip']}:{r['port']}\nName: {r['host'] or '(no name)'}\nLocal: {r['local']}"))
        self.ttable.set_size_request(-1, 420)
        self.ttable.set_context(lambda r: [("Look up this address", lambda rr: launch(["xdg-open", f"https://ipinfo.io/{rr['ip']}"])),
                                           ("Stop this app…", lambda rr: self.win.goto("processes"))], "connections")
        self.talk_box.append(self.ttable)
        self.talk_box.append(label("Names come from reverse DNS, so big services show their hosting provider (e.g. cloudfront, 1e100 = Google).",
                                   "dim", wrap=True))

    def load_talk(self) -> None:
        self.ttable.set_empty("Looking at connections…")
        self.bg(network.connections, self.show_talk)

    def show_talk(self, items: list[dict]) -> None:
        grouped: dict[tuple, dict] = {}  # one row per app + remote address (browsers open many sockets to the same server)
        for c in items:
            k = (c["process"] or "(system)", c["remote_ip"], c["remote_port"])
            g = grouped.get(k)
            if g:
                g["n"] += 1
                continue
            grouped[k] = {"key": ":".join(map(str, k)), "process": k[0], "host": c.get("host", ""), "ip": c["remote_ip"],
                          "port": c["remote_port"], "svc": network.SERVICES.get(c["remote_port"], str(c["remote_port"])),
                          "pid": c["pid"], "local": c["local"], "n": 1}
        rows = list(grouped.values())
        for r in rows:
            if r["n"] > 1:
                r["svc"] = f"{r['svc']} ×{r['n']}"
        self.ttable.set_rows(rows)
        self.ttable.set_empty("No open connections.")
        apps = len({r["process"] for r in rows})
        self.talk_status.set_text(f"{len(items)} connections to {len(rows)} places from {apps} app{'s' if apps != 1 else ''} right now.")

    # ---------------------------------------------------------------- devices nearby
    def _build_lan(self) -> None:
        self.lan_status = label("Phones, TVs, printers and other computers on the same network as this PC.", "dim", hexpand=True)
        self.lan_btn = button("Scan", icon="system-search-symbolic", css="suggested-action", on_click=self.scan_lan)
        self.lan_box.append(flow(self.lan_status, self.lan_btn, spacing=8, max_per_line=2))
        self.ltable = DataTable([
            Column("name", "Name", "bold", expand=True),
            Column("ip", "Address", "mono", width=150, sort="ipkey"),
            Column("mac", "Hardware ID (MAC)", "mono", width=200),
            Column("what", "", "pill", width=110),
        ], empty="Press Scan to look for devices.", sort="ipkey", descending=False)
        self.ltable.set_size_request(-1, 400)
        self.lan_box.append(self.ltable)
        self.lan_box.append(label("Unknown devices you don't recognise on your home Wi-Fi? Change the Wi-Fi password in your router.", "dim", wrap=True))

    def scan_lan(self) -> None:
        self.lan_btn.set_sensitive(False)
        self.lan_status.set_text("Scanning your network (a few seconds)…")
        self.bg(network.lan_devices, self.show_lan)

    def show_lan(self, items: list[dict]) -> None:
        self.lan_btn.set_sensitive(True)
        rows = []
        for d in items:
            what = ("router", "accent") if d["router"] else (("this PC", "ok") if d["state"] == "self" else ("", "neutral"))
            rows.append({"key": d["ip"], "name": d["name"] or "(unknown device)", "ip": d["ip"], "ipkey": tuple(int(x) for x in d["ip"].split(".")),
                         "mac": d["mac"], "what": what})
        self.ltable.set_rows(rows)
        self.lan_status.set_text(f"{len(rows)} devices found.")

    def connect_wifi(self, n: dict) -> None:
        # Not named `connect`: that would shadow GObject.connect and break signal hookup for this page.
        ssid = n["ssid"]

        def attempt(fn) -> None:
            self.toast(f"Connecting to {ssid}…")
            self.bg(fn, lambda r: (self.toast(f"Connected to {ssid}." if r.ok else f"Couldn't connect: {(r.err or r.out).strip()[:120]}", 5),
                                   self.load_conn(), self.load()))
        if ssid in getattr(self, "saved", set()):
            attempt(lambda: sh(["nmcli", "con", "up", "id", ssid], timeout=45))
        elif n["security"] in ("open", "--", ""):
            attempt(lambda: network.wifi_connect(ssid))
        else:
            ask_text(self.win, f"Connect to {ssid}", "Enter the Wi-Fi password.", on_done=lambda pw: pw and attempt(
                lambda: network.wifi_connect(ssid, pw, n["security"])), password=True, ok_label="Connect")

    # ---------------------------------------------------------------- ports
    def _build_ports(self) -> None:
        self.fw_banner = vbox()
        self.ports_box.append(self.fw_banner)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filter by port, app…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self.ptable.set_filter(e.get_text()))
        self.only_exposed = Gtk.CheckButton(label="Only reachable from other devices")
        self.only_exposed.connect("toggled", lambda *_: self.show_ports(self.port_items))
        self.ports_box.append(flow(self.search_entry, self.only_exposed, button(icon="view-refresh-symbolic", tooltip="Refresh", on_click=self.load_ports), spacing=8, max_per_line=3))
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
        self.ports_box.append(flow(label("“Only this PC” is private. “Your network” means phones and laptops on the same Wi-Fi can connect.", "dim", wrap=True, hexpand=True),
                                    button("Open in browser", css="flat", on_click=lambda: self._port_sel(self._port_open)),
                                    button("Allow in firewall…", css="flat", on_click=lambda: self._port_sel(self.allow)),
                                    button("Stop app…", icon="process-stop-symbolic", css="destructive-action", on_click=lambda: self._port_sel(self.stop_port)),
                                    min_per_line=1, max_per_line=4, column_spacing=8, row_spacing=8))
        self.port_items: list[network.Port] = []

    def load_ports(self) -> None:
        self.ptable.set_empty("Looking at open ports…")
        self.bg(lambda: (network.ports(with_root=False), security.firewall()), self._ports_loaded)

    def _ports_loaded(self, res) -> None:
        items, fw = res
        self.fw = fw
        clear(self.fw_banner)
        if fw.level != "ok":
            actions = []
            if fw.steps:
                actions.append(button(fw.fix_label or "Turn on", css="suggested-action",
                                      on_click=lambda: self.run(fw.fix_label or "Firewall", fw.steps, fw.detail)))
            self.fw_banner.append(banner(fw.detail, "bad", *actions))
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
        self.diag_box.append(card(flow(self.sp_down, self.sp_up, self.sp_ping, self.sp_btn, spacing=22, min_per_line=2, max_per_line=4), self.sp_status, title="Speed test"))

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
