"""Main window: connection panel on the left, servers on the right (landscape)."""
from __future__ import annotations

import gc
import json
import time
from dataclasses import replace

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetricsF, QGuiApplication, QKeySequence, QPainter, \
    QPen, QPixmapCache, QShortcut
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget,
)

from .. import i18n
from ..i18n import tr
from .. import deeplink, paths, qr, share
from ..platform import current as osys
from ..config_builder import active_preset, provider_routing
from ..controller import Controller
from ..store import Balancer, Server
from . import flags, icons, theme
from .dialogs import AddDialog, BalancerDialog, ConfigsDialog, LogDialog, UserAgentDialog, ask, get_text, inform, \
    plural
from .presets import describe
from .server_list import BALANCERS, Row, ServerList
from .settings_dialog import SettingsDialog
from .share_ui import QrDialog, save_text
from .widgets import Anim, ElidedLabel, IconButton, PowerButton, Segmented, SpeedGraph, Spinner, ThemeSwitch, \
    Toaster, caption

STATUS_TEXT = {"disconnected": tr("Не подключено"), "connecting": tr("Подключение"),
               "connected": tr("Подключено"), "disconnecting": tr("Отключение")}
MANUAL = "__manual__"
SORT_MODES = [("source", tr("Порядок"), tr("Как в подписке у провайдера")),
              ("ping", tr("Пинг"), tr("Внутри каждой подписки — сначала самые быстрые")),
              ("name", tr("А–Я"), tr("Внутри каждой подписки — по алфавиту, без учёта эмодзи"))]
PROTO_NAMES = {"vless": "VLESS", "vmess": "VMess", "trojan": "Trojan", "ss": "Shadowsocks",
               "shadowsocks": "Shadowsocks", "hysteria": "Hysteria2", "hysteria2": "Hysteria2", "hy2": "Hysteria2",
               "socks": "SOCKS5", "wireguard": "WireGuard", "wg": "WireGuard", "http": "HTTP"}
CRYPT_TEXT = (tr("Зашифрованная ссылка Happ не открылась: {reason}. Ссылка могла быть изменена при "
                 "копировании или зашифрована ключом, которого нет в этой версии Nimbus. Попросите у "
                 "VPN-провайдера обычную ссылку на подписку — она начинается с https://."))
ROUTE_TIPS = {
    True: tr("Умная* — маршруты из вашей подписки: какие сайты открываются без VPN, решает VPN-провайдер"),
    False: tr("Весь трафик, включая российские сайты, идёт через VPN"),
}


def route_hint(info: dict | None, provider: bool, preset: dict | None = None, tun: bool = False,
               presets: bool = False, balancer: bool = False) -> str:
    if preset:
        what = describe(preset)
        if preset.get("mode", "bypass") == "vpn":
            text = tr("Пресет «{name}»: через VPN идут только {what}, всё остальное — напрямую.",
                      name=preset['name'], what=what)
        else:
            text = tr("Пресет «{name}»: {what} — без VPN, остальное через VPN.", name=preset['name'], what=what)
            if preset.get("provider", True) and info is not None:
                text += tr(" Правила провайдера* тоже действуют.")
        if preset.get("apps") and not tun:
            text += tr(" Программы без поддержки системного прокси учитываются только в режиме TUN.")
        return text
    if info is None and balancer:
        return (tr("Весь трафик идёт через VPN: в балансировщике серверы разных подписок, поэтому правила "
                   "провайдера не применяются.") + (tr(" Свои правила — в пресетах.") if presets else ""))
    if info is None:
        if presets:
            return (tr("Весь трафик идёт через VPN: в этом конфиге VPN-провайдер не задал правил маршрутизации. "
                       "Свои правила — в пресетах."))
        return (tr("Весь трафик идёт через VPN: в этом конфиге VPN-провайдер не задал правил маршрутизации, "
                   "поэтому выбирать нечего."))
    if not provider:
        return tr("Все сайты, включая российские, идут через VPN. Правила из подписки не используются.")
    what = tr("российские сайты открываются без VPN") if info["ru"] else tr("часть сайтов открывается без VPN")
    return tr("* Правила маршрутизации задаёт ваш VPN-провайдер в подписке: {what}, остальные — через VPN.",
              what=what)

def gap(layout: QVBoxLayout, h: int) -> None:
    """Vertical space of `h` px that gives way when the window is too short for everything."""
    layout.addSpacerItem(QSpacerItem(0, h, QSizePolicy.Minimum, QSizePolicy.Maximum))


def proto_label(s: Server) -> str:
    proto = s.protocol
    if proto.startswith("balancer"):
        n = int(proto.split("·")[-1].strip() or 0)
        return tr("Авто · {n} {nodes}", n=n, nodes=plural(n, "узел", "узла", "узлов"))
    return PROTO_NAMES.get(proto, proto.upper())


class ServerChip(QWidget):
    """Flag + name of the chosen server under the connect button."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.code, self.name, self.badge = None, "", ""
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = Anim(self, 150)
        self._font = theme.font(9.5, QFont.Medium)

    def set_server(self, srv: Server | None, balancer: bool = False, node: str = "") -> None:
        """balancer: a bolt instead of the flag; node: the server it goes through now."""
        self.code, self.name = flags.split(srv.name) if srv else (None, tr("Сервер не выбран"))
        self.badge = "bolt" if balancer and srv else ""
        if self.badge:
            self.code, self.name = None, srv.name + (f"  →  {flags.split(node)[1]}" if node else "")
        tip = srv.name if srv else ""
        if node:
            tip += tr("\nСейчас самый быстрый: {node}", node=node)
        self.setToolTip(tip)
        self.update()

    def enterEvent(self, e):
        self._hover.to(1)

    def leaveEvent(self, e):
        self._hover.to(0)

    def mouseReleaseEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetricsF(self._font)
        text = fm.elidedText(self.name, Qt.ElideRight, self.width() - 70)
        w = min(self.width() - 2, fm.horizontalAdvance(text) + 62)
        r = QRectF((self.width() - w) / 2, 0.5, w, self.height() - 1)
        p.setPen(QPen(theme.mix(theme.BORDER, theme.BORDER_2, self._hover.v), 1))
        p.setBrush(theme.mix(theme.SURFACE, theme.SURFACE_2, self._hover.v))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.badge:
            flags.paint_badge(p, QRectF(r.x() + 14, r.center().y() - 7.5, 22, 15), self.badge, 3)
        else:
            flags.paint(p, QRectF(r.x() + 14, r.center().y() - 7.5, 22, 15), self.code, 3)
        p.setFont(self._font)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(r.x() + 44, r.y(), w - 56, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class ExitIpLabel(QWidget):
    """IP sites see through the VPN and its country's flag, under the server chip, with a
    button to check again. Clicking the IP copies it."""
    clicked = Signal()
    refresh = Signal()

    def __init__(self):
        super().__init__()
        self.status, self.ip, self.code = "", "", None
        self.setFixedHeight(24)
        self._font = theme.font(9, QFont.Medium, tabular=True)
        self.button = IconButton("refresh", tr("Проверить IP ещё раз"), size=22)
        self.button.setParent(self)
        self.button.clicked.connect(self.refresh)
        self.button.hide()

    def _text(self) -> str:
        if self.status == "fail" and not self.ip:
            return tr("IP не определён")
        if self.status == "checking" and not self.ip:
            return tr("Определяем IP…")
        return self.ip

    def _layout(self) -> tuple[float, float, float]:
        """x of the flag, its width and the width of the text, centred with the button."""
        flag_w = 20 if self.ip else 0
        text_w = QFontMetricsF(self._font).horizontalAdvance(self._text())
        total = flag_w + (7 if flag_w else 0) + text_w + 4 + self.button.width()
        return (self.width() - total) / 2, flag_w, text_w

    def set_ip(self, status: str, ip: str, code: str) -> None:
        self.status, self.ip, self.code = status, ip, code or None
        self.button.setVisible(bool(status))
        self.button.set_spinning(status == "checking")
        self.button.setEnabled(status != "checking")
        tip = tr("Ваш IP через VPN — нажмите, чтобы скопировать") if ip else ""
        if status == "fail" and ip:
            tip = tr("Не удалось проверить IP заново — показан последний известный")
        elif status == "fail":
            tip = tr("Сервисы проверки IP не ответили через VPN. Причина — в логах ядра, строка "
                     "«IP check failed»")
        self.setToolTip(tip)
        self.resizeEvent(None)
        self.update()

    def resizeEvent(self, _):
        x, flag_w, text_w = self._layout()
        self.button.move(int(x + flag_w + (7 if flag_w else 0) + text_w + 4), (self.height() - self.button.height()) // 2)

    def mouseReleaseEvent(self, e):
        x, flag_w, text_w = self._layout()
        if self.ip and x <= e.position().x() <= x + flag_w + 7 + text_w:
            self.clicked.emit()

    def paintEvent(self, _):
        if not self.status:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font)
        x, flag_w, text_w = self._layout()
        if flag_w:
            p.setOpacity(0.55 if self.status == "checking" else 1.0)
            flags.paint(p, QRectF(x, self.height() / 2 - 6.5, flag_w, 13), self.code, 2.5)
            x += flag_w + 7
        p.setPen(QColor(theme.TEXT_2 if self.ip and self.status == "ok" else theme.MUTED))
        p.drawText(QRectF(x, 0, text_w + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text())
        p.end()


class MainWindow(QMainWindow):
    quit_requested = Signal()
    restart_requested = Signal()         # the interface language changed

    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(paths.APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1220, 760)
        # Only the width is fixed here: the height comes from the layout, so the window can't be
        # made shorter than the sidebar needs (it used to, and the texts slid under the button).
        self.setMinimumWidth(1040)
        self._log_dialog: LogDialog | None = None
        self.really_quit = False
        self._collapsed: set[str] = set()
        self._ping_ids: set[str] = set()
        self._connected_at = 0.0
        self._speed = (0.0, 0.0)

        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())
        lay.addWidget(self._build_main(), 1)
        self.toaster = Toaster(root)

        self._clock = QTimer(self, interval=1000, timeout=self._tick)
        QShortcut(QKeySequence.Paste, self, self.paste_clipboard)
        QShortcut(QKeySequence.Find, self, lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("F5"), self, lambda: ctl.update_subscriptions())
        QShortcut(QKeySequence("Ctrl+P"), self, lambda: self._ping())

        ctl.state_changed.connect(self.on_state)
        ctl.servers_changed.connect(lambda: self.refresh_servers())
        ctl.speed.connect(self.on_speed)
        ctl.exit_ip.connect(self.exit_ip.set_ip)
        ctl.busy.connect(self.on_busy)
        ctl.ping_result.connect(self._on_ping_result)
        ctl.node.connect(lambda _: self.refresh_servers(animate=False))
        # Ping results re-sort the list; batching them keeps it calm when dozens arrive at once.
        self._ping_refresh = QTimer(self, singleShot=True, interval=250,
                                    timeout=lambda: self.refresh_servers(animate=False))
        ctl.message.connect(self.on_message)
        self.on_state(ctl.state)
        self.refresh_servers()
        self._sync_mode_buttons(animate=False)

    # -- layout ----------------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QWidget(objectName="sidebar")
        side.setFixedWidth(352)
        v = QVBoxLayout(side)
        v.setContentsMargins(30, 26, 30, 26)
        v.setSpacing(0)

        brand = QHBoxLayout()
        name = QLabel("nimbus")
        name.setFont(theme.font(17, QFont.Bold, spacing=-0.4))
        ver = QLabel(paths.VERSION + ("  portable" if paths.PORTABLE else ""))
        ver.setFont(theme.font(8, QFont.Medium))
        theme.styled(ver, lambda: f"color: {theme.FAINT}; padding-left: 6px; padding-bottom: 3px;")
        brand.addWidget(name)
        brand.addWidget(ver, 0, Qt.AlignBottom)
        brand.addStretch()
        self.theme_switch = ThemeSwitch(theme.is_dark())
        self.theme_switch.theme_changed.connect(self._set_theme)
        brand.addWidget(self.theme_switch, 0, Qt.AlignVCenter)
        v.addLayout(brand)
        v.addStretch(2)

        # Fixed spacing below is gap(): in a short window it gives way first, then the button and
        # the graph shrink; the window can't get shorter than that (see setMinimumWidth above).
        self.power = PowerButton(172, 116)
        self.power.clicked.connect(self.ctl.toggle)
        v.addWidget(self.power, 0, Qt.AlignHCenter)
        gap(v, 10)
        self.status = QLabel(alignment=Qt.AlignHCenter)
        self.status.setFont(theme.font(16, QFont.DemiBold, spacing=-0.2))
        self.status.setMinimumHeight(self.status.sizeHint().height())
        v.addWidget(self.status)
        v.addSpacing(2)
        gap(v, 2)
        self.substatus = QLabel(alignment=Qt.AlignHCenter)
        self.substatus.setFont(theme.font(9, QFont.Medium, tabular=True))
        theme.styled(self.substatus, lambda: f"color: {theme.MUTED};")
        v.addWidget(self.substatus)
        v.addSpacing(8)
        gap(v, 10)
        self.chip = ServerChip()
        self.chip.clicked.connect(lambda: self.list.scroll_to_selected())
        v.addWidget(self.chip)
        v.addSpacing(6)
        self.exit_ip = ExitIpLabel()
        self.exit_ip.clicked.connect(self._copy_exit_ip)
        self.exit_ip.refresh.connect(lambda: self.ctl.check_exit_ip(manual=True))
        v.addWidget(self.exit_ip)
        v.addSpacing(10)
        v.addStretch(3)

        stats = QHBoxLayout()
        stats.setSpacing(18)
        self.down_val, self.up_val = QLabel(), QLabel()
        for title, lbl, glyph in ((tr("Загрузка"), self.down_val, "arrow_down"),
                                  (tr("Отдача"), self.up_val, "arrow_up")):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(caption(title))
            lbl.setTextFormat(Qt.RichText)
            lbl.setFont(theme.font(15, QFont.DemiBold, tabular=True))
            col.addWidget(lbl)
            stats.addLayout(col)
        stats.addStretch()
        v.addLayout(stats)
        v.addSpacing(6)
        gap(v, 4)
        self.graph = SpeedGraph()
        v.addWidget(self.graph)
        v.addSpacing(14)
        gap(v, 10)

        v.addWidget(caption(tr("Режим")))
        v.addSpacing(8)
        self.mode_seg = Segmented([
            ("proxy", tr("Системный прокси"), tr("Браузеры и программы, которые используют системный прокси. "
                                                 "Без прав администратора")),
            ("tun", "TUN", tr("Весь трафик компьютера, включая игры. Нужны права администратора")
                    if osys.OS_NAME == "Windows" else
                    tr("Весь трафик компьютера, включая игры. Один раз попросит пароль администратора"))])
        self.mode_seg.changed.connect(self._mode_changed)
        v.addWidget(self.mode_seg)
        v.addSpacing(10)
        gap(v, 6)
        v.addWidget(caption(tr("Маршрутизация")))
        v.addSpacing(8)
        self.route_seg = Segmented([(True, tr("Умная*"), ROUTE_TIPS[True]),
                                    (False, tr("Весь трафик"), ROUTE_TIPS[False])])
        self.route_seg.changed.connect(self._route_changed)
        self.route_seg.reselected.connect(lambda key: key == "preset" and self._preset_menu())
        self.route_fixed = QLabel(tr("Весь трафик через VPN"), alignment=Qt.AlignCenter)
        self.route_fixed.setFixedHeight(34)
        self.route_fixed.setFont(theme.font(8.8, QFont.DemiBold))
        theme.styled(self.route_fixed, lambda: f"color: {theme.TEXT_2}; border: 1px solid {theme.BORDER}; "
                                               f"border-radius: 17px; background: {theme.SURFACE};")
        add_preset = IconButton("plus", tr("Пресеты маршрутизации"), size=24)
        add_preset.setFixedWidth(16)  # narrow, so the labels of the pill next to it fit
        add_preset.clicked.connect(lambda: self.show_settings("presets"))
        route_row = QHBoxLayout()
        route_row.setSpacing(2)
        route_row.addWidget(self.route_seg, 1)
        route_row.addWidget(self.route_fixed, 1)
        route_row.addWidget(add_preset, 0, Qt.AlignVCenter)
        v.addLayout(route_row)
        v.addSpacing(8)
        self.route_hint = QLabel()
        self.route_hint.setWordWrap(True)
        self.route_hint.setFont(theme.font(8.2))
        theme.styled(self.route_hint, lambda: f"color: {theme.MUTED};")
        self.route_hint.setMinimumHeight(34)
        self.route_hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        v.addWidget(self.route_hint)
        self._hint_width = side.width() - 60  # the sidebar is fixed-width: 30 px margins
        return side

    def _build_main(self) -> QWidget:
        main = QWidget()
        v = QVBoxLayout(main)
        v.setContentsMargins(30, 24, 30, 18)
        v.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.count = QLabel()  # "Серверы 61"
        self.count.setFont(theme.font(18, QFont.DemiBold, spacing=-0.3))
        self.count.setTextFormat(Qt.RichText)
        top.addWidget(self.count)
        top.addStretch()
        self.spinner = Spinner()
        self.busy_label = QLabel()
        self.busy_label.setFont(theme.font(8.8, QFont.Medium))
        theme.styled(self.busy_label, lambda: f"color: {theme.MUTED}; padding-right: 10px;")
        self.spinner.hide()
        self.busy_label.hide()
        top.addWidget(self.spinner)
        top.addWidget(self.busy_label)
        self.update_btn = IconButton("refresh", tr("Обновить подписки  (F5)"))
        self.update_btn.clicked.connect(lambda: self.ctl.update_subscriptions())
        self.ping_btn = IconButton("pulse", tr("Проверить задержку всех серверов  (Ctrl+P)"))
        self.ping_btn.clicked.connect(lambda: self._ping())
        logs = IconButton("logs", tr("Логи ядра"))
        logs.clicked.connect(self.show_logs)
        settings = IconButton("gear", tr("Настройки"))
        settings.clicked.connect(self.show_settings)
        for b in (self.update_btn, self.ping_btn, logs, settings):
            top.addWidget(b)
        v.addLayout(top)
        v.addSpacing(18)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit(objectName="search", placeholderText=tr("Поиск по серверам"))
        search_icon = self.search.addAction(icons.icon("search", theme.MUTED, 16), QLineEdit.LeadingPosition)
        theme.on_change(lambda: search_icon.setIcon(icons.icon("search", theme.MUTED, 16)))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(38)
        self.search.textChanged.connect(lambda _: self.refresh_servers())
        bar.addWidget(self.search, 1)
        self.sort_seg = Segmented([(k, t, tip + tr(". У отдельной группы — правый клик по ней → «Сортировка»"))
                                   for k, t, tip in SORT_MODES],
                                  self.ctl.settings.sort_mode, stretch=False, height=38)
        self.sort_seg.changed.connect(self._sort_changed)
        bar.addWidget(self.sort_seg)
        paste = IconButton("paste", tr("Вставить из буфера  (Ctrl+V)"), size=38)
        paste.clicked.connect(self.paste_clipboard)
        bar.addWidget(paste)
        add = IconButton("plus", tr("Подписка, ссылки vless:// и т.п. или Xray JSON"), text=tr("Добавить"),
                         primary=True, size=38)
        add.clicked.connect(lambda: self.add_menu(add))
        bar.addWidget(add)
        v.addLayout(bar)
        v.addSpacing(14)

        # Shown while several servers are picked (Ctrl / Shift + click): what to do with all of them.
        self.sel_bar = QWidget()
        sb = QHBoxLayout(self.sel_bar)
        sb.setContentsMargins(4, 0, 0, 10)
        sb.setSpacing(8)
        self.sel_label = QLabel()
        self.sel_label.setFont(theme.font(9.5, QFont.DemiBold))
        sb.addWidget(self.sel_label)
        hint = ElidedLabel(tr("Клик — добавить или убрать, Shift+клик — диапазон, Ctrl+A — все"), objectName="hint")
        hint.setFont(theme.font(8.4))
        sb.addWidget(hint, 1)
        self.sel_bal = IconButton("bolt", tr("Добавить выбранные серверы в балансировщик"), text=tr("В балансировщик"),
                                  size=34)
        self.sel_bal.clicked.connect(lambda: self._balancer_menu_at(self.sel_bal))
        sb.addWidget(self.sel_bal)
        self.sel_share = IconButton("share", tr("Поделиться выбранными"), text=tr("Поделиться"), size=34)
        self.sel_share.clicked.connect(lambda: self._share_marked_at(self.sel_share))
        sb.addWidget(self.sel_share)
        sel_del = IconButton("trash", tr("Удалить выбранные  (Delete)"), text=tr("Удалить"), size=34)
        sel_del.clicked.connect(self._remove_marked)
        sb.addWidget(sel_del)
        sel_clear = IconButton("close", tr("Снять выделение  (Esc)"), size=34)
        sel_clear.clicked.connect(lambda: self.list.set_marked(set()))
        sb.addWidget(sel_clear)
        self.sel_bar.hide()
        v.addWidget(self.sel_bar)

        self.list = ServerList()
        self.list.selected.connect(lambda sid: self.ctl.select(sid))
        self.list.activated.connect(lambda sid: self.ctl.select(sid, connect=True))
        self.list.context.connect(self._context_menu)
        self.list.toggled.connect(lambda gid, c: (self._collapsed.add if c else self._collapsed.discard)(gid))
        self.list.ping_requested.connect(lambda sid: self._ping([s for s in [self.ctl.resolve(sid)] if s]))
        self.list.header_action.connect(self._header_action)
        self.list.link_clicked.connect(self._link_clicked)
        self.list.share_requested.connect(self._share_at)
        self.list.marked_changed.connect(self._on_marked)
        self.list.delete_requested.connect(self._remove_marked)
        v.addWidget(self.list, 1)
        return main

    # -- state -----------------------------------------------------------------------------
    def on_state(self, state: str) -> None:
        self.power.set_state(state)
        self.status.setText(STATUS_TEXT[state])
        theme.styled(self.status, lambda: f"color: {theme.WHITE if self.ctl.state == 'connected' else theme.TEXT_2};")
        if state == "connected":
            self._connected_at = time.monotonic()
            self._clock.start()
        else:
            self._clock.stop()
            self.graph.clear()
            self.on_speed(0, 0)
        self._tick()
        self.list.set_selected(self.ctl.settings.selected_server, state == "connected")

    def _tick(self) -> None:
        state = self.ctl.state
        tun = self.ctl.settings.tunnel_mode == "tun"
        if state == "connected":
            s = int(time.monotonic() - self._connected_at)
            text = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}  ·  {'TUN' if tun else tr('прокси')}"
        elif state == "connecting":
            text = tr("Поднимаем TUN-адаптер…") if tun else tr("Запускаем ядро…")
        elif state == "disconnecting":
            text = tr("Возвращаем настройки сети…")
        else:
            text = tr("Нажмите, чтобы подключиться")
        self.substatus.setText(text)

    def on_speed(self, up: float, down: float) -> None:
        self._speed = (up, down)
        self._show_speed()
        if self.ctl.state == "connected":
            self.graph.add(up, down)

    def _show_speed(self) -> None:
        up, down = self._speed
        for lbl, val in ((self.down_val, down), (self.up_val, up)):
            num, unit = theme.human_speed(val)
            lbl.setText(f'{num}<span style="color:{theme.MUTED}; font-size:9pt; font-weight:500">&nbsp;{unit}</span>')

    def _copy_exit_ip(self) -> None:
        QGuiApplication.clipboard().setText(self.exit_ip.ip)
        self.toaster.show(tr("IP {ip} скопирован", ip=self.exit_ip.ip))

    def on_busy(self, text: str) -> None:
        self.spinner.setVisible(bool(text))
        self.busy_label.setVisible(bool(text))
        self.busy_label.setText(text)
        self.update_btn.setEnabled(not text)
        self.ping_btn.setEnabled(not text)
        self.update_btn.set_spinning(text in (tr("Обновление подписок…"), tr("Загрузка подписки…")))
        self.list.set_busy(bool(text))
        if text == tr("Проверка задержки…"):
            self.list.set_pinging(self._ping_ids)
        elif not text:
            self.list.set_pinging(set())

    def on_message(self, level: str, text: str) -> None:
        self.toaster.show(text, error=level == "error")

    def _sync_mode_buttons(self, animate: bool = True) -> None:
        self.mode_seg.set_current(self.ctl.settings.tunnel_mode, animate)
        self._sync_route(animate)
        self._tick()

    def _route_state(self) -> tuple[dict | None, dict | None, object]:
        """(provider rules of the selected config, active preset, current segment key)."""
        s = self.ctl.settings
        srv = self.ctl.selected
        info = provider_routing(srv) if srv else {"ru": True}
        preset = active_preset(s)
        key = "preset" if preset else (bool(s.use_provider_routing) if info is not None else False)
        return info, preset, key

    def _sync_route(self, animate: bool = True) -> None:
        """"Умная" only where the selected config has rules of its own to route by; presets after it."""
        s = self.ctl.settings
        info, preset, key = self._route_state()
        options = []
        if info is not None:
            options.append((True, tr("Умная*"), ROUTE_TIPS[True]))
        options.append((False, tr("Весь трафик"), ROUTE_TIPS[False]))
        presets = s.route_presets
        if presets:
            many = len(presets) > 1
            label = preset["name"] if preset else (presets[0]["name"] if not many else tr("Пресеты"))
            tip = tr("Ваши пресеты маршрутизации") + (tr(" — нажмите, чтобы выбрать") if many else "")
            options.append(("preset", label, tip, many))
        old = self.route_seg.current
        self.route_seg.set_options(options, key)
        if animate and old != key and old in [o[0] for o in options]:
            self.route_seg.set_current(old, False)
            self.route_seg.set_current(key, True)
        self.route_seg.setVisible(len(options) > 1)
        self.route_fixed.setVisible(len(options) == 1)
        self.route_hint.setText(route_hint(info, bool(s.use_provider_routing), preset, s.tunnel_mode == "tun",
                                           bool(presets), self.ctl.store.balancer(s.selected_server) is not None))
        # Reserve the wrapped text's full height: the window's minimum height then covers it and
        # a short window can't cut the last line off.
        self.route_hint.setMinimumHeight(max(34, self.route_hint.heightForWidth(self._hint_width)))

    def _route_changed(self, key) -> None:
        s = self.ctl.settings
        if key == "preset":
            if len(s.route_presets) == 1:
                self._apply_route(route_preset=s.route_presets[0]["id"])
            else:
                self._preset_menu()
            return
        info, _, _ = self._route_state()
        if info is None:  # nothing of the provider's to switch: just leave the preset
            self._apply_route(route_preset="")
        else:
            self._apply_route(route_preset="", use_provider_routing=bool(key))

    def _apply_route(self, **changes) -> None:
        new = replace(self.ctl.settings, **changes)
        if new != self.ctl.settings:
            self.ctl.apply_settings(new)
        self._sync_route()

    def _preset_menu(self) -> None:
        s = self.ctl.settings
        menu = QMenu(self)
        for p in s.route_presets:
            act = menu.addAction(p["name"], lambda pid=p["id"]: self._apply_route(route_preset=pid))
            act.setCheckable(True)
            act.setChecked(p["id"] == s.route_preset)
        menu.addSeparator()
        menu.addAction(icons.icon("gear", theme.TEXT, 16), tr("Настроить пресеты…"),
                       lambda: self.show_settings("presets"))
        r = self.route_seg.rect_of("preset")
        chosen = menu.exec(self.route_seg.mapToGlobal(r.bottomLeft().toPoint() + QPoint(0, 6)))
        if chosen is None:
            self._sync_route()  # dismissed: the thumb goes back

    def _mode_changed(self, mode) -> None:
        if mode != self.ctl.settings.tunnel_mode:
            self.ctl.apply_settings(replace(self.ctl.settings, tunnel_mode=mode))
        self._sync_mode_buttons()

    def _sort_changed(self, mode) -> None:
        self.ctl.settings.sort_mode = mode
        self.ctl.settings.save()
        self.refresh_servers()

    def _owner(self, gid: str) -> str:
        """Store owner id of a list group ("" for "Мои серверы")."""
        return "" if gid == MANUAL else gid

    def _header_action(self, action: str, gid: str) -> None:
        if gid == BALANCERS:
            if action == "ping":
                self._ping([self.ctl.resolve(b.id) for b in self.ctl.store.balancers])
            elif action == "add":
                self.edit_balancer()
            return
        if action == "ping":
            self._ping(self.ctl.store.servers_of(self._owner(gid)))
        elif action == "refresh":
            self.ctl.update_subscriptions(sub_ids=[gid])
        elif action == "add":
            self.add_configs(gid)

    def _link_clicked(self, target: str) -> None:
        if target.startswith("action:add:"):
            self.add_configs(target[len("action:add:"):])
        else:
            QDesktopServices.openUrl(QUrl(target))

    def _ping(self, servers: list[Server] | None = None) -> None:
        servers = list(servers if servers is not None else self.ctl.store.servers)
        self._ping_ids = {s.id for s in servers}
        self.ctl.ping(servers)

    def _on_ping_result(self, sid: str, ms: int) -> None:
        self._ping_ids.discard(sid)
        if self._ping_ids:
            self.list.set_pinging(self._ping_ids)
        if not self._ping_refresh.isActive():
            self._ping_refresh.start()

    # -- servers ---------------------------------------------------------------------------
    def _server_row(self, s: Server) -> Row:
        code, name = flags.split(s.name)
        return Row("server", s.id, gid=s.sub_id or MANUAL, server=s, code=code, name=name, detail=proto_label(s))


    def _groups(self) -> list[tuple[str, str]]:
        """(list group id, title) of the groups configs can be added to."""
        return [(MANUAL, tr("Мои серверы"))] + [(g.id, g.name) for g in self.ctl.store.groups]

    def refresh_servers(self, animate: bool = True) -> None:
        """Subscriptions and groups stay in their order; sorting happens inside each of them,
        by the group's own order if it has one."""
        query = self.search.text().strip().lower()
        store = self.ctl.store
        group_sort = self.ctl.settings.group_sort
        groups = [(s.id, s.title, store.servers_of(s.id), s) for s in store.subscriptions]
        manual = store.servers_of("")
        if manual:
            groups.append((MANUAL, tr("Мои серверы"), manual, None))
        groups += [(g.id, g.name, store.servers_of(g.id), None) for g in store.groups]
        rows: list[Row] = self._balancer_rows(query)
        for gid, title, servers, sub in groups:
            shown = [s for s in servers if query in s.name.lower()] if query else list(servers)
            if query and not shown:
                continue
            mode = group_sort.get(gid, self.ctl.settings.sort_mode)
            if mode == "ping":
                shown.sort(key=lambda s: (s.latency is None or s.latency < 0,
                                          s.latency if s.latency and s.latency > 0 else 0, flags.sort_key(s.name)))
            elif mode == "name":
                shown.sort(key=lambda s: flags.sort_key(s.name))
            rows.append(Row("header", "h:" + gid, gid=gid, title=title, count=len(servers),
                            error=sub.error if sub else "",
                            actions=("ping", "refresh", "share") if sub else ("ping", "add")))
            if sub:
                info = self._sub_info(sub) if not query else None
            elif not servers:
                info = {"announce": tr("Группа пуста. Добавьте в неё конфиги текстом или файлом: кнопкой «+» справа "
                                       "от названия группы, правым кликом по группе или кнопкой ниже."),
                        "links": [(tr("Добавить конфиги"), f"action:add:{gid}")]}
            else:
                info = None
            if info:
                rows.append(Row("info", "i:" + gid, gid=gid, info=info))
            rows += [self._server_row(s) for s in shown]
        self.list.empty_title = tr("Ничего не найдено") if query and store.servers else tr("Серверов пока нет")
        self.list.empty_hint = (tr("Попробуйте другой запрос") if query and store.servers else
                                tr("Нажмите «Добавить» или скопируйте ссылку на подписку и нажмите Ctrl+V"))
        self.list.set_rows(rows, self._collapsed, animate)
        self.list.set_selected(self.ctl.settings.selected_server, self.ctl.state == "connected")
        n = len(store.servers)
        self.count.setText(tr("Серверы") + (f'<span style="color:{theme.FAINT}; font-size:13pt; font-weight:500">'
                                             f'&nbsp;&nbsp;{n}</span>' if n else ""))
        sel = self.ctl.settings.selected_server
        self.chip.set_server(self.ctl.selected, store.balancer(sel) is not None,
                             self.ctl.current_node if self.ctl.state == "connected" else "")
        self._sync_route()

    def _balancer_rows(self, query: str) -> list[Row]:
        """The user's balancers, at the top: they're what you connect to most."""
        store = self.ctl.store
        shown = [b for b in store.balancers if query in b.name.lower()] if query else list(store.balancers)
        if not shown:
            return []
        rows = [Row("header", "h:" + BALANCERS, gid=BALANCERS, title=tr("Балансировщики"), count=len(store.balancers),
                    actions=("ping", "add"))]
        sel, connected = self.ctl.settings.selected_server, self.ctl.state == "connected"
        for b in shown:
            n = len(store.members(b))
            detail = (tr("Авто · {n} {servers}", n=n, servers=plural(n, "сервер", "сервера", "серверов")) if n
                      else tr("Нет серверов"))
            if n and b.mode == "fastest":
                detail += tr("  ·  самый быстрый")
            if connected and b.id == sel and self.ctl.current_node:
                detail += tr("  ·  сейчас {node}", node=flags.split(self.ctl.current_node)[1])
            rows.append(Row("server", b.id, gid=BALANCERS, server=Server(id=b.id, name=b.name, latency=b.latency),
                            badge="bolt", share=False, name=b.name, detail=detail))
        return rows

    @staticmethod
    def _sub_info(sub) -> dict | None:
        """What the provider tells about the subscription: its text, time left, traffic, links."""
        info: dict = {"announce": sub.announce.strip()}
        if sub.expire:
            left = sub.expire - time.time()
            when = i18n.date(sub.expire)
            if left <= 0:
                info["left"] = tr("истекла {when}", when=when)
            elif left < 86400:
                info["left"] = tr("{hours} ч  ·  до {when}", hours=max(1, int(left // 3600)), when=when)
            else:
                info["left"] = tr("{days} дн.  ·  до {when}", days=int(left // 86400), when=when)
        used = sub.upload + sub.download
        if sub.total:
            info["traffic"] = tr("{used} из {total}", used=theme.human_bytes(used), total=theme.human_bytes(sub.total))
            info["frac"] = used / sub.total
        elif used:
            info["traffic"] = tr("{used}  ·  без лимита", used=theme.human_bytes(used))
        links = []
        if sub.web_page_url:
            links.append((tr("Сайт"), sub.web_page_url))
        if sub.support_url and sub.support_url != sub.web_page_url:
            links.append((tr("Поддержка"), sub.support_url))
        info["links"] = links
        return info if any((info["announce"], info.get("left"), info.get("traffic"), links)) else None

    def _context_menu(self, kind: str, ident: str, pos) -> None:
        menu = QMenu(self)
        store = self.ctl.store
        many = ident in self.list.marked and len(self.list.marked) > 1
        if kind == "server" and store.balancer(ident) and not many:
            self._balancer_context(menu, ident)
        elif kind == "server" and many:
            self._marked_menu(menu)
        elif kind == "header" and ident == BALANCERS:
            menu.addAction(icons.icon("plus", theme.TEXT, 16), tr("Создать балансировщик…"), self.edit_balancer)
            menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку"),
                           lambda: self._header_action("ping", BALANCERS))
            menu.addSeparator()
            menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить все балансировщики"),
                           lambda: self._remove_balancers([b.id for b in store.balancers]))
        elif kind == "server":
            srv = store.server(ident)
            menu.addAction(icons.icon("arrow_up", theme.TEXT, 16), tr("Подключиться"),
                           lambda: self.ctl.select(ident, connect=True))
            menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку"), lambda: self._ping([srv]))
            self._fill_share(menu.addMenu(icons.icon("share", theme.TEXT, 16), tr("Поделиться")), "server", ident)
            menu.addAction(icons.icon("check", theme.TEXT, 16), tr("Выделить  (Ctrl+клик)"),
                           lambda: self.list.set_marked(self.list.marked | {ident}))
            self._fill_balancer_menu(menu.addMenu(icons.icon("bolt", theme.TEXT, 16), tr("Добавить в балансировщик")),
                                     [ident])
            if not store.subscription(srv.sub_id):
                move = menu.addMenu(tr("Переместить в группу"))
                for gid, title in self._groups():
                    act = move.addAction(title, lambda g=gid: self.ctl.move_server(ident, self._owner(g)))
                    act.setEnabled(self._owner(gid) != srv.sub_id)
                menu.addSeparator()
                menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить"), lambda: self.ctl.remove_server(ident))
        elif store.subscription(ident):
            sub = store.subscription(ident)
            menu.addAction(icons.icon("refresh", theme.TEXT, 16), tr("Обновить"),
                           lambda: self.ctl.update_subscriptions(sub_ids=[ident]))
            menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку"),
                           lambda: self._ping(store.servers_of(ident)))
            self._fill_sort(menu, ident)
            menu.addAction(tr("Переименовать…"), lambda: self._rename_sub(ident))
            menu.addAction("User-Agent…", lambda: self._sub_ua(ident))
            hw = menu.addAction(tr("Отправлять HWID"))
            hw.setCheckable(True)
            hw.setChecked(sub.send_hwid)
            hw.setToolTip(tr("Включается само, если без HWID подписка не загрузилась. Режим для всех подписок — "
                             "в настройках, вкладка «Подписки»"))
            hw.toggled.connect(lambda on: self.ctl.set_subscription_hwid(ident, on))
            menu.setToolTipsVisible(True)
            self._fill_share(menu.addMenu(icons.icon("share", theme.TEXT, 16), tr("Поделиться")), "header", ident)
            for label, url in ((tr("Сайт"), sub.web_page_url), (tr("Поддержка"), sub.support_url)):
                if url:
                    menu.addAction(icons.icon("link", theme.TEXT, 16), label,
                                   lambda u=url: QDesktopServices.openUrl(QUrl(u)))
            menu.addSeparator()
            menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить подписку"), lambda: self._remove_sub(ident))
        else:
            menu.addAction(icons.icon("plus", theme.TEXT, 16), tr("Добавить конфиги…"), lambda: self.add_configs(ident))
            menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку"),
                           lambda: self._ping(store.servers_of(self._owner(ident))))
            self._fill_sort(menu, ident)
            if store.servers_of(self._owner(ident)):
                self._fill_share(menu.addMenu(icons.icon("share", theme.TEXT, 16), tr("Поделиться")), "header", ident)
            if ident != MANUAL:
                menu.addAction(tr("Переименовать…"), lambda: self._rename_group(ident))
                menu.addSeparator()
                menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить группу"),
                               lambda: self._remove_group(ident))
        menu.exec(pos)

    def _fill_sort(self, menu: QMenu, gid: str) -> None:
        """Sort submenu of one subscription / group: its own order or the common one."""
        s = self.ctl.settings
        current = s.group_sort.get(gid, "")
        sub = menu.addMenu(icons.icon("sort", theme.TEXT, 16), tr("Сортировка"))
        common = {key: text for key, text, _ in SORT_MODES}[s.sort_mode]
        for key, text in [("", tr("Как у всех ({common})", common=common))] + [(k, t) for k, t, _ in SORT_MODES]:
            act = sub.addAction(text, lambda k=key: self._set_group_sort(gid, k))
            act.setCheckable(True)
            act.setChecked(key == current)
            if not key:
                sub.addSeparator()

    def _set_group_sort(self, gid: str, mode: str) -> None:
        s = self.ctl.settings
        if mode:
            s.group_sort[gid] = mode
        else:
            s.group_sort.pop(gid, None)
        s.save()
        self.refresh_servers()

    # -- sharing ---------------------------------------------------------------------------
    def _share_at(self, kind: str, ident: str, pos) -> None:
        menu = QMenu(self)
        self._fill_share(menu, kind, ident)
        menu.exec(pos)

    def _fill_share(self, menu: QMenu, kind: str, ident: str) -> None:
        """Share menu of a server ("server") or of a subscription / group ("header")."""
        ic = lambda name: icons.icon(name, theme.TEXT, 16)  # noqa: E731
        store = self.ctl.store
        if kind == "server":
            menu.addAction(ic("qr"), tr("QR-код"), lambda: self._share_server(ident, "qr"))
            menu.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._share_server(ident, "link"))
            conf = menu.addMenu(ic("code"), tr("Конфигурация"))
            conf.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._share_server(ident, "json"))
            conf.addAction(ic("file"), tr("Файлом…"), lambda: self._share_server(ident, "json-file"))
            return
        sub = store.subscription(ident)
        if sub:
            url = menu.addMenu(ic("link"), tr("Поделиться URL подписки"))
            url.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._copy(sub.url, tr("URL подписки скопирован")))
            url.addAction(ic("qr"), tr("QR-код"), lambda: self._show_qr(
                sub.title, sub.url, tr("Отсканируйте в Happ, v2rayNG, Hiddify или другом клиенте — подписка "
                                       "добавится вместе с обновлениями.")))
        export = menu.addMenu(ic("arrow_up"), tr("Экспортировать"))
        export.setToolTipsVisible(True)
        for act in (export.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._export(ident, False)),
                    export.addAction(ic("file"), tr("В файл…"), lambda: self._export(ident, True))):
            act.setToolTip(tr("Каждый конфиг — ссылкой vless://, hy2:// и т.п., по одной в строке"))

    # -- several servers at once ------------------------------------------------------------
    def _marked(self) -> list[Server]:
        """Marked servers in the order of the list."""
        by_id = {s.id: s for s in self.ctl.store.servers}
        return [by_id[k] for k in self.list.marked_ids() if k in by_id]

    def _marked_balancers(self) -> list[str]:
        """Ids of the marked balancers, in list order."""
        return [k for k in self.list.marked_ids() if self.ctl.store.balancer(k)]

    def _on_marked(self, ids: set) -> None:
        n = len(ids)
        self.sel_label.setText(tr("Выбрано: {n}", n=n))
        self.sel_bar.setVisible(n > 0)
        # Sharing and adding to a balancer are for servers: balancers alone don't get them.
        servers = bool(self._marked())
        self.sel_bal.setVisible(servers)
        self.sel_share.setVisible(servers)

    def _marked_menu(self, menu: QMenu) -> None:
        n = len(self.list.marked)
        servers = self._marked()
        if servers:
            k = len(servers)
            self._fill_share_marked(menu.addMenu(icons.icon("share", theme.TEXT, 16), tr("Поделиться ({k})", k=k)))
            self._fill_balancer_menu(menu.addMenu(icons.icon("bolt", theme.TEXT, 16),
                                                  tr("Добавить в балансировщик ({k})", k=k)), [s.id for s in servers])
        menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку ({n})", n=n),
                       lambda: self._ping(self._marked() + [self.ctl.resolve(i) for i in self._marked_balancers()]))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить ({n})…", n=n), self._remove_marked)
        menu.addAction(icons.icon("close", theme.TEXT, 16), tr("Снять выделение"), lambda: self.list.set_marked(set()))

    def _share_marked_at(self, button: QWidget) -> None:
        menu = QMenu(self)
        self._fill_share_marked(menu)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft() + QPoint(0, 6)))

    def _fill_share_marked(self, menu: QMenu) -> None:
        """The same three ways as for one server: QR code, links, configuration."""
        ic = lambda name: icons.icon(name, theme.TEXT, 16)  # noqa: E731
        menu.addAction(ic("qr"), tr("QR-код"), lambda: self._share_marked("qr"))
        lnk = menu.addMenu(ic("link"), tr("Ссылки"))
        lnk.setToolTipsVisible(True)
        for act in (lnk.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._share_marked("link")),
                    lnk.addAction(ic("file"), tr("В файл…"), lambda: self._share_marked("link-file"))):
            act.setToolTip(tr("Каждый конфиг — ссылкой vless://, hy2:// и т.п., по одной в строке"))
        conf = menu.addMenu(ic("code"), tr("Конфигурация"))
        conf.addAction(ic("copy"), tr("В буфер обмена"), lambda: self._share_marked("json"))
        conf.addAction(ic("file"), tr("В файл…"), lambda: self._share_marked("json-file"))

    def _share_marked(self, how: str) -> None:
        servers = self._marked()
        if not servers:
            return
        if len(servers) == 1 and how != "link-file":
            self._share_server(servers[0].id, how)
            return
        title = tr("Серверы ({n})", n=len(servers))
        if how in ("json", "json-file"):
            text = json.dumps(share.export_json(servers, self.ctl.settings), ensure_ascii=False, indent=2)
            if how == "json":
                self._copy(text, tr("Конфигурации скопированы: {n} (Xray JSON, массивом)", n=len(servers)))
            elif save_text(self, tr("Сохранить конфигурации"), "Nimbus servers", text, "json"):
                self.toaster.show(tr("Сохранено конфигураций: {n}", n=len(servers)))
            return
        text, skipped = share.export_links(servers)
        if not text:
            self.toaster.show(tr("Эти конфиги нельзя записать ссылками — поделитесь ими как конфигурацией"), error=True)
            return
        n = len(text.splitlines())
        tail = tr(", пропущено: {skipped} (только как конфигурация)", skipped=skipped) if skipped else ""
        if how == "qr":
            self._show_qr(title, text, tr("Ссылки по одной в строке. Happ, v2rayNG и Hiddify добавят их все; "
                                          "если клиент взял только одну — поделитесь через буфер обмена."),
                          tr("Ссылок в коде: {n}{tail}.", n=n, tail=tail) if skipped else "")
        elif how == "link-file":
            if save_text(self, tr("Сохранить ссылки"), "Nimbus servers", text + "\n", "txt"):
                self.toaster.show(tr("Сохранено ссылок: {n}{tail}", n=n, tail=tail))
        else:
            self._copy(text + "\n", tr("Скопировано ссылок: {n}{tail}", n=n, tail=tail))

    def _remove_marked(self) -> None:
        servers = self._marked()
        bals = self._marked_balancers()
        if bals and not servers:
            self._remove_balancers(bals)
            return
        store = self.ctl.store
        own = [s for s in servers if not store.subscription(s.sub_id)]
        from_subs = len(servers) - len(own)
        if not own and not bals:
            self.toaster.show(tr("Серверы подписки удаляются только вместе с подпиской: при обновлении они "
                                 "вернутся"), error=True)
            return
        parts = []
        if own:
            parts.append(tr("серверы: {n}", n=len(own)))
        if bals:
            parts.append(tr("балансировщики: {n}", n=len(bals)))
        text = tr("Будут удалены выбранные ") + ", ".join(parts) + "."
        if from_subs:
            text += (tr(" Серверы из подписок ({from_subs}) останутся: при обновлении они вернулись бы, их удаляют "
                        "вместе с подпиской.", from_subs=from_subs))
        if ask(self, tr("Удалить выбранное") if bals else tr("Удалить серверы"), text, tr("Удалить")):
            self.list.set_marked(set())
            if own:
                self.ctl.remove_servers([s.id for s in own])
            if bals:
                self.ctl.remove_balancers(bals)

    def _copy(self, text: str, done: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.toaster.show(done)

    def _show_qr(self, title: str, text: str, hint: str, note: str = "") -> None:
        try:
            QrDialog(self, title, text, hint, note).exec()
        except qr.DataTooLong:
            self.toaster.show(tr("Слишком длинно для QR-кода — поделитесь через буфер обмена"), error=True)

    def _share_server(self, server_id: str, how: str) -> None:
        srv = self.ctl.resolve(server_id)
        if not srv:
            return
        if how in ("json", "json-file"):
            text = json.dumps(share.server_json(srv, self.ctl.settings), ensure_ascii=False, indent=2)
            if how == "json":
                self._copy(text, tr("Конфигурация (Xray JSON) скопирована"))
            elif save_text(self, tr("Сохранить конфигурацию"), srv.name, text, "json"):
                self.toaster.show(tr("Конфигурация сохранена"))
            return
        link = share.server_link(srv)
        if not link:
            self.toaster.show(tr("Этот конфиг нельзя записать ссылкой — поделитесь им как конфигурацией"), error=True)
            return
        n = share.node_count(srv)
        note = (tr("В ссылке основной узел из {n}: ссылка не умеет балансировщик. Весь конфиг с автовыбором — через "
                   "«Конфигурация».", n=n)) if n > 1 else ""
        if how == "qr":
            self._show_qr(srv.name, link, tr("Отсканируйте в Happ, v2rayNG, Hiddify, Streisand или другом клиенте, "
                                             "чтобы добавить этот сервер."), note)
        else:
            self._copy(link, tr("Ссылка скопирована") + (f". {note}" if note else ""))

    def _export(self, gid: str, to_file: bool) -> None:
        store = self.ctl.store
        sub = store.subscription(gid)
        servers = store.servers_of(self._owner(gid))
        title = sub.title if sub else dict(self._groups()).get(gid, tr("Серверы"))
        text, skipped = share.export_links(servers)
        if not text:
            self.toaster.show(tr("Нечего экспортировать"), error=True)
            return
        n = len(text.splitlines())
        tail = tr(", пропущено: {skipped}", skipped=skipped) if skipped else ""
        if not to_file:
            self._copy(text + "\n", tr("Скопировано ссылок: {n}{tail}", n=n, tail=tail))
        elif save_text(self, tr("Экспорт конфигов"), title, text + "\n", "txt"):
            self.toaster.show(tr("Сохранено ссылок: {n}{tail}", n=n, tail=tail))

    def _rename_group(self, gid: str) -> None:
        group = self.ctl.store.group(gid)
        name, ok = get_text(self, tr("Переименовать"), tr("Название группы."), group.name)
        if ok:
            self.ctl.rename_group(gid, name)

    def _remove_group(self, gid: str) -> None:
        group = self.ctl.store.group(gid)
        n = len(self.ctl.store.servers_of(gid))
        text = tr("Группа «{name}» и её конфиги ({n}) будут удалены.",
                  name=group.name, n=n) if n else tr("Группа «{name}» будет удалена.", name=group.name)
        if ask(self, tr("Удалить группу"), text, tr("Удалить")):
            self.ctl.remove_group(gid)

    def _rename_sub(self, sub_id: str) -> None:
        sub = self.ctl.store.subscription(sub_id)
        name, ok = get_text(self, tr("Переименовать"), tr("Название подписки. Пусто — как у провайдера."),
                            sub.custom_name)
        if ok:
            self.ctl.rename_subscription(sub_id, name)

    def _sub_ua(self, sub_id: str) -> None:
        sub = self.ctl.store.subscription(sub_id)
        dlg = UserAgentDialog(self, sub.user_agent, self.ctl.settings.sub_user_agent)
        if dlg.exec():
            self.ctl.set_subscription_ua(sub_id, dlg.picker.value())

    def _remove_sub(self, sub_id: str) -> None:
        sub = self.ctl.store.subscription(sub_id)
        if ask(self, tr("Удалить подписку"), tr("«{title}» и все её серверы будут удалены.", title=sub.title),
               tr("Удалить")):
            self.ctl.remove_subscription(sub_id)

    # -- adding ----------------------------------------------------------------------------
    def _import(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.open_link(text, confirm=False):
            return
        if text.lower().startswith(("http://", "https://")) and "\n" not in text:
            self.ctl.add_subscription(text)
        else:
            n = self.ctl.import_text(text)
            if n:
                self.toaster.show(tr("Добавлено серверов: {n}", n=n))

    def _crypt_failed(self, reason: str) -> None:
        inform(self, tr("Зашифрованная ссылка Happ"), CRYPT_TEXT.format(reason=reason))

    def open_link(self, text: str, confirm: bool = True) -> bool:
        """A deep link (nimbus://import/…, happ://add/…, v2rayn://install-sub?url=… and the like).
        An encrypted Happ link (happ://crypt…, crypt://…) opens to what it carries: a subscription
        or the configs themselves.
        confirm: it came from outside (a browser), so the user sees what gets added first.
        False if `text` isn't a deep link."""
        link = deeplink.parse(text)
        if link is None:
            return False
        if link.kind == "crypt":
            self._crypt_failed(link.payload)
        elif link.kind == "subscription":
            if not confirm:
                self.ctl.add_subscription(link.payload)
                return True
            dlg = AddDialog(self, link.payload)
            if dlg.exec() and dlg.text():
                self._import(dlg.text())
        elif link.kind == "configs":
            if confirm:
                self.add_configs(MANUAL, link.payload)
            else:
                n = self.ctl.import_text(link.payload)
                if n:
                    self.toaster.show(tr("Добавлено серверов: {n}", n=n))
        else:
            self.toaster.show(tr("В ссылке нет адреса подписки или конфигов"), error=True)
        return True

    def add_menu(self, button: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction(icons.icon("globe", theme.TEXT, 16), tr("Подписку…"), self.add_subscription)
        menu.addAction(icons.icon("paste", theme.TEXT, 16), tr("Конфиги…"), lambda: self.add_configs(MANUAL))
        menu.addAction(icons.icon("folder", theme.TEXT, 16), tr("Группу…"), self.add_group)
        menu.addAction(icons.icon("bolt", theme.TEXT, 16), tr("Балансировщик…"), self.edit_balancer)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft() + QPoint(0, 6)))

    def add_subscription(self) -> None:
        dlg = AddDialog(self)
        if dlg.exec():
            self._import(dlg.text())

    def _import_chunks(self, chunks: list[str], gid: str) -> int:
        """Each chunk is configs or, as often happens in a chat, a link that carries them."""
        n = 0
        for chunk in chunks:
            link = deeplink.parse(chunk)
            if link is None:
                n += self.ctl.import_text(chunk, self._owner(gid))
            elif link.kind == "subscription":
                self.ctl.add_subscription(link.payload)
            elif link.kind == "configs":
                n += self.ctl.import_text(link.payload, self._owner(gid))
            elif link.kind == "crypt":
                self._crypt_failed(link.payload)
            else:
                self.toaster.show(tr("В ссылке нет адреса подписки или конфигов"), error=True)
        return n

    def add_configs(self, gid: str = MANUAL, text: str = "") -> None:
        dlg = ConfigsDialog(self, self._groups(), gid, text=text)
        if dlg.exec():
            target = dlg.group_id()
            n = self._import_chunks(dlg.chunks(), target)
            title = dict(self._groups()).get(target, "")
            if n:
                self._collapsed.discard(target)
                self.toaster.show(tr("Добавлено конфигов: {n} → «{title}»", n=n, title=title))

    def add_group(self) -> None:
        dlg = ConfigsDialog(self, self._groups(), new_group=True)
        if not dlg.exec():
            return
        group = self.ctl.add_group(dlg.group_name())
        n = self._import_chunks(dlg.chunks(), group.id)
        QTimer.singleShot(50, lambda: self.list.scroll_to_group(group.id))
        if n:
            self.toaster.show(tr("Группа «{name}» создана, конфигов: {n}", name=group.name, n=n))
        else:
            self.toaster.show(tr("Группа «{name}» создана. Добавьте в неё конфиги: «+» справа от названия группы или "
                                 "правый клик по ней.", name=group.name))

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            self.toaster.show(tr("Буфер обмена пуст"), error=True)
            return
        self._import(text)

    # -- balancers ---------------------------------------------------------------------------
    def _balancer_groups(self) -> list[tuple[str, str, list[Server]]]:
        """(store owner id, title, servers) of everything a balancer can take servers from."""
        store = self.ctl.store
        return ([(s.id, s.title, store.servers_of(s.id)) for s in store.subscriptions]
                + [("", tr("Мои серверы"), store.servers_of(""))]
                + [(g.id, g.name, store.servers_of(g.id)) for g in store.groups])

    def edit_balancer(self, balancer_id: str = "", picked: list[str] | None = None) -> None:
        """Create a balancer (optionally with servers already ticked) or edit an existing one."""
        old = self.ctl.store.balancer(balancer_id)
        dlg = BalancerDialog(self, self.ctl, self._balancer_groups(), old, set(picked or ()))
        if not dlg.exec():
            return
        name = dlg.balancer_name()
        if old:
            name = name or old.name
            self.ctl.save_balancer(Balancer(id=old.id, name=name, server_ids=dlg.server_ids(),
                                            sub_ids=dlg.sub_ids(), interval=dlg.interval.value(),
                                            mode=dlg.balancer_mode()))
            self.toaster.show(tr("Балансировщик «{name}» сохранён", name=name))
            return
        bal = self.ctl.new_balancer(name or tr("Балансировщик {n}", n=len(self.ctl.store.balancers) + 1),
                                    dlg.server_ids(), dlg.sub_ids(), dlg.interval.value(), dlg.balancer_mode())
        self.list.set_marked(set())
        self._collapsed.discard(BALANCERS)
        self.ctl.select(bal.id)
        QTimer.singleShot(50, lambda: self.list.scroll_to_group(BALANCERS))
        self.toaster.show(tr("Балансировщик «{name}» создан. Двойной клик — подключиться", name=bal.name))

    def _balancer_context(self, menu: QMenu, ident: str) -> None:
        menu.addAction(icons.icon("arrow_up", theme.TEXT, 16), tr("Подключиться"),
                       lambda: self.ctl.select(ident, connect=True))
        menu.addAction(icons.icon("pulse", theme.TEXT, 16), tr("Проверить задержку"),
                       lambda: self._ping([s for s in [self.ctl.resolve(ident)] if s]))
        menu.addAction(icons.icon("check", theme.TEXT, 16), tr("Выделить  (Ctrl+клик)"),
                       lambda: self.list.set_marked(self.list.marked | {ident}))
        menu.addAction(icons.icon("gear", theme.TEXT, 16), tr("Изменить…"), lambda: self.edit_balancer(ident))
        menu.addAction(tr("Переименовать…"), lambda: self._rename_balancer(ident))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", theme.TEXT, 16), tr("Удалить"), lambda: self._remove_balancers([ident]))

    def _remove_balancers(self, balancer_ids: list[str]) -> None:
        bals = [b for b in (self.ctl.store.balancer(i) for i in balancer_ids) if b]
        if not bals:
            return
        if len(bals) == 1:
            title, text = tr("Удалить балансировщик"), tr("Балансировщик «{name}» будет удалён.", name=bals[0].name)
        else:
            title, text = tr("Удалить балансировщики"), tr("Будут удалены балансировщики: {n}.", n=len(bals))
        if ask(self, title, text + tr(" Серверы в подписках и группах останутся на своих местах."), tr("Удалить")):
            self.list.set_marked(self.list.marked - {b.id for b in bals})
            self.ctl.remove_balancers([b.id for b in bals])

    def _fill_balancer_menu(self, menu: QMenu, server_ids: list[str]) -> None:
        """Existing balancers to add the servers to, and a new one with them ticked."""
        for b in self.ctl.store.balancers:
            menu.addAction(b.name, lambda bid=b.id: self._add_to_balancer(bid, server_ids))
        if self.ctl.store.balancers:
            menu.addSeparator()
        menu.addAction(icons.icon("plus", theme.TEXT, 16), tr("Новый балансировщик…"),
                       lambda: self.edit_balancer(picked=server_ids))

    def _balancer_menu_at(self, button: QWidget) -> None:
        menu = QMenu(self)
        self._fill_balancer_menu(menu, [s.id for s in self._marked()])
        menu.exec(button.mapToGlobal(button.rect().bottomLeft() + QPoint(0, 6)))

    def _add_to_balancer(self, balancer_id: str, server_ids: list[str]) -> None:
        bal = self.ctl.store.balancer(balancer_id)
        if not bal or not server_ids:
            return
        self.ctl.add_to_balancer(balancer_id, server_ids)
        self.list.set_marked(set())
        n = len(server_ids)
        self.toaster.show(tr("Добавлено в «{name}»: {n} {servers}",
                             name=bal.name, n=n, servers=plural(n, "сервер", "сервера", "серверов")))

    def _rename_balancer(self, balancer_id: str) -> None:
        bal = self.ctl.store.balancer(balancer_id)
        name, ok = get_text(self, tr("Переименовать"), tr("Название балансировщика."), bal.name)
        if ok and name:
            bal.name = name
            self.ctl.store.save()
            self.refresh_servers(animate=False)

    # -- theme -----------------------------------------------------------------------------
    def _set_theme(self, name: str) -> None:
        """Switch the palette under a snapshot of the old window that then fades away."""
        if name == theme.NAME:
            return
        self.ctl.settings.theme = name
        self.ctl.settings.save()
        if getattr(self, "_theme_shot", None) is not None:
            self._theme_shot.deleteLater()
        shot = self._theme_shot = QLabel(self)
        shot.setPixmap(self.grab())
        shot.setGeometry(self.rect())
        shot.setAttribute(Qt.WA_TransparentForMouseEvents)
        fx = QGraphicsOpacityEffect(shot)
        fx.setOpacity(1.0)
        shot.setGraphicsEffect(fx)
        shot.show()
        shot.raise_()
        theme.apply(name)
        self._retheme()
        fade = QPropertyAnimation(fx, b"opacity", shot)
        fade.setDuration(340)
        fade.setEasingCurve(QEasingCurve.InOutQuad)
        fade.setEndValue(0.0)
        fade.finished.connect(self._drop_theme_shot)
        fade.start()

    def _drop_theme_shot(self) -> None:
        if getattr(self, "_theme_shot", None) is not None:
            self._theme_shot.deleteLater()
            self._theme_shot = None

    def _retheme(self) -> None:
        """Bits whose colors are baked into rich text."""
        self._show_speed()
        self.refresh_servers(animate=False)

    # -- dialogs / window ------------------------------------------------------------------
    def show_settings(self, tab: str = "") -> None:
        dlg = SettingsDialog(self.ctl, self, tab)
        if dlg.exec():
            new = dlg.result_settings()
            self.ctl.apply_settings(new)
            self._sync_mode_buttons()
            if i18n.resolve(new.language) != i18n.LANG and ask(
                    self, tr("Язык интерфейса"),
                    tr("Новый язык заработает после перезапуска Nimbus. Перезапустить сейчас? Подключение "
                       "восстановится само."), tr("Перезапустить"), tr("Позже")):
                self.restart_requested.emit()

    def show_logs(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = LogDialog(self.ctl, self)
        self._log_dialog.show()
        self._log_dialog.raise_()

    def showEvent(self, e):
        super().showEvent(e)
        theme.frame(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._drop_theme_shot()  # the snapshot of the old theme no longer matches the window
        self.toaster.relayout()

    def hideEvent(self, e):
        super().hideEvent(e)
        # In the tray Nimbus only needs the core running: give the window's memory back.
        QTimer.singleShot(400, self._release_memory)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and self.isMinimized():
            QTimer.singleShot(400, self._release_memory)

    def _release_memory(self) -> None:
        if self.isVisible() and not self.isMinimized():
            return
        self.list.drop_cache()
        QPixmapCache.clear()
        gc.collect()
        osys.trim_memory()

    def closeEvent(self, event) -> None:
        if self.ctl.settings.minimize_to_tray and not self.really_quit:
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.quit_requested.emit()
