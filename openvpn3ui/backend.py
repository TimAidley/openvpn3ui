"""OpenVPN3 D-Bus backend.

Wraps the official ``openvpn3`` Python module and exposes profile/session
state to the Qt world through signals.  All D-Bus signal delivery relies on
``dbus.mainloop.glib.DBusGMainLoop`` being installed as the default main loop
before the bus is opened; Qt's GLib event dispatcher then runs it for us.
"""

import collections
import enum
import logging
import os
import time
from dataclasses import dataclass, field

import dbus
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from openvpn3 import (ClientAttentionGroup, ClientAttentionType,
                      ConfigParser, ConfigurationManager, SessionManager,
                      SessionManagerEventType, StatusMajor, StatusMinor)

log = logging.getLogger(__name__)

SESSIONS_BUS_NAME = 'net.openvpn.v3.sessions'
SESSIONS_PATH = '/net/openvpn/v3/sessions'

# How long to keep retrying Ready() while the backend VPN process starts
READY_RETRY_MS = 250
READY_MAX_RETRIES = 80

# Log lines kept per profile
LOG_LINES = 5000


class LogLevel(enum.IntEnum):
    """OpenVPN3's LogCategory values."""
    UNDEFINED = 0
    DEBUG = 1
    VERB2 = 2
    VERB1 = 3
    INFO = 4
    WARN = 5
    ERROR = 6
    CRIT = 7
    FATAL = 8

    @classmethod
    def from_category(cls, value):
        try:
            return cls(int(value))
        except ValueError:
            return cls.UNDEFINED


@dataclass
class LogEntry:
    timestamp: float
    level: LogLevel
    text: str
    source: str = 'vpn'     # 'vpn' for OpenVPN3 log messages, 'app' for ours


class State(enum.Enum):
    DISCONNECTED = 'Disconnected'
    CONNECTING = 'Connecting'
    AUTH_REQUIRED = 'Waiting for login'
    CONNECTED = 'Connected'
    RECONNECTING = 'Reconnecting'
    PAUSED = 'Paused'
    DISCONNECTING = 'Disconnecting'

    @property
    def busy(self):
        return self in (State.CONNECTING, State.AUTH_REQUIRED,
                        State.RECONNECTING, State.DISCONNECTING)


# StatusMinor codes which mean the session is finished and should be dropped
_END_STATUSES = {StatusMinor.CONN_DISCONNECTED, StatusMinor.CONN_DONE,
                 StatusMinor.PROC_STOPPED, StatusMinor.PROC_KILLED,
                 StatusMinor.SESS_REMOVED}

# StatusMinor codes which map directly onto a State
_STATE_FOR_STATUS = {
    StatusMinor.CONN_INIT: State.CONNECTING,
    StatusMinor.CONN_CONNECTING: State.CONNECTING,
    StatusMinor.CONN_CONNECTED: State.CONNECTED,
    StatusMinor.CONN_RECONNECTING: State.RECONNECTING,
    StatusMinor.CONN_PAUSING: State.PAUSED,
    StatusMinor.CONN_PAUSED: State.PAUSED,
    StatusMinor.CONN_RESUMING: State.CONNECTING,
    StatusMinor.CONN_DISCONNECTING: State.DISCONNECTING,
}


def state_for_status(minor):
    """Map a StatusMinor to a State, or None if it doesn't imply one."""
    if minor in _END_STATUSES:
        return State.DISCONNECTED
    return _STATE_FOR_STATUS.get(minor)


@dataclass
class InputRequest:
    """One piece of information the VPN backend wants from the user."""
    group: ClientAttentionGroup
    name: str        # backend variable name, e.g. 'username', 'password'
    label: str       # human readable prompt from the backend/server
    secret: bool     # input should be masked
    slot: object = field(repr=False, default=None)

    @property
    def is_username(self):
        return (self.group == ClientAttentionGroup.USER_PASSWORD
                and self.name == 'username')


@dataclass
class Profile:
    name: str
    config_path: str
    session_path: str = None
    state: State = State.DISCONNECTED
    message: str = ''
    connected_since: float = None   # time.time() of the last CONNECTED


@dataclass
class SessionInfo:
    """Details about a live session, for display."""
    created: float = None           # session creation (epoch seconds)
    connected_since: float = None
    server: str = ''                # e.g. 'udp 192.0.2.1:1194'
    device: str = ''                # tunnel interface, e.g. 'tun0'
    statistics: dict = field(default_factory=dict)


class _Tracked:
    """Book-keeping for one session we're following."""

    def __init__(self, session, profile_name, owned):
        self.session = session
        self.profile_name = profile_name
        self.owned = owned          # started by us, so we drive auth/connect
        self.status_cb = None
        self.log_cb = None
        self.ready_retries = 0
        self.pending_input = []
        self.failed = False         # an error has already been reported


class BackendError(Exception):
    pass


def _dbus_error_text(excp):
    """Extract the human readable part of a D-Bus exception."""
    msg = excp.get_dbus_message() if isinstance(excp, dbus.DBusException) \
        else None
    return (msg or str(excp)).strip()


class VpnBackend(QObject):
    # The profile list itself changed (import/remove/refresh)
    profiles_changed = pyqtSignal()
    # A single profile's state or message changed
    profile_updated = pyqtSignal(str)
    # (profile name, list[InputRequest]) - call provide_credentials() or
    # cancel_credentials() in response
    credentials_required = pyqtSignal(str, list)
    # (profile name, url) - web based authentication
    open_url = pyqtSignal(str, str)
    # (profile name, message)
    error = pyqtSignal(str, str)
    # (profile name, LogEntry)
    log_message = pyqtSignal(str, object)

    def __init__(self, bus=None, parent=None):
        super().__init__(parent)
        self._bus = bus if bus is not None else dbus.SystemBus()
        self._uid = os.getuid()
        self.profiles = {}      # name -> Profile
        self._sessions = {}     # session path -> _Tracked
        self.logs = collections.defaultdict(
            lambda: collections.deque(maxlen=LOG_LINES))

        # Subscribe via the well-known name so this survives the session
        # manager service restarting.
        self._bus.add_signal_receiver(
            self._on_session_manager_event,
            signal_name='SessionManagerEvent',
            dbus_interface=SESSIONS_BUS_NAME,
            bus_name=SESSIONS_BUS_NAME,
            path=SESSIONS_PATH)

        # Safety net for any missed signals while sessions exist
        self._reconcile_timer = QTimer(self)
        self._reconcile_timer.setInterval(10_000)
        self._reconcile_timer.timeout.connect(self._reconcile_sessions)

    # The OpenVPN3 services are D-Bus activated and may exit when idle.
    # The openvpn3 module binds proxies to the service's unique name, so
    # create fresh managers per use rather than holding on to them.
    def _cfgmgr(self):
        return ConfigurationManager(self._bus)

    def _sessmgr(self):
        return SessionManager(self._bus)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload the configuration profiles and attach to live sessions."""
        try:
            configs = self._cfgmgr().FetchAvailableConfigs()
            found = {}
            for cfg in configs:
                name = str(cfg.GetConfigName())
                found[name] = str(cfg.GetPath())
        except (dbus.DBusException, RuntimeError) as excp:
            log.exception('Failed to fetch configuration profiles')
            self.error.emit('', 'Could not read VPN profiles: %s'
                            % _dbus_error_text(excp))
            return

        old = self.profiles
        self.profiles = {}
        for name in sorted(found, key=str.lower):
            prof = old.get(name)
            if prof is None or prof.config_path != found[name]:
                prof = Profile(name, found[name])
            self.profiles[name] = prof
        # Sessions of profiles which vanished are kept tracked; their
        # profile lookups simply return None until they end.
        self.profiles_changed.emit()
        self._reconcile_sessions()

    def import_profile(self, file_path, name):
        """Import an .ovpn file as a persistent profile.

        Returns a warning string (possibly empty).  Raises BackendError on
        failure.
        """
        if name in self.profiles:
            raise BackendError('A profile named "%s" already exists' % name)
        file_path = os.path.abspath(file_path)
        # ConfigParser resolves files the profile refers to (ca, cert, ...)
        # relative to the working directory, so parse from the file's own
        # directory, as the openvpn3 command does.
        old_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(file_path))
            parser = ConfigParser(['openvpn3ui', '--config', file_path],
                                  'Import profile')
            cfgstr = parser.GenerateConfig()
        except Exception as excp:
            raise BackendError('Could not read %s: %s'
                               % (os.path.basename(file_path),
                                  str(excp).replace('openvpn3ui: error: ',
                                                    '')))
        finally:
            os.chdir(old_cwd)

        warning = ''
        try:
            cfg = self._cfgmgr().Import(name, cfgstr, False, True)
        except (dbus.DBusException, RuntimeError) as excp:
            raise BackendError('Import failed: %s' % _dbus_error_text(excp))
        try:
            cfg.Validate()
        except dbus.DBusException as excp:
            warning = _dbus_error_text(excp)
            log.warning('Profile %s imported with warning: %s', name, warning)
        self.refresh()
        return warning

    def remove_profile(self, name):
        prof = self.profiles.get(name)
        if prof is None:
            return
        if prof.session_path:
            raise BackendError('Disconnect "%s" before removing it' % name)
        try:
            self._cfgmgr().Retrieve(prof.config_path).Remove()
        except (dbus.DBusException, RuntimeError) as excp:
            raise BackendError('Could not remove "%s": %s'
                               % (name, _dbus_error_text(excp)))
        self.refresh()

    # ------------------------------------------------------------------
    # Connecting and disconnecting
    # ------------------------------------------------------------------

    def connect_profile(self, name):
        prof = self.profiles.get(name)
        if prof is None or prof.session_path:
            return
        log.info('Connecting %s', name)
        try:
            cfg = self._cfgmgr().Retrieve(prof.config_path)
            session = self._sessmgr().NewTunnel(cfg)
        except (dbus.DBusException, RuntimeError) as excp:
            self._report(name, 'Could not start VPN session: %s'
                         % _dbus_error_text(excp))
            return
        tracked = self._track(session, name, owned=True)
        if tracked is None:
            return
        self._set_state(name, State.CONNECTING, 'Starting')
        self._start_attempt(str(session.GetPath()))

    def disconnect_profile(self, name):
        prof = self.profiles.get(name)
        if prof is None or not prof.session_path:
            return
        log.info('Disconnecting %s', name)
        self._set_state(name, State.DISCONNECTING, '')
        self._untrack(prof.session_path, disconnect=True)

    def disconnect_all(self):
        for path in list(self._sessions):
            self._untrack(path, disconnect=True)

    def provide_credentials(self, name, values):
        """Answer an earlier credentials_required signal.

        values maps InputRequest.name -> string.
        """
        tracked = self._tracked_for(name)
        if tracked is None or not tracked.pending_input:
            return
        try:
            for req in tracked.pending_input:
                req.slot.ProvideInput(values.get(req.name, ''))
        except dbus.DBusException as excp:
            self._fail(tracked, 'Could not send credentials: %s'
                       % _dbus_error_text(excp))
            return
        tracked.pending_input = []
        tracked.ready_retries = 0
        self._set_state(name, State.CONNECTING, 'Authenticating')
        self._start_attempt(str(tracked.session.GetPath()))

    def cancel_credentials(self, name):
        tracked = self._tracked_for(name)
        if tracked is not None:
            tracked.pending_input = []
        self.disconnect_profile(name)

    def connected_profiles(self):
        return [p.name for p in self.profiles.values()
                if p.state == State.CONNECTED]

    def active_profiles(self):
        return [p.name for p in self.profiles.values() if p.session_path]

    def session_info(self, name):
        """Return a SessionInfo for the profile's session, or None."""
        tracked = self._tracked_for(name)
        if tracked is None:
            return None
        info = SessionInfo(connected_since=self.profiles[name].connected_since)
        session = tracked.session
        try:
            info.statistics = {str(k): int(v)
                               for k, v in session.GetStatistics().items()}
        except (dbus.DBusException, RuntimeError):
            pass
        try:
            info.created = float(session.GetProperty('session_created'))
        except (dbus.DBusException, RuntimeError, TypeError, ValueError):
            pass
        try:
            info.device = str(session.GetProperty('device_name'))
        except (dbus.DBusException, RuntimeError):
            pass
        try:
            proto, addr, port = session.GetProperty('connected_to')
            if addr:
                host = '[%s]' % addr if ':' in str(addr) else str(addr)
                info.server = ('%s %s:%d' % (proto, host, int(port))).strip()
        except (dbus.DBusException, RuntimeError, TypeError, ValueError):
            pass
        return info

    def clear_log(self, name):
        self.logs.pop(name, None)

    def _log(self, name, text, level=LogLevel.INFO, source='app'):
        if not name:
            return
        entry = LogEntry(time.time(), level, text, source)
        self.logs[name].append(entry)
        self.log_message.emit(name, entry)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _tracked_for(self, name):
        prof = self.profiles.get(name)
        if prof is None or not prof.session_path:
            return None
        return self._sessions.get(prof.session_path)

    def _set_state(self, name, state, message=None):
        prof = self.profiles.get(name)
        if prof is None:
            return
        changed = prof.state != state
        if changed:
            self._log(name, state.value + (': ' + message if message else ''))
            if state == State.CONNECTED:
                prof.connected_since = time.time()
            elif state == State.DISCONNECTED:
                prof.connected_since = None
        prof.state = state
        if message is not None:
            changed = changed or prof.message != message
            prof.message = message
        if changed:
            self.profile_updated.emit(name)

    def _report(self, name, message):
        log.warning('%s: %s', name or '(backend)', message)
        self._log(name, message, LogLevel.ERROR)
        prof = self.profiles.get(name)
        if prof is not None:
            prof.message = message
            self.profile_updated.emit(name)
        self.error.emit(name, message)

    def _fail(self, tracked, message):
        """Report an error once and tear the session down."""
        if not tracked.failed:
            tracked.failed = True
            self._report(tracked.profile_name, message)
        self._untrack(str(tracked.session.GetPath()), disconnect=True,
                      keep_message=True)

    def _profile_name_for_session(self, session):
        """Work out which profile a session belongs to."""
        try:
            cfg_path = str(session.GetProperty('config_path'))
        except dbus.DBusException:
            cfg_path = None
        for prof in self.profiles.values():
            if prof.config_path == cfg_path:
                return prof.name
        try:
            return str(session.GetProperty('config_name'))
        except dbus.DBusException:
            return None

    def _track(self, session, name, owned):
        path = str(session.GetPath())
        if path in self._sessions:
            return self._sessions[path]

        tracked = _Tracked(session, name, owned)

        def on_status(major, minor, message):
            self._on_status(path, major, minor, message)

        try:
            session.StatusChangeCallback(on_status)
        except dbus.DBusException as excp:
            log.warning('Cannot follow session %s: %s', path,
                        _dbus_error_text(excp))
            if owned:
                try:
                    session.Disconnect()
                except dbus.DBusException:
                    pass
                self._report(name, 'Could not follow VPN session: %s'
                             % _dbus_error_text(excp))
            return None
        tracked.status_cb = on_status
        self._sessions[path] = tracked

        def on_log(group, category, message):
            level = LogLevel.from_category(category)
            for line in str(message).splitlines():
                if line.strip():
                    self._log(name, line, level, source='vpn')

        try:
            session.LogCallback(on_log)
            tracked.log_cb = on_log
        except (dbus.DBusException, RuntimeError) as excp:
            log.debug('No log access for %s: %s', path, excp)

        prof = self.profiles.get(name)
        if prof is not None:
            prof.session_path = path
        self._reconcile_timer.start()
        log.debug('Tracking session %s for %s (owned=%s)', path, name, owned)
        return tracked

    def _untrack(self, path, disconnect, keep_message=False):
        tracked = self._sessions.pop(path, None)
        if tracked is None:
            return
        log.debug('Untracking session %s (disconnect=%s)', path, disconnect)
        for unsubscribe in (tracked.session.StatusChangeCallback,
                            tracked.session.LogCallback):
            try:
                unsubscribe(None)
            except (dbus.DBusException, RuntimeError):
                pass
        if disconnect:
            try:
                tracked.session.Disconnect()
            except (dbus.DBusException, RuntimeError) as excp:
                log.debug('Disconnect of %s: %s', path, excp)

        prof = self.profiles.get(tracked.profile_name)
        if prof is not None and prof.session_path == path:
            prof.session_path = None
            self._set_state(prof.name, State.DISCONNECTED,
                            None if keep_message else '')
        if not self._sessions:
            self._reconcile_timer.stop()

    def _start_attempt(self, path):
        """Ask the backend if it's ready; if so, start connecting."""
        tracked = self._sessions.get(path)
        if tracked is None:
            return
        try:
            tracked.session.Ready()
        except dbus.DBusException as excp:
            text = _dbus_error_text(excp)
            if 'Missing user credentials' in text:
                self._request_input(tracked)
            elif 'not ready' in text \
                    and tracked.ready_retries < READY_MAX_RETRIES:
                tracked.ready_retries += 1
                QTimer.singleShot(READY_RETRY_MS,
                                  lambda: self._start_attempt(path))
            else:
                self._fail(tracked, text)
            return

        try:
            tracked.session.Connect()
        except dbus.DBusException as excp:
            self._fail(tracked, 'Could not connect: %s'
                       % _dbus_error_text(excp))

    def _request_input(self, tracked):
        try:
            slots = tracked.session.FetchUserInputSlots()
        except dbus.DBusException as excp:
            self._fail(tracked, 'Could not read login request: %s'
                       % _dbus_error_text(excp))
            return

        requests = []
        for slot in slots:
            atype, group = slot.GetTypeGroup()
            if atype != ClientAttentionType.CREDENTIALS:
                continue
            requests.append(InputRequest(group=group,
                                         name=str(slot.GetVariableName()),
                                         label=str(slot.GetLabel()),
                                         secret=bool(slot.GetInputMask()),
                                         slot=slot))
        if not requests:
            self._fail(tracked, 'The server asked for input this '
                       'application does not support')
            return

        log.debug('%s needs input: %s', tracked.profile_name,
                  [(r.group.name, r.name, r.label) for r in requests])
        self._log(tracked.profile_name, 'Login requested: %s'
                  % ', '.join(r.label for r in requests))
        tracked.pending_input = requests
        self._set_state(tracked.profile_name, State.AUTH_REQUIRED, '')
        self.credentials_required.emit(tracked.profile_name, requests)

    def _on_status(self, path, major, minor, message):
        tracked = self._sessions.get(path)
        if tracked is None:
            return
        try:
            major = StatusMajor(major)
            minor = StatusMinor(minor)
        except ValueError:
            log.debug('Unknown status %s/%s: %s', major, minor, message)
            return
        message = str(message)
        name = tracked.profile_name
        log.debug('[%s] status %s/%s: %s', name, major.name, minor.name,
                  message)

        if minor == StatusMinor.SESS_AUTH_URL:
            self.open_url.emit(name, message)
            return
        if minor == StatusMinor.CFG_REQUIRE_USER:
            # Typically a dynamic (CRV1) challenge after the first login
            if tracked.owned:
                self._request_input(tracked)
            return
        if minor == StatusMinor.CONN_AUTH_FAILED:
            self._fail(tracked, 'Authentication failed'
                       + (': ' + message if message else ''))
            return
        if minor == StatusMinor.CONN_FAILED:
            self._fail(tracked, 'Connection failed'
                       + (': ' + message if message else ''))
            return

        state = state_for_status(minor)
        if state == State.DISCONNECTED:
            self._untrack(path, disconnect=(minor != StatusMinor.SESS_REMOVED),
                          keep_message=tracked.failed)
        elif state is not None:
            self._set_state(name, state, message)

    def _attach_existing(self, path):
        """Start following a session we didn't create."""
        try:
            session = self._sessmgr().Retrieve(dbus.ObjectPath(path))
            owner = int(session.GetProperty('owner'))
        except (dbus.DBusException, RuntimeError) as excp:
            log.debug('Cannot inspect session %s: %s', path, excp)
            return
        if owner != self._uid:
            return
        name = self._profile_name_for_session(session)
        if name not in self.profiles:
            log.debug('Session %s has unknown profile %s', path, name)
            return
        if self.profiles[name].session_path:
            return  # already tracking another session for this profile
        if self._track(session, name, owned=False) is None:
            return
        try:
            status = session.GetStatus()
            state = state_for_status(status['minor'])
            self._set_state(name, state or State.CONNECTING,
                            str(status['message']))
            if state == State.CONNECTED:
                # We don't know when it connected; its creation is close
                prof = self.profiles[name]
                prof.connected_since = float(
                    session.GetProperty('session_created')) or \
                    prof.connected_since
        except (dbus.DBusException, RuntimeError, ValueError):
            self._set_state(name, State.CONNECTING, '')

    def _reconcile_sessions(self):
        """Sync our tracked sessions with what the session manager has."""
        try:
            live = {str(p) for p in dbus.Interface(
                self._bus.get_object(SESSIONS_BUS_NAME, SESSIONS_PATH),
                SESSIONS_BUS_NAME).FetchAvailableSessions()}
        except dbus.DBusException as excp:
            log.debug('FetchAvailableSessions failed: %s', excp)
            return
        for path in list(self._sessions):
            if path not in live:
                self._untrack(path, disconnect=False)
        for path in live - set(self._sessions):
            self._attach_existing(path)

    def _on_session_manager_event(self, path, evtype, owner):
        path = str(path)
        try:
            evtype = SessionManagerEventType(evtype)
        except ValueError:
            return
        log.debug('Session manager event %s %s (owner %s)', evtype.name,
                  path, owner)
        if evtype == SessionManagerEventType.SESS_CREATED:
            if int(owner) == self._uid and path not in self._sessions:
                # Give our own connect_profile() the chance to claim it
                QTimer.singleShot(500, lambda: self._attach_if_new(path))
        elif evtype == SessionManagerEventType.SESS_DESTROYED:
            self._untrack(path, disconnect=False)

    def _attach_if_new(self, path):
        if path not in self._sessions:
            self._attach_existing(path)
