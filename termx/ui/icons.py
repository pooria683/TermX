"""Vector icon system.

Icons are inline SVG strings compiled into a QIcon at runtime, so the app has
crisp, themeable icons with no binary assets and no image pipeline. Icon
colours follow the active palette; call :func:`icon` with an explicit colour
when a state (e.g. danger) matters.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 stroke paths, drawn with currentColor replaced at build time.
_PATHS: dict[str, str] = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/>'
    '<rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>',
    "terminal": '<rect x="2.5" y="4" width="19" height="16" rx="3"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M13 15h4"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 8v4.5l3 1.8"/>',
    "sessions": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18"/><path d="M8 4v16"/>',
    "models": '<path d="M12 3l3.2 6.4 7 1-5 5 1.2 7L12 19l-6.4 3.4 1.2-7-5-5 7-1z"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><circle cx="12" cy="7.6" r="0.9" fill="currentColor" stroke="none"/>',
    "play": '<path d="M7 4.5l12 7.5-12 7.5z" fill="currentColor" stroke-linejoin="round"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "copy": '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2.5"/><path d="M15.5 5.5A2.5 2.5 0 0 0 13 3H6.5A2.5 2.5 0 0 0 4 5.5V12a2.5 2.5 0 0 0 2.5 2.5"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2"/>'
    '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M10 11v6M14 11v6"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
    '<path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "chevron-right": '<path d="M9 5l7 7-7 7"/>',
    "chevron-down": '<path d="M5 9l7 7 7-7"/>',
    "chevron-left": '<path d="M15 5l-7 7 7 7"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.2a2 2 0 0 1 1.6.8l1 1.4a2 2 0 0 0 1.6.8h5.6A2.5 2.5 0 0 1 21 10.5v6A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    "zap": '<path d="M13 2L4.5 13.5H11l-1 8.5 9-12h-6.5z"/>',
    "shield": '<path d="M12 3l7.5 3v5.4c0 4.4-3 8.1-7.5 9.6-4.5-1.5-7.5-5.2-7.5-9.6V6z"/><path d="M9 12l2 2 4-4"/>',
    "warning": '<path d="M12 4.5L21 19H3z"/><path d="M12 10v4"/><circle cx="12" cy="16.6" r="0.9" fill="currentColor" stroke="none"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "success": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/>',
    "star": '<path d="M12 3.5l2.7 5.6 6.1.9-4.4 4.3 1 6-5.4-2.9-5.4 2.9 1-6L3.2 10l6.1-.9z"/>',
    "star-filled": '<path d="M12 3.5l2.7 5.6 6.1.9-4.4 4.3 1 6-5.4-2.9-5.4 2.9 1-6L3.2 10l6.1-.9z" fill="currentColor"/>',
    "download": '<path d="M12 4v10"/><path d="M8 11l4 4 4-4"/><path d="M4.5 18.5h15"/>',
    "upload": '<path d="M12 16V6"/><path d="M8 9l4-4 4 4"/><path d="M4.5 18.5h15"/>',
    "cwd": '<path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z"/><path d="M8 10h8M8 14h5"/>',
    "cpu": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3"/>',
    "bolt": '<path d="M11 2.5L5 13h5l-1 8.5L19 10h-6z"/>',
    "brain": '<path d="M9.5 4.5A2.7 2.7 0 0 1 12 6.2a2.7 2.7 0 0 1 2.5-1.7 2.8 2.8 0 0 1 2.8 2.8c1.4.4 2.2 1.6 2.2 3a2.9 2.9 0 0 1-1.4 2.5 3 3 0 0 1-1.8 4.9A2.7 2.7 0 0 1 12 19.5a2.7 2.7 0 0 1-4.3-1.8 3 3 0 0 1-1.8-4.9 2.9 2.9 0 0 1-1.4-2.5c0-1.4.8-2.6 2.2-3a2.8 2.8 0 0 1 2.8-2.8z"/>',
    "logo": '<path d="M4 5.5h16" stroke-linecap="round"/><path d="M8 10.5l3 2.5-3 2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M13 15.5h4" stroke-linecap="round"/>',
    "github": '<path d="M9 19.5c-4 1.2-4-2.2-5.5-2.8m11 5.3v-3.4a3 3 0 0 0-.9-2.4c3-.3 5.4-1.5 5.4-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12 12 0 0 0-6.2 0C5.5 3.2 4.4 3.5 4.4 3.5a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 3 9.9c0 4.5 2.4 5.7 5.4 6a3 3 0 0 0-.9 2.4v3.4"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4L10.5 13.5"/><path d="M18 14.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5"/>',
    "filter": '<path d="M4 5h16l-6.5 7.5V20l-3-2v-5.5z"/>',
    "database": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>',
    "code": '<path d="M9 7l-5 5 5 5"/><path d="M15 7l5 5-5 5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "send": '<path d="M21 3L10.5 13.5"/><path d="M21 3l-6.8 18-3.7-7.5L3 9.8z"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M6.5 14h11"/>',
    "book": '<path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H20v18H7.5A2.5 2.5 0 0 0 5 22z"/><path d="M5 17.5h15"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "activity": '<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>',
    "edit": '<path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M14.5 5.5l4 4"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M8 3v5h7V3"/><rect x="7" y="13" width="10" height="7"/>',
    "lightning": '<path d="M12 2v5M12 17v5M2 12h5M17 12h5M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/>',
}

FILLED = {"play", "stop", "logo", "bolt", "star-filled", "warning", "sparkles", "send"}

COLOR_KEYS = ("color",)


def svg_markup(name: str, color: str, size: int = 24, stroke_width: float = 1.8) -> str:
    path = _PATHS.get(name, _PATHS["info"])
    fill = "currentColor" if name in FILLED else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}">'
        f'<g fill="{fill}" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round" style="color:{color}">{path}</g>'
        f"</svg>"
    )


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 24, stroke_width: float = 1.8) -> QPixmap:
    """Render an icon to a pixmap at 2x for crisp HiDPI display."""
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color, size, stroke_width).encode()))
    scale = 2
    pm = QPixmap(QSize(size * scale, size * scale))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#E8ECF4", size: int = 20, stroke_width: float = 1.8) -> QIcon:
    """Return a cached QIcon for ``name`` tinted with ``color``."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size, stroke_width), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(
        pixmap(name, color if color != "#E8ECF4" else "#FFFFFF", size, stroke_width),
        QIcon.Mode.Active,
        QIcon.State.Off,
    )
    return result


def has_icon(name: str) -> bool:
    return name in _PATHS


def available_icons() -> list[str]:
    return sorted(_PATHS)
