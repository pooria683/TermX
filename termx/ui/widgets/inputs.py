"""Text inputs: the natural-language prompt and the search field."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
)

from termx.ui import icons
from termx.ui.theme import Palette


class SearchField(QFrame):
    """Search box with a leading icon and a clear button."""

    text_changed = Signal(str)

    def __init__(self, placeholder: str = "Search…", palette: Palette | None = None) -> None:
        super().__init__()
        p = palette or Palette()
        self._palette = p
        self.setObjectName("Inset")
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(8)

        self._icon = QLabel()
        self._icon.setPixmap(icons.pixmap("search", p.text_dim, 15, 1.9))
        layout.addWidget(self._icon)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; padding: 0; color: {p.text}; font-size: 12px; }}"
        )
        self._edit.textChanged.connect(self.text_changed.emit)
        layout.addWidget(self._edit, 1)

        self._clear = QPushButton()
        self._clear.setObjectName("IconButton")
        self._clear.setIcon(icons.icon("close", p.text_dim, 16))
        self._clear.setIconSize(QSize(12, 12))
        self._clear.setFixedSize(20, 20)
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.setVisible(False)
        self._clear.clicked.connect(self.clear)
        layout.addWidget(self._clear)
        self._edit.textChanged.connect(lambda t: self._clear.setVisible(bool(t)))

    def text(self) -> str:
        return self._edit.text()

    def clear(self) -> None:
        self._edit.clear()

    def setFocus(self) -> None:
        self._edit.setFocus()


class PromptInput(QFrame):
    """Multi-purpose natural-language input with a send affordance.

    Enter submits; Shift+Enter inserts a newline (the widget is a QLineEdit for
    single-line requests, which matches terminal muscle memory).
    """

    submitted = Signal(str)
    text_changed = Signal(str)

    def __init__(self, placeholder: str = "", palette: Palette | None = None) -> None:
        super().__init__()
        p = palette or Palette()
        self._palette = p
        self.setObjectName("Inset")
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 8, 6)
        layout.setSpacing(10)

        self._prompt_icon = QLabel()
        self._prompt_icon.setPixmap(icons.pixmap("sparkles", p.accent, 18, 1.8))
        layout.addWidget(self._prompt_icon)

        self._edit = QLineEdit()
        self._edit.setObjectName("Prompt")
        self._edit.setPlaceholderText(placeholder)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            f"""
            QLineEdit#Prompt {{
                background: transparent;
                border: none;
                padding: 2px 0;
                color: {p.text};
                font-size: 14px;
            }}
            """
        )
        self._edit.returnPressed.connect(self._on_return)
        self._edit.textChanged.connect(self.text_changed.emit)
        self._edit.installEventFilter(self)
        layout.addWidget(self._edit, 1)

        self._hint = QLabel("Enter")
        self._hint.setStyleSheet(
            f"color: {p.text_faint}; font-size: 10px; font-weight: 600; "
            f"border: 1px solid {p.border}; border-radius: 4px; padding: 2px 6px;"
        )
        layout.addWidget(self._hint)

        self._send = QPushButton()
        self._send.setObjectName("Primary")
        self._send.setIcon(icons.icon("send", "#FFFFFF", 18))
        self._send.setIconSize(QSize(15, 15))
        self._send.setFixedSize(36, 36)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setToolTip("Generate command (Enter)")
        self._send.clicked.connect(self._on_return)
        layout.addWidget(self._send)

        self._busy = False

    # -- api ----------------------------------------------------------------
    def text(self) -> str:
        return self._edit.text().strip()

    def setText(self, text: str) -> None:
        self._edit.setText(text)

    def clear(self) -> None:
        self._edit.clear()

    def setFocus(self) -> None:
        self._edit.setFocus()

    def set_placeholder(self, text: str) -> None:
        self._edit.setPlaceholderText(text)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._send.setEnabled(not busy)
        self._edit.setReadOnly(busy)
        self._hint.setText("…" if busy else "Enter")

    def set_send_icon(self, name: str) -> None:
        self._send.setIcon(icons.icon(name, "#FFFFFF", 18))

    # -- internals ----------------------------------------------------------
    def _on_return(self) -> None:
        if self._busy:
            return
        text = self.text()
        if text:
            self.submitted.emit(text)

    def eventFilter(self, obj, event):
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            key_event = event  # type: QKeyEvent
            if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._on_return()
                return True
            if key_event.key() == Qt.Key.Key_Escape:
                self.clear()
                return True
        return super().eventFilter(obj, event)


class InlineError(QLabel):
    """Inline validation/error text with an icon prefix."""

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        p = palette or Palette()
        self.setWordWrap(True)
        self.setStyleSheet(
            f"color: {p.danger}; font-size: 12px; background-color: {p.danger_soft};"
            f"border: 1px solid rgba(248,113,113,0.28); border-radius: 8px; padding: 8px 10px;"
        )
        self.hide()

    def show_message(self, text: str) -> None:
        self.setText(text)
        self.show()

    def clear_message(self) -> None:
        self.clear()
        self.hide()
