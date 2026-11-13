"""Bottom status bar: shell, working directory, AI state, model, version."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from termx import APP_VERSION
from termx.core.models import ConnectionState, ShellType
from termx.ui import icons
from termx.ui.theme import Palette
from termx.ui.widgets.badges import StatusDot
from termx.ui.widgets.misc import ElidedLabel, VDivider


class _Segment(QWidget):
    """Icon + value pair inside the status bar."""

    def __init__(
        self,
        icon_name: str,
        palette: Palette,
        text: str = "",
        tooltip: str = "",
        mono: bool = False,
    ) -> None:
        super().__init__()
        self._palette = palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._icon = QLabel()
        self._icon.setPixmap(icons.pixmap(icon_name, palette.text_dim, 13, 1.9))
        layout.addWidget(self._icon)
        self._label = ElidedLabel(text)
        self._label.setStyleSheet(
            f"color: {palette.text_muted}; font-size: 11px; font-weight: 600;"
            + (f' font-family: "{palette.font_mono}", Consolas, monospace;' if mono else "")
        )
        if tooltip:
            self.setToolTip(tooltip)
        layout.addWidget(self._label)

    def set_text(self, text: str, tooltip: str = "") -> None:
        self._label.setText(text)
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon(self, name: str, color: str | None = None) -> None:
        self._icon.setPixmap(icons.pixmap(name, color or self._palette.text_dim, 13, 1.9))


class StatusBar(QFrame):
    """Persistent application status strip."""

    request_settings = Signal()

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setObjectName("StatusBar")
        self.setFixedHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 12, 0)
        layout.setSpacing(12)

        self._shell = _Segment("code", self._palette, "PowerShell", "Active shell — click to change")
        self._shell.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._shell)

        layout.addWidget(VDivider())

        self._cwd = _Segment("cwd", self._palette, "~", "Current working directory", mono=True)
        self._cwd.setMaximumWidth(420)
        layout.addWidget(self._cwd, 1)

        layout.addWidget(VDivider())

        self._ai_dot = StatusDot(self._palette.text_dim, 7)
        layout.addWidget(self._ai_dot)
        self._ai = QLabel("AI offline")
        self._ai.setStyleSheet(f"color: {self._palette.text_muted}; font-size: 11px; font-weight: 600;")
        layout.addWidget(self._ai)

        layout.addWidget(VDivider())

        self._model = _Segment("brain", self._palette, "No model", "Selected Ollama model")
        self._model.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._model)

        layout.addWidget(VDivider())

        self._command = QLabel("")
        self._command.setStyleSheet(f"color: {self._palette.text_faint}; font-size: 11px;")
        layout.addWidget(self._command, 1)

        version = QLabel(f"TermX v{APP_VERSION}")
        version.setStyleSheet(f"color: {self._palette.text_faint}; font-size: 11px; font-weight: 600;")
        layout.addWidget(version)

    # -- updates ------------------------------------------------------------
    def set_shell(self, shell: ShellType) -> None:
        self._shell.set_text(shell.label, f"Active shell: {shell.label}")

    def set_cwd(self, cwd: str) -> None:
        display = cwd
        home = str(__import__("pathlib").Path.home())
        if display.startswith(home):
            display = "~" + display[len(home) :]
        self._cwd.set_text(display, cwd)

    def set_ai(self, state: ConnectionState, detail: str) -> None:
        self._ai_dot.set_color(state.color)
        self._ai.setText(state.label)
        self._ai.setStyleSheet(f"color: {state.color}; font-size: 11px; font-weight: 600;")
        self._ai.setToolTip(detail)
        self.setToolTip(detail)

    def set_model(self, model: str) -> None:
        self._model.set_text(model or "No model", f"Model: {model}")

    def set_activity(self, text: str) -> None:
        self._command.setText(text)
