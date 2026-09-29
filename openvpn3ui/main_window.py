"""Main window: profile list, connect/disconnect, import/remove."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                             QHeaderView, QInputDialog, QLineEdit,
                             QMainWindow, QMessageBox, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from . import APP_NAME, settings
from .backend import BackendError, State
from .icons import status_icon, status_kind


class MainWindow(QMainWindow):
    quit_requested = pyqtSignal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        # When False (no system tray), closing the window quits the app
        self.hide_on_close = True
        self.setWindowTitle(APP_NAME)
        self.resize(560, 320)

        self._build_menus()

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(['Profile', 'Status', 'Details'])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self._toggle_selected())
        layout.addWidget(self.tree)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton(
            QIcon.fromTheme('network-connect'), 'Connect')
        self.connect_button.clicked.connect(self._connect_selected)
        self.disconnect_button = QPushButton(
            QIcon.fromTheme('network-disconnect'), 'Disconnect')
        self.disconnect_button.clicked.connect(self._disconnect_selected)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch()
        import_button = QPushButton(QIcon.fromTheme('document-import'),
                                    'Import…')
        import_button.clicked.connect(self.import_profile)
        self.remove_button = QPushButton(QIcon.fromTheme('edit-delete'),
                                         'Remove…')
        self.remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(import_button)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)

        backend.profiles_changed.connect(self._rebuild)
        backend.profile_updated.connect(self._update_profile)
        self._rebuild()

    def _build_menus(self):
        file_menu = self.menuBar().addMenu('&File')
        act = QAction(QIcon.fromTheme('document-import'),
                      '&Import Profile…', self)
        act.triggered.connect(self.import_profile)
        file_menu.addAction(act)
        act = QAction(QIcon.fromTheme('view-refresh'), '&Refresh', self)
        act.setShortcut('F5')
        act.triggered.connect(self.backend.refresh)
        file_menu.addAction(act)
        file_menu.addSeparator()
        act = QAction(QIcon.fromTheme('application-exit'), '&Quit', self)
        act.setShortcut('Ctrl+Q')
        act.triggered.connect(self.quit_requested)
        file_menu.addAction(act)

        settings_menu = self.menuBar().addMenu('&Settings')
        self.autostart_action = QAction('&Start at Login', self)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(settings.autostart_enabled())
        self.autostart_action.toggled.connect(self._set_autostart)
        settings_menu.addAction(self.autostart_action)

    # ------------------------------------------------------------------

    def _rebuild(self):
        selected = self.selected_profile()
        self.tree.clear()
        for name in self.backend.profiles:
            item = QTreeWidgetItem([name, '', ''])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            self.tree.addTopLevelItem(item)
            self._fill_item(item)
            if name == selected:
                item.setSelected(True)
        if selected is None and self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setSelected(True)
        self._update_buttons()

    def _item_for(self, name):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == name:
                return item
        return None

    def _fill_item(self, item):
        prof = self.backend.profiles[item.data(0, Qt.ItemDataRole.UserRole)]
        item.setIcon(0, status_icon(status_kind([prof.state])))
        item.setText(1, prof.state.value)
        item.setText(2, prof.message)
        item.setToolTip(2, prof.message)

    def _update_profile(self, name):
        item = self._item_for(name)
        if item is not None:
            self._fill_item(item)
        self._update_buttons()

    def selected_profile(self):
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _update_buttons(self):
        prof = self.backend.profiles.get(self.selected_profile())
        active = prof is not None and prof.session_path is not None
        self.connect_button.setEnabled(prof is not None and not active)
        self.disconnect_button.setEnabled(active)
        self.remove_button.setEnabled(prof is not None and not active)

    # ------------------------------------------------------------------

    def _connect_selected(self):
        name = self.selected_profile()
        if name:
            self.backend.connect_profile(name)

    def _disconnect_selected(self):
        name = self.selected_profile()
        if name:
            self.backend.disconnect_profile(name)

    def _toggle_selected(self):
        prof = self.backend.profiles.get(self.selected_profile())
        if prof is None:
            return
        if prof.session_path:
            self.backend.disconnect_profile(prof.name)
        else:
            self.backend.connect_profile(prof.name)

    def import_profile(self):
        self.show_and_raise()
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import OpenVPN Profile', os.path.expanduser('~'),
            'OpenVPN profiles (*.ovpn *.conf);;All files (*)')
        if not path:
            return
        default = os.path.splitext(os.path.basename(path))[0]
        name, ok = QInputDialog.getText(self, 'Import OpenVPN Profile',
                                        'Profile name:',
                                        QLineEdit.EchoMode.Normal, default)
        name = name.strip()
        if not ok or not name:
            return
        try:
            warning = self.backend.import_profile(path, name)
        except BackendError as excp:
            QMessageBox.critical(self, 'Import Failed', str(excp))
            return
        if warning:
            QMessageBox.warning(self, 'Profile Imported',
                                'The profile "%s" was imported, but OpenVPN '
                                'reported a problem with it:\n\n%s'
                                % (name, warning))

    def _remove_selected(self):
        name = self.selected_profile()
        if not name:
            return
        answer = QMessageBox.question(
            self, 'Remove Profile',
            'Remove the VPN profile "%s"?\n\nThis deletes it from OpenVPN3 '
            'and cannot be undone.' % name)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.remove_profile(name)
        except BackendError as excp:
            QMessageBox.critical(self, 'Remove Failed', str(excp))

    def _set_autostart(self, enabled):
        try:
            settings.set_autostart(enabled)
        except OSError as excp:
            QMessageBox.critical(self, 'Start at Login',
                                 'Could not change the autostart entry: %s'
                                 % excp)
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(settings.autostart_enabled())
            self.autostart_action.blockSignals(False)

    # ------------------------------------------------------------------

    def show_and_raise(self):
        self.show()
        self.setWindowState(self.windowState()
                            & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.hide_on_close:
            event.ignore()
            self.hide()
        else:
            event.ignore()
            self.quit_requested.emit()
