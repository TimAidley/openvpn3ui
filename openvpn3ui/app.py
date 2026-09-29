# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Application controller: wires the backend to the window, tray and dialogs."""

import logging

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_NAME
from .auth_dialog import AuthDialog
from .backend import State
from .log_window import LogWindow
from .main_window import MainWindow
from .settings import Settings
from .tray import Tray

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, backend, start_hidden=False):
        self.backend = backend
        self.settings = Settings()
        self.dialogs = {}           # profile name -> AuthDialog
        self.last_state = {}        # profile name -> State
        self.errored = set()        # profiles whose last session failed

        self.window = MainWindow(backend, self.settings)
        self.window.quit_requested.connect(self.quit)
        self.window.show_log_requested.connect(self.show_log)
        self.log_window = None

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(backend)
            self.tray.show_window_requested.connect(self.toggle_window)
            self.tray.show_log_requested.connect(self.show_log)
            self.tray.quit_requested.connect(self.quit)
            self.tray.show()
        else:
            log.warning('No system tray available; running as a window')
            self.window.hide_on_close = False
            start_hidden = False

        backend.credentials_required.connect(self._on_credentials_required)
        backend.open_url.connect(self._on_open_url)
        backend.error.connect(self._on_error)
        backend.profile_updated.connect(self._on_profile_updated)
        backend.profiles_changed.connect(self._on_profiles_changed)

        backend.refresh()
        if not start_hidden:
            self.window.show_and_raise()
        # Once the event loop is running, so the login dialog can appear
        QTimer.singleShot(0, self._autoconnect)

    def _autoconnect(self):
        name = self.settings.autoconnect_profile()
        prof = self.backend.profiles.get(name) if name else None
        if prof is None:
            if name:
                log.warning('Auto-connect profile %r no longer exists', name)
            return
        if not prof.session_path:
            log.info('Auto-connecting %s', name)
            self.backend.connect_profile(name)

    def show_window(self):
        self.window.show_and_raise()

    def show_log(self, name=''):
        if self.log_window is None:
            self.log_window = LogWindow(self.backend)
        self.log_window.show_profile(name)

    def toggle_window(self):
        if self.window.isVisible() and self.window.isActiveWindow():
            self.window.hide()
        else:
            self.window.show_and_raise()

    # ------------------------------------------------------------------

    def _notify(self, title, message, critical=False):
        if self.tray is None:
            if critical:
                QMessageBox.warning(self.window, title, message)
            return
        icon = QSystemTrayIcon.MessageIcon.Critical if critical \
            else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, message, icon, 5000)

    def _on_profiles_changed(self):
        self.last_state = {name: prof.state
                           for name, prof in self.backend.profiles.items()}
        for name in list(self.dialogs):
            if name not in self.backend.profiles:
                self._close_dialog(name)

    def _on_profile_updated(self, name):
        prof = self.backend.profiles.get(name)
        if prof is None:
            return
        old = self.last_state.get(name, State.DISCONNECTED)
        self.last_state[name] = prof.state
        if prof.state == old:
            return
        if prof.state == State.CONNECTED:
            self.errored.discard(name)
            self._notify('VPN connected', 'Connected to %s' % name)
        elif prof.state == State.DISCONNECTED:
            self._close_dialog(name)
            if old == State.CONNECTED and name not in self.errored:
                self._notify('VPN disconnected',
                             'Disconnected from %s' % name)
        elif prof.state == State.CONNECTING:
            self.errored.discard(name)

    def _on_error(self, name, message):
        if name:
            self.errored.add(name)
        self._notify('VPN error' if not name else '%s: VPN error' % name,
                     message, critical=True)

    def _on_open_url(self, name, url):
        log.info('%s requires web authentication: %s', name, url)
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(
                self.window, 'Log in to %s' % name,
                'Open this address in a web browser to finish logging in:'
                '\n\n%s' % url)

    # ------------------------------------------------------------------

    def _on_credentials_required(self, name, requests):
        self._close_dialog(name)
        dlg = AuthDialog(name, requests, self.settings.username(name),
                         parent=None)
        dlg.setWindowIcon(self.window.windowIcon())
        dlg.submitted.connect(self._on_credentials_submitted)
        dlg.cancelled.connect(self._on_credentials_cancelled)
        self.dialogs[name] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_credentials_submitted(self, name, values):
        dlg = self.dialogs.pop(name, None)
        if dlg is not None:
            username = dlg.username()
            if username:
                self.settings.set_username(name, username)
            dlg.deleteLater()
        self.backend.provide_credentials(name, values)

    def _on_credentials_cancelled(self, name):
        dlg = self.dialogs.pop(name, None)
        if dlg is not None:
            dlg.deleteLater()
            self.backend.cancel_credentials(name)

    def _close_dialog(self, name):
        dlg = self.dialogs.pop(name, None)
        if dlg is not None:
            # Detach first so closing it doesn't cancel the session
            dlg.cancelled.disconnect()
            dlg.submitted.disconnect()
            dlg.close()
            dlg.deleteLater()

    # ------------------------------------------------------------------

    def quit(self):
        active = self.backend.active_profiles()
        if active:
            box = QMessageBox(
                QMessageBox.Icon.Question, 'Quit %s' % APP_NAME,
                'Disconnect %s before quitting?' % ', '.join(active),
                QMessageBox.StandardButton.Cancel, self.window)
            box.setInformativeText('If you keep the VPN connected, you can '
                                   'still manage it later from this app or '
                                   'with the openvpn3 command.')
            disconnect = box.addButton('Disconnect and Quit',
                                       QMessageBox.ButtonRole.AcceptRole)
            keep = box.addButton('Keep Connected',
                                 QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(disconnect)
            box.exec()
            clicked = box.clickedButton()
            if clicked == disconnect:
                self.backend.disconnect_all()
            elif clicked != keep:
                return
        for name in list(self.dialogs):
            self._close_dialog(name)
        if self.log_window is not None:
            self.log_window.close()
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()
