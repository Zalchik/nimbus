"""Sharing: Xray outbounds back to share links (vless:// …), and configs as standalone JSON."""
from __future__ import annotations

import base64
import copy
import json
from urllib.parse import quote

from . import config_builder, links
from .settings import Settings
from .store import Server

NON_PROXY = ("freedom", "blackhole", "dns", "loopback")


def _q(params: dict) -> str:
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v not in (None, "", False))


def _host(addr: str) -> str:
    return f"[{addr}]" if ":" in addr and not addr.startswith("[") else addr


def _first(settings: dict, key: str) -> tuple[dict, dict]:
    """(server, user) from either the flat 26.x form or vnext/servers lists."""
    if settings.get(key):
        srv = settings[key][0]
        users = srv.get("users") or [{}]
        return srv, {**srv, **users[0]}
    return settings, settings


def _stream_params(ss: dict) -> dict:
    net = (ss.get("network") or "tcp").lower()
    net = {"raw": "tcp", "splithttp": "xhttp", "h2": "http"}.get(net, net)
    sec = (ss.get("security") or "none").lower()
    q: dict = {"type": net, "security": sec}
    if net == "tcp":
        header = (ss.get("tcpSettings") or ss.get("rawSettings") or {}).get("header") or {}
        if header.get("type") == "http":
            req = header.get("request") or {}
            q["headerType"] = "http"
            q["path"] = ",".join(req.get("path") or [])
            q["host"] = ",".join((req.get("headers") or {}).get("Host") or [])
    elif net in ("ws", "httpupgrade"):
        st = ss.get(f"{net}Settings") or {}
        q["path"] = st.get("path", "")
        q["host"] = st.get("host") or (st.get("headers") or {}).get("Host", "")
    elif net == "grpc":
        st = ss.get("grpcSettings") or {}
        q["serviceName"] = st.get("serviceName", "")
        q["authority"] = st.get("authority", "")
        if st.get("multiMode") or st.get("mode") in (True, "multi"):
            q["mode"] = "multi"
    elif net == "xhttp":
        st = ss.get("xhttpSettings") or ss.get("splithttpSettings") or {}
        q["path"] = st.get("path", "")
        q["host"] = st.get("host", "")
        q["mode"] = st.get("mode", "")
        if st.get("extra"):
            q["extra"] = json.dumps(st["extra"], separators=(",", ":"))
    elif net == "kcp":
        st = ss.get("kcpSettings") or {}
        q["headerType"] = (st.get("header") or {}).get("type", "")
        q["seed"] = st.get("seed", "")
    if sec == "tls":
        t = ss.get("tlsSettings") or {}
        q["sni"] = t.get("serverName", "")
        q["fp"] = t.get("fingerprint", "")
        q["alpn"] = ",".join(t.get("alpn") or [])
        q["pcs"] = t.get("pinnedPeerCertSha256", "")
        q["vcn"] = t.get("verifyPeerCertByName", "")
        q["ech"] = t.get("echConfigList", "")
    elif sec == "reality":
        r = ss.get("realitySettings") or {}
        q["sni"] = r.get("serverName", "")
        q["fp"] = r.get("fingerprint", "")
        q["pbk"] = r.get("publicKey") or r.get("password", "")
        q["sid"] = r.get("shortId", "")
        q["spx"] = r.get("spiderX", "")
        q["pqv"] = r.get("mldsa65Verify", "")
    return q


def outbound_link(ob: dict, name: str) -> str | None:
    """Share link for one outbound, or None for protocols links can't express."""
    proto = ob.get("protocol")
    st = ob.get("settings") or {}
    ss = ob.get("streamSettings") or {}
    frag = "#" + quote(name, safe="")
    if proto == "vless":
        srv, user = _first(st, "vnext")
        q = {"encryption": user.get("encryption") or "none", "flow": user.get("flow", ""), **_stream_params(ss)}
        return f"vless://{quote(user.get('id', ''), safe='')}@{_host(srv['address'])}:{srv['port']}?{_q(q)}{frag}"
    if proto == "trojan":
        srv, user = _first(st, "servers")
        q = {"flow": user.get("flow", ""), **_stream_params(ss)}
        return f"trojan://{quote(user.get('password', ''), safe='')}@{_host(srv['address'])}:{srv['port']}?{_q(q)}{frag}"
    if proto == "vmess":
        srv, user = _first(st, "vnext")
        p = _stream_params(ss)
        j = {"v": "2", "ps": name, "add": srv["address"], "port": str(srv["port"]), "id": user.get("id", ""),
             "aid": "0", "scy": user.get("security") or "auto", "net": p["type"],
             "type": p.get("headerType") or "none", "host": p.get("host", ""),
             "path": p.get("serviceName", "") if p["type"] == "grpc" else p.get("path", ""),
             "tls": "" if p["security"] == "none" else p["security"], "sni": p.get("sni", ""),
             "alpn": p.get("alpn", ""), "fp": p.get("fp", "")}
        if p.get("mode"):
            j["mode"] = p["mode"]
        return "vmess://" + base64.b64encode(json.dumps(j, ensure_ascii=False).encode()).decode()
    if proto == "shadowsocks":
        srv, user = _first(st, "servers")
        method, password = user.get("method", ""), user.get("password", "")
        if method.startswith("2022-"):  # SIP002: AEAD-2022 keys go percent-encoded, not base64
            userinfo = f"{quote(method, safe='')}:{quote(password, safe='')}"
        else:
            userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode().rstrip("=")
        return f"ss://{userinfo}@{_host(srv['address'])}:{srv['port']}{frag}"
    if proto in ("hysteria", "hysteria2"):
        srv = st if st.get("address") else (st.get("servers") or [{}])[0]
        hs = ss.get("hysteriaSettings") or {}
        tls = ss.get("tlsSettings") or {}
        q = {"sni": tls.get("serverName", ""), "vcn": tls.get("verifyPeerCertByName", ""),
             "pinSHA256": tls.get("pinnedPeerCertSha256", "")}
        for mask in (ss.get("finalmask") or {}).get("udp") or []:
            if mask.get("type") == "salamander":
                q["obfs"] = "salamander"
                q["obfs-password"] = (mask.get("settings") or {}).get("password", "")
            elif mask.get("type") == "udphop":
                q["mport"] = (mask.get("settings") or {}).get("remotePorts", "")
        auth = quote(hs.get("auth") or srv.get("password", ""), safe="")
        return f"hy2://{auth}@{_host(srv['address'])}:{srv['port']}?{_q(q)}{frag}"
    if proto == "socks":
        srv, user = _first(st, "servers")
        login = user.get("user", "")
        cred = ""
        if login:
            raw = f"{login}:{user.get('pass', '')}".encode()
            cred = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "@"
        return f"socks://{cred}{_host(srv['address'])}:{srv['port']}{frag}"
    if proto == "wireguard":
        peer = (st.get("peers") or [{}])[0]
        host, _, port = peer.get("endpoint", "").rpartition(":")
        q = {"publickey": peer.get("publicKey", ""), "presharedkey": peer.get("preSharedKey", ""),
             "address": ",".join(st.get("address") or []), "mtu": st.get("mtu", ""),
             "reserved": ",".join(str(x) for x in st.get("reserved") or []),
             "allowedips": ",".join(peer.get("allowedIPs") or [])}
        return f"wireguard://{quote(st.get('secretKey', ''), safe='')}@{host}:{port}?{_q(q)}{frag}"
    return None


def main_outbounds(server: Server) -> list[dict]:
    """The proxy outbounds of a full config, the one tagged "proxy" first."""
    obs = [o for o in (server.config or {}).get("outbounds", []) if o.get("protocol") not in NON_PROXY]
    return sorted(obs, key=lambda o: o.get("tag") != "proxy")


def server_link(server: Server) -> str | None:
    """A share link for the server. For a provider config it describes its main node only."""
    if not server.is_full_config:
        link = server.link.split("#", 1)[0]
        if link.lower().startswith("vmess://"):
            try:
                _, ob = links.parse_link(server.link)
            except links.LinkError:
                return server.link
            return outbound_link(ob, server.name) or server.link
        return f"{link}#{quote(server.name, safe='')}"
    for ob in main_outbounds(server):
        link = outbound_link(ob, server.name)
        if link:
            return link
    return None


def node_count(server: Server) -> int:
    return len(main_outbounds(server)) if server.is_full_config else 1


def server_json(server: Server, settings: Settings) -> dict:
    """A config another Xray client can import as is."""
    if server.is_full_config:
        cfg = copy.deepcopy(server.config)
        cfg.setdefault("remarks", server.name)
        config_builder.drop_allow_insecure(cfg)   # Xray 26.2.6+ rejects it
        return cfg
    s = copy.copy(settings)
    s.tunnel_mode = "proxy"
    s.route_preset = ""
    cfg = config_builder.build(server, s, 0).config
    for key in ("metrics", "stats", "policy"):
        cfg.pop(key, None)
    return {"remarks": server.name, **cfg}


def export_links(servers: list[Server]) -> tuple[str, int]:
    """Newline-separated share links, and how many servers couldn't be expressed as one."""
    out, skipped = [], 0
    for s in servers:
        link = server_link(s)
        if link:
            out.append(link)
        else:
            skipped += 1
    return "\n".join(out), skipped


def export_json(servers: list[Server], settings: Settings) -> dict | list[dict]:
    """One config as is, several as a JSON array (v2rayN, Happ and Xray clients import either)."""
    configs = [server_json(s, settings) for s in servers]
    return configs[0] if len(configs) == 1 else configs
