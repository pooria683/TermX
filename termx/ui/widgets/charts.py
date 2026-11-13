"""Lightweight, dependency-free charts painted with QPainter."""

from __future__ import annotations

import time
from collections.abc import Sequence

from PySide6.QtCore import Property, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from termx.ui.misc_colors import qcolor
from termx.ui.widgets.misc import motion_enabled


class Sparkline(QWidget):
    """Tiny area chart for a series of integers."""

    def __init__(
        self,
        color: str = "#4C8DFF",
        height: int = 40,
        fill: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._color = color
        self._fill = fill
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = [float(v) for v in values]
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint_line(painter)
        finally:
            painter.end()

    def _paint_line(self, painter: QPainter) -> None:
        width = self.width()
        height = self.height()
        pad = 3
        values = self._values
        peak = max(values) or 1.0
        n = len(values)
        step = (width - pad * 2) / max(1, n - 1)
        points = [
            QPointF(
                pad + i * step,
                height - pad - (v / peak) * (height - pad * 2),
            )
            for i, v in enumerate(values)
        ]

        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)

        if self._fill:
            area = QPainterPath(path)
            area.lineTo(points[-1].x(), height)
            area.lineTo(points[0].x(), height)
            area.closeSubpath()
            gradient = QLinearGradient(0, 0, 0, height)
            gradient.setColorAt(0.0, qcolor(self._color, 0.36))
            gradient.setColorAt(1.0, qcolor(self._color, 0.0))
            painter.fillPath(area, gradient)

        pen = QPen(QColor(self._color), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        if n <= 40:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._color))
            painter.drawEllipse(points[-1], 2.4, 2.4)


class BarChart(QWidget):
    """Vertical bar chart with optional labels and animated growth."""

    def __init__(
        self,
        palette=None,
        height: int = 150,
        color: str = "#4C8DFF",
        accent: str = "#9B7BFF",
    ) -> None:
        super().__init__()
        self._labels: list[str] = []
        self._values: list[float] = []
        self._color = color
        self._accent = accent
        self._progress = 0.0
        self._hover = -1
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        # Growth is time-based rather than step-based: the progress at any
        # paint is derived from the clock, so grabbing the widget (screenshots,
        # printers, page swaps) can never capture a zero-height chart. The
        # timer only exists to schedule repaints while the animation runs.
        self._started = 0.0
        self._duration = 0.35
        self._has_drawn = False
        self._growth_timer = QTimer(self)
        self._growth_timer.setInterval(16)
        self._growth_timer.timeout.connect(self._grow)

    # -- data ---------------------------------------------------------------
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = Property(float, get_progress, set_progress)

    def set_data(self, labels: Sequence[str], values: Sequence[float], animate: bool = True) -> None:
        self._labels = list(labels)
        self._values = [float(v) for v in values]
        # Animations do not tick while the widget is hidden (e.g. a page that
        # has not been shown yet), so only animate a visible chart and always
        # leave the final state reachable.
        # Grow once, on first data. Refreshes re-render instantly: re-animating
        # from zero on every update made the dashboard flicker to an empty
        # chart whenever any controller event arrived.
        first_paint = not self._has_drawn
        if animate and first_paint and self.isVisible() and motion_enabled():
            self._started = time.monotonic()
            self._progress = 0.0
            self._growth_timer.start()
        else:
            self._started = 0.0
            self._progress = 1.0
            self._growth_timer.stop()
            self._has_drawn = True
        self.update()

    def _current_progress(self) -> float:
        if not self._started:
            return 1.0
        elapsed = time.monotonic() - self._started
        return max(0.0, min(1.0, elapsed / self._duration))

    def _grow(self) -> None:
        self._progress = self._current_progress()
        if self._progress >= 1.0:
            self._growth_timer.stop()
        self.update()

    def _finish_growth(self) -> None:
        """Settle the chart so any later render (grab, print, resize) is correct."""
        if self._started:
            self._started = 0.0
            self._progress = 1.0
            self._growth_timer.stop()
        self._has_drawn = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # A chart that becomes visible settles immediately: it was already
        # rendered off-screen and must never look empty on arrival.
        if self._values and self._progress < 1.0:
            self._started = 0.0
            self._progress = 1.0
            self._growth_timer.stop()
            self.update()

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint_bars(painter)
        finally:
            painter.end()

    def _paint_bars(self, painter: QPainter) -> None:
        # Settle immediately when painting outside the normal animation tick
        # (screenshots, printing): a capture must never show a blank chart.
        if self._started and not self._growth_timer.isActive():
            self._finish_growth()
        progress = self._current_progress()
        width = self.width()
        height = self.height()
        label_h = 18
        chart_h = height - label_h - 6
        n = len(self._values)
        peak = max(self._values) or 1.0
        gap = 6
        bar_w = max(4.0, (width - gap * (n - 1)) / n)

        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)

        for i, value in enumerate(self._values):
            x = i * (bar_w + gap)
            ratio = (value / peak) * progress if peak else 0
            bar_h = max(2.0, ratio * chart_h)
            rect = QRectF(x, chart_h - bar_h, bar_w, bar_h)
            gradient = QLinearGradient(0, chart_h - bar_h, 0, chart_h)
            top = self._accent if i == self._hover else self._color
            gradient.setColorAt(0.0, qcolor(top, 0.95 if i == self._hover else 0.9))
            gradient.setColorAt(1.0, qcolor(top, 0.28))
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            painter.fillPath(path, gradient)

            if self._labels and i < len(self._labels):
                painter.setPen(QColor("#6B788F"))
                painter.drawText(
                    QRectF(x, chart_h + 2, bar_w, label_h),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    self._labels[i],
                )

    def mouseMoveEvent(self, event) -> None:
        if not self._values:
            return
        n = len(self._values)
        gap = 6
        bar_w = max(4.0, (self.width() - gap * (n - 1)) / n)
        index = int(event.position().x() / (bar_w + gap))
        index = max(0, min(n - 1, index))
        if index != self._hover:
            self._hover = index
            value = int(self._values[index])
            label = self._labels[index] if index < len(self._labels) else ""
            self.setToolTip(f"{label}: {value}")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()
        super().leaveEvent(event)


class DonutChart(QWidget):
    """Compact donut visualising a success/failure split."""

    def __init__(self, palette=None, size: int = 132) -> None:
        super().__init__()
        self._segments: list[tuple[str, float, str]] = []
        self._center_title = ""
        self._center_sub = ""
        self.setFixedSize(size, size)

    def set_data(
        self,
        segments: Sequence[tuple[str, float, str]],
        center_title: str = "",
        center_sub: str = "",
    ) -> None:
        self._segments = list(segments)
        self._center_title = center_title
        self._center_sub = center_sub
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        thickness = 11
        rect = QRectF(thickness / 2 + 2, thickness / 2 + 2, side - thickness - 4, side - thickness - 4)
        total = sum(value for _, value, _ in self._segments) or 1.0
        start = 90 * 16
        for _label, value, color in self._segments:
            span = int(-(value / total) * 360 * 16)
            pen = QPen(QColor(color), thickness)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, start, span)
            start += span

        if not any(value for _, value, _ in self._segments):
            pen = QPen(QColor("#232B3A"), thickness)
            painter.setPen(pen)
            painter.drawArc(rect, 0, 360 * 16)

        font = QFont(painter.font())
        font.setPointSizeF(15)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#E8ECF4"))
        painter.drawText(
            QRectF(0, side / 2 - 20, side, 26),
            Qt.AlignmentFlag.AlignCenter,
            self._center_title,
        )
        font.setPointSizeF(8)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor("#6B788F"))
        painter.drawText(
            QRectF(0, side / 2 + 6, side, 20),
            Qt.AlignmentFlag.AlignCenter,
            self._center_sub,
        )
