"""AI Models page: inspect Ollama models, pull guidance, choose the active one."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import ConnectionState, ModelInfo
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge, StatusDot
from termx.ui.widgets.buttons import IconButton, PillButton
from termx.ui.widgets.cards import Card, SectionHeader
from termx.ui.widgets.misc import Divider, EmptyState, clear_layout

MODEL_NOTES = {
    "qwen2.5-coder": "Excellent at code and shell commands. Best default for TermX.",
    "llama3.1": "Strong general reasoning; good explanations.",
    "llama3.2": "Fast and small — ideal on 8 GB machines.",
    "mistral": "Balanced quality and speed.",
    "phi3": "Very small; runs on modest hardware.",
    "codellama": "Code-focused; weaker at prose explanations.",
    "deepseek-coder": "Precise code generation.",
    "gemma2": "Compact, well-rounded model.",
}


class ModelCard(QFrame):
    """Card for one installed model."""

    select = Signal(str)
    remove = Signal(str)

    def __init__(self, model: ModelInfo, palette: Palette, active: bool) -> None:
        super().__init__()
        self.model = model
        self._palette = palette
        self._active = active
        self.setObjectName("Card")
        if active:
            self.setStyleSheet(f"QFrame#Card {{ border: 1px solid {palette.accent}; background-color: {palette.surface_alt}; }}")
        self.setMinimumHeight(126)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(7)
        dot = StatusDot(palette.success if active else palette.text_dim, 6)
        top.addWidget(dot)
        name = QLabel(model.name)
        name.setStyleSheet(f"color: {palette.text}; font-size: 13px; font-weight: 700;")
        top.addWidget(name, 1)
        if active:
            top.addWidget(Badge("ACTIVE", palette.accent))
        layout.addLayout(top)

        family = model.family or MODEL_NOTES.get(model.display_name, "")
        note = MODEL_NOTES.get(model.display_name, "")
        description = QLabel(note or family or "Local Ollama model")
        description.setObjectName("Dim")
        description.setWordWrap(True)
        description.setMaximumHeight(34)
        layout.addWidget(description)
        layout.addStretch(1)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        meta.addWidget(Badge(model.size_label, palette.purple))
        if model.parameter_size:
            meta.addWidget(Badge(model.parameter_size, palette.cyan))
        if model.quantization:
            meta.addWidget(Badge(model.quantization, palette.text_muted))
        meta.addStretch(1)
        layout.addLayout(meta)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        if not active:
            use = PillButton("Use model", "check", palette)
            use.clicked.connect(lambda: self.select.emit(model.name))
            actions.addWidget(use)
        else:
            actions.addWidget(Badge("In use", palette.success))
        actions.addStretch(1)
        layout.addLayout(actions)


class ModelsPage(QWidget):
    """Model management and Ollama diagnostics."""

    model_selected = Signal(str)

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

        header = SectionHeader(
            "AI Models",
            "TermX runs entirely on your machine through Ollama — no API keys, no data leaves your computer.",
            self._palette,
        )
        self._refresh_button = PillButton("Refresh", "refresh", self._palette)
        self._refresh_button.clicked.connect(self.refresh)
        header.add_action(self._refresh_button)
        layout.addWidget(header)

        layout.addWidget(self._build_status_card())

        installed_header = QHBoxLayout()
        title = QLabel("Installed models")
        title.setObjectName("CardTitle")
        installed_header.addWidget(title)
        installed_header.addStretch(1)
        self._installed_count = QLabel("0")
        self._installed_count.setObjectName("Dim")
        installed_header.addWidget(self._installed_count)
        layout.addLayout(installed_header)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        layout.addWidget(self._grid_host)

        self._empty = EmptyState(
            "No models installed",
            "Install one with:  ollama pull qwen2.5-coder:7b",
            "brain",
            "",
            self._palette,
        )
        self._empty.setMinimumHeight(210)
        layout.addWidget(self._empty)

        layout.addWidget(self._build_recommended())
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addStretch(1)

        self.controller.models_changed.connect(self._on_models_changed)
        self.controller.connection_changed.connect(self._on_connection_changed)
        self._render()

    # -- construction -------------------------------------------------------
    def _build_status_card(self) -> Card:
        card = Card(self._palette, "Ollama engine", "Local inference server status", "zap")
        row = QHBoxLayout()
        row.setSpacing(14)

        self._status_dot = StatusDot(self._palette.text_dim, 9)
        row.addWidget(self._status_dot)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._status_title = QLabel("Checking…")
        self._status_title.setStyleSheet(f"color: {self._palette.text}; font-size: 13px; font-weight: 700;")
        text_col.addWidget(self._status_title)
        self._status_detail = QLabel("")
        self._status_detail.setObjectName("Dim")
        self._status_detail.setWordWrap(True)
        text_col.addWidget(self._status_detail)
        row.addLayout(text_col, 1)

        endpoint_box = QFrame()
        endpoint_box.setObjectName("Inset")
        endpoint_layout = QHBoxLayout(endpoint_box)
        endpoint_layout.setContentsMargins(10, 6, 6, 6)
        endpoint_layout.setSpacing(8)
        endpoint_label = QLabel(self.controller.settings.ollama_host)
        endpoint_label.setStyleSheet(
            f'color: {self._palette.text_muted}; font-family: "{self._palette.font_mono}", monospace; font-size: 11px;'
        )
        endpoint_layout.addWidget(endpoint_label)
        copy_button = IconButton("copy", "Copy endpoint", self._palette, size=16)
        copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.controller.settings.ollama_host))
        endpoint_layout.addWidget(copy_button)
        row.addWidget(endpoint_box)
        card.add_layout(row)

        card.add(Divider())
        hint = QLabel(
            "Install Ollama from ollama.com, then run:  ollama pull qwen2.5-coder:7b  "
            "(≈4.7 GB). TermX detects models automatically."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _build_recommended(self) -> Card:
        card = Card(self._palette, "Recommended models", "Copy a pull command, then press Refresh", "sparkles")
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, (name, note) in enumerate(
            [
                ("qwen2.5-coder:7b", "Best overall for shell commands"),
                ("llama3.2:3b", "Fast, runs on 8 GB RAM"),
                ("llama3.1:8b", "Best explanations"),
                ("phi3:mini", "Smallest footprint"),
            ]
        ):
            row = QFrame()
            row.setObjectName("Inset")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 8, 8)
            row_layout.setSpacing(10)
            text = QVBoxLayout()
            text.setSpacing(1)
            label = QLabel(name)
            label.setStyleSheet(
                f'color: {self._palette.text}; font-family: "{self._palette.font_mono}", monospace;'
                "font-size: 11px; font-weight: 600;"
            )
            text.addWidget(label)
            caption = QLabel(note)
            caption.setObjectName("Dim")
            text.addWidget(caption)
            row_layout.addLayout(text, 1)
            copy = IconButton("copy", f"Copy: ollama pull {name}", self._palette, size=16)
            copy.clicked.connect(lambda _=False, n=name: self._copy_pull(n))
            row_layout.addWidget(copy)
            grid.addWidget(row, index // 2, index % 2)
        card.add_layout(grid)
        return card

    def _copy_pull(self, name: str) -> None:
        command = f"ollama pull {name}"
        QGuiApplication.clipboard().setText(command)
        self.controller.notice.emit(f"Copied “{command}” to the clipboard.", "success")

    # -- data ---------------------------------------------------------------
    def _on_models_changed(self, _models) -> None:
        """The controller already has fresh data: just redraw."""
        self._render()

    def _on_connection_changed(self, *_args) -> None:
        """Connection state changed — redraw, never re-request.

        Re-requesting here would emit ``connection_changed`` again and recurse
        until the stack overflows.
        """
        self._render()

    def refresh(self, use_cache: bool = False) -> None:
        """Ask the controller for a live health check, then redraw."""
        if use_cache:
            self._render()
            return
        self._refresh_button.setEnabled(False)
        self._refresh_button.setText("Refreshing…")
        self.controller.refresh_ai_status()
        QTimer.singleShot(400, self._finish_refresh)

    def _finish_refresh(self) -> None:
        self._refresh_button.setEnabled(True)
        self._refresh_button.setText("Refresh")
        self._render()

    def _render(self) -> None:
        p = self._palette
        state = self.controller.connection_state
        self._status_dot.set_color(state.color)
        self._status_dot.set_pulse(state is ConnectionState.CONNECTED)
        titles = {
            ConnectionState.CONNECTED: "Ollama is running",
            ConnectionState.DEGRADED: "Ollama is running (no models)",
            ConnectionState.OFFLINE: "Ollama is not reachable",
            ConnectionState.UNKNOWN: "Checking Ollama…",
        }
        self._status_title.setText(titles.get(state, "Unknown"))
        self._status_detail.setText(self.controller.connection_detail)

        clear_layout(self._grid)

        models = self.controller.models
        self._installed_count.setText(f"{len(models)} installed")
        self._grid_host.setVisible(bool(models))
        self._empty.setVisible(not models)
        if not models:
            self._empty.setVisible(True)

        active = self.controller.settings.model
        for index, model in enumerate(models):
            is_active = model.name == active or (":" not in active and model.name.split(":")[0] == active)
            card = ModelCard(model, p, is_active)
            card.select.connect(self._select_model)
            self._grid.addWidget(card, index // 2, index % 2)
            card.show()
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)

    def _select_model(self, name: str) -> None:
        settings = self.controller.settings.model_copy(update={"model": name})
        self.controller.update_settings(settings)
        self.controller.db.mark_model_used(name)
        self.controller.notice.emit(f"Active model set to {name}.", "success")
        self._render()

    def on_shown(self) -> None:
        self.refresh()
