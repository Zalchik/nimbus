"""Palette, fonts, stylesheet and the painted app icon. Black and white on purpose: the only
color in the window comes from the country flags.

Two palettes, dark and light. WHITE / BLACK are the accent and the color drawn on it: white on
black in the dark theme, the other way round in the light one. Colors are read at paint time,
so painted widgets follow a switch by themselves; style sheets built from them register with
styled() to be rebuilt."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap

from .. import paths

PALETTES = {
    "dark": dict(
        BG="#0a0a0a",           # window
        PANEL="#0f0f0f",        # sidebar
        SURFACE="#151515",      # cards, inputs
        SURFACE_2="#1b1b1b",    # raised / hovered
        RAISED="#222222",       # hovered button with text, link chips
        PRESSED="#262626",      # hovered icon in the list
        HOVER="#181818",
        BORDER="#232323",
        BORDER_2="#303030",
        BORDER_3="#454545",     # hovered border
        FOCUS="#5a5a5a",        # focused border
        TEXT="#f2f2f2",
        TEXT_2="#c4c4c4",
        MUTED="#7c7c7c",
        FAINT="#4a4a4a",
        WHITE="#ffffff",        # accent
        BLACK="#000000",        # on accent
        ACCENT_HOVER="#dcdcdc",
        ACCENT_PRESS="#bdbdbd",
        TOAST="#141414",
    ),
    "light": dict(
        BG="#f7f7f6",
        PANEL="#efefed",
        SURFACE="#ffffff",
        SURFACE_2="#e9e9e7",
        RAISED="#e2e2e0",
        PRESSED="#dfdfdc",
        HOVER="#f1f1ef",
        BORDER="#e0e0dd",
        BORDER_2="#cdcdca",
        BORDER_3="#b3b3b0",
        FOCUS="#8f8f8c",
        TEXT="#141414",
        TEXT_2="#3a3a3a",
        MUTED="#707074",
        FAINT="#a9a9a6",
        WHITE="#111111",
        BLACK="#ffffff",
        ACCENT_HOVER="#2e2e2e",
        ACCENT_PRESS="#474747",
        TOAST="#ffffff",
    ),
}

NAME = "dark"
BG = PANEL = SURFACE = SURFACE_2 = RAISED = PRESSED = HOVER = BORDER = BORDER_2 = BORDER_3 = FOCUS = ""
TEXT = TEXT_2 = MUTED = FAINT = WHITE = BLACK = ACCENT_HOVER = ACCENT_PRESS = TOAST = ""

FONT = "Montserrat"
MONO = "IBM Plex Mono"

_styled: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_listeners: list = []


def set_palette(name: str) -> None:
    """Make `name` ("dark" | "light") the current palette. Doesn't touch any widget."""
    global NAME
    NAME = name if name in PALETTES else "dark"
    globals().update(PALETTES[NAME])


set_palette("dark")


def is_dark() -> bool:
    return NAME == "dark"


def styled(widget, css) -> None:
    """Give `widget` the style sheet css() now and again after every theme switch."""
    _styled[widget] = css
    widget.setStyleSheet(css())


def on_change(callback) -> None:
    """Call callback() after every theme switch (e.g. to redraw an icon made with a color)."""
    _listeners.append(callback)


def apply(name: str) -> None:
    """Switch the running app to palette `name`: style sheets, then a repaint of everything."""
    from PySide6.QtWidgets import QApplication

    set_palette(name)
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(stylesheet())
    for w, css in list(_styled.items()):
        try:
            w.setStyleSheet(css())
        except RuntimeError:     # the C++ widget is gone
            pass
    from PySide6.QtWidgets import QDialog, QMainWindow
    for w in app.topLevelWidgets():
        if isinstance(w, (QMainWindow, QDialog)) and w.isVisible():
            frame(w)
    for cb in list(_listeners):
        try:
            cb()
        except RuntimeError:
            _listeners.remove(cb)
    for w in app.allWidgets():
        w.update()


def load_fonts() -> None:
    """Bundled fonts first; if they're missing, an installed Montserrat (or Segoe UI) is used.
    QFontDatabase.families() would enumerate every font in Windows (slow right after a reboot
    on a PC with many fonts), so it's asked only when a bundled font didn't load."""
    global FONT, MONO
    loaded: set[str] = set()
    for f in sorted((paths.RES_DIR / "fonts").glob("*.ttf")):
        loaded.update(QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(f))))
    if FONT in loaded and MONO in loaded:
        return
    families = set(QFontDatabase.families())
    if FONT not in loaded and FONT not in families:
        FONT = "Segoe UI"
    if MONO not in loaded and MONO not in families:
        MONO = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"


def font(pt: float, weight: QFont.Weight = QFont.Normal, *, tabular: bool = False,
         spacing: float = 0, mono: bool = False) -> QFont:
    f = QFont(MONO if mono else FONT)
    f.setPointSizeF(pt)
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)  # digits of equal width: numbers don't jitter
        except (AttributeError, TypeError):
            pass
    return f


def mix(a: str | QColor, b: str | QColor, t: float) -> QColor:
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def alpha(c: str, a: float) -> QColor:
    q = QColor(c)
    q.setAlphaF(max(0.0, min(1.0, a)))
    return q


def frame(window) -> None:
    """Title bar of a top-level window in the colors of the theme."""
    from .. import winsys
    winsys.title_bar(int(window.winId()), is_dark(), BG, BORDER if is_dark() else BORDER_2)


def stylesheet() -> str:
    CHEVRON = _tinted_svg("chevron", "#9a9a9a" if is_dark() else "#6a6a6a")
    CHECK = _tinted_svg("check", BLACK)
    return f"""
* {{ font-family: "{FONT}"; font-size: 9.5pt; color: {TEXT}; outline: 0; }}
QMainWindow, QDialog, QMessageBox, QInputDialog {{ background: {BG}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QWidget#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel {{ background: transparent; }}
QLabel#muted, QLabel#hint {{ color: {MUTED}; }}
QLabel#hint {{ font-size: 8.5pt; }}
QLabel#caption {{ color: {MUTED}; font-size: 7.5pt; font-weight: 600; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 9px;
    padding: 8px 16px; font-weight: 500;
}}
QPushButton:hover {{ background: {SURFACE_2}; border-color: {BORDER_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {BORDER}; }}
QPushButton#primary, QDialogButtonBox QPushButton:default {{
    background: {WHITE}; color: {BLACK}; border: 1px solid {WHITE}; font-weight: 600;
}}
QPushButton#primary:hover, QDialogButtonBox QPushButton:default:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESS}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; padding: 7px 10px;
    selection-background-color: {WHITE}; selection-color: {BLACK};
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QPlainTextEdit:hover {{ border-color: {BORDER_2}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {FOCUS}; }}
QLineEdit#search {{ padding-left: 6px; border-radius: 10px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{CHEVRON}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 4px;
    selection-background-color: {SURFACE_2}; selection-color: {TEXT};
}}

QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 10px 2px; margin-right: 22px;
    border: none; border-bottom: 2px solid transparent; font-weight: 500;
}}
QTabBar::tab:hover {{ color: {TEXT_2}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {WHITE}; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER_2}; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {FOCUS}; }}
QCheckBox::indicator:checked {{ background: {WHITE}; border-color: {WHITE}; image: url("{CHECK}"); }}

QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 7px; color: {TEXT}; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
QListWidget::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER_2}; background: {BG};
}}
QListWidget::indicator:hover {{ border-color: {FOCUS}; }}
QListWidget::indicator:checked {{ background: {WHITE}; border-color: {WHITE}; image: url("{CHECK}"); }}
QListWidget::indicator:indeterminate {{ background: {FAINT}; border-color: {FAINT}; }}

QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QTreeWidget::item {{ padding: 2px 2px; color: {TEXT}; border: none; }}
QTreeWidget::item:hover {{ background: {SURFACE_2}; }}
QTreeWidget::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER_2}; background: {BG};
}}
QTreeWidget::indicator:hover {{ border-color: {FOCUS}; }}
QTreeWidget::indicator:checked {{ background: {WHITE}; border-color: {WHITE}; image: url("{CHECK}"); }}
QTreeWidget::indicator:indeterminate {{ background: {FAINT}; border-color: {FAINT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_2}; border-radius: 3px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_2}; border-radius: 3px; min-width: 36px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 26px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_2}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::indicator {{ width: 0; }}
QMenu::item:checked {{ font-weight: 600; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 8px; }}
QMenu#tray {{ padding: 4px; }}
QMenu#tray::item {{ padding: 5px 16px 5px 10px; }}
QMenu#tray::separator {{ margin: 3px 6px; }}
QTextBrowser {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; padding: 6px 8px;
    selection-background-color: {WHITE}; selection-color: {BLACK};
}}
QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {WHITE}; border-radius: 3px; }}
QPushButton#disclosure, QPushButton#disclosure:hover, QPushButton#disclosure:pressed {{
    background: transparent; border: none; padding: 4px 0; text-align: left; color: {TEXT_2}; font-weight: 600;
}}
QPushButton#disclosure:hover {{ color: {TEXT}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER_2}; padding: 6px 8px; }}
QMessageBox QLabel {{ min-width: 320px; }}
"""


def _tinted_svg(name: str, color: str) -> str:
    """Copy of resources/<name>.svg drawn in `color`, for style sheets (they take files only)."""
    src = paths.RES_DIR / f"{name}.svg"
    try:
        text = src.read_text("utf-8")
        for c in ("#0a0a0a", "#9a9a9a"):
            text = text.replace(c, color)
        out = paths.RUN_DIR / f"{name}-{color.lstrip('#')}.svg"
        if not out.exists() or out.read_text("utf-8") != text:
            out.write_text(text, "utf-8")
        return out.as_posix()
    except OSError:
        return src.as_posix()


# -- app icon -------------------------------------------------------------------------------
def _cloud_path(r: QRectF) -> QPainterPath:
    w, h, x, y = r.width(), r.height(), r.x(), r.y()
    p = QPainterPath()
    p.addRoundedRect(QRectF(x + w * 0.12, y + h * 0.48, w * 0.76, h * 0.30), h * 0.15, h * 0.15)
    p.addEllipse(QPointF(x + w * 0.34, y + h * 0.52), w * 0.17, w * 0.17)
    p.addEllipse(QPointF(x + w * 0.56, y + h * 0.44), w * 0.22, w * 0.22)
    p.addEllipse(QPointF(x + w * 0.74, y + h * 0.58), w * 0.13, w * 0.13)
    return p.simplified()


def app_pixmap(size: int = 256, state: str = "brand") -> QPixmap:
    """brand: black tile, white cloud · on: white tile, black cloud · off: grey."""
    # Fixed colors: the tray and the exe keep this icon whatever the window's theme.
    tile, cloud, edge = {"brand": ("#0d0d0d", "#ffffff", "#3a3a3a"), "on": ("#ffffff", "#000000", "#ffffff"),
                         "off": ("#1e1e1e", "#8a8a8a", "#3a3a3a")}[state]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    m = size * 0.04
    p.setPen(QColor(edge) if size >= 32 else Qt.NoPen)
    p.setBrush(QColor(tile))
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.24, size * 0.24)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(cloud))
    p.drawPath(_cloud_path(QRectF(size * 0.12, size * 0.1, size * 0.76, size * 0.76)))
    p.end()
    return pm


def app_icon(state: str = "brand") -> QIcon:
    icon = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(s, state))
    return icon


def human_bytes(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(n) < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def human_speed(n: float) -> tuple[str, str]:
    """(value, unit) for a bytes/s rate, e.g. ("1.4", "МБ/с")."""
    for unit in ("Б/с", "КБ/с", "МБ/с", "ГБ/с"):
        if n < 1000 or unit == "ГБ/с":
            return (f"{n:.0f}" if unit == "Б/с" or n >= 100 else f"{n:.1f}"), unit
        n /= 1024
    return f"{n:.1f}", "ГБ/с"
