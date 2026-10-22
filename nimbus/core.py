"""Running the Xray process, and in TUN mode the sing-box process in front of it."""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import threading
import time
from collections import deque
from typing import Callable


from .i18n import tr
from . import paths
from .platform import current as osys
from .config_builder import TUN_GATEWAY, Built, free_port  # noqa: F401  (free_port: re-exported)

PROXY_BACKUP = paths.RUN_DIR / "proxy_backup.json"
ENV_BACKUP = paths.RUN_DIR / "env_backup.json"   # HTTP(S)_PROXY as they were before we set them


class CoreError(RuntimeError):
    pass


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _address_assigned(ip: str) -> bool:
    """True once some local interface owns this address (binding to it then succeeds)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind((ip, 0))
            return True
        except OSError:
            return False


def xray_env() -> dict:
    return {**os.environ, "XRAY_LOCATION_ASSET": str(paths.asset_dir())}


def test_config(config: dict) -> None:
    """Raise CoreError with Xray's message if the config doesn't load."""
    path = paths.RUN_DIR / "test.json"
    path.write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    r = subprocess.run([str(paths.XRAY_EXE), "run", "-test", "-c", str(path)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=xray_env(),
                       **osys.POPEN)
    path.unlink(missing_ok=True)
    if r.returncode != 0:
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        raise CoreError(lines[-1] if lines else "invalid config")


def restore_proxy_after_crash() -> None:
    """If a previous run died while connected, put the user's proxy settings back."""
    if PROXY_BACKUP.exists():
        try:
            saved = json.loads(PROXY_BACKUP.read_text("utf-8"))
            osys.write_proxy(osys.without_dead_local_proxy(saved))
        except (OSError, ValueError):
            pass
        PROXY_BACKUP.unlink(missing_ok=True)
    if ENV_BACKUP.exists():
        try:
            saved = json.loads(ENV_BACKUP.read_text("utf-8"))
            osys.write_env_proxy(saved)
            # Started while our variables were set, we inherited them: subscription downloads
            # would go to a proxy that isn't there.
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = str(value[0] if isinstance(value, list) else value)
        except (OSError, ValueError):
            pass
        ENV_BACKUP.unlink(missing_ok=True)


class XrayCore:
    """One running Xray instance (plus sing-box in front of it in TUN mode) and the
    system-proxy state around them."""

    def __init__(self, on_log: Callable[[str], None], on_exit: Callable[[int], None]):
        self.on_log = on_log
        self.on_exit = on_exit
        self.proc: subprocess.Popen | None = None
        self.tun_proc: subprocess.Popen | None = None
        self.tail: deque[str] = deque(maxlen=40)
        self.tun_tail: deque[str] = deque(maxlen=40)
        self.metrics_port = 0
        self.proxy_tags: list[str] = []
        self.http_port = 0
        self.egress = ""             # adapter Xray is bound to (TUN mode)
        self.uses_sysproxy = False   # system proxy points at us (proxy mode)
        self.touched_proxy = False   # we changed the system proxy and must restore it
        self._stopping = False
        self._last = (0.0, 0, 0)
        self.observatory: dict = {}  # Xray's latest node checks (balancers), from the metrics

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, built: Built, http_port: int, set_sysproxy: bool, proxy_env: bool = False) -> None:
        if self.running:
            raise CoreError("already running")
        for ib in built.config["inbounds"]:
            if ib.get("port") and port_in_use(ib["port"]):
                raise CoreError(tr("Порт {port} занят другой программой (другой VPN-клиент?)", port=ib['port']))
        if built.tun and _address_assigned(TUN_GATEWAY):
            raise CoreError(tr("Адрес {ip} уже занят другим TUN-адаптером: закройте другой VPN-клиент "
                               "(Throne, sing-box, v2rayN…) и подключитесь снова", ip=TUN_GATEWAY))

        cfg_path = paths.RUN_DIR / "config.json"
        cfg_path.write_text(json.dumps(built.config, ensure_ascii=False, indent=1), "utf-8")
        self.proxy_tags = built.proxy_tags
        self.metrics_port = int(built.config["metrics"]["listen"].rsplit(":", 1)[1])
        self.http_port = http_port
        self.egress = built.egress
        self.observatory = {}
        self.tail.clear()
        self.tun_tail.clear()
        self._stopping = False
        self._last = (0.0, 0, 0)

        self.proc = self._spawn([str(paths.XRAY_EXE), "run", "-c", str(cfg_path)], "xray.log", "",
                                self.tail, env=xray_env())

        # Xray fails fast on bad configs and busy ports; give it a moment to do so.
        bridge = next((ib["port"] for ib in built.config["inbounds"] if ib.get("tag") == "tun"), 0)
        deadline = time.time() + (5 if bridge else 2.5)
        while time.time() < deadline and self.proc.poll() is None:
            if bridge and port_in_use(bridge):
                break
            time.sleep(0.05)
        self._raise_if_dead(self.proc, self.tail, "Xray")
        if bridge and not port_in_use(bridge):
            self.stop(restore_proxy=False)
            raise CoreError(tr("Xray не открыл порт для TUN за 5 секунд"))

        if built.tun:
            # sing-box takes the adapter, routes and DNS. We're only "connected" once the adapter
            # really has its address: until then traffic still flows outside the tunnel.
            tun_path = paths.RUN_DIR / "tun.json"
            tun_path.write_text(json.dumps(built.tun, ensure_ascii=False, indent=1), "utf-8")
            self.tun_proc = self._spawn([str(osys.singbox_path()), "run", "--disable-color", "-c", str(tun_path)],
                                        "sing-box.log", "[tun] ", self.tun_tail)
            deadline = time.time() + 25
            while time.time() < deadline:
                if self.tun_proc.poll() is not None or self.proc.poll() is not None:
                    break
                if _address_assigned(TUN_GATEWAY):
                    break
                time.sleep(0.1)
            self._raise_if_dead(self.tun_proc, self.tun_tail, "sing-box")
            self._raise_if_dead(self.proc, self.tail, "Xray")
            if not _address_assigned(TUN_GATEWAY):
                self.stop(restore_proxy=False)
                raise CoreError(tr("TUN-адаптер не поднялся за 25 секунд"))

        # Proxy mode points the system proxy at us. TUN mode switches it off: browsers would
        # otherwise keep using whatever proxy is set (e.g. a dead one from another client)
        # instead of the tunnel. Either way the user's settings come back on disconnect.
        if not PROXY_BACKUP.exists():
            PROXY_BACKUP.write_text(json.dumps(osys.read_proxy()), "utf-8")
        self.touched_proxy = True
        self.uses_sysproxy = set_sysproxy
        if set_sysproxy:
            osys.enable_proxy(http_port)
            if proxy_env:
                # Programs that never read the Windows proxy (Claude Code, git, curl, npm…)
                # go by these. Only ones started from now on see them.
                if not ENV_BACKUP.exists():
                    ENV_BACKUP.write_text(json.dumps(osys.read_env_proxy()), "utf-8")
                osys.enable_env_proxy(http_port)
        else:
            osys.disable_proxy()

    def _spawn(self, args: list[str], log_name: str, prefix: str, tail: deque, env=None) -> subprocess.Popen:
        log_file = open(paths.LOG_DIR / log_name, "w", encoding="utf-8")
        for attempt in range(20):
            try:
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    cwd=str(paths.CORE_DIR), env=env, **osys.POPEN)
                break
            except PermissionError:
                # WinError 32: an antivirus still holds the exe after its previous run (a reconnect).
                if attempt == 19:
                    log_file.close()
                    raise
                time.sleep(0.25)
        threading.Thread(target=self._pump, args=(proc, log_file, prefix, tail), daemon=True).start()
        return proc

    def _raise_if_dead(self, proc: subprocess.Popen | None, tail: deque, name: str) -> None:
        if proc is None or proc.poll() is None:
            return
        # Give the pump a moment to collect the last words.
        time.sleep(0.2)
        msg = next((l for l in reversed(tail) if "fail" in l.lower() or "error" in l.lower()
                    or "fatal" in l.lower()),
                   tail[-1] if tail else tr("{name} завершился сразу после запуска", name=name))
        self.stop(restore_proxy=False)
        raise CoreError(msg)

    def _pump(self, proc: subprocess.Popen, log_file, prefix: str, tail: deque) -> None:
        with log_file:
            for line in proc.stdout:
                line = line.rstrip()
                tail.append(line)
                if tail is not self.tail:
                    self.tail.append(prefix + line)   # the last line shown when the core stops
                log_file.write(line + "\n")
                self.on_log(prefix + line)
        code = proc.wait()
        if not self._stopping:
            self.on_exit(code)

    def stop(self, restore_proxy: bool = True) -> None:
        self._stopping = True
        tun = self.tun_proc is not None
        # sing-box first: its routes send everything to Xray, which is about to go away.
        for name in ("tun_proc", "proc"):
            proc = getattr(self, name)
            if proc is not None:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                setattr(self, name, None)
        if tun:
            osys.flush_dns()   # fake addresses cached while the tunnel was up
        if restore_proxy:
            self.restore_proxy()

    def restore_proxy(self) -> None:
        if self.touched_proxy:
            restore_proxy_after_crash()
            self.touched_proxy = False
            self.uses_sysproxy = False

    def speed(self) -> tuple[float, float, int, int] | None:
        """(up B/s, down B/s, total up, total down) through proxy outbounds."""
        if not self.running:
            return None
        try:
            # Plain http.client: no proxy lookup (the system proxy is us) and, unlike a fresh httpx
            # client, no SSL context to build every second, which made the window stutter.
            conn = http.client.HTTPConnection("127.0.0.1", self.metrics_port, timeout=1)
            try:
                conn.request("GET", "/debug/vars")
                data = json.loads(conn.getresponse().read())
            finally:
                conn.close()
        except Exception:
            return None
        self.observatory = data.get("observatory") or {}
        outs = (data.get("stats") or {}).get("outbound") or {}
        up = sum(outs.get(t, {}).get("uplink", 0) for t in self.proxy_tags)
        down = sum(outs.get(t, {}).get("downlink", 0) for t in self.proxy_tags)
        now = time.monotonic()
        t0, up0, down0 = self._last
        self._last = (now, up, down)
        if not t0:
            return 0.0, 0.0, up, down
        dt = max(now - t0, 1e-3)
        return max(up - up0, 0) / dt, max(down - down0, 0) / dt, up, down
