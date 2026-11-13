"""Terminal output view.

A custom-painted, scrollable transcript that renders structured entries
(user prompts, commands, stdout, stderr, notices, AI notes) with ANSI colour
support, wrapping, text selection, and a capped buffer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QFrame,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx.core.ansi import has_ansi, parse_ansi
from termx.ui.misc_colors import qcolor
from termx.ui.theme import Palette

MAX_ENTRIES = 4000
MAX_CHARS = 1_500_000


class EntryKind(str, Enum):
    PROMPT = "prompt"  # the natural-language request
    COMMAND = "command"  # the command that was/will be run
    STDOUT = "stdout"
    STDERR = "stderr"
    NOTICE = "notice"  # TermX system notices
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    AI = "ai"  # AI explanation / diagnosis
    BANNER = "banner"


@dataclass
class TerminalEntry:
    kind: EntryKind
    text: str
    title: str = ""
    meta: str = ""
    timestamp: float = field(default_factory=time.time)
    _layouts: list[tuple[QTextLayout, float]] | None = None
    _colors: list[str | None] = field(default_factory=list)
    _height: float = 0.0
    _width: float = 0.0


class TerminalView(QFrame):
    """Scrollable terminal transcript."""

    command_clicked = Signal(str)

    def __init__(self, palette: Palette | None = None, mono_font: QFont | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self.setObjectName("Inset")
        self._entries: list[TerminalEntry] = []
        self._char_count = 0

        self._font = mono_font or QFont(self._palette.font_mono, 13)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._title_font = QFont(self._font)
        self._title_font.setBold(True)
        self._metrics = QFontMetricsF(self._font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        self._area.setFrameShape(QFrame.Shape.NoFrame)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._area.setStyleSheet("background: transparent; border: none;")

        self._canvas = _TerminalCanvas(self)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self._area.setWidget(self._canvas)
        layout.addWidget(self._area)

        self.setMinimumHeight(160)

    # -- configuration ------------------------------------------------------
    def set_font_size(self, size: int) -> None:
        self._font.setPointSize(size)
        self._title_font.setPointSize(size)
        self._metrics = QFontMetricsF(self._font)
        self._invalidate_all()
        self._canvas.update()

    def _invalidate_all(self) -> None:
        for entry in self._entries:
            entry._layouts = None
            entry._height = 0.0
            entry._width = 0.0

    # -- content ------------------------------------------------------------
    def append(self, kind: EntryKind | str, text: str, title: str = "", meta: str = "") -> None:
        entry = TerminalEntry(kind=EntryKind(kind), text=text, title=title, meta=meta)
        self._entries.append(entry)
        self._char_count += len(text)
        self._trim()
        self._canvas.relayout()
        self.scroll_to_bottom(force=True)

    def append_command(self, command: str, shell_label: str = "", cwd: str = "") -> None:
        meta = " · ".join(part for part in (shell_label, cwd) if part)
        self.append(EntryKind.COMMAND, command, title="COMMAND", meta=meta)

    def append_output(self, text: str, is_error: bool = False) -> None:
        if not text:
            return
        cleaned = text.rstrip("\n")
        if not cleaned.strip():
            return
        self.append(EntryKind.STDERR if is_error else EntryKind.STDOUT, cleaned)

    def append_prompt(self, request: str) -> None:
        self.append(EntryKind.PROMPT, request, title="YOU ASKED")

    def append_notice(self, text: str) -> None:
        self.append(EntryKind.NOTICE, text)

    def append_success(self, text: str) -> None:
        self.append(EntryKind.SUCCESS, text)

    def append_error(self, text: str) -> None:
        self.append(EntryKind.ERROR, text)

    def append_ai(self, text: str, title: str = "TERMX AI") -> None:
        self.append(EntryKind.AI, text, title=title)

    def append_banner(self, lines: list[str]) -> None:
        self.append(EntryKind.BANNER, "\n".join(lines))

    def clear(self) -> None:
        self._entries.clear()
        self._char_count = 0
        self._canvas.relayout()
        self._canvas.update()

    def transcript(self) -> str:
        """Plain-text transcript, used for 'copy all' and session reports."""
        chunks: list[str] = []
        for entry in self._entries:
            if entry.kind is EntryKind.PROMPT:
                chunks.append(f"> {entry.text}")
            elif entry.kind is EntryKind.COMMAND:
                chunks.append(f"$ {entry.text}")
            elif entry.kind in (EntryKind.STDERR, EntryKind.ERROR):
                chunks.append(f"! {entry.text}")
            elif entry.kind in (EntryKind.NOTICE, EntryKind.SUCCESS):
                chunks.append(f"· {entry.text}")
            elif entry.kind is EntryKind.AI:
                chunks.append(f"[TermX] {entry.text}")
            else:
                chunks.append(entry.text)
        return "\n".join(chunks)

    def entry_count(self) -> int:
        return len(self._entries)

    # -- behaviour ----------------------------------------------------------
    def _trim(self) -> None:
        removed = 0
        while len(self._entries) > MAX_ENTRIES or self._char_count > MAX_CHARS:
            if not self._entries:
                break
            old = self._entries.pop(0)
            self._char_count -= len(old.text)
            removed += 1
        if removed:
            self.append(EntryKind.NOTICE, f"Trimmed {removed} old entries to keep TermX responsive.")

    def scroll_to_bottom(self, force: bool = False) -> None:
        bar = self._area.verticalScrollBar()
        if force or bar.value() >= bar.maximum() - 40:
            bar.setValue(bar.maximum())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._entries:
            self._canvas.relayout(preserve_scroll=True)

    def copy_selection(self) -> str:
        return self._canvas.selected_text()

    def select_all(self) -> None:
        self._canvas.select_all()

    def contextMenuEvent(self, event) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtGui import QGuiApplication as QGA
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        selected = self.copy_selection()
        if selected:
            copy_sel = QAction("Copy selection", self)
            copy_sel.triggered.connect(lambda: QGA.clipboard().setText(selected))
            menu.addAction(copy_sel)
        copy_all = QAction("Copy all output", self)
        copy_all.triggered.connect(lambda: QGA.clipboard().setText(self.transcript()))
        menu.addAction(copy_all)
        menu.addSeparator()
        clear = QAction("Clear terminal", self)
        clear.triggered.connect(self.clear)
        menu.addAction(clear)
        menu.exec(event.globalPos())


class _TerminalCanvas(QWidget):
    """Paints all terminal entries and handles selection."""

    def __init__(self, view: TerminalView) -> None:
        super().__init__()
        self._view = view
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._anchor: tuple[int, int] | None = None
        self._cursor: tuple[int, int] | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    # -- layout -------------------------------------------------------------
    @property
    def palette_tokens(self) -> Palette:
        return self._view._palette

    def _content_width(self) -> float:
        return max(120.0, self.width() - 36)

    def _kind_color(self, kind: EntryKind) -> tuple[QColor, QColor, str]:
        """Return (background, foreground, accent) for an entry kind."""
        p = self._view._palette
        mapping = {
            EntryKind.PROMPT: ("transparent", p.accent, p.accent),
            EntryKind.COMMAND: (p.surface_alt, p.term_text, p.purple),
            EntryKind.STDOUT: ("transparent", p.term_text, p.term_dim),
            EntryKind.STDERR: ("transparent", p.term_error, p.term_error),
            EntryKind.NOTICE: ("transparent", p.term_dim, p.term_dim),
            EntryKind.SUCCESS: ("transparent", p.term_success, p.term_success),
            EntryKind.ERROR: (p.danger_soft, p.term_error, p.term_error),
            EntryKind.WARNING: (p.warning_soft, p.term_warning, p.term_warning),
            EntryKind.AI: (p.purple_soft, p.text, p.purple),
            EntryKind.BANNER: ("transparent", p.text_dim, p.text_dim),
        }
        background, foreground, accent = mapping[kind]
        return qcolor(background), qcolor(foreground), accent

    def _build_layout(self, entry: TerminalEntry, width: float) -> float:
        """Lay out an entry's text into positioned blocks.

        ``QTextLayout`` has no notion of ``\n`` — it must be given one layout
        per paragraph, otherwise newlines silently collapse into spaces. Every
        paragraph (and every ANSI colour run inside a paragraph) therefore
        becomes its own layout with an explicit vertical offset.
        """
        font = self._view._font
        metrics = QFontMetricsF(font)
        line_height = metrics.lineSpacing()
        inner_width = max(120.0, width - 44)
        y = 10.0
        if entry.title:
            y += line_height * 0.9 + 8

        layouts: list[tuple[QTextLayout, float]] = []
        colors: list[str | None] = []
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        line_spacing = 1.16

        def add_paragraph(text: str, bold: bool = False, color: str | None = None) -> None:
            nonlocal y
            if not text.strip():
                y += line_height * 0.55
                return
            paragraph_font = QFont(font)
            paragraph_font.setBold(bold)
            layout = QTextLayout(text, paragraph_font)
            layout.setTextOption(option)
            self._run_layout(layout, inner_width, line_spacing)
            layouts.append((layout, y))
            colors.append(color)
            y += layout.boundingRect().height() + 2.0

        command_font_bold = entry.kind is EntryKind.COMMAND
        if has_ansi(entry.text):
            groups: list[tuple[str, str | None, bool]] = []
            for span in parse_ansi(entry.text):
                color, bold = span.fg, span.bold or command_font_bold
                if groups and groups[-1][1] == color and groups[-1][2] == bold:
                    groups[-1] = (groups[-1][0] + span.text, color, bold)
                else:
                    groups.append((span.text, color, bold))
            for text, color, bold in groups:
                for line in text.split("\n"):
                    add_paragraph(line, bold, color)
        else:
            for line in entry.text.split("\n"):
                add_paragraph(line, command_font_bold)

        entry._layouts = layouts
        entry._colors = colors
        entry._width = width
        entry._height = max(y + 8, line_height + 12)
        return entry._height

    @staticmethod
    def _run_layout(layout: QTextLayout, width: float, spacing: float = 1.0) -> None:
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, y))
            y += line.height() * spacing
        layout.endLayout()

    def relayout(self, preserve_scroll: bool = False) -> None:
        width = self._content_width()
        scroll = self._view._area.verticalScrollBar()
        old_value = scroll.value()
        total = 8.0
        for entry in self._view._entries:
            if entry._layouts is not None and abs(entry._width - width) < 0.5:
                total += entry._height
                continue
            total += self._build_layout(entry, width)
        total += 8
        self.setMinimumHeight(int(total))
        self.resize(max(self.width(), 100), int(total))
        if preserve_scroll:
            scroll.setValue(min(old_value, scroll.maximum()))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(max(self.width(), 320), max(self.minimumHeight(), 200))

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = self._view._palette
        painter = QPainter(self)
        painter.fillRect(self.rect(), qcolor(p.term_bg))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        width = self._content_width()
        y = 8.0
        clip = event.rect()
        metrics = QFontMetricsF(self._view._font)
        line_height = metrics.lineSpacing()

        for index, entry in enumerate(self._view._entries):
            if entry._layouts is None or abs(entry._width - width) > 0.5:
                self._build_layout(entry, width)
            height = entry._height
            if y + height < clip.top() - 40 or y > clip.bottom() + 40:
                y += height
                continue

            background, foreground, accent = self._kind_color(entry.kind)
            if background.alpha() > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                painter.drawRoundedRect(QRectF(10, y + 2, width + 16, height - 6), 8, 8)
                painter.setBrush(qcolor(accent))
                painter.drawRoundedRect(QRectF(10, y + 6, 3, max(4.0, height - 14)), 1.5, 1.5)

            text_x = 22.0
            if entry.title:
                title_font = QFont(self._view._title_font)
                title_font.setPointSizeF(max(7.0, title_font.pointSizeF() - 3.5))
                title_font.setWeight(QFont.Weight.Bold)
                title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
                painter.setFont(title_font)
                painter.setPen(qcolor(accent))
                title_y = y + 6 + line_height * 0.72
                painter.drawText(QPointF(text_x + 4, title_y), entry.title)
                if entry.meta:
                    meta_font = QFont(title_font)
                    meta_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
                    painter.setFont(meta_font)
                    painter.setPen(qcolor(p.term_dim))
                    fm = QFontMetricsF(title_font)
                    prefix_w = fm.horizontalAdvance(entry.title) + 12
                    painter.drawText(QPointF(text_x + 4 + prefix_w, title_y), entry.meta)

            if entry.kind is EntryKind.COMMAND:
                prompt_font = QFont(self._view._font)
                prompt_font.setBold(True)
                painter.setFont(prompt_font)
                painter.setPen(qcolor(p.term_prompt))
                painter.drawText(QPointF(text_x + 4, y + height - 12), "\u276f")

            for block_index, (layout, offset) in enumerate(entry._layouts or []):
                painter.save()
                painter.translate(0, y + offset)
                block_color = foreground
                colors = getattr(entry, "_colors", None) or []
                if block_index < len(colors) and colors[block_index]:
                    block_color = qcolor(colors[block_index])
                painter.setPen(QPen(block_color if isinstance(block_color, QColor) else qcolor(block_color)))
                layout.draw(painter, QPointF(text_x + 12, 0))
                painter.restore()

            self._paint_selection(painter, entry, index, y, text_x + 12)
            y += height

        if not self._view._entries:
            painter.setPen(qcolor(p.term_dim))
            painter.setFont(self._view._font)
            painter.drawText(
                QRectF(20, 20, self.width() - 40, 60),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                "TermX terminal ready — describe what you want to do and press Enter.",
            )
        painter.end()

    # -- selection ----------------------------------------------------------
    def _position_at(self, pos: QPointF) -> tuple[int, int] | None:
        y = 8.0
        for index, entry in enumerate(self._view._entries):
            height = entry._height or 0.0
            if y <= pos.y() <= y + height:
                local_y = pos.y() - y
                offset_y = 0.0
                for layout, offset in entry._layouts or []:
                    layout_height = layout.boundingRect().height()
                    if offset_y + offset <= local_y <= offset + layout_height + offset_y:
                        for line_index in range(layout.lineCount()):
                            line = layout.lineAt(line_index)
                            line_top = offset + line.position().y()
                            if line_top <= local_y <= line_top + line.height():
                                x = pos.x() - 34
                                col = line.xToCursor(x)
                                return (index, self._global_to_local(entry, offset, col))
                    offset_y += 0
                # approximate: end of entry
                total = sum(len(layout.text()) for layout, _ in entry._layouts or [])
                return (index, total)
            y += height
        if self._view._entries:
            last = len(self._view._entries) - 1
            return (last, len(self._view._entries[last].text))
        return None

    @staticmethod
    def _global_to_local(entry: TerminalEntry, offset: float, col: int) -> int:
        consumed = 0
        for layout, block_offset in entry._layouts or []:
            text_len = len(layout.text())
            if abs(block_offset - offset) < 0.01 or offset <= block_offset:
                return consumed + col
            consumed += text_len
        return consumed + col

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._anchor = self._position_at(event.position())
            self._cursor = self._anchor
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._cursor = self._position_at(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            return
        if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.select_all()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._anchor = self._cursor = None
            self.update()
            return
        super().keyPressEvent(event)

    def select_all(self) -> None:
        if not self._view._entries:
            return
        self._anchor = (0, 0)
        last = len(self._view._entries) - 1
        self._cursor = (last, len(self._view._entries[last].text))
        self.update()

    def selected_text(self) -> str:
        if not self._anchor or not self._cursor:
            return ""
        (a_idx, a_col), (b_idx, b_col) = sorted([self._anchor, self._cursor])
        if (a_idx, a_col) == (b_idx, b_col):
            return ""
        parts: list[str] = []
        for index in range(a_idx, b_idx + 1):
            entry = self._view._entries[index]
            text = entry.text
            start = a_col if index == a_idx else 0
            end = b_col if index == b_idx else len(text)
            parts.append(text[start:end])
        return "\n".join(parts)

    def _paint_selection(self, painter, entry, index, y, text_x) -> None:
        if not self._anchor or not self._cursor:
            return
        (a_idx, a_col), (b_idx, b_col) = sorted([self._anchor, self._cursor])
        if not (a_idx <= index <= b_idx):
            return
        start = a_col if index == a_idx else 0
        end = b_col if index == b_idx else len(entry.text)
        if start >= end:
            return
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(76, 141, 255, 70))
        consumed = 0
        for layout, offset in entry._layouts or []:
            text = layout.text()
            local_start = max(0, start - consumed)
            local_end = min(len(text), end - consumed)
            if local_start < local_end:
                for line_index in range(layout.lineCount()):
                    line = layout.lineAt(line_index)
                    line_start = line.textStart()
                    line_end = line_start + line.textLength()
                    s = max(local_start, line_start)
                    e = min(local_end, line_end)
                    if s < e:
                        x1 = line.cursorToX(s)
                        x2 = line.cursorToX(e)
                        top = y + offset + line.position().y()
                        painter.drawRect(QRectF(text_x + x1, top, max(2.0, x2 - x1), line.height()))
            consumed += len(text)
        painter.restore()

    def select_all_copy(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
