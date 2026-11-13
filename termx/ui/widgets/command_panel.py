"""The generated-command preview panel.

Shows the proposed command, risk assessment, explanation, alternatives and the
safety warnings — and offers Execute / Copy / Explain / Edit actions. Nothing
runs until the user presses Execute.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import CommandSuggestion, RiskLevel, SafetyVerdict
from termx.ui import icons
from termx.ui.misc_colors import with_alpha
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge, RiskBadge, ShellBadge
from termx.ui.widgets.buttons import IconButton, PillButton, PrimaryButton
from termx.ui.widgets.misc import Divider, fade_in


class CommandPreviewPanel(QFrame):
    """Preview + actions for the command TermX proposes."""

    execute_requested = Signal(str)
    explain_requested = Signal(str)
    copy_requested = Signal(str)
    clear_requested = Signal()
    edited = Signal(str)
    alternative_requested = Signal(str)

    def __init__(self, palette: Palette | None = None) -> None:
        super().__init__()
        self._palette = palette or Palette()
        self._suggestion: CommandSuggestion | None = None
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # -- header ---------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(8)
        self._heading = QLabel("COMMAND PREVIEW")
        self._heading.setObjectName("CardCaption")
        header.addWidget(self._heading)
        self._shell_badge = ShellBadge()
        self._shell_badge.hide()
        header.addWidget(self._shell_badge)
        header.addStretch(1)
        self._risk_badge = RiskBadge()
        self._risk_badge.hide()
        header.addWidget(self._risk_badge)
        self._edit_toggle = IconButton("edit", "Edit command before running", self._palette)
        self._edit_toggle.setCheckable(True)
        self._edit_toggle.toggled.connect(self._on_edit_toggled)
        header.addWidget(self._edit_toggle)
        root.addLayout(header)

        # -- command surface ------------------------------------------------
        self._command_box = QFrame()
        self._command_box.setObjectName("Inset")
        box_layout = QVBoxLayout(self._command_box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        box_layout.setSpacing(8)

        self._command_label = QLabel()
        self._command_label.setObjectName("Mono")
        self._command_label.setWordWrap(True)
        self._command_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._command_label.setStyleSheet(
            f'font-family: "{self._palette.font_mono}", Consolas, monospace;'
            f"font-size: 13px; color: {self._palette.term_text}; background: transparent;"
            "line-height: 1.5;"
        )
        box_layout.addWidget(self._command_label)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("CodeEdit")
        self._editor.setMinimumHeight(76)
        self._editor.setTabChangesFocus(False)
        self._editor.textChanged.connect(self._on_editor_changed)
        self._editor.hide()
        box_layout.addWidget(self._editor)

        placeholder = QLabel("Describe a task above — TermX will draft the command here.")
        placeholder.setStyleSheet(f"color: {self._palette.text_dim}; font-size: 12px; background: transparent;")
        placeholder.setWordWrap(True)
        self._placeholder = placeholder
        box_layout.addWidget(placeholder)

        root.addWidget(self._command_box)

        # -- explanation ----------------------------------------------------
        self._explanation = QLabel()
        self._explanation.setWordWrap(True)
        self._explanation.setStyleSheet(
            f"color: {self._palette.text_muted}; font-size: 12px; line-height: 1.6; background: transparent;"
        )
        self._explanation.hide()
        root.addWidget(self._explanation)

        # -- risk / safety notice ------------------------------------------
        self._notice = QFrame()
        self._notice.setObjectName("Inset")
        notice_layout = QHBoxLayout(self._notice)
        notice_layout.setContentsMargins(12, 9, 12, 9)
        notice_layout.setSpacing(9)
        self._notice_icon = QLabel()
        notice_layout.addWidget(self._notice_icon, 0, Qt.AlignmentFlag.AlignTop)
        self._notice_text = QLabel()
        self._notice_text.setWordWrap(True)
        self._notice_text.setStyleSheet("background: transparent; font-size: 11px;")
        notice_layout.addWidget(self._notice_text, 1)
        self._notice.hide()
        root.addWidget(self._notice)

        # -- alternative ----------------------------------------------------
        self._alternative_row = QWidget()
        alt_layout = QHBoxLayout(self._alternative_row)
        alt_layout.setContentsMargins(0, 0, 0, 0)
        alt_layout.setSpacing(8)
        alt_icon = QLabel()
        alt_icon.setPixmap(icons.pixmap("layers", self._palette.text_dim, 14))
        alt_layout.addWidget(alt_icon)
        self._alternative_label = QLabel()
        self._alternative_label.setWordWrap(True)
        self._alternative_label.setStyleSheet(f"color: {self._palette.text_dim}; font-size: 11px; background: transparent;")
        alt_layout.addWidget(self._alternative_label, 1)
        self._use_alt = PillButton("Use alternative", "chevron-right", self._palette)
        self._use_alt.clicked.connect(lambda: self.alternative_requested.emit(self._alternative_label.text()))
        alt_layout.addWidget(self._use_alt)
        self._alternative_row.hide()
        root.addWidget(self._alternative_row)

        root.addWidget(Divider())

        # -- actions --------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._execute = PrimaryButton("Execute", "play", self._palette)
        self._execute.setToolTip("Run this command (Ctrl+Enter)")
        self._execute.clicked.connect(self._emit_execute)
        actions.addWidget(self._execute)

        self._copy = PillButton("Copy", "copy", self._palette)
        self._copy.setToolTip("Copy command to clipboard")
        self._copy.clicked.connect(self._emit_copy)
        actions.addWidget(self._copy)

        self._explain = PillButton("Explain", "book", self._palette)
        self._explain.setToolTip("Ask the AI to explain this command")
        self._explain.clicked.connect(self._emit_explain)
        actions.addWidget(self._explain)

        actions.addStretch(1)

        self._source = Badge("OFFLINE", self._palette.warning)
        self._source.hide()
        actions.addWidget(self._source)

        self._clear = PillButton("Clear", "trash", self._palette)
        self._clear.setToolTip("Clear the terminal (Ctrl+L)")
        self._clear.clicked.connect(self.clear_requested.emit)
        actions.addWidget(self._clear)

        root.addLayout(actions)

        self._set_state(empty=True)

    # -- state --------------------------------------------------------------
    def _set_state(self, empty: bool) -> None:
        self._command_label.setVisible(not empty)
        self._placeholder.setVisible(empty)
        for widget in (
            self._execute,
            self._copy,
            self._explain,
            self._edit_toggle,
        ):
            widget.setEnabled(not empty)

    def current_command(self) -> str:
        if self._editor.isVisible():
            return self._editor.toPlainText().strip()
        return self._command_label.text().strip()

    def has_command(self) -> bool:
        return bool(self.current_command())

    # -- public API ---------------------------------------------------------
    def show_suggestion(self, suggestion: CommandSuggestion, verdict: SafetyVerdict | None = None) -> None:
        self._suggestion = suggestion
        self._shell_badge.set_shell(suggestion.shell)
        self._shell_badge.show()
        self._risk_badge.set_risk(suggestion.risk)
        self._risk_badge.show()
        self._command_label.setText(suggestion.command or "—")
        self._editor.setPlainText(suggestion.command or "")
        self._set_state(empty=not suggestion.command)
        self._placeholder.setVisible(not suggestion.command)
        if not suggestion.command:
            self._placeholder.setText(
                suggestion.explanation or "TermX could not turn this request into a command. Try rephrasing it."
            )
            self._placeholder.show()
            self._command_label.hide()

        if suggestion.explanation:
            self._explanation.setText(suggestion.explanation)
            self._explanation.show()
            fade_in(self._explanation)
        else:
            self._explanation.hide()

        self._apply_notice(suggestion, verdict)
        self._apply_source(suggestion)

        if suggestion.alternative:
            self._alternative_label.setText(suggestion.alternative)
            self._alternative_row.show()
        else:
            self._alternative_row.hide()

        self._execute.setText("Execute")
        self._execute.set_icon_name("play")

    def _apply_source(self, suggestion: CommandSuggestion) -> None:
        if suggestion.generated_by == "offline":
            self._source.set_text("OFFLINE")
            self._source.set_color(self._palette.warning)
            self._source.setToolTip("Generated from TermX's built-in library (AI unavailable)")
            self._source.show()
        elif suggestion.model:
            short = suggestion.model.split(":")[0]
            self._source.set_text(short.upper()[:18])
            self._source.set_color(self._palette.accent)
            self._source.setToolTip(f"Generated by {suggestion.model}")
            self._source.show()
        else:
            self._source.hide()

    def _apply_notice(self, suggestion: CommandSuggestion, verdict: SafetyVerdict | None) -> None:
        p = self._palette
        reasons: list[str] = []
        if verdict is not None:
            reasons = verdict.reasons
        elif suggestion.risk_reason:
            reasons = [suggestion.risk_reason]

        risk = suggestion.risk
        if not suggestion.command:
            self._notice.hide()
            return

        if risk is RiskLevel.BLOCKED:
            color, icon_name, headline = p.danger, "error", "Blocked by TermX safety rules"
        elif risk is RiskLevel.DESTRUCTIVE:
            color, icon_name, headline = p.danger, "warning", "Destructive command — review carefully"
        elif risk is RiskLevel.CAUTION:
            color, icon_name, headline = p.warning, "warning", "Changes will be made to your system"
        else:
            color, icon_name, headline = p.success, "shield", "Read-only command"

        detail = " ".join(r for r in reasons if r)[:420] if reasons else ""
        self._notice_icon.setPixmap(icons.pixmap(icon_name, color, 16, 1.9))
        self._notice_text.setText(f"<b style='color:{color}'>{headline}</b>" + (f"<br>{detail}" if detail else ""))
        self._notice_text.setStyleSheet(f"color: {p.text_muted}; font-size: 11px; background: transparent;")
        self._notice.setStyleSheet(
            f"QFrame#Inset {{ background-color: {with_alpha(color, 0.08)};"
            f" border: 1px solid {with_alpha(color, 0.3)}; border-radius: 8px; }}"
        )
        self._notice.show()
        if risk is RiskLevel.BLOCKED:
            self._execute.setEnabled(False)
            self._execute.setToolTip("This command is blocked by the safety policy")

    def set_executing(self, running: bool) -> None:
        if running:
            self._execute.setText("Running…")
            self._execute.set_icon_name("stop")
            self._execute.setEnabled(True)
        else:
            self._execute.setText("Execute")
            self._execute.set_icon_name("play")
            suggestion = self._suggestion
            self._execute.setEnabled(not (suggestion is not None and suggestion.risk is RiskLevel.BLOCKED))

    def set_shell(self, shell) -> None:
        self._shell_badge.set_shell(shell)
        self._shell_badge.show()

    def clear(self) -> None:
        self._suggestion = None
        self._command_label.clear()
        self._editor.clear()
        self._editor.hide()
        self._command_label.show()
        self._explanation.hide()
        self._notice.hide()
        self._alternative_row.hide()
        self._source.hide()
        self._risk_badge.hide()
        self._shell_badge.hide()
        self._placeholder.setText("Describe a task above — TermX will draft the command here.")
        self._placeholder.show()
        self._set_state(empty=True)

    def set_explanation(self, text: str, title: str = "AI EXPLANATION") -> None:
        self._explanation.setText(text)
        self._explanation.show()
        fade_in(self._explanation)

    # -- internals ----------------------------------------------------------
    def _on_edit_toggled(self, checked: bool) -> None:
        if checked:
            self._editor.setPlainText(self._command_label.text())
            self._command_label.hide()
            self._editor.show()
            self._editor.setFocus()
            self._edit_toggle.setToolTip("Done editing")
        else:
            self._editor.hide()
            self._command_label.show()
            self._edit_toggle.setToolTip("Edit command before running")
            self.edited.emit(self._editor.toPlainText().strip())

    def _on_editor_changed(self) -> None:
        text = self._editor.toPlainText().strip()
        self._execute.setEnabled(bool(text))
        self.edited.emit(text)

    def _emit_execute(self) -> None:
        command = self.current_command()
        if command:
            self.execute_requested.emit(command)

    def _emit_copy(self) -> None:
        command = self.current_command()
        if command:
            QGuiApplication.clipboard().setText(command)
            self._copy.setText("Copied")
            self._copy.set_tint(self._palette.success)
            from PySide6.QtCore import QTimer

            QTimer.singleShot(1400, self._reset_copy)

    def _reset_copy(self) -> None:
        self._copy.setText("Copy")
        self._copy.set_tint(self._palette.text_muted)

    def _emit_explain(self) -> None:
        command = self.current_command()
        if command:
            self.explain_requested.emit(command)
