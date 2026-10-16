"""User balancers: the servers picked from any subscriptions and groups become one Xray config
with a leastPing balancer. burstObservatory checks every node in the background and Xray moves
new connections to the fastest one that answers, with no reconnect.

The config is an ordinary full config, so connecting, TUN, presets and ping run it like any
provider config. Provider rules ("Умная*") are kept only when every server comes from the same
subscription; otherwise nobody's rules apply and the traffic goes as with "Весь трафик"."""
from __future__ import annotations

import copy
import re
import subprocess

from .i18n import tr
from . import config_builder, paths, winsys
from .config_builder import NON_PROXY
from .settings import Settings
from .store import Balancer, Server, Store

MODES = {"stable": tr("Стабильный"), "fastest": tr("Самый быстрый")}
# Stable mode moves to another node only when it's faster by both of these: small gains aren't
# worth a new exit IP (sites log you out, ask for captchas), and delays jitter by tens of ms.
MIN_GAIN_MS = 50
MIN_GAIN_RATIO = 0.3

TAG = "nimbus-auto"
PREFIX = TAG + "-"           # balanced nodes: nimbus-auto-<member index>-<their own tag>
FRAGMENT = "nimbus-fragment"


def _refs(outbounds: list[dict]) -> set[str]:
    """Tags other outbounds dial through: chain hops and fragment helpers, not nodes of their own."""
    out = set()
    for o in outbounds:
        dialer = ((o.get("streamSettings") or {}).get("sockopt") or {}).get("dialerProxy")
        if dialer:
            out.add(dialer)
        if (o.get("proxySettings") or {}).get("tag"):
            out.add(o["proxySettings"]["tag"])
    return out


def _member(i: int, srv: Server, s: Settings) -> tuple[list[dict], dict[str, str]]:
    """Outbounds of one member under tags of its own, and its old tag -> new tag."""
    obs = config_builder.proxy_outbounds(srv)
    if not srv.is_full_config:
        # As _build_link does for a single server.
        config_builder._apply_mux(obs[0], s)
        if s.fragment and obs[0].get("protocol") not in ("hysteria", "wireguard"):
            obs[0].setdefault("streamSettings", {}).setdefault("sockopt", {})["dialerProxy"] = FRAGMENT
    refs = _refs(obs)
    tags: dict[str, str] = {}
    kept = []
    for j, o in enumerate(obs):
        tag = o.get("tag") or f"out{j}"
        proto = o.get("protocol")
        if proto in ("freedom", "blackhole") and tag not in refs:
            continue   # the balancer's own direct / block take their place
        node = proto not in NON_PROXY and tag not in refs
        o["tag"] = tags[tag] = f"{PREFIX}{i}-{tag}" if node else f"n{i}-{tag}"
        kept.append(o)
    for o in kept:
        sockopt = (o.get("streamSettings") or {}).get("sockopt") or {}
        if sockopt.get("dialerProxy") in tags:
            sockopt["dialerProxy"] = tags[sockopt["dialerProxy"]]
        if (o.get("proxySettings") or {}).get("tag") in tags:
            o["proxySettings"]["tag"] = tags[o["proxySettings"]["tag"]]
    return kept, tags


def _provider_rules(src: Server, tags: dict[str, str]) -> list[dict]:
    """The source config's rules, pointed at the balancer and its direct / block."""
    cfg = src.config
    protos = {o.get("tag"): o.get("protocol") for o in cfg.get("outbounds", []) if o.get("tag")}
    own_balancers = {b.get("tag") for b in (cfg.get("routing") or {}).get("balancers") or []}
    rules = []
    for rule in copy.deepcopy((cfg.get("routing") or {}).get("rules", [])):
        out, bal = rule.pop("outboundTag", None), rule.pop("balancerTag", None)
        proto = protos.get(out)
        if bal in own_balancers or (out and proto not in NON_PROXY and out in protos):
            rule["balancerTag"] = TAG
        elif proto == "freedom":
            rule["outboundTag"] = "direct"
        elif proto == "blackhole":
            rule["outboundTag"] = "block"
        elif out in tags:
            rule["outboundTag"] = tags[out]
        else:
            continue
        rules.append(rule)
    return rules


def provider_source(store: Store, members: list[Server]) -> Server | None:
    """The member whose provider rules the balancer keeps: only when all come from one subscription."""
    subs = {m.sub_id for m in members}
    if len(subs) != 1 or store.subscription(next(iter(subs))) is None:
        return None
    return next((m for m in members if config_builder.provider_routing(m) is not None), None)


def build_config(members: list[Server], s: Settings, interval: int, source: Server | None = None) -> dict:
    outbounds, nodes, source_tags = [], [], {}
    for i, srv in enumerate(members):
        try:
            obs, tags = _member(i, srv, s)
        except Exception:
            continue   # a link that no longer parses shouldn't take the whole balancer down
        outbounds += obs
        nodes += [o["tag"] for o in obs if o["tag"].startswith(PREFIX)]
        if srv is source:
            source_tags = tags
    if any(((o.get("streamSettings") or {}).get("sockopt") or {}).get("dialerProxy") == FRAGMENT
           for o in outbounds):
        outbounds.append({"tag": FRAGMENT, "protocol": "freedom", "settings": {"fragment": {
            "packets": s.fragment_packets, "length": s.fragment_length, "interval": s.fragment_interval}}})
    # First, so _build_full takes them (not a member's fragment helper) for direct and block.
    outbounds = [{"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}] + outbounds

    balancer = {"tag": TAG, "selector": [PREFIX], "strategy": {"type": "leastPing"}}
    if nodes:
        balancer["fallbackTag"] = nodes[0]   # until the first check is in
    cfg: dict = {"outbounds": outbounds}
    if source is not None:
        rules = _provider_rules(source, source_tags)
        strategy = (source.config.get("routing") or {}).get("domainStrategy", "AsIs")
        if source.config.get("dns"):
            cfg["dns"] = copy.deepcopy(source.config["dns"])
    else:
        # Servers of several providers: nobody's rules, as "Весь трафик".
        rules = config_builder.routing_rules(s, "direct", "block", ru=False)
        strategy = s.domain_strategy
        cfg["dns"] = config_builder.dns_section(s)
    rules.append({"network": "tcp,udp", "balancerTag": TAG})
    cfg["routing"] = {"domainStrategy": strategy, "balancers": [balancer], "rules": rules}
    cfg["burstObservatory"] = {"subjectSelector": [PREFIX], "pingConfig": {
        "destination": s.ping_url, "interval": f"{max(10, interval)}s", "sampling": 2,
        "timeout": f"{max(1, s.ping_timeout)}s"}}
    return cfg


def as_server(bal: Balancer, store: Store, s: Settings) -> Server:
    """The balancer as a full-config server the rest of Nimbus runs as is."""
    members = store.members(bal)
    cfg = build_config(members, s, bal.interval, provider_source(store, members))
    return Server(id=bal.id, name=bal.name, sub_id=TAG, config=cfg, latency=bal.latency)


def alive(observatory: dict) -> dict[str, int]:
    """Balanced node tag -> delay in ms, for the nodes that answered the last check."""
    return {tag: int(st.get("delay") or 0) for tag, st in (observatory or {}).items()
            if tag.startswith(PREFIX) and st.get("alive")}


def fastest(observatory: dict) -> str | None:
    """The node leastPing picks: the alive one with the lowest delay."""
    nodes = alive(observatory)
    return min(nodes, key=nodes.get) if nodes else None


def pick_stable(observatory: dict, current: str | None) -> str | None:
    """Stay on the current node while it answers, unless another one is much faster."""
    nodes = alive(observatory)
    if not nodes:
        return current   # nothing answers: no better choice than staying
    best = min(nodes, key=nodes.get)
    if current not in nodes:
        return best
    gain = nodes[current] - nodes[best]
    return best if gain >= max(MIN_GAIN_MS, nodes[current] * MIN_GAIN_RATIO) else current


def member_of(tag: str | None, members: list[Server]) -> Server | None:
    """The server a balanced node tag belongs to."""
    if not tag or not tag.startswith(PREFIX):
        return None
    try:
        i = int(tag[len(PREFIX):].split("-", 1)[0])
    except ValueError:
        return None
    return members[i] if 0 <= i < len(members) else None


def current_node(observatory: dict, members: list[Server]) -> Server | None:
    """The member leastPing picks now."""
    return member_of(fastest(observatory), members)


def enable_api(cfg: dict, port: int) -> None:
    """Xray's routing API on a local port: stable mode pins the balancer to a node through it."""
    cfg["api"] = {"tag": "api", "listen": f"127.0.0.1:{port}", "services": ["RoutingService"]}


def pin(port: int, tag: str) -> None:
    """Make the balancer use this node for new connections (xray api bo)."""
    r = subprocess.run([str(paths.XRAY_EXE), "api", "bo", f"--server=127.0.0.1:{port}", "-b", TAG, tag],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                       stdin=subprocess.DEVNULL, creationflags=winsys.NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).strip() or tr("код {returncode}", returncode=r.returncode))


_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]")


def plain(name: str) -> str:
    """A server name without its flag emoji: Windows notifications show them as two letters."""
    return _FLAG.sub("", name).strip()
