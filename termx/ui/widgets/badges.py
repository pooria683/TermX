"""Status indicators: dots, badges, risk and shell chips."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from termx.core.models import RiskLevel, ShellType
from termx.ui import icons
from termx.ui.misc_colors import with_alpha
from termx.ui.theme import Palette


class StatusDot(QWidget):
    """Small coloured indicator, optionally pulsing."""

    def __init__(
        self,
        color: str = "#34D399",
        size: int = 8,
        pulse: bool = False,
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._color = QColor(color)
        self._diameter = size
        self._pulse = pulse
        self._alpha = 1.0
        self._growing = False
        self.setFixedSize(size + 8, size + 8)
        # One timer for the widget's whole lifetime; started and stopped on demand.
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        if pulse:
            self._timer.start()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self._color.setAlphaF(1.0)
        self.update()

    def set_pulse(self, pulse: bool) -> None:
        if pulse == self._pulse:
            return
        self._pulse = pulse
        if pulse:
            self._timer.start()
        else:
            self._timer.stop()
            self._alpha = 1.0
        self.update()

    def _tick(self) -> None:
        self._alpha += 0.045 if self._growing else -0.045
        if self._alpha >= 1.0:
            self._alpha, self._growing = 1.0, False
        elif self._alpha <= 0.35:
            self._alpha, self._growing = 0.35, True
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        cx, cy = self.width() / 2, self.height() / 2
        if self._pulse:
            halo = QColor(self._color)
            halo.setAlphaF(0.18 * self._alpha)
            painter.setBrush(halo)
            painter.setPen(Qt.PenStyle.NoPen)
            r = self._diameter / 2 + 3
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        solid = QColor(self._color)
        solid.setAlphaF(self._alpha if self._pulse else 1.0)
        painter.setBrush(solid)
        painter.setPen(Qt.PenStyle.NoPen)
        d = self._diameter
        painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))


class Badge(QLabel):
    """Tinted, rounded label for statuses and counts."""

    def __init__(
        self,
        text: str = "",
        color: str = "#4C8DFF",
        palette: Palette | None = None,
        icon_name: str | None = None,
        solid: bool = False,
    ) -> None:
        super().__init__()
        self._color = color
        self._solid = solid
        self._icon_name = icon_name
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setContentsMargins(0, 0, 0, 0)
        self.set_color(color)
        self.set_text(text)
        if icon_name:
            self.set_icon(icon_name)

    def set_text(self, text: str) -> None:
        self._text = text
        self.setText(f"  {text}" if self._icon_name else f" {text} ")

    def set_icon(self, name: str | None) -> None:
        self._icon_name = name
        self.set_text(self._text)

    def set_color(self, color: str) -> None:
        self._color = color
        if self._solid:
            background, foreground = color, "#0B0D12"
        else:
            background, foreground = with_alpha(color, 0.14), color
        self.setStyleSheet(
            f"""
            QLabel#Badge {{
                color: {foreground};
                background-color: {background};
                border: 1px solid {with_alpha(color, 0.32)};
                border-radius: 9px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.4px;
            }}
            """
        )

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width() + 6, max(hint.height(), 20))


class RiskBadge(Badge):
    """Badge that renders a :class:`RiskLevel` consistently everywhere."""

    ICONS = {
        RiskLevel.SAFE: "shield",
        RiskLevel.CAUTION: "warning",
        RiskLevel.DESTRUCTIVE: "error",
        RiskLevel.BLOCKED: "error",
    }

    def __init__(self, risk: RiskLevel = RiskLevel.SAFE, palette: Palette | None = None) -> None:
        super().__init__(risk.label, risk.color)
        self.set_risk(risk)

    def set_risk(self, risk: RiskLevel) -> None:
        self._risk = risk
        self.set_icon(self.ICONS.get(risk, "info"))
        self.set_color(risk.color)
        self.set_text(risk.label)
        self.setToolTip(f"Risk level: {risk.label.value if hasattr(risk.label, 'value') else risk.label}")


class ShellBadge(Badge):
    """Compact shell indicator."""

    COLORS = {
        ShellType.POWERSHELL: "#3B8EEA",
        ShellType.CMD: "#9AA6BC",
        ShellType.BASH: "#34D399",
        ShellType.ZSH: "#FBBF24",
    }

    def __init__(self, shell: ShellType = ShellType.POWERSHELL, palette: Palette | None = None) -> None:
        super().__init__(shell.label, self.COLORS.get(shell, "#4C8DFF"))
        self.set_shell(shell)

    def set_shell(self, shell: ShellType) -> None:
        self._shell = shell
        self.set_color(self.COLORS.get(shell, "#4C8DFF"))
        self.set_text(shell.label)


class Chip(QWidget):
    """Icon + text inline chip used in metadata rows."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        color: str = "#9AA6BC",
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if icon_name:
            icon_label = QLabel()
            icon_label.setPixmap(icons.pixmap(icon_name, color, 14, 1.8))
            layout.addWidget(icon_label)
        self._label = QLabel(text)
        self._label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 500;")
        layout.addWidget(self._label)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
