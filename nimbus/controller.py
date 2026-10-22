"""App logic between the UI and the core. Lives in the Qt main thread."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from typing import Callable

from .i18n import plural, tr
from .lazy import httpx
from PySide6.QtCore import QObject, QTimer, Signal

from . import balancer, config_builder, exit_ip, paths, ping, subscription, updater
from .platform import current as osys
from .core import CoreError, XrayCore, free_port, restore_proxy_after_crash, test_config
from .settings import Settings
from .store import Balancer, Group, Server, Store, Subscription, new_id

GEO_URLS = {
    "geoip.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat",
    "geosite.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
}

# Settings that change the generated Xray config; editing them while connected reconnects.
CONFIG_KEYS = {
    "tunnel_mode", "kill_switch", "proxy_env", "socks_port", "http_port", "allow_lan", "tun_mtu", "routing_mode",
    "use_provider_routing", "block_ads", "bypass_private", "domain_strategy", "remote_dns",
    "direct_dns", "fake_dns", "sniffing", "mux", "mux_concurrency", "fragment", "fragment_packets",
    "fragment_length", "fragment_interval", "log_level", "route_preset", "route_presets",
}


ICS_WARNING = (tr("TUN не работает, пока включены «Мобильный хот-спот» или общий доступ к интернету (ICS): "
                  "Windows заворачивает соединения ядра обратно в туннель. Выключите хот-спот или в его "
                  "настройках раздавайте подключение Nimbus."))


class _Bridge(QObject):
    """Hands results from worker threads back to the Qt thread."""
    call = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn, arg: fn(arg))


class Controller(QObject):
    state_changed = Signal(str)          # disconnected | connecting | connected | disconnecting
    servers_changed = Signal()
    log = Signal(str)
    speed = Signal(float, float)
    message = Signal(str, str)           # level (info|error), text
    need_admin = Signal()
    busy = Signal(str)                   # "" = idle, else a description
    ping_result = Signal(str, int)       # server id, ms (-1 = unreachable): one server's result is in
    ping_finished = Signal(object)       # ids of a finished ping run (its last results may have been -1)
    exit_ip = Signal(str, str, str)      # status ("" | checking | ok | fail), IP, country code
    node = Signal(str)                   # server a connected balancer goes through now ("" = unknown)
    update_checked = Signal(object, bool, str)   # newer Release or None, manual check, error ("" = none)

    def __init__(self):
        super().__init__()
        restore_proxy_after_crash()
        self.settings = Settings.load()
        self.store = Store.load()
        self.state = "disconnected"
        self._bridge = _Bridge()
        self._reconnects = 0
        self._members: list[Server] = []   # of the balancer we're connected to
        self._balancer: Balancer | None = None
        self._api_port = 0
        self._node_tag = ""                  # balanced node in use now
        self._pinning = False                # a pin request is on its way to Xray
        self._pings = 0        # ping runs going on at once
        self._ping_runs = 0    # every run gets files of its own
        self._node = ""
        self.core = XrayCore(on_log=lambda l: self._ui(self._core_log, l),
                             on_exit=lambda c: self._ui(self._core_died, c))

        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(1000)
        self._speed_timer.timeout.connect(self._poll_speed)
        self._sub_timer = QTimer(self)
        self._sub_timer.setInterval(10 * 60 * 1000)
        self._sub_timer.timeout.connect(lambda: self.update_subscriptions(only_due=True))
        self._sub_timer.start()
        # The balancer may move to another node while connected: look at the exit IP again now and then.
        self._ip_timer = QTimer(self)
        self._ip_timer.setInterval(2 * 60 * 1000)
        self._ip_timer.timeout.connect(self.check_exit_ip)
        self._ip_gen = 0
        self._ip_last = ("", "")
        # TUN binds Xray to the physical adapter; when Windows moves to another one (Wi-Fi to
        # cable, a dropped link) the binding goes stale, so reconnect onto the new adapter.
        self._egress_timer = QTimer(self)
        self._egress_timer.setInterval(4000)
        self._egress_timer.timeout.connect(self._check_egress)
        # New releases: at launch (App starts the first check) and every CHECK_HOURS after it.
        self._update_last = 0.0
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(30 * 60 * 1000)
        self._update_timer.timeout.connect(self.maybe_check_updates)
        self._update_timer.start()

    # -- threading helpers ---------------------------------------------------------------
    def _ui(self, fn: Callable, arg=None) -> None:
        self._bridge.call.emit(fn, arg)

    def run_async(self, work: Callable, done: Callable | None = None, fail: Callable | None = None):
        def runner():
            try:
                result = work()
            except Exception as e:  # reported to the UI, never raised in the thread
                if fail:
                    self._ui(fail, e)
                else:
                    self._ui(lambda err: self.message.emit("error", str(err)), e)
                return
            if done:
                self._ui(done, result)
        threading.Thread(target=runner, daemon=True).start()

    # -- selection -----------------------------------------------------------------------
    @property
    def selected(self) -> Server | None:
        return self.resolve(self.settings.selected_server)

    def resolve(self, server_id: str) -> Server | None:
        """A server, or a balancer as the full-config server it runs as."""
        srv = self.store.server(server_id)
        if srv is None and (bal := self.store.balancer(server_id)):
            srv = balancer.as_server(bal, self.store, self.settings)
        return srv

    def select(self, server_id: str, connect: bool = False) -> None:
        changed = server_id != self.settings.selected_server
        self.settings.selected_server = server_id
        self.settings.save()
        self.servers_changed.emit()
        if connect or (changed and self.state == "connected"):
            self.reconnect() if self.state == "connected" else self.connect()

    # -- connection ----------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)
        if state == "connected":
            self._ip_timer.start()
            self.check_exit_ip(first=True)
            if self.core.egress:
                self._egress_timer.start()
        else:
            self._ip_timer.stop()
            self._egress_timer.stop()
            self._ip_gen += 1   # a lookup still running belongs to the old connection
            self._ip_last = ("", "")
            self.exit_ip.emit("", "", "")
            self._set_node("")

    def check_exit_ip(self, first: bool = False, manual: bool = False) -> None:
        """Find out which IP sites see now (through the VPN) and its country. manual: the
        refresh button, which shows the check in progress and its failure like the first one."""
        if self.state != "connected":
            return
        self._ip_gen += 1
        gen = self._ip_gen
        first = first or manual
        if first:
            self.exit_ip.emit("checking", *self._ip_last)   # the old IP stays readable meanwhile
        # Through Xray's own HTTP inbound in both modes: in TUN too, so the answer doesn't depend
        # on how Windows routes Nimbus' own traffic.
        proxy = f"http://127.0.0.1:{self.core.http_port}"

        def done(result):
            if gen == self._ip_gen and self.state == "connected":
                self._ip_last = (result[0], result[1] or "")
                self.exit_ip.emit("ok", *self._ip_last)

        def fail(e):
            if gen == self._ip_gen and self.state == "connected":
                line = f"[nimbus] IP check failed: {e}"   # the reason, for a screenshot of the core log
                self.core.tail.append(line)
                self.log.emit(line)
                if first:
                    self.exit_ip.emit("fail", *self._ip_last)
        self.run_async(lambda: exit_ip.lookup(proxy), done, fail)

    def toggle(self) -> None:
        if self.state == "connected":
            self.disconnect()
        elif self.state == "disconnected":
            self.connect()

    def connect(self) -> None:
        if self.state not in ("disconnected",):
            return
        server = self.selected
        if server is None:
            if not self.store.servers:
                self.message.emit("error", tr("Сначала добавьте подписку или сервер."))
                return
            server = self.store.servers[0]
            self.settings.selected_server = server.id
            self.settings.save()
            self.servers_changed.emit()
        bal = self.store.balancer(server.id)
        self._balancer = bal
        self._members = self.store.members(bal) if bal else []
        self._node_tag = ""
        api_port = free_port() if bal and bal.mode == "stable" else 0
        self._api_port = api_port
        if bal and not self._members:
            self.message.emit("error", tr("В балансировщике «{name}» нет серверов: добавьте их через правый клик → "
                                          "«Изменить…».", name=bal.name))
            return
        if self.settings.tunnel_mode == "tun" and not osys.tun_allowed():
            self.need_admin.emit()
            return
        for exe in (paths.XRAY_EXE, osys.singbox_path() if self.settings.tunnel_mode == "tun" else None):
            if exe and not exe.exists():
                self.message.emit("error", tr("Не найдено ядро: {exe}", exe=exe))
                return

        self._set_state("connecting")
        s = self.settings

        def work():
            egress = ""
            if s.tunnel_mode == "tun":
                found = osys.default_egress(config_builder.TUN_NAME)
                if found is None:
                    raise CoreError(tr("нет активного подключения к интернету"))
                egress, forwarding = found
                if forwarding:
                    # Windows ignores the adapter binding on a forwarding adapter.
                    self._ui(lambda _: self.message.emit("error", ICS_WARNING))
            # Linux: Xray isn't bound to the adapter; sing-box sends its traffic straight out.
            built = config_builder.build(server, s, free_port(), egress=egress if osys.BIND_EGRESS else "")
            if api_port:
                balancer.enable_api(built.config, api_port)
            test_config(built.config)
            # No separate `sing-box check`: sing-box reports a bad config as fast on `run`, and
            # each launch of it may cost seconds of antivirus scanning.
            self.core.start(built, s.http_port, set_sysproxy=s.tunnel_mode == "proxy", proxy_env=s.proxy_env)

        def done(_):
            self._reconnects = 0
            self._remember(server.id)
            self._set_state("connected")
            self._speed_timer.start()

        def fail(err):
            self._set_state("disconnected")
            text = str(err)
            self.message.emit("error", tr("Не удалось подключиться: {text}", text=text))

        self.run_async(work, done, fail)

    RECENT = 3

    def _remember(self, server_id: str) -> None:
        """Keep the last servers / balancers connected to, for switching from the tray."""
        recent = [server_id] + [i for i in self.settings.recent_servers if i != server_id]
        if recent != self.settings.recent_servers:
            self.settings.recent_servers = recent[:self.RECENT]
            self.settings.save()

    def recent(self) -> list[Server]:
        """The last servers / balancers connected to that still exist, newest first."""
        return [s for s in (self.resolve(i) for i in self.settings.recent_servers) if s][:self.RECENT]

    def disconnect(self, then: Callable | None = None) -> None:
        if self.state not in ("connected", "connecting"):
            if then:
                then()
            return
        self._set_state("disconnecting")
        self._speed_timer.stop()

        def done(_):
            self._set_state("disconnected")
            self.speed.emit(0, 0)
            if then:
                then()
        self.run_async(lambda: self.core.stop(restore_proxy=True), done)

    def reconnect(self) -> None:
        self.disconnect(then=self.connect)

    def _core_log(self, line: str) -> None:
        self.log.emit(line)

    def _check_egress(self) -> None:
        if self.state != "connected" or not self.core.egress:
            return
        bound = self.core.egress

        def done(found):
            if found and found[0] != bound and self.state == "connected" and self.core.egress == bound:
                self.message.emit("info", tr("Сеть сменилась ({bound} → {new}), переподключение…",
                                             bound=bound, new=found[0]))
                self.reconnect()
        self.run_async(lambda: osys.default_egress(config_builder.TUN_NAME), done, fail=lambda e: None)

    def _core_died(self, code: int) -> None:
        """Xray exited without us asking."""
        if self.state != "connected":
            return
        self._speed_timer.stop()
        last = self.core.tail[-1] if self.core.tail else tr("код {code}", code=code)
        # Kill switch (proxy mode): leave the system proxy pointing at the dead port so
        # nothing leaks past it. It's lifted on reconnect, on quit or when the switch is turned off.
        # In TUN mode the other process goes too: sing-box without Xray is a tunnel to nowhere.
        self.core.stop(restore_proxy=not (self.settings.kill_switch and self.core.uses_sysproxy))
        self._set_state("disconnected")
        self.speed.emit(0, 0)
        if self._reconnects < 3:
            self._reconnects += 1
            self.message.emit("error", tr("Ядро остановилось ({last}). Переподключение…", last=last))
            QTimer.singleShot(1500, self.connect)
        elif self.core.uses_sysproxy:
            self.message.emit("error", tr("Ядро упало несколько раз подряд. Kill switch держит интернет "
                                          "заблокированным — нажмите «Подключиться» или выйдите из программы."))
        else:
            self.message.emit("error", tr("Ядро упало несколько раз подряд: {last}", last=last))

    def _poll_speed(self) -> None:
        def done(res):
            if res and self.state == "connected":
                self.speed.emit(res[0], res[1])
                if self._members:
                    self._balancer_tick(dict(self.core.observatory))
        self.run_async(self.core.speed, done, fail=lambda e: None)

    def _balancer_tick(self, obs: dict) -> None:
        """Follow the balancer's node; in stable mode decide it ourselves and pin it in Xray."""
        if self._api_port:
            target = balancer.pick_stable(obs, self._node_tag or None)
            if not target or target == self._node_tag or self._pinning:
                return
            self._pinning = True
            port, old = self._api_port, self._node_tag

            def pinned(_):
                self._pinning = False
                if self.state == "connected" and self._api_port == port:
                    self._switched(old, target, obs)

            def failed(err):
                self._pinning = False
                self.log.emit(tr("[nimbus] не удалось закрепить узел {target}: {err}", target=target, err=err))
            self.run_async(lambda: balancer.pin(port, target), pinned, failed)
        else:
            target = balancer.fastest(obs)
            if target and target != self._node_tag:
                self._switched(self._node_tag, target, obs)

    def _switched(self, old: str, new: str, obs: dict) -> None:
        self._node_tag = new
        node = balancer.member_of(new, self._members)
        self._set_node(node.name if node else "")
        before = balancer.member_of(old, self._members)
        if not (before and node and before is not node and self.settings.balancer_notify):
            return
        delays = balancer.alive(obs)
        if old not in delays:
            why = tr("{name} не отвечает", name=balancer.plain(before.name))
        else:
            why = tr("на {ms} мс быстрее, чем {name}", ms=delays[old] - delays.get(new, 0),
                     name=balancer.plain(before.name))
        name = self._balancer.name if self._balancer else tr("Балансировщик")
        self.message.emit("info", f"«{name}» → {balancer.plain(node.name)}: {why}")

    def _set_node(self, name: str) -> None:
        if name == self._node:
            return
        moved = bool(self._node and name)
        self._node = name
        self.node.emit(name)
        if moved:
            self.check_exit_ip()   # another node, likely another exit IP

    @property
    def current_node(self) -> str:
        return self._node

    def shutdown(self) -> None:
        self._speed_timer.stop()
        self.core.stop(restore_proxy=True)
        self.store.save()
        self.settings.save()

    # -- settings ------------------------------------------------------------------------
    def apply_settings(self, new: Settings) -> None:
        old = asdict(self.settings)
        self.settings = new
        new.save()
        changed = {k for k, v in asdict(new).items() if old.get(k) != v}
        old_preset = next((p for p in old["route_presets"] if p.get("id") == old["route_preset"]), None)
        if config_builder.active_preset(new) == old_preset:
            changed.discard("route_presets")  # only presets that aren't in use were edited
        if "kill_switch" in changed and not new.kill_switch and not self.core.running:
            self.core.restore_proxy()  # lift a block left by a crash
        if "autostart" in changed:
            try:
                osys.set_autostart(new.autostart, paths.APP_NAME)
            except OSError as e:
                self.message.emit("error", tr("Автозапуск: {e}", e=e))
        if changed & CONFIG_KEYS and self.state == "connected":
            if new.tunnel_mode == "tun" and not osys.tun_allowed():
                self.disconnect()
                self.need_admin.emit()
            else:
                self.reconnect()

    # -- app updates ---------------------------------------------------------------------
    def maybe_check_updates(self) -> None:
        if self.settings.update_check and time.time() - self._update_last >= updater.CHECK_HOURS * 3600:
            self.check_updates()

    def check_updates(self, manual: bool = False) -> None:
        """Ask GitHub for the latest release; update_checked tells the result. A version the user
        skipped is offered again only when asked by hand."""
        self._update_last = time.time()
        proxy = self._proxy_for_downloads()

        def done(release):
            newer = release if release and updater.is_newer(release.version) else None
            if newer and not manual and newer.version == self.settings.update_skip:
                newer = None
            self.update_checked.emit(newer, manual, "")

        def fail(err):
            self.update_checked.emit(None, manual, str(err) or type(err).__name__)
        self.run_async(lambda: updater.latest(proxy), done, fail)

    def download_update(self, release, kind: str, progress: Callable, done: Callable,
                        fail: Callable) -> threading.Event:
        """Download (through the VPN when connected) and check the update. progress gets
        (bytes, total); setting the returned event cancels."""
        stop = threading.Event()
        proxy = self._proxy_for_downloads()
        self.run_async(lambda: updater.prepare(release, kind, proxy, lambda d, t: self._ui(progress, (d, t)),
                                               stop.is_set), done, fail)
        return stop

    def install_update(self, prepared, kind: str, quit_app: Callable, failed: Callable | None = None) -> None:
        """Disconnect (the proxy settings go back), start the installer or the swap helper, quit.
        A connection that was up comes back after the update."""
        connect = self.state == "connected"

        def go():
            try:
                updater.install(prepared, kind, os.getpid(), connect)
            except Exception as e:
                if failed:
                    failed(e)
                else:
                    self.message.emit("error", tr("Не удалось запустить обновление: {e}", e=e))
                return
            quit_app()
        self.disconnect(then=go)

    # -- subscriptions -------------------------------------------------------------------
    def _proxy_for_downloads(self) -> str | None:
        """When connected through the system proxy, fetch through the tunnel too."""
        if self.state == "connected" and self.core.uses_sysproxy:
            return f"http://127.0.0.1:{self.settings.http_port}"
        return None

    def add_subscription(self, url: str) -> None:
        sub = Subscription(id=new_id(), url=url.strip())
        self.busy.emit(tr("Загрузка подписки…"))

        def done(servers):
            self.store.subscriptions.append(sub)
            self.store.servers += servers
            self.store.touch(sub)
            self.store.save()
            self.busy.emit("")
            self.servers_changed.emit()
            n = len(servers)
            self.message.emit("info", tr("Добавлено: {title} — {n} {servers}", title=sub.title, n=n,
                                         servers=plural(n, "сервер", "сервера", "серверов")))

        def fail(err):
            self.busy.emit("")
            self.message.emit("error", tr("Не удалось загрузить подписку: {err}", err=err))

        proxy, hwid = self._proxy_for_downloads(), self._hwid()
        self.run_async(lambda: subscription.fetch(sub, self.settings.sub_user_agent, proxy, *hwid), done, fail)

    def update_subscriptions(self, only_due: bool = False, sub_ids: list[str] | None = None) -> None:
        now = time.time()
        subs = []
        for sub in self.store.subscriptions:
            if sub_ids is not None and sub.id not in sub_ids:
                continue
            if only_due:
                if not self.settings.sub_auto_update:
                    continue
                hours = sub.update_hours or self.settings.sub_update_hours
                if now - sub.last_updated < hours * 3600:
                    continue
            subs.append(sub)
        if not subs:
            return
        self.busy.emit(tr("Обновление подписок…"))
        ua, proxy, hwid = self.settings.sub_user_agent, self._proxy_for_downloads(), self._hwid()

        def work():
            results = {}
            for sub in subs:
                try:
                    results[sub.id] = subscription.fetch(sub, ua, proxy, *hwid)
                    sub.error = ""
                except Exception as e:
                    sub.error = str(e)
            return results

        def done(results):
            for sub in subs:
                if sub.id in results:
                    self.store.replace_servers(sub.id, results[sub.id])
                    self.store.touch(sub)
            self.store.save()
            self.busy.emit("")
            self.servers_changed.emit()
            failed = [s.title for s in subs if s.error]
            if failed:
                self.message.emit("error", tr("Не обновились: ") + ", ".join(failed))
            elif not only_due:
                self.message.emit("info", tr("Подписки обновлены"))

        self.run_async(work, done)

    def import_text(self, text: str, group_id: str = "") -> int:
        """Pasted share links or Xray JSON become servers of a group ("" = "Мои серверы")."""
        servers, errors = subscription.parse_body(text, sub_id=group_id)
        if servers:
            self.store.servers += servers
            self.store.save()
            self.servers_changed.emit()
        if errors and not servers:
            self.message.emit("error", tr("Не удалось распознать: ") + "; ".join(errors[:3]))
        return len(servers)

    def add_group(self, name: str) -> Group:
        group = Group(id=new_id(), name=name.strip() or tr("Новая группа"))
        self.store.groups.append(group)
        self.store.save()
        self.servers_changed.emit()
        return group

    def rename_group(self, group_id: str, name: str) -> None:
        group = self.store.group(group_id)
        if group and name.strip():
            group.name = name.strip()
            self.store.save()
            self.servers_changed.emit()

    def remove_group(self, group_id: str) -> None:
        self.store.remove_group(group_id)
        self.store.save()
        self.servers_changed.emit()

    def move_server(self, server_id: str, group_id: str) -> None:
        srv = self.store.server(server_id)
        if srv and not self.store.subscription(srv.sub_id):
            srv.sub_id = group_id
            self.store.save()
            self.servers_changed.emit()

    def rename_subscription(self, sub_id: str, name: str) -> None:
        sub = self.store.subscription(sub_id)
        if sub:
            sub.custom_name = name.strip()
            self.store.save()
            self.servers_changed.emit()

    def set_subscription_ua(self, sub_id: str, ua: str) -> None:
        sub = self.store.subscription(sub_id)
        if sub:
            sub.user_agent = ua.strip()
            self.store.save()
            self.update_subscriptions(sub_ids=[sub_id])

    def _hwid(self) -> tuple[str, dict[str, str]]:
        """(mode, device headers) for subscription.fetch, from the HWID settings."""
        s = self.settings
        return s.hwid_mode, subscription.hwid_headers(s.hwid_custom, s.hwid_device)

    def set_subscription_hwid(self, sub_id: str, on: bool) -> None:
        sub = self.store.subscription(sub_id)
        if sub:
            sub.send_hwid = on
            self.store.save()
            self.update_subscriptions(sub_ids=[sub_id])

    def remove_subscription(self, sub_id: str) -> None:
        self.store.remove_subscription(sub_id)
        self.store.save()
        self.servers_changed.emit()

    def remove_server(self, server_id: str) -> None:
        self.remove_servers([server_id])

    def remove_servers(self, server_ids) -> None:
        ids = set(server_ids)
        self.store.servers = [s for s in self.store.servers if s.id not in ids]
        self.store.save()
        self.servers_changed.emit()

    # -- balancers -----------------------------------------------------------------------
    def save_balancer(self, bal: Balancer) -> None:
        """Add a new balancer or store the edits of one; reconnects if it's the one in use."""
        if self.store.balancer(bal.id) is None:
            self.store.balancers.append(bal)
        else:
            self.store.balancers = [bal if b.id == bal.id else b for b in self.store.balancers]
        bal.latency = None   # measured for other servers
        self.store.save()
        self.servers_changed.emit()
        if self.state == "connected" and self.settings.selected_server == bal.id:
            self.reconnect()

    def new_balancer(self, name: str, server_ids: list[str], sub_ids: list[str], interval: int = 30,
                     mode: str = "stable") -> Balancer:
        bal = Balancer(id=new_id(), name=name.strip() or tr("Балансировщик"), server_ids=list(server_ids),
                       sub_ids=list(sub_ids), interval=interval, mode=mode)
        self.save_balancer(bal)
        return bal

    def add_to_balancer(self, balancer_id: str, server_ids: list[str]) -> None:
        bal = self.store.balancer(balancer_id)
        if bal:
            bal.server_ids += [i for i in server_ids if i not in bal.server_ids]
            self.save_balancer(bal)

    def remove_balancer(self, balancer_id: str) -> None:
        self.remove_balancers([balancer_id])

    def remove_balancers(self, balancer_ids) -> None:
        ids = set(balancer_ids)
        self.store.balancers = [b for b in self.store.balancers if b.id not in ids]
        self.store.save()
        if self.settings.selected_server in ids and self.state != "connected":
            self.settings.selected_server = ""
            self.settings.save()
        self.servers_changed.emit()

    # -- ping / geo ----------------------------------------------------------------------
    def ping(self, servers: list[Server] | None = None) -> None:
        servers = list(servers if servers is not None else self.store.servers)
        if not servers:
            return
        # Runs don't wait for each other: a server with a dead node keeps its run going for
        # seconds after its first result is in, and another server shouldn't wait for that.
        self._pings += 1
        self._ping_runs += 1
        name = f"ping-{self._ping_runs}"
        ids = {s.id for s in servers}
        self.busy.emit(tr("Проверка задержки…"))
        url, timeout = self.settings.ping_url, self.settings.ping_timeout

        def finished() -> None:
            self._pings -= 1
            self.ping_finished.emit(ids)
            if not self._pings:
                self.busy.emit("")

        def one(item):
            sid, ms = item
            s = self.store.server(sid) or self.store.balancer(sid)
            if s is not None:
                s.latency = ms
                self.ping_result.emit(sid, ms)

        def done(result):
            for s in self.store.servers + self.store.balancers:
                if s.id in result:
                    s.latency = result[s.id]
            # A balancer is as fast as its best server: no need to measure it again.
            for b in self.store.balancers:
                members = self.store.members(b)
                if b.id in result or not any(m.id in result for m in members):
                    continue
                known = [m.latency for m in members if m.latency is not None]
                good = [ms for ms in known if ms >= 0]
                b.latency = min(good) if good else (-1 if known else None)
            self.store.save()
            finished()
            self.servers_changed.emit()

        def fail(err):
            finished()
            self.message.emit("error", tr("Пинг: {err}", err=err))

        self.run_async(lambda: ping.ping_servers(servers, url, timeout,
                                                 on_result=lambda sid, ms: self._ui(one, (sid, ms)), name=name),
                       done, fail)

    def update_geo(self) -> None:
        self.busy.emit(tr("Загрузка geoip/geosite…"))
        proxy = self._proxy_for_downloads()

        def work():
            for name, url in GEO_URLS.items():
                r = httpx.get(url, follow_redirects=True, timeout=120, proxy=proxy)
                r.raise_for_status()
                if len(r.content) < 100_000:
                    raise ValueError(tr("{name}: подозрительно маленький файл", name=name))
                tmp = paths.GEO_DIR / (name + ".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(paths.GEO_DIR / name)

        def done(_):
            self.busy.emit("")
            self.message.emit("info", tr("Geo-файлы обновлены. Применятся при следующем подключении."))

        def fail(err):
            self.busy.emit("")
            self.message.emit("error", tr("Не удалось обновить geo-файлы: {err}", err=err))

        self.run_async(work, done, fail)
