"""Subscriptions and servers, persisted as one JSON file."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field

from .paths import PROFILES_FILE


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Server:
    id: str
    name: str
    sub_id: str = ""            # owner: a subscription or a user group id; "" = "Мои серверы"
    link: str = ""              # share link, for link-based servers
    config: dict | None = None  # full Xray config, for provider-supplied JSON servers
    latency: int | None = None  # ms; -1 = failed

    @property
    def is_full_config(self) -> bool:
        return self.config is not None

    @property
    def protocol(self) -> str:
        if self.config is not None:
            protos = [o.get("protocol") for o in self.config.get("outbounds", [])
                      if o.get("protocol") not in ("freedom", "blackhole", "dns")]
            if self.config.get("routing", {}).get("balancers"):
                return f"balancer · {len(protos)}"
            return protos[0] if protos else "config"
        return self.link.split("://", 1)[0].lower()


@dataclass
class Subscription:
    id: str
    url: str
    name: str = ""
    custom_name: str = ""
    user_agent: str = ""        # "" = use the global setting
    last_updated: float = 0
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0
    update_hours: int = 0       # from the profile-update-interval header; 0 = use setting
    support_url: str = ""
    web_page_url: str = ""
    announce: str = ""
    error: str = ""
    send_hwid: bool = False     # the panel only gives servers to a device that sends its HWID

    @property
    def title(self) -> str:
        host = self.url.split("/")[2] if "//" in self.url else self.url
        return self.custom_name or self.name or host


@dataclass
class Group:
    """A folder of servers the user added by hand (links, JSON configs)."""
    id: str
    name: str


@dataclass
class Balancer:
    """Servers picked from any subscriptions and groups; Xray keeps to the fastest of them."""
    id: str
    name: str
    server_ids: list = field(default_factory=list)  # servers picked one by one
    sub_ids: list = field(default_factory=list)     # whole subscriptions / groups ("" = "Мои серверы"), new servers too
    interval: int = 30                              # seconds between speed checks
    mode: str = "stable"                            # stable: keep a node until it fails or another is much
                                                    # faster | fastest: always the fastest (IP changes more often)
    latency: int | None = None                      # best member at the last ping; -1 = none answered


@dataclass
class Store:
    subscriptions: list[Subscription] = field(default_factory=list)
    servers: list[Server] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    balancers: list[Balancer] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Store":
        try:
            data = json.loads(PROFILES_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            subscriptions=[Subscription(**s) for s in data.get("subscriptions", [])],
            servers=[Server(**s) for s in data.get("servers", [])],
            groups=[Group(**g) for g in data.get("groups", [])],
            balancers=[Balancer(**b) for b in data.get("balancers", [])],
        )

    def save(self) -> None:
        tmp = PROFILES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False), "utf-8")
        tmp.replace(PROFILES_FILE)

    def server(self, server_id: str) -> Server | None:
        return next((s for s in self.servers if s.id == server_id), None)

    def subscription(self, sub_id: str) -> Subscription | None:
        return next((s for s in self.subscriptions if s.id == sub_id), None)

    def group(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def balancer(self, balancer_id: str) -> Balancer | None:
        return next((b for b in self.balancers if b.id == balancer_id), None)

    def members(self, bal: Balancer) -> list[Server]:
        """The balancer's servers that still exist, in list order."""
        ids, subs = set(bal.server_ids), set(bal.sub_ids)
        return [s for s in self.servers if s.id in ids or s.sub_id in subs]

    def remove_group(self, group_id: str) -> None:
        self.groups = [g for g in self.groups if g.id != group_id]
        self.servers = [s for s in self.servers if s.sub_id != group_id]

    def servers_of(self, sub_id: str) -> list[Server]:
        return [s for s in self.servers if s.sub_id == sub_id]

    def replace_servers(self, sub_id: str, servers: list[Server]) -> None:
        """Swap a subscription's servers, keeping ids (and so the selection) for unchanged names."""
        old = {s.name: s for s in self.servers_of(sub_id)}
        for s in servers:
            if s.name in old:
                s.id = old[s.name].id
                s.latency = old[s.name].latency
        first = next((i for i, s in enumerate(self.servers) if s.sub_id == sub_id), len(self.servers))
        rest = [s for s in self.servers if s.sub_id != sub_id]
        self.servers = rest[:first] + servers + rest[first:]

    def remove_subscription(self, sub_id: str) -> None:
        self.subscriptions = [s for s in self.subscriptions if s.id != sub_id]
        self.servers = [s for s in self.servers if s.sub_id != sub_id]

    def touch(self, sub: Subscription) -> None:
        sub.last_updated = time.time()
