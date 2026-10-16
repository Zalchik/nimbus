"""Sharing UI: the QR code window and saving to files."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from ..i18n import tr
from .. import qr
from . import flags, theme
from .dialogs import Dialog


def paint_qr(p: QPainter, rect: QRectF, code: qr.QrCode, quiet: int = 4) -> None:
    """Dark modules on white with the standard quiet zone, snapped to whole pixels."""
    n = code.size + 2 * quiet
    cell = max(1, int(min(rect.width(), rect.height()) // n))
    side = cell * n
    x0 = int(rect.x() + (rect.width() - side) / 2)
    y0 = int(rect.y() + (rect.height() - side) / 2)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.fillRect(x0, y0, side, side, QColor("#ffffff"))
    black = QColor("#000000")
    for y, row in enumerate(code.modules):
        x = 0
        while x < code.size:  # one rectangle per horizontal run
            if row[x]:
                start = x
                while x < code.size and row[x]:
                    x += 1
                p.fillRect(x0 + (start + quiet) * cell, y0 + (y + quiet) * cell, (x - start) * cell, cell, black)
            else:
                x += 1
    p.restore()


class QrView(QWidget):
    def __init__(self, code: qr.QrCode, side: int = 340):
        super().__init__()
        self.code = code
        self.setFixedSize(QSize(side, side))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(self.rect()), 16, 16)
        paint_qr(p, QRectF(self.rect()).adjusted(6, 6, -6, -6), self.code)
        p.end()


def safe_filename(name: str, default: str = "nimbus") -> str:
    _, name = flags.split(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name)
    name = re.sub(r"[^\w\s().,#№+-]+", "", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:80] or default


def save_text(parent, title: str, name: str, text: str, ext: str) -> str | None:
    """Ask where to save and write text there; returns the path, or None if cancelled."""
    filters = {"json": "JSON (*.json)", "txt": tr("Текст (*.txt)")}
    start = Path.home() / "Downloads"
    start = start if start.is_dir() else Path.home()
    path, _ = QFileDialog.getSaveFileName(parent, title, str(start / f"{safe_filename(name)}.{ext}"),
                                          tr("{filter};;Все файлы (*)", filter=filters[ext]))
    if not path:
        return None
    Path(path).write_text(text, "utf-8")
    return path


class QrDialog(Dialog):
    def __init__(self, parent, title: str, text: str, hint: str, note: str = ""):
        super().__init__(parent, tr("QR-код"), title, hint, 460)
        self.text = text
        self.code = qr.encode(text, "M" if len(text.encode()) < 600 else "L")
        self.lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(QrView(self.code))
        row.addStretch()
        self.lay.addLayout(row)
        if note:
            lbl = QLabel(note, objectName="hint")
            lbl.setWordWrap(True)
            self.lay.addSpacing(4)
            self.lay.addWidget(lbl)
        self.status = QLabel(objectName="hint")
        self.status.setFont(theme.font(8.5, QFont.Medium))
        self.lay.addWidget(self.status)
        buttons = QHBoxLayout()
        save = QPushButton(tr("Сохранить PNG…"))
        save.clicked.connect(self._save)
        copy = QPushButton(tr("Копировать текст"))
        copy.clicked.connect(self._copy)
        done = QPushButton(tr("Готово"), objectName="primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        buttons.addWidget(save)
        buttons.addWidget(copy)
        buttons.addStretch()
        buttons.addWidget(done)
        self.lay.addSpacing(6)
        self.lay.addLayout(buttons)
        self._name = title

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.status.setText(tr("Скопировано в буфер обмена"))

    def _save(self) -> None:
        start = Path.home() / "Downloads"
        start = start if start.is_dir() else Path.home()
        path, _ = QFileDialog.getSaveFileName(self, tr("Сохранить QR-код"),
                                              str(start / f"{safe_filename(self._name)} QR.png"), "PNG (*.png)")
        if not path:
            return
        n = self.code.size + 8
        cell = max(8, 1024 // n)
        img = QImage(n * cell, n * cell, QImage.Format_RGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        paint_qr(p, QRectF(0, 0, img.width(), img.height()), self.code)
        p.end()
        img.save(path, "PNG")
        self.status.setText(tr("Сохранено: {name}", name=Path(path).name))
