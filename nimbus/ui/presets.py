"""Routing presets: the editor (programs + sites) and the list on the settings page."""
from __future__ import annotations

import copy
import os
import threading
import time

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFileIconProvider, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import apps, i18n
from ..i18n import tr
from ..config_builder import site_entry
from ..store import new_id
from . import icons, theme
from .dialogs import Dialog, ask
from .widgets import Segmented, Spinner, caption

MODE_TEXT = {
    "bypass": tr("Отмеченные программы и сайты работают напрямую, без VPN. Всё остальное идёт через VPN."),
    "vpn": tr("Через VPN идут только отмеченные программы и сайты. Всё остальное работает напрямую."),
}
PROXY_NOTE = (tr("Программы различаются в любом режиме, но в режиме «Системный прокси» через Nimbus проходят только "
                 "те, что используют системный прокси: браузеры, Telegram, Discord и т.п. Для игр включите TUN."))


def plural(n: int, one: str, few: str, many: str) -> str:
    """"5 программ" / "5 programs"."""
    return f"{n} {i18n.plural(n, one, few, many)}"


def decimal(x: float) -> str:
    """One decimal, with the decimal comma in Russian."""
    text = f"{x:.1f}"
    return text.replace(".", ",") if i18n.LANG == "ru" else text


def describe(preset: dict) -> str:
    """"3 программы и 2 сайта" for a preset."""
    n_apps = len(preset.get("apps", []))
    n_sites = sum(1 for line in preset.get("sites", []) if site_entry(line))
    parts = []
    if n_apps:
        parts.append(plural(n_apps, "программа", "программы", "программ"))
    if n_sites:
        parts.append(plural(n_sites, "сайт", "сайта", "сайтов"))
    return tr(" и ").join(parts) or tr("пусто")


class _Scanner(QObject):
    """Runs the program scan off the UI thread; results are cached for the session."""
    found = Signal(list, float)
    icons_ready = Signal()
    cache: list[apps.App] | None = None
    took = 0.0

    def start(self, force: bool = False) -> None:
        if _Scanner.cache is not None and not force:
            self.found.emit(_Scanner.cache, _Scanner.took)
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        t = time.perf_counter()
        result = apps.scan()
        _Scanner.cache, _Scanner.took = result, time.perf_counter() - t
        try:
            self.found.emit(result, _Scanner.took)
            apps.fill_icons(result)
            self.icons_ready.emit()
        except RuntimeError:  # the dialog was closed meanwhile
            pass


class PresetDialog(Dialog):
    def __init__(self, parent, preset: dict | None = None, taken: set[str] | None = None):
        new = preset is None
        self.preset = copy.deepcopy(preset) if preset else {
            "id": new_id(), "name": "", "mode": "bypass", "provider": True, "apps": [], "sites": []}
        super().__init__(parent, tr("Пресет маршрутизации"),
                         tr("Новый пресет") if new else tr("Пресет маршрутизации"), "", 1000)
        self.resize(1000, 680)
        self._taken = taken or set()
        self._icons = QFileIconProvider()
        # chosen programs by path key -> stored entry (dict) or App found by the scan
        self._chosen: dict[str, dict | apps.App] = {self._key(a["path"]): a for a in self.preset["apps"]}
        self._items: dict[str, QListWidgetItem] = {}
        self._icon_queue: list[QListWidgetItem] = []
        self._icon_timer = QTimer(self, interval=0, timeout=self._load_icons)
        self._found: list[apps.App] = []
        self._running: list[apps.App] = []

        top = QHBoxLayout()
        top.setSpacing(12)
        self.name = QLineEdit(self.preset["name"], placeholderText=tr("Название, например «Игры без VPN»"))
        self.name.setFixedHeight(36)
        top.addWidget(self.name, 1)
        self.mode = Segmented([("bypass", tr("В обход VPN"), MODE_TEXT["bypass"]),
                               ("vpn", tr("Только через VPN"), MODE_TEXT["vpn"])],
                              self.preset.get("mode", "bypass"), stretch=False, height=36)
        self.mode.changed.connect(self._sync_mode)
        top.addWidget(self.mode)
        self.lay.addLayout(top)
        self.mode_text = QLabel(objectName="hint")
        self.mode_text.setWordWrap(True)
        self.lay.addWidget(self.mode_text)
        self.provider = QCheckBox(tr("Вместе с правилами провайдера (Умная*)"))
        self.provider.setChecked(self.preset.get("provider", True))
        self.provider.setToolTip(tr("Если в конфиге есть правила маршрутизации от VPN-провайдера, они продолжают "
                                    "работать вместе с пресетом: например, российские сайты тоже открываются без VPN."))
        self.lay.addWidget(self.provider)
        self.lay.addSpacing(6)

        cols = QHBoxLayout()
        cols.setSpacing(22)
        cols.addLayout(self._apps_column(), 3)
        cols.addLayout(self._sites_column(), 2)
        self.lay.addLayout(cols, 1)
        note = QLabel(PROXY_NOTE, objectName="hint")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.TEXT};")
        self.error.hide()
        self.lay.addWidget(self.error)
        self.buttons(tr("Сохранить"))
        self._sync_mode(self.mode.current)

        self.scanner = _Scanner()
        self.scanner.found.connect(self._on_found)
        self.scanner.icons_ready.connect(self._refresh_game_icons)
        self._fill([])
        self.scanner.start()

    # -- layout --------------------------------------------------------------------------
    def _apps_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(caption(tr("Программы")))
        self.view = Segmented([("all", tr("Все"), tr("Установленные программы и игры")),
                               ("running", tr("Запущенные"),
                                tr("Программы, которые работают сейчас; с окном — сверху"))],
                              "all", stretch=False, height=30, pt=8.4)
        self.view.changed.connect(self._view_changed)
        head.addWidget(self.view)
        head.addStretch()
        self.count = QLabel(objectName="hint")
        head.addWidget(self.count)
        col.addLayout(head)
        self.search = QLineEdit(objectName="search", placeholderText=tr("Поиск программы"))
        self.search.addAction(icons.icon("search", theme.MUTED, 16), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        col.addWidget(self.search)
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.setUniformItemSizes(True)
        self.list.itemChanged.connect(self._item_changed)
        self.list.itemClicked.connect(self._item_clicked)
        col.addWidget(self.list, 1)
        status = QHBoxLayout()
        status.setSpacing(8)
        self.spinner = Spinner()
        status.addWidget(self.spinner)
        self.status = QLabel(objectName="hint")
        status.addWidget(self.status, 1)
        col.addLayout(status)
        buttons = QHBoxLayout()
        for text, slot in ((tr("Добавить файл…"), self._add_file), (tr("Добавить папку…"), self._add_folder)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()
        self.rescan = QPushButton(tr("Искать заново"))
        self.rescan.clicked.connect(self._refresh)
        buttons.addWidget(self.rescan)
        col.addLayout(buttons)
        return col

    def _sites_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(caption(tr("Сайты и IP")))
        self.sites = QPlainTextEdit("\n".join(self.preset.get("sites", [])))
        self.sites.setPlaceholderText(tr("Например:") + "\n\nyoutube.com\ndiscord.gg\n*.steampowered.com\n"
                                                        "91.108.4.0/22\ngeosite:twitch\ngeoip:ru")
        self.sites.setFont(theme.font(9.5, mono=True))
        self.sites.textChanged.connect(self._sync_count)
        col.addWidget(self.sites, 1)
        hint = QLabel(tr("По одному в строке. Домен включает все поддомены. Можно IP и подсети, а также готовые "
                         "списки geosite:… и geoip:… (например, geosite:youtube, geoip:ru)."), objectName="hint")
        hint.setWordWrap(True)
        col.addWidget(hint)
        quick = QHBoxLayout()
        quick.setSpacing(8)
        for text, lines in ((tr("+ Российские сайты"), ["geosite:category-ru", "geoip:ru"]),
                            (tr("+ Локальная сеть"), ["geoip:private"])):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, ls=lines: self._add_sites(ls))
            quick.addWidget(b)
        quick.addStretch()
        col.addLayout(quick)
        return col

    # -- programs ------------------------------------------------------------------------
    @staticmethod
    def _key(path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    def _refresh(self) -> None:
        if self.view.current == "running":
            self._load_running()
        else:
            self._start_scan(True)

    def _view_changed(self, view) -> None:
        self.rescan.setText(tr("Обновить") if view == "running" else tr("Искать заново"))
        if view == "running":
            self._load_running()
        elif self._found:
            self._on_found(self._found, _Scanner.took)
        else:
            self._fill([])  # the scan is still running

    def _load_running(self) -> None:
        self._running = apps.running()
        self._fill(self._running)
        self.spinner.hide()
        self.rescan.setEnabled(True)
        windows = sum(1 for a in self._running if a.source != tr("в фоне"))
        self.status.setText(tr("Запущено {programs}, с окном — {windows}. Нет нужной — запустите её и нажмите "
                               "«Обновить».", programs=plural(len(self._running), "программа", "программы", "программ"),
                               windows=windows))

    def _start_scan(self, force: bool) -> None:
        self.rescan.setEnabled(False)
        self.spinner.show()
        self.status.setText(tr("Ищем установленные программы…"))
        self.scanner.start(force)

    def _on_found(self, found: list, took: float) -> None:
        self._found = found
        if self.view.current == "running":
            return
        self._fill(found)
        self.spinner.hide()
        self.rescan.setEnabled(True)
        self.status.setText(tr("Найдено {programs} за {took} с. Нет нужной — добавьте файл или папку.",
                               programs=plural(len(found), "программа", "программы", "программ"),
                               took=decimal(took)))

    def _fill(self, found: list[apps.App]) -> None:
        running = self.view.current == "running"
        if not found and not running:
            self.spinner.show()
            self.status.setText(tr("Ищем установленные программы…"))
            self.rescan.setEnabled(False)
        self.list.blockSignals(True)
        self.list.clear()
        self._items.clear()
        self._icon_queue.clear()
        by_key = {a.key: a for a in found}
        chosen = []
        for key, entry in ({} if running else self._chosen).items():
            app = by_key.get(key)
            if app is None:
                d = entry if isinstance(entry, dict) else entry.as_dict()
                app = apps.App(d.get("name") or os.path.basename(d["path"]), d["path"], d.get("kind", "exe"))
            chosen.append(app)
        rest = found if running else [a for a in found if a.key not in self._chosen]
        for app in sorted(chosen, key=lambda a: a.name.casefold()) + rest:
            self._add_item(app, app.key in self._chosen)
        self.list.blockSignals(False)
        self._filter(self.search.text())
        self._sync_count()
        self._icon_timer.start()

    def _add_item(self, app: apps.App, checked: bool) -> QListWidgetItem:
        label = app.name + (f"   ·   {app.source}" if app.source else "") + (tr("   ·   папка") if app.kind == "dir"
                                                                             and not app.source else "")
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        item.setData(Qt.UserRole, app)
        item.setToolTip(app.path)
        item.setSizeHint(QSize(0, 34))
        self.list.addItem(item)
        self._items[app.key] = item
        self._icon_queue.append(item)
        return item

    def _load_icons(self) -> None:
        """A few icons per event loop turn: the shell is slow to hand out hundreds at once."""
        for _ in range(12):
            if not self._icon_queue:
                self._icon_timer.stop()
                return
            item = self._icon_queue.pop(0)
            app: apps.App = item.data(Qt.UserRole)
            src = app.icon or app.path
            item.setIcon(self._icons.icon(QFileInfo(src)))

    def _refresh_game_icons(self) -> None:
        for item in self._items.values():
            app: apps.App = item.data(Qt.UserRole)
            if app.kind == "dir" and app.icon:
                self._icon_queue.append(item)
        self._icon_timer.start()

    def _item_changed(self, item: QListWidgetItem) -> None:
        app: apps.App = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            if app.source and self.view.current == "running":
                app = apps.App(app.name, app.path)  # the window title is not part of the preset
            self._chosen.setdefault(app.key, app)
        else:
            self._chosen.pop(app.key, None)
        self._sync_count()

    def _item_clicked(self, item: QListWidgetItem) -> None:
        # The whole row toggles, not just the little box.
        pos = self.list.viewport().mapFromGlobal(self.cursor().pos())
        if pos.x() > 34:
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _filter(self, text: str) -> None:
        q = text.strip().casefold()
        for item in self._items.values():
            app: apps.App = item.data(Qt.UserRole)
            item.setHidden(bool(q) and q not in app.name.casefold() and q not in app.path.casefold())

    def _add_picked(self, app: apps.App) -> None:
        item = self._items.get(app.key)
        if item is None:
            self.list.blockSignals(True)
            item = self._add_item(app, True)
            self.list.takeItem(self.list.row(item))
            self.list.insertItem(0, item)
            self.list.blockSignals(False)
            self._icon_timer.start()
        self._chosen[app.key] = app
        item.setCheckState(Qt.Checked)
        item.setHidden(False)
        self.list.scrollToItem(item)
        self.list.setCurrentItem(item)
        self._sync_count()

    def _add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Выберите программу"), os.environ.get("ProgramFiles", ""),
                                                tr("Программы (*.exe);;Все файлы (*)"))
        for path in paths:
            self._add_picked(apps.from_path(path))

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Папка программы или игры — учитываются все её .exe"),
                                                os.environ.get("ProgramFiles", ""))
        if path:
            self._add_picked(apps.from_path(path))

    # -- sites ---------------------------------------------------------------------------
    def _add_sites(self, lines: list[str]) -> None:
        have = self.sites.toPlainText().splitlines()
        add = [x for x in lines if x not in have]
        if add:
            text = self.sites.toPlainText().rstrip("\n")
            self.sites.setPlainText((text + "\n" if text else "") + "\n".join(add))

    def _site_lines(self) -> list[str]:
        return [line.strip() for line in self.sites.toPlainText().splitlines() if line.strip()]

    # -- state ---------------------------------------------------------------------------
    def _sync_mode(self, mode) -> None:
        self.mode_text.setText(MODE_TEXT[mode])
        self.provider.setVisible(mode == "bypass")

    def _sync_count(self) -> None:
        n_apps = len(self._chosen)
        bad = [line for line in self._site_lines() if not site_entry(line)]
        text = tr("выбрано: {n}", n=n_apps)
        self.count.setText(text)
        if bad:
            self.error.setText(tr("Не понял строку сайтов: «{line}». Она будет пропущена.", line=bad[0]))
        self.error.setVisible(bool(bad))

    def accept(self) -> None:
        sites = self._site_lines()
        if not self._chosen and not any(site_entry(s) for s in sites):
            self.error.setText(tr("Отметьте хотя бы одну программу или впишите сайт."))
            self.error.show()
            return
        name = self.name.text().strip() or tr("Мой пресет")
        base, i = name, 2
        while name.casefold() in self._taken:
            name, i = f"{base} {i}", i + 1
        entries = []
        for entry in self._chosen.values():
            entries.append(entry if isinstance(entry, dict) else apps.entry(entry))
        self.preset.update(name=name, mode=self.mode.current, provider=self.provider.isChecked(),
                           apps=sorted(entries, key=lambda a: a["name"].casefold()), sites=sites)
        super().accept()


class PresetsPage(QWidget):
    """Settings tab: the user's presets with create / edit / delete."""

    def __init__(self, presets: list[dict], active: str):
        super().__init__()
        self.presets = copy.deepcopy(presets)
        self.active = active
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 22, 2, 8)
        lay.setSpacing(12)
        intro = QLabel(tr("Свои правила: какие программы и сайты идут мимо VPN или, наоборот, только через него. "
                          "Созданный пресет появляется на главном экране в «Маршрутизации» рядом с «Умная*» и "
                          "«Весь трафик»."), objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        self.list.itemDoubleClicked.connect(lambda _: self._edit())
        self.list.currentRowChanged.connect(self._sync)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton(tr("Создать пресет…"), objectName="primary")
        self.add_btn.clicked.connect(self._add)
        self.edit_btn = QPushButton(tr("Изменить…"))
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn = QPushButton(tr("Удалить"))
        self.del_btn.clicked.connect(self._delete)
        row.addWidget(self.add_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)
        row.addStretch()
        lay.addLayout(row)
        self.empty = QLabel(tr("Пресетов пока нет."), objectName="hint")
        self._render()

    def _render(self, select: int = 0) -> None:
        self.list.clear()
        for p in self.presets:
            how = tr("в обход VPN") if p.get("mode", "bypass") == "bypass" else tr("только через VPN")
            item = QListWidgetItem(icons.icon("route", theme.TEXT_2, 18), f"{p['name']}   ·   {describe(p)} {how}")
            item.setSizeHint(QSize(0, 38))
            self.list.addItem(item)
        if self.presets:
            self.list.setCurrentRow(min(select, len(self.presets) - 1))
        self._sync()

    def _sync(self, *_):
        has = self.list.currentRow() >= 0 and bool(self.presets)
        self.edit_btn.setEnabled(has)
        self.del_btn.setEnabled(has)

    def _taken(self, skip: str = "") -> set[str]:
        return {p["name"].casefold() for p in self.presets if p["id"] != skip}

    def _add(self) -> None:
        dlg = PresetDialog(self, taken=self._taken())
        if dlg.exec():
            self.presets.append(dlg.preset)
            self._render(len(self.presets) - 1)

    def _edit(self) -> None:
        i = self.list.currentRow()
        if i < 0 or i >= len(self.presets):
            return
        dlg = PresetDialog(self, self.presets[i], self._taken(self.presets[i]["id"]))
        if dlg.exec():
            self.presets[i] = dlg.preset
            self._render(i)

    def _delete(self) -> None:
        i = self.list.currentRow()
        if i < 0 or i >= len(self.presets):
            return
        if ask(self, tr("Удалить пресет"), tr("Пресет «{name}» будет удалён.", name=self.presets[i]["name"]),
               tr("Удалить")):
            removed = self.presets.pop(i)
            if removed["id"] == self.active:
                self.active = ""
            self._render(i)
