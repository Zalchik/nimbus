"""Dialogs: log viewer, "add", User-Agent picker, and small ask/text prompts in the app's style."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor, QCursor, QDesktopServices, QFont, QFontMetricsF, QGuiApplication, QIcon, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit,
    QPushButton, QSpinBox, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import balancer, links, paths, subscription
from ..store import Balancer, Server
from . import flags, icons, theme
from .widgets import IconButton

# Panels pick the subscription format by User-Agent: these get full Xray JSON configs.
UA_PRESETS = [("Happ", "Happ/3.0.0"), ("v2rayN", "v2rayN/7.15.0"), ("INCY", "INCY/3.8.8")]
CUSTOM = "__custom__"
INHERIT = "__inherit__"


class Dialog(QDialog):
    """Base: dark frame, title, hint, consistent margins."""

    def __init__(self, parent, title: str, heading: str = "", hint: str = "", width: int = 520):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, 10)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26, 22, 26, 20)
        self.lay.setSpacing(10)
        if heading:
            h = QLabel(heading)
            h.setFont(theme.font(14, QFont.DemiBold))
            h.setWordWrap(True)
            self.lay.addWidget(h)
        if hint:
            lbl = QLabel(hint, objectName="hint")
            lbl.setWordWrap(True)
            self.lay.addWidget(lbl)

    def showEvent(self, e):
        super().showEvent(e)
        theme.frame(self)
        if not getattr(self, "_sized", False):
            # Word-wrapped labels need the height for this width; top-level windows don't ask for it.
            self._sized = True
            h = self.lay.totalHeightForWidth(self.width()) if self.lay.hasHeightForWidth()                 else self.sizeHint().height()
            self.resize(self.width(), max(self.height(), h))

    def buttons(self, ok: str = "Готово", cancel: str | None = "Отмена") -> None:
        row = QHBoxLayout()
        row.addStretch()
        if cancel:
            c = QPushButton(cancel)
            c.clicked.connect(self.reject)
            row.addWidget(c)
        o = QPushButton(ok, objectName="primary")
        o.setDefault(True)
        o.clicked.connect(self.accept)
        row.addWidget(o)
        self.lay.addSpacing(8)
        self.lay.addLayout(row)


def ask(parent, title: str, text: str, ok: str = "Да", cancel: str = "Отмена") -> bool:
    d = Dialog(parent, title, title, text, 460)
    d.buttons(ok, cancel)
    return bool(d.exec())


def get_text(parent, title: str, label: str, text: str = "") -> tuple[str, bool]:
    d = Dialog(parent, title, title, label, 480)
    edit = QLineEdit(text)
    d.lay.addSpacing(4)
    d.lay.addWidget(edit)
    d.buttons("Сохранить")
    edit.selectAll()
    ok = bool(d.exec())
    return edit.text().strip(), ok


class UserAgentPicker(QWidget):
    """Preset list of client User-Agents plus a field for your own User-Agent."""

    def __init__(self, value: str, inherit_label: str | None = None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.combo = QComboBox()
        if inherit_label is not None:
            self.combo.addItem(inherit_label, INHERIT)
        for name, ua in UA_PRESETS:
            self.combo.addItem(f"{name}  ·  {ua}", ua)
        self.combo.addItem("Свой…", CUSTOM)
        self.edit = QLineEdit(placeholderText="Например, Hiddify/2.5.7")
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.edit, 1)
        i = self.combo.findData(INHERIT if not value and inherit_label is not None else value)
        if i < 0:
            i = self.combo.findData(CUSTOM)
            self.edit.setText(value)
        self.combo.setCurrentIndex(i)
        self.combo.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        custom = self.combo.currentData() == CUSTOM
        self.edit.setVisible(custom)
        if custom:
            self.edit.setFocus()

    def value(self) -> str:
        data = self.combo.currentData()
        if data == INHERIT:
            return ""
        return self.edit.text().strip() if data == CUSTOM else data


class UserAgentDialog(Dialog):
    def __init__(self, parent, current: str, default: str):
        super().__init__(parent, "User-Agent", "User-Agent подписки",
                         "От него зависит формат подписки: с Happ или v2rayN панели (Remnawave, Marzban) "
                         "отдают полные Xray-конфиги с балансировщиком. После сохранения подписка обновится.", 560)
        self.picker = UserAgentPicker(current, f"Как в настройках  ·  {default}")
        self.lay.addSpacing(4)
        self.lay.addWidget(self.picker)
        self.buttons("Сохранить")


class LogDialog(Dialog):
    def __init__(self, ctl, parent=None):
        super().__init__(parent, "Логи Xray", "Логи ядра",
                         "Подробность задаётся в настройках → Дополнительно → Уровень логов. "
                         "Соединения видны на уровне info и debug.", 860)
        self.resize(860, 520)
        self.view = QPlainTextEdit(readOnly=True)
        self.view.setMaximumBlockCount(5000)
        self.view.setFont(theme.font(8.8, mono=True))
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in (
            ("Копировать", lambda: QGuiApplication.clipboard().setText(self.view.toPlainText())),
            ("Очистить", self.view.clear),
            ("Папка с данными", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.DATA_DIR)))),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        close = QPushButton("Закрыть", objectName="primary")
        close.clicked.connect(self.close)
        row.addWidget(close)
        self.lay.addLayout(row)
        for line in ctl.core.tail:
            self.view.appendPlainText(line)
        ctl.log.connect(self.view.appendPlainText)


class AddDialog(Dialog):
    """Subscription URL. Picks up the clipboard if it holds one."""

    def __init__(self, parent=None):
        super().__init__(parent, "Подписка", "Добавить подписку",
                         "Ссылка на подписку от VPN-провайдера (https://…). Серверы, трафик и срок подписки "
                         "подтянутся сами и будут обновляться автоматически.", 560)
        self.edit = QLineEdit(placeholderText="https://…")
        self.edit.setFont(theme.font(9, mono=True))
        self.edit.setMinimumHeight(40)
        clip = QGuiApplication.clipboard().text().strip()
        if clip.lower().startswith(("http://", "https://")) and "\n" not in clip:
            self.edit.setText(clip)
            self.edit.selectAll()
        self.lay.addSpacing(4)
        self.lay.addWidget(self.edit)
        self.buttons("Добавить")

    def text(self) -> str:
        return self.edit.text().strip()


def _read_config_file(path: Path) -> str:
    """Text of a config file. A JSON config without a name gets the file's name."""
    text = path.read_text("utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        return text
    items = data if isinstance(data, list) else [data]
    for i, cfg in enumerate(items, 1):
        if isinstance(cfg, dict) and cfg.get("outbounds") and not cfg.get("remarks"):
            cfg["remarks"] = path.stem if len(items) == 1 else f"{path.stem} {i}"
    return json.dumps(data, ensure_ascii=False)


class ConfigsDialog(Dialog):
    """Configs as text or files, into a chosen group — or a new group with optional configs."""

    def __init__(self, parent, groups: list[tuple[str, str]], group_id: str = "", new_group: bool = False):
        if new_group:
            super().__init__(parent, "Новая группа", "Новая группа",
                             "Группа — ваша папка для конфигов. Дайте ей название и, если хотите, сразу добавьте "
                             "конфиги: текстом или файлом. Позже — кнопкой «+» справа от названия группы "
                             "или правым кликом по ней.", 640)
        else:
            super().__init__(parent, "Конфиги", "Добавить конфиги",
                             "Ссылки vless://, vmess://, trojan://, ss://, hy2://, socks://, wireguard:// — по одной "
                             "на строку — или Xray JSON. Можно загрузить файлы .json / .txt или перетащить их "
                             "в это окно.", 640)
        self.new_group = new_group
        self.files: list[tuple[str, str]] = []   # (file name, text)
        self.setAcceptDrops(True)
        self.resize(640, 520)
        form = QHBoxLayout()
        form.setSpacing(10)
        if new_group:
            self.name = QLineEdit(placeholderText="Название группы, например «Работа»")
            self.name.setMinimumHeight(40)
            form.addWidget(self.name, 1)
        else:
            lbl = QLabel("Группа")
            lbl.setStyleSheet(f"color: {theme.MUTED};")
            self.group = QComboBox()
            for gid, title in groups:
                self.group.addItem(title, gid)
            self.group.setCurrentIndex(max(0, self.group.findData(group_id)))
            form.addWidget(lbl)
            form.addWidget(self.group, 1)
        self.lay.addSpacing(4)
        self.lay.addLayout(form)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText('vless://…\nhy2://…\n\nили {"outbounds": [...]}')
        self.edit.setFont(theme.font(9, mono=True))
        clip = QGuiApplication.clipboard().text().strip()
        first = clip.splitlines()[0] if clip else ""
        if links.is_link(first) or clip[:1] in "[{":
            self.edit.setPlainText(clip)
            self.edit.selectAll()
        self.edit.textChanged.connect(self._update)
        self.lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.setSpacing(10)
        pick = QPushButton("Загрузить файл…")
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        self.status = QLabel()
        self.status.setFont(theme.font(8.8, QFont.Medium))
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.lay.addLayout(row)
        self.buttons("Создать группу" if new_group else "Добавить")
        self.ok = self.findChild(QPushButton, "primary")
        self._update()

    def _pick(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Файлы с конфигами", "",
                                                "Конфиги (*.json *.txt *.conf);;Все файлы (*)")
        self._load([Path(n) for n in names])

    def _load(self, paths_: list[Path]) -> None:
        for path in paths_:
            try:
                if path.stat().st_size > 5_000_000:
                    raise OSError("файл больше 5 МБ")
                self.files.append((path.name, _read_config_file(path)))
            except OSError as e:
                self.files.append((path.name, ""))
                self.status.setToolTip(f"{path.name}: {e}")
        self._update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._load([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    def chunks(self) -> list[str]:
        return [t for t in [self.edit.toPlainText().strip()] + [t for _, t in self.files] if t.strip()]

    def _count(self) -> int:
        return sum(len(subscription.parse_body(c)[0]) for c in self.chunks())

    def _update(self) -> None:
        n = self._count()
        parts = []
        if self.files:
            names = ", ".join(name for name, _ in self.files[:3]) + ("…" if len(self.files) > 3 else "")
            parts.append(f"Файлы: {names}")
        if self.chunks():
            parts.append(f"найдено конфигов: {n}" if n else "конфиги не распознаны")
        self.status.setText(" · ".join(parts).capitalize() if parts else "")
        self.status.setStyleSheet(f"color: {theme.TEXT if n else theme.MUTED};")
        self.ok.setEnabled(self.new_group or n > 0)

    def group_id(self) -> str:
        return self.group.currentData()

    def group_name(self) -> str:
        return self.name.text().strip()


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def flag_icon(code: str | None) -> QIcon:
    """The country flag as the list paints it: Windows draws emoji flags as two letters."""
    pm = QPixmap(48, 34)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    flags.paint(p, QRectF(0, 0, 24, 17), code, 3)
    p.end()
    return QIcon(pm)


COL_ARROW, COL_NAME, COL_PING = 0, 1, 2


def _ms_text(latency: int | None) -> str:
    if latency is None:
        return "—"
    return "нет ответа" if latency < 0 else f"{latency} мс"


def _chevron(expanded: bool) -> QIcon:
    """Down when the group is open, right when it's folded."""
    pm = QPixmap(32, 32)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    if not expanded:
        p.translate(8, 8)
        p.rotate(-90)
        p.translate(-8, -8)
    icons.paint(p, "chevron", QRectF(0, 0, 16, 16), theme.MUTED, 1.8)
    p.end()
    return QIcon(pm)


class _PingButton(QStyledItemDelegate):
    """The latency column drawn as a button: a pill with the pulse icon that lights up under the mouse."""

    def __init__(self, dialog: "BalancerDialog"):
        super().__init__(dialog)
        self.dialog = dialog
        self._font = theme.font(8.6, QFont.Medium, tabular=True)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        text = index.data(Qt.DisplayRole) or ""
        hot = QPersistentModelIndex(index) == self.dialog._hover
        quiet = text.startswith("проверка") or text in ("—", "проверить")
        fm = QFontMetricsF(self._font)
        r = QRectF(option.rect)
        w = min(r.width() - 10, fm.horizontalAdvance(text) + 40)
        pill = QRectF(r.right() - 8 - w, r.center().y() - 12, w, 24)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.FAINT if hot else theme.BORDER_2), 1))
        p.setBrush(QColor(theme.RAISED if hot else theme.SURFACE_2))
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        color = theme.WHITE if hot else (theme.MUTED if quiet else theme.TEXT_2)
        icons.paint(p, "pulse", QRectF(pill.x() + 9, pill.center().y() - 7, 14, 14), color, 1.8)
        p.setFont(self._font)
        p.setPen(QColor(color))
        p.drawText(pill.adjusted(27, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()


class BalancerDialog(Dialog):
    """Name, servers ticked from every subscription and group, how often to check them.
    A group ticked as a whole is kept as a group: its future servers join the balancer too.

    Groups fold (arrow on the left); the column on the right checks latency of a group or of
    one server; press and drag ticks every row the mouse passes."""

    def __init__(self, parent, ctl, groups: list[tuple[str, str, list[Server]]], bal: Balancer | None = None,
                 picked: set[str] | None = None):
        super().__init__(parent, "Балансировщик", "Изменить балансировщик" if bal else "Новый балансировщик",
                         "Отметьте серверы из любых подписок и групп. Nimbus сам проверяет их скорость и ведёт "
                         "трафик через самый быстрый, а если тот перестанет отвечать, переключается на следующий "
                         "без переподключения. Подписка или группа, отмеченная целиком, берётся вместе с "
                         "будущими серверами. Несколько подряд отмечаются протягиванием мыши с зажатой кнопкой.",
                         640)
        self.resize(640, 700)
        self.ctl = ctl
        picked = set(picked or ())
        subs = set(bal.sub_ids) if bal else set()
        ids = set(bal.server_ids) if bal else set()
        self.name = QLineEdit(bal.name if bal else "", placeholderText="Название, например «Европа»")
        self.name.setMinimumHeight(40)
        self.lay.addSpacing(4)
        self.lay.addWidget(self.name)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit(placeholderText="Поиск по серверам")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        self.ping_all = IconButton("pulse", "Проверить задержку всех серверов в списке", text="Проверить все",
                                   size=38)
        self.ping_all.clicked.connect(lambda: self._ping(list(self._servers.values())))
        bar.addWidget(self.ping_all)
        self.lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.setIconSize(QSize(24, 17))
        self.tree.setMinimumHeight(300)
        head_view = self.tree.header()
        head_view.setStretchLastSection(False)
        head_view.setSectionResizeMode(COL_ARROW, QHeaderView.Fixed)
        head_view.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        head_view.setSectionResizeMode(COL_PING, QHeaderView.Fixed)
        head_view.resizeSection(COL_ARROW, 30)
        head_view.resizeSection(COL_PING, 132)
        self._hover = QPersistentModelIndex()    # the latency button under the mouse
        self.tree.setItemDelegateForColumn(COL_PING, _PingButton(self))
        self.tree.setMouseTracking(True)

        self._heads: dict[str, QTreeWidgetItem] = {}
        self._rows: dict[str, list[QTreeWidgetItem]] = {}
        self._items: dict[str, QTreeWidgetItem] = {}     # server id -> its row
        self._servers: dict[str, Server] = {}
        bold = theme.font(9.2, QFont.DemiBold)
        shown = [g for g in groups if g[2]]
        for gid, title, servers in shown:
            head = QTreeWidgetItem(["", f"{title}   ·   {len(servers)}", "проверить"])
            head.setFlags(head.flags() | Qt.ItemIsUserCheckable)
            head.setData(COL_NAME, Qt.UserRole, ("group", gid, title))
            head.setFont(COL_NAME, bold)
            head.setToolTip(COL_ARROW, "Свернуть или развернуть")
            head.setToolTip(COL_PING, f"Проверить задержку серверов «{title}»")
            head.setSizeHint(COL_NAME, QSize(0, 38))
            self.tree.addTopLevelItem(head)
            self._heads[gid] = head
            rows = []
            for s in servers:
                code, name = flags.split(s.name)
                item = QTreeWidgetItem(["", name, _ms_text(s.latency)])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setData(COL_NAME, Qt.UserRole, ("server", s.id, gid, s.name))
                item.setIcon(COL_NAME, flag_icon(code))
                item.setToolTip(COL_NAME, s.name)
                item.setToolTip(COL_PING, "Проверить задержку")
                item.setCheckState(COL_NAME, Qt.Checked if gid in subs or s.id in ids or s.id in picked
                                   else Qt.Unchecked)
                item.setSizeHint(COL_NAME, QSize(0, 32))
                head.addChild(item)
                rows.append(item)
                self._items[s.id] = item
                self._servers[s.id] = s
            self._rows[gid] = rows
            self._sync_head(gid)
            # Open where something is ticked (or when there's only one group): the rest stays out of the way.
            head.setExpanded(len(shown) == 1 or any(r.checkState(COL_NAME) != Qt.Unchecked for r in rows))
            head.setIcon(COL_ARROW, _chevron(head.isExpanded()))
        self.tree.itemChanged.connect(self._changed)
        self.tree.itemExpanded.connect(lambda it: it.setIcon(COL_ARROW, _chevron(True)))
        self.tree.itemCollapsed.connect(lambda it: it.setIcon(COL_ARROW, _chevron(False)))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.viewport().installEventFilter(self)
        self._drag: tuple[str, Qt.CheckState] | None = None   # kind of row it started on, state to set
        self._drag_item: QTreeWidgetItem | None = None
        self._scroll_dir = 0
        self._autoscroll = QTimer(self, interval=30, timeout=self._autoscroll_step)
        self.lay.addWidget(self.tree, 1)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_lbl = QLabel("Режим")
        mode_lbl.setStyleSheet(f"color: {theme.MUTED};")
        self.mode = QComboBox()
        for key, title in balancer.MODES.items():
            self.mode.addItem(title, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(bal.mode if bal else "stable")))
        self.mode.setFixedWidth(190)
        self.mode_hint = QLabel(objectName="hint")
        self.mode_hint.setWordWrap(True)
        self.mode.currentIndexChanged.connect(self._mode_hint)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.mode)
        mode_row.addWidget(self.mode_hint, 1)
        self.lay.addLayout(mode_row)
        self._mode_hint()

        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel("Проверять скорость каждые")
        lbl.setStyleSheet(f"color: {theme.MUTED};")
        self.interval = QSpinBox()
        self.interval.setRange(10, 600)
        self.interval.setSuffix(" с")
        self.interval.setValue(bal.interval if bal else 30)
        self.interval.setFixedWidth(90)
        row.addWidget(lbl)
        row.addWidget(self.interval)
        row.addStretch()
        self.status = QLabel()
        self.status.setFont(theme.font(8.8, QFont.Medium))
        row.addWidget(self.status)
        self.lay.addLayout(row)
        self.buttons("Сохранить" if bal else "Создать")
        self.ok = self.findChild(QPushButton, "primary")
        self._busy = False
        self._pinging: set[str] = set()
        ctl.ping_result.connect(self._on_ping)
        ctl.ping_finished.connect(self._on_finished)
        self._update()

    # -- ticks -----------------------------------------------------------------------------
    def _sync_head(self, gid: str) -> None:
        states = {i.checkState(COL_NAME) for i in self._rows[gid]}
        self._heads[gid].setCheckState(COL_NAME, states.pop() if len(states) == 1 else Qt.PartiallyChecked)

    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._busy or column != COL_NAME:
            return
        self._busy = True
        data = item.data(COL_NAME, Qt.UserRole)
        if data[0] == "group":
            state = item.checkState(COL_NAME)
            if state != Qt.PartiallyChecked:
                for row in self._rows[data[1]]:
                    row.setCheckState(COL_NAME, state)
        else:
            self._sync_head(data[2])
        self._busy = False
        self._update()

    def _set_group(self, gid: str, state: Qt.CheckState) -> None:
        self._heads[gid].setCheckState(COL_NAME, state)

    # -- mouse -----------------------------------------------------------------------------
    def eventFilter(self, obj, e):
        if obj is not self.tree.viewport():
            return super().eventFilter(obj, e)
        t = e.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and e.button() == Qt.LeftButton:
            pos = e.position().toPoint()
            item = self.tree.itemAt(pos)
            if item is None:
                return False
            kind = item.data(COL_NAME, Qt.UserRole)[0]
            column = self.tree.columnAt(pos.x())
            if column == COL_PING:
                self._ping_item(item)
            elif kind == "group" and column == COL_ARROW:
                item.setExpanded(not item.isExpanded())
            else:
                # The whole row toggles, not just the little box; the state it gets goes to the rows
                # dragged over.
                state = Qt.Unchecked if item.checkState(COL_NAME) == Qt.Checked else Qt.Checked
                self._drag = (kind, state)
                self._drag_item = item
                item.setCheckState(COL_NAME, state)
            return True
        if t == QEvent.MouseMove and self._drag:
            pos = e.position().toPoint()
            self._drag_to(pos)
            h = self.tree.viewport().height()
            self._scroll_dir = -1 if pos.y() < 16 else 1 if pos.y() > h - 16 else 0
            self._autoscroll.start() if self._scroll_dir else self._autoscroll.stop()
            return True
        if t == QEvent.MouseButtonRelease and self._drag:
            self._drag = None
            self._autoscroll.stop()
            return True
        if t == QEvent.MouseMove:
            self._track(e.position().toPoint())
        elif t == QEvent.Leave:
            self._track(None)
        return False

    def _track(self, pos: QPoint | None) -> None:
        """Hand cursor and a lit button over what can be clicked: the latency button, a group's arrow."""
        hover, hand = QPersistentModelIndex(), False
        if pos is not None:
            item = self.tree.itemAt(pos)
            column = self.tree.columnAt(pos.x())
            if item is not None and column == COL_PING:
                hover, hand = QPersistentModelIndex(self.tree.indexFromItem(item, COL_PING)), True
            elif item is not None and column == COL_ARROW:
                hand = item.data(COL_NAME, Qt.UserRole)[0] == "group"
        self.tree.viewport().setCursor(Qt.PointingHandCursor if hand else Qt.ArrowCursor)
        if hover != self._hover:
            self._hover = hover
            self.tree.viewport().update()

    def _visible(self) -> list[QTreeWidgetItem]:
        """Rows in the order they're on screen: folded and filtered-out ones left out."""
        out = []
        for gid, head in self._heads.items():
            if head.isHidden():
                continue
            out.append(head)
            if head.isExpanded():
                out += [r for r in self._rows[gid] if not r.isHidden()]
        return out

    def _drag_to(self, pos: QPoint) -> None:
        """Every row between the last one and the one under the mouse: a fast flick skips none."""
        h = self.tree.viewport().height()
        item = self.tree.itemAt(QPoint(40, min(max(pos.y(), 1), h - 2)))
        if item is None or self._drag is None:
            return
        rows = self._visible()
        if item not in rows or self._drag_item not in rows:
            return
        lo, hi = sorted((rows.index(self._drag_item), rows.index(item)))
        kind, state = self._drag
        for it in rows[lo:hi + 1]:
            if it.data(COL_NAME, Qt.UserRole)[0] == kind and it.checkState(COL_NAME) != state:
                it.setCheckState(COL_NAME, state)
        self._drag_item = item

    def _autoscroll_step(self) -> None:
        """Dragging past the top or bottom edge scrolls on, ticking as it goes."""
        if self._drag is None or not QGuiApplication.mouseButtons() & Qt.LeftButton:
            self._drag = None
            self._autoscroll.stop()
            return
        sb = self.tree.verticalScrollBar()
        sb.setValue(sb.value() + self._scroll_dir * 10)
        self._drag_to(self.tree.viewport().mapFromGlobal(QCursor.pos()))

    def _menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        ic = lambda name: icons.icon(name, theme.TEXT, 16)  # noqa: E731
        if item is not None:
            data = item.data(COL_NAME, Qt.UserRole)
            if data[0] == "group":
                gid = data[1]
                menu.addAction(ic("pulse"), "Проверить задержку", lambda: self._ping_item(item))
                menu.addAction(ic("check"), "Отметить все", lambda: self._set_group(gid, Qt.Checked))
                menu.addAction(ic("close"), "Снять все", lambda: self._set_group(gid, Qt.Unchecked))
                menu.addAction("Свернуть" if item.isExpanded() else "Развернуть",
                               lambda: item.setExpanded(not item.isExpanded()))
            else:
                menu.addAction(ic("pulse"), "Проверить задержку", lambda: self._ping_item(item))
                ticked = [self._servers[i] for i in self.server_ids(all_=True)]
                if ticked:
                    menu.addAction(ic("pulse"), f"Проверить отмеченные ({len(ticked)})", lambda: self._ping(ticked))
            menu.addSeparator()
        menu.addAction("Свернуть все", lambda: [h.setExpanded(False) for h in self._heads.values()])
        menu.addAction("Развернуть все", lambda: [h.setExpanded(True) for h in self._heads.values()])
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # -- ping ------------------------------------------------------------------------------
    def _ping_item(self, item: QTreeWidgetItem) -> None:
        data = item.data(COL_NAME, Qt.UserRole)
        if data[0] == "group":
            self._ping([self._servers[r.data(COL_NAME, Qt.UserRole)[1]] for r in self._rows[data[1]]])
        else:
            self._ping([self._servers[data[1]]])

    def _ping(self, servers: list[Server]) -> None:
        servers = [s for s in servers if s.id not in self._pinging]   # those already being checked wait for it
        if not servers:
            return
        self._pinging |= {s.id for s in servers}
        for s in servers:
            self._items[s.id].setText(COL_PING, "проверка…")
        self.ctl.ping(servers)

    def _on_ping(self, sid: str, ms: int) -> None:
        item = self._items.get(sid)
        if item is not None:
            self._pinging.discard(sid)
            item.setText(COL_PING, _ms_text(ms))

    def _on_finished(self, ids: set) -> None:
        for sid in ids & self._pinging:   # the run ended without a word on them
            self._items[sid].setText(COL_PING, _ms_text(self._servers[sid].latency))
        self._pinging -= ids

    def done(self, result: int) -> None:
        for signal, slot in ((self.ctl.ping_result, self._on_ping), (self.ctl.ping_finished, self._on_finished)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    # -- search, results -------------------------------------------------------------------
    def _filter(self, text: str) -> None:
        q = text.strip().casefold()
        for gid, rows in self._rows.items():
            shown = 0
            for row in rows:
                hide = bool(q) and q not in row.data(COL_NAME, Qt.UserRole)[3].casefold()
                row.setHidden(hide)
                shown += not hide
            head = self._heads[gid]
            head.setHidden(not shown)
            if q and shown:
                head.setExpanded(True)

    def _update(self) -> None:
        n = len(self.server_ids(all_=True))
        self.status.setText(f"Выбрано: {n} {plural(n, 'сервер', 'сервера', 'серверов')}" if n
                            else "Серверы не выбраны")
        self.status.setStyleSheet(f"color: {theme.TEXT if n else theme.MUTED};")
        self.ok.setEnabled(n > 0)

    def sub_ids(self) -> list[str]:
        return [gid for gid, head in self._heads.items() if head.checkState(COL_NAME) == Qt.Checked]

    def server_ids(self, all_: bool = False) -> list[str]:
        """Servers ticked one by one (all_: every ticked server, whole groups included)."""
        whole = set() if all_ else set(self.sub_ids())
        return [row.data(COL_NAME, Qt.UserRole)[1] for gid, rows in self._rows.items() if gid not in whole
                for row in rows if row.checkState(COL_NAME) == Qt.Checked]

    def _mode_hint(self) -> None:
        if self.mode.currentData() == "stable":
            text = (f"Держится за сервер, пока он отвечает. Переходит на другой, только если тот быстрее "
                    f"хотя бы на {balancer.MIN_GAIN_MS} мс и на {int(balancer.MIN_GAIN_RATIO * 100)}%: "
                    f"IP меняется редко, сайты не разлогинивают.")
        else:
            text = "Всегда самый быстрый сервер. IP может меняться чаще: банки и игры иногда просят войти заново."
        self.mode_hint.setText(text)

    def balancer_mode(self) -> str:
        return self.mode.currentData()

    def balancer_name(self) -> str:
        return self.name.text().strip()
