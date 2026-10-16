"""Server list, painted by hand for the motion a QTreeWidget can't do: the selection slides
between rows, groups fold smoothly, rows fade in, hover fades, wheel scrolling is eased.

Rows are rendered once into cached pixmaps (text with emoji and flags is the expensive part);
a frame only blits them and draws the few live bits: hover, latency, icons."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QToolTip

from ..store import Server
from . import flags, icons, theme

HEADER_H = 48
ROW_H = 58
GROUP_GAP = 10
PAD = 16          # inside the subscription card
ICON = 30         # hit size of row icons
BALANCERS = "__balancers__"   # list group of the user's balancers


@dataclass
class Row:
    kind: str                      # "header" | "info" | "server"
    key: str
    gid: str = ""
    title: str = ""                # header
    count: int = 0
    error: str = ""
    actions: tuple = ("ping",)     # header icons, right to left: "ping", "refresh", "add", "share"
    server: Server | None = None   # server
    code: str | None = None
    badge: str = ""                # icon instead of the flag (a balancer)
    share: bool = True             # the row has a share button (balancers don't)
    name: str = ""
    detail: str = ""
    info: dict = field(default_factory=dict)  # info: announce, left, traffic, frac, links


class _Float:
    """Animated float owned by the list (repaints the viewport, re-lays out on change)."""

    def __init__(self, owner: "ServerList", value: float, ms: int, curve=QEasingCurve.OutCubic):
        self.v = value
        self.a = QVariantAnimation(owner)
        self.a.setDuration(ms)
        self.a.setEasingCurve(curve)
        self.a.valueChanged.connect(lambda x: (setattr(self, "v", float(x)), owner._changed()))

    def to(self, target: float) -> None:
        self.a.stop()
        self.a.setStartValue(self.v)
        self.a.setEndValue(float(target))
        self.a.start()

    def jump(self, value: float) -> None:
        self.a.stop()
        self.v = value

    @property
    def running(self) -> bool:
        return self.a.state() == QVariantAnimation.Running


class ServerList(QAbstractScrollArea):
    selected = Signal(str)
    activated = Signal(str)
    context = Signal(str, str, object)      # kind, id, global pos
    toggled = Signal(str, bool)             # group id, collapsed
    ping_requested = Signal(str)            # server id
    header_action = Signal(str, str)        # action ("ping" | "refresh" | "add"), group id
    link_clicked = Signal(str)              # URL, or "action:<name>:<group id>" from a chip
    share_requested = Signal(str, str, object)  # "server" | "header", id, global pos for the menu
    marked_changed = Signal(object)         # set of server ids picked with Ctrl / Shift + click
    delete_requested = Signal()             # Delete key while servers are marked

    def __init__(self):
        super().__init__()
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QAbstractScrollArea { background: transparent; }")
        self.rows: list[Row] = []
        self.selected_id = ""
        self.marked: set[str] = set()       # multi-selection, apart from the server to connect to
        self._anchor = ""                   # where a Shift + click range starts
        self._press_marked = False          # the last click on a server changed the selection
        self.connected = False
        self.busy = False
        self.empty_title = "Серверов пока нет"
        self.empty_hint = "Нажмите «Добавить» или скопируйте ссылку на подписку и нажмите Ctrl+V"
        self._expand: dict[str, _Float] = {}
        self._sel = _Float(self, 1.0, 360)
        self._sel_from: float | None = None
        self._appear = _Float(self, 1.0, 700, QEasingCurve.Linear)
        self._scroll = QVariantAnimation(self)
        self._scroll.setDuration(260)
        self._scroll.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll.valueChanged.connect(lambda v: self.verticalScrollBar().setValue(int(v)))
        self._scroll_target = 0.0
        self._hover_key = ""
        self._hover_hit = ""                # "ping" | "refresh" | "add" | "link:<i>" under the mouse
        self._hover: dict[str, float] = {}
        self._hover_timer = QTimer(self, interval=16, timeout=self._step_hover)
        self.pinging: set[str] = set()
        self._ping_timer = QTimer(self, interval=50, timeout=self.viewport().update)
        self._cache: dict[tuple, QPixmap] = {}
        self._cache_gen: tuple = ()
        self._lay: list[tuple[Row, float, float, float]] | None = None
        self._info_h: dict[tuple, float] = {}
        self._f_name = theme.font(10, QFont.Medium)
        self._f_name_sel = theme.font(10, QFont.DemiBold)
        self._f_detail = theme.font(8, QFont.Normal)
        self._f_head = theme.font(7.6, QFont.DemiBold, spacing=1.3)
        self._f_ms = theme.font(10, QFont.DemiBold, tabular=True)
        self._f_unit = theme.font(7.6, QFont.Medium)
        self._f_empty = theme.font(13, QFont.DemiBold)
        self._f_hint = theme.font(9)
        self._f_ann = theme.font(9)
        self._f_cap = theme.font(6.8, QFont.DemiBold, spacing=1.2)
        self._f_val = theme.font(9.2, QFont.DemiBold, tabular=True)
        self._f_chip = theme.font(8.6, QFont.DemiBold)

    # -- data ------------------------------------------------------------------------------
    def set_rows(self, rows: list[Row], collapsed: set[str], animate: bool = True) -> None:
        """animate: fade the list in when its rows change (off while ping results re-sort it)."""
        old_keys = [r.key for r in self.rows]
        self.rows = rows
        for r in rows:
            if r.kind == "header" and r.gid not in self._expand:
                self._expand[r.gid] = _Float(self, 0.0 if r.gid in collapsed else 1.0, 300)
        if animate and [r.key for r in rows] != old_keys:
            self._appear.jump(0.0)
            self._appear.to(1.0)
        shown = {r.key for r in rows if r.kind == "server"}
        if self.marked - shown:
            self.set_marked(self.marked & shown)
        self._changed()

    def set_marked(self, ids) -> None:
        ids = set(ids)
        if ids != self.marked:
            self.marked = ids
            self.marked_changed.emit(set(ids))
            self.viewport().update()

    def marked_ids(self) -> list[str]:
        """Marked servers in list order, folded groups included."""
        return [r.key for r in self.rows if r.kind == "server" and r.key in self.marked]

    def _server_keys(self) -> list[str]:
        """Server rows in list order, those of folded groups left out."""
        return [r.key for r, y, h, f in self._layout() if r.kind == "server" and f > 0.5]

    def _mark_click(self, key: str, mods) -> None:
        """Ctrl + click adds or removes one server, Shift + click picks a range, as in Explorer."""
        keys = self._server_keys()
        if mods & Qt.ShiftModifier:
            start = self._anchor or self.selected_id
            if start in keys and key in keys:
                i, j = sorted((keys.index(start), keys.index(key)))
                rng = set(keys[i:j + 1])
                self.set_marked((self.marked | rng) if mods & Qt.ControlModifier else rng)
                return
            self.set_marked(self.marked | {key})
        else:
            marked = set(self.marked)
            if not marked and self.selected_id in keys and self.selected_id != key:
                marked.add(self.selected_id)   # the highlighted server is part of the selection
            marked ^= {key}
            self.set_marked(marked)
        self._anchor = key

    def set_selected(self, server_id: str, connected: bool) -> None:
        self.connected = connected
        if server_id != self.selected_id:
            old = self._row_y(self.selected_id)
            self.selected_id = server_id
            if old is not None and self._row_y(server_id) is not None:
                self._sel_from = old
                self._sel.jump(0.0)
                self._sel.to(1.0)
            else:
                self._sel_from = None
        self.viewport().update()

    def set_pinging(self, ids: set[str]) -> None:
        self.pinging = set(ids)
        self._ping_timer.start() if ids else self._ping_timer.stop()
        self.viewport().update()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.viewport().update()

    def scroll_to_selected(self) -> None:
        y = self._row_y(self.selected_id)
        if y is None:
            return
        vh = self.viewport().height()
        cur = self.verticalScrollBar().value()
        if y < cur or y + ROW_H > cur + vh:
            self._animate_scroll(y - vh / 2 + ROW_H / 2)

    def scroll_to_group(self, gid: str) -> None:
        y = self._row_y("h:" + gid)
        if y is not None:
            self._animate_scroll(y - 8)

    # -- geometry --------------------------------------------------------------------------
    def _width(self) -> int:
        return self.viewport().width()

    def _layout(self) -> list[tuple[Row, float, float, float]]:
        if self._lay is not None:
            return self._lay
        out, y, gf, first = [], 4.0, 1.0, True
        w = self._width()
        for r in self.rows:
            if r.kind == "header":
                if not first:
                    y += GROUP_GAP
                first = False
                gf = self._expand[r.gid].v if r.gid in self._expand else 1.0
                out.append((r, y, HEADER_H, 1.0))
                y += HEADER_H
            else:
                full = self._info_height(r, w) if r.kind == "info" else ROW_H
                h = full * gf
                out.append((r, y, h, gf))
                y += h
        self._lay = out
        return out

    def _info_height(self, r: Row, w: int) -> float:
        k = (r.key, w, r.info.get("announce", ""))
        if k not in self._info_h:
            ann = r.info.get("announce", "")
            h = PAD
            if ann:
                fm = QFontMetricsF(self._f_ann)
                h += fm.boundingRect(QRectF(0, 0, w - 2 - 2 * PAD, 10000), Qt.TextWordWrap, ann).height() + 14
            h += 38 + PAD + 8   # stats line, padding, gap to servers
            self._info_h[k] = h
        return self._info_h[k]

    def _content_height(self) -> float:
        lay = self._layout()
        return (lay[-1][1] + lay[-1][2] + 12) if lay else 0

    def _row_y(self, key: str) -> float | None:
        if not key:
            return None
        for r, y, h, f in self._layout():
            if r.key == key:
                return y if f > 0.01 else None
        return None

    def _changed(self) -> None:
        self._lay = None
        sb = self.verticalScrollBar()
        sb.setPageStep(self.viewport().height())
        sb.setSingleStep(ROW_H)
        sb.setRange(0, max(0, int(self._content_height() - self.viewport().height())))
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._changed()

    def _hit(self, pos) -> tuple[Row | None, str, float]:
        """(row, part, row top in content coords). part: "", "ping", "refresh", "link:<i>"."""
        y = pos.y() + self.verticalScrollBar().value()
        w = self._width()
        for r, ry, h, f in self._layout():
            if ry <= y < ry + h and f > 0.3:
                ly, x = y - ry, pos.x()
                part = ""
                if r.kind == "header":
                    part = next((a for a, rect in self._action_rects(r, w) if rect.contains(x, ly)), "")
                elif r.kind == "server":
                    if self._ping_rect(w).contains(x, ly):
                        part = "ping"
                    elif r.share and self._share_rect(w).contains(x, ly):
                        part = "share"
                elif r.kind == "info":
                    for i, rect in enumerate(self._chip_rects(r, w)):
                        if rect.contains(x, ly):
                            part = f"link:{i}"
                return r, part, ry
        return None, "", 0.0

    @staticmethod
    def _action_rects(r: Row, w: int) -> list[tuple[str, QRectF]]:
        top = (HEADER_H - ICON) / 2 + 3
        return [(a, QRectF(w - (i + 1) * ICON - 6 - i * 2, top, ICON, ICON)) for i, a in enumerate(r.actions)]

    @staticmethod
    def _ping_rect(w: int) -> QRectF:
        return QRectF(w - 134 - ICON + 14, (ROW_H - ICON) / 2, ICON, ICON)

    @classmethod
    def _share_rect(cls, w: int) -> QRectF:
        return cls._ping_rect(w).translated(-ICON - 2, 0)

    def _chip_rects(self, r: Row, w: int) -> list[QRectF]:
        h_total = self._info_height(r, w)
        y = h_total - 8 - PAD - 32
        fm = QFontMetricsF(self._f_chip)
        x = w - 2 - PAD
        out = []
        for label, _ in reversed(r.info.get("links", [])):
            cw = fm.horizontalAdvance(label) + 50
            x -= cw
            out.append(QRectF(x, y, cw, 32))
            x -= 8
        return list(reversed(out))

    # -- interaction -----------------------------------------------------------------------
    def _animate_scroll(self, target: float) -> None:
        sb = self.verticalScrollBar()
        target = max(0.0, min(float(sb.maximum()), target))
        self._scroll_target = target
        self._scroll.stop()
        self._scroll.setStartValue(float(sb.value()))
        self._scroll.setEndValue(target)
        self._scroll.start()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        base = self._scroll_target if self._scroll.state() == QVariantAnimation.Running \
            else self.verticalScrollBar().value()
        self._animate_scroll(base - steps * ROW_H * 1.6)
        e.accept()

    def mouseMoveEvent(self, e):
        r, part, _ = self._hit(e.position())
        key = r.key if r and r.kind != "info" else ""
        if key != self._hover_key or part != self._hover_hit:
            self._hover_key = key
            self._hover_hit = part
            self._hover_timer.start()
            self.viewport().update()
        clickable = r is not None and (r.kind != "info" or part)
        self.viewport().setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)

    def leaveEvent(self, e):
        self._hover_key = ""
        self._hover_hit = ""
        self._hover_timer.start()

    def _step_hover(self) -> None:
        busy = False
        keys = set(self._hover) | ({self._hover_key} if self._hover_key else set())
        for k in keys:
            target = 1.0 if k == self._hover_key else 0.0
            v = self._hover.get(k, 0.0)
            v += (target - v) * 0.3
            if abs(target - v) < 0.03:
                v = target
            else:
                busy = True
            if v == 0.0:
                self._hover.pop(k, None)
            else:
                self._hover[k] = v
        if not busy:
            self._hover_timer.stop()
        self.viewport().update()

    def mousePressEvent(self, e):
        r, part, ry = self._hit(e.position())
        if not r:
            return
        if e.button() == Qt.LeftButton:
            if part == "share":
                w = self._width()
                rect = (dict(self._action_rects(r, w))["share"] if r.kind == "header" else self._share_rect(w))
                at = QPointF(rect.left(), ry - self.verticalScrollBar().value() + rect.bottom() + 4).toPoint()
                self.share_requested.emit(r.kind, r.gid if r.kind == "header" else r.key,
                                          self.viewport().mapToGlobal(at))
            elif r.kind == "header" and part:
                if part == "add" or not self.busy:
                    self.header_action.emit(part, r.gid)
            elif part == "ping":
                if not self.busy:
                    self.ping_requested.emit(r.key)
            elif part.startswith("link:"):
                self.link_clicked.emit(r.info["links"][int(part[5:])][1])
            elif r.kind == "header":
                self._toggle(r.gid)
            elif r.kind == "server":
                mods = e.modifiers()
                # Ctrl + click starts picking servers; while some are picked a plain click adds or
                # removes one, and connecting to a server waits until the selection is cleared.
                self._press_marked = bool(mods & (Qt.ControlModifier | Qt.ShiftModifier) or self.marked)
                if self._press_marked:
                    self._mark_click(r.key, mods)
                else:
                    self.set_marked(set())
                    self._anchor = r.key
                    self.selected.emit(r.key)
        elif e.button() == Qt.RightButton and r.kind != "info":
            self.context.emit(r.kind, r.gid if r.kind == "header" else r.key,
                              self.viewport().mapToGlobal(e.position().toPoint()))

    def mouseDoubleClickEvent(self, e):
        r, part, _ = self._hit(e.position())
        if not r or part or e.button() != Qt.LeftButton:
            return
        if r.kind == "server" and self._press_marked:
            return   # the press already picked or dropped the server; never connect from here
        if r.kind == "server":
            self.activated.emit(r.key)
        elif r.kind == "header":
            self._toggle(r.gid)

    def _toggle(self, gid: str) -> None:
        f = self._expand.get(gid)
        if not f:
            return
        collapse = f.a.endValue() != 0.0 if f.running else f.v > 0.5
        f.to(0.0 if collapse else 1.0)
        self.toggled.emit(gid, collapse)

    def keyPressEvent(self, e):
        keys = self._server_keys()
        if e.matches(QKeySequence.SelectAll) and keys:
            self.set_marked(keys)
        elif e.key() == Qt.Key_Escape and self.marked:
            self.set_marked(set())
        elif e.key() == Qt.Key_Delete and self.marked:
            self.delete_requested.emit()
        elif e.key() in (Qt.Key_Down, Qt.Key_Up) and keys:
            i = keys.index(self.selected_id) if self.selected_id in keys else -1
            i = min(len(keys) - 1, i + 1) if e.key() == Qt.Key_Down else max(0, i - 1)
            self.selected.emit(keys[i])
            QTimer.singleShot(0, self.scroll_to_selected)
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.selected_id in keys:
            self.activated.emit(self.selected_id)
        else:
            super().keyPressEvent(e)

    def viewportEvent(self, e):
        if e.type() == e.Type.ToolTip:
            r, part, _ = self._hit(e.position() if hasattr(e, "position") else e.pos())
            tip = ""
            if r and part == "ping":
                tip = "Проверить задержку серверов группы" if r.kind == "header" else "Проверить задержку"
            elif r and part == "refresh":
                tip = "Обновить подписку"
            elif r and part == "share":
                tip = "Поделиться"
            elif r and part == "add":
                tip = ("Создать балансировщик" if r.gid == BALANCERS
                       else "Добавить конфиги в эту группу — текстом или файлом")
            elif r and part.startswith("link:"):
                target = r.info["links"][int(part[5:])][1]
                tip = "" if target.startswith("action:") else target
            elif r and r.kind == "header" and r.error:
                tip = f"Не удалось обновить: {r.error}"
            elif r and r.kind == "server":
                tip = r.server.name
            QToolTip.showText(e.globalPos(), tip, self.viewport()) if tip else QToolTip.hideText()
            return True
        return super().viewportEvent(e)

    # -- painting --------------------------------------------------------------------------
    CACHE_MAX = 300   # rendered rows kept; a few screens' worth, ~0.2 MB each

    def drop_cache(self) -> None:
        """Forget the rendered rows (they're redrawn on demand), e.g. while the window is hidden."""
        self._cache.clear()

    def _pixmap(self, key: tuple, w: float, h: float, paint) -> QPixmap:
        dpr = self.devicePixelRatioF()
        # Rows rendered for another list width, screen scale or theme will never be shown again:
        # without this, dragging the window edge filled the cache with hundreds of MB of them.
        gen = (self._width(), dpr, theme.NAME)
        if gen != self._cache_gen:
            self._cache.clear()
            self._cache_gen = gen
        k = key + (int(w), int(h))
        pm = self._cache.pop(k, None)
        if pm is not None:
            self._cache[k] = pm   # most recently used goes last
        else:
            pm = QPixmap(max(1, int(math.ceil(w * dpr))), max(1, int(math.ceil(h * dpr))))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.setRenderHint(QPainter.TextAntialiasing)
            paint(q)
            q.end()
            self._cache[k] = pm
            while len(self._cache) > self.CACHE_MAX:
                del self._cache[next(iter(self._cache))]   # least recently used
        return pm

    def paintEvent(self, _):
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        w = self._width()
        vh = self.viewport().height()
        off = self.verticalScrollBar().value()
        lay = self._layout()
        if not lay:
            self._paint_empty(p, w, vh)
            p.end()
            return

        # sliding selection
        target = next(((y, f) for r, y, h, f in lay if r.key == self.selected_id), None)
        if target and target[1] > 0.01:
            ty = target[0]
            y = ty if self._sel_from is None else self._sel_from + (ty - self._sel_from) * self._sel.v
            rect = QRectF(1, y - off + 3, w - 2, ROW_H * target[1] - 6)
            p.setPen(QPen(theme.mix(theme.BORDER_2, theme.BORDER_3, 0.4) if self.connected
                          else QColor(theme.BORDER_2), 1))
            p.setBrush(QColor(theme.SURFACE_2))
            p.drawRoundedRect(rect, 12, 12)

        appear_t = self._appear.v * 0.7
        for index, (r, y, h, f) in enumerate(lay):
            if y + h < off - 2 or y > off + vh + 2 or h < 0.5:
                continue
            a = max(0.0, min(1.0, (appear_t - min(index, 14) * 0.025) / 0.25))
            if a <= 0:
                continue
            p.save()
            p.setOpacity(a * (f if r.kind != "header" else 1.0))
            p.translate(0, y - off + (1 - a) * 8)
            p.setClipRect(QRectF(0, -2, w, h + 4))
            if r.kind == "header":
                self._paint_header(p, r, w)
            elif r.kind == "info":
                self._paint_info(p, r, w)
            else:
                self._paint_server(p, r, w)
            p.restore()
        p.end()

    def _paint_empty(self, p: QPainter, w: int, h: int) -> None:
        cy = h * 0.42
        icons.paint(p, "globe", QRectF(w / 2 - 22, cy - 60, 44, 44), theme.FAINT, 1.2)
        p.setFont(self._f_empty)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, cy, w, 28), Qt.AlignCenter, self.empty_title)
        p.setFont(self._f_hint)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(w * 0.15, cy + 30, w * 0.7, 44), Qt.AlignHCenter | Qt.TextWordWrap, self.empty_hint)

    def _icon_button(self, p: QPainter, rect: QRectF, name: str, hot: bool, visible: float,
                     enabled: bool | None = None) -> None:
        if visible <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * visible)
        if hot:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.PRESSED))
            p.drawRoundedRect(rect, 8, 8)
        enabled = not self.busy if enabled is None else enabled
        color = theme.WHITE if hot else (theme.MUTED if enabled else theme.FAINT)
        icons.paint(p, name, rect.adjusted(7, 7, -7, -7), color, 1.8)
        p.restore()

    def _paint_header(self, p: QPainter, r: Row, w: int) -> None:
        hv = self._hover.get(r.key, 0.0)
        f = self._expand[r.gid].v if r.gid in self._expand else 1.0
        cy = HEADER_H / 2 + 3
        p.save()
        p.translate(18, cy)
        p.rotate(-90 * (1 - f))
        icons.paint(p, "chevron", QRectF(-8, -8, 16, 16), theme.mix(theme.MUTED, theme.TEXT, hv), 1.8)
        p.restore()
        tw = w - 2 * ICON - 60

        def paint(q: QPainter):
            q.setFont(self._f_head)
            fm = QFontMetricsF(self._f_head)
            title = fm.elidedText(r.title.upper(), Qt.ElideRight, tw - 120)
            q.setPen(QColor(theme.TEXT_2))
            q.drawText(QRectF(0, 0, tw, HEADER_H + 6), Qt.AlignVCenter | Qt.AlignLeft, title)
            x = fm.horizontalAdvance(title) + 10
            q.setPen(QColor(theme.FAINT))
            q.drawText(QRectF(x, 0, 60, HEADER_H + 6), Qt.AlignVCenter | Qt.AlignLeft, str(r.count))
            if r.error:
                x += fm.horizontalAdvance(str(r.count)) + 12
                q.setPen(QColor(theme.TEXT))
                q.drawText(QRectF(x, 0, 200, HEADER_H + 6), Qt.AlignVCenter | Qt.AlignLeft, "· НЕ ОБНОВИЛАСЬ")

        p.drawPixmap(QPointF(34, 0), self._pixmap(("h", r.gid, r.title, r.count, r.error), tw, HEADER_H + 6, paint))
        hot = r.key == self._hover_key
        for action, rect in self._action_rects(r, w):
            self._icon_button(p, rect, {"ping": "pulse", "add": "plus"}.get(action, action),
                              hot and self._hover_hit == action, 1,
                              enabled=action in ("add", "share") or not self.busy)

    def _paint_info(self, p: QPainter, r: Row, w: int) -> None:
        h = self._info_height(r, w)
        info = r.info

        def paint(q: QPainter):
            card = QRectF(1.5, 0.5, w - 3, h - 8 - 1)
            q.setPen(QPen(QColor(theme.BORDER), 1))
            q.setBrush(QColor(theme.SURFACE))
            q.drawRoundedRect(card, 12, 12)
            y = PAD
            ann = info.get("announce", "")
            if ann:
                q.setFont(self._f_ann)
                q.setPen(QColor(theme.TEXT_2))
                br = QRectF(PAD + 2, y, w - 2 - 2 * PAD, 10000)
                used = q.boundingRect(br, Qt.TextWordWrap, ann)
                q.drawText(br, Qt.TextWordWrap, ann)
                y += used.height() + 14
            x = PAD + 2
            for cap, val, frac in (("Осталось", info.get("left", ""), None),
                                   ("Трафик", info.get("traffic", ""), info.get("frac"))):
                if not val:
                    continue
                q.setFont(self._f_cap)
                q.setPen(QColor(theme.MUTED))
                q.drawText(QRectF(x, y, 300, 14), Qt.AlignLeft | Qt.AlignVCenter, cap.upper())
                q.setFont(self._f_val)
                q.setPen(QColor(theme.TEXT))
                vw = QFontMetricsF(self._f_val).horizontalAdvance(val)
                q.drawText(QRectF(x, y + 15, vw + 4, 20), Qt.AlignLeft | Qt.AlignVCenter, val)
                colw = vw
                if frac is not None:
                    mw = 120
                    q.setPen(Qt.NoPen)
                    q.setBrush(QColor(theme.BORDER_2))
                    q.drawRoundedRect(QRectF(x + vw + 12, y + 23, mw, 4), 2, 2)
                    q.setBrush(QColor(theme.WHITE))
                    q.drawRoundedRect(QRectF(x + vw + 12, y + 23, max(4.0, mw * min(1.0, frac)), 4), 2, 2)
                    colw += 12 + mw
                x += colw + 34

        p.drawPixmap(QPointF(0, 0), self._pixmap(("i", r.gid, repr(sorted(info.items()))), w, h, paint))
        p.setFont(self._f_chip)
        for i, (rect, (label, target)) in enumerate(zip(self._chip_rects(r, w), info.get("links", []))):
            hot = self._hover_hit == f"link:{i}"
            p.setPen(QPen(QColor(theme.FAINT if hot else theme.BORDER_2), 1))
            p.setBrush(QColor(theme.RAISED if hot else theme.SURFACE_2))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), rect.height() / 2, rect.height() / 2)
            p.setPen(QColor(theme.WHITE if hot else theme.TEXT))
            p.drawText(rect.adjusted(16, 0, -30, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
            icons.paint(p, "plus" if target.startswith("action:") else "link",
                        QRectF(rect.right() - 29, rect.center().y() - 6.5, 13, 13),
                        theme.WHITE if hot else theme.MUTED, 2)

    def _paint_server(self, p: QPainter, r: Row, w: int) -> None:
        sel = r.key == self.selected_id
        marked = r.key in self.marked
        hv = self._hover.get(r.key, 0.0)
        if marked:
            p.setPen(QPen(QColor(theme.BORDER_2), 1))
            p.setBrush(theme.alpha(theme.WHITE, 0.06 + 0.03 * hv))
            p.drawRoundedRect(QRectF(1.5, 3.5, w - 3, ROW_H - 7), 12, 12)
            icons.paint(p, "check", QRectF(3, ROW_H / 2 - 8, 16, 16), theme.WHITE, 2.2)
        elif hv and not sel:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.alpha(theme.SURFACE_2, 0.75 * hv))
            p.drawRoundedRect(QRectF(1, 3, w - 2, ROW_H - 6), 12, 12)
        if sel and not marked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.WHITE))
            p.drawRoundedRect(QRectF(7, ROW_H / 2 - 9, 3, 18), 1.5, 1.5)

        right_w = 134 + 2 * ICON + 20
        sw = w - right_w
        connected = sel and self.connected

        def paint(q: QPainter):
            if r.badge:
                flags.paint_badge(q, QRectF(22, ROW_H / 2 - 8.5, 25, 17), r.badge, 3.5)
            else:
                flags.paint(q, QRectF(22, ROW_H / 2 - 8.5, 25, 17), r.code, 3.5)
            tx = 61
            avail = sw - tx - 8
            q.setFont(self._f_name_sel if sel else self._f_name)
            q.setPen(QColor(theme.WHITE if sel else theme.TEXT))
            fm = QFontMetricsF(q.font())
            q.drawText(QRectF(tx, 9, avail, 22), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(r.name, Qt.ElideRight, avail))
            q.setFont(self._f_detail)
            detail = ("подключено  ·  " + r.detail) if connected else r.detail
            q.setPen(QColor(theme.TEXT_2 if connected else theme.MUTED))
            q.drawText(QRectF(tx, 30, avail, 18), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(self._f_detail).elidedText(detail, Qt.ElideRight, avail))

        p.drawPixmap(QPointF(0, 0), self._pixmap(("s", r.key, r.name, r.detail, r.code, r.badge, sel, connected),
                                                 sw, ROW_H, paint))
        hot = r.key == self._hover_key
        if r.share:
            self._icon_button(p, self._share_rect(w), "share", hot and self._hover_hit == "share", max(hv, 0.0),
                              enabled=True)
        self._icon_button(p, self._ping_rect(w), "pulse", hot and self._hover_hit == "ping",
                          0.0 if r.key in self.pinging else max(hv, 0.0))
        self._paint_latency(p, r.server, QRectF(w - 134 - 6, 0, 134, ROW_H))

    def _paint_latency(self, p: QPainter, s: Server, r: QRectF) -> None:
        bars_x = r.right() - 20
        if s.id in self.pinging:
            t = time.monotonic()
            p.setPen(Qt.NoPen)
            for i in range(3):
                a = 0.2 + 0.8 * max(0.0, math.sin(t * 6 - i * 0.8))
                p.setBrush(theme.alpha(theme.WHITE, a))
                p.drawEllipse(QPointF(r.right() - 26 + i * 8, r.center().y()), 2, 2)
            return
        lat = s.latency
        level = 0
        if lat is None:
            p.setFont(self._f_unit)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(r.x(), 0, bars_x - r.x() - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight, "—")
        elif lat < 0:
            p.setFont(self._f_unit)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(r.x(), 0, bars_x - r.x() - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                       "нет ответа")
        else:
            level = 4 if lat < 150 else 3 if lat < 300 else 2 if lat < 700 else 1
            unit_w = QFontMetricsF(self._f_unit).horizontalAdvance("мс")
            p.setFont(self._f_unit)
            p.setPen(QColor(theme.MUTED))
            ux = bars_x - 10 - unit_w
            p.drawText(QRectF(ux, 0, unit_w, r.height() + 1), Qt.AlignVCenter | Qt.AlignLeft, "мс")
            p.setFont(self._f_ms)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(r.x(), 0, ux - r.x() - 4, r.height()), Qt.AlignVCenter | Qt.AlignRight, str(lat))
        p.setPen(Qt.NoPen)
        for i in range(4):
            bh = 4 + i * 3
            p.setBrush(QColor(theme.TEXT if i < level else theme.BORDER_2))
            p.drawRoundedRect(QRectF(bars_x + i * 5, r.center().y() + 7 - bh, 3, bh), 1, 1)
