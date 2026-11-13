"""Main application window: sidebar, stacked pages, status bar, toasts."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from termx import APP_NAME, APP_TAGLINE
from termx.core.models import AppSettings, CommandRecord, ConnectionState
from termx.ui import icons
from termx.ui.controller import AppController
from termx.ui.pages import (
    AboutPage,
    DashboardPage,
    HistoryPage,
    ModelsPage,
    SessionsPage,
    SettingsPage,
    TerminalPage,
)
from termx.ui.sidebar import Sidebar
from termx.ui.statusbar import StatusBar
from termx.ui.theme import Palette
from termx.ui.widgets.misc import fade_in, set_motion_enabled

log = logging.getLogger(__name__)

PAGE_ORDER = ("dashboard", "terminal", "history", "sessions", "models", "settings", "about")


class Toast(QFrame):
    """Transient notification shown above the status bar."""

    def __init__(self, parent: QWidget, message: str, level: str, palette: Palette) -> None:
        super().__init__(parent)
        colors = {
            "success": palette.success,
            "error": palette.danger,
            "warning": palette.warning,
            "info": palette.accent,
        }
        color = colors.get(level, palette.accent)
        icon_name = {"success": "success", "error": "error", "warning": "warning"}.get(level, "info")
        self.setObjectName("Toast")
        self.setStyleSheet(
            f"QFrame#Toast {{ background-color: {palette.elevated}; border: 1px solid {palette.border_strong};"
            f" border-left: 3px solid {color}; border-radius: 10px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 14, 9)
        layout.setSpacing(9)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap(icon_name, color, 16, 1.9))
        layout.addWidget(icon_label)
        label = QLabel(message)
        label.setStyleSheet(f"color: {palette.text}; font-size: 12px; background: transparent;")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.adjustSize()
        self.setMaximumWidth(460)


class MainWindow(QMainWindow):
    """The TermX desktop shell."""

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self._palette = Palette()
        self.setWindowTitle(f"{APP_NAME} — {APP_TAGLINE}")
        self.setWindowIcon(icons.icon("logo", "#4C8DFF", 64, 2.0))
        self.setMinimumSize(1120, 720)
        self.resize(1440, 900)
        self._toast: Toast | None = None
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)

        central = QWidget()
        central.setObjectName("Central")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(self._palette)
        self.sidebar.navigate.connect(self.navigate)
        layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Workspace")
        right_layout.addWidget(self.stack, 1)

        self.status_bar = StatusBar(self._palette)
        self.status_bar.request_settings.connect(lambda: self.navigate("settings"))
        right_layout.addWidget(self.status_bar)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

        self._build_pages()
        self._connect_controller()
        self._install_shortcuts()
        self._update_status()
        self.navigate("dashboard")

        QTimer.singleShot(300, self.controller.refresh_ai_status)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(60_000)
        self._status_timer.timeout.connect(self.controller.refresh_ai_status)
        self._status_timer.start()

    # -- construction -------------------------------------------------------
    def _build_pages(self) -> None:
        self.pages: dict[str, QWidget] = {}

        dashboard = DashboardPage(self.controller, self._palette)
        dashboard.open_terminal.connect(lambda: self.navigate("terminal"))
        dashboard.open_history.connect(lambda: self.navigate("history"))
        dashboard.open_sessions.connect(lambda: self.navigate("sessions"))
        dashboard.open_settings.connect(lambda: self.navigate("settings"))
        dashboard.open_models.connect(lambda: self.navigate("models"))
        self.pages["dashboard"] = dashboard

        terminal = TerminalPage(self.controller, self._palette)
        self.pages["terminal"] = terminal

        history = HistoryPage(self.controller, self._palette)
        history.open_in_terminal.connect(self._open_record)
        self.pages["history"] = history

        sessions = SessionsPage(self.controller, self._palette)
        sessions.open_session.connect(self._open_session)
        self.pages["sessions"] = sessions

        self.pages["models"] = ModelsPage(self.controller, self._palette)

        settings = SettingsPage(self.controller, self._palette)
        settings.settings_saved.connect(self._apply_settings)
        self.pages["settings"] = settings

        about = AboutPage(self.controller, self._palette)
        about.open_terminal.connect(lambda: self.navigate("terminal"))
        self.pages["about"] = about

        for key in PAGE_ORDER:
            self.stack.addWidget(self.pages[key])

    def _connect_controller(self) -> None:
        c = self.controller
        c.connection_changed.connect(self._on_connection)
        c.shell_changed.connect(lambda *_: self._update_status())
        c.cwd_changed.connect(lambda *_: self._update_status())
        c.settings_changed.connect(lambda *_: self._update_status())
        c.models_changed.connect(lambda *_: self._update_status())
        c.notice.connect(self.show_toast)
        c.execution_started.connect(lambda cmd: self.status_bar.set_activity(f"Running: {cmd[:70]}"))
        c.execution_finished.connect(lambda _r: self.status_bar.set_activity(""))
        c.busy_changed.connect(self._on_busy)

    def _install_shortcuts(self) -> None:
        for index, key in enumerate(PAGE_ORDER, start=1):
            QShortcut(QKeySequence(f"Ctrl+{index}"), self, activated=lambda k=key: self.navigate(k))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.controller.new_session() and self.navigate("terminal"))

    # -- navigation ---------------------------------------------------------
    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.sidebar.set_active(key)
        fade_in(page, 150)
        if hasattr(page, "on_shown"):
            try:
                page.on_shown()  # type: ignore[attr-defined]
            except Exception:
                log.exception("Page refresh failed for %s", key)
        self.status_bar.set_activity("")

    def _open_record(self, record: CommandRecord) -> None:
        self.navigate("terminal")
        self.pages["terminal"].load_from_history(record)  # type: ignore[attr-defined]

    def _open_session(self, session_id: str) -> None:
        commands = self.controller.session_commands(session_id)
        self.navigate("terminal")
        if commands:
            self.pages["terminal"].load_from_history(commands[0])  # type: ignore[attr-defined]
        else:
            self.show_toast("This session has no commands yet.", "info")

    # -- status -------------------------------------------------------------
    def _on_connection(self, state: ConnectionState, detail: str) -> None:
        self.status_bar.set_ai(state, detail)
        self.sidebar.set_ai_status(state, detail, self.controller.settings.model)
        if state is ConnectionState.OFFLINE:
            self.status_bar.set_model(self.controller.settings.model + " (offline)")
        else:
            self.status_bar.set_model(self.controller.settings.model)

    def _on_busy(self, busy: bool) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor) if busy else QApplication.restoreOverrideCursor()

    def _update_status(self) -> None:
        self.status_bar.set_shell(self.controller.shell)
        self.status_bar.set_cwd(self.controller.cwd)
        self.status_bar.set_model(self.controller.settings.model)
        self.sidebar.set_ai_status(
            self.controller.connection_state, self.controller.connection_detail, self.controller.settings.model
        )

    def _apply_settings(self, settings: AppSettings) -> None:
        set_motion_enabled(not settings.reduce_motion)
        terminal = self.pages["terminal"]
        terminal.apply_settings()  # type: ignore[attr-defined]
        self._update_status()

    # -- toasts -------------------------------------------------------------
    def show_toast(self, message: str, level: str = "info") -> None:
        self._hide_toast()
        self._toast = Toast(self, message, level, self._palette)
        self._toast.adjustSize()
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        fade_in(self._toast, 150)
        self._toast_timer.start(3400)

    def _position_toast(self) -> None:
        if not self._toast:
            return
        margin = 18
        x = self.centralWidget().width() - self._toast.width() - margin
        y = self.centralWidget().height() - self._toast.height() - 44
        self._toast.move(self.centralWidget().mapTo(self, QPoint(x, y)))

    def _hide_toast(self) -> None:
        if self._toast is not None:
            self._toast.hide()
            self._toast.setParent(None)
            self._toast = None

    # -- lifecycle ----------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_toast()

    def closeEvent(self, event) -> None:
        # Stop timers and workers before the database closes: a queued status
        # update that lands after shutdown would otherwise query a dead handle.
        self._status_timer.stop()
        self._toast_timer.stop()
        self.controller.shutdown()
        self._hide_toast()
        super().closeEvent(event)
