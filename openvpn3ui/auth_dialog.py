# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Login dialog built from whatever the VPN backend asks for."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                             QLineEdit, QVBoxLayout)

from openvpn3 import ClientAttentionGroup

# The backend's generic labels, replaced with friendlier ones.  Anything
# else (e.g. a server's MFA challenge text) is shown as sent.
_FRIENDLY_LABELS = {
    'Auth User name': 'Username',
    'Auth Password': 'Password',
}


def field_label(req):
    return _FRIENDLY_LABELS.get(req.label, req.label)


class AuthDialog(QDialog):
    # (profile name, {request name: value})
    submitted = pyqtSignal(str, dict)
    # (profile name)
    cancelled = pyqtSignal(str)

    def __init__(self, profile, requests, saved_username='', parent=None):
        super().__init__(parent)
        self.profile = profile
        self.requests = requests
        self.setWindowTitle('Log in to %s' % profile)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        challenge = any(r.group in (ClientAttentionGroup.CHALLENGE_STATIC,
                                    ClientAttentionGroup.CHALLENGE_DYNAMIC)
                        for r in requests)
        intro = QLabel('The server needs another code to finish logging in '
                       'to <b>%s</b>.' % profile if challenge else
                       'Log in to <b>%s</b>.' % profile)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        layout.addLayout(form)
        self.fields = {}
        first_empty = None
        for req in requests:
            edit = QLineEdit(self)
            if req.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            if req.is_username and saved_username:
                edit.setText(saved_username)
            if first_empty is None and not edit.text():
                first_empty = edit
            label = QLabel(field_label(req))
            label.setWordWrap(True)
            form.addRow(label, edit)
            self.fields[req.name] = edit
        (first_empty or next(iter(self.fields.values()))).setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.addButton(
            'Connect', QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {name: edit.text() for name, edit in self.fields.items()}

    def username(self):
        for req in self.requests:
            if req.is_username:
                return self.fields[req.name].text()
        return None

    def accept(self):
        super().accept()
        self.submitted.emit(self.profile, self.values())

    def reject(self):
        super().reject()
        self.cancelled.emit(self.profile)
