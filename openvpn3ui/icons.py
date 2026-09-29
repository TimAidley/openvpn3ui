"""Status icons: a shield filled with the status colour and a white glyph.

The icons are drawn entirely by us rather than decorating a theme icon, so
they stay legible on both dark and light panels (Plasma can't recolour the
pixmaps a tray icon sends).
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                         QPixmap)

from .backend import State

COLOURS = {
    'connected': QColor('#27ae60'),
    'busy': QColor('#f39c12'),
    'disconnected': QColor('#7f8c8d'),
}
GLYPH_COLOUR = QColor('#ffffff')

_SIZES = (16, 20, 22, 24, 32, 44, 48, 64, 96)
_cache = {}


def app_icon():
    icon = QIcon.fromTheme('network-vpn')
    if icon.isNull():
        icon = status_icon('connected')
    return icon


def status_kind(states):
    """Reduce the states of all profiles to one indicator."""
    states = list(states)
    if any(s == State.CONNECTED for s in states):
        return 'connected'
    if any(s.busy or s == State.PAUSED for s in states):
        return 'busy'
    return 'disconnected'


def _shield(u):
    """Shield outline on a 16x16 grid scaled by u."""
    path = QPainterPath()
    path.moveTo(8 * u, 0.6 * u)
    path.cubicTo(10 * u, 1.8 * u, 12.5 * u, 2.4 * u, 14.6 * u, 2.4 * u)
    path.cubicTo(14.6 * u, 9.6 * u, 12 * u, 13.4 * u, 8 * u, 15.4 * u)
    path.cubicTo(4 * u, 13.4 * u, 1.4 * u, 9.6 * u, 1.4 * u, 2.4 * u)
    path.cubicTo(3.5 * u, 2.4 * u, 6 * u, 1.8 * u, 8 * u, 0.6 * u)
    path.closeSubpath()
    return path


def _padlock(p, u, locked):
    # Body
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(GLYPH_COLOUR)
    p.drawRoundedRect(QRectF(5.2 * u, 7.2 * u, 5.6 * u, 4.6 * u),
                      0.7 * u, 0.7 * u)
    # Shackle; when unlocked it is raised and the right leg is free
    lift = 0 if locked else 1.3 * u
    left, right, top = 6.3 * u, 9.7 * u, 3.7 * u - lift
    shackle = QPainterPath()
    shackle.moveTo(left, 7.4 * u)
    shackle.lineTo(left, top + 1.7 * u)
    shackle.arcTo(QRectF(left, top, right - left, right - left), 180, -180)
    shackle.lineTo(right, 7.4 * u if locked else top + 3.0 * u)
    pen = QPen(GLYPH_COLOUR, 1.35 * u)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(shackle)


def _dots(p, u):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(GLYPH_COLOUR)
    r = 1.15 * u
    for x in (5.1, 8.0, 10.9):
        p.drawEllipse(QPointF(x * u, 7.6 * u), r, r)


def draw_status(p, size, kind):
    u = size / 16.0
    colour = COLOURS[kind]
    shield = _shield(u)
    # A darker rim separates the shield from light panels
    p.setPen(QPen(colour.darker(150), max(1.0, 0.8 * u)))
    p.setBrush(colour)
    p.drawPath(shield)
    if kind == 'busy':
        _dots(p, u)
    else:
        _padlock(p, u, locked=(kind == 'connected'))


def status_icon(kind):
    if kind in _cache:
        return _cache[kind]
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_status(p, size, kind)
        p.end()
        icon.addPixmap(pm)
    _cache[kind] = icon
    return icon
