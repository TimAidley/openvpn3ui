"""Backend state machine tests against fake OpenVPN3 objects."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import dbus  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from openvpn3 import (ClientAttentionGroup, ClientAttentionType,  # noqa: E402
                      StatusMajor, StatusMinor)
from openvpn3ui.backend import (LogLevel, State, VpnBackend,  # noqa: E402
                                state_for_status)

app = QApplication.instance() or QApplication([])


class FakeBus:
    def __init__(self):
        self.receivers = []

    def add_signal_receiver(self, handler, **kwargs):
        self.receivers.append((handler, kwargs))


class FakeSlot:
    def __init__(self, session, group, name, label, mask):
        self.session = session
        self.group, self.name, self.label, self.mask = group, name, label, mask

    def GetTypeGroup(self):
        return (ClientAttentionType.CREDENTIALS, self.group)

    def GetVariableName(self):
        return self.name

    def GetLabel(self):
        return self.label

    def GetInputMask(self):
        return self.mask

    def ProvideInput(self, value):
        self.session.provided[self.name] = value
        self.session.slots.remove(self)


class FakeSession:
    def __init__(self, path='/net/openvpn/v3/sessions/s1'):
        self.path = path
        self.status_cb = None
        self.log_cb = None
        self.provided = {}
        self.connect_calls = 0
        self.disconnected = False
        self.not_ready_count = 0
        self.slots = [
            FakeSlot(self, ClientAttentionGroup.USER_PASSWORD, 'username',
                     'Auth User name', False),
            FakeSlot(self, ClientAttentionGroup.USER_PASSWORD, 'password',
                     'Auth Password', True),
        ]

    def GetPath(self):
        return dbus.ObjectPath(self.path)

    def StatusChangeCallback(self, cb):
        self.status_cb = cb

    def LogCallback(self, cb):
        self.log_cb = cb

    def GetStatistics(self):
        return {'BYTES_IN': 2048, 'BYTES_OUT': 1024}

    def GetProperty(self, name):
        return {'session_created': dbus.UInt64(1000),
                'device_name': 'tun0',
                'connected_to': ('udp', '192.0.2.1', dbus.UInt32(1194)),
                }[name]

    def Ready(self):
        if self.not_ready_count:
            self.not_ready_count -= 1
            raise dbus.DBusException('Backend VPN process is not ready')
        if self.slots:
            raise dbus.DBusException('net.openvpn.v3.error.ready: '
                                     'Missing user credentials')

    def Connect(self):
        self.connect_calls += 1

    def Disconnect(self):
        self.disconnected = True

    def FetchUserInputSlots(self):
        return list(self.slots)

    def status(self, minor, message=''):
        self.status_cb(StatusMajor.CONNECTION.value, minor.value, message)


class FakeConfig:
    def __init__(self, name, path):
        self.name, self.path = name, path

    def GetConfigName(self):
        return self.name

    def GetPath(self):
        return self.path


class FakeCfgMgr:
    def __init__(self, configs):
        self.configs = configs

    def FetchAvailableConfigs(self):
        return self.configs

    def Retrieve(self, path):
        return next(c for c in self.configs if c.path == path)


class FakeSessMgr:
    def __init__(self, session):
        self.session = session

    def NewTunnel(self, cfg):
        return self.session


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.backend = VpnBackend(bus=FakeBus())
        cfgmgr = FakeCfgMgr([FakeConfig('work', '/cfg/1'),
                             FakeConfig('Other', '/cfg/2')])
        self.backend._cfgmgr = lambda: cfgmgr
        self.backend._sessmgr = lambda: FakeSessMgr(self.session)
        self.backend._reconcile_sessions = lambda: None
        self.creds, self.errors = [], []
        self.backend.credentials_required.connect(
            lambda n, r: self.creds.append((n, r)))
        self.backend.error.connect(lambda n, m: self.errors.append((n, m)))
        self.backend.refresh()

    def state(self):
        return self.backend.profiles['work'].state

    def test_profiles_sorted_case_insensitively(self):
        self.assertEqual(list(self.backend.profiles), ['Other', 'work'])

    def test_login_then_connect(self):
        self.backend.connect_profile('work')
        self.assertEqual(self.state(), State.AUTH_REQUIRED)
        self.assertEqual(len(self.creds), 1)
        name, reqs = self.creds[0]
        self.assertEqual(name, 'work')
        self.assertEqual([r.name for r in reqs], ['username', 'password'])
        self.assertTrue(reqs[0].is_username)
        self.assertTrue(reqs[1].secret)

        self.backend.provide_credentials('work', {'username': 'tim',
                                                  'password': '123456'})
        self.assertEqual(self.session.provided,
                         {'username': 'tim', 'password': '123456'})
        self.assertEqual(self.session.connect_calls, 1)
        self.assertEqual(self.state(), State.CONNECTING)

        self.session.status(StatusMinor.CONN_CONNECTED, 'ok')
        self.assertEqual(self.state(), State.CONNECTED)
        self.assertEqual(self.backend.connected_profiles(), ['work'])

        self.backend.disconnect_profile('work')
        self.assertTrue(self.session.disconnected)
        self.assertEqual(self.state(), State.DISCONNECTED)
        self.assertIsNone(self.backend.profiles['work'].session_path)
        self.assertEqual(self.errors, [])

    def test_dynamic_challenge_after_first_login(self):
        self.backend.connect_profile('work')
        self.backend.provide_credentials('work', {'username': 'u',
                                                  'password': 'p'})
        # Server responds with a CRV1 challenge
        self.session.slots = [FakeSlot(
            self.session, ClientAttentionGroup.CHALLENGE_DYNAMIC,
            'dynamic_challenge', 'Enter OTP', False)]
        self.session.status(StatusMinor.CFG_REQUIRE_USER)
        self.assertEqual(self.state(), State.AUTH_REQUIRED)
        self.assertEqual(self.creds[-1][1][0].label, 'Enter OTP')
        self.backend.provide_credentials('work', {'dynamic_challenge': '42'})
        self.assertEqual(self.session.provided['dynamic_challenge'], '42')
        self.assertEqual(self.session.connect_calls, 2)

    def test_auth_failure_reports_once_and_cleans_up(self):
        self.backend.connect_profile('work')
        self.backend.provide_credentials('work', {'username': 'u',
                                                  'password': 'bad'})
        cb = self.session.status_cb
        self.session.status(StatusMinor.CONN_AUTH_FAILED, 'AUTH_FAILED')
        # A trailing disconnect status must not produce a second error
        cb(StatusMajor.CONNECTION.value,
           StatusMinor.CONN_DISCONNECTED.value, '')
        self.assertEqual(len(self.errors), 1)
        self.assertIn('Authentication failed', self.errors[0][1])
        self.assertTrue(self.session.disconnected)
        self.assertEqual(self.state(), State.DISCONNECTED)
        self.assertIn('Authentication failed',
                      self.backend.profiles['work'].message)

    def test_cancel_login_disconnects(self):
        self.backend.connect_profile('work')
        self.backend.cancel_credentials('work')
        self.assertTrue(self.session.disconnected)
        self.assertEqual(self.state(), State.DISCONNECTED)
        self.assertEqual(self.errors, [])

    def test_backend_not_ready_is_retried(self):
        self.session.not_ready_count = 2
        self.backend.connect_profile('work')
        self.assertEqual(self.creds, [])
        for _ in range(50):
            app.processEvents()
            if self.creds:
                break
            import time
            time.sleep(0.05)
        self.assertEqual(len(self.creds), 1)

    def test_server_side_disconnect(self):
        self.backend.connect_profile('work')
        self.backend.provide_credentials('work', {'username': 'u',
                                                  'password': 'p'})
        self.session.status(StatusMinor.CONN_CONNECTED)
        self.session.status(StatusMinor.CONN_RECONNECTING)
        self.assertEqual(self.state(), State.RECONNECTING)
        self.session.status(StatusMinor.CONN_DISCONNECTED)
        self.assertEqual(self.state(), State.DISCONNECTED)
        self.assertIsNone(self.backend.profiles['work'].session_path)

    def test_log_and_session_info(self):
        logged = []
        self.backend.log_message.connect(lambda n, e: logged.append((n, e)))
        self.backend.connect_profile('work')
        self.backend.provide_credentials('work', {'username': 'u',
                                                  'password': 'p'})
        self.session.log_cb(dbus.UInt32(6), dbus.UInt32(5),
                            'first line\nsecond line\n')
        self.session.status(StatusMinor.CONN_CONNECTED)

        texts = [e.text for _, e in logged]
        self.assertIn('first line', texts)
        self.assertIn('second line', texts)
        self.assertIn('Connected', texts)
        vpn = [e for _, e in logged if e.source == 'vpn']
        self.assertEqual(vpn[0].level, LogLevel.WARN)
        self.assertEqual(len(self.backend.logs['work']), len(logged))

        info = self.backend.session_info('work')
        self.assertEqual(info.server, 'udp 192.0.2.1:1194')
        self.assertEqual(info.device, 'tun0')
        self.assertEqual(info.statistics['BYTES_IN'], 2048)
        self.assertIsNotNone(info.connected_since)

        self.backend.disconnect_profile('work')
        self.assertIsNone(self.backend.session_info('work'))
        self.assertIsNone(self.backend.profiles['work'].connected_since)
        self.assertIsNone(self.session.log_cb)


class StatusMappingTest(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(state_for_status(StatusMinor.CONN_CONNECTED),
                         State.CONNECTED)
        self.assertEqual(state_for_status(StatusMinor.PROC_STOPPED),
                         State.DISCONNECTED)
        self.assertIsNone(state_for_status(StatusMinor.CFG_OK))


if __name__ == '__main__':
    unittest.main()
