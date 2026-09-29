# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Entry point: python3 -m openvpn3ui"""

import argparse
import logging
import os
import signal
import sys

import dbus
import dbus.mainloop.glib
from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME, __version__
from .icons import app_icon

SERVER_NAME = '%s-%d' % (APP_ID, os.getuid())


def _signal_running_instance():
    """Ask an already running instance to show itself.  True if found."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(b'show\n')
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog=APP_ID, description=APP_NAME)
    ap.add_argument('--hidden', action='store_true',
                    help='start in the system tray without showing the window')
    ap.add_argument('--debug', action='store_true', help='verbose logging')
    ap.add_argument('--version', action='version', version=__version__)
    args, qt_args = ap.parse_known_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s '
                        '%(message)s')

    # Must happen before any D-Bus connection is opened; Qt's GLib event
    # dispatcher then delivers D-Bus signals for us.
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    if _signal_running_instance():
        logging.info('Already running; asked it to show its window')
        return 0

    # Imported late so the D-Bus main loop is set up first
    from .app import Controller
    from .backend import VpnBackend

    try:
        backend = VpnBackend()
    except dbus.DBusException as excp:
        QMessageBox.critical(None, APP_NAME,
                             'Could not connect to the system D-Bus:\n%s'
                             % excp)
        return 1

    controller = Controller(backend, start_hidden=args.hidden)

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_new_connection():
        conn = server.nextPendingConnection()
        conn.readyRead.connect(lambda: (conn.readAll(),
                                        controller.show_window()))
        conn.disconnected.connect(conn.deleteLater)
    server.newConnection.connect(on_new_connection)

    # Quit cleanly (leaving VPN sessions alone) on Ctrl-C / SIGTERM
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(250)

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
