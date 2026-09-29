#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley
"""Exercise the openvpn3ui backend from a terminal.

    tools/try_connect.py --list
    tools/try_connect.py PROFILE --probe   # stop at the login prompt
    tools/try_connect.py PROFILE           # connect; Ctrl-C disconnects
"""

import argparse
import getpass
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import dbus.mainloop.glib                                      # noqa: E402
from PyQt6.QtCore import QCoreApplication, QTimer              # noqa: E402

from openvpn3ui.backend import State, VpnBackend               # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('profile', nargs='?')
    ap.add_argument('--list', action='store_true', help='list profiles')
    ap.add_argument('--probe', action='store_true',
                    help='show what the login prompt asks for, then abort '
                    'without contacting the server')
    ap.add_argument('--debug', action='store_true')
    args = ap.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = QCoreApplication(sys.argv)
    backend = VpnBackend()
    backend.refresh()

    if args.list or not args.profile:
        for prof in backend.profiles.values():
            print('%-30s %s %s' % (prof.name, prof.state.value, prof.message))
        return 0
    if args.profile not in backend.profiles:
        print('Unknown profile %r' % args.profile, file=sys.stderr)
        return 1

    result = {'code': 0}
    was_connected = [False]

    def on_update(name):
        prof = backend.profiles[name]
        print('>>> %s: %s %s' % (name, prof.state.value, prof.message))
        if prof.state == State.CONNECTED and not was_connected[0]:
            was_connected[0] = True
            print('>>> Connected. Press Ctrl-C to disconnect.')
        if prof.state == State.DISCONNECTED:
            app.quit()

    def on_credentials(name, requests):
        print('>>> Login requested with %d field(s):' % len(requests))
        for req in requests:
            print('      group=%s name=%r label=%r secret=%s'
                  % (req.group.name, req.name, req.label, req.secret))
        if args.probe:
            print('>>> Probe only: aborting without contacting the server')
            backend.cancel_credentials(name)
            return
        values = {}
        for req in requests:
            ask = getpass.getpass if req.secret else input
            values[req.name] = ask('%s: ' % req.label)
        backend.provide_credentials(name, values)

    def on_error(name, message):
        print('!!! %s: %s' % (name, message))
        result['code'] = 2

    def on_url(name, url):
        print('>>> Web authentication required: %s' % url)

    backend.profile_updated.connect(on_update)
    backend.credentials_required.connect(on_credentials)
    backend.error.connect(on_error)
    backend.open_url.connect(on_url)

    def on_sigint(*_):
        print('\n>>> Disconnecting')
        backend.disconnect_profile(args.profile)
        app.quit()
    signal.signal(signal.SIGINT, on_sigint)
    # Let the Python interpreter run periodically so Ctrl-C is noticed
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)

    QTimer.singleShot(0, lambda: backend.connect_profile(args.profile))
    app.exec()
    return result['code']


if __name__ == '__main__':
    sys.exit(main())
