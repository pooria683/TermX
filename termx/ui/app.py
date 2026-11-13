"""Qt application bootstrap: fonts, theme, logging, and main window."""

from __future__ import annotations

import gc
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from termx import APP_NAME, APP_VERSION, ORGANIZATION, get_user_data_dir
from termx.ui import icons
from termx.ui.fonts import load_fonts
from termx.ui.theme import DARK, ThemeManager
from termx.ui.widgets.misc import set_motion_enabled

log = logging.getLogger(__name__)


def configure_logging(level: int = logging.INFO) -> Path:
    """Log to stderr and to a rotating file in the user data directory."""
    log_dir = get_user_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "termx.log"

    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(file_handler)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(stream)
    return log_file


def app_icon() -> QIcon:
    """Multi-resolution window icon drawn from the vector logo."""
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#121722"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, size * 0.24, size * 0.24)
        painter.end()
        logo = icons.pixmap("logo", "#4C8DFF", size, max(1.6, size / 12))
        painter = QPainter(pix)
        painter.drawPixmap(0, 0, logo)
        painter.end()
        result.addPixmap(pix)
    return result


def create_application(argv: list[str] | None = None) -> tuple[QApplication, ThemeManager]:
    """Create and configure the QApplication (idempotent)."""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)
    app.setDesktopFileName("termx")

    ui_family, mono_family = load_fonts()
    palette = DARK
    palette = type(palette)(**{**palette.__dict__, "font_ui": ui_family, "font_mono": mono_family})
    theme = ThemeManager(palette=palette)

    base_font = QFont(ui_family, 10)
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base_font)
    app.setStyleSheet(theme.app_stylesheet())
    app.setWindowIcon(app_icon())
    set_motion_enabled(True)
    return app, theme


def run(argv: list[str] | None = None) -> int:
    """Start the full TermX GUI.

    Teardown is explicit and ordered on purpose: widgets are destroyed and the
    controller is shut down *before* the interpreter finalises. Leaving live Qt
    objects, timers or threads to be collected during interpreter shutdown is
    what produces the ``Fatal Python error: none_dealloc`` aborts seen when a
    PySide6 app exits without unwinding its object graph.
    """
    configure_logging()
    app, theme = create_application(argv)

    # Imported here so logging is configured first.
    from termx.ui.controller import AppController
    from termx.ui.main_window import MainWindow

    controller = AppController()
    set_motion_enabled(not controller.settings.reduce_motion)
    window = MainWindow(controller)
    window.show()
    log.info("TermX %s started on %s", APP_VERSION, sys.platform)

    try:
        return app.exec()
    finally:
        shutdown_application(app, window, controller)
        del window
        del controller
        del theme
        gc.collect()
        app.processEvents()
        log.info("TermX shut down cleanly")


def shutdown_application(app: QApplication, window, controller) -> None:
    """Wind the app down in a deterministic order."""
    try:
        window.close()
        window.deleteLater()
        app.processEvents()
    except Exception:  # pragma: no cover - defensive during exit
        log.exception("Error while closing the main window")
    try:
        controller.shutdown()
        app.processEvents()
    except Exception:  # pragma: no cover - defensive during exit
        log.exception("Error while shutting the controller down")
