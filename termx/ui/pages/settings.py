"""Settings page: AI, execution, appearance, history and data controls."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import AppSettings, ShellType
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.buttons import PillButton
from termx.ui.widgets.cards import Card, SectionHeader
from termx.ui.widgets.misc import Divider, ToggleSwitch, set_motion_enabled


class SettingRow(QWidget):
    """Label + description on the left, control on the right."""

    def __init__(self, title: str, description: str = "", widget: QWidget | None = None) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 12px; font-weight: 600;")
        text_col.addWidget(self.title)
        if description:
            desc = QLabel(description)
            desc.setObjectName("Dim")
            desc.setWordWrap(True)
            text_col.addWidget(desc)
        layout.addLayout(text_col, 1)
        if widget is not None:
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingsPage(QWidget):
    """Editable application configuration."""

    settings_saved = Signal(object)

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()
        self._dirty = False

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
        layout.setSpacing(14)

        header = SectionHeader("Settings", "Tune TermX's AI, safety, and appearance.", self._palette)
        self._save = PillButton("Save changes", "save", self._palette, "Primary")
        self._save.setMinimumHeight(34)
        self._save.clicked.connect(self.save)
        header.add_action(self._save)
        self._reset = PillButton("Reset", "refresh", self._palette)
        self._reset.clicked.connect(self.reset_defaults)
        header.add_action(self._reset)
        layout.addWidget(header)

        layout.addWidget(self._build_ai_card())
        layout.addWidget(self._build_execution_card())
        layout.addWidget(self._build_appearance_card())
        layout.addWidget(self._build_data_card())
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addStretch(1)

        self._load(self.controller.settings)
        # Stay in sync when settings change from elsewhere (CLI, another page).
        self.controller.settings_changed.connect(self._on_external_settings)

    # -- cards --------------------------------------------------------------
    def _build_ai_card(self) -> Card:
        p = self._palette
        card = Card(p, "Artificial intelligence", "Ollama connection and model behaviour", "brain")

        self._host = QLineEdit()
        self._host.setPlaceholderText("http://localhost:11434")
        self._host.setMinimumWidth(240)
        self._host.textChanged.connect(self._mark_dirty)
        card.add(SettingRow("Ollama endpoint", "Where the local Ollama server listens.", self._host))
        card.add(Divider())

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setMinimumWidth(240)
        self._model.currentTextChanged.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Preferred model",
                "TermX falls back to any installed model if this one is missing.",
                self._model,
            )
        )
        card.add(Divider())

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.05)
        self._temperature.setDecimals(2)
        self._temperature.setMinimumWidth(110)
        self._temperature.valueChanged.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Temperature",
                "Lower values produce more deterministic, precise commands.",
                self._temperature,
            )
        )
        card.add(Divider())

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(128, 4096)
        self._max_tokens.setSingleStep(64)
        self._max_tokens.setMinimumWidth(110)
        self._max_tokens.valueChanged.connect(self._mark_dirty)
        card.add(SettingRow("Response limit", "Maximum tokens per AI response.", self._max_tokens))
        card.add(Divider())

        self._offline = ToggleSwitch(True, p)
        self._offline.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Offline fallback",
                "Use TermX's built-in command library when the AI is unavailable.",
                self._offline,
            )
        )

        refresh_models = PillButton("Reload models", "refresh", p)
        refresh_models.clicked.connect(self._reload_models)
        card.add_header_widget(refresh_models)
        self._reload_models(silent=True)
        return card

    def _build_execution_card(self) -> Card:
        p = self._palette
        card = Card(p, "Execution & safety", "How commands are confirmed and run", "shield")

        self._shell = QComboBox()
        for shell in ShellType:
            self._shell.addItem(shell.label, shell.value)
        self._shell.setMinimumWidth(180)
        self._shell.currentIndexChanged.connect(self._mark_dirty)
        card.add(SettingRow("Default shell", "Shell used for generated commands.", self._shell))
        card.add(Divider())

        self._auto_shell = ToggleSwitch(True, p)
        self._auto_shell.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Auto-detect shell",
                "Prefer PowerShell on Windows and bash/zsh elsewhere.",
                self._auto_shell,
            )
        )
        card.add(Divider())

        self._confirm = ToggleSwitch(True, p)
        self._confirm.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Always confirm before running",
                "Show the command preview and require an explicit Execute.",
                self._confirm,
            )
        )
        card.add(Divider())

        self._confirm_destructive = ToggleSwitch(True, p)
        self._confirm_destructive.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Extra warning for destructive commands",
                "Ask for confirmation when a command can delete data.",
                self._confirm_destructive,
            )
        )
        card.add(Divider())

        self._block = ToggleSwitch(True, p)
        self._block.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Block dangerous commands",
                "Refuse patterns like disk formatting, root deletion, or encoded payloads.",
                self._block,
            )
        )
        card.add(Divider())

        self._auto_explain = ToggleSwitch(True, p)
        self._auto_explain.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Explain errors automatically",
                "Diagnose failures and propose a corrected command.",
                self._auto_explain,
            )
        )
        card.add(Divider())

        self._timeout = QSpinBox()
        self._timeout.setRange(5, 3600)
        self._timeout.setSuffix(" s")
        self._timeout.setMinimumWidth(110)
        self._timeout.valueChanged.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Command timeout",
                "Long-running commands are terminated after this many seconds.",
                self._timeout,
            )
        )
        return card

    def _build_appearance_card(self) -> Card:
        p = self._palette
        card = Card(p, "Appearance", "Typography and motion", "eye")

        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(10)
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(11, 20)
        self._font_slider.setFixedWidth(150)
        self._font_size_label = QLabel("13 px")
        self._font_size_label.setMinimumWidth(48)
        self._font_size_label.setStyleSheet(f"color: {p.text_muted}; font-size: 11px;")
        self._font_slider.valueChanged.connect(self._on_font_size)
        size_layout.addWidget(self._font_slider)
        size_layout.addWidget(self._font_size_label)
        card.add(SettingRow("Terminal font size", "Applies to the AI Terminal immediately.", size_row))
        card.add(Divider())

        self._motion = ToggleSwitch(True, p)
        self._motion.toggled.connect(self._on_motion)
        card.add(
            SettingRow(
                "Interface animations",
                "Fades, chart growth and pulsing indicators.",
                self._motion,
            )
        )
        card.add(Divider())

        theme_note = QLabel("Dark theme · designed for long terminal sessions")
        theme_note.setObjectName("Dim")
        card.add(SettingRow("Theme", "TermX ships with a premium dark palette.", theme_note))
        return card

    def _build_data_card(self) -> Card:
        p = self._palette
        card = Card(p, "History & data", "Everything is stored locally in SQLite", "database")

        self._remember = ToggleSwitch(True, p)
        self._remember.toggled.connect(self._mark_dirty)
        card.add(
            SettingRow(
                "Remember sessions",
                "Keep session history across app restarts.",
                self._remember,
            )
        )
        card.add(Divider())

        self._max_history = QSpinBox()
        self._max_history.setRange(50, 100000)
        self._max_history.setSingleStep(50)
        self._max_history.setMinimumWidth(130)
        self._max_history.valueChanged.connect(self._mark_dirty)
        card.add(SettingRow("History limit", "Older entries beyond this count are pruned.", self._max_history))
        card.add(Divider())

        path_box = QWidget()
        path_layout = QHBoxLayout(path_box)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        db_path = QLabel(str(self.controller.db.path))
        db_path.setStyleSheet(f'color: {p.text_dim}; font-family: "{p.font_mono}", monospace; font-size: 10px;')
        db_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_layout.addWidget(db_path)
        open_folder = PillButton("Open folder", "folder", p)
        open_folder.clicked.connect(self._open_data_dir)
        path_layout.addWidget(open_folder)
        card.add(SettingRow("Database file", "TermX's local SQLite store.", path_box))
        card.add(Divider())

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        export = PillButton("Export history", "download", p)
        export.clicked.connect(self._export)
        actions_layout.addWidget(export)
        vacuum = PillButton("Compact database", "layers", p)
        vacuum.clicked.connect(self._vacuum)
        actions_layout.addWidget(vacuum)
        clear = PillButton("Clear history", "trash", p, "Danger")
        clear.clicked.connect(self._clear_history)
        actions_layout.addWidget(clear)
        actions_layout.addStretch(1)
        card.add(SettingRow("Maintenance", "Export, compact, or clear stored commands.", actions))
        return card

    # -- state --------------------------------------------------------------
    def _on_external_settings(self, settings) -> None:
        """Mirror settings edited outside this page, unless we have unsaved edits."""
        if self._dirty:
            return
        self._load(settings)

    def on_shown(self) -> None:
        """Refresh from the controller when the page becomes visible."""
        if not self._dirty:
            self._load(self.controller.settings)

    def _mark_dirty(self, *args) -> None:
        self._dirty = True
        self._save.setText("Save changes •")

    def _load(self, settings: AppSettings) -> None:
        targets = [
            self._host,
            self._model,
            self._temperature,
            self._max_tokens,
            self._offline,
            self._shell,
            self._auto_shell,
            self._confirm,
            self._confirm_destructive,
            self._block,
            self._auto_explain,
            self._timeout,
            self._remember,
            self._max_history,
            self._motion,
            self._font_slider,
        ]
        for widget in targets:
            widget.blockSignals(True)
        self._host.setText(settings.ollama_host)
        if self._model.findText(settings.model) == -1:
            self._model.addItem(settings.model)
        self._model.setCurrentText(settings.model)
        self._temperature.setValue(settings.temperature)
        self._max_tokens.setValue(settings.max_tokens)
        self._offline.setChecked(settings.offline_fallback, silent=True)
        index = self._shell.findData(settings.preferred_shell.value)
        self._shell.setCurrentIndex(max(0, index))
        self._auto_shell.setChecked(settings.auto_detect_shell, silent=True)
        self._confirm.setChecked(settings.confirm_execution, silent=True)
        self._confirm_destructive.setChecked(settings.confirm_destructive, silent=True)
        self._block.setChecked(settings.block_forbidden, silent=True)
        self._auto_explain.setChecked(settings.auto_explain_errors, silent=True)
        self._timeout.setValue(settings.timeout_seconds)
        self._remember.setChecked(settings.remember_sessions, silent=True)
        self._max_history.setValue(settings.max_history)
        self._motion.setChecked(not settings.reduce_motion, silent=True)
        self._font_slider.setValue(settings.font_size)
        for widget in targets:
            widget.blockSignals(False)
        self._font_size_label.setText(f"{settings.font_size} px")
        self._dirty = False
        self._save.setText("Save changes")

    def collect(self) -> AppSettings:
        base = self.controller.settings
        shell_value = self._shell.currentData() or ShellType.POWERSHELL.value
        return base.model_copy(
            update={
                "ollama_host": self._host.text().strip() or "http://localhost:11434",
                "model": self._model.currentText().strip() or base.model,
                "temperature": round(self._temperature.value(), 2),
                "max_tokens": self._max_tokens.value(),
                "offline_fallback": self._offline.isChecked(),
                "preferred_shell": ShellType(shell_value),
                "auto_detect_shell": self._auto_shell.isChecked(),
                "confirm_execution": self._confirm.isChecked(),
                "confirm_destructive": self._confirm_destructive.isChecked(),
                "block_forbidden": self._block.isChecked(),
                "auto_explain_errors": self._auto_explain.isChecked(),
                "timeout_seconds": self._timeout.value(),
                "remember_sessions": self._remember.isChecked(),
                "max_history": self._max_history.value(),
                "reduce_motion": not self._motion.isChecked(),
                "font_size": self._font_slider.value(),
            }
        )

    # -- actions ------------------------------------------------------------
    def save(self) -> None:
        settings = self.collect()
        self.controller.update_settings(settings)
        self.controller.refresh_ai_status()
        self._dirty = False
        self._save.setText("Saved")
        self.controller.notice.emit("Settings saved.", "success")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1600, lambda: self._save.setText("Save changes"))
        self.settings_saved.emit(settings)

    def reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset settings",
            "Restore all settings to their defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._load(AppSettings())
            self.save()

    def _on_font_size(self, value: int) -> None:
        self._font_size_label.setText(f"{value} px")
        self._mark_dirty()

    def _on_motion(self, enabled: bool) -> None:
        set_motion_enabled(enabled)
        self._mark_dirty()

    def _reload_models(self, silent: bool = False) -> None:
        self.controller.refresh_ai_status()
        names = [m.name for m in self.controller.models]
        current = self._model.currentText()
        self._model.blockSignals(True)
        self._model.clear()
        for name in names:
            self._model.addItem(name)
        if current and current not in names:
            self._model.addItem(current)
        self._model.setCurrentText(current or self.controller.settings.model)
        self._model.blockSignals(False)
        if not silent:
            self.controller.notice.emit(
                f"Found {len(names)} model{'s' if len(names) != 1 else ''}." if names else "No models found — is Ollama running?",
                "success" if names else "warning",
            )

    def _open_data_dir(self) -> None:
        path = Path(self.controller.db.path).parent
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export history",
            str(Path.home() / "termx-history.json"),
            "JSON (*.json);;CSV (*.csv)",
        )
        if path:
            fmt = "csv" if path.endswith(".csv") else "json"
            count = self.controller.export_history(path, fmt)
            self.controller.notice.emit(f"Exported {count} entries.", "success")

    def _vacuum(self) -> None:
        before = self.controller.db.size_bytes()
        self.controller.db.vacuum()
        after = self.controller.db.size_bytes()
        self.controller.notice.emit(f"Database compacted ({before / 1024:.0f} KB → {after / 1024:.0f} KB).", "success")

    def _clear_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear history",
            "Delete all command history? Favourites are preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            removed = self.controller.clear_history(keep_favorites=True)
            self.controller.notice.emit(f"Removed {removed} history entries.", "success")
