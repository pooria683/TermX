"""Card containers, metric tiles, and section headers."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx.ui import icons
from termx.ui.misc_colors import mix, with_alpha
from termx.ui.theme import Palette
from termx.ui.widgets.misc import fade_in


class Card(QFrame):
    """Rounded surface with an optional title row and body layout."""

    def __init__(
        self,
        palette: Palette | None = None,
        title: str = "",
        subtitle: str = "",
        icon_name: str | None = None,
        object_name: str = "Card",
        padding: int = 16,
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setObjectName(object_name)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(padding, padding, padding, padding)
        self._outer.setSpacing(12)

        self.header: QHBoxLayout | None = None
        self.title_label: QLabel | None = None
        if title:
            self.header = QHBoxLayout()
            self.header.setContentsMargins(0, 0, 0, 0)
            self.header.setSpacing(9)
            if icon_name:
                icon_label = QLabel()
                icon_label.setPixmap(icons.pixmap(icon_name, self._palette.accent, 16, 1.9))
                icon_label.setFixedSize(16, 16)
                icon_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            text_col.addWidget(self.title_label)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setObjectName("Dim")
                sub.setWordWrap(True)
                sub.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
                text_col.addWidget(sub)
            self.header.addLayout(text_col, 1)
            self._outer.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        self._outer.addLayout(self.body, 1)

    def add_header_widget(self, widget: QWidget) -> None:
        if self.header is not None:
            self.header.addWidget(widget)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


class SectionHeader(QWidget):
    """Page-level heading with subtitle and trailing actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        text_col.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("PageSubtitle")
            self.subtitle_label.setWordWrap(True)
            text_col.addWidget(self.subtitle_label)
        layout.addLayout(text_col, 1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class StatTile(QFrame):
    """Compact metric with label, value, icon and trend line."""

    clicked = Signal()

    def __init__(
        self,
        label: str,
        value: str = "0",
        caption: str = "",
        icon_name: str = "activity",
        accent: str = "#4C8DFF",
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self._accent = accent
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._icon_label = QLabel()
        self._icon_label.setPixmap(icons.pixmap(icon_name, accent, 16, 1.9))
        top.addWidget(self._icon_label)
        self._label = QLabel(label.upper())
        self._label.setObjectName("CardCaption")
        top.addWidget(self._label)
        top.addStretch(1)
        layout.addLayout(top)

        self._value = QLabel(value)
        self._value.setObjectName("MetricValue")
        layout.addWidget(self._value)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self._caption = QLabel(caption)
        self._caption.setObjectName("MetricLabel")
        bottom.addWidget(self._caption)
        bottom.addStretch(1)
        layout.addLayout(bottom)

    def set_value(self, value: str) -> None:
        if self._value.text() != value:
            self._value.setText(value)
            fade_in(self._value, 180)

    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.setStyleSheet(f"QFrame#Card {{ border: 1px solid {with_alpha(self._accent, 0.5)}; }}")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setStyleSheet("")
        super().leaveEvent(event)


class MetricCard(QFrame):
    """Large hero metric with a gradient accent bar."""

    def __init__(
        self,
        title: str,
        value: str = "0",
        caption: str = "",
        palette: Palette | None = None,
        accent: str = "#4C8DFF",
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self._accent = accent
        self.setObjectName("Card")
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        label = QLabel(title.upper())
        label.setObjectName("CardCaption")
        layout.addWidget(label)
        self._value = QLabel(value)
        self._value.setStyleSheet(f"color: {self._palette.text}; font-size: 32px; font-weight: 800; letter-spacing: -1px;")
        layout.addWidget(self._value)
        self._caption = QLabel(caption)
        self._caption.setObjectName("MetricLabel")
        layout.addWidget(self._caption)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        rect = QRectF(0, 0, 3, self.height())
        path.addRoundedRect(rect, 2, 2)
        gradient = mix(self._accent, self._palette.purple, 0.5)
        painter.fillPath(path, QColor(gradient))
        painter.end()
