"""Status icons: the theme's VPN icon with a coloured status badge."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .backend import State

COLOURS = {
    'connected': QColor('#27ae60'),
    'busy': QColor('#f39c12'),
    'disconnected': QColor('#7f8c8d'),
}

_SIZES = (16, 22, 24, 32, 48, 64)
_cache = {}


def app_icon():
    icon = QIcon.fromTheme('network-vpn')
    if icon.isNull():
        icon = _drawn_shield()
    return icon


def _drawn_shield():
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 16.0
        path = QPainterPath()
        path.moveTo(8 * s, 1 * s)
        path.lineTo(14 * s, 3.5 * s)
        path.cubicTo(14 * s, 10 * s, 11 * s, 13.5 * s, 8 * s, 15 * s)
        path.cubicTo(5 * s, 13.5 * s, 2 * s, 10 * s, 2 * s, 3.5 * s)
        path.closeSubpath()
        p.setPen(QPen(QColor('#232629'), max(1.0, s)))
        p.setBrush(QColor('#3daee9'))
        p.drawPath(path)
        p.end()
        icon.addPixmap(pm)
    return icon


def status_kind(states):
    """Reduce the states of all profiles to one indicator."""
    states = list(states)
    if any(s == State.CONNECTED for s in states):
        return 'connected'
    if any(s.busy or s == State.PAUSED for s in states):
        return 'busy'
    return 'disconnected'


def status_icon(kind):
    if kind in _cache:
        return _cache[kind]
    base = app_icon()
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base.paint(p, 0, 0, size, size)
        r = size * 0.22
        centre = QPointF(size - r - 0.5, size - r - 0.5)
        p.setPen(QPen(QColor('#fcfcfc'), max(1.0, size / 16.0)))
        p.setBrush(COLOURS[kind])
        p.drawEllipse(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r))
        p.end()
        icon.addPixmap(pm)
    _cache[kind] = icon
    return icon
