"""Unit tests plus `xray run -test` validation of generated configs.

Run: python -m pytest tests  (or: python tests/test_core_logic.py)
"""
import base64
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NIMBUS_LANG", "ru")   # texts in assertions are the Russian ones

from nimbus import balancer, config_builder, links, paths, subscription  # noqa: E402
from nimbus.settings import Settings  # noqa: E402
from nimbus.store import Balancer, Server, Store, Subscription  # noqa: E402

UUID = "b831381d-6324-4d53-ad4f-8cda48b30811"
PBK = "Z84J2IelR9ch3k8VtlVhhs5ycBUlXA7wHBWcBLjF1QA"
VMESS = "vmess://" + base64.b64encode(json.dumps({
    "v": "2", "ps": "vm-ws", "add": "vm.example.com", "port": "443", "id": UUID, "aid": "0",
    "scy": "auto", "net": "ws", "type": "none", "host": "cdn.example.com", "path": "/ws",
    "tls": "tls", "sni": "cdn.example.com", "fp": "chrome"}).encode()).decode()

LINKS = {
    "vless-reality": f"vless://{UUID}@1.2.3.4:443?type=tcp&security=reality&sni=www.microsoft.com"
                     f"&fp=firefox&pbk={PBK}&sid=6ba85179e30d4fc2&flow=xtls-rprx-vision#NL%20Reality",
    "vless-xhttp": f"vless://{UUID}@x.example.com:443?type=xhttp&security=tls&sni=x.example.com"
                   f"&path=%2Fxh&mode=packet-up&alpn=h2,http/1.1#xhttp",
    "vless-grpc": f"vless://{UUID}@g.example.com:443?type=grpc&security=tls&serviceName=svc&mode=multi#grpc",
    "vmess": VMESS,
    "trojan": "trojan://p%40ss@t.example.com:443?sni=t.example.com&type=ws&path=%2Ft#trojan",
    "ss-sip002": "ss://" + base64.urlsafe_b64encode(b"chacha20-ietf-poly1305:secret").decode().rstrip("=")
                 + "@5.6.7.8:8388#ss",
    "ss-2022-plain": "ss://2022-blake3-aes-128-gcm:AAAAAAAAAAAAAAAAAAAAAA%3D%3D@5.6.7.8:8388#ss2022",
    "ss-legacy": "ss://" + base64.b64encode(b"aes-256-gcm:pw@9.9.9.9:443").decode() + "#legacy",
    "hy2": "hy2://authpass@h.example.com:443?sni=h.example.com&obfs=salamander&obfs-password=ob#hy2",
    "hy2-hop": "hysteria2://authpass@h.example.com:443?sni=h.example.com&mport=20000-30000#hop",
    "socks": "socks://" + base64.b64encode(b"user:pw").decode() + "@10.0.0.1:1080#socks",
    "wireguard": "wireguard://" + "yAnz5TF%2BlXXJte14tji3zlMNq%2BhdP3K9Ug6v7ZMg9Gc%3D"
                 "@162.159.192.1:2408?publickey=bmXOC%2BF1FxEMF9dyiK2H5%2F1SUtzH0JuVo51h2wPfgyo%3D"
                 "&address=172.16.0.2%2F32,2606:4700::2%2F128&reserved=1,2,3&mtu=1280#warp",
}


def xray_ok(config: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.write(fd, json.dumps(config).encode())
    os.close(fd)
    try:
        r = subprocess.run([str(paths.XRAY_EXE), "run", "-test", "-c", path], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "XRAY_LOCATION_ASSET": str(paths.CORE_DIR)})
        return "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[-1]
    finally:
        os.remove(path)


def singbox_ok(config: dict) -> str:
    """"" if sing-box accepts the TUN config; "skip" without sing-box.exe."""
    if not paths.SINGBOX_EXE.exists():
        return "skip"
    fd, path = tempfile.mkstemp(suffix=".json")
    os.write(fd, json.dumps(config).encode())
    os.close(fd)
    try:
        for attempt in range(40):
            try:
                r = subprocess.run([str(paths.SINGBOX_EXE), "check", "--disable-color", "-c", path],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                break
            except PermissionError:   # an antivirus still scanning the exe after its last run
                if attempt == 39:
                    raise
                time.sleep(0.25)
        return "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[-1]
    finally:
        os.remove(path)


SETTING_VARIANTS = {
    "default": Settings(),
    "tun+killswitch": Settings(tunnel_mode="tun", kill_switch=True),
    "bypass_ru+fakedns+tun": Settings(tunnel_mode="tun", routing_mode="bypass_ru", fake_dns=True),
    "mux+fragment": Settings(mux=True, fragment=True),
}


class LinkTests(unittest.TestCase):
    def test_all_links_parse_and_validate(self):
        for label, link in LINKS.items():
            for vname, s in SETTING_VARIANTS.items():
                with self.subTest(link=label, settings=vname):
                    server = Server(id="x", name=label, link=link)
                    built = config_builder.build(server, s, 12345, egress="Ethernet")
                    self.assertEqual(xray_ok(built.config), "")

    def test_reality_fields(self):
        name, ob = links.parse_link(LINKS["vless-reality"])
        self.assertEqual(name, "NL Reality")
        st = ob["streamSettings"]
        self.assertEqual(st["security"], "reality")
        self.assertEqual(st["realitySettings"]["publicKey"], PBK)
        self.assertEqual(ob["settings"]["flow"], "xtls-rprx-vision")

    def test_mux_skipped_with_vision(self):
        built = config_builder.build(Server(id="x", name="r", link=LINKS["vless-reality"]),
                                     Settings(mux=True), 1)
        self.assertNotIn("mux", built.config["outbounds"][0])

    def test_ss_variants(self):
        for key in ("ss-sip002", "ss-2022-plain", "ss-legacy"):
            _, ob = links.parse_link(LINKS[key])
            self.assertTrue(ob["settings"]["method"] and ob["settings"]["password"], key)

    def test_subscription_body_formats(self):
        plain = "\n".join(LINKS.values())
        self.assertEqual(len(subscription.parse_body(plain)[0]), len(LINKS))
        b64 = base64.b64encode(plain.encode()).decode()
        self.assertEqual(len(subscription.parse_body(b64)[0]), len(LINKS))
        cfgs = json.dumps([{"remarks": "A", "outbounds": [{"protocol": "freedom"}]},
                           {"remarks": "B", "outbounds": [{"protocol": "freedom"}]}])
        servers, _ = subscription.parse_body(cfgs)
        self.assertEqual([s.name for s in servers], ["A", "B"])
        self.assertTrue(all(s.is_full_config for s in servers))


class FullConfigTests(unittest.TestCase):
    PROVIDER = {
        "remarks": "Balancer",
        "routing": {"domainStrategy": "IPIfNonMatch",
                    "balancers": [{"tag": "bal", "selector": ["proxy"],
                                   "strategy": {"type": "leastLoad"}}],
                    "rules": [{"domain": ["domain:example.ru"], "outboundTag": "direct"},
                              {"network": "tcp,udp", "balancerTag": "bal"}]},
        "burstObservatory": {"subjectSelector": ["proxy"],
                             "pingConfig": {"destination": "http://www.gstatic.com/generate_204",
                                            "interval": "1m"}},
        "outbounds": [
            {"tag": "proxy", **{k: v for k, v in links.parse_link(LINKS["vless-reality"])[1].items()
                                if k != "tag"}},
            {"tag": "proxy-2", **{k: v for k, v in links.parse_link(LINKS["vless-xhttp"])[1].items()
                                  if k != "tag"}},
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "inbounds": [{"tag": "socks", "protocol": "socks", "port": 10808}],
    }

    def test_provider_config_kept(self):
        server = Server(id="x", name="b", config=self.PROVIDER)
        for vname, s in SETTING_VARIANTS.items():
            with self.subTest(settings=vname):
                built = config_builder.build(server, s, 1)
                cfg = built.config
                self.assertEqual(xray_ok(cfg), "")
                self.assertEqual(cfg["routing"]["balancers"], self.PROVIDER["routing"]["balancers"])
                self.assertIn("burstObservatory", cfg)
                self.assertEqual(built.proxy_tags, ["proxy", "proxy-2"])
                self.assertEqual("tun" in [i["tag"] for i in cfg["inbounds"]], s.tunnel_mode == "tun")

    def test_global_mode_keeps_balancer(self):
        """Provider routing off: provider's RU-direct rules go, the balancer stays."""
        server = Server(id="x", name="b", config=self.PROVIDER)
        cfg = config_builder.build(server, Settings(use_provider_routing=False), 1).config
        rules = cfg["routing"]["rules"]
        self.assertEqual(rules[-1].get("balancerTag"), "bal")
        self.assertFalse(any("domain:example.ru" in r.get("domain", []) for r in rules))
        self.assertEqual(xray_ok(cfg), "")

    def test_default_runs_provider_config_as_is(self):
        """Default = what the original launcher script did: only inbounds (and stats) change."""
        server = Server(id="x", name="b", config=self.PROVIDER)
        cfg = config_builder.build(server, Settings(), 1).config
        self.assertEqual(cfg["routing"], self.PROVIDER["routing"])
        self.assertEqual(cfg["outbounds"], self.PROVIDER["outbounds"])
        self.assertEqual(cfg["burstObservatory"], self.PROVIDER["burstObservatory"])
        self.assertNotIn("dns", cfg)

    def test_settings_migration_restores_provider_routing(self):
        import tempfile
        from pathlib import Path
        from nimbus import settings as settings_mod
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            f.write_text(json.dumps({"use_provider_routing": False, "http_port": 1234,
                                     "settings_version": 2}), "utf-8")
            old, settings_mod.SETTINGS_FILE = settings_mod.SETTINGS_FILE, f
            try:
                s = Settings.load()
                self.assertTrue(s.use_provider_routing)
                self.assertEqual(s.http_port, 1234)
                s.use_provider_routing = False
                s.save()
                self.assertFalse(Settings.load().use_provider_routing)  # a later choice sticks
            finally:
                settings_mod.SETTINGS_FILE = old

    def test_settings_migration_turns_fakedns_on(self):
        import tempfile
        from pathlib import Path
        from nimbus import settings as settings_mod
        self.assertTrue(Settings().fake_dns)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            f.write_text(json.dumps({"fake_dns": False, "settings_version": 3}), "utf-8")
            old, settings_mod.SETTINGS_FILE = settings_mod.SETTINGS_FILE, f
            try:
                s = Settings.load()
                self.assertTrue(s.fake_dns)
                s.fake_dns = False
                s.save()
                self.assertFalse(Settings.load().fake_dns)  # turning it off later sticks
            finally:
                settings_mod.SETTINGS_FILE = old


class ExitIpTests(unittest.TestCase):
    def _lookup(self, handler):
        import httpx
        from nimbus import exit_ip
        real, old_country = httpx.Client, exit_ip.country

        def client(**kw):
            kw.pop("proxy", None)
            return real(transport=httpx.MockTransport(handler), **kw)
        exit_ip.httpx.Client, exit_ip.country = client, lambda ip: None
        try:
            return exit_ip.lookup(None, attempts=1)
        finally:
            exit_ip.httpx.Client, exit_ip.country = real, old_country

    def test_own_endpoint_wins(self):
        """The VPN server sends Cloudflare's traffic out another address (78.17.84.98) than
        what sites see (31.207.5.18): ours must be the answer whenever it gives one."""
        import httpx

        def handler(request):
            if request.url.host == "zalchikmods.site":
                return httpx.Response(200, json={"ip": "2.27.202.125", "country": "DE"})
            return httpx.Response(200, text="ip=78.17.84.98\nloc=FI\n")
        # The server's fresh database names the country (geoip.dat said US for this one).
        self.assertEqual(self._lookup(handler), ("2.27.202.125", "DE"))

    def test_country_of_fallback_ip_from_own_database(self):
        import httpx

        def handler(request):
            if request.url.host == "zalchikmods.site":
                if request.url.params.get("ip") == "2.26.81.49":
                    return httpx.Response(200, json={"ip": "2.26.81.49", "country": "DE"})
                return httpx.Response(502)
            if request.url.host == "1.1.1.1":
                return httpx.Response(200, text="ip=2.26.81.49\nloc=XX\n")
            return httpx.Response(429)
        self.assertEqual(self._lookup(handler), ("2.26.81.49", "DE"))

    def test_fallback_when_own_endpoint_fails(self):
        import httpx

        def handler(request):
            if request.url.host == "1.1.1.1":
                return httpx.Response(200, text="fl=1\nip=2.26.81.49\nloc=DE\n")
            return httpx.Response(429)  # rate-limited, as free APIs do with a shared VPN exit
        self.assertEqual(self._lookup(handler), ("2.26.81.49", "DE"))

    def test_country_from_geoip_dat(self):
        from nimbus import exit_ip

        def field(num, payload):
            def varint(n):
                out = b""
                while n >= 0x80:
                    out += bytes([n & 0x7F | 0x80])
                    n >>= 7
                return out + bytes([n])
            return varint(num << 3 | 2) + varint(len(payload)) + payload

        def cidr(net, prefix):
            return field(2, field(1, ipaddress.ip_address(net).packed) + bytes([2 << 3, prefix]))
        data = (field(1, field(1, b"PRIVATE") + cidr("2.0.0.0", 8))
                + field(1, field(1, b"DE") + cidr("2.26.0.0", 16))
                + field(1, field(1, b"RU") + cidr("77.88.0.0", 18) + cidr("2a02:6b8::", 32)))
        cases = {"2.26.81.49": "DE", "77.88.8.8": "RU", "2a02:6b8::feed": "RU", "8.8.8.8": None,
                 "2.27.0.1": None}
        old = exit_ip._index
        try:
            exit_ip._index = exit_ip.build_index(data)
            for ip, want in cases.items():
                self.assertEqual(exit_ip.country_in(data, ip), want, ip)
                self.assertEqual(exit_ip.country(ip), want, ip)
        finally:
            exit_ip._index = old


class TunAndInstanceTests(unittest.TestCase):
    def test_tun_without_ipv6_is_ipv4_only(self):
        """With IPv6 off in Windows the adapter can't get an IPv6 address."""
        from nimbus.platform import current as winsys
        old = winsys.ipv6_enabled
        server = Server(id="x", name="r", link=LINKS["vless-reality"])
        try:
            for v6 in (False, True):
                winsys.ipv6_enabled = lambda v=v6: v
                tun = config_builder.build(server, Settings(tunnel_mode="tun"), 1).tun["inbounds"][0]
                self.assertEqual(any(":" in a for a in tun["address"]), v6)
                self.assertEqual(any(":" in a for a in tun["route_exclude_address"]), v6)
                self.assertEqual(tun["address"][0], config_builder.TUN_GATEWAY + "/24")
        finally:
            winsys.ipv6_enabled = old

    def test_tun_is_singbox_in_front_of_xray(self):
        """Throne's layout: sing-box TUN with its own stack, everything to Xray over SOCKS,
        Xray's sockets bound to the physical adapter."""
        server = Server(id="x", name="x", link=LINKS["vless-xhttp"])
        built = config_builder.build(server, Settings(tunnel_mode="tun"), 1, egress="Ethernet")
        cfg, tun = built.config, built.tun
        self.assertFalse(any(i["protocol"] == "tun" for i in cfg["inbounds"]))
        bridge = next(i for i in cfg["inbounds"] if i["tag"] == "tun")
        self.assertEqual((bridge["protocol"], bridge["listen"]), ("socks", "127.0.0.1"))
        self.assertTrue(bridge["sniffing"]["enabled"])
        out = next(o for o in tun["outbounds"] if o["tag"] == "xray")
        self.assertEqual(out["server_port"], bridge["port"])
        self.assertEqual(out["username"], bridge["settings"]["accounts"][0]["user"])
        inbound = tun["inbounds"][0]
        self.assertNotIn("stack", inbound)   # sing-tun's own stack, as in Throne
        self.assertTrue(inbound["auto_route"])
        self.assertFalse(inbound["strict_route"])
        self.assertEqual(tun["route"]["final"], "xray")
        self.assertEqual(tun["route"]["rules"][0]["process_name"], [paths.XRAY_EXE.name])
        self.assertIn({"protocol": "dns", "action": "hijack-dns"}, tun["route"]["rules"])
        for ob in cfg["outbounds"]:
            want = None if ob["protocol"] == "blackhole" else "Ethernet"
            self.assertEqual(ob.get("streamSettings", {}).get("sockopt", {}).get("interface"), want, ob["tag"])
        self.assertEqual(tun["dns"]["rules"][0], {"domain": ["x.example.com"], "action": "route",
                                                  "server": "dns-direct"})
        remote = tun["dns"]["servers"][0]
        self.assertEqual((remote["type"], remote["server"], remote["detour"]), ("https", "1.1.1.1", "xray"))
        self.assertEqual(xray_ok(cfg), "")
        self.assertIn(singbox_ok(tun), ("", "skip"))
        self.assertIsNone(config_builder.build(server, Settings(), 1).tun)

    def test_kill_switch_sends_xray_direct_dns_through_tunnel(self):
        """strict_route blocks port 53 outside the tunnel for every process but sing-box."""
        server = Server(id="x", name="x", link=LINKS["vless-reality"])
        s = Settings(tunnel_mode="tun", kill_switch=True, routing_mode="bypass_ru")
        built = config_builder.build(server, s, 1, egress="Wi-Fi")
        rule = next(r for r in built.config["routing"]["rules"] if r.get("inboundTag") == ["dns-internal"])
        self.assertEqual(rule["outboundTag"], config_builder.TUN_DNS_OUT)
        dns_out = next(o for o in built.config["outbounds"] if o["tag"] == config_builder.TUN_DNS_OUT)
        self.assertNotIn("streamSettings", dns_out)
        self.assertTrue(built.tun["inbounds"][0]["strict_route"])
        self.assertEqual(xray_ok(built.config), "")
        self.assertIn(singbox_ok(built.tun), ("", "skip"))

    def test_preset_apps_routed_by_singbox(self):
        """Behind the bridge Xray only sees sing-box, so app rules live in sing-box."""
        apps = PresetTests.PRESET["apps"]
        server = Server(id="x", name="x", link=LINKS["vless-reality"])
        for mode, out in (("bypass", "direct"), ("vpn", "xray-app")):
            with self.subTest(mode=mode):
                s = Settings(tunnel_mode="tun", route_preset="p",
                             route_presets=[{"id": "p", "name": "p", "mode": mode, "apps": apps, "sites": []}])
                built = config_builder.build(server, s, 1)
                rule = built.tun["route"]["rules"][1]
                self.assertEqual(rule["outbound"], out)
                self.assertEqual(rule["process_name"], ["steam.exe", "cs2.exe"])
                self.assertEqual(rule["process_path_regex"], [r"(?i)^D:\\Games\\CS\\" if sys.platform == "win32"
                                                              else r"(?i)^D:/Games/CS/"])
                app_in = [i for i in built.config["inbounds"] if i["tag"] == "tun-app"]
                self.assertEqual(bool(app_in), mode == "vpn")
                if mode == "vpn":
                    rules = built.config["routing"]["rules"]
                    self.assertLess(rules.index({"inboundTag": ["tun-app"], "outboundTag": "proxy"}),
                                    rules.index({"network": "tcp,udp", "outboundTag": "direct"}))
                    port = next(o for o in built.tun["outbounds"] if o["tag"] == "xray-app")["server_port"]
                    self.assertEqual(port, app_in[0]["port"])
                self.assertEqual(xray_ok(built.config), "")
                self.assertIn(singbox_ok(built.tun), ("", "skip"))

    def test_dns_address_formats(self):
        f = config_builder._sb_dns
        self.assertEqual(f("8.8.8.8", True), {"type": "https", "server": "8.8.8.8", "path": "/dns-query"})
        self.assertEqual(f("77.88.8.8", True), {"type": "tcp", "server": "77.88.8.8"})
        self.assertEqual(f("8.8.8.8", False), {"type": "udp", "server": "8.8.8.8"})
        self.assertEqual(f("tcp://1.2.3.4:5353", False), {"type": "tcp", "server": "1.2.3.4", "server_port": 5353})
        self.assertEqual(f("quic+local://dns.adguard.com", False),
                         {"type": "quic", "server": "dns.adguard.com", "domain_resolver": "dns-local"})
        self.assertEqual(f("localhost", False), {"type": "local"})

    def test_default_egress_found(self):
        from nimbus.platform import current as winsys
        found = winsys.default_egress(config_builder.TUN_NAME)
        if found is None:
            self.skipTest("no default route on this machine")
        self.assertTrue(found[0])

    def test_all_tun_configs_validate_in_singbox(self):
        if not paths.SINGBOX_EXE.exists():
            self.skipTest("sing-box.exe not in vendor/xray")
        servers = [Server(id=k, name=k, link=v) for k, v in LINKS.items()]
        servers.append(Server(id="p", name="p", config=FullConfigTests.PROVIDER))
        for srv in servers:
            for vname, s in SETTING_VARIANTS.items():
                if s.tunnel_mode != "tun":
                    continue
                with self.subTest(server=srv.id, settings=vname):
                    self.assertEqual(singbox_ok(config_builder.build(srv, s, 1, egress="Ethernet").tun), "")

    def test_single_instance_lock(self):
        from nimbus.platform import current as osys
        if sys.platform == "win32":
            import ctypes

            def release(h):
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
        else:
            release = os.close
        name = f"nimbus-test-{id(self)}"
        first = osys.single_instance_lock(name)
        self.assertTrue(first)
        self.assertIsNone(osys.single_instance_lock(name))
        release(first)
        again = osys.single_instance_lock(name)
        self.assertTrue(again)
        release(again)


class GroupAndRoutingTests(unittest.TestCase):
    def test_provider_routing_detection(self):
        ru = Server(id="a", name="a", config={
            "outbounds": [{"tag": "proxy", "protocol": "vless"}, {"tag": "direct", "protocol": "freedom"}],
            "routing": {"rules": [{"ip": ["geoip:private"], "outboundTag": "direct"},
                                  {"domain": ["geosite:category-ru"], "outboundTag": "direct"}]}})
        local_only = Server(id="b", name="b", config={
            "outbounds": [{"tag": "proxy", "protocol": "vless"}, {"tag": "direct", "protocol": "freedom"}],
            "routing": {"rules": [{"ip": ["geoip:private", "192.168.0.0/16"], "outboundTag": "direct"}]}})
        link = Server(id="c", name="c", link=LINKS["vless-reality"])
        self.assertEqual(config_builder.provider_routing(ru), {"ru": True})
        self.assertIsNone(config_builder.provider_routing(local_only))
        self.assertIsNone(config_builder.provider_routing(link))

    def test_groups_store_roundtrip(self):
        import tempfile
        from pathlib import Path
        from nimbus import store as store_mod
        with tempfile.TemporaryDirectory() as d:
            old, store_mod.PROFILES_FILE = store_mod.PROFILES_FILE, Path(d) / "profiles.json"
            try:
                st = store_mod.Store(groups=[store_mod.Group(id="g1", name="Работа")],
                                     servers=[Server(id="s1", name="x", sub_id="g1", link=LINKS["vless-reality"]),
                                              Server(id="s2", name="y", link=LINKS["vless-reality"])])
                st.save()
                st = store_mod.Store.load()
                self.assertEqual(st.group("g1").name, "Работа")
                self.assertEqual([s.id for s in st.servers_of("g1")], ["s1"])
                st.remove_group("g1")
                self.assertEqual([s.id for s in st.servers], ["s2"])
            finally:
                store_mod.PROFILES_FILE = old


class FlagTests(unittest.TestCase):
    def test_flag_split_and_sort_key(self):
        from nimbus.ui import flags
        self.assertEqual(flags.split("🇪🇺 ⚡️ Быстрый | АВТО"), ("EU", "⚡️ Быстрый | АВТО"))
        self.assertEqual(flags.split(" 🇳🇱 Нидерланды | 5 гб/c")[0], "NL")
        self.assertEqual(flags.split("Обход LTE | Нидерланды • 🟢")[0], "NL")
        self.assertIsNone(flags.split("YouTube без рекламы")[0])
        names = ["🇪🇺 ⚡️ Быстрый", "🇦🇲 Армения", "⭐ Болгария", "  🇩🇪 Германия"]
        self.assertEqual(sorted(names, key=flags.sort_key),
                         ["🇦🇲 Армения", "⭐ Болгария", "🇪🇺 ⚡️ Быстрый", "  🇩🇪 Германия"])


class ShareTests(unittest.TestCase):
    def test_links_roundtrip_through_outbounds(self):
        from nimbus import share
        for label, link in LINKS.items():
            with self.subTest(link=label):
                name, ob = links.parse_link(link)
                again = share.outbound_link(ob, name)
                self.assertIsNotNone(again)
                name2, ob2 = links.parse_link(again)
                self.assertEqual(name2, name)
                self.assertEqual(ob2["settings"], ob["settings"])
                self.assertEqual(ob2.get("streamSettings"), ob.get("streamSettings"))

    def test_provider_config_shares_main_node(self):
        from nimbus import share
        srv = Server(id="p", name="🇳🇱 Авто", config=FullConfigTests.PROVIDER)
        link = share.server_link(srv)
        self.assertTrue(link.startswith("vless://") and link.endswith("#%F0%9F%87%B3%F0%9F%87%B1%20%D0%90%D0%B2%D1%82%D0%BE"))
        self.assertEqual(links.parse_link(link)[1]["settings"]["address"], "1.2.3.4")
        self.assertEqual(share.node_count(srv), 2)
        self.assertEqual(share.server_json(srv, Settings())["routing"]["balancers"][0]["tag"], "bal")
        link_srv = Server(id="l", name="mine", link=LINKS["trojan"])
        cfg = share.server_json(link_srv, Settings(tunnel_mode="tun"))
        self.assertEqual(cfg["remarks"], "mine")
        self.assertNotIn("metrics", cfg)
        self.assertFalse(any(i["protocol"] == "tun" for i in cfg["inbounds"]))
        self.assertEqual(xray_ok(cfg), "")
        text, skipped = share.export_links([srv, link_srv])
        self.assertEqual((len(text.splitlines()), skipped), (2, 0))
        many = share.export_json([srv, link_srv], Settings())
        self.assertEqual([c["remarks"] for c in many], ["Balancer", "mine"])  # provider name kept
        self.assertEqual(share.export_json([link_srv], Settings())["remarks"], "mine")

    def test_qr_codes_decode(self):
        from nimbus import qr
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV not installed")
        for text in (LINKS["vless-reality"], "https://sub.example.com/abc", "x" * 900):
            code = qr.encode(text)
            n = code.size + 8
            img = np.full((n, n), 255, np.uint8)
            for y, row in enumerate(code.modules):
                for x, dark in enumerate(row):
                    if dark:
                        img[y + 4, x + 4] = 0
            decoded = ""
            for scale in (4, 6, 8):
                big = cv2.resize(img, (n * scale, n * scale), interpolation=cv2.INTER_NEAREST)
                for det in (cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()):
                    decoded = decoded or det.detectAndDecode(big)[0]
            self.assertEqual(decoded, text)


class PresetTests(unittest.TestCase):
    PRESET = {"id": "p1", "name": "Игры", "mode": "bypass", "provider": True,
              "apps": [{"name": "Steam", "path": r"C:\Program Files (x86)\Steam\steam.exe", "kind": "exe"},
                       {"name": "CS2", "path": r"D:\Games\CS", "kind": "dir", "exes": ["cs2.exe"]}],
              "sites": ["store.steampowered.com", "https://www.twitch.tv/x", "*.valve.net", "1.2.3.0/24",
                        "geoip:ru", "geosite:youtube", "не сайт"]}

    def test_site_entries(self):
        e = config_builder.site_entry
        self.assertEqual(e("https://www.twitch.tv/x"), ("domain", "domain:www.twitch.tv"))
        self.assertEqual(e("*.Valve.net"), ("domain", "domain:valve.net"))
        self.assertEqual(e("1.2.3.0/24"), ("ip", "1.2.3.0/24"))
        self.assertEqual(e("GeoIP:RU"), ("ip", "geoip:ru"))
        self.assertEqual(e("geosite:youtube"), ("domain", "geosite:youtube"))
        self.assertIsNone(e("не сайт"))

    def test_app_matchers_cover_case(self):
        values = config_builder.app_matchers(self.PRESET["apps"])
        self.assertEqual(values, ["steam.exe", "D:/Games/CS/", "d:/games/cs/", "cs2.exe"])

    def test_presets_build_and_validate(self):
        s = Settings(route_presets=[self.PRESET, {**self.PRESET, "id": "p2", "mode": "vpn"}])
        provider = Server(id="p", name="p", config=FullConfigTests.PROVIDER)
        link = Server(id="l", name="l", link=LINKS["vless-reality"])
        for pid in ("p1", "p2"):
            for srv in (provider, link):
                for mode in ("proxy", "tun"):
                    with self.subTest(preset=pid, server=srv.id, mode=mode):
                        cfg = config_builder.build(srv, replace(s, route_preset=pid, tunnel_mode=mode), 1).config
                        self.assertEqual(xray_ok(cfg), "")
                        rules = cfg["routing"]["rules"]
                        proc = next(r for r in rules if "process" in r)
                        if pid == "p1":
                            self.assertEqual(proc["outboundTag"], "direct")
                        else:
                            self.assertNotEqual(proc.get("outboundTag"), "direct")
                            self.assertEqual(rules[-1], {"network": "tcp,udp", "outboundTag": "direct"})
                        self.assertEqual(cfg["routing"]["domainStrategy"], "IPIfNonMatch")
        # bypass on top of the provider's rules keeps them
        cfg = config_builder.build(provider, replace(s, route_preset="p1"), 1).config
        self.assertIn({"domain": ["domain:example.ru"], "outboundTag": "direct"}, cfg["routing"]["rules"])

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcuts")
    def test_lnk_parsing(self):
        from nimbus.platform import apps_windows as apps
        roots = apps._shortcut_dirs()
        import glob
        lnks = [p for r in roots for p in glob.glob(os.path.join(r, "**", "*.lnk"), recursive=True)][:50]
        if not lnks:
            self.skipTest("no shortcuts on this machine")
        targets = [apps.lnk_target(p) for p in lnks]
        self.assertTrue(any(t and t[0].lower().endswith(".exe") for t in targets))


class ProxyEnvTests(unittest.TestCase):
    def test_env_proxy_set_and_restored(self):
        """Claude Code and other console programs ignore the Windows proxy and read HTTPS_PROXY;
        whatever the user had comes back on disconnect, after a crash too."""
        from pathlib import Path
        from nimbus import core
        from nimbus.platform import current as winsys
        # Windows keeps [value, registry type], Linux plain strings.
        corp = ["http://corp:3128", 1] if sys.platform == "win32" else "http://corp:3128"

        def value(v):
            return v[0] if isinstance(v, list) else v
        reg = {name: None for name in winsys.ENV_VARS}
        reg["HTTPS_PROXY"] = corp
        before = dict(reg)
        saved = (winsys.read_env_proxy, winsys.write_env_proxy, core.ENV_BACKUP, dict(os.environ))
        with tempfile.TemporaryDirectory() as d:
            winsys.read_env_proxy = lambda: dict(reg)
            winsys.write_env_proxy = lambda values: reg.update(values)
            core.ENV_BACKUP = Path(d) / "env_backup.json"
            try:
                core.ENV_BACKUP.write_text(json.dumps(winsys.read_env_proxy()), "utf-8")
                winsys.enable_env_proxy(10809)
                self.assertEqual(value(reg["HTTPS_PROXY"]), "http://127.0.0.1:10809")
                self.assertIn("127.0.0.1", value(reg["NO_PROXY"]))
                os.environ["HTTP_PROXY"] = "http://127.0.0.1:10809"   # inherited by a fresh start
                core.restore_proxy_after_crash()
                self.assertEqual(reg, before)
                self.assertNotIn("HTTP_PROXY", os.environ)
                self.assertFalse(core.ENV_BACKUP.exists())
            finally:
                winsys.read_env_proxy, winsys.write_env_proxy, core.ENV_BACKUP, env = saved
                os.environ.clear()
                os.environ.update(env)


class ProxyRestoreTests(unittest.TestCase):
    def test_dead_local_proxy_is_not_restored_linux(self):
        """GNOME and KDE snapshots: a proxy at a dead local port isn't put back."""
        import socket
        from nimbus.platform import linux
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        saved = {"gnome": {"mode": "'manual'", "http.host": "'127.0.0.1'", "http.port": str(dead)},
                 "kde": {"ProxyType": "1", "httpProxy": f"http://127.0.0.1 {dead}"}}
        out = linux.without_dead_local_proxy(saved)
        self.assertEqual((out["gnome"]["mode"], out["kde"]["ProxyType"]), ("'none'", "0"))
        self.assertEqual(saved["gnome"]["mode"], "'manual'")   # the snapshot itself is left alone
        corporate = {"gnome": {"mode": "'manual'", "http.host": "'proxy.corp'", "http.port": "3128"}}
        self.assertEqual(linux.without_dead_local_proxy(corporate)["gnome"]["mode"], "'manual'")

    @unittest.skipUnless(sys.platform == "win32", "Windows registry")
    def test_dead_local_proxy_is_not_restored(self):
        import socket
        import winreg
        from nimbus.platform import current as winsys
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]  # closed after the block: nothing listens there
        saved = {"ProxyEnable": [1, winreg.REG_DWORD], "ProxyServer": [f"127.0.0.1:{dead}", 1],
                 "ProxyOverride": None}
        self.assertEqual(winsys.without_dead_local_proxy(saved)["ProxyEnable"][0], 0)
        with socket.socket() as live:
            live.bind(("127.0.0.1", 0))
            live.listen()
            saved["ProxyServer"] = [f"127.0.0.1:{live.getsockname()[1]}", 1]
            self.assertEqual(winsys.without_dead_local_proxy(saved)["ProxyEnable"][0], 1)
        corporate = {**saved, "ProxyServer": ["proxy.corp.local:3128", 1]}
        self.assertEqual(winsys.without_dead_local_proxy(corporate)["ProxyEnable"][0], 1)


class BalancerTests(unittest.TestCase):
    def _store(self) -> Store:
        st = Store(subscriptions=[Subscription(id="sub", url="https://panel.example.com/sub")])
        st.servers = [Server(id=f"l{i}", name=k, link=v) for i, (k, v) in enumerate(LINKS.items())]
        st.servers += [Server(id="p1", name="prov 1", sub_id="sub", config=FullConfigTests.PROVIDER),
                       Server(id="p2", name="prov 2", sub_id="sub", config=FullConfigTests.PROVIDER)]
        return st

    def test_mixed_servers_validate_without_provider_rules(self):
        st = self._store()
        bal = Balancer(id="b", name="Все", server_ids=[s.id for s in st.servers])
        for vname, s in SETTING_VARIANTS.items():
            with self.subTest(settings=vname):
                srv = balancer.as_server(bal, st, s)
                self.assertIsNone(config_builder.provider_routing(srv))
                built = config_builder.build(srv, s, 1, egress="Ethernet")
                self.assertEqual(xray_ok(built.config), "")
                routing = built.config["routing"]
                self.assertEqual(routing["balancers"][0]["tag"], balancer.TAG)
                self.assertEqual(routing["rules"][-1].get("balancerTag"), balancer.TAG)

    def test_one_subscription_keeps_provider_rules(self):
        st = self._store()
        srv = balancer.as_server(Balancer(id="b", name="Провайдер", sub_ids=["sub"]), st, Settings())
        self.assertIsNotNone(config_builder.provider_routing(srv))
        rules = srv.config["routing"]["rules"]
        self.assertIn({"domain": ["domain:example.ru"], "outboundTag": "direct"}, rules)
        self.assertEqual(xray_ok(config_builder.build(srv, Settings(), 1).config), "")

    def test_nodes_and_helpers_tagged_apart(self):
        st = self._store()
        cfg = balancer.as_server(Balancer(id="b", name="x", server_ids=["l0", "p1"]), st,
                                 Settings(fragment=True)).config
        tags = [o["tag"] for o in cfg["outbounds"]]
        self.assertEqual(len(tags), len(set(tags)))
        nodes = [t for t in tags if t.startswith(balancer.PREFIX)]
        self.assertEqual(nodes, ["nimbus-auto-0-proxy", "nimbus-auto-1-proxy", "nimbus-auto-1-proxy-2"])
        self.assertIn(balancer.FRAGMENT, tags)

    def test_whole_subscription_takes_new_servers(self):
        st = self._store()
        bal = Balancer(id="b", name="x", sub_ids=["sub"], server_ids=["l0"])
        self.assertEqual([m.id for m in st.members(bal)], ["l0", "p1", "p2"])
        st.servers.append(Server(id="p3", name="prov 3", sub_id="sub", config=FullConfigTests.PROVIDER))
        self.assertIn("p3", [m.id for m in st.members(bal)])

    def test_current_node(self):
        members = [Server(id="a", name="A"), Server(id="b", name="B")]
        obs = {"nimbus-auto-0-proxy": {"alive": True, "delay": 120},
               "nimbus-auto-1-proxy": {"alive": True, "delay": 40},
               "nimbus-auto-1-proxy-2": {"health_ping": {"all": 2, "fail": 2}}}
        self.assertEqual(balancer.current_node(obs, members).name, "B")
        self.assertIsNone(balancer.current_node({"nimbus-auto-0-proxy": {}}, members))

    def test_stable_mode_keeps_node_unless_much_faster(self):
        def obs(**delays):
            return {f"nimbus-auto-{k[1:]}-proxy": ({"alive": True, "delay": v} if v else {})
                    for k, v in delays.items()}
        cur = "nimbus-auto-0-proxy"
        # 40 ms (20%) faster: jitter, not worth a new IP
        self.assertEqual(balancer.pick_stable(obs(n0=200, n1=160), cur), cur)
        # 30% but only 30 ms: still stays
        self.assertEqual(balancer.pick_stable(obs(n0=100, n1=70), cur), cur)
        # 150 ms and 50% faster: moves
        self.assertEqual(balancer.pick_stable(obs(n0=300, n1=150), cur), "nimbus-auto-1-proxy")
        # current one stopped answering: moves to the fastest alive
        self.assertEqual(balancer.pick_stable(obs(n0=0, n1=400, n2=250), cur), "nimbus-auto-2-proxy")
        # nothing answers: stays put; nothing chosen yet: the fastest
        self.assertEqual(balancer.pick_stable(obs(n0=0, n1=0), cur), cur)
        self.assertEqual(balancer.pick_stable(obs(n0=90, n1=80), None), "nimbus-auto-1-proxy")

    def test_api_config_validates(self):
        st = self._store()
        s = Settings()
        built = config_builder.build(balancer.as_server(Balancer(id="b", name="x", sub_ids=["sub"]), st, s), s, 1)
        balancer.enable_api(built.config, 12399)
        self.assertEqual(xray_ok(built.config), "")

    def test_plain_names(self):
        self.assertEqual(balancer.plain("\U0001F1F3\U0001F1F1 Нидерланды"), "Нидерланды")
        self.assertEqual(balancer.plain("Без флага"), "Без флага")


class UpdaterTests(unittest.TestCase):
    RELEASE = {"tag_name": "v0.3.0", "draft": False, "prerelease": False, "body": "## Что нового\n- всё",
               "published_at": "2026-10-16T09:17:44Z",
               "html_url": "https://github.com/Zalchik/nimbus/releases/v0.3.0",
               "assets": [{"name": "Nimbus-0.3.0-setup.exe", "size": 5,
                           "browser_download_url": "https://example.com/Nimbus-0.3.0-setup.exe"},
                          {"name": "SHA256SUMS.txt", "size": 90,
                           "browser_download_url": "https://example.com/SHA256SUMS.txt"}]}

    def test_versions(self):
        from nimbus import updater
        self.assertEqual(updater.parse_version("v0.2.10"), (0, 2, 10))
        self.assertIsNone(updater.parse_version("v0.3.0-beta"))
        self.assertIsNone(updater.parse_version("latest"))
        self.assertTrue(updater.is_newer("v0.2.10", "0.2.9"))
        self.assertTrue(updater.is_newer("0.3", "0.2.9"))
        self.assertFalse(updater.is_newer("v0.2.0", "0.2.0"))
        self.assertFalse(updater.is_newer("0.2", "0.2.0"))
        self.assertFalse(updater.is_newer("0.1.9", "0.2.0"))
        self.assertFalse(updater.is_newer("nightly", "0.2.0"))

    def test_release_parsing(self):
        from nimbus import updater
        r = updater.parse_release(self.RELEASE)
        self.assertEqual((r.version, r.tag), ("0.3.0", "v0.3.0"))
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M", time.gmtime(r.published)), "2026-10-16 09:17")
        self.assertEqual(r.assets["Nimbus-0.3.0-setup.exe"].size, 5)
        self.assertIsNone(updater.parse_release({**self.RELEASE, "draft": True}))
        self.assertIsNone(updater.parse_release({**self.RELEASE, "prerelease": True}))
        self.assertEqual(updater.asset_name("0.3.0", "setup"), "Nimbus-0.3.0-setup.exe")
        self.assertEqual(updater.asset_name("0.3.0", "portable"), "Nimbus-0.3.0-portable.zip")

    def test_checksums_and_verify(self):
        from nimbus import updater
        h = "a" * 64
        text = f"{h}  Nimbus-0.3.0-setup.exe\r\n{'B' * 64} *Nimbus-0.3.0-portable.zip\ngarbage line\n"
        self.assertEqual(updater.parse_checksums(text),
                         {"Nimbus-0.3.0-setup.exe": h, "Nimbus-0.3.0-portable.zip": "b" * 64})
        updater.verify(5, h, 5, h.upper())
        updater.verify(5, h, 0, "")   # nothing known: nothing to check
        with self.assertRaises(updater.UpdateError):
            updater.verify(4, h, 5, h)
        with self.assertRaises(updater.UpdateError):
            updater.verify(5, "c" * 64, 5, h)

    def test_setup_args_are_silent(self):
        from nimbus import updater
        args = updater.setup_args(Path("C:/t/Nimbus-0.3.0-setup.exe"), connect=True)
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NIMBUSRESTART=connect"):
            self.assertIn(flag, args)

    def _download(self, files: dict, release: dict):
        """updater.download against a fake GitHub serving `files` by name."""
        import httpx
        from nimbus import updater

        def handler(request):
            name = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=files[name]) if name in files else httpx.Response(404)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        old_work = updater.WORK_DIR
        with tempfile.TemporaryDirectory() as tmp:
            updater.WORK_DIR = Path(tmp)
            updater.httpx.get = lambda url, **kw: client.get(url, headers=kw.get("headers"))
            updater.httpx.stream = lambda method, url, **kw: client.stream(method, url, headers=kw.get("headers"))
            try:
                seen = []
                path = updater.download(updater.parse_release(release), "setup",
                                        progress=lambda d, t: seen.append(d))
                return path.read_bytes(), seen
            finally:
                updater.WORK_DIR = old_work
                del updater.httpx.get, updater.httpx.stream   # back to the real module's

    def test_download_checks_sha256(self):
        import hashlib
        from nimbus import updater
        data = b"hello"
        good = f"{hashlib.sha256(data).hexdigest()}  Nimbus-0.3.0-setup.exe\n".encode()
        got, seen = self._download({"Nimbus-0.3.0-setup.exe": data, "SHA256SUMS.txt": good}, self.RELEASE)
        self.assertEqual(got, data)
        self.assertEqual(seen[-1], 5)
        bad = f"{'0' * 64}  Nimbus-0.3.0-setup.exe\n".encode()
        with self.assertRaises(updater.UpdateError):
            self._download({"Nimbus-0.3.0-setup.exe": data, "SHA256SUMS.txt": bad}, self.RELEASE)
        # Without a checksum file only the size is checked.
        no_sums = {**self.RELEASE, "assets": self.RELEASE["assets"][:1]}
        self.assertEqual(self._download({"Nimbus-0.3.0-setup.exe": data}, no_sums)[0], data)
        with self.assertRaises(updater.UpdateError):
            self._download({"Nimbus-0.3.0-setup.exe": b"hell"}, no_sums)

    def test_unpack_rejects_paths_outside(self):
        import zipfile
        from nimbus import updater
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.zip"
            with zipfile.ZipFile(good, "w") as z:
                z.writestr(f"Nimbus/{Path(sys.executable).name}", b"exe")
                z.writestr("Nimbus/portable", b"")
            self.assertEqual(updater.unpack(good).name, "Nimbus")
            bad = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("../evil.txt", b"x")
            with self.assertRaises(updater.UpdateError):
                updater.unpack(bad)
            self.assertFalse((Path(tmp) / "evil.txt").exists())


class SwapTests(unittest.TestCase):
    @staticmethod
    def _tree(root: Path, files: dict) -> None:
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, "utf-8")

    @staticmethod
    def _read(root: Path) -> dict:
        return {p.relative_to(root).as_posix(): p.read_text("utf-8") for p in root.rglob("*") if p.is_file()}

    def _dirs(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, dst = Path(tmp.name) / "new", Path(tmp.name) / "app"
        self._tree(src, {"Nimbus.exe": "new exe", "_internal/b.dll": "b", "core/xray.exe": "x2",
                         "portable": "marker from the zip", "data/settings.json": "{}"})
        self._tree(dst, {"Nimbus.exe": "old exe", "_internal/a.dll": "a", "core/xray.exe": "x1",
                         "portable": "my marker", "data/settings.json": '{"mine": 1}', "data/logs/l.txt": "log"})
        return src, dst

    def test_replace_keeps_data_and_marker(self):
        from nimbus import swap
        src, dst = self._dirs()
        swap.replace(src, dst)
        self.assertEqual(self._read(dst), {"Nimbus.exe": "new exe", "_internal/b.dll": "b", "core/xray.exe": "x2",
                                           "portable": "my marker", "data/settings.json": '{"mine": 1}',
                                           "data/logs/l.txt": "log"})

    def test_failed_copy_rolls_back(self):
        from nimbus import swap
        src, dst = self._dirs()
        before = self._read(dst)
        calls = []

        def copy(a, b):
            calls.append(a.name)
            if len(calls) == 2:
                raise PermissionError("locked")
            swap._copy(a, b)
        with self.assertRaises(PermissionError):
            swap.replace(src, dst, copy=copy)
        self.assertEqual(self._read(dst), before)
        self.assertFalse((dst / swap.BACKUP).exists())

    def test_wait_for_exit(self):
        from nimbus import swap
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        self.assertFalse(swap.wait_for_exit(p.pid, timeout=0.05))
        self.assertTrue(swap.wait_for_exit(p.pid, timeout=10))
        p.wait()


class DeepLinkTests(unittest.TestCase):
    SUB = "https://panel.example.com/sub/AbC?x=1&y=2"

    def test_formats(self):
        from urllib.parse import quote
        from nimbus import deeplink
        enc = quote(self.SUB, safe="")
        for text in (f"nimbus://import/{self.SUB}", f"nimbus://import/{enc}", f"NIMBUS://import?url={enc}",
                     f"happ://add/{self.SUB}", f"v2rayn://install-sub?url={enc}&name=My",
                     f"clash://install-config?url={enc}", f"sing-box://import-remote-profile?url={enc}#My"):
            link = deeplink.parse(text)
            self.assertEqual((link.kind, link.payload), ("subscription", self.SUB), text)
        self.assertEqual(deeplink.parse(f"v2rayn://install-sub?url={enc}&name=My").name, "My")
        self.assertEqual(deeplink.parse(f"sing-box://import-remote-profile?url={enc}#My").name, "My")

    def test_configs_crypt_and_others(self):
        from urllib.parse import quote
        from nimbus import deeplink
        vless = LINKS["vless-reality"]
        self.assertEqual(deeplink.parse("nimbus://import/" + quote(vless, safe="")).kind, "configs")
        for crypt in ("happ://crypt/abcdef", "happ://crypt2/abc", "happ://crypt5/xyz", "HAPP://CRYPT3/q"):
            self.assertEqual(deeplink.parse(crypt).kind, "crypt", crypt)
        self.assertEqual(deeplink.parse("nimbus://import/not a link").kind, "invalid")
        self.assertEqual(deeplink.parse("v2rayn://install-sub").kind, "invalid")
        self.assertIsNone(deeplink.parse(self.SUB))
        self.assertIsNone(deeplink.parse(vless))
        self.assertEqual(deeplink.from_args(["--autostart", "nimbus://import/x"]), "nimbus://import/x")
        self.assertEqual(deeplink.from_args(["--connect"]), "")

    def test_url_scheme_registration(self):
        if sys.platform != "win32":
            self.skipTest("Windows registry")
        from nimbus.platform import current as winsys
        scheme = "nimbus-test-scheme"
        try:
            winsys.register_url_scheme(scheme, "Nimbus test")
            self.assertTrue(winsys.url_scheme_command(scheme).endswith('"%1"'))
            self.assertIn(Path(sys.executable).name.lower(), winsys.url_scheme_command(scheme).lower())
        finally:
            winsys.unregister_url_scheme(scheme)
        self.assertEqual(winsys.url_scheme_command(scheme), "")


class I18nTests(unittest.TestCase):
    @staticmethod
    def _source_texts():
        """Every tr("…") text and plural() "one" form in nimbus/."""
        import ast
        texts, plurals = set(), set()
        root = Path(__file__).resolve().parent.parent / "nimbus"
        for f in root.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            for node in ast.walk(ast.parse(f.read_text("utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name == "tr" and node.args and isinstance(node.args[0], ast.Constant):
                    ctx = next((k.value.value for k in node.keywords if k.arg == "ctx"), "")
                    texts.add(f"{ctx}|{node.args[0].value}" if ctx else node.args[0].value)
                elif name == "plural" and len(node.args) == 4 and isinstance(node.args[1], ast.Constant):
                    plurals.add(node.args[1].value)
        return texts, plurals

    def test_english_covers_every_text(self):
        from nimbus import locale_en
        texts, plurals = self._source_texts()
        self.assertGreater(len(texts), 300)
        self.assertEqual(sorted(texts - set(locale_en.TEXTS)), [], "texts without an English translation")
        self.assertEqual(sorted(plurals - set(locale_en.PLURALS)), [], "plural forms without English")

    def test_placeholders_match(self):
        import string
        from nimbus import locale_en

        def fields(text):
            return sorted(f for _, f, _, _ in string.Formatter().parse(text) if f is not None)
        for ru, en in locale_en.TEXTS.items():
            self.assertEqual(fields(ru), fields(en), ru)
            self.assertNotRegex(en, "[А-Яа-яЁё]", ru)

    def test_tr_and_plural(self):
        from nimbus import i18n
        old = i18n.LANG
        try:
            i18n.set_language("ru")
            self.assertEqual(i18n.tr("Добавлено серверов: {n}", n=3), "Добавлено серверов: 3")
            self.assertEqual([i18n.plural(n, "сервер", "сервера", "серверов") for n in (1, 2, 5, 11, 21, 112)],
                             ["сервер", "сервера", "серверов", "серверов", "сервер", "серверов"])
            i18n.set_language("en")
            self.assertEqual(i18n.tr("Добавлено серверов: {n}", n=3), "Servers added: 3")
            self.assertEqual(i18n.tr("Текста нет в словаре"), "Текста нет в словаре")
            self.assertEqual([i18n.plural(n, "сервер", "сервера", "серверов") for n in (1, 2, 21)],
                             ["server", "servers", "servers"])
        finally:
            i18n.set_language(old)

    def test_language_choice(self):
        from nimbus import i18n
        self.assertEqual(i18n.resolve("en"), "en")
        self.assertEqual(i18n.resolve("ru"), "ru")
        self.assertIn(i18n.resolve("auto"), i18n.LANGUAGES)
        self.assertEqual(Settings().language, "auto")


class PlatformTests(unittest.TestCase):
    """The Windows and Linux modules offer the same interface. The Linux module loads on any
    system, so most of its logic is checked here too."""
    INTERFACE = {
        "OS_NAME", "POPEN", "POPEN_BACKGROUND", "UI_FONTS", "MONO_FONTS", "TUN_RELAUNCH", "BIND_EGRESS",
        "ENV_VARS", "exe_name", "data_dir", "machine_id",
        "read_proxy", "write_proxy", "enable_proxy", "disable_proxy", "without_dead_local_proxy",
        "read_env_proxy", "write_env_proxy", "enable_env_proxy", "default_egress", "ipv6_enabled",
        "is_admin", "tun_allowed", "grant_tun", "singbox_path", "relaunch_as_admin",
        "background_thread", "trim_memory", "process_age_ms", "app_command", "relaunch", "single_instance_lock",
        "set_autostart", "autostart_is_this_exe", "register_url_scheme", "unregister_url_scheme",
        "url_scheme_command", "title_bar",
    }
    APPS = {"App", "scan", "running", "fill_icons", "from_path", "main_exe", "entry"}

    @staticmethod
    def _names(module: str) -> set:
        import ast
        path = Path(__file__).resolve().parent.parent / "nimbus" / "platform" / f"{module}.py"
        out = set()
        for node in ast.parse(path.read_text("utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                out.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                out |= {t.id for t in targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.ImportFrom):
                out |= {a.asname or a.name for a in node.names}
        return out

    def test_same_interface(self):
        for module in ("windows", "linux"):
            self.assertEqual(self.INTERFACE - self._names(module), set(), module)
        for module in ("apps_windows", "apps_linux"):
            self.assertEqual(self.APPS - self._names(module), set(), module)

    def test_linux_routes(self):
        from nimbus.platform import linux
        table = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                 "Nimbus\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"
                 "wlp2s0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
                 "enp3s0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
                 "enp3s0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")
        self.assertEqual(linux.parse_routes(table, "Nimbus"), ("enp3s0", False))
        self.assertIsNone(linux.parse_routes(table.splitlines()[0], "Nimbus"))

    def test_linux_desktop_entries(self):
        from nimbus.platform import apps_linux, linux
        with tempfile.TemporaryDirectory() as d:
            entry = Path(d) / "x.desktop"
            entry.write_text("[Desktop Entry]\nType=Application\nName=Firefox\nName[ru]=Файрфокс\n"
                             "Exec=env MOZ=1 firefox %u\n[Desktop Action new]\nName=New window\n", "utf-8")
            old = os.environ.get("LANG")
            os.environ["LANG"] = "ru_RU.UTF-8"
            try:
                e = apps_linux._desktop_entry(str(entry))
            finally:
                os.environ.pop("LANG") if old is None else os.environ.__setitem__("LANG", old)
            self.assertEqual((e["Name"], e["Exec"]), ("Файрфокс", "env MOZ=1 firefox %u"))
            self.assertEqual(apps_linux._exec_target("flatpak run org.x.App"), "")
            # autostart and nimbus:// entries go to the XDG folders
            saved = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME")}
            os.environ["XDG_CONFIG_HOME"], os.environ["XDG_DATA_HOME"] = d, d
            try:
                linux.set_autostart(True, "Nimbus")
                self.assertTrue(linux.autostart_is_this_exe("Nimbus"))
                self.assertIn("--autostart", (Path(d) / "autostart" / "nimbus.desktop").read_text())
                linux.set_autostart(False, "Nimbus")
                self.assertFalse(linux.autostart_is_this_exe("Nimbus"))
                linux.register_url_scheme("nimbus", "Nimbus")
                self.assertTrue(linux.url_scheme_command("nimbus").endswith(" %u"))
                linux.unregister_url_scheme("nimbus")
                self.assertEqual(linux.url_scheme_command("nimbus"), "")
            finally:
                for k, v in saved.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("NIMBUS_TEST_GSETTINGS"),
                         "changes the desktop's proxy: only in CI's throwaway D-Bus session")
    def test_linux_gnome_proxy_roundtrip(self):
        from nimbus.platform import linux
        before = linux.read_proxy()
        self.assertIn("gnome", before)
        linux.enable_proxy(10809)
        on = linux.read_proxy()["gnome"]
        self.assertEqual((on["mode"], on["http.host"], on["http.port"]), ("'manual'", "'127.0.0.1'", "10809"))
        linux.write_proxy(before)
        self.assertEqual(linux.read_proxy()["gnome"], before["gnome"])

    def test_appimage_update(self):
        from nimbus import updater
        self.assertEqual(updater.asset_name("0.3.0", "appimage"), "Nimbus-0.3.0-x86_64.AppImage")
        with tempfile.TemporaryDirectory() as d:
            new, target = Path(d) / "dl.AppImage", Path(d) / "Nimbus.AppImage"
            new.write_bytes(b"new")
            target.write_bytes(b"old")
            self.assertEqual(updater.replace_appimage(new, target), target)
            self.assertEqual(target.read_bytes(), b"new")
            if sys.platform != "win32":
                self.assertTrue(os.access(target, os.X_OK))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["Nimbus.AppImage", "dl.AppImage"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
