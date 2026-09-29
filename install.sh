#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley
# Install openvpn3ui for the current user (default prefix: ~/.local).
#
#   ./install.sh              install or upgrade
#   ./install.sh --uninstall  remove it again
set -eu

PREFIX="${PREFIX:-$HOME/.local}"
BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/share/openvpn3ui"
APPDIR="$PREFIX/share/applications"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/openvpn3ui.desktop"
SRC="$(cd "$(dirname "$0")" && pwd)"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$LIBDIR" "$BINDIR/openvpn3ui" "$APPDIR/openvpn3ui.desktop" \
           "$AUTOSTART"
    echo "Uninstalled openvpn3ui (settings in ~/.config/openvpn3ui kept)."
    exit 0
fi

if ! /usr/bin/python3 -c 'import PyQt6.QtWidgets, dbus, openvpn3' 2>/dev/null
then
    echo "Missing dependencies. Install them with:" >&2
    echo "  sudo apt install python3-pyqt6 python3-dbus openvpn3" >&2
    exit 1
fi

mkdir -p "$BINDIR" "$LIBDIR" "$APPDIR"
rm -rf "$LIBDIR/openvpn3ui"
cp -r "$SRC/openvpn3ui" "$LIBDIR/"
find "$LIBDIR" -name __pycache__ -type d -prune -exec rm -rf {} +

cat > "$BINDIR/openvpn3ui" <<WRAPPER
#!/bin/sh
PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}" exec /usr/bin/python3 -m openvpn3ui "\$@"
WRAPPER
chmod 755 "$BINDIR/openvpn3ui"

sed "s|@BINDIR@|$BINDIR|" "$SRC/data/openvpn3ui.desktop" \
    > "$APPDIR/openvpn3ui.desktop"

# Point an existing autostart entry at the installed copy
if [ -f "$AUTOSTART" ]; then
    sed -i "s|^Exec=.*|Exec=$BINDIR/openvpn3ui --hidden|" "$AUTOSTART"
fi

command -v update-desktop-database >/dev/null && \
    update-desktop-database -q "$APPDIR" || true

echo "Installed openvpn3ui to $BINDIR/openvpn3ui"
echo "Start it from the application launcher or run: openvpn3ui"
