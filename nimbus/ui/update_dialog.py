"""«Найдено обновление»: what's new, then download, check and install the new version."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QTextCharFormat, QTextCursor, QTextDocument, \
    QTextFormat
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser

from .. import i18n
from ..i18n import tr
from .. import paths, updater
from ..platform import current as osys
from . import theme
from .dialogs import Dialog, _chevron


def _tone_down(doc: QTextDocument) -> None:
    """Release notes in the dialog's scale and colors: headings a little larger than the text
    instead of page-sized, links in the text color (underlined) instead of the system blue."""
    changes = []   # collected first: merging formats while walking the fragments would split them
    block = doc.begin()
    while block.isValid():
        level = block.blockFormat().headingLevel()
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            change = QTextCharFormat()
            if level:
                change.setProperty(QTextFormat.FontSizeAdjustment, 1 if level <= 2 else 0)
                change.setFontWeight(QFont.DemiBold)
            if frag.charFormat().isAnchor():
                change.setForeground(QColor(theme.TEXT))
                change.setFontUnderline(True)
            if not change.isEmpty():
                changes.append((frag.position(), frag.position() + frag.length(), change))
            it += 1
        block = block.next()
    cur = QTextCursor(doc)
    for start, end, change in changes:
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.KeepAnchor)
        cur.mergeCharFormat(change)


class UpdateDialog(Dialog):
    def __init__(self, parent, ctl, release: updater.Release, quit_app):
        super().__init__(parent, tr("Обновление"), tr("Найдено обновление"), width=560)
        self.ctl, self.release, self.quit_app = ctl, release, quit_app
        self.kind = updater.install_kind()
        self._stop = None          # set to cancel a download
        self._busy = False

        versions = QLabel()
        versions.setTextFormat(Qt.RichText)
        versions.setFont(theme.font(11, QFont.Medium))
        versions.setText(f'<span style="color:{theme.MUTED}">Nimbus {paths.VERSION}</span>'
                         f'&nbsp;&nbsp;<span style="color:{theme.FAINT}">→</span>&nbsp;&nbsp;'
                         f'<b>{release.version}</b>')
        self.lay.addWidget(versions)
        if release.published:
            when = QLabel(tr("Выпущена {date}", date=i18n.date(release.published)),
                          objectName="hint")
            self.lay.addWidget(when)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(release.body.strip())
        _tone_down(self.notes.document())
        self.notes.setMinimumHeight(220)
        self.notes.hide()
        self.toggle = QPushButton(tr("Что нового"), objectName="disclosure")
        self.toggle.setIcon(_chevron(False))
        self.toggle.setIconSize(QSize(16, 16))
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.clicked.connect(self._toggle_notes)
        if release.body.strip():
            self.lay.addSpacing(4)
            self.lay.addWidget(self.toggle, 0, Qt.AlignLeft)
            self.lay.addWidget(self.notes, 1)

        self.progress = QProgressBar(textVisible=False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        self.status.hide()
        self.lay.addSpacing(4)
        self.lay.addWidget(self.progress)
        self.lay.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch()
        self.never = QPushButton(tr("Никогда"))
        self.never.setToolTip(tr("Не предлагать эту версию. О следующей Nimbus сообщит снова"))
        self.never.clicked.connect(self._skip)
        self.later = QPushButton(tr("Позже"))
        self.later.setToolTip(tr("Напомнить при следующей проверке"))
        self.later.clicked.connect(self.reject)
        self.download = QPushButton(tr("Скачать"), objectName="primary")
        self.download.setDefault(True)
        self.download.clicked.connect(self._download)
        if not self.kind and getattr(osys, "LAUNCHER", ""):
            self.download.setToolTip(tr("Открыть страницу релиза: скачайте исходный код новой версии "
                                        "и выполните в его папке make install"))
        elif not self.kind:
            self.download.setToolTip(tr("Открыть страницу релиза: эта копия запущена из исходников"))
        for b in (self.never, self.later, self.download):
            row.addWidget(b)
        self.lay.addSpacing(8)
        self.lay.addLayout(row)

    # -- notes -------------------------------------------------------------------------------
    def _toggle_notes(self) -> None:
        show = not self.notes.isVisible()
        self.notes.setVisible(show)
        self.toggle.setIcon(_chevron(show))
        self.lay.activate()
        h = self.lay.totalHeightForWidth(self.width()) if self.lay.hasHeightForWidth() else self.sizeHint().height()
        self.resize(self.width(), max(h, self.minimumSizeHint().height()))

    # -- buttons -----------------------------------------------------------------------------
    def _skip(self) -> None:
        self.ctl.settings.update_skip = self.release.version
        self.ctl.settings.save()
        self.reject()

    def _download(self) -> None:
        if not self.kind:
            QDesktopServices.openUrl(QUrl(self.release.page))
            self.accept()
            return
        self._busy = True
        self.download.setEnabled(False)
        self.download.setText(tr("Загрузка…"))
        self.never.hide()
        self.later.setText(tr("Отмена"))
        self.progress.setRange(0, 0)
        self.progress.show()
        self._set_status(tr("Подключаемся к GitHub…"))
        self._stop = self.ctl.download_update(self.release, self.kind, self._on_progress, self._on_ready,
                                              self._on_failed)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.TEXT if error else theme.MUTED};")
        self.status.show()

    def _on_progress(self, value) -> None:
        done, total = value
        if not self._busy:
            return
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
        if total and done >= total:
            self._set_status(tr("Проверяем файл…") if self.kind == "setup" else tr("Проверяем и распаковываем…"))
        else:
            self._set_status(tr("{used} из {total}", used=theme.human_bytes(done), total=theme.human_bytes(total))
                             if total
                             else theme.human_bytes(done))

    def _on_ready(self, prepared) -> None:
        if not self._busy:
            return
        self.progress.setRange(0, 0)
        self.later.setEnabled(False)
        self.download.setText(tr("Установка…"))
        self._set_status(tr("Отключаемся и перезапускаем Nimbus с новой версией…"))
        self.ctl.install_update(prepared, self.kind, self.quit_app, self._on_install_failed)

    def _on_install_failed(self, err) -> None:
        self._busy = True
        self._on_failed(err)
        self.later.setEnabled(True)
        self._set_status(tr("Не удалось запустить обновление: {err}", err=err), error=True)

    def _on_failed(self, err) -> None:
        if not self._busy:
            return
        self._busy = False
        self._stop = None
        self.progress.hide()
        self.download.setEnabled(True)
        self.download.setText(tr("Повторить"))
        self.never.show()
        self.later.setText(tr("Позже"))
        if not isinstance(err, updater.Cancelled):
            self._set_status(tr("Не удалось скачать обновление: {err}", err=err), error=True)

    def reject(self) -> None:
        if self._stop is not None:
            self._stop.set()
        self._busy = False
        super().reject()
