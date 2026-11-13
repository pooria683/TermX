"""Small shared building blocks: dividers, empty states, toggles, animation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
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
from termx.ui.theme import Palette

_motion_enabled = True


def set_motion_enabled(enabled: bool) -> None:
    """Globally disable animations (used by the 'reduce motion' setting)."""
    global _motion_enabled
    _motion_enabled = enabled


def motion_enabled() -> bool:
    return _motion_enabled


def animate(
    target: QWidget,
    prop: bytes,
    start,
    end,
    duration: int = 180,
    easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
) -> QPropertyAnimation | None:
    """Run a short property animation unless motion is disabled.

    The animation is kept alive by the target widget (parent + attribute) and
    always uses ``KeepWhenStopped``. Deleting a running animation from a
    ``DeleteWhenStopped`` policy while Python still holds a reference is a
    classic source of use-after-free crashes in PySide, so we avoid it.
    """
    if not _motion_enabled:
        try:
            target.setProperty(prop.decode(), end)
        except Exception:
            pass
        return None
    previous = getattr(target, "_termx_anim", None)
    if previous is not None:
        try:
            previous.stop()
        except RuntimeError:
            pass
    animation = QPropertyAnimation(target, prop, target)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(easing)
    target._termx_anim = animation  # type: ignore[attr-defined]
    animation.start(QPropertyAnimation.DeletionPolicy.KeepWhenStopped)
    return animation


def fade_in(widget: QWidget, duration: int = 220) -> None:
    """Reveal a widget.

    TermX deliberately does not use ``QGraphicsOpacityEffect`` or property
    animations for content reveal: graphics effects force every child into an
    offscreen surface (which conflicts with custom painting) and, on some Qt
    builds, starting a property animation from inside a signal handler spins a
    nested event loop that never returns. Motion in TermX is therefore limited
    to cheap, self-contained timers (the loading bar, chart growth, pulsing
    status dots) — smooth, predictable, and crash-free.
    """
    if widget.isHidden():
        widget.show()


def clear_layout(layout, keep: tuple[QWidget, ...] = ()) -> None:
    """Remove every child widget from ``layout`` without dangling references.

    Widgets are hidden and unparented rather than deleted through
    ``deleteLater()``: Qt owns them once they have no parent, and Python drops
    its reference on the next GC pass. This avoids the use-after-free crashes
    that occur when a hidden page is rebuilt while a paint or animation is in
    flight.
    """
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        if child_layout is not None:
            clear_layout(child_layout, keep)
            continue
        widget = item.widget()
        if widget is None:
            continue
        if widget in keep:
            widget.hide()
            continue
        widget.hide()
        widget.setParent(None)


class Divider(QFrame):
    """One-pixel horizontal rule."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class VDivider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusDivider")
        self.setFixedWidth(1)


class InfoRow(QWidget):
    """Label/value row used in detail panels."""

    def __init__(self, label: str, value: str = "", palette: Palette | None = None) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)
        self._label = QLabel(label)
        self._label.setObjectName("Dim")
        self._value = QLabel(value)
        self._value.setObjectName("Muted")
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value.setWordWrap(False)
        layout.addWidget(self._label)
        layout.addStretch(1)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def value(self) -> str:
        return self._value.text()


class EmptyState(QWidget):
    """Friendly placeholder shown when a list or page has no content."""

    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        body: str = "",
        icon_name: str = "sparkles",
        action_text: str = "",
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        p = palette or Palette()
        self._palette = p
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_label = QLabel()
        self._icon_label.setPixmap(icons.pixmap(icon_name, p.text_faint, 40, 1.4))
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._title = QLabel(title)
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        if body:
            self._body = QLabel(body)
            self._body.setObjectName("EmptyBody")
            self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body.setWordWrap(True)
            self._body.setMaximumWidth(420)
            layout.addWidget(self._body, alignment=Qt.AlignmentFlag.AlignCenter)

        if action_text:
            from termx.ui.widgets.buttons import PillButton

            self._action = PillButton(action_text, "plus", p)
            self._action.clicked.connect(self.action_clicked.emit)
            layout.addWidget(self._action, alignment=Qt.AlignmentFlag.AlignCenter)


class ToggleSwitch(QWidget):
    """iOS-style animated toggle."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, palette: Palette | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._glide = QTimer(self)
        self._glide.setInterval(16)
        self._glide.timeout.connect(self._tick_glide)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def _tick_glide(self) -> None:
        target = 1.0 if self._checked else 0.0
        delta = target - self._offset
        if abs(delta) < 0.05:
            self._offset = target
            self._glide.stop()
            self.update()
            return
        self._offset += delta * 0.35
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, silent: bool = False) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        if motion_enabled():
            self._glide.start()
        else:
            self._offset = 1.0 if checked else 0.0
            self.update()
        if not silent:
            self.toggled.emit(checked)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self._palette
        rect = self.rect().adjusted(1, 3, -1, -3)
        radius = rect.height() / 2
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)

        if self._checked:
            painter.setBrush(QColor(p.accent))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QColor(p.surface_high))
            painter.setPen(QColor(p.border_strong))
        painter.drawPath(track)

        knob_d = rect.height() - 4
        travel = self.width() - knob_d - 8
        x = 4 + travel * self._offset
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF" if self._checked else p.text_muted))
        painter.drawEllipse(QRect(int(x), int(rect.top() + 2), knob_d, knob_d))
        painter.end()


class LoadingBar(QWidget):
    """Indeterminate gradient bar shown while the AI is thinking."""

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setFixedHeight(2)
        self._pos = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self) -> None:
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._pos = (self._pos + 0.012) % 1.3
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self._palette
        painter.fillRect(self.rect(), QColor(p.surface_high))
        width = self.width()
        seg = max(80, int(width * 0.28))
        x = int((width + seg) * self._pos) - seg

        from PySide6.QtGui import QLinearGradient

        grad = QLinearGradient(0, 0, seg, 0)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, QColor(p.accent))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRect(x, 0, seg, self.height()))
        painter.end()


class ClickableFrame(QFrame):
    """Frame that emits ``clicked`` and shows a pointer cursor."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, object_name: str = "CardHover") -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ElidedLabel(QLabel):
    """Single-line label that elides its text and keeps the tooltip in sync."""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__()
        self._full_text = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._apply()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = self.fontMetrics()
        elided = metrics.elidedText(self._full_text, self._mode, max(10, self.width() - 2))
        super().setText(elided)


def schedule(delay_ms: int, callback: Callable[[], None], parent: QWidget | None = None) -> QTimer:
    """Single-shot timer helper."""
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(delay_ms)
    return timer
