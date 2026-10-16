"""Real-delay test: one temporary Xray with an HTTP inbound per server outbound."""
from __future__ import annotations

import json
import ssl
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import certifi
from .lazy import httpx

from . import paths
from .platform import current as osys
from .config_builder import NON_PROXY, proxy_outbounds
from .core import free_port, port_in_use, xray_env
from .store import Server


def _retag(outbounds: list[dict], prefix: str) -> list[dict]:
    tags = {o.get("tag") for o in outbounds if o.get("tag")}
    for o in outbounds:
        if o.get("tag"):
            o["tag"] = prefix + o["tag"]
        sockopt = o.get("streamSettings", {}).get("sockopt", {})
        if sockopt.get("dialerProxy") in tags:
            sockopt["dialerProxy"] = prefix + sockopt["dialerProxy"]
        if o.get("proxySettings", {}).get("tag") in tags:
            o["proxySettings"]["tag"] = prefix + o["proxySettings"]["tag"]
    return outbounds


def _get(c: httpx.Client, url: str) -> None:
    # Over plain http:// Xray answers 5xx itself when the server is down: that's no reply from the target.
    if c.get(url).status_code >= 500:
        raise ConnectionError("no response through the server")


# Probes at once. Each one is a TLS handshake in Xray and in Python; dozens at a time pegged
# the CPU, and on Windows even the mouse cursor stuttered.
WORKERS = 10
_ssl: ssl.SSLContext | None = None
_ssl_lock = threading.Lock()


def _ssl_context() -> ssl.SSLContext:
    """One shared context: building one loads the whole CA bundle, a lot of CPU per probe."""
    global _ssl
    with _ssl_lock:
        if _ssl is None:
            _ssl = ssl.create_default_context(cafile=certifi.where())
        return _ssl


def _measure(port: int, url: str, timeout: float) -> int:
    osys.background_thread()
    proxy = f"http://127.0.0.1:{port}"
    # trust_env=False: proxy/certificate variables on the user's machine must not get in the way.
    for _ in range(2):  # a second try covers a handshake that just happened to stall
        try:
            with httpx.Client(proxy=proxy, timeout=timeout, trust_env=False, verify=_ssl_context()) as c:
                _get(c, url)  # warm-up: proxy handshake + TLS to the target
                t = time.perf_counter()
                _get(c, url)  # measured: round trip through the established tunnel
                return int((time.perf_counter() - t) * 1000)
        except Exception:
            continue
    return -1


def _wait_ready(proc: subprocess.Popen, ports: list[int], limit: float = 10.0) -> bool:
    """Wait until Xray listens on every probe port. Startup time varies a lot between machines
    (antivirus scanning xray.exe, slow disks), so a fixed pause isn't enough."""
    deadline = time.monotonic() + limit
    pending = list(ports)
    while pending and time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        pending = [p for p in pending if not port_in_use(p)]
        if pending:
            time.sleep(0.1)
    return not pending and proc.poll() is None


def _build(servers: list[Server]) -> tuple[dict, list[tuple[str, int]]]:
    inbounds, outbounds, rules, probes = [], [], [], []
    for i, srv in enumerate(servers):
        try:
            obs = _retag(proxy_outbounds(srv), f"s{i}-")
        except Exception:
            continue
        outbounds += obs
        for o in obs:
            if o.get("protocol") in NON_PROXY or not o.get("tag"):
                continue
            port = free_port()
            in_tag = "in-" + o["tag"]
            inbounds.append({"tag": in_tag, "protocol": "http", "listen": "127.0.0.1", "port": port})
            rules.append({"inboundTag": [in_tag], "outboundTag": o["tag"]})
            probes.append((srv.id, port))
    cfg = {"log": {"loglevel": "warning", "access": "none"}, "inbounds": inbounds,
           "outbounds": outbounds + [{"tag": "direct", "protocol": "freedom"}],
           "routing": {"rules": rules}}
    return cfg, probes


OnResult = Callable[[str, int], None]


def _run(servers: list[Server], url: str, timeout: float, result: dict[str, int], name: str,
         on_result: OnResult | None) -> bool:
    """Ping servers with one Xray. False if Xray didn't start (some config it couldn't load)."""
    cfg, probes = _build(servers)
    if not probes:
        return True
    path = paths.RUN_DIR / f"{name}.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
    log = open(paths.LOG_DIR / f"{name}.log", "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([str(paths.XRAY_EXE), "run", "-c", str(path)],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=str(paths.CORE_DIR), env=xray_env(),
                            **osys.POPEN_BACKGROUND)
    try:
        if not _wait_ready(proc, [port for _, port in probes]):
            return False
        left: dict[str, int] = {}
        for sid, _ in probes:
            left[sid] = left.get(sid, 0) + 1
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(_measure, port, url, timeout): sid for sid, port in probes}
            for fut in as_completed(futures):
                sid, ms = futures[fut], fut.result()
                left[sid] -= 1
                better = ms >= 0 and (result[sid] < 0 or ms < result[sid])
                if better:
                    result[sid] = ms
                # Report as soon as there's something to show: a server's first (or a better) result,
                # or "unreachable" once all of its nodes have failed.
                if on_result and (better or not left[sid]):
                    on_result(sid, result[sid])
        return True
    finally:
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        path.unlink(missing_ok=True)


def ping_servers(servers: list[Server], url: str, timeout: float,
                 on_result: OnResult | None = None, name: str = "ping") -> dict[str, int]:
    """server id -> latency in ms (-1 = unreachable). Balancers report their best node.
    on_result(server id, ms) is called from worker threads as results come in.
    name: of the run's config and log files, so runs at the same time don't share them."""
    result = {s.id: -1 for s in servers}
    if _run(servers, url, timeout, result, name, on_result):
        return result
    # One config Xray can't load takes the whole shared instance down with it. Test each server
    # on its own then, so only the broken ones stay unreachable.
    if len(servers) > 1:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda x: _run([x[1]], url, timeout, result, f"{name}-{x[0]}", on_result),
                          enumerate(servers)))
    return result
