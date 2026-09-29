# openvpn3ui — plan

A KDE Plasma tray application and main window for OpenVPN3 on Debian 13.

## Environment
- Debian 13, KDE Plasma on Wayland
- OpenVPN3/Linux v27.1: services on the system D-Bus (`net.openvpn.v3.*`)
- Python 3.13, PyQt6 (`python3-pyqt6`), the official `openvpn3` Python module
  (`/usr/lib/python3/dist-packages/openvpn3`)
- Profiles: `work` and `work-split`, both `auth-user-pass`, with no `static-challenge` directive

## Decisions
- **Stack:** Python and PyQt6. Talk to OpenVPN3 over D-Bus through the `openvpn3` module; never parse CLI output.
- **UI:** a tray icon with a menu, plus a main window (profiles, status, connect/disconnect).
- **Auth:** the user enters a username and an OTP/MFA code. Store the username only, per
  profile, in the app's settings (QSettings). Always prompt for the code and never persist it.
- **v1 extras:** autostart at login, and importing/removing `.ovpn` profiles.
- **Later:** a live log viewer, connection stats, and auto-connect.

## Layout
```
openvpn3ui/
  openvpn3ui/
    __main__.py      # entry point, single-instance guard
    backend.py       # OpenVPN3 D-Bus wrapper (QObject, emits Qt signals)
    tray.py          # QSystemTrayIcon + menu
    main_window.py   # profile list, status, connect/disconnect, import/remove
    auth_dialog.py   # username (prefilled) + OTP/password prompt; handles dynamic challenges
    settings.py      # QSettings: remembered usernames, autostart flag
    autostart.py     # manage ~/.config/autostart/openvpn3ui.desktop
  data/              # .desktop file, icons (disconnected/connecting/connected/error)
  pyproject.toml
```

## Milestones
1. **Backend spike.** From a script: list configs, start a session, answer the
   user-input requests (username/password and any dynamic challenge), then track status
   signals through to CONNECTED, then disconnect. Find out exactly what the MFA prompt
   looks like (whether the OTP goes in the password field or arrives as a CRV1 dynamic
   challenge).
2. **Tray MVP.**
   - The icon shows the state.
   - The menu has Connect ▸ <profile>, Disconnect, Open window and Quit.
   - A notification fires on connect, disconnect or failure.
3. **Auth dialog.**
   - The username is prefilled from settings and the OTP field has focus.
   - A clear error appears on auth failure, with a retry.
4. **Main window.**
   - A profile list with state, and connect/disconnect buttons.
   - Import `.ovpn` (file picker; use persistent import like `config-import --persistent`) and remove a profile.
   - Settings: autostart on/off.
5. **Robustness.**
   - Pick up sessions that already exist (started from the CLI, or before the app launched).
   - Handle reconnect/pause states, the service restarting, and a stale or duplicate session for a profile.
6. **Packaging.** Add a `.desktop` launcher, an autostart entry, and install with `pipx` or a simple `.deb`.

## Open questions / risks
- The exact shape of the MFA prompt (milestone 1 answers this).
- The D-Bus policy must allow the user to start and stop sessions. It already works from the CLI, so this is expected to be fine.
