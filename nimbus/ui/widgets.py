"""Painted widgets with motion: connect button, segmented switch, icon buttons, speed graph,
toasts. Animations are short and eased; nothing keeps a timer running while idle."""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QGraphicsOpacityEffect, QLabel, QSizePolicy, QWidget

from . import icons, theme


class Anim(QVariantAnimation):
    """A float 0..1 (or any range) driver that repaints its widget."""

    def __init__(self, widget: QWidget, ms: int = 220, curve=QEasingCurve.OutCubic, value: float = 0.0):
        super().__init__(widget)
        self.setDuration(ms)
        self.setEasingCurve(curve)
        self._v = value
        self.valueChanged.connect(self._set)
        self._w = widget

    def _set(self, v) -> None:
        self._v = float(v)
        self._w.update()

    @property
    def v(self) -> float:
        return self._v

    def to(self, target: float, ms: int | None = None) -> None:
        if abs(target - self._v) < 1e-4 and self.state() != QVariantAnimation.Running:
            return
        self.stop()
        if ms is not None:
            self.setDuration(ms)
        self.setStartValue(self._v)
        self.setEndValue(float(target))
        self.start()

    def jump(self, value: float) -> None:
        self.stop()
        self._set(value)


# -- connect button -------------------------------------------------------------------------
class PowerButton(QAbstractButton):
    """Ring that fills white when connected. While connecting, an arc chases around it; on
    success one ring ripples outwards. Takes `size` when there's room and shrinks down to
    `min_size` in a short window instead of sliding under the text below it."""

    def __init__(self, size: int = 176, min_size: int = 112):
        super().__init__()
        self._size = size
        self.setMinimumSize(size, min_size)
        self.setMaximumSize(size, size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.setCursor(Qt.PointingHandCursor)
        self.state = "disconnected"
        self._on = Anim(self, 520)
        self._hover = Anim(self, 160)
        self._press = Anim(self, 120)
        self._ripple = Anim(self, 1100, QEasingCurve.OutQuad, 1.0)
        self._t0 = time.monotonic()
        self._spin = QTimer(self, interval=16, timeout=self.update)

    def set_state(self, state: str) -> None:
        was = self.state
        self.state = state
        busy = state in ("connecting", "disconnecting")
        self._spin.start() if busy else self._spin.stop()
        self._on.to(1.0 if state == "connected" else 0.0)
        if state == "connected" and was != "connected":
            self._ripple.jump(0.0)
            self._ripple.to(1.0)
        self.update()

    def enterEvent(self, e):
        self._hover.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._press.to(1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press.to(0)
        super().mouseReleaseEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def _side(self) -> float:
        return min(self.width(), self.height())

    def hitButton(self, pos) -> bool:
        c = QPointF(self.width() / 2, self.height() / 2)
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= self._side() * 0.36

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        side = self._side()
        # The ring keeps its size while there's a margin around it to give up, then shrinks.
        R = min(self._size * 0.34, side / 2 - 10) * (1 - 0.03 * self._press.v)
        on, hov = self._on.v, self._hover.v

        # ripple on connect
        if self._ripple.v < 1:
            t = self._ripple.v
            p.setPen(QPen(theme.alpha(theme.WHITE, 0.45 * (1 - t)), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, R + 8 + t * side * 0.14, R + 8 + t * side * 0.14)

        # outer track
        p.setPen(QPen(theme.mix(theme.BORDER_2, theme.FOCUS, hov * (1 - on)), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, R + 9, R + 9)

        # disc
        p.setPen(QPen(theme.mix(theme.BORDER_2, theme.WHITE, max(on, 0.25 * hov)), 1.2))
        p.setBrush(theme.mix(theme.mix(theme.SURFACE, theme.SURFACE_2, hov), theme.WHITE, on))
        p.drawEllipse(c, R, R)

        # spinner
        if self.state in ("connecting", "disconnecting"):
            t = time.monotonic() - self._t0
            start = (t * 300) % 360
            span = 40 + 70 * (1 + math.sin(t * 3.2)) / 2
            pen = QPen(QColor(theme.WHITE), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            rr = R + 9
            p.drawArc(QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr), int(-start * 16), int(-span * 16))

        # power glyph
        glyph = theme.mix(theme.mix(theme.TEXT_2, theme.WHITE, hov), theme.BLACK, on)
        pen = QPen(glyph, 2.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        s = R * 0.36
        p.drawArc(QRectF(c.x() - s, c.y() - s + s * 0.12, 2 * s, 2 * s), 120 * 16, 300 * 16)
        p.drawLine(QPointF(c.x(), c.y() - s * 1.12), QPointF(c.x(), c.y() - s * 0.1))
        p.end()


# -- segmented switch -----------------------------------------------------------------------
class Segmented(QWidget):
    """Pill switch whose white thumb slides to the chosen option. An option given as
    (key, text, tip, True) gets a small chevron: it opens a menu (see reselected)."""
    changed = Signal(object)
    reselected = Signal(object)     # the current option was clicked again

    def __init__(self, options: list[tuple[object, str, str]], current=None, *, stretch: bool = True,
                 height: int = 34, pt: float = 8.8):
        super().__init__()
        self.options = options
        self._keys = [o[0] for o in options]
        self._i = self._keys.index(current) if current in self._keys else 0
        self._pos = Anim(self, 280, QEasingCurve.OutCubic, float(self._i))
        self._hover = -1
        self._font = theme.font(pt, QFont.DemiBold)
        self.stretch = stretch
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        if not stretch:
            fm = QFontMetricsF(self._font)
            self.setFixedWidth(int(sum(fm.horizontalAdvance(o[1]) + 28 for o in options) + 8))

    def set_options(self, options: list[tuple], current=None) -> None:
        moved = [o[0] for o in options] != self._keys
        self.options = options
        self._keys = [o[0] for o in options]
        i = self._keys.index(current) if current in self._keys else 0
        if moved or i != self._i:
            self._i = i
            self._pos.jump(i)
        self.update()

    def rect_of(self, key) -> QRectF:
        return self._rects()[self._keys.index(key)]

    @property
    def current(self):
        return self._keys[self._i]

    def set_current(self, key, animate: bool = True) -> None:
        if key not in self._keys:
            return
        self._i = self._keys.index(key)
        self._pos.to(self._i) if animate else self._pos.jump(self._i)

    def _rects(self) -> list[QRectF]:
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.stretch:
            w = r.width() / len(self.options)
            return [QRectF(r.x() + i * w, r.y(), w, r.height()) for i in range(len(self.options))]
        fm = QFontMetricsF(self._font)
        out, x = [], r.x()
        for o in self.options:
            w = fm.horizontalAdvance(o[1]) + 28
            out.append(QRectF(x, r.y(), w, r.height()))
            x += w
        return out

    def _index_at(self, pos) -> int:
        return next((i for i, r in enumerate(self._rects()) if r.contains(QPointF(pos))), -1)

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.setToolTip(self.options[i][2] if i >= 0 and len(self.options[i]) > 2 else "")
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        i = self._index_at(e.position().toPoint())
        if i >= 0 and i != self._i:
            self._i = i
            self._pos.to(i)
            self.changed.emit(self._keys[i])
        elif i >= 0:
            self.reselected.emit(self._keys[i])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = outer.height() / 2
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(outer, rad, rad)
        rects = self._rects()
        # thumb: interpolate between neighbouring segments
        v = self._pos.v
        i0 = max(0, min(len(rects) - 1, int(math.floor(v))))
        i1 = min(len(rects) - 1, i0 + 1)
        f = v - i0
        a, b = rects[i0], rects[i1]
        thumb = QRectF(a.x() + (b.x() - a.x()) * f, a.y(), a.width() + (b.width() - a.width()) * f, a.height())
        p.setPen(Qt.NoPen)
        if 0 <= self._hover != self._i:
            p.setBrush(QColor(theme.SURFACE_2))
            hr = rects[self._hover]
            p.drawRoundedRect(hr, hr.height() / 2, hr.height() / 2)
        p.setBrush(QColor(theme.WHITE))
        p.drawRoundedRect(thumb, thumb.height() / 2, thumb.height() / 2)
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        for i, (r, o) in enumerate(zip(rects, self.options)):
            # text turns black as the thumb passes under it
            cover = max(0.0, 1 - abs(v - i))
            color = theme.mix(theme.TEXT_2 if i == self._hover else theme.MUTED, theme.BLACK, cover)
            p.setPen(color)
            menu = len(o) > 3 and o[3]
            text = fm.elidedText(o[1], Qt.ElideRight, r.width() - (30 if menu else 12))
            if menu:
                tw = fm.horizontalAdvance(text) + 13
                x = r.center().x() - tw / 2
                p.drawText(QRectF(x, r.y(), tw, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
                icons.paint(p, "chevron", QRectF(x + tw - 10, r.center().y() - 5.5, 11, 11), color, 2.2)
            else:
                p.drawText(r, Qt.AlignCenter, text)
        p.end()


# -- buttons --------------------------------------------------------------------------------
class IconButton(QAbstractButton):
    """Square (or text+icon) button with a fading hover background."""

    def __init__(self, icon_name: str, tooltip: str = "", text: str = "", primary: bool = False,
                 size: int = 36):
        super().__init__()
        self.icon_name = icon_name
        self.primary = primary
        self.setText(text)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = Anim(self, 150)
        self._press = Anim(self, 90)
        self._font = theme.font(9, QFont.DemiBold)
        self._spin = None
        self._t0 = 0.0
        w = size
        if text:
            w = int(QFontMetricsF(self._font).horizontalAdvance(text) + size + 10)
        self.setFixedSize(w, size)

    def set_spinning(self, on: bool) -> None:
        """Rotate the icon (used for refresh while subscriptions update)."""
        if on and self._spin is None:
            self._t0 = time.monotonic()
            self._spin = QTimer(self, interval=16, timeout=self.update)
            self._spin.start()
        elif not on and self._spin is not None:
            self._spin.stop()
            self._spin = None
            self.update()

    def enterEvent(self, e):
        self._hover.to(1)

    def leaveEvent(self, e):
        self._hover.to(0)

    def mousePressEvent(self, e):
        self._press.to(1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press.to(0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h, pr = self._hover.v, self._press.v
        enabled = self.isEnabled()
        if self.primary:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.mix(theme.mix(theme.WHITE, theme.ACCENT_HOVER, h), theme.ACCENT_PRESS, pr) if enabled
                       else QColor(theme.FAINT))
            fg = QColor(theme.BLACK)
        else:
            p.setPen(QPen(theme.mix(theme.BORDER, theme.BORDER_2, h), 1) if self.text() else Qt.NoPen)
            p.setBrush(theme.mix(theme.alpha(theme.SURFACE_2, 0.0 if not self.text() else 1.0),
                                 QColor(theme.SURFACE_2) if not self.text() else QColor(theme.RAISED), h))
            fg = theme.mix(theme.TEXT_2, theme.WHITE, h) if enabled else QColor(theme.FAINT)
        p.drawRoundedRect(r, 10, 10)
        s = min(18, self.height() // 2)
        if self.text():
            ir = QRectF(12, (self.height() - s) / 2, s, s)
        else:
            ir = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        if self._spin is not None:
            p.save()
            p.translate(ir.center())
            p.rotate(((time.monotonic() - self._t0) * 360) % 360)
            p.translate(-ir.center())
            icons.paint(p, self.icon_name, ir, fg)
            p.restore()
        else:
            icons.paint(p, self.icon_name, ir, fg)
        if self.text():
            p.setFont(self._font)
            p.setPen(fg)
            p.drawText(QRectF(ir.right() + 8, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       self.text())
        p.end()


# -- speed graph ----------------------------------------------------------------------------
class SpeedGraph(QWidget):
    """Last minute of download (solid) and upload (thin) speed; scrolls smoothly between samples."""

    def __init__(self, seconds: int = 60):
        super().__init__()
        self.down: deque[float] = deque([0.0] * seconds, maxlen=seconds)
        self.up: deque[float] = deque([0.0] * seconds, maxlen=seconds)
        self._shift = Anim(self, 350, QEasingCurve.OutCubic, 1.0)
        self._peak = Anim(self, 600, QEasingCurve.OutCubic, 1.0)
        self.setMinimumHeight(30)
        self.setMaximumHeight(62)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def sizeHint(self) -> QSize:
        return QSize(200, 62)

    def add(self, up: float, down: float) -> None:
        self.down.append(down)
        self.up.append(up)
        self._peak.to(max(max(self.down), max(self.up), 50 * 1024))
        self._shift.jump(0.0)
        self._shift.to(1.0)

    def clear(self) -> None:
        for d in (self.down, self.up):
            for i in range(len(d)):
                d[i] = 0.0
        self._peak.jump(1.0)
        self.update()

    def _path(self, data, r: QRectF, close: bool) -> QPainterPath:
        n = len(data)
        step = r.width() / (n - 2)
        off = (1 - self._shift.v) * step
        peak = max(self._peak.v, 1.0)
        pts = [QPointF(r.x() + (i - 1) * step + off, r.bottom() - r.height() * min(v / peak, 1.0) * 0.92)
               for i, v in enumerate(data)]
        path = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mx = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        if close:
            path.lineTo(pts[-1].x(), r.bottom())
            path.lineTo(pts[0].x(), r.bottom())
            path.closeSubpath()
        return path

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 4, 0, -1)
        p.setClipRect(self.rect())
        p.setPen(QPen(QColor(theme.BORDER), 1, Qt.DotLine))
        for k in (0.33, 0.66):
            y = r.y() + r.height() * k
            p.drawLine(QPointF(r.x(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(QPointF(r.x(), r.bottom()), QPointF(r.right(), r.bottom()))
        g = QLinearGradient(0, r.y(), 0, r.bottom())
        g.setColorAt(0, theme.alpha(theme.WHITE, 0.16))
        g.setColorAt(1, theme.alpha(theme.WHITE, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(self._path(self.down, r, True))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.WHITE if any(self.down) else theme.BORDER_2), 1.6))
        p.drawPath(self._path(self.down, r, False))
        if any(self.up):
            p.setPen(QPen(QColor(theme.MUTED), 1.1, Qt.DashLine))
            p.drawPath(self._path(self.up, r, False))
        p.end()


# -- theme switch ---------------------------------------------------------------------------
class ThemeSwitch(QAbstractButton):
    """Day / night toggle: a pill whose knob rolls from the moon to the sun. The sky behind it
    goes from night to day, the crescent fills into a sun and grows rays, the stars fade out."""
    theme_changed = Signal(str)     # "dark" | "light"

    STARS = ((0.30, 0.32, 1.1), (0.44, 0.64, 0.8), (0.20, 0.66, 0.7), (0.52, 0.28, 0.6))

    def __init__(self, dark: bool = True):
        super().__init__()
        self.setFixedSize(54, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(not dark)
        self._t = Anim(self, 460, QEasingCurve.InOutCubic, 0.0 if dark else 1.0)
        self._hover = Anim(self, 150)
        self._tip()
        self.toggled.connect(self._on_toggled)

    def _tip(self) -> None:
        self.setToolTip("Включить светлую тему" if not self.isChecked() else "Включить тёмную тему")

    def set_dark(self, dark: bool) -> None:
        self.blockSignals(True)
        self.setChecked(not dark)
        self.blockSignals(False)
        self._t.jump(0.0 if dark else 1.0)
        self._tip()

    def _on_toggled(self, light: bool) -> None:
        self._t.to(1.0 if light else 0.0)
        self._tip()
        self.theme_changed.emit("light" if light else "dark")

    def enterEvent(self, e):
        self._hover.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t, hv = self._t.v, self._hover.v
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        # track: night sky -> day sky; the edge gets brighter on hover
        edge = theme.mix(theme.mix("#2e2e31", "#d6d6d2", t), theme.mix("#56565a", "#a9a9a5", t), hv)
        p.setPen(QPen(edge, 1))
        p.setBrush(theme.mix("#141416", "#ffffff", t))
        p.drawRoundedRect(r, rad, rad)

        # stars on the night side, fading out one after another
        p.setPen(Qt.NoPen)
        for i, (sx, sy, sr) in enumerate(self.STARS):
            a = max(0.0, 1 - t * (1.8 + i * 0.4))
            if a > 0:
                p.setBrush(theme.alpha("#ffffff", 0.85 * a))
                p.drawEllipse(QPointF(r.right() - r.width() * sx, r.y() + r.height() * sy), sr, sr)

        # knob
        d = r.height() - 6
        c = QPointF(r.x() + 3 + d / 2 + (r.width() - 6 - d) * t, r.center().y())
        kr = d / 2
        if t > 0.05:
            # sun rays grow and turn into place as the knob arrives on the day side
            ray = QPen(theme.alpha("#141414", min(1.0, t * 1.4)), 1.5)
            ray.setCapStyle(Qt.RoundCap)
            p.setPen(ray)
            inner, outer = kr * 0.68, kr * (0.68 + 0.3 * t)
            for k in range(8):
                ang = math.radians(k * 45 + 60 * (1 - t))
                p.drawLine(QPointF(c.x() + math.cos(ang) * inner, c.y() + math.sin(ang) * inner),
                           QPointF(c.x() + math.cos(ang) * outer, c.y() + math.sin(ang) * outer))
            p.setPen(Qt.NoPen)
        # the moon is a disc with a bite that slides off it, leaving the sun's core
        disc = QPainterPath()
        core = kr * (1 - 0.48 * t)
        disc.addEllipse(c, core, core)
        bite = QPainterPath()
        off = kr * (0.42 + 1.3 * t)
        bite.addEllipse(QPointF(c.x() + off, c.y() - kr * 0.38 * (1 - t)), kr * 0.8, kr * 0.8)
        knob = disc.subtracted(bite)
        # Mid-way the sky and the knob pass through the same grey: a thin edge keeps it visible.
        bump = 4 * t * (1 - t)
        p.setPen(QPen(theme.alpha("#000000", 0.35 * bump), 1.2) if bump > 0.02 else Qt.NoPen)
        p.setBrush(theme.mix("#f4f4f0", "#141414", t))
        p.drawPath(knob)
        p.end()


class ElidedLabel(QLabel):
    """One line of text that ends in "…" when there's no room, instead of pushing its
    neighbours out of the window."""

    def __init__(self, text: str = "", **kw):
        super().__init__(**kw)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self._elide()

    def setText(self, text: str) -> None:
        self._full = text
        self._elide()

    def sizeHint(self) -> QSize:
        return QSize(int(QFontMetricsF(self.font()).horizontalAdvance(self._full)) + 4, super().sizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self) -> None:
        fm = QFontMetricsF(self.font())
        shown = fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 2))
        self.setToolTip(self._full if shown != self._full else "")
        super().setText(shown)


# -- small pieces ---------------------------------------------------------------------------
class Spinner(QWidget):
    """Three dots that pulse in turn."""

    def __init__(self, size: int = 18):
        super().__init__()
        self.setFixedSize(size, size)
        self._t = QTimer(self, interval=33, timeout=self.update)

    def showEvent(self, e):
        self._t.start()

    def hideEvent(self, e):
        self._t.stop()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = time.monotonic()
        p.setPen(Qt.NoPen)
        for i in range(3):
            a = 0.25 + 0.75 * max(0.0, math.sin(t * 5 - i * 0.7))
            p.setBrush(theme.alpha(theme.WHITE, a))
            p.drawEllipse(QPointF(self.width() / 2 + (i - 1) * 5.5, self.height() / 2), 1.8, 1.8)
        p.end()


class Meter(QWidget):
    """Thin progress line for subscription traffic."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(4)
        self._v = Anim(self, 700)

    def set_value(self, v: float | None) -> None:
        self.setVisible(v is not None)
        if v is not None:
            self._v.to(max(0.0, min(1.0, v)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(r, 2, 2)
        p.setBrush(QColor(theme.WHITE))
        p.drawRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * self._v.v), r.height()), 2, 2)
        p.end()


def caption(text: str) -> QLabel:
    """Small uppercase section label."""
    lbl = QLabel(text.upper())
    lbl.setFont(theme.font(7.2, QFont.DemiBold, spacing=1.4))
    theme.styled(lbl, lambda: f"color: {theme.MUTED};")
    return lbl


# -- toasts ---------------------------------------------------------------------------------
class Toast(QWidget):
    """Message card that slides up from the bottom right corner of its parent and goes away."""

    def __init__(self, parent: QWidget, text: str, error: bool, on_done):
        super().__init__(parent)
        self.error = error
        self._on_done = on_done
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.PointingHandCursor)
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.setFont(theme.font(9, QFont.Medium))
        theme.styled(self.label, lambda: f"color: {theme.TEXT};")
        self.title = QLabel("Ошибка" if error else "Готово", self)
        self.title.setFont(theme.font(7.2, QFont.DemiBold, spacing=1.4))
        theme.styled(self.title, lambda: f"color: {theme.MUTED};")
        self.title.setText(self.title.text().upper())
        w = 360
        self.label.setFixedWidth(w - 44)
        self.label.adjustSize()
        self.title.move(24, 14)
        self.label.move(24, 34)
        self.resize(w, self.label.height() + 52)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._timer = QTimer(self, singleShot=True, timeout=self.dismiss)
        self._timer.start(8000 if error else 3800)
        self._gone = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.FAINT if self.error else theme.BORDER_2), 1))
        p.setBrush(QColor(theme.TOAST))
        p.drawRoundedRect(r, 12, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.WHITE if self.error else theme.TEXT_2))
        p.drawRoundedRect(QRectF(r.x() + 12, r.y() + 17, 2.5, 9), 1.2, 1.2)
        p.end()

    def mousePressEvent(self, e):
        self.dismiss()

    def show_at(self, target: QPoint) -> None:
        self.move(target + QPoint(0, 24))
        self.show()
        self.raise_()
        self._slide(target, 0.0, 1.0)

    def move_to(self, target: QPoint) -> None:
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(240)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setEndValue(target)
        a.start(QPropertyAnimation.DeleteWhenStopped)

    def _slide(self, target: QPoint, o0: float, o1: float, done=None) -> None:
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(320)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setEndValue(target)
        o = QPropertyAnimation(self._fx, b"opacity", self)
        o.setDuration(260)
        o.setStartValue(o0)
        o.setEndValue(o1)
        if done:
            o.finished.connect(done)
        a.start(QPropertyAnimation.DeleteWhenStopped)
        o.start(QPropertyAnimation.DeleteWhenStopped)

    def dismiss(self) -> None:
        if self._gone:
            return
        self._gone = True
        self._slide(self.pos() + QPoint(0, 16), self._fx.opacity(), 0.0, self._finish)

    def _finish(self) -> None:
        self.hide()
        self._on_done(self)
        self.deleteLater()


class Toaster:
    """Keeps toasts stacked in the corner of a widget."""

    def __init__(self, host: QWidget):
        self.host = host
        self.items: list[Toast] = []

    def show(self, text: str, error: bool = False) -> None:
        if len(self.items) >= 3:
            self.items[0].dismiss()
        t = Toast(self.host, text, error, self._removed)
        self.items.append(t)
        self._layout(new=t)

    def _removed(self, t: Toast) -> None:
        if t in self.items:
            self.items.remove(t)
        self._layout()

    def _layout(self, new: Toast | None = None) -> None:
        y = self.host.height() - 24
        for t in reversed(self.items):
            y -= t.height()
            target = QPoint(self.host.width() - t.width() - 24, y)
            if t is new:
                t.show_at(target)
            elif not t._gone:
                t.move_to(target)
            y -= 10

    def relayout(self) -> None:
        y = self.host.height() - 24
        for t in reversed(self.items):
            y -= t.height()
            t.move(self.host.width() - t.width() - 24, y)
            y -= 10
