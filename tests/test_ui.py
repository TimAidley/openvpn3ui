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


class FormattingTest(unittest.TestCase):
    def test_bytes(self):
        from openvpn3ui.formatting import human_bytes
        self.assertEqual(human_bytes(512), '512 B')
        self.assertEqual(human_bytes(1536), '1.5 KiB')
        self.assertEqual(human_bytes(5 * 1024 ** 3), '5.0 GiB')

    def test_duration(self):
        from openvpn3ui.formatting import human_duration
        self.assertEqual(human_duration(0), '0:00:00')
        self.assertEqual(human_duration(3725), '1:02:05')
        self.assertEqual(human_duration(90061), '1d 1:01:01')


class AutoconnectSettingTest(unittest.TestCase):
    def test_roundtrip(self):
        qs = QSettings(os.path.join(_tmp.name, 'auto.ini'),
                       QSettings.Format.IniFormat)
        s = settings.Settings(qs)
        self.assertEqual(s.autoconnect_profile(), '')
        s.set_autoconnect_profile('work')
        self.assertEqual(s.autoconnect_profile(), 'work')
        s.set_autoconnect_profile(None)
        self.assertEqual(s.autoconnect_profile(), '')


class ConnectionDetailsTest(unittest.TestCase):
    def test_rates_and_placeholders(self):
        import time
        from openvpn3ui.backend import SessionInfo
        from openvpn3ui.main_window import ConnectionDetails
        panel = ConnectionDetails()
        info = SessionInfo(connected_since=time.time() - 65,
                           server='udp 192.0.2.1:1194', device='',
                           statistics={'TUN_BYTES_IN': 1000,
                                       'TUN_BYTES_OUT': 10,
                                       'BYTES_IN': 99999})
        panel.update_from('work', info)
        self.assertEqual(panel.values['server'].text(), 'udp 192.0.2.1:1194')
        self.assertEqual(panel.values['received'].text(), '1000 B')
        self.assertTrue(panel.values['duration'].text().startswith('0:01:0'))
        # Second sample produces a rate
        panel._last = ('work', panel._last[1] - 1.0, 0, 0)
        panel.update_from('work', info)
        self.assertIn('/s', panel.values['received'].text())
        panel.update_from('work', None)
        self.assertEqual(panel.values['sent'].text(), '—')


class LogWindowTest(unittest.TestCase):
    def test_shows_and_follows_entries(self):
        import time
        from PyQt6.QtCore import QObject, pyqtSignal
        from openvpn3ui.backend import LogEntry, LogLevel, Profile
        from openvpn3ui.log_window import LogWindow

        class Backend(QObject):
            profiles_changed = pyqtSignal()
            log_message = pyqtSignal(str, object)

            def __init__(self):
                super().__init__()
                self.profiles = {'a': Profile('a', '/1'),
                                 'b': Profile('b', '/2')}
                self.logs = {'b': [LogEntry(time.time(), LogLevel.INFO,
                                            'old <line>')]}

            def active_profiles(self):
                return ['b']

            def clear_log(self, name):
                self.logs.pop(name, None)

        backend = Backend()
        win = LogWindow(backend)
        self.assertEqual(win.current_profile(), 'b')
        self.assertIn('old <line>', win.text.toPlainText())
        backend.log_message.emit('b', LogEntry(time.time(), LogLevel.ERROR,
                                               'boom'))
        backend.log_message.emit('a', LogEntry(time.time(), LogLevel.INFO,
                                               'other profile'))
        text = win.text.toPlainText()
        self.assertIn('ERROR: boom', text)
        self.assertNotIn('other profile', text)
        win._clear()
        self.assertEqual(win.text.toPlainText(), '')
        self.assertNotIn('b', backend.logs)


if __name__ == '__main__':
    unittest.main()
