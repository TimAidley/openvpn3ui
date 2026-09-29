# openvpn3ui

A small system tray client for [OpenVPN3 Linux](https://github.com/OpenVPN/openvpn3-linux),
written in Python and PyQt6. It is built for KDE Plasma but works on any desktop
with a StatusNotifier tray.

- Connect and disconnect profiles from the tray menu or the main window.
- The tray icon shows the state: grey is disconnected, amber is connecting, green is connected.
- The login dialog is built from what the server asks for, so username/password,
  OTP and follow-up MFA challenges all work. Web logins open in your browser.
- Remembers your username for each profile. Passwords and codes are never stored.
- Import `.ovpn` files and remove profiles.
- Optionally starts at login, in the tray, and connects a chosen profile at startup.
- Connection details for the selected profile: server, tunnel address, time connected,
  and data received/sent with live speed.
- A live log viewer for each profile that you can save to a file.
- Picks up sessions started with the `openvpn3` command.

It talks to the OpenVPN3 services over D-Bus using the `openvpn3` Python module
that comes with OpenVPN3. It never parses command output.

## Requirements

Debian 13 (or similar) with:

```
sudo apt install openvpn3 python3-pyqt6 python3-dbus
```

## Install

```
./install.sh               # installs to ~/.local
./install.sh --uninstall
```

Then start **OpenVPN3 UI** from the application launcher. To start it at login,
turn on **Settings ▸ Start at Login** in the main window. To connect automatically
when the app starts, pick a profile under **Settings ▸ Connect at Startup**. If the
profile needs a one-time code, the login dialog pops up.

## Development

```
python3 -m openvpn3ui --debug          # run from the source tree
python3 -m unittest discover -s tests  # run the tests
tools/try_connect.py --list            # terminal test of the backend
tools/try_connect.py PROFILE --probe   # show the login fields, don't connect
tools/try_connect.py PROFILE           # connect from the terminal; Ctrl-C disconnects
```

Layout:

| File | Purpose |
| --- | --- |
| `openvpn3ui/backend.py` | OpenVPN3 D-Bus wrapper and session state (Qt signals) |
| `openvpn3ui/app.py` | Controller: connects the backend to the tray, window and dialogs |
| `openvpn3ui/tray.py` | Tray icon and menu |
| `openvpn3ui/main_window.py` | Profile list, connection details, import/remove, settings |
| `openvpn3ui/log_window.py` | Live log viewer |
| `openvpn3ui/formatting.py` | Byte, rate and duration formatting |
| `openvpn3ui/auth_dialog.py` | Login dialog |
| `openvpn3ui/settings.py` | Remembered usernames, autostart entry |
| `openvpn3ui/icons.py` | Status icons |

## Licence

Copyright (C) 2026 Tim Aidley

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software Foundation,
either version 2 of the License, or (at your option) any later version. See
[LICENSE](LICENSE) for the full text.

Because it uses PyQt6 (GPL-3.0) and the `openvpn3` Python module (AGPL-3.0), the app
as a whole can in practice only be distributed under GPL-3.0.
