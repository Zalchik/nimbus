"""Country flags for server names.

Windows has no color flag emoji (🇳🇱 shows up as the letters "NL"), so the flag is taken out of
the name and painted here. Names without a flag get one guessed from the country name in them.
"""
from __future__ import annotations

import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

from . import theme

_RI = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
_LEAD = re.compile(r"^[\W_]+")

# Country names as they appear in provider subscriptions (lowercase stems).
_NAMES = [
    ("нидерланд", "NL"), ("голланд", "NL"), ("netherlands", "NL"), ("amsterdam", "NL"),
    ("герман", "DE"), ("germany", "DE"), ("frankfurt", "DE"), ("финлянд", "FI"), ("finland", "FI"),
    ("польш", "PL"), ("poland", "PL"), ("эстон", "EE"), ("estonia", "EE"), ("латви", "LV"),
    ("latvia", "LV"), ("литв", "LT"), ("lithuania", "LT"), ("итали", "IT"), ("italy", "IT"),
    ("франци", "FR"), ("france", "FR"), ("болгари", "BG"), ("bulgaria", "BG"), ("турци", "TR"),
    ("turkey", "TR"), ("росси", "RU"), ("russia", "RU"), ("армени", "AM"), ("armenia", "AM"),
    ("казахстан", "KZ"), ("kazakhstan", "KZ"), ("сша", "US"), ("америк", "US"), ("usa", "US"),
    ("united states", "US"), ("канад", "CA"), ("canada", "CA"), ("великобритан", "GB"),
    ("англи", "GB"), ("united kingdom", "GB"), ("london", "GB"), ("чехи", "CZ"), ("czech", "CZ"),
    ("швеци", "SE"), ("sweden", "SE"), ("норвеги", "NO"), ("norway", "NO"), ("дания", "DK"),
    ("denmark", "DK"), ("швейцари", "CH"), ("switzerland", "CH"), ("австри", "AT"),
    ("austria", "AT"), ("испани", "ES"), ("spain", "ES"), ("португали", "PT"), ("portugal", "PT"),
    ("япони", "JP"), ("japan", "JP"), ("сингапур", "SG"), ("singapore", "SG"), ("гонконг", "HK"),
    ("hong kong", "HK"), ("украин", "UA"), ("ukraine", "UA"), ("грузи", "GE"), ("georgia", "GE"),
    ("серби", "RS"), ("serbia", "RS"), ("румыни", "RO"), ("romania", "RO"), ("венгри", "HU"),
    ("hungary", "HU"), ("молдов", "MD"), ("moldova", "MD"), ("израил", "IL"), ("israel", "IL"),
    ("оаэ", "AE"), ("эмират", "AE"), ("uae", "AE"), ("dubai", "AE"), ("инди", "IN"), ("india", "IN"),
    ("бразили", "BR"), ("brazil", "BR"), ("австрали", "AU"), ("australia", "AU"), ("коре", "KR"),
    ("korea", "KR"), ("тайван", "TW"), ("taiwan", "TW"), ("греци", "GR"), ("greece", "GR"),
    ("ирланди", "IE"), ("ireland", "IE"), ("бельги", "BE"), ("belgium", "BE"),
    ("люксембург", "LU"), ("luxembourg", "LU"), ("исланди", "IS"), ("iceland", "IS"),
    ("словаки", "SK"), ("slovakia", "SK"), ("словени", "SI"), ("slovenia", "SI"),
    ("хорвати", "HR"), ("croatia", "HR"), ("азербайджан", "AZ"), ("azerbaijan", "AZ"),
    ("узбекистан", "UZ"), ("uzbekistan", "UZ"), ("беларус", "BY"), ("belarus", "BY"),
    ("мексик", "MX"), ("mexico", "MX"), ("аргентин", "AR"), ("argentina", "AR"), ("китай", "CN"),
    ("china", "CN"), ("вьетнам", "VN"), ("vietnam", "VN"), ("индонези", "ID"),
    ("indonesia", "ID"), ("европ", "EU"), ("europe", "EU"),
]


def split(name: str) -> tuple[str | None, str]:
    """(country code or None, name without the flag)."""
    m = _RI.search(name)
    if m:
        code = "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in m.group())
        rest = (name[:m.start()] + name[m.end():]).strip()
        return code, re.sub(r"\s{2,}", " ", rest)
    low = name.lower()
    code = next((c for stem, c in _NAMES if stem in low), None)
    if code is None and re.search(r"\bEU\b", name):
        code = "EU"
    return code, name.strip()


def sort_key(name: str) -> str:
    """Alphabetical key that ignores leading emoji, flags and symbols."""
    return _LEAD.sub("", split(name)[1]).casefold()


# -- painting -------------------------------------------------------------------------------
H, V = "h", "v"
_STRIPES = {
    "RU": (H, "#ffffff #0039a6 #d52b1e"), "NL": (H, "#ae1c28 #ffffff #21468b"),
    "DE": (H, "#000000 #dd0000 #ffce00"), "EE": (H, "#0072ce #000000 #ffffff"),
    "BG": (H, "#ffffff #00966e #d62612"), "LT": (H, "#fdb913 #006a44 #c1272d"),
    "AM": (H, "#d90012 #0033a0 #f2a800"), "AT": (H, "#ed2939 #ffffff #ed2939"),
    "HU": (H, "#ce2939 #ffffff #477050"), "LU": (H, "#ed2939 #ffffff #00a1de"),
    "PL": (H, "#ffffff #dc143c"), "UA": (H, "#0057b7 #ffd700"), "ID": (H, "#ff0000 #ffffff"),
    "MC": (H, "#ce1126 #ffffff"), "RS": (H, "#c6363c #0c4076 #ffffff"),
    "SI": (H, "#ffffff #005da4 #ed1c24"), "SK": (H, "#ffffff #0b4ea2 #ee1c25"),
    "HR": (H, "#ff0000 #ffffff #171796"), "AZ": (H, "#00b5e2 #ef3340 #509e2f"),
    "LV": (H, "#9e3039:2 #ffffff:1 #9e3039:2"), "ES": (H, "#aa151b:1 #f1bf00:2 #aa151b:1"),
    "BY": (H, "#c8313e:2 #4aa657:1"), "IN": (H, "#ff9933 #ffffff #138808"),
    "AR": (H, "#74acdf #ffffff #74acdf"),
    "UZ": (H, "#0099b5:10 #ce1126:1 #ffffff:8 #ce1126:1 #1eb53a:10"),
    "FR": (V, "#002395 #ffffff #ed2939"), "IT": (V, "#009246 #ffffff #ce2b37"),
    "BE": (V, "#000000 #fae042 #ed2939"), "IE": (V, "#169b62 #ffffff #ff883e"),
    "RO": (V, "#002b7f #fcd116 #ce1126"), "MD": (V, "#0046ae #ffd200 #cc092f"),
    "MX": (V, "#006847 #ffffff #ce1126"), "PT": (V, "#006600:2 #ff0000:3"),
}
_CROSS = {  # Nordic crosses: background, cross, inner cross
    "FI": ("#ffffff", "#002f6c", None), "SE": ("#006aa7", "#fecc00", None),
    "DK": ("#c8102e", "#ffffff", None), "NO": ("#ba0c2f", "#ffffff", "#00205b"),
    "IS": ("#02529c", "#ffffff", "#dc1e35"),
}


def _stripes(p: QPainter, r: QRectF, kind: str, spec: str) -> None:
    parts = [(c.split(":")[0], float(c.split(":")[1]) if ":" in c else 1.0) for c in spec.split()]
    total = sum(w for _, w in parts)
    pos = 0.0
    for color, w in parts:
        if kind == H:
            seg = QRectF(r.x(), r.y() + r.height() * pos / total, r.width(), r.height() * w / total + 0.5)
        else:
            seg = QRectF(r.x() + r.width() * pos / total, r.y(), r.width() * w / total + 0.5, r.height())
        p.fillRect(seg, QColor(color))
        pos += w


def _star(cx: float, cy: float, r: float, points: int = 5, inner: float = 0.42, rot: float = -90) -> QPolygonF:
    poly = QPolygonF()
    for i in range(points * 2):
        rad = r if i % 2 == 0 else r * inner
        a = math.radians(rot + i * 180 / points)
        poly.append(QPointF(cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return poly


def _nordic(p: QPainter, r: QRectF, bg: str, cross: str, inner: str | None) -> None:
    p.fillRect(r, QColor(bg))
    w, h = r.width(), r.height()
    cx = r.x() + w * 0.36
    t = h * (0.26 if inner else 0.22)
    p.fillRect(QRectF(cx - t / 2, r.y(), t, h), QColor(cross))
    p.fillRect(QRectF(r.x(), r.center().y() - t / 2, w, t), QColor(cross))
    if inner:
        t2 = t * 0.5
        p.fillRect(QRectF(cx - t2 / 2, r.y(), t2, h), QColor(inner))
        p.fillRect(QRectF(r.x(), r.center().y() - t2 / 2, w, t2), QColor(inner))


def _union(p: QPainter, r: QRectF) -> None:
    p.fillRect(r, QColor("#012169"))
    p.save()
    p.setClipRect(r, Qt.IntersectClip)
    h = r.height()
    for color, width in (("#ffffff", h * 0.2), ("#c8102e", h * 0.08)):
        pen = QPen(QColor(color), width)
        p.setPen(pen)
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.bottomLeft(), r.topRight())
    p.setPen(Qt.NoPen)
    for color, t in (("#ffffff", h * 0.34), ("#c8102e", h * 0.2)):
        p.fillRect(QRectF(r.center().x() - t / 2, r.y(), t, h), QColor(color))
        p.fillRect(QRectF(r.x(), r.center().y() - t / 2, r.width(), t), QColor(color))
    p.restore()


def _special(p: QPainter, r: QRectF, code: str) -> bool:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    c = r.center()
    p.setPen(Qt.NoPen)
    if code == "US":
        for i in range(13):
            p.fillRect(QRectF(x, y + h * i / 13, w, h / 13 + 0.3), QColor("#b22234" if i % 2 == 0 else "#ffffff"))
        canton = QRectF(x, y, w * 0.42, h * 7 / 13)
        p.fillRect(canton, QColor("#3c3b6e"))
        p.setBrush(QColor(255, 255, 255, 210))
        for row in range(3):
            for col in range(4):
                p.drawEllipse(QPointF(canton.x() + canton.width() * (col + 0.5) / 4,
                                      canton.y() + canton.height() * (row + 0.5) / 3), h * 0.035, h * 0.035)
    elif code == "GB":
        _union(p, r)
    elif code == "AU":
        p.fillRect(r, QColor("#012169"))
        _union(p, QRectF(x, y, w / 2, h / 2))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(_star(x + w * 0.25, y + h * 0.75, h * 0.13, 7))
        for sx, sy in ((0.75, 0.25), (0.62, 0.48), (0.86, 0.42), (0.75, 0.8)):
            p.drawPolygon(_star(x + w * sx, y + h * sy, h * 0.07, 7))
    elif code == "CA":
        _stripes(p, r, V, "#d52b1e:1 #ffffff:2 #d52b1e:1")
        p.setBrush(QColor("#d52b1e"))
        p.drawPolygon(_star(c.x(), c.y() - h * 0.02, h * 0.3, 7, 0.5))
        p.fillRect(QRectF(c.x() - h * 0.025, c.y() + h * 0.12, h * 0.05, h * 0.18), QColor("#d52b1e"))
    elif code == "CH":
        p.fillRect(r, QColor("#da291c"))
        t, l = h * 0.18, h * 0.6
        p.fillRect(QRectF(c.x() - t / 2, c.y() - l / 2, t, l), QColor("#ffffff"))
        p.fillRect(QRectF(c.x() - l / 2, c.y() - t / 2, l, t), QColor("#ffffff"))
    elif code == "GE":
        p.fillRect(r, QColor("#ffffff"))
        t = h * 0.2
        p.fillRect(QRectF(c.x() - t / 2, y, t, h), QColor("#ff0000"))
        p.fillRect(QRectF(x, c.y() - t / 2, w, t), QColor("#ff0000"))
    elif code == "TR":
        p.fillRect(r, QColor("#e30a17"))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(x + w * 0.36, c.y()), h * 0.25, h * 0.25)
        p.setBrush(QColor("#e30a17"))
        p.drawEllipse(QPointF(x + w * 0.41, c.y()), h * 0.2, h * 0.2)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(_star(x + w * 0.57, c.y(), h * 0.13, 5, 0.42, 180))
    elif code == "KZ":
        p.fillRect(r, QColor("#00afca"))
        p.setBrush(QColor("#fec50c"))
        p.drawEllipse(QPointF(c.x(), c.y() - h * 0.06), h * 0.17, h * 0.17)
        for i in range(16):
            a = math.radians(i * 22.5)
            p.drawEllipse(QPointF(c.x() + h * 0.26 * math.cos(a), c.y() - h * 0.06 + h * 0.26 * math.sin(a)),
                          h * 0.025, h * 0.025)
        p.fillRect(QRectF(x + w * 0.06, y + h * 0.1, w * 0.04, h * 0.8), QColor("#fec50c"))
    elif code == "JP":
        p.fillRect(r, QColor("#ffffff"))
        p.setBrush(QColor("#bc002d"))
        p.drawEllipse(c, h * 0.3, h * 0.3)
    elif code == "KR":
        p.fillRect(r, QColor("#ffffff"))
        p.setBrush(QColor("#cd2e3a"))
        p.drawPie(QRectF(c.x() - h * 0.25, c.y() - h * 0.25, h * 0.5, h * 0.5), 0, 180 * 16)
        p.setBrush(QColor("#0047a0"))
        p.drawPie(QRectF(c.x() - h * 0.25, c.y() - h * 0.25, h * 0.5, h * 0.5), 180 * 16, 180 * 16)
    elif code in ("CN", "VN"):
        p.fillRect(r, QColor("#ee1c25" if code == "CN" else "#da251d"))
        p.setBrush(QColor("#ffff00"))
        if code == "VN":
            p.drawPolygon(_star(c.x(), c.y(), h * 0.3))
        else:
            p.drawPolygon(_star(x + w * 0.17, y + h * 0.27, h * 0.16))
            for sx, sy in ((0.33, 0.12), (0.4, 0.24), (0.4, 0.4), (0.33, 0.52)):
                p.drawPolygon(_star(x + w * sx, y + h * sy, h * 0.05))
    elif code == "HK":
        p.fillRect(r, QColor("#de2910"))
        p.setBrush(QColor("#ffffff"))
        for i in range(5):
            a = math.radians(-90 + i * 72)
            p.drawEllipse(QPointF(c.x() + h * 0.14 * math.cos(a), c.y() + h * 0.14 * math.sin(a)), h * 0.1, h * 0.1)
    elif code == "SG":
        _stripes(p, r, H, "#ef3340 #ffffff")
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(x + w * 0.2, y + h * 0.25), h * 0.15, h * 0.15)
        p.setBrush(QColor("#ef3340"))
        p.drawEllipse(QPointF(x + w * 0.25, y + h * 0.25), h * 0.14, h * 0.14)
    elif code == "EU":
        p.fillRect(r, QColor("#003399"))
        p.setBrush(QColor("#ffcc00"))
        for i in range(12):
            a = math.radians(i * 30)
            p.drawPolygon(_star(c.x() + h * 0.32 * math.cos(a), c.y() + h * 0.32 * math.sin(a), h * 0.065))
    elif code == "CZ":
        _stripes(p, r, H, "#ffffff #d7141a")
        tri = QPolygonF([QPointF(x, y), QPointF(x + w * 0.5, c.y()), QPointF(x, y + h)])
        p.setBrush(QColor("#11457e"))
        p.drawPolygon(tri)
    elif code == "IL":
        p.fillRect(r, QColor("#ffffff"))
        p.fillRect(QRectF(x, y + h * 0.1, w, h * 0.13), QColor("#0038b8"))
        p.fillRect(QRectF(x, y + h * 0.77, w, h * 0.13), QColor("#0038b8"))
        p.setPen(QPen(QColor("#0038b8"), max(1.0, h * 0.05)))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(_star(c.x(), c.y(), h * 0.2, 3, 1.0))
        p.drawPolygon(_star(c.x(), c.y(), h * 0.2, 3, 1.0, 90))
    elif code == "AE":
        _stripes(p, r, H, "#00732f #ffffff #000000")
        p.fillRect(QRectF(x, y, w * 0.26, h), QColor("#ff0000"))
    elif code == "GR":
        for i in range(9):
            p.fillRect(QRectF(x, y + h * i / 9, w, h / 9 + 0.3), QColor("#0d5eaf" if i % 2 == 0 else "#ffffff"))
        canton = QRectF(x, y, h * 5 / 9, h * 5 / 9)
        p.fillRect(canton, QColor("#0d5eaf"))
        t = h / 9
        p.fillRect(QRectF(canton.center().x() - t / 2, y, t, canton.height()), QColor("#ffffff"))
        p.fillRect(QRectF(x, canton.center().y() - t / 2, canton.width(), t), QColor("#ffffff"))
    elif code == "BR":
        p.fillRect(r, QColor("#009c3b"))
        p.setBrush(QColor("#ffdf00"))
        p.drawPolygon(QPolygonF([QPointF(c.x(), y + h * 0.12), QPointF(x + w * 0.92, c.y()),
                                 QPointF(c.x(), y + h * 0.88), QPointF(x + w * 0.08, c.y())]))
        p.setBrush(QColor("#002776"))
        p.drawEllipse(c, h * 0.21, h * 0.21)
    elif code == "TW":
        p.fillRect(r, QColor("#fe0000"))
        p.fillRect(QRectF(x, y, w / 2, h / 2), QColor("#000095"))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(_star(x + w / 4, y + h / 4, h * 0.17, 12, 0.6))
    else:
        return False
    return True


def paint_badge(p: QPainter, rect: QRectF, icon: str, radius: float = 3.0) -> None:
    """An icon in a flag-sized badge, where a row has no country (a balancer)."""
    from . import icons
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(theme.BORDER_2), 1))
    p.setBrush(QColor(theme.SURFACE_2))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    s = rect.height() * 0.86
    icons.paint(p, icon, QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s), theme.TEXT, 1.9)
    p.restore()


def paint(p: QPainter, rect: QRectF, code: str | None, radius: float = 3.0) -> None:
    """Flag in a rounded rect; a neutral badge with a globe or the code when we don't know it."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    p.setClipPath(clip)
    known = True
    if code in _STRIPES:
        _stripes(p, rect, *_STRIPES[code])
    elif code in _CROSS:
        _nordic(p, rect, *_CROSS[code])
    elif not (code and _special(p, rect, code)):
        known = False
        p.fillRect(rect, QColor(theme.SURFACE_2))
        if code:
            p.setPen(QColor(theme.TEXT_2))
            p.setFont(theme.font(max(5.5, rect.height() * 0.36), QFont.DemiBold))
            p.drawText(rect, Qt.AlignCenter, code)
        else:
            from . import icons
            s = rect.height() * 0.8
            icons.paint(p, "globe", QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s),
                        theme.MUTED, 1.8)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 34 if known else 20), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.restore()
