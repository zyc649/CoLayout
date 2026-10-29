"""Small native SVG line icons; no downloaded assets or runtime dependencies."""
from PySide6.QtCore import QByteArray,Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter
from PySide6.QtSvg import QSvgRenderer

_PATHS={
    'rectangle':'<rect x="3" y="5" width="18" height="14"/>',
    'route':'<path d="M3 6h7v12h11M3 18h4V6h14"/><circle cx="3" cy="6" r="1.5"/><circle cx="21" cy="18" r="1.5"/>',
    'open':'<path d="M3 7V4h7l2 3h9v13H3Z"/><path d="M3 11h18"/>',
    'save':'<path d="M4 3h13l4 4v14H3V3Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    'import':'<path d="M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6"/>',
    'sync':'<path d="M5 8a8 8 0 0 1 13-3l3 3M21 3v5h-5M19 16A8 8 0 0 1 6 19l-3-3M3 21v-5h5"/>',
    'undo':'<path d="M4 8h10a6 6 0 0 1 0 12h-4M8 3 3 8l5 5"/>',
    'redo':'<path d="M20 8H10a6 6 0 0 0 0 12h4M16 3l5 5-5 5"/>',
    'region':'<rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="3 2"/><path d="M8 12h8m-4-4v8"/>',
    'markup':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h10m-10 4h6"/>',
    'keepout':'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m5 19 14-14M3 11l8-8m2 18 8-8"/>',
    'fit':'<path d="M3 9V3h6m6 0h6v6m0 6v6h-6m-6 0H3v-6"/><rect x="7" y="7" width="10" height="10" rx="1"/>',
    'up':'<path d="M12 21V4m-7 7 7-7 7 7"/>',
    'rotate':'<path d="M4 8a9 9 0 1 1 0 8M4 3v5h5"/><rect x="10" y="9" width="7" height="7"/>',
    'mirror':'<path d="M12 2v20M3 6h5v12H3Zm18 0h-5v12h5Z"/>',
    'check':'<path d="m4 12 5 5L20 5"/>',
    'circuit':'<path d="M3 5h6v6h6v8h6M3 19h4V5m8 6V5h6"/><circle cx="15" cy="11" r="1.5"/>',
    'settings':'<path d="M4 6h16M4 12h16M4 18h16"/><rect x="7" y="4" width="3" height="4"/><rect x="14" y="10" width="3" height="4"/><rect x="9" y="16" width="3" height="4"/>',
    'delete':'<path d="M3 6h18M9 3h6m-10 3 1 15h12l1-15M10 10v7m4-7v7"/>',
    'copy':'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 5V3H3v13h2"/>',
    'inspect':'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    'panels':'<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M15 4v16"/>',
    'hierarchy':'<path d="M5 4v14h6M5 9h6"/><rect x="11" y="6" width="9" height="6" rx="1"/><rect x="11" y="15" width="9" height="6" rx="1"/>',
    'more':'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    'close':'<path d="m6 6 12 12M18 6 6 18"/>',
    'back':'<path d="M20 12H4m7-7-7 7 7 7"/>',
}
_CACHE={}


def icon(name,color='#536270',*,angle=0,active=False):
    key=(name,color,angle,active)
    if key not in _CACHE:
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</g></svg>'
        pixmap=QPixmap(48,48);pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pixmap)
        if angle or name=='sync':
            painter.translate(24,24);painter.rotate(angle)
            if name=='sync':painter.scale(.88,.88)  # Same inset at rest/in motion; arrow corners never clip.
            painter.translate(-24,-24)
        QSvgRenderer(QByteArray(svg.encode())).render(painter);painter.end();pixmap.setDevicePixelRatio(2)
        _CACHE[key]=QIcon(pixmap)
        if angle or active:_CACHE[key].addPixmap(pixmap,QIcon.Mode.Disabled)
    return _CACHE[key]
