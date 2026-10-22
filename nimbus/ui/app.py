"""Application bootstrap: single instance, tray, elevation."""
from __future__ import annotations

import getpass
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QFontMetrics
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..i18n import tr
from .. import balancer, deeplink, paths, updater
from ..platform import current as osys
from ..controller import Controller
from ..settings import Settings
from . import flags, icons, theme
from .dialogs import ask, flag_icon
from .main_window import MainWindow
from .server_list import BALANCERS

INSTANCE_KEY = f"{paths.APP_NAME}-{getpass.getuser()}"


def _signal_running_instance(msg: bytes) -> bool:
    """Send msg to the running copy: b"show", b"quit" or b"link <url>"."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    sock.write(msg)
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


class App:
    def __init__(self, argv: list[str]):
        self.args = set(argv[1:])
        self.link = deeplink.from_args(argv[1:])   # nimbus://… the OS started us with
        self.qt = QApplication(argv)
        self.qt.setApplicationName(paths.APP_NAME)
        if osys.OS_NAME != "Windows":
            # Wayland docks find the icon through the menu entry (nimbus.desktop) by this name.
            self.qt.setDesktopFileName(osys.DESKTOP_FILE.removesuffix(".desktop"))
        self.qt.setQuitOnLastWindowClosed(False)
        theme.load_fonts()
        theme.set_palette(Settings.load().theme)
        self.qt.setFont(theme.font(9.5))
        self.qt.setStyleSheet(theme.stylesheet())
        self.qt.setWindowIcon(theme.app_icon())

    def run(self) -> int:
        if "--quit" in self.args:
            return self._quit_running()
        # One Nimbus per user. The mutex is the source of truth: the pipe alone let a second
        # copy start whenever it couldn't reach the first (e.g. the first runs elevated after a
        # switch to TUN), and every launch from the exe left one more icon in the tray.
        # An elevated relaunch may start before the old instance has exited; wait for it.
        deadline = time.time() + (8 if self.args & {"--elevated", "--restarted"} else 0)
        while True:
            self._mutex = osys.single_instance_lock(INSTANCE_KEY)
            if self._mutex:
                break
            if time.time() >= deadline:
                msg = b"link " + self.link.encode() if self.link else b"show"
                for _ in range(10):  # the other copy may still be starting up
                    if _signal_running_instance(msg):
                        break
                    time.sleep(0.3)
                return 0
            time.sleep(0.3)
        QLocalServer.removeServer(INSTANCE_KEY)
        self.server = QLocalServer()
        # Let a non-elevated launch reach an elevated instance to bring its window up.
        self.server.setSocketOptions(QLocalServer.WorldAccessOption)
        self.server.listen(INSTANCE_KEY)
        self.server.newConnection.connect(self._on_instance_message)

        self.ctl = Controller()
        self.win = MainWindow(self.ctl)
        self.win.quit_requested.connect(self.quit)
        self.win.restart_requested.connect(self.restart)
        self.ctl.need_admin.connect(self._ask_elevation)
        self.ctl.update_checked.connect(self._on_update_checked)
        self._update_dialog = None
        self._pending_update = None
        self._build_tray()

        minimized = "--autostart" in self.args and self.ctl.settings.start_minimized
        if not minimized:
            self.win.show()
            QTimer.singleShot(0, self._log_startup)  # runs once the window has been painted

        s = self.ctl.settings
        if s.update_on_launch:
            self.ctl.update_subscriptions()
        if "--connect" in self.args or s.auto_connect:
            QTimer.singleShot(300, self.ctl.connect)
        if self.link:
            QTimer.singleShot(200, lambda: (self.show_window(), self.win.open_link(self.link)))
        if "--updated" in self.args:
            QTimer.singleShot(600, lambda: self.win.toaster.show(tr("Nimbus обновлён до версии {version}",
                                                                    version=paths.VERSION)))
        elif "--update-failed" in self.args:
            QTimer.singleShot(600, lambda: self.win.toaster.show(
                tr("Обновление не установилось: файлы программы были заняты. Прежняя версия на месте, "
                   "попробуйте ещё раз"), error=True))
        QTimer.singleShot(1500, self._register_links)
        QTimer.singleShot(10_000, self.ctl.maybe_check_updates)
        # What the last update left in the temp folder; later, so a swap helper has surely exited.
        QTimer.singleShot(60_000, lambda: threading.Thread(target=updater.cleanup, daemon=True).start())
        self.qt.aboutToQuit.connect(self.ctl.shutdown)
        return self.qt.exec()

    @staticmethod
    def _log_startup() -> None:
        """Append how long the window took to appear to logs/startup.log (last 50 launches)."""
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {paths.VERSION}  window shown in {osys.process_age_ms()} ms\n"
        log = paths.LOG_DIR / "startup.log"
        try:
            old = log.read_text("utf-8").splitlines(keepends=True)[-49:] if log.exists() else []
            log.write_text("".join(old) + line, "utf-8")
        except OSError:
            pass

    # -- tray ----------------------------------------------------------------------------
    TRAY_BALANCERS = 8   # balancers listed in the tray before "Все балансировщики…"
    TRAY_TEXT_W = 170    # px: names from providers carry speeds and emoji and made the menu half a screen wide

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.app_icon("off"))
        # The actions that stay belong to the tray icon, so rebuilding the menu doesn't delete them.
        self.tray_toggle = QAction(tr("Подключиться"), self.tray)
        self.tray_toggle.triggered.connect(self.ctl.toggle)
        self.tray_mode = {}
        for mode, text in (("proxy", tr("Системный прокси")), ("tun", "TUN")):
            act = QAction(text, self.tray, checkable=True)
            act.triggered.connect(lambda _=False, m=mode: self._set_mode(m))
            self.tray_mode[mode] = act
        self.tray_open = QAction(tr("Открыть"), self.tray)
        self.tray_open.triggered.connect(self.show_window)
        self.tray_quit = QAction(tr("Выход"), self.tray)
        self.tray_quit.triggered.connect(self.quit)
        self.tray_menu = self._tray_submenu(None, "")
        self.tray_menu.aboutToShow.connect(self._fill_tray)
        self._fill_tray()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.ctl.state_changed.connect(self._on_state)
        self.ctl.node.connect(lambda _: self._on_state(self.ctl.state))
        self.ctl.servers_changed.connect(lambda: self._on_state(self.ctl.state))
        self.ctl.message.connect(self._on_message)
        self._on_state(self.ctl.state)

    @staticmethod
    def _tray_submenu(parent: QMenu | None, title: str) -> QMenu:
        """A menu in the tray's compact style (QMenu#tray in the style sheet)."""
        menu = QMenu(title, parent, objectName="tray")
        menu.setToolTipsVisible(True)
        if parent is not None:
            parent.addMenu(menu)
        return menu

    def _tray_icon_for(self, srv) -> "QIcon":
        if self.ctl.store.balancer(srv.id):
            return icons.icon("bolt", theme.TEXT, 16)
        return flag_icon(flags.split(srv.name)[0])

    def _fit(self, act: QAction) -> QAction:
        """Cut a long name with "…"; the whole one is in the tooltip."""
        full = act.text()
        short = QFontMetrics(theme.font(9.5, QFont.DemiBold)).elidedText(full, Qt.ElideRight, self.TRAY_TEXT_W)
        if short != full:
            act.setText(short)
            act.setToolTip(full)
        return act

    def _pick_action(self, menu: QMenu, srv, text: str = "") -> QAction:
        """A server / balancer to connect through, ticked if it's the chosen one."""
        act = self._fit(QAction(self._tray_icon_for(srv), text or balancer.plain(srv.name), menu))
        act.setCheckable(True)
        act.setChecked(srv.id == self.ctl.settings.selected_server)
        act.setEnabled(self.ctl.state in ("connected", "disconnected"))
        act.triggered.connect(lambda _=False, sid=srv.id: self._tray_pick(sid))
        menu.addAction(act)
        return act

    def _fill_tray(self) -> None:
        """Rebuilt on each open: the server in use, recent ones and balancers, mode, routing."""
        menu = self.tray_menu
        menu.clear()
        srv, state = self.ctl.selected, self.ctl.state
        connected = state == "connected"
        if srv:
            text = balancer.plain(srv.name)
            if connected and self.ctl.current_node:
                text += f"  →  {balancer.plain(self.ctl.current_node)}"
            cur = self._fit(QAction(self._tray_icon_for(srv), text, menu))
            cur.setToolTip((tr("Подключено: ") if connected else tr("Выбран: ")) + cur.toolTip())
        else:
            cur = QAction(tr("Сервер не выбран"), menu)
        bold = QFont(cur.font())
        bold.setBold(True)
        cur.setFont(bold)
        # Not greyed out: a click opens the window on this server.
        cur.triggered.connect(lambda: self._open_at(self.ctl.settings.selected_server))
        menu.addAction(cur)
        menu.addSeparator()
        menu.addAction(self.tray_toggle)

        recent = self.ctl.recent()
        if recent:
            sub = self._tray_submenu(menu, tr("Недавние"))
            for r in recent:
                self._pick_action(sub, r)
        bals = self.ctl.store.balancers
        if bals:
            sub = self._tray_submenu(menu, tr("Балансировщики"))
            # A handful fits a tray menu; the one in use always among them, the rest in the window.
            shown = bals[:self.TRAY_BALANCERS]
            current = self.ctl.store.balancer(self.ctl.settings.selected_server)
            if current and current not in shown:
                shown = shown[:-1] + [current]
            for b in shown:
                text = b.name
                if current is b and connected and self.ctl.current_node:
                    text += f"  →  {balancer.plain(self.ctl.current_node)}"
                self._pick_action(sub, b, text)
            if len(bals) > len(shown):
                sub.addSeparator()
                sub.addAction(tr("Все балансировщики ({n})…", n=len(bals)), lambda: self._open_at(BALANCERS))

        menu.addSeparator()
        for act in self.tray_mode.values():
            menu.addAction(act)
        menu.addSeparator()
        self._fill_tray_routing(menu)
        menu.addSeparator()
        menu.addAction(self.tray_open)
        menu.addAction(self.tray_quit)

    def _fill_tray_routing(self, menu: QMenu) -> None:
        """The window's routing switch: "Умная" where the config has rules, "Весь трафик", and the
        presets: one is listed as is, several fold into "Пресеты"."""
        win, s = self.win, self.ctl.settings
        info, preset, key = win._route_state()
        options = []
        if info is not None:
            options.append((True, tr("Умная"), tr("Правила маршрутизации от вашего VPN-провайдера")))
        options.append((False, tr("Весь трафик"), tr("Весь трафик, включая российские сайты, идёт через VPN")))
        for value, text, tip in options:
            act = menu.addAction(text, lambda v=value: win._route_changed(v))
            act.setCheckable(True)
            act.setChecked(key == value)
            act.setToolTip(tip)
        presets = s.route_presets
        if len(presets) == 1:
            p = presets[0]
            act = self._fit(menu.addAction(p["name"], lambda pid=p["id"]: win._apply_route(route_preset=pid)))
            act.setCheckable(True)
            act.setChecked(key == "preset")
        elif presets:
            title = tr("Пресет: {name}", name=preset['name']) if preset else tr("Пресеты")
            sub = self._tray_submenu(menu, QFontMetrics(theme.font(9.5)).elidedText(title, Qt.ElideRight,
                                                                                    self.TRAY_TEXT_W))
            if preset:
                f = QFont(sub.menuAction().font())
                f.setBold(True)
                sub.menuAction().setFont(f)
            for p in presets:
                act = self._fit(sub.addAction(p["name"], lambda pid=p["id"]: win._apply_route(route_preset=pid)))
                act.setCheckable(True)
                act.setChecked(p["id"] == s.route_preset)
            sub.addSeparator()
            sub.addAction(tr("Настроить пресеты…"), lambda: (self.show_window(), win.show_settings("presets")))

    def _tray_pick(self, server_id: str) -> None:
        """Connect through a server or balancer; the one already in use stays as it is."""
        if server_id == self.ctl.settings.selected_server and self.ctl.state == "connected":
            return
        self.ctl.select(server_id, connect=True)

    def _open_at(self, target: str) -> None:
        """Bring the window up on a server (its id) or on the balancers (BALANCERS)."""
        self.show_window()
        lst = self.win.list
        QTimer.singleShot(60, lambda: lst.scroll_to_group(BALANCERS) if target == BALANCERS
                          else lst.scroll_to_selected())

    def _set_mode(self, mode: str) -> None:
        from dataclasses import replace
        self.ctl.apply_settings(replace(self.ctl.settings, tunnel_mode=mode))
        self.win._sync_mode_buttons()
        self._on_state(self.ctl.state)

    def _on_state(self, state: str) -> None:
        self.tray.setIcon(theme.app_icon("on" if state == "connected" else "off"))
        srv = self.ctl.selected
        tip = f"{paths.APP_NAME}: {tr('подключено') if state == 'connected' else tr('отключено')}"
        if srv and state == "connected":
            tip += f"\n{balancer.plain(srv.name)}"
            if self.ctl.current_node:
                tip += f" → {balancer.plain(self.ctl.current_node)}"
        self.tray.setToolTip(tip[:127])
        self.tray_toggle.setText(tr("Отключиться") if state == "connected" else tr("Подключиться"))
        self.tray_toggle.setEnabled(state in ("connected", "disconnected"))
        for mode, act in self.tray_mode.items():
            act.setChecked(mode == self.ctl.settings.tunnel_mode)

    @staticmethod
    def _register_links() -> None:
        """nimbus:// links open this copy (an installed one also gets it from the installer, a
        .deb / .rpm from its menu entry)."""
        if getattr(sys, "frozen", False) and not paths.PACKAGE:
            try:
                icon = paths.DATA_DIR / "nimbus.png"   # Linux: for the .desktop entry
                if osys.OS_NAME != "Windows" and not icon.exists():
                    theme.app_pixmap(256).save(str(icon), "PNG")
                osys.register_url_scheme(deeplink.SCHEME, paths.APP_NAME, str(icon))
            except OSError:
                pass

    # -- updates -------------------------------------------------------------------------
    def _on_update_checked(self, release, manual: bool, error: str) -> None:
        if release is None:
            return
        if manual or (self.win.isVisible() and not self.win.isMinimized()):
            self._show_update(release)
        else:
            # In the tray: say so, and offer the dialog when the window opens.
            self._pending_update = release
            self.tray.showMessage(paths.APP_NAME, tr("Доступна новая версия {version}. Откройте Nimbus, чтобы "
                                                     "обновиться.", version=release.version),
                                  QSystemTrayIcon.Information, 8000)

    def _show_update(self, release) -> None:
        from .update_dialog import UpdateDialog

        self._pending_update = None
        if self._update_dialog is not None and self._update_dialog.isVisible():
            return
        parent = QApplication.activeModalWidget() or self.win
        dlg = self._update_dialog = UpdateDialog(parent, self.ctl, release, self.quit)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda: setattr(self, "_update_dialog", None))
        dlg.show()

    def _on_message(self, level: str, text: str) -> None:
        if not self.win.isVisible():
            icon = QSystemTrayIcon.Warning if level == "error" else QSystemTrayIcon.Information
            self.tray.showMessage(paths.APP_NAME, text, icon, 5000)

    def show_window(self) -> None:
        self.win.show()
        self.win.setWindowState(self.win.windowState() & ~Qt.WindowMinimized)
        self.win.raise_()
        self.win.activateWindow()
        if self._pending_update is not None:
            release = self._pending_update
            QTimer.singleShot(300, lambda: self._show_update(release))

    def _on_instance_message(self) -> None:
        sock = self.server.nextPendingConnection()
        msg = b""
        while sock.waitForReadyRead(300):   # a long link may come in several pieces
            msg += bytes(sock.readAll())
        msg += bytes(sock.readAll())
        if msg.startswith(b"link "):
            self.show_window()
            link = msg[5:].decode("utf-8", "replace").strip()
            QTimer.singleShot(0, lambda: self.win.open_link(link))
        elif msg.startswith(b"show"):
            self.show_window()
        elif msg.startswith(b"quit"):
            self.quit()

    def _quit_running(self, timeout: float = 15) -> int:
        """`Nimbus.exe --quit`, run by the installer before an update, and `--quit --uninstall`,
        run by the uninstaller: closes the running copy the normal way (it disconnects and puts
        the proxy settings back) and waits until it has gone. If a copy died while connected,
        its proxy settings are put back here, so nobody is left without internet after an
        uninstall. Exit code 0 if nothing is left running."""
        gone = not _signal_running_instance(b"quit")
        deadline = time.time() + timeout
        while not gone and time.time() < deadline:
            gone = bool(osys.single_instance_lock(INSTANCE_KEY))
            if not gone:
                time.sleep(0.25)
        if gone:
            from ..core import restore_proxy_after_crash
            restore_proxy_after_crash()
        if "--uninstall" in self.args and osys.autostart_is_this_exe(paths.APP_NAME):
            osys.set_autostart(False, paths.APP_NAME)
        if "--uninstall" in self.args:
            osys.unregister_url_scheme(deeplink.SCHEME)
        return 0 if gone else 1

    # -- elevation -----------------------------------------------------------------------
    def _ask_elevation(self) -> None:
        self.show_window()
        if not osys.TUN_RELAUNCH:
            self._grant_tun()
            return
        if not ask(self.win, tr("Нужны права администратора"),
                   tr("Режим TUN создаёт виртуальный сетевой адаптер и меняет маршруты — для этого Windows "
                      "требует права администратора. Перезапустить Nimbus от имени администратора?"),
                   tr("Перезапустить")):
            return
        self.ctl.shutdown()
        self.server.close()
        if osys.relaunch_as_admin(["--elevated", "--connect"]):
            self.qt.exit(0)
        else:
            self.server.listen(INSTANCE_KEY)
            self.win.toaster.show(tr("Запуск от имени администратора отменён."), error=True)

    def _grant_tun(self) -> None:
        """Linux: sing-box gets the network rights it needs once (a password prompt); the
        window itself never runs as root."""
        if not ask(self.win, tr("Разрешить режим TUN"),
                   tr("Режиму TUN нужны права на сетевой адаптер и маршруты. Nimbus один раз попросит пароль "
                      "администратора и выдаст эти права только ядру sing-box, а также разрешит без пароля "
                      "настраивать DNS своего адаптера. Продолжить?"),
                   tr("Продолжить")):
            return

        def done(ok):
            if ok:
                self.ctl.connect()
            else:
                self.win.toaster.show(tr("Права для режима TUN не выданы."), error=True)
        self.ctl.run_async(osys.grant_tun, done)

    def restart(self) -> None:
        """Start a fresh copy (e.g. in another language) and quit; a connection comes back."""
        args = ["--restarted"] + (["--connect"] if self.ctl.state == "connected" else [])

        def go():
            self.server.close()   # the new copy waits for the single-instance mutex, not the pipe
            osys.relaunch(args)
            self.quit()
        self.ctl.disconnect(then=go)

    def quit(self) -> None:
        self.win.really_quit = True
        self.tray.hide()
        self.qt.quit()


def main() -> int:
    return App(sys.argv).run()
