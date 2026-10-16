"""Line icons drawn on a 24-unit grid, so they stay crisp at any size and match the text."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _path(name: str) -> QPainterPath:
    p = QPainterPath()
    if name == "plus":
        p.moveTo(12, 5); p.lineTo(12, 19); p.moveTo(5, 12); p.lineTo(19, 12)
    elif name == "paste":
        p.addRoundedRect(QRectF(5.5, 5, 13, 15.5), 2.5, 2.5)
        p.addRoundedRect(QRectF(9, 3, 6, 4), 1.5, 1.5)
        p.moveTo(9, 12); p.lineTo(15, 12); p.moveTo(9, 15.5); p.lineTo(13.5, 15.5)
    elif name == "refresh":
        p.arcMoveTo(QRectF(5, 5, 14, 14), 60)
        p.arcTo(QRectF(5, 5, 14, 14), 60, 280)
        p.moveTo(18.2, 3.6); p.lineTo(18.6, 8.4); p.lineTo(13.9, 8.6)
    elif name == "pulse":
        p.moveTo(3, 12.5); p.lineTo(7, 12.5); p.lineTo(9.5, 6); p.lineTo(14, 18.5)
        p.lineTo(16.5, 12.5); p.lineTo(21, 12.5)
    elif name == "gear":
        p.addEllipse(QPointF(12, 12), 3, 3)
        for i in range(8):
            a = math.radians(i * 45)
            p.moveTo(12 + 6.2 * math.cos(a), 12 + 6.2 * math.sin(a))
            p.lineTo(12 + 8.6 * math.cos(a), 12 + 8.6 * math.sin(a))
        p.addEllipse(QPointF(12, 12), 6.2, 6.2)
    elif name == "logs":
        p.addRoundedRect(QRectF(3.5, 4.5, 17, 15), 2.5, 2.5)
        p.moveTo(7, 9.5); p.lineTo(9.5, 12); p.lineTo(7, 14.5); p.moveTo(11.5, 14.5); p.lineTo(16.5, 14.5)
    elif name == "search":
        p.addEllipse(QPointF(10.5, 10.5), 6, 6)
        p.moveTo(15, 15); p.lineTo(20, 20)
    elif name == "sort":
        p.moveTo(4.5, 7); p.lineTo(19.5, 7); p.moveTo(4.5, 12); p.lineTo(15, 12)
        p.moveTo(4.5, 17); p.lineTo(10.5, 17)
    elif name == "chevron":
        p.moveTo(8, 10); p.lineTo(12, 14); p.lineTo(16, 10)
    elif name == "check":
        p.moveTo(5.5, 12.5); p.lineTo(10, 17); p.lineTo(18.5, 7.5)
    elif name == "close":
        p.moveTo(7, 7); p.lineTo(17, 17); p.moveTo(17, 7); p.lineTo(7, 17)
    elif name == "folder":
        p.moveTo(3.5, 7); p.lineTo(3.5, 18); p.lineTo(20.5, 18); p.lineTo(20.5, 9); p.lineTo(11.5, 9)
        p.lineTo(9.5, 6.5); p.lineTo(4, 6.5)
    elif name == "copy":
        p.addRoundedRect(QRectF(8.5, 8.5, 11, 11), 2, 2)
        p.moveTo(15.5, 8.5); p.lineTo(15.5, 5.5); p.lineTo(4.5, 5.5); p.lineTo(4.5, 15.5); p.lineTo(8.5, 15.5)
    elif name == "trash":
        p.moveTo(4.5, 7); p.lineTo(19.5, 7); p.moveTo(9.5, 7); p.lineTo(10, 4.5); p.lineTo(14, 4.5)
        p.lineTo(14.5, 7); p.moveTo(6.5, 7); p.lineTo(7.5, 19.5); p.lineTo(16.5, 19.5); p.lineTo(17.5, 7)
    elif name == "arrow_down":
        p.moveTo(12, 4); p.lineTo(12, 19); p.moveTo(6.5, 13.5); p.lineTo(12, 19); p.lineTo(17.5, 13.5)
    elif name == "arrow_up":
        p.moveTo(12, 20); p.lineTo(12, 5); p.moveTo(6.5, 10.5); p.lineTo(12, 5); p.lineTo(17.5, 10.5)
    elif name == "globe":
        p.addEllipse(QPointF(12, 12), 8, 8)
        p.addEllipse(QPointF(12, 12), 3.6, 8)
        p.moveTo(4, 12); p.lineTo(20, 12)
    elif name == "link":
        p.moveTo(10, 14); p.lineTo(14, 10)
        p.addRoundedRect(QRectF(3.5, 11, 9, 9).translated(0, -0.5), 4, 4)
        p.addRoundedRect(QRectF(11.5, 3.5, 9, 9).translated(0, 0.5), 4, 4)
    elif name == "share":
        p.moveTo(12, 3.5); p.lineTo(12, 14.5); p.moveTo(8, 7.5); p.lineTo(12, 3.5); p.lineTo(16, 7.5)
        p.moveTo(9, 10.5); p.lineTo(6.5, 10.5); p.lineTo(6.5, 20.5); p.lineTo(17.5, 20.5); p.lineTo(17.5, 10.5)
        p.lineTo(15, 10.5)
    elif name == "qr":
        for x, y in ((4, 4), (14, 4), (4, 14)):
            p.addRoundedRect(QRectF(x, y, 6, 6), 1.2, 1.2)
        p.moveTo(14, 14); p.lineTo(14, 16.5); p.moveTo(17, 14); p.lineTo(20, 14); p.moveTo(20, 17)
        p.lineTo(20, 20); p.moveTo(14, 20); p.lineTo(16.5, 20); p.moveTo(17.2, 17.2); p.lineTo(17.2, 17.3)
    elif name == "code":
        p.moveTo(8.5, 7.5); p.lineTo(4, 12); p.lineTo(8.5, 16.5); p.moveTo(15.5, 7.5); p.lineTo(20, 12)
        p.lineTo(15.5, 16.5); p.moveTo(13.5, 5.5); p.lineTo(10.5, 18.5)
    elif name == "file":
        p.moveTo(14, 3.5); p.lineTo(6, 3.5); p.lineTo(6, 20.5); p.lineTo(18.5, 20.5); p.lineTo(18.5, 8)
        p.lineTo(14, 3.5); p.lineTo(14, 8); p.lineTo(18.5, 8)
    elif name == "route":
        p.addEllipse(QPointF(6, 18), 2.2, 2.2)
        p.addEllipse(QPointF(18, 6), 2.2, 2.2)
        p.moveTo(8.2, 18); p.lineTo(14, 18); p.cubicTo(18.5, 18, 18.5, 12, 14, 12); p.lineTo(10, 12)
        p.cubicTo(5.5, 12, 5.5, 6, 10, 6); p.lineTo(15.8, 6)
    elif name == "bolt":
        p.moveTo(13, 3); p.lineTo(5.5, 13.5); p.lineTo(11.5, 13.5); p.lineTo(10.5, 21); p.lineTo(18.5, 10.5)
        p.lineTo(12.5, 10.5); p.closeSubpath()
    return p


def paint(p: QPainter, name: str, rect: QRectF, color: QColor | str, width: float = 1.6) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.topLeft())
    s = min(rect.width(), rect.height()) / 24
    p.scale(s, s)
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(_path(name))
    p.restore()


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    color = color or theme.TEXT
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        paint(p, name, QRectF(0, 0, size * scale, size * scale), color)
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic
