"""System tray icon and menu."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_NAME
from .backend import State
from .icons import status_icon, status_kind


class Tray(QSystemTrayIcon):
    show_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        backend.profiles_changed.connect(self.update)
        backend.profile_updated.connect(self.update)
        self.update()

    def update(self, *_):
        profiles = list(self.backend.profiles.values())
        self.setIcon(status_icon(status_kind(p.state for p in profiles)))

        active = [p for p in profiles if p.session_path]
        if active:
            tip = '\n'.join('%s: %s' % (p.name, p.state.value)
                            for p in active)
        else:
            tip = 'Not connected'
        self.setToolTip('%s\n%s' % (APP_NAME, tip))

        self.menu.clear()
        if not profiles:
            act = self.menu.addAction('No VPN profiles')
            act.setEnabled(False)
        for prof in profiles:
            if prof.session_path:
                label = 'Disconnect %s' % prof.name
                if prof.state != State.CONNECTED:
                    label += ' (%s)' % prof.state.value.lower()
                act = self.menu.addAction(
                    QIcon.fromTheme('network-disconnect'), label)
                act.triggered.connect(
                    lambda _, n=prof.name: self.backend.disconnect_profile(n))
            else:
                act = self.menu.addAction(
                    QIcon.fromTheme('network-connect'),
                    'Connect %s' % prof.name)
                act.triggered.connect(
                    lambda _, n=prof.name: self.backend.connect_profile(n))
        self.menu.addSeparator()
        act = self.menu.addAction(QIcon.fromTheme('window'), 'Show Window…')
        act.triggered.connect(self.show_window_requested)
        act = self.menu.addAction(QIcon.fromTheme('application-exit'), 'Quit')
        act.triggered.connect(self.quit_requested)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_requested.emit()
