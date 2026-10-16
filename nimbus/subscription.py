"""Fetching and decoding subscriptions."""
from __future__ import annotations

import base64
import hashlib
import json
import platform
import re
import uuid
from urllib.parse import quote

from .lazy import httpx

from . import links, paths
from .paths import VERSION
from .store import Server, Subscription, new_id


def _machine_id() -> str:
    """Windows' MachineGuid; elsewhere a random id kept in the data folder."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        pass
    path = paths.DATA_DIR / "device_id"
    try:
        value = path.read_text("utf-8").strip()
    except OSError:
        value = ""
    if not value:
        value = uuid.uuid4().hex
        path.write_text(value, "utf-8")
    return value


def auto_hwid() -> str:
    """Stable per computer, but not the raw MachineGuid: panels only need to tell devices apart."""
    return hashlib.sha256(f"nimbus:{_machine_id()}".encode()).hexdigest()[:32]


def random_hwid() -> str:
    return uuid.uuid4().hex


def device_name() -> str:
    return platform.node() or "Windows PC"


def _header_value(value: str) -> str:
    """HTTP headers take ASCII only; a computer named "Домашний-ПК" goes percent-encoded."""
    return value if value.isascii() else quote(value, safe=" -_.()")


def hwid_headers(custom: str = "", device: str = "") -> dict[str, str]:
    """Device headers Remnawave and other panels read (the same ones Happ and v2rayN send)."""
    values = {"x-hwid": custom.strip() or auto_hwid(), "x-device-os": "Windows",
              "x-ver-os": platform.release() or "", "x-device-model": device.strip() or device_name()}
    return {k: _header_value(v) for k, v in values.items()}


_DUMMY_HOSTS = {"", "0.0.0.0", "::", "localhost"}


def _address(ob: dict) -> str:
    st = ob.get("settings") or {}
    for entry in (st.get("vnext") or []) + (st.get("servers") or []):
        if isinstance(entry, dict) and entry.get("address"):
            return str(entry["address"])
    return str(st.get("address") or "")


def placeholders_only(servers: list[Server]) -> bool:
    """True if no server points anywhere real: the stub "update the app / device not allowed"
    entries panels hand out instead of the list."""
    for srv in servers:
        try:
            obs = ([o for o in srv.config.get("outbounds", []) if o.get("protocol") not in
                    ("freedom", "blackhole", "dns", "loopback")] if srv.is_full_config
                   else [links.parse_link(srv.link)[1]])
        except Exception:
            continue
        for ob in obs:
            host = _address(ob).strip("[]").lower()
            if host not in _DUMMY_HOSTS and not host.startswith("127."):
                return False
    return True


def _header_text(value: str) -> str:
    """Panels send some headers as "base64:<data>"."""
    if value.startswith("base64:"):
        try:
            return base64.b64decode(value[7:] + "==").decode("utf-8")
        except Exception:
            return value
    return value


def parse_body(text: str, sub_id: str = "") -> tuple[list[Server], list[str]]:
    """Decode a subscription body or pasted text. Returns (servers, errors)."""
    text = text.strip().lstrip("﻿")
    servers: list[Server] = []
    errors: list[str] = []

    if text[:1] in "[{":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            items = data if isinstance(data, list) else [data]
            for i, cfg in enumerate(items, 1):
                if isinstance(cfg, dict) and cfg.get("outbounds"):
                    name = cfg.get("remarks") or f"Config {i}"
                    servers.append(Server(id=new_id(), name=name, sub_id=sub_id, config=cfg))
                else:
                    errors.append(f"item {i}: not an Xray config")
            return servers, errors

    lines = text.splitlines()
    if not any(links.is_link(l) for l in lines):
        try:
            lines = links.b64decode(text.replace("\n", "").replace("\r", "")).splitlines()
        except Exception:
            pass
    for line in lines:
        line = line.strip()
        if not links.is_link(line):
            continue
        try:
            name, _ = links.parse_link(line)
        except links.LinkError as e:
            errors.append(str(e))
            continue
        servers.append(Server(id=new_id(), name=name, sub_id=sub_id, link=line))
    if not servers and not errors:
        errors.append("no servers found")
    return servers, errors


def fetch(sub: Subscription, default_ua: str, proxy: str | None = None, hwid_mode: str = "auto",
          device: dict[str, str] | None = None) -> list[Server]:
    """Download a subscription, update its metadata in place and return its servers.
    hwid_mode "auto": the device headers (default: hwid_headers()) go out only if the panel gives
    no real servers without them, which is then remembered; "always" / "never" as they say."""
    ua = sub.user_agent or default_ua or f"Nimbus/{VERSION}"
    device = device or hwid_headers()
    if hwid_mode == "never":
        return _fetch(sub, ua, proxy, {})
    if hwid_mode == "always" or sub.send_hwid:
        return _fetch(sub, ua, proxy, device)
    first: list[Server] = []
    error: Exception | None = None
    try:
        first = _fetch(sub, ua, proxy, {})
        if not placeholders_only(first):
            return first
    except httpx.TransportError:
        raise  # no connection at all: an HWID won't help
    except Exception as e:
        error = e
    try:
        servers = _fetch(sub, ua, proxy, device)
    except Exception:
        if first:
            return first  # the panel's stub entries say what's wrong better than an HTTP error
        raise error
    if first and placeholders_only(servers):
        return first
    sub.send_hwid = True
    return servers


def _fetch(sub: Subscription, ua: str, proxy: str | None, extra: dict[str, str]) -> list[Server]:
    r = httpx.get(sub.url, headers={"User-Agent": ua, **extra}, follow_redirects=True, timeout=20,
                  proxy=proxy)
    r.raise_for_status()

    h = r.headers
    if "profile-title" in h:
        sub.name = _header_text(h["profile-title"])
    elif "content-disposition" in h:
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", h["content-disposition"])
        if m:
            sub.name = m.group(1)
    info = dict(re.findall(r"(\w+)=(\d+)", h.get("subscription-userinfo", "")))
    sub.upload = int(info.get("upload", 0))
    sub.download = int(info.get("download", 0))
    sub.total = int(info.get("total", 0))
    sub.expire = int(info.get("expire", 0))
    try:
        sub.update_hours = int(h.get("profile-update-interval", 0))
    except ValueError:
        sub.update_hours = 0
    sub.support_url = h.get("support-url", "")
    sub.web_page_url = h.get("profile-web-page-url", "")
    sub.announce = _header_text(h.get("announce", ""))

    servers, errors = parse_body(r.text, sub.id)
    if not servers:
        raise ValueError("; ".join(errors) or "empty subscription")
    return servers
