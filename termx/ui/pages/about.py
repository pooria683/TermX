"""About page: version, architecture, keyboard shortcuts, and credits."""

from __future__ import annotations

import platform

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx import APP_NAME, APP_TAGLINE, APP_VERSION, LICENSE_NAME, PROJECT_URL
from termx.ui import icons
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge
from termx.ui.widgets.buttons import PillButton
from termx.ui.widgets.cards import Card
from termx.ui.widgets.misc import Divider

SHORTCUTS = (
    ("Ctrl + G", "Focus the natural-language prompt"),
    ("Enter", "Generate a command from the prompt"),
    ("Ctrl + Enter", "Execute the previewed command"),
    ("Esc", "Cancel a running command"),
    ("Ctrl + L", "Clear the terminal"),
    ("Ctrl + C", "Copy the terminal selection"),
    ("Ctrl + A", "Select all terminal text"),
    ("Ctrl + 1…7", "Jump between pages"),
)

ARCHITECTURE = (
    ("UI", "PySide6 widgets, custom-painted terminal, design tokens"),
    ("Controller", "Qt signals + QThread workers — no blocking calls on the UI thread"),
    ("AI layer", "Ollama /api/chat with JSON-constrained prompts and offline fallback"),
    ("Safety layer", "Deterministic rule engine — the model's risk label is never trusted"),
    ("Execution", "Shell-agnostic subprocess runner with streaming and timeouts"),
    ("Storage", "SQLite (WAL) for history, sessions, settings, and model cache"),
)


class AboutPage(QWidget):
    """Product information and diagnostics."""

    open_terminal = Signal()

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        content = QWidget()
        content.setObjectName("PageBody")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(self._build_hero())
        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._build_shortcuts(), 1)
        columns.addWidget(self._build_architecture(), 1)
        layout.addLayout(columns)
        layout.addWidget(self._build_diagnostics())
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addStretch(1)

    # -- cards --------------------------------------------------------------
    def _build_hero(self) -> QFrame:
        p = self._palette
        hero = QFrame()
        hero.setObjectName("Card")
        hero.setStyleSheet(f"QFrame#Card {{ background-color: {p.surface}; border: 1px solid {p.border}; border-radius: 16px; }}")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(20)

        logo = QLabel()
        logo.setFixedSize(64, 64)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent}, stop:1 {p.purple});border-radius: 18px;"
        )
        logo.setPixmap(icons.pixmap("terminal", "#FFFFFF", 34, 2.1))
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name = QLabel(APP_NAME)
        name.setStyleSheet(f"color: {p.text}; font-size: 26px; font-weight: 800; letter-spacing: -0.6px;")
        name_row.addWidget(name)
        name_row.addWidget(Badge(f"v{APP_VERSION}", p.accent))
        name_row.addWidget(Badge("OPEN SOURCE", p.purple))
        name_row.addStretch(1)
        text_col.addLayout(name_row)

        tagline = QLabel(APP_TAGLINE)
        tagline.setStyleSheet(f"color: {p.text_muted}; font-size: 13px;")
        text_col.addWidget(tagline)

        description = QLabel(
            "TermX turns plain English into safe, explained shell commands. It drafts the command, "
            "explains each part, rates the risk, and only runs it after you approve. Everything runs "
            "locally — your prompts and terminal output never leave your machine."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {p.text_dim}; font-size: 12px; line-height: 1.6;")
        description.setMinimumHeight(78)
        description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        text_col.addWidget(description)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        start = PillButton("Open AI Terminal", "terminal", p, "Primary")
        start.setMinimumHeight(34)
        start.clicked.connect(self.open_terminal.emit)
        buttons.addWidget(start)
        copy_link = PillButton("Copy project URL", "github", p)
        copy_link.clicked.connect(lambda: QGuiApplication.clipboard().setText(PROJECT_URL))
        buttons.addWidget(copy_link)
        buttons.addStretch(1)
        text_col.addSpacing(4)
        text_col.addLayout(buttons)

        layout.addLayout(text_col, 1)
        return hero

    def _build_shortcuts(self) -> Card:
        card = Card(self._palette, "Keyboard shortcuts", "Work without leaving the keyboard", "keyboard")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        for row, (keys, description) in enumerate(SHORTCUTS):
            key_label = QLabel(keys)
            key_label.setStyleSheet(
                f"color: {self._palette.text}; font-size: 10px; font-weight: 700;"
                f"border: 1px solid {self._palette.border_strong}; border-radius: 5px;"
                f"background-color: {self._palette.surface_alt}; padding: 3px 7px;"
            )
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(key_label, row, 0)
            desc = QLabel(description)
            desc.setObjectName("Muted")
            grid.addWidget(desc, row, 1)
        grid.setColumnStretch(1, 1)
        card.add_layout(grid)
        return card

    def _build_architecture(self) -> Card:
        card = Card(self._palette, "Built for real use", "Layered architecture, no shortcuts", "layers")
        for layer, description in ARCHITECTURE:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 3, 0, 3)
            row_layout.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(5, 5)
            dot.setStyleSheet(f"background-color: {self._palette.accent}; border-radius: 2px;")
            row_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(layer)
            name.setStyleSheet(f"color: {self._palette.text}; font-size: 11px; font-weight: 700;")
            text.addWidget(name)
            desc = QLabel(description)
            desc.setObjectName("Dim")
            desc.setWordWrap(True)
            text.addWidget(desc)
            row_layout.addLayout(text, 1)
            card.add(row)
        return card

    def _build_diagnostics(self) -> Card:
        p = self._palette
        card = Card(p, "Environment", "Runtime diagnostics — useful in bug reports", "cpu")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)

        from PySide6 import __version__ as pyside_version

        facts = [
            ("Python", platform.python_version()),
            ("PySide6 / Qt", pyside_version),
            ("Platform", f"{platform.system()} {platform.release()}"),
            ("Architecture", platform.machine()),
            ("Shell selected", self.controller.shell.label),
            ("Ollama endpoint", self.controller.settings.ollama_host),
            ("Database", f"{self.controller.db.size_bytes() / 1024:.0f} KB"),
            ("License", LICENSE_NAME),
        ]
        for index, (label, value) in enumerate(facts):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(1)
            key = QLabel(label.upper())
            key.setObjectName("CardCaption")
            cell_layout.addWidget(key)
            val = QLabel(value)
            val.setStyleSheet(f'color: {p.text_muted}; font-size: 11px; font-family: "{p.font_mono}", monospace;')
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cell_layout.addWidget(val)
            grid.addWidget(cell, index // 4, index % 4)
        card.add_layout(grid)
        card.add(Divider())

        copy_diag = PillButton("Copy diagnostics", "copy", p)
        copy_diag.clicked.connect(self._copy_diagnostics)
        row = QHBoxLayout()
        row.addWidget(copy_diag)
        row.addStretch(1)
        credit = QLabel(f"Built with PySide6 · Ollama · SQLite  ·  {LICENSE_NAME} licensed")
        credit.setObjectName("Dim")
        row.addWidget(credit)
        card.add_layout(row)
        return card

    def _copy_diagnostics(self) -> None:
        from PySide6 import __version__ as pyside_version

        report = "\n".join(
            [
                f"TermX {APP_VERSION}",
                f"Python {platform.python_version()}",
                f"PySide6 {pyside_version}",
                f"Platform {platform.system()} {platform.release()} {platform.machine()}",
                f"Shell {self.controller.shell.value}",
                f"Ollama {self.controller.settings.ollama_host}",
                f"Model {self.controller.settings.model}",
                f"AI state {self.controller.connection_state.value}",
            ]
        )
        QGuiApplication.clipboard().setText(report)
        self.controller.notice.emit("Diagnostics copied to clipboard.", "success")
