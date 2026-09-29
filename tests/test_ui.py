"""Tests for settings, autostart, icons and the login dialog."""

import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_tmp = tempfile.TemporaryDirectory()
os.environ['XDG_CONFIG_HOME'] = _tmp.name

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from openvpn3 import ClientAttentionGroup  # noqa: E402
from openvpn3ui import settings  # noqa: E402
from openvpn3ui.auth_dialog import AuthDialog  # noqa: E402
from openvpn3ui.backend import InputRequest, State  # noqa: E402
from openvpn3ui.icons import status_kind  # noqa: E402

app = QApplication.instance() or QApplication([])

USERPASS = [
    InputRequest(ClientAttentionGroup.USER_PASSWORD, 'username',
                 'Auth User name', False),
    InputRequest(ClientAttentionGroup.USER_PASSWORD, 'password',
                 'Auth Password', True),
]


class AutostartTest(unittest.TestCase):
    def test_enable_disable(self):
        self.assertFalse(settings.autostart_enabled())
        settings.set_autostart(True)
        self.assertTrue(settings.autostart_enabled())
        path = os.path.join(_tmp.name, 'autostart', 'openvpn3ui.desktop')
        with open(path) as f:
            content = f.read()
        self.assertIn('--hidden', content)
        self.assertIn('Exec=', content)
        settings.set_autostart(False)
        self.assertFalse(settings.autostart_enabled())


class SettingsTest(unittest.TestCase):
    def test_username_per_profile(self):
        qs = QSettings(os.path.join(_tmp.name, 'test.ini'),
                       QSettings.Format.IniFormat)
        s = settings.Settings(qs)
        self.assertEqual(s.username('work'), '')
        s.set_username('work', 'tim')
        self.assertEqual(s.username('work'), 'tim')
        self.assertEqual(s.username('other'), '')


class AuthDialogTest(unittest.TestCase):
    def test_prefill_and_focus(self):
        dlg = AuthDialog('work', USERPASS, saved_username='tim')
        self.assertEqual(dlg.fields['username'].text(), 'tim')
        self.assertEqual(dlg.fields['password'].echoMode(),
                         QLineEdit.EchoMode.Password)
        self.assertIs(dlg.focusWidget() or dlg.fields['password'],
                      dlg.fields['password'])

    def test_submit_emits_values(self):
        dlg = AuthDialog('work', USERPASS)
        got = []
        dlg.submitted.connect(lambda n, v: got.append((n, v)))
        dlg.fields['username'].setText('tim')
        dlg.fields['password'].setText('123456')
        dlg.accept()
        self.assertEqual(got, [('work', {'username': 'tim',
                                         'password': '123456'})])
        self.assertEqual(dlg.username(), 'tim')

    def test_cancel_emits(self):
        dlg = AuthDialog('work', USERPASS)
        got = []
        dlg.cancelled.connect(got.append)
        dlg.reject()
        self.assertEqual(got, ['work'])


class StatusKindTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(status_kind([]), 'disconnected')
        self.assertEqual(status_kind([State.DISCONNECTED, State.CONNECTING]),
                         'busy')
        self.assertEqual(status_kind([State.CONNECTING, State.CONNECTED]),
                         'connected')


if __name__ == '__main__':
    unittest.main()
