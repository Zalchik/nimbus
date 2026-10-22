"""Share links (vless://, vmess://, trojan://, ss://, hy2://, socks://, wireguard://) -> Xray outbounds."""
from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit


class LinkError(ValueError):
    pass


SCHEMES = ("vless", "vmess", "trojan", "ss", "hysteria2", "hy2", "socks", "socks5", "wireguard", "wg")


def b64decode(s: str) -> str:
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4)).decode("utf-8")


def is_link(line: str) -> bool:
    return line.split("://", 1)[0].lower() in SCHEMES and "://" in line


def parse_link(link: str) -> tuple[str, dict]:
    """Return (display name, outbound with tag "proxy")."""
    link = link.strip()
    scheme = link.split("://", 1)[0].lower()
    parser = {
        "vless": _vless, "vmess": _vmess, "trojan": _trojan, "ss": _ss,
        "hysteria2": _hy2, "hy2": _hy2, "socks": _socks, "socks5": _socks,
        "wireguard": _wireguard, "wg": _wireguard,
    }.get(scheme)
    if not parser:
        raise LinkError(f"unsupported scheme: {scheme}")
    try:
        name, outbound = parser(link)
    except LinkError:
        raise
    except Exception as e:  # malformed input of any kind
        raise LinkError(f"bad {scheme} link: {e}") from e
    outbound["tag"] = "proxy"
    return name or f"{outbound['protocol']} server", outbound


def _split(link: str):
    u = urlsplit(link)
    q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    host = u.hostname or ""
    if not host or not u.port:
        raise LinkError("missing host or port")
    return u, q, host, u.port, unquote(u.fragment)


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def stream_settings(q: dict, default_network: str = "tcp") -> dict:
    """Build streamSettings from the common share-link query parameters."""
    network = (q.get("type") or q.get("net") or default_network).lower()
    if network in ("raw", "tcp"):
        network = "tcp"
    if network == "splithttp":
        network = "xhttp"
    security = (q.get("security") or "none").lower()
    s: dict = {"network": network, "security": security}

    host, path = q.get("host", ""), unquote(q.get("path", ""))
    if network == "tcp":
        if q.get("headerType") == "http":
            req: dict = {"path": [path or "/"]}
            if host:
                req["headers"] = {"Host": _csv(host)}
            s["tcpSettings"] = {"header": {"type": "http", "request": req}}
    elif network == "ws":
        s["wsSettings"] = {"path": path or "/", **({"host": host} if host else {})}
    elif network == "httpupgrade":
        s["httpupgradeSettings"] = {"path": path or "/", **({"host": host} if host else {})}
    elif network == "grpc":
        g: dict = {"serviceName": unquote(q.get("serviceName", ""))}
        if q.get("mode") == "multi":
            g["multiMode"] = True
        if q.get("authority"):
            g["authority"] = q["authority"]
        s["grpcSettings"] = g
    elif network == "xhttp":
        x: dict = {"path": path or "/", "mode": q.get("mode") or "auto"}
        if host:
            x["host"] = host
        if q.get("extra"):
            x["extra"] = json.loads(unquote(q["extra"]))
        s["xhttpSettings"] = x
    elif network == "kcp":
        k: dict = {"header": {"type": q.get("headerType") or "none"}}
        if q.get("seed"):
            k["seed"] = q["seed"]
        s["kcpSettings"] = k

    sni = q.get("sni") or q.get("peer") or ""
    fp = q.get("fp", "")
    if security == "tls":
        t: dict = {}
        if sni:
            t["serverName"] = sni
        if fp:
            t["fingerprint"] = fp
        if q.get("alpn"):
            t["alpn"] = _csv(unquote(q["alpn"]))
        if q.get("pcs"):
            t["pinnedPeerCertSha256"] = q["pcs"]
        if q.get("vcn"):
            t["verifyPeerCertByName"] = q["vcn"]
        if q.get("ech"):
            t["echConfigList"] = q["ech"]
        # insecure=1/allowInsecure=1 is deliberately dropped: Xray 26.2.6+ refuses to start a
        # config carrying allowInsecure (migrated to pinnedPeerCertSha256 / verifyPeerCertByName),
        # so passing it through would break the whole server, not just the certificate check.
        s["tlsSettings"] = t
    elif security == "reality":
        r: dict = {"serverName": sni, "fingerprint": fp or "chrome", "publicKey": q.get("pbk", "")}
        if q.get("sid"):
            r["shortId"] = q["sid"]
        if q.get("spx"):
            r["spiderX"] = unquote(q["spx"])
        if q.get("pqv"):
            r["mldsa65Verify"] = q["pqv"]
        s["realitySettings"] = r
    return s


def _vless(link):
    u, q, host, port, name = _split(link)
    out = {"protocol": "vless", "settings": {
        "address": host, "port": port, "id": unquote(u.username or ""),
        "encryption": q.get("encryption") or "none",
    }}
    if q.get("flow"):
        out["settings"]["flow"] = q["flow"]
    out["streamSettings"] = stream_settings(q)
    return name, out


def _vmess(link):
    body = link.split("://", 1)[1].split("#", 1)[0]
    try:
        j = json.loads(b64decode(body))
    except Exception:
        # Some panels emit vmess in vless-style URL form.
        u, q, host, port, name = _split(link)
        out = {"protocol": "vmess", "settings": {
            "address": host, "port": port, "id": unquote(u.username or ""),
            "security": q.get("encryption") or "auto"}}
        out["streamSettings"] = stream_settings(q)
        return name, out
    q = {
        "type": j.get("net", "tcp"), "headerType": j.get("type", ""), "host": j.get("host", ""),
        "path": j.get("path", ""), "security": j.get("tls") or "none", "sni": j.get("sni", ""),
        "alpn": j.get("alpn", ""), "fp": j.get("fp", ""), "serviceName": j.get("path", ""),
        "mode": j.get("mode", ""),
    }
    if q["type"] == "grpc":
        q["path"] = ""
    out = {"protocol": "vmess", "settings": {
        "address": j["add"], "port": int(j["port"]), "id": j["id"],
        "security": j.get("scy") or "auto"}}
    out["streamSettings"] = stream_settings(q)
    return j.get("ps", ""), out


def _trojan(link):
    u, q, host, port, name = _split(link)
    q.setdefault("security", "tls")
    out = {"protocol": "trojan", "settings": {
        "address": host, "port": port, "password": unquote(u.username or "")}}
    if q.get("flow"):
        out["settings"]["flow"] = q["flow"]
    out["streamSettings"] = stream_settings(q)
    return name, out


def _ss(link):
    rest = link.split("://", 1)[1]
    rest, _, frag = rest.partition("#")
    name = unquote(frag)
    rest = rest.split("?", 1)[0].rstrip("/")
    if "@" in rest:
        userinfo, _, hostport = rest.rpartition("@")
        userinfo = unquote(userinfo)
        if ":" not in userinfo:
            userinfo = b64decode(userinfo)
    else:  # legacy: base64(method:password@host:port)
        userinfo, _, hostport = b64decode(rest).rpartition("@")
    method, _, password = userinfo.partition(":")
    host, _, port = hostport.rpartition(":")
    host = host.strip("[]")
    if not (method and host and port):
        raise LinkError("missing method, host or port")
    return name, {"protocol": "shadowsocks", "settings": {
        "address": host, "port": int(port), "method": method, "password": password}}


def _hy2(link):
    u, q, host, port, name = _split(link)
    auth = unquote(u.username or "")
    if u.password:
        auth += ":" + unquote(u.password)
    tls: dict = {"serverName": q.get("sni") or host, "alpn": ["h3"]}
    if q.get("vcn"):
        tls["verifyPeerCertByName"] = q["vcn"]
    if q.get("pinSHA256"):
        tls["pinnedPeerCertSha256"] = q["pinSHA256"]
    stream: dict = {
        "network": "hysteria", "security": "tls", "tlsSettings": tls,
        "hysteriaSettings": {"version": 2, "auth": auth},
    }
    udp_masks = []
    if q.get("obfs") == "salamander" and q.get("obfs-password"):
        udp_masks.append({"type": "salamander", "settings": {"password": q["obfs-password"]}})
    if q.get("mport"):
        udp_masks.append({"type": "udphop", "settings": {
            "mode": "intervalRemote", "remotePorts": q["mport"], "interval": "30"}})
    if udp_masks:
        stream["finalmask"] = {"udp": udp_masks}
    return name, {"protocol": "hysteria",
                  "settings": {"version": 2, "address": host, "port": port},
                  "streamSettings": stream}


def _socks(link):
    u, q, host, port, name = _split(link)
    user, password = unquote(u.username or ""), unquote(u.password or "")
    if user and not password:
        try:
            user, _, password = b64decode(user).partition(":")
        except Exception:
            pass
    s: dict = {"address": host, "port": port}
    if user:
        s["user"], s["pass"] = user, password
    return name, {"protocol": "socks", "settings": s}


def _wireguard(link):
    u, q, host, port, name = _split(link)
    peer: dict = {"publicKey": q.get("publickey") or q.get("publicKey", ""),
                  "endpoint": f"{host}:{port}"}
    if q.get("presharedkey"):
        peer["preSharedKey"] = q["presharedkey"]
    peer["allowedIPs"] = _csv(unquote(q.get("allowedips", ""))) or ["0.0.0.0/0", "::/0"]
    s: dict = {
        "secretKey": unquote(u.username or q.get("privatekey", "")),
        "address": _csv(unquote(q.get("address", ""))) or ["172.16.0.2/32"],
        "peers": [peer],
        "mtu": int(q.get("mtu") or 1420),
    }
    if q.get("reserved"):
        s["reserved"] = [int(x) for x in _csv(q["reserved"])]
    return name, {"protocol": "wireguard", "settings": s}
