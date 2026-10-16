"""User settings, persisted as JSON."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from .paths import SETTINGS_FILE


@dataclass
class Settings:
    # Connection
    tunnel_mode: str = "proxy"          # "proxy" (system proxy) | "tun"
    kill_switch: bool = False
    # Proxy mode: also set HTTP(S)_PROXY for programs that ignore the Windows proxy (Claude Code,
    # git, curl, pip, npm…). Only programs started after connecting see it.
    proxy_env: bool = True
    socks_port: int = 10808
    http_port: int = 10809
    allow_lan: bool = False
    tun_mtu: int = 1500

    # Routing. Full-config servers keep the provider's balancer either way. By default they run
    # with the provider's own rules (RU sites direct), as shipped. With use_provider_routing off, their rules are replaced by these.
    routing_mode: str = "global"        # "global" | "bypass_ru"
    use_provider_routing: bool = True   # keep the subscription's own rules (e.g. RU sites direct)
    block_ads: bool = True
    bypass_private: bool = True
    domain_strategy: str = "AsIs"       # AsIs | IPIfNonMatch | IPOnDemand
    # User presets: {"id", "name", "mode": "bypass" | "vpn", "provider": bool,
    #                "apps": [{"name", "path", "kind": "exe" | "dir"}], "sites": [str]}
    route_presets: list = field(default_factory=list)
    route_preset: str = ""              # active preset id; "" = Умная / Весь трафик

    # DNS
    remote_dns: str = "https://1.1.1.1/dns-query"
    direct_dns: str = "8.8.8.8"
    fake_dns: bool = True               # TUN: answers at once instead of a DNS round trip through the tunnel

    # Advanced
    sniffing: bool = True
    mux: bool = False
    mux_concurrency: int = 8
    fragment: bool = False
    fragment_packets: str = "tlshello"
    fragment_length: str = "100-200"
    fragment_interval: str = "10-20"
    log_level: str = "warning"          # none | error | warning | info | debug

    # Subscriptions
    sub_user_agent: str = "Happ/3.0.0"  # panels send full Xray JSON configs to this UA
    sub_auto_update: bool = True
    sub_update_hours: int = 2
    update_on_launch: bool = True
    # HWID (x-hwid and device headers) for panels that limit devices
    hwid_mode: str = "auto"             # auto (only if a panel won't give servers without it) | always | never
    hwid_custom: str = ""               # "" = derived from this computer
    hwid_device: str = ""               # x-device-model; "" = computer name

    # Ping
    ping_url: str = "https://www.gstatic.com/generate_204"
    ping_timeout: int = 5

    # App
    auto_connect: bool = False
    autostart: bool = False
    start_minimized: bool = False
    minimize_to_tray: bool = True
    balancer_notify: bool = True        # a toast (or tray notice) when a balancer moves to another server
    theme: str = "dark"                 # dark | light
    selected_server: str = ""
    recent_servers: list = field(default_factory=list)   # servers / balancers last connected to, newest first
    sort_mode: str = "source"           # source | ping | name
    group_sort: dict = field(default_factory=dict)   # subscription / group id -> its own sort_mode
    settings_version: int = 4

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        if data.get("settings_version", 1) < 3:
            # 0.1.1 forced "everything through VPN", and 0.1.2 told users that turning provider
            # routing off was the better choice. It isn't: with the provider's RU-direct rules off
            # Russian sites (and speed tests) went abroad and back. Back to the provider's rules.
            data["use_provider_routing"] = True
        if data.get("settings_version", 1) < 4:
            # FakeDNS became the default in 4: earlier "off" was only the old default, not a choice.
            data["fake_dns"] = True
        data["settings_version"] = cls.settings_version
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(SETTINGS_FILE)
