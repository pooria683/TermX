"""Button family: primary, pill, icon, and segmented control."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
)

from termx.ui import icons
from termx.ui.theme import Palette


class IconButton(QPushButton):
    """Square icon-only button with hover background."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        palette: Palette | None = None,
        size: int = 20,
        icon_size: int = 18,
        color: str | None = None,
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self._icon_name = icon_name
        self._color = color
        self.setObjectName("IconButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size + 10, size + 10)
        self.setIconSize(QSize(icon_size, icon_size))
        if tooltip:
            self.setToolTip(tooltip)
        self._refresh()

    def _refresh(self) -> None:
        color = self._color or self._palette.text_muted
        self.setIcon(icons.icon(self._icon_name, color, 20))

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._refresh()

    def set_color(self, color: str | None) -> None:
        self._color = color
        self._refresh()

    def enterEvent(self, event) -> None:
        self.setIcon(icons.icon(self._icon_name, self._color or self._palette.text, 20))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._refresh()
        super().leaveEvent(event)


class PillButton(QPushButton):
    """Secondary button with an optional leading icon."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        palette: Palette | None = None,
        object_name: str = "Ghost",
    ) -> None:
        super().__init__(text)
        self._palette = palette or Palette()
        self._icon_name = icon_name
        self._icon_color = self._palette.text_muted
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            self.setIcon(icons.icon(icon_name, self._icon_color, 18))
            self.setIconSize(QSize(15, 15))

    def set_icon_name(self, name: str | None, color: str | None = None) -> None:
        self._icon_name = name
        if color:
            self._icon_color = color
        if name:
            self.setIcon(icons.icon(name, self._icon_color, 18))
            self.setIconSize(QSize(15, 15))
        else:
            self.setIcon(QIcon())

    def set_tint(self, color: str) -> None:
        self._icon_color = color
        if self._icon_name:
            self.setIcon(icons.icon(self._icon_name, color, 18))


class PrimaryButton(QPushButton):
    """Gradient call-to-action button."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = "play",
        palette: Palette | None = None,
    ) -> None:
        super().__init__(text)
        self._palette = palette or Palette()
        self._icon_name = icon_name
        self.setObjectName("Primary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        if icon_name:
            self.setIcon(icons.icon(icon_name, "#FFFFFF", 18))
            self.setIconSize(QSize(15, 15))

    def set_icon_name(self, name: str | None, color: str = "#FFFFFF") -> None:
        self._icon_name = name
        if name:
            self.setIcon(icons.icon(name, color, 18))
            self.setIconSize(QSize(15, 15))
        else:
            self.setIcon(QIcon())

    def set_busy(self, busy: bool, busy_text: str = "Working…") -> None:
        if busy:
            self._idle_text = self.text()
            self.setText(busy_text)
            self.setEnabled(False)
        else:
            if hasattr(self, "_idle_text"):
                self.setText(self._idle_text)
            self.setEnabled(True)


class SegmentedControl(QFrame):
    """Group of mutually exclusive options rendered as a segmented strip."""

    changed = Signal(int)

    def __init__(
        self,
        options: list[str],
        current: int = 0,
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setObjectName("Inset")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        for index, label in enumerate(options):
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(index == current)
            self._group.addButton(button, index)
            self._buttons.append(button)
            self._layout.addWidget(button)
        self._group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def set_label(self, index: int, text: str) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setText(text)


class ToggleChip(QPushButton):
    """Checkable chip used for quick filters."""

    def __init__(self, text: str, palette: Palette | None = None) -> None:
        super().__init__(text)
        self.setObjectName("Chip")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
