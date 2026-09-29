# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Live log viewer for VPN sessions."""

import html
import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QIcon, QTextCursor
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                             QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                             QVBoxLayout, QWidget)

from . import APP_NAME
from .backend import LogLevel

# Colours chosen to read on both light and dark Breeze
_LEVEL_COLOURS = {
    LogLevel.WARN: '#e67e22',
    LogLevel.ERROR: '#da4453',
    LogLevel.CRIT: '#da4453',
    LogLevel.FATAL: '#da4453',
}
_APP_COLOUR = '#3daee9'


def format_entry(entry):
    stamp = time.strftime('%H:%M:%S', time.localtime(entry.timestamp))
    prefix = ''
    # OpenVPN messages often carry their own "WARNING:"/"ERROR:" prefix
    if entry.level >= LogLevel.WARN \
            and not entry.text.upper().startswith(entry.level.name[:4]):
        prefix = entry.level.name + ': '
    return '%s  %s%s' % (stamp, prefix, entry.text)


def entry_html(entry):
    text = html.escape(format_entry(entry)).replace(' ', '&nbsp;')
    colour = _LEVEL_COLOURS.get(entry.level)
    if colour is None and entry.source == 'app':
        colour = _APP_COLOUR
    if colour:
        text = '<span style="color:%s">%s</span>' % (colour, text)
    return text


class LogWindow(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.backend = backend
        self.setWindowTitle('VPN Log — %s' % APP_NAME)
        self.resize(820, 480)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('Profile:'))
        self.profile_box = QComboBox()
        self.profile_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.profile_box.currentTextChanged.connect(self._reload)
        top.addWidget(self.profile_box)
        top.addStretch()
        self.follow = QCheckBox('Follow')
        self.follow.setToolTip('Scroll to new messages as they arrive')
        self.follow.setChecked(True)
        top.addWidget(self.follow)
        save = QPushButton(QIcon.fromTheme('document-save'), 'Save…')
        save.clicked.connect(self._save)
        top.addWidget(save)
        clear = QPushButton(QIcon.fromTheme('edit-clear-history'), 'Clear')
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        layout.addLayout(top)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont))
        self.text.setMaximumBlockCount(10_000)
        self.text.setPlaceholderText(
            'No log messages yet. Messages appear here while this profile '
            'is connecting or connected.')
        layout.addWidget(self.text)

        backend.profiles_changed.connect(self._fill_profiles)
        backend.log_message.connect(self._on_log_message)
        self._fill_profiles()

    def current_profile(self):
        return self.profile_box.currentText() or None

    def show_profile(self, name):
        if name:
            idx = self.profile_box.findText(name)
            if idx >= 0:
                self.profile_box.setCurrentIndex(idx)
        self.show()
        self.raise_()
        self.activateWindow()

    def _fill_profiles(self):
        current = self.current_profile()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItems(list(self.backend.profiles))
        idx = self.profile_box.findText(current) if current else -1
        if idx < 0:
            # Default to a profile that's in use, if any
            active = self.backend.active_profiles()
            idx = self.profile_box.findText(active[0]) if active else 0
        self.profile_box.setCurrentIndex(max(idx, 0))
        self.profile_box.blockSignals(False)
        self._reload()

    def _reload(self, *_):
        self.text.clear()
        name = self.current_profile()
        if not name:
            return
        for entry in self.backend.logs.get(name, ()):
            self.text.appendHtml(entry_html(entry))
        self._scroll()

    def _on_log_message(self, name, entry):
        if name != self.current_profile():
            return
        self.text.appendHtml(entry_html(entry))
        if self.follow.isChecked():
            self._scroll()

    def _scroll(self):
        self.text.moveCursor(QTextCursor.MoveOperation.End)
        self.text.ensureCursorVisible()

    def _clear(self):
        name = self.current_profile()
        if name:
            self.backend.clear_log(name)
        self.text.clear()

    def _save(self):
        name = self.current_profile() or 'vpn'
        default = os.path.join(
            os.path.expanduser('~'),
            '%s-%s.log' % (name, time.strftime('%Y%m%d-%H%M%S')))
        path, _ = QFileDialog.getSaveFileName(self, 'Save Log', default,
                                              'Log files (*.log *.txt)')
        if not path:
            return
        try:
            with open(path, 'w') as f:
                for entry in self.backend.logs.get(name, ()):
                    f.write(format_entry(entry) + '\n')
        except OSError as excp:
            QMessageBox.critical(self, 'Save Log', str(excp))
