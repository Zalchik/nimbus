"""Turn a server + settings into the Xray config that actually runs, and in TUN mode the
sing-box config in front of it.

TUN works the way Throne does it: sing-box owns the adapter (sing-tun's own TCP/IP stack,
auto_route, strict_route, hijack-dns) and hands every connection to Xray over a local SOCKS
bridge, so provider configs still run in Xray as shipped. Xray's own sockets are bound to the
physical adapter (IP_UNICAST_IF) and never loop back into the tunnel."""
from __future__ import annotations

import copy
import ipaddress
import re
import secrets
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import links, winsys
from .settings import Settings
from .store import Server

TUN_NAME = "Nimbus"
TUN_GATEWAY = "172.19.0.1"  # the adapter's own address once sing-box has configured it
TUN_ADDRESS4 = TUN_GATEWAY + "/24"
TUN_ADDRESS6 = "fdfe:dcba:9876::1/96"
NON_PROXY = ("freedom", "blackhole", "dns", "loopback")
DNS_HOSTS = {"cloudflare-dns.com": "1.1.1.1", "dns.google": "8.8.8.8",
             "common.dot.dns.yandex.net": "77.88.8.8"}
# What "Локальные сети напрямую" keeps out of the tunnel entirely (Throne's default list).
PRIVATE_RANGES = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "224.0.0.0/4",
                  "fc00::/7", "fe80::/10", "ff00::/8"]
TUN_DNS_OUT = "nimbus-tun-dns"   # unbound freedom: Xray's port-53 queries that must cross the tunnel
UNBOUND = ("blackhole", "loopback")
# Public resolvers that also answer DoH on their IP: plain UDP to them becomes DoH through Xray.
DOH_IPS = {"1.1.1.1", "1.0.0.1", "1.1.1.2", "1.0.0.2", "1.1.1.3", "1.0.0.3", "8.8.8.8", "8.8.4.4",
           "9.9.9.9", "149.112.112.112", "94.140.14.14", "94.140.15.15"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class Bridge:
    """Local SOCKS inbounds of Xray that sing-box forwards TUN traffic to. app_port carries the
    apps of a "vpn" preset: Xray only sees sing-box behind the bridge and can't tell apps apart."""
    port: int
    auth: str
    app_port: int = 0

    @classmethod
    def new(cls, apps: bool) -> "Bridge":
        return cls(free_port(), secrets.token_hex(16), free_port() if apps else 0)


@dataclass
class Built:
    config: dict
    proxy_tags: list[str]   # outbound tags whose traffic counts as "through the tunnel"
    tun: dict | None = None  # sing-box config (TUN mode)
    egress: str = ""         # adapter Xray's outbounds are bound to (TUN mode)


def inbounds(s: Settings, bridge: Bridge | None = None) -> list[dict]:
    listen = "0.0.0.0" if s.allow_lan else "127.0.0.1"
    sniff = {"enabled": s.sniffing, "destOverride": ["http", "tls", "quic"], "routeOnly": False}
    result = [
        {"tag": "socks", "protocol": "socks", "listen": listen, "port": s.socks_port,
         "settings": {"auth": "noauth", "udp": True}, "sniffing": sniff},
        {"tag": "http", "protocol": "http", "listen": listen, "port": s.http_port,
         "settings": {"allowTransparent": False}, "sniffing": sniff},
    ]
    if bridge:
        # As Throne's bridge: always sniffing, so Xray routes TUN traffic by domain.
        for tag, port in (("tun", bridge.port), ("tun-app", bridge.app_port)):
            if port:
                result.append({
                    "tag": tag, "protocol": "socks", "listen": "127.0.0.1", "port": port,
                    "settings": {"auth": "password", "udp": True,
                                 "accounts": [{"user": bridge.auth, "pass": bridge.auth}]},
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False}})
    return result


def _dns_ip(addr: str) -> str | None:
    """IP of a DNS server address if it's given literally (8.8.8.8, https://1.1.1.1/dns-query)."""
    host = urlsplit(addr).hostname if "://" in addr else addr.split(":")[0]
    if host and re.fullmatch(r"[\d.]+|[0-9a-fA-F:]+", host):
        return host
    return None


def routing_rules(s: Settings, direct: str = "direct", block: str = "block", ru: bool = True) -> list[dict]:
    rules: list[dict] = []
    if s.bypass_private:
        rules.append({"ip": ["geoip:private"], "outboundTag": direct})
    if s.block_ads:
        rules.append({"domain": ["geosite:category-ads-all"], "outboundTag": block})
    if ru and s.routing_mode == "bypass_ru":
        direct_ip = _dns_ip(s.direct_dns)
        if direct_ip:
            rules.append({"inboundTag": ["dns-internal"], "ip": [direct_ip], "outboundTag": direct})
        rules.append({"domain": ["geosite:category-ru", "domain:ru", "domain:su", "domain:xn--p1ai"],
                      "outboundTag": direct})
        rules.append({"ip": ["geoip:ru"], "outboundTag": direct})
    return rules


_IPV4 = re.compile(r"\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?")
_IPV6 = re.compile(r"[0-9a-fA-F]*:[0-9a-fA-F:.]*(/\d{1,3})?")


def active_preset(s: Settings) -> dict | None:
    if not s.route_preset:
        return None
    return next((p for p in s.route_presets if p.get("id") == s.route_preset), None)


def site_entry(entry: str) -> tuple[str, str] | None:
    """("domain" | "ip", Xray matcher) for a line of a preset's site list: example.com,
    https://example.com/page, *.example.com, 1.2.3.0/24, geosite:youtube, geoip:ru …"""
    e = entry.strip()
    low = e.lower()
    if not e or e.startswith("#"):
        return None
    if low.startswith("geoip:"):
        return "ip", low
    if low.startswith(("geosite:", "domain:", "full:", "regexp:", "keyword:")):
        return "domain", e
    if "://" in e:
        e = urlsplit(e).hostname or ""
    if _IPV4.fullmatch(e) or _IPV6.fullmatch(e.strip("[]")):
        return "ip", e.strip("[]")
    e = e.split("/")[0].split(":")[0].lstrip("*.").rstrip(".").lower()
    if "." in e and " " not in e:
        return "domain", "domain:" + e
    return None


def app_matchers(apps: list[dict]) -> list[str]:
    """Xray "process" values. Matching is case-sensitive and Windows doesn't keep case stable,
    so each name or folder also goes in lower case."""
    out: list[str] = []
    for app in apps:
        path = str(app.get("path", "")).replace("\\", "/")
        if app.get("kind") == "dir":
            path = path.rstrip("/") + "/"
            values = [path, path.lower()]
            for exe in app.get("exes", []):
                values += [exe, exe.lower()]
        else:
            base = path.rsplit("/", 1)[-1]
            values = [base, base.lower()]
        for v in values:
            if v and v != "/" and v not in out:
                out.append(v)
    return out


def preset_rules(preset: dict, direct: str, proxy: dict) -> tuple[list[dict], bool]:
    """Rules for a routing preset's apps and sites, and whether any of them match IPs.
    "bypass" sends them past the VPN; "vpn" sends only them through it."""
    target = {"outboundTag": direct} if preset.get("mode", "bypass") == "bypass" else dict(proxy)
    domains, ips = [], []
    for line in preset.get("sites", []):
        kind_value = site_entry(line)
        if kind_value:
            (domains if kind_value[0] == "domain" else ips).append(kind_value[1])
    rules = []
    procs = app_matchers(preset.get("apps", []))
    if procs:
        rules.append({"process": procs, **target})
    if domains:
        rules.append({"domain": domains, **target})
    if ips:
        rules.append({"ip": ips, **target})
    return rules, bool(ips)


def dns_section(s: Settings) -> dict:
    servers: list = [s.remote_dns]
    if s.routing_mode == "bypass_ru":
        servers.append({"address": s.direct_dns, "domains": ["geosite:category-ru"], "skipFallback": True})
    return {"tag": "dns-internal", "hosts": dict(DNS_HOSTS), "servers": servers, "queryStrategy": "UseIP"}


def _apply_mux(ob: dict, s: Settings) -> None:
    st = ob.get("settings", {})
    has_flow = st.get("flow") or any(u.get("flow") for v in st.get("vnext", []) for u in v.get("users", []))
    if s.mux and not has_flow and ob["protocol"] in ("vless", "vmess", "trojan", "shadowsocks"):
        ob["mux"] = {"enabled": True, "concurrency": s.mux_concurrency,
                     "xudpConcurrency": 16, "xudpProxyUDP443": "reject"}


def _common(cfg: dict, s: Settings, metrics_port: int, bridge: Bridge | None) -> None:
    # Xray writes a line per connection to stdout unless told not to. Every line goes through
    # our pipe and into the log window, so keep the access log for info/debug only.
    cfg["log"] = {"loglevel": s.log_level, "dnsLog": False}
    if s.log_level not in ("info", "debug"):
        cfg["log"]["access"] = "none"
    cfg["inbounds"] = inbounds(s, bridge)
    cfg["stats"] = {}
    cfg["metrics"] = {"tag": "metrics", "listen": f"127.0.0.1:{metrics_port}"}
    policy = cfg.setdefault("policy", {})
    policy.setdefault("system", {}).update({"statsOutboundUplink": True, "statsOutboundDownlink": True})


def _app_rule(preset: dict | None, bridge: Bridge | None, target: dict) -> list[dict]:
    """A "vpn" preset's apps arrive on their own bridge inbound; this sends them through the VPN."""
    if preset and bridge and bridge.app_port:
        return [{"inboundTag": ["tun-app"], **target}]
    return []


def _preset_apps_via_bridge(preset: dict | None) -> bool:
    return bool(preset and preset.get("mode") == "vpn" and preset.get("apps"))


def build(server: Server, s: Settings, metrics_port: int, egress: str = "") -> Built:
    """egress: name of the physical adapter (TUN mode). Xray's outbounds are bound to it."""
    bridge = None
    if s.tunnel_mode == "tun":
        bridge = Bridge.new(apps=_preset_apps_via_bridge(active_preset(s)))
    if server.is_full_config:
        built = _build_full(server, s, metrics_port, bridge)
    else:
        built = _build_link(server, s, metrics_port, bridge)
    if bridge:
        _prepare_for_tun(built.config, s, egress)
        built.tun = tun_config(s, bridge, server_domains(built.config), ru_direct(server, s))
        built.egress = egress
    return built


def _build_link(server: Server, s: Settings, metrics_port: int, bridge: Bridge | None = None) -> Built:
    _, proxy = links.parse_link(server.link)
    _apply_mux(proxy, s)
    outbounds = [proxy]
    if s.fragment and proxy["protocol"] not in ("hysteria", "wireguard"):
        proxy.setdefault("streamSettings", {}).setdefault("sockopt", {})["dialerProxy"] = "fragment"
        outbounds.append({"tag": "fragment", "protocol": "freedom", "settings": {"fragment": {
            "packets": s.fragment_packets, "length": s.fragment_length, "interval": s.fragment_interval}}})
    outbounds += [{"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}]
    preset = active_preset(s)
    rules = routing_rules(s, ru=preset is None)
    strategy = s.domain_strategy
    if preset:
        extra, has_ip = preset_rules(preset, "direct", {"outboundTag": "proxy"})
        rules += _app_rule(preset, bridge, {"outboundTag": "proxy"}) + extra
        if preset.get("mode") == "vpn":
            rules.append({"network": "tcp,udp", "outboundTag": "direct"})
        if has_ip and strategy == "AsIs":
            strategy = "IPIfNonMatch"
    cfg = {
        "outbounds": outbounds,
        "routing": {"domainStrategy": strategy, "rules": rules},
        "dns": dns_section(s),
    }
    _common(cfg, s, metrics_port, bridge)
    return Built(cfg, ["proxy"])


def _build_full(server: Server, s: Settings, metrics_port: int, bridge: Bridge | None = None) -> Built:
    """Provider configs run as shipped; only inbounds (and optional extras) are ours."""
    cfg = copy.deepcopy(server.config)
    cfg.pop("remarks", None)
    outbounds = cfg.setdefault("outbounds", [])

    direct = next((o["tag"] for o in outbounds if o.get("protocol") == "freedom" and o.get("tag")), None)
    if direct is None:
        direct = "nimbus-direct"
        outbounds.append({"tag": direct, "protocol": "freedom"})
    block = next((o["tag"] for o in outbounds if o.get("protocol") == "blackhole" and o.get("tag")), None)
    if block is None:
        block = "nimbus-block"
        outbounds.append({"tag": block, "protocol": "blackhole"})

    routing = cfg.setdefault("routing", {})
    rules = routing.setdefault("rules", [])
    balancers = routing.get("balancers") or []
    main = next((o["tag"] for o in outbounds if o.get("tag") and o.get("protocol") not in NON_PROXY), "proxy")
    proxy = {"balancerTag": balancers[0]["tag"]} if balancers else {"outboundTag": main}
    preset = active_preset(s)
    keep = s.use_provider_routing
    if preset:
        # A "bypass" preset can sit on top of the provider's rules; a "vpn" one replaces them.
        keep = (preset.get("mode", "bypass") == "bypass" and preset.get("provider", True)
                and provider_routing(server) is not None)
    if not keep:
        tail = [{"network": "tcp,udp", **proxy}]
        extra, has_ip = [], False
        if preset:
            extra, has_ip = preset_rules(preset, direct, proxy)
            extra = _app_rule(preset, bridge, proxy) + extra
            if preset.get("mode") == "vpn":
                tail = [{"network": "tcp,udp", "outboundTag": direct}]
        routing["domainStrategy"] = s.domain_strategy
        routing["rules"] = routing_rules(s, direct, block, ru=preset is None) + extra + tail
        cfg["dns"] = dns_section(s)
    else:
        # Keep the provider's rules; in TUN mode LAN traffic must still go direct.
        extra = []
        if s.tunnel_mode == "tun" and s.bypass_private:
            extra.append({"ip": ["geoip:private"], "outboundTag": direct})
        has_ip = False
        if preset:
            mine, has_ip = preset_rules(preset, direct, proxy)
            extra += _app_rule(preset, bridge, proxy) + mine
        routing["rules"] = extra + rules
    if has_ip and routing.get("domainStrategy", "AsIs") == "AsIs":
        routing["domainStrategy"] = "IPIfNonMatch"

    _common(cfg, s, metrics_port, bridge)
    proxy_tags = [o["tag"] for o in cfg["outbounds"] if o.get("tag") and o.get("protocol") not in NON_PROXY]
    return Built(cfg, proxy_tags)


# -- TUN (sing-box in front of Xray) ---------------------------------------------------------

def _prepare_for_tun(cfg: dict, s: Settings, egress: str) -> None:
    """Keep Xray's own traffic out of the tunnel, as Throne does for its in-process Xray:
    every outbound socket is bound to the physical adapter."""
    freedoms = {o.get("tag") for o in cfg["outbounds"] if o.get("protocol") == "freedom"}
    if s.kill_switch:
        # strict_route blocks port 53 outside the tunnel for every process but sing-box, so
        # Xray's direct DNS queries cross the tunnel instead; sing-box sends them on as they are.
        moved = False
        for rule in cfg.get("routing", {}).get("rules", []):
            if rule.get("outboundTag") in freedoms and set(rule.get("inboundTag") or []) & {
                    cfg.get("dns", {}).get("tag", "dns-internal")}:
                rule["outboundTag"] = TUN_DNS_OUT
                moved = True
        if moved:
            cfg["outbounds"].append({"tag": TUN_DNS_OUT, "protocol": "freedom"})
    if not egress:
        return
    for ob in cfg["outbounds"]:
        if ob.get("protocol") in UNBOUND or ob.get("tag") == TUN_DNS_OUT:
            continue
        sockopt = ob.setdefault("streamSettings", {}).setdefault("sockopt", {})
        sockopt.setdefault("interface", egress)


_DOMAIN = re.compile(r"(?=.{1,253}$)([a-z0-9_]([a-z0-9_-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]", re.I)


def _host_of(value: str) -> str:
    v = value.strip()
    if "://" in v:
        return urlsplit(v).hostname or ""
    if v.count(":") == 1:
        v = v.split(":")[0]
    return v.strip("[]").rstrip(".")


def server_domains(cfg: dict) -> list[str]:
    """Domain names of the proxy servers. sing-box resolves them with the direct DNS: through
    the tunnel they would wait on a connection that needs them first."""
    found: list[str] = []

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key in ("address", "endpoint", "server", "host"):
            host = _host_of(node).lower()
            if _DOMAIN.fullmatch(host) and host not in found:
                found.append(host)

    for ob in cfg.get("outbounds", []):
        if ob.get("protocol") not in NON_PROXY:
            walk(ob.get("settings", {}))
            # xhttp's separate download connection
            walk(((ob.get("streamSettings") or {}).get("xhttpSettings") or {}).get("extra", {}))
    return found


def ru_direct(server: Server, s: Settings) -> bool:
    """Whether Russian sites go past the VPN, so their names are better resolved directly."""
    if s.routing_mode == "bypass_ru" and not (server.is_full_config and s.use_provider_routing):
        return True
    info = provider_routing(server)
    return bool(info and info.get("ru") and s.use_provider_routing)


def _sb_dns(addr: str, through_xray: bool) -> dict:
    """A sing-box DNS server from Nimbus' address formats (1.1.1.1, https://1.1.1.1/dns-query,
    tcp://8.8.8.8, tls://…, quic+local://dns.adguard.com, localhost)."""
    a = addr.strip()
    if a.lower() in ("localhost", "local"):
        return {"type": "local"}
    scheme = "udp"
    if "://" in a:
        scheme, _, rest = a.partition("://")
        scheme = scheme.lower().replace("+local", "")
        parts = urlsplit("x://" + rest)
    else:
        parts = urlsplit("x://" + a)
    host, port, path = parts.hostname or "", parts.port, parts.path
    # UDP over Xray's SOCKS is unreliable (Throne: "overwrite remote dns to TCP based"): known
    # resolvers go DoH, the rest TCP.
    if through_xray and scheme in ("udp", "quic"):
        scheme = "https" if host in DOH_IPS else "tcp"
        if scheme == "https":
            path, port = "/dns-query", None
    kind = {"https": "https", "h3": "h3", "tls": "tls", "quic": "quic", "tcp": "tcp"}.get(scheme, "udp")
    out: dict = {"type": kind, "server": host}
    if port:
        out["server_port"] = port
    if kind in ("https", "h3"):
        out["path"] = path or "/dns-query"
    if not _ip(host):
        out["domain_resolver"] = "dns-local"
    return out


def _ip(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _sb_apps(apps: list[dict]) -> dict:
    """sing-box process matchers for a preset's apps. Folders match by path, case-insensitively."""
    names: list[str] = []
    regexes: list[str] = []
    for app in apps:
        path = str(app.get("path", "")).replace("/", "\\")
        if app.get("kind") == "dir":
            regexes.append("(?i)^" + re.escape(path.rstrip("\\") + "\\"))
            exes = app.get("exes", [])
        else:
            exes = [path.rsplit("\\", 1)[-1]]
        for exe in exes:
            for v in (exe, exe.lower()):
                if v and v not in names:
                    names.append(v)
    match: dict = {}
    if names:
        match["process_name"] = names
    if regexes:
        match["process_path_regex"] = regexes
    return match


_SB_LOG = {"error": "error", "warning": "warn", "info": "info", "debug": "debug"}


def tun_config(s: Settings, bridge: Bridge, domains: list[str], ru: bool) -> dict:
    """sing-box config: Throne's TUN inbound, hijack-dns, and everything else to Xray."""
    v6 = winsys.ipv6_enabled()
    exclude = ["127.0.0.0/8", "255.255.255.255/32"]
    if s.bypass_private:
        exclude += [r for r in PRIVATE_RANGES if v6 or ":" not in r]
    tun = {
        "type": "tun", "tag": "tun-in", "interface_name": TUN_NAME,
        # No IPv6 where Windows has it off: the adapter can't be configured then.
        "address": [TUN_ADDRESS4] + ([TUN_ADDRESS6] if v6 else []),
        "mtu": s.tun_mtu, "auto_route": True,
        # Kill switch = strict_route: Windows Filtering Platform blocks DNS outside the tunnel
        # and IPv6 when the tunnel has none.
        "strict_route": s.kill_switch,
        "route_exclude_address": exclude,
    }
    socks = {"type": "socks", "server": "127.0.0.1", "version": "5",
             "username": bridge.auth, "password": bridge.auth}
    outbounds = [{**socks, "tag": "xray", "server_port": bridge.port}]
    if bridge.app_port:
        outbounds.append({**socks, "tag": "xray-app", "server_port": bridge.app_port})
    outbounds.append({"type": "direct", "tag": "direct"})

    servers = [
        {**_sb_dns(s.remote_dns, True), "tag": "dns-remote", "detour": "xray"},
        {**_sb_dns(s.direct_dns, False), "tag": "dns-direct"},
        {"type": "local", "tag": "dns-local"},
    ]
    dns_rules: list[dict] = []
    if domains:
        dns_rules.append({"domain": domains, "action": "route", "server": "dns-direct"})
    if ru:
        dns_rules.append({"domain_suffix": ["ru", "su", "xn--p1ai"], "action": "route", "server": "dns-direct"})
    if s.fake_dns:
        # Not fc00::/18: the private-range bypass would send fake addresses past the tunnel.
        servers.append({"type": "fakeip", "tag": "dns-fake", "inet4_range": "198.18.0.0/15",
                        "inet6_range": "2001:db8::/32"})
        dns_rules.append({"query_type": ["A", "AAAA"], "action": "route", "server": "dns-fake"})

    rules: list[dict] = [
        # Xray's own sockets are bound past the tunnel; whatever still lands here (its DNS under
        # strict_route, latency tests) goes straight out instead of back into Xray.
        {"process_name": ["xray.exe"], "action": "route", "outbound": "direct"},
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
    ]
    preset = active_preset(s)
    if preset and preset.get("apps"):
        match = _sb_apps(preset["apps"])
        if match:
            out = "direct" if preset.get("mode", "bypass") == "bypass" else "xray-app"
            rules.insert(1, {**match, "action": "route", "outbound": out})

    log = {"disabled": True} if s.log_level == "none" else {"level": _SB_LOG.get(s.log_level, "warn")}
    return {
        "log": log,
        "dns": {"servers": servers, "rules": dns_rules, "final": "dns-remote"},
        "inbounds": [tun],
        "outbounds": outbounds,
        "route": {"rules": rules, "final": "xray", "auto_detect_interface": True,
                  "default_domain_resolver": "dns-direct"},
    }


_LOCAL = ("geoip:private", "10.", "127.", "169.254.", "172.16.", "192.168.", "fc00:", "fe80:", "::1",
          "localhost", "domain:local", "geosite:private")
_RU = ("category-ru", "geoip:ru", "geosite:ru", "domain:ru", "domain:su", "xn--p1ai", "yandex", "vk.com")


def provider_routing(server: Server) -> dict | None:
    """What the provider's own rules send past the VPN, or None if they don't (a share link,
    or a config whose rules only keep the local network direct). {"ru": True} when Russian
    sites are among them."""
    if not server.is_full_config:
        return None
    cfg = server.config
    direct = {o.get("tag") for o in cfg.get("outbounds", []) if o.get("protocol") == "freedom" and o.get("tag")}
    found, ru = False, False
    for rule in (cfg.get("routing") or {}).get("rules", []):
        if rule.get("outboundTag") not in direct:
            continue
        entries = [str(e) for e in (rule.get("domain") or []) + (rule.get("ip") or [])]
        public = [e for e in entries if not e.lower().startswith(_LOCAL)]
        if public:
            found = True
            ru = ru or any(m in e.lower() for e in public for m in _RU)
    return {"ru": ru} if found else None


def proxy_outbounds(server: Server) -> list[dict]:
    """All outbounds of a server, for latency testing (dialerProxy chains included)."""
    if server.is_full_config:
        return copy.deepcopy(server.config.get("outbounds", []))
    _, ob = links.parse_link(server.link)
    return [ob]
