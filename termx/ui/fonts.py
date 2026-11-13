"""Bundled font loading with graceful fallbacks."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFontDatabase

log = logging.getLogger(__name__)

UI_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"
#: Fontconfig reports the Inter variable font under this family name.
UI_FAMILY_ALIASES = ("Inter", "Inter Variable", "Inter Display", "InterVariable")
MONO_FAMILY_ALIASES = ("JetBrains Mono", "JetBrainsMono", "JetBrains Mono NL")

_FONT_FILES = (
    "InterVariable.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf",
    "JetBrainsMono-SemiBold.ttf",
    "JetBrainsMono-Bold.ttf",
    "JetBrainsMono-Italic.ttf",
)


def assets_dir() -> Path:
    """Locate the bundled assets directory in source and frozen builds."""
    import sys

    candidates = []
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        candidates.append(Path(frozen) / "assets")
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parent.parent.parent / "assets",  # repo layout
            here.parent.parent / "assets",
            Path.cwd() / "assets",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return here.parent.parent.parent / "assets"


def load_fonts() -> tuple[str, str]:
    """Register bundled fonts; return the (ui, mono) families to use."""
    fonts_dir = assets_dir() / "fonts"
    loaded: set[str] = set()
    if fonts_dir.is_dir():
        for filename in _FONT_FILES:
            path = fonts_dir / filename
            if not path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                loaded.update(families)
                log.debug("Loaded font %s -> %s", filename, families)
    families = set(QFontDatabase.families())
    ui = next((name for name in UI_FAMILY_ALIASES if name in families), None)
    mono = next((name for name in MONO_FAMILY_ALIASES if name in families), None)
    if ui is None:
        ui = "Segoe UI" if "Segoe UI" in families else ("Sans Serif" if "Sans Serif" in families else "Sans")
    if mono is None:
        for candidate in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Monospace"):
            if candidate in families:
                mono = candidate
                break
        else:
            mono = "Monospace"
    log.info("Fonts ready — UI: %s, mono: %s (loaded %s)", ui, mono, sorted(loaded))
    return ui, mono
