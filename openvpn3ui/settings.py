# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Persistent settings: remembered usernames and autostart."""

import os
import shlex
import shutil
import sys

from PyQt6.QtCore import QSettings, QStandardPaths

from . import APP_ID, APP_NAME


class Settings:
    def __init__(self, qsettings=None):
        self._s = qsettings if qsettings is not None \
            else QSettings(APP_ID, APP_ID)

    def username(self, profile):
        return self._s.value('profiles/%s/username' % profile, '', type=str)

    def set_username(self, profile, username):
        self._s.setValue('profiles/%s/username' % profile, username)
        self._s.sync()

    def autoconnect_profile(self):
        """The profile to connect when the app starts, or ''."""
        return self._s.value('autoconnect', '', type=str)

    def set_autoconnect_profile(self, profile):
        self._s.setValue('autoconnect', profile or '')
        self._s.sync()


def _autostart_file():
    config = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericConfigLocation)
    return os.path.join(config, 'autostart', APP_ID + '.desktop')


def launch_command():
    """The command which starts this application."""
    # ~/.local/bin isn't always on PATH, so check install.sh's default too
    for installed in (shutil.which(APP_ID),
                      os.path.expanduser('~/.local/bin/' + APP_ID)):
        if installed and os.access(installed, os.X_OK):
            return shlex.quote(installed)
    # Running from a source checkout
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return 'env PYTHONPATH=%s %s -m %s' % (shlex.quote(pkg_parent),
                                           shlex.quote(sys.executable), APP_ID)


def autostart_enabled():
    return os.path.exists(_autostart_file())


def set_autostart(enabled):
    path = _autostart_file()
    if not enabled:
        if os.path.exists(path):
            os.unlink(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('[Desktop Entry]\n'
                'Type=Application\n'
                'Name=%s\n'
                'Comment=OpenVPN3 tray client\n'
                'Exec=%s --hidden\n'
                'Icon=network-vpn\n'
                'Terminal=false\n'
                'X-GNOME-Autostart-enabled=true\n'
                % (APP_NAME, launch_command()))
