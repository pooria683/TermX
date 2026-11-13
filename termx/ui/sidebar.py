"""Left navigation sidebar with brand header and AI status card."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx import APP_VERSION
from termx.core.models import ConnectionState
from termx.ui import icons
from termx.ui.theme import Palette
from termx.ui.widgets.badges import StatusDot


class NavButton(QPushButton):
    """Sidebar entry with a left icon and selected state."""

    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
        palette: Palette,
        badge_text: str = "",
    ) -> None:
        super().__init__()
        self.key = key
        self.icon_name = icon_name
        self._palette = palette
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setText("  " + label)
        self.setIconSize(QSize(18, 18))
        self._badge_text = badge_text
        self._refresh_icon(self._palette.text_muted)

    def set_label(self, label: str) -> None:
        self.setText("  " + label)

    def set_badge(self, text: str) -> None:
        self._badge_text = text
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.setChecked(selected)
        self._refresh_icon(self._palette.text if selected else self._palette.text_muted)

    def _refresh_icon(self, color: str) -> None:
        self.setIcon(icons.icon(self.icon_name, color, 22))

    def enterEvent(self, event) -> None:
        if not self.isChecked():
            self._refresh_icon(self._palette.text)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._refresh_icon(self._palette.text if self.isChecked() else self._palette.text_muted)
        super().leaveEvent(event)


class Sidebar(QFrame):
    """Fixed-width navigation rail."""

    navigate = Signal(str)

    NAV_ITEMS = (
        ("dashboard", "Dashboard", "dashboard"),
        ("terminal", "AI Terminal", "terminal"),
        ("history", "Command History", "history"),
        ("sessions", "Sessions", "sessions"),
        ("models", "AI Models", "brain"),
        ("settings", "Settings", "settings"),
        ("about", "About TermX", "info"),
    )

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setObjectName("Sidebar")
        self.setFixedWidth(self._palette.sidebar_width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._buttons: dict[str, NavButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 18, 14, 14)
        root.setSpacing(4)

        root.addWidget(self._build_brand())
        root.addSpacing(14)

        section = QLabel("WORKSPACE")
        section.setObjectName("NavSection")
        root.addWidget(section)

        for key, label, icon_name in self.NAV_ITEMS[:5]:
            button = NavButton(key, label, icon_name, self._palette)
            button.clicked.connect(lambda _=False, k=key: self._select(k))
            root.addWidget(button)
            self._buttons[key] = button

        section2 = QLabel("SYSTEM")
        section2.setObjectName("NavSection")
        root.addWidget(section2)

        for key, label, icon_name in self.NAV_ITEMS[5:]:
            button = NavButton(key, label, icon_name, self._palette)
            button.clicked.connect(lambda _=False, k=key: self._select(k))
            root.addWidget(button)
            self._buttons[key] = button

        root.addStretch(1)
        root.addWidget(self._build_ai_card())
        root.addSpacing(10)
        root.addWidget(self._build_footer())
        self._buttons["dashboard"].set_selected(True)

    # -- brand --------------------------------------------------------------
    def _build_brand(self) -> QWidget:
        p = self._palette
        brand = QWidget()
        layout = QHBoxLayout(brand)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(11)

        logo = QLabel()
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent}, stop:1 {p.purple});border-radius: 10px;"
        )
        logo.setPixmap(
            icons.pixmap("terminal", "#FFFFFF", 20, 2.0).scaled(
                20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        layout.addWidget(logo)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        name = QLabel("TermX")
        name.setObjectName("BrandName")
        name.setStyleSheet(f"color: {p.text}; font-size: 19px; font-weight: 800; letter-spacing: 0.3px;")
        text_col.addWidget(name)
        tag = QLabel("AI TERMINAL")
        tag.setObjectName("BrandTag")
        tag.setStyleSheet(f"color: {p.text_dim}; font-size: 9px; font-weight: 700; letter-spacing: 1.6px;")
        text_col.addWidget(tag)
        layout.addLayout(text_col)
        layout.addStretch(1)
        return brand

    # -- AI status card -----------------------------------------------------
    def _build_ai_card(self) -> QWidget:
        p = self._palette
        card = QFrame()
        card.setObjectName("Inset")
        card.setStyleSheet(f"QFrame#Inset {{ background-color: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(7)
        self._ai_dot = StatusDot(p.text_dim, 7, pulse=False)
        top.addWidget(self._ai_dot)
        self._ai_label = QLabel("Checking AI…")
        self._ai_label.setStyleSheet(f"color: {p.text_muted}; font-size: 11px; font-weight: 600;")
        top.addWidget(self._ai_label)
        top.addStretch(1)
        layout.addLayout(top)

        self._ai_model = QLabel("—")
        self._ai_model.setStyleSheet(f"color: {p.text_dim}; font-size: 10px; background: transparent;")
        self._ai_model.setWordWrap(False)
        layout.addWidget(self._ai_model)

        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(4)
        self._ai_detail = QLabel("")
        self._ai_detail.setStyleSheet(f"color: {p.text_faint}; font-size: 9px; background: transparent;")
        row.addWidget(self._ai_detail, 1)
        layout.addLayout(row)
        return card

    def _build_footer(self) -> QWidget:
        p = self._palette
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet(f"color: {p.text_faint}; font-size: 10px; font-weight: 600;")
        layout.addWidget(version)
        layout.addStretch(1)
        hint = QLabel("MIT")
        hint.setStyleSheet(f"color: {p.text_faint}; font-size: 10px;")
        layout.addWidget(hint)
        return footer

    # -- behavior -----------------------------------------------------------
    def _select(self, key: str) -> None:
        for name, button in self._buttons.items():
            button.set_selected(name == key)
        self.navigate.emit(key)

    def set_active(self, key: str) -> None:
        for name, button in self._buttons.items():
            button.set_selected(name == key)

    def set_ai_status(self, state: ConnectionState, detail: str, model: str) -> None:
        self._ai_dot.set_color(state.color)
        self._ai_dot.set_pulse(state is ConnectionState.CONNECTED)
        self._ai_label.setText(state.label)
        self._ai_label.setStyleSheet(
            f"color: {state.color if state is not ConnectionState.CONNECTED else self._palette.text_muted};"
            "font-size: 11px; font-weight: 600;"
        )
        self._ai_model.setText(model or "No model selected")
        self._ai_detail.setText(detail[:38] + ("…" if len(detail) > 38 else ""))
        self._ai_detail.setToolTip(detail)

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(True)
