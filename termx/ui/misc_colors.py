"""Colour helpers shared by widgets.

Two flavours are provided:

* :func:`with_alpha` / :func:`mix` return CSS strings for stylesheets;
* :func:`qcolor` / :func:`qmix` return real ``QColor`` objects for painting.

Keeping them separate avoids the classic bug of passing an ``rgba(...)`` CSS
string to ``QColor``, which silently produces an invalid (transparent) colour.
"""

from __future__ import annotations

from PySide6.QtGui import QColor


def _parse_hex(color: str) -> tuple[int, int, int] | None:
    value = (color or "").strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return None


def with_alpha(color: str, alpha: float) -> str:
    """Return a CSS ``rgba(...)`` string for a hex colour with the given opacity."""
    alpha = max(0.0, min(1.0, alpha))
    rgb = _parse_hex(color)
    if rgb is not None:
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha:.2f})"
    value = color.strip()
    if value.startswith("rgb("):
        return f"rgba({value[4:-1]}, {alpha:.2f})"
    if value.startswith("rgba("):
        body = value[5:-1].split(",")[:3]
        return f"rgba({','.join(body)}, {alpha:.2f})"
    return color


def qcolor(color: str, alpha: float = 1.0) -> QColor:
    """Build a QColor from any CSS-ish colour string, honouring ``alpha``."""
    alpha = max(0.0, min(1.0, alpha))
    value = (color or "").strip()
    if value in ("", "transparent", "none"):
        return QColor(0, 0, 0, 0)
    result = QColor()
    if value.startswith("rgba("):
        parts = [p.strip() for p in value[5:-1].split(",")]
        if len(parts) >= 3:
            try:
                result = QColor(int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
                base_alpha = float(parts[3]) if len(parts) > 3 else 1.0
                result.setAlphaF(max(0.0, min(1.0, base_alpha * alpha)))
                return result
            except ValueError:
                return QColor(0, 0, 0, 0)
    elif value.startswith("rgb("):
        parts = [p.strip() for p in value[4:-1].split(",")]
        if len(parts) >= 3:
            try:
                result = QColor(int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
                result.setAlphaF(alpha)
                return result
            except ValueError:
                return QColor(0, 0, 0, 0)
    rgb = _parse_hex(value)
    if rgb is not None:
        result = QColor(*rgb)
        result.setAlphaF(alpha)
        return result
    fallback = QColor(value)
    if fallback.isValid():
        fallback.setAlphaF(alpha)
        return fallback
    return QColor(0, 0, 0, 0)


def mix(color_a: str, color_b: str, ratio: float = 0.5) -> str:
    """Blend two hex colours (ratio 0 -> a, 1 -> b) and return a hex string."""
    ratio = max(0.0, min(1.0, ratio))
    first, second = _parse_hex(color_a), _parse_hex(color_b)
    if first is None or second is None:
        return color_a
    mixed = tuple(round(a + (b - a) * ratio) for a, b in zip(first, second, strict=True))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def qmix(color_a: str, color_b: str, ratio: float = 0.5) -> QColor:
    """Same as :func:`mix` but returns a QColor."""
    return qcolor(mix(color_a, color_b, ratio))


def luminance(color: str) -> float:
    """Relative luminance, used to pick readable foreground colours."""
    rgb = _parse_hex(color)
    if rgb is None:
        return 0.0
    r, g, b = (c / 255 for c in rgb)

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
