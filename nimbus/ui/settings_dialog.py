"""Settings dialog."""
from __future__ import annotations

from dataclasses import fields, replace

from PySide6.QtCore import QProcess, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import paths, subscription, winsys
from ..settings import Settings
from . import theme
from .dialogs import UserAgentPicker
from .presets import PresetsPage


def _hint(text: str) -> QLabel:
    lbl = QLabel(text, objectName="muted")
    lbl.setWordWrap(True)
    return lbl


class SettingsDialog(QDialog):
    def __init__(self, ctl, parent=None, tab: str = ""):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("Настройки")
        self.resize(900, 620)
        self._w: dict[str, QWidget] = {}
        s = ctl.settings

        tabs = QTabWidget()
        tabs.addTab(self._page([
            ("tunnel_mode", "Режим", self._combo(s.tunnel_mode, [
                ("proxy", "Системный прокси"), ("tun", "TUN — весь трафик (нужен администратор)")])),
            ("kill_switch", None, self._check(s.kill_switch, "Kill switch")),
            (None, None, _hint("TUN: strict route — блокирует DNS мимо туннеля и IPv6, если туннель "
                               "его не несёт (Windows Filtering Platform). "
                               "Прокси: при падении ядра прокси остаётся включённым, и трафик не уходит "
                               "напрямую.")),
            ("proxy_env", None, self._check(s.proxy_env, "Прокси для консольных программ (HTTP_PROXY / HTTPS_PROXY)")),
            (None, None, _hint("Режим прокси: Claude Code, git, curl, npm и другие программы, которые не "
                               "видят системный прокси Windows, тоже пойдут через VPN. Действует на программы, "
                               "запущенные после подключения; при отключении переменные убираются.")),
            ("socks_port", "SOCKS-порт", self._spin(s.socks_port, 1, 65535)),
            ("http_port", "HTTP-порт", self._spin(s.http_port, 1, 65535)),
            ("allow_lan", None, self._check(s.allow_lan, "Разрешить подключения из локальной сети")),
            ("tun_mtu", "MTU TUN", self._spin(s.tun_mtu, 1280, 9000)),
        ]), "Подключение")
        tabs.addTab(self._page([
            ("use_provider_routing", None, self._check(
                s.use_provider_routing, "Умная* — правила маршрутизации из подписки")),
            (None, None, _hint("* Правила задаёт ваш VPN-провайдер в конфиге: например, российские сайты "
                               "открываются без VPN, поэтому пинг до них такой же, как без VPN. Nimbus их только "
                               "применяет. Выключено (режим «Весь трафик»): вместо них работают правила ниже. "
                               "Балансировщик провайдера сохраняется в любом случае.")),
            ("routing_mode", "Без правил провайдера", self._combo(s.routing_mode, [
                ("global", "Весь трафик через VPN"), ("bypass_ru", "Российские сайты напрямую")])),
            ("block_ads", None, self._check(s.block_ads, "Блокировать рекламу (geosite:category-ads-all)")),
            ("bypass_private", None, self._check(s.bypass_private, "Локальные сети напрямую")),
            ("domain_strategy", "Domain strategy", self._combo(s.domain_strategy, [
                ("AsIs", "AsIs"), ("IPIfNonMatch", "IPIfNonMatch"), ("IPOnDemand", "IPOnDemand")])),
            (None, None, self._button("Обновить geoip/geosite (Loyalsoldier)", self.ctl.update_geo)),
        ]), "Маршруты")
        self.presets = PresetsPage(s.route_presets, s.route_preset)
        tabs.addTab(self.presets, "Пресеты")
        tabs.addTab(self._page([
            ("remote_dns", "Удалённый DNS", self._line(s.remote_dns)),
            ("direct_dns", "Прямой DNS", self._line(s.direct_dns)),
            ("fake_dns", None, self._check(s.fake_dns, "FakeDNS (только TUN)")),
            (None, None, _hint("Удалённый DNS идёт через туннель. Прямой используется для российских "
                               "доменов в режиме обхода. Форматы: 1.1.1.1, https://1.1.1.1/dns-query, "
                               "tcp://8.8.8.8, quic+local://dns.adguard.com")),
        ]), "DNS")
        tabs.addTab(self._page([
            ("sniffing", None, self._check(s.sniffing, "Sniffing (определять домен по трафику; в TUN включён всегда)")),
            ("mux", None, self._check(s.mux, "Mux (не используется с XTLS Vision)")),
            ("mux_concurrency", "Mux-потоков", self._spin(s.mux_concurrency, 1, 1024)),
            ("fragment", None, self._check(s.fragment, "Фрагментация TLS ClientHello")),
            ("fragment_packets", "Пакеты", self._line(s.fragment_packets)),
            ("fragment_length", "Длина", self._line(s.fragment_length)),
            ("fragment_interval", "Интервал, мс", self._line(s.fragment_interval)),
            (None, None, _hint("Mux и фрагментация применяются к серверам из ссылок; конфиги провайдера "
                               "не изменяются.")),
            ("log_level", "Уровень логов", self._combo(s.log_level, [
                (x, x) for x in ("none", "error", "warning", "info", "debug")])),
        ]), "Дополнительно")
        tabs.addTab(self._page([
            ("sub_user_agent", "User-Agent", UserAgentPicker(s.sub_user_agent)),
            (None, None, _hint("Панели (Remnawave, Marzban) выбирают формат подписки по User-Agent. "
                               "С Happ или v2rayN приходят полные Xray-конфиги с балансировщиком. "
                               "Для отдельной подписки его можно сменить правой кнопкой по ней.")),
            ("hwid_mode", "Отправлять HWID", self._combo(s.hwid_mode, [
                ("auto", "Автоматически — только если без него подписка не загружается"),
                ("always", "Всегда"), ("never", "Никогда")])),
            (None, "HWID", self._hwid_row(s.hwid_custom)),
            ("hwid_device", "Имя устройства", self._line(s.hwid_device)),
            (None, None, _hint("HWID — идентификатор устройства для панелей с лимитом устройств (Remnawave и др.). "
                               "Пустое поле — HWID этого компьютера; свой можно вписать или сгенерировать, "
                               "например чтобы перенести устройство с другого клиента. «Автоматически»: для "
                               "каждой подписки решается отдельно и запоминается; переключить вручную — правый "
                               "клик по подписке → «Отправлять HWID».")),
            ("sub_auto_update", None, self._check(s.sub_auto_update, "Автообновление подписок")),
            ("sub_update_hours", "Интервал, ч", self._spin(s.sub_update_hours, 1, 168)),
            ("update_on_launch", None, self._check(s.update_on_launch, "Обновлять при запуске")),
            ("ping_url", "URL для пинга", self._line(s.ping_url)),
            ("ping_timeout", "Таймаут пинга, с", self._spin(s.ping_timeout, 1, 30)),
        ]), "Подписки")
        tabs.addTab(self._page([
            ("autostart", None, self._check(s.autostart, "Запускать вместе с Windows")),
            ("start_minimized", None, self._check(s.start_minimized, "Запускать свёрнутым в трей")),
            ("auto_connect", None, self._check(s.auto_connect, "Подключаться при запуске")),
            ("minimize_to_tray", None, self._check(s.minimize_to_tray, "Закрытие окна сворачивает в трей")),
            ("balancer_notify", None, self._check(s.balancer_notify, "Сообщать, когда балансировщик меняет сервер")),
            (None, None, _hint(f"{paths.APP_NAME} {paths.VERSION} · "
                               f"{'portable' if paths.PORTABLE else 'установлен' if paths.UNINSTALLER else 'без установки'}"
                               f" · ядро Xray-core · шрифт Montserrat · "
                               f"{'администратор' if winsys.is_admin() else 'обычные права'}")),
            (None, None, self._app_buttons()),
        ]), "Приложение")

        if tab == "presets":
            tabs.setCurrentWidget(self.presets)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(14)
        head = QLabel("Настройки")
        head.setFont(theme.font(16, QFont.DemiBold))
        lay.addWidget(head)
        lay.addWidget(tabs, 1)
        lay.addWidget(buttons)

    # -- widget helpers ------------------------------------------------------------------
    def _page(self, rows) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(2, 22, 2, 8)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(24)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for key, label, widget in rows:
            if key:
                self._w[key] = widget
            if label:
                form.addRow(label, widget)
            else:
                form.addRow(widget)
        return page

    def _app_buttons(self) -> QWidget:
        """Data folder; for a copy set up by the installer, also its uninstaller."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self._button("Открыть папку с данными", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.DATA_DIR)))))
        if paths.UNINSTALLER:
            remove = self._button("Удалить Nimbus…", self._uninstall)
            remove.setToolTip("Запустить деинсталлятор. Он спросит подтверждение, закроет Nimbus "
                              "и предложит оставить или удалить настройки и подписки")
            h.addWidget(remove)
        h.addStretch()
        return row

    def _uninstall(self) -> None:
        # The uninstaller asks for confirmation itself, then closes this copy with --quit.
        if QProcess.startDetached(str(paths.UNINSTALLER), [], str(paths.APP_DIR))[0]:
            self.reject()

    def _hwid_row(self, value: str) -> QWidget:
        line = QLineEdit(value)
        line.setPlaceholderText(subscription.auto_hwid() + "  (этого компьютера)")
        self._w["hwid_custom"] = line
        new = self._button("Новый", lambda: line.setText(subscription.random_hwid()))
        new.setToolTip("Сгенерировать случайный HWID")
        auto = self._button("Сбросить", lambda: line.clear())
        auto.setToolTip("Вернуть HWID этого компьютера")
        copy = self._button("Копировать", lambda: QGuiApplication.clipboard().setText(
            line.text().strip() or subscription.auto_hwid()))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(line, 1)
        for b in (new, auto, copy):
            h.addWidget(b)
        return row

    @staticmethod
    def _check(value: bool, text: str) -> QCheckBox:
        w = QCheckBox(text)
        w.setChecked(value)
        return w

    @staticmethod
    def _spin(value: int, lo: int, hi: int) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(value)
        return w

    @staticmethod
    def _line(value: str) -> QLineEdit:
        return QLineEdit(value)

    @staticmethod
    def _combo(value: str, options: list[tuple[str, str]]) -> QComboBox:
        w = QComboBox()
        for key, text in options:
            w.addItem(text, key)
        w.setCurrentIndex(max(0, w.findData(value)))
        return w

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    def showEvent(self, e):
        super().showEvent(e)
        theme.frame(self)

    def result_settings(self) -> Settings:
        values = {}
        for f in fields(Settings):
            w = self._w.get(f.name)
            if isinstance(w, QCheckBox):
                values[f.name] = w.isChecked()
            elif isinstance(w, QSpinBox):
                values[f.name] = w.value()
            elif isinstance(w, QComboBox):
                values[f.name] = w.currentData()
            elif isinstance(w, UserAgentPicker):
                values[f.name] = w.value() or Settings.sub_user_agent
            elif isinstance(w, QLineEdit):
                values[f.name] = w.text().strip()
        values["route_presets"] = self.presets.presets
        values["route_preset"] = self.presets.active
        return replace(self.ctl.settings, **values)
