"""AI Terminal page — the primary workspace.

Layout:
    header (title, shell switcher, actions)
    terminal output (flex)
    suggestion chips
    prompt input
    command preview panel
"""

from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import (
    CommandSuggestion,
    ConnectionState,
    ErrorExplanation,
    ExecutionResult,
    ExecutionStatus,
    RiskLevel,
    SafetyVerdict,
    ShellType,
)
from termx.core.shell import available_shells
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import StatusDot
from termx.ui.widgets.buttons import IconButton, PillButton, SegmentedControl
from termx.ui.widgets.command_panel import CommandPreviewPanel
from termx.ui.widgets.inputs import PromptInput
from termx.ui.widgets.misc import LoadingBar, clear_layout, fade_in
from termx.ui.widgets.terminal import EntryKind, TerminalView

EXAMPLE_REQUESTS = (
    "Show all files in the current directory",
    "Find the largest files in this folder",
    "Check available disk space",
    "Which processes are using the most memory?",
    "Show my network configuration",
    "List the last 15 git commits",
    "Find all TODO comments in this project",
    "What is my current IP address?",
    "Show how long this machine has been running",
    "List the listening network ports",
)

WELCOME_BANNER = (
    "TermX  ·  AI-powered intelligent terminal",
    "Describe what you want in plain English. TermX drafts the command, explains it,",
    "shows the risk level, and only runs it after you confirm.",
)


class TerminalPage(QWidget):
    """The AI Terminal workspace."""

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()
        self._shells = available_shells()
        self._running = False
        self._stream_buffer = ""
        self._pending_request = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addWidget(self._build_terminal(), 1)
        root.addWidget(self._build_chips())
        root.addWidget(self._build_prompt())
        self._preview = CommandPreviewPanel(self._palette)
        self._preview.execute_requested.connect(self._on_execute)
        self._preview.explain_requested.connect(self._on_explain)
        self._preview.copy_requested.connect(self._on_copy)
        self._preview.clear_requested.connect(self._on_clear)
        self._preview.alternative_requested.connect(self._on_alternative)
        self._preview.edited.connect(self._on_edited)
        root.addWidget(self._preview)

        self._loading = LoadingBar(self._palette)
        root.addWidget(self._loading)

        self._connect_controller()
        self._install_shortcuts()
        self._show_welcome()

    # -- construction -------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        p = self._palette
        header = QHBoxLayout()
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("AI Terminal")
        title.setObjectName("PageTitle")
        title_col.addWidget(title)
        self._subtitle = QLabel("Describe a task — TermX writes, explains, and runs the command with your approval.")
        self._subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(self._subtitle)
        header.addLayout(title_col, 1)

        self._shell_switch = SegmentedControl([s.label for s in self._shells], self._shell_index(), self._palette)
        self._shell_switch.setToolTip("Target shell for generated commands")
        self._shell_switch.changed.connect(self._on_shell_segment)
        header.addWidget(self._shell_switch, 0, Qt.AlignmentFlag.AlignVCenter)

        self._status_pill = QFrame()
        self._status_pill.setObjectName("Inset")
        pill_layout = QHBoxLayout(self._status_pill)
        pill_layout.setContentsMargins(10, 5, 12, 5)
        pill_layout.setSpacing(7)
        self._new_session = IconButton("plus", "Start a new session (clears the terminal)", self._palette, size=20)
        self._new_session.clicked.connect(self._on_new_session)
        header.addWidget(self._new_session, 0, Qt.AlignmentFlag.AlignVCenter)

        self._status_dot = StatusDot(p.text_dim, 7)
        pill_layout.addWidget(self._status_dot)
        self._status_text = QLabel("Checking AI…")
        self._status_text.setStyleSheet(f"color: {p.text_muted}; font-size: 11px; font-weight: 600; background: transparent;")
        pill_layout.addWidget(self._status_text)
        header.addWidget(self._status_pill, 0, Qt.AlignmentFlag.AlignVCenter)

        return header

    def _build_terminal(self) -> QWidget:
        from PySide6.QtGui import QFont

        font = QFont(self._palette.font_mono, self.controller.settings.font_size - 1)
        self.terminal = TerminalView(self._palette, font)
        self.terminal.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return self.terminal

    def _build_chips(self) -> QWidget:
        container = QWidget()
        self._chip_layout = QHBoxLayout(container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(6)
        self._chips: list[PillButton] = []
        self._refresh_chips()
        return container

    def _refresh_chips(self) -> None:
        clear_layout(self._chip_layout)
        self._chips.clear()
        picks = random.sample(EXAMPLE_REQUESTS, 3)
        label = QLabel("Try:")
        label.setObjectName("Dim")
        self._chip_layout.addWidget(label)
        for text in picks:
            chip = PillButton(text, "sparkles", self._palette)
            chip.setObjectName("Chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.set_tint(self._palette.text_dim)
            chip.clicked.connect(lambda _=False, t=text: self._use_example(t))
            self._chip_layout.addWidget(chip)
            self._chips.append(chip)
        self._chip_layout.addStretch(1)
        shuffle = IconButton("refresh", "Show other examples", self._palette, size=18)
        shuffle.clicked.connect(self._refresh_chips)
        self._chip_layout.addWidget(shuffle)

    def _build_prompt(self) -> QWidget:
        self._prompt = PromptInput("e.g. “find files larger than 100 MB and show their size”", self._palette)
        self._prompt.submitted.connect(self._on_submit)
        self._prompt.text_changed.connect(self._on_prompt_text)
        return self._prompt

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._on_clear)
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, activated=self._on_clear)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._execute_current)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._execute_current)
        QShortcut(QKeySequence("Ctrl+G"), self, activated=self._prompt.setFocus)
        QShortcut(QKeySequence("Escape"), self, activated=self._on_escape)

    # -- controller wiring --------------------------------------------------
    def _connect_controller(self) -> None:
        c = self.controller
        c.suggestion_ready.connect(self._on_suggestion)
        c.generation_failed.connect(self._on_generation_failed)
        c.generation_started.connect(self._on_generation_started)
        c.generation_finished.connect(self._on_generation_finished)
        c.execution_started.connect(self._on_execution_started)
        c.execution_output.connect(self._on_execution_output)
        c.execution_finished.connect(self._on_execution_finished)
        c.execution_failed.connect(self._on_execution_failed)
        c.connection_changed.connect(self._on_connection)
        c.explanation_ready.connect(self._on_explanation)
        c.diagnosis_ready.connect(self._on_diagnosis)
        c.stream_chunk.connect(self._on_stream_chunk)
        c.stream_finished.connect(self._on_stream_finished)
        c.notice.connect(self._on_notice)
        c.shell_changed.connect(self._on_shell_changed)
        c.cwd_changed.connect(lambda _cwd: self._update_prompt_prefix())
        self._on_connection(c.connection_state, c.connection_detail)

    # -- lifecycle ----------------------------------------------------------
    def _show_welcome(self) -> None:
        from termx import APP_VERSION

        self.terminal.append(EntryKind.BANNER, "\n".join(WELCOME_BANNER), title=f"TERMX v{APP_VERSION}")
        self.terminal.append(
            EntryKind.NOTICE,
            "Tip: press Ctrl+Enter to run the previewed command, Ctrl+L to clear, Ctrl+G to focus the prompt.",
        )
        self._update_prompt_prefix()

    def _update_prompt_prefix(self) -> None:
        cwd = self.controller.cwd
        shell = self.controller.shell
        prompt_symbol = "PS>" if shell is ShellType.POWERSHELL else ("C:\\>" if shell is ShellType.CMD else "$")
        from pathlib import Path

        home = str(Path.home())
        short = "~" + cwd[len(home) :] if cwd.startswith(home) and len(cwd) > len(home) else cwd
        if len(short) > 46:
            short = "…" + short[-44:]
        self._prompt.set_placeholder(f"{prompt_symbol} {short} — describe what you want to do")

    def on_shown(self) -> None:
        self._prompt.setFocus()

    def apply_settings(self) -> None:
        self.terminal.set_font_size(self.controller.settings.font_size - 1)
        self._refresh_chips()

    # -- prompt -------------------------------------------------------------
    def _on_prompt_text(self, text: str) -> None:
        if not text.strip():
            self._prompt.set_send_icon("send")

    def _use_example(self, text: str) -> None:
        self._prompt.setText(text)
        self._prompt.setFocus()

    def _on_submit(self, text: str) -> None:
        question = text.strip()
        if not question:
            return
        self.terminal.append_prompt(question)
        self._pending_request = question
        self._prompt.clear()

        if self._looks_like_question(question):
            self.terminal.append_notice("Asking the AI…")
            self.controller.ask(question)
            return
        self.controller.generate(question)

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("explain ", "what is ", "what's ", "why ", "how does ", "how do i use ")):
            # "how do I use X" is usually a task; treat only pure questions as chat.
            return not any(verb in lowered for verb in ("find", "list", "show", "delete", "create", "run"))
        return False

    # -- generation ---------------------------------------------------------
    def _on_generation_started(self) -> None:
        self._prompt.set_busy(True)
        self._loading.start()
        self.controller.refresh_ai_status()
        self._set_status_pill("Generating…", self._palette.accent, pulse=True)

    def _on_generation_finished(self) -> None:
        self._prompt.set_busy(False)
        self._loading.stop()

    def _on_suggestion(self, suggestion: CommandSuggestion, verdict: SafetyVerdict) -> None:
        self._preview.show_suggestion(suggestion, verdict)
        fade_in(self._preview)
        if suggestion.command:
            self.terminal.append_notice(f"Drafted a {suggestion.risk.label.lower()} command — press Execute to run it.")
        else:
            self.terminal.append_notice(suggestion.explanation or "TermX could not build a command for that request.")
        if verdict.blocked:
            self.terminal.append_error("Blocked by TermX safety rules: " + " ".join(verdict.reasons[:2]))
        self._prompt.setFocus()

    def _on_generation_failed(self, message: str) -> None:
        self.terminal.append_error(message)
        self.terminal.append_notice("Start Ollama (`ollama serve`) and pull a model, or try one of the example prompts.")

    # -- execution ----------------------------------------------------------
    def _execute_current(self) -> None:
        command = self._preview.current_command()
        if command:
            self._on_execute(command)

    def _on_execute(self, command: str) -> None:
        if self._running:
            self.controller.cancel_execution()
            self.terminal.append_notice("Stopping the running command…")
            return
        suggestion = self.controller.suggestion
        risk = suggestion.risk if suggestion and suggestion.command == command else None
        if risk is RiskLevel.DESTRUCTIVE and self.controller.settings.confirm_destructive:
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setWindowTitle("Confirm destructive command")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("This command can destroy data and cannot be undone.")
            box.setInformativeText(command[:400])
            run = box.addButton("Run anyway", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not run:
                self.terminal.append_notice("Cancelled.")
                return
        self.controller.execute(command)

    def _on_execution_started(self, command: str) -> None:
        self._running = True
        self._preview.set_executing(True)
        shell = self.controller.shell
        self.terminal.append_command(command, shell.label, self.controller.cwd)
        self._set_status_pill("Running…", self._palette.info, pulse=True)

    def _on_execution_output(self, stream: str, text: str) -> None:
        self.terminal.append_output(text, is_error=(stream == "stderr"))

    def _on_execution_finished(self, result: ExecutionResult) -> None:
        self._running = False
        self._preview.set_executing(False)
        ready = self.controller.connection_state is ConnectionState.CONNECTED
        self._set_status_pill("AI ready", self._palette.success if ready else self._palette.warning)

        if result.status is ExecutionStatus.BLOCKED:
            return  # message already shown
        if result.status is ExecutionStatus.CANCELLED:
            self.terminal.append_notice("Command cancelled.")
            return

        seconds = result.duration_ms / 1000
        if result.status is ExecutionStatus.SUCCESS:
            extra = ""
            if not result.stdout.strip() and not result.stderr.strip():
                extra = " (no output)"
            self.terminal.append_success(f"✓ Completed in {seconds:.2f}s{extra}")
        else:
            self.terminal.append_error(f"✗ Exit code {result.exit_code} after {seconds:.2f}s")

    def _on_execution_failed(self, message: str) -> None:
        self._running = False
        self._preview.set_executing(False)
        self.terminal.append_error(message)

    def _on_escape(self) -> None:
        if self._running:
            self.controller.cancel_execution()

    # -- AI feedback --------------------------------------------------------
    def _on_explanation(self, text: str, used_offline: bool) -> None:
        label = "EXPLANATION (OFFLINE)" if used_offline else "AI EXPLANATION"
        self.terminal.append_ai(text, title=label)
        self._preview.set_explanation(text)

    def _on_diagnosis(self, explanation: ErrorExplanation) -> None:
        lines = [f"**{explanation.summary}**"]
        if explanation.cause:
            lines.append(explanation.cause)
        for suggestion in explanation.suggestions:
            lines.append(f"• {suggestion}")
        if explanation.corrected_command:
            lines.append(f"Try instead: {explanation.corrected_command}")
        source = "AI DIAGNOSIS" if explanation.source == "ai" else "DIAGNOSIS"
        self.terminal.append_ai("\n".join(lines), title=source)
        if explanation.corrected_command:
            verdict = self.controller.reanalyze(explanation.corrected_command)
            suggestion = CommandSuggestion(
                request=self.controller.suggestion.request if self.controller.suggestion else "",
                command=explanation.corrected_command,
                shell=self.controller.shell,
                explanation="Corrected command proposed by TermX after the failure.",
                risk=verdict.risk,
                risk_reason=" ".join(verdict.reasons[:2]),
                generated_by="ai" if explanation.source == "ai" else "offline",
            )
            self.controller.set_suggestion(suggestion, verdict)

    def _on_stream_chunk(self, token: str) -> None:
        if not self._stream_buffer:
            self.terminal.append(EntryKind.AI, "", title="TERMX AI")
        self._stream_buffer += token
        self._set_streaming_text()

    def _set_streaming_text(self) -> None:
        entries = self.terminal._entries
        if entries:
            entries[-1].text = self._stream_buffer
            entries[-1]._layouts = None
            self.terminal._canvas.relayout()
            self.terminal.scroll_to_bottom()

    def _on_stream_finished(self, text: str) -> None:
        self._stream_buffer = ""
        if not text.strip():
            return
        command = None
        lines = []
        for line in text.splitlines():
            if line.strip().lower().startswith("command:"):
                command = line.split(":", 1)[1].strip().strip("`")
            else:
                lines.append(line)
        body = "\n".join(lines).strip()
        if command:
            self._on_alternative(command)
        if not body:
            self.terminal.append_notice("(empty response)")

    # -- actions ------------------------------------------------------------
    def _on_explain(self, command: str) -> None:
        self.terminal.append_notice("Explaining the command…")
        self.controller.explain(command)

    def _on_copy(self, command: str) -> None:
        QGuiApplication.clipboard().setText(command)
        self.terminal.append_notice("Command copied to clipboard.")

    def _on_clear(self) -> None:
        self.terminal.clear()
        self._preview.clear()
        self.controller.suggestion = None
        self.controller.verdict = None
        self._show_welcome()

    def _on_alternative(self, command: str) -> None:
        verdict = self.controller.reanalyze(command)
        suggestion = CommandSuggestion(
            request=command,
            command=command,
            shell=self.controller.shell,
            explanation="Selected alternative command — review before running.",
            risk=verdict.risk,
            risk_reason=" ".join(verdict.reasons[:2]),
            generated_by="manual",
        )
        self._preview.show_suggestion(suggestion, verdict)

    def _on_edited(self, command: str) -> None:
        if command:
            self.controller.reanalyze(command)

    def _on_new_session(self) -> None:
        session = self.controller.new_session()
        self.terminal.append_notice(f"Started “{session.title}”.")
        self._on_clear()

    # -- shell / status -----------------------------------------------------
    def _shell_index(self) -> int:
        try:
            return self._shells.index(self.controller.shell)
        except ValueError:
            return 0

    def _on_shell_segment(self, index: int) -> None:
        if 0 <= index < len(self._shells):
            self.controller.set_shell(self._shells[index])
            self.terminal.append_notice(f"Target shell set to {self._shells[index].label}.")

    def _on_shell_changed(self, shell: ShellType) -> None:
        index = self._shells.index(shell) if shell in self._shells else 0
        self._shell_switch.set_current(index)
        self._preview.set_shell(shell)
        self._update_prompt_prefix()

    def _on_connection(self, state: ConnectionState, detail: str) -> None:
        self._status_dot.set_color(state.color)
        self._status_dot.set_pulse(state is ConnectionState.CONNECTED)
        self._set_status_pill(state.label, state.color, pulse=state is ConnectionState.CONNECTED)
        self._status_pill.setToolTip(detail)

    def _set_status_pill(self, text: str, color: str, pulse: bool = False) -> None:
        self._status_text.setText(text)
        self._status_text.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600; background: transparent;")
        self._status_dot.set_color(color)
        self._status_dot.set_pulse(pulse)

    def _on_notice(self, message: str, level: str) -> None:
        if level == "error":
            self.terminal.append_error(message)
        elif level == "warning":
            self.terminal.append(EntryKind.WARNING, message)
        elif level == "success":
            self.terminal.append_success(message)
        else:
            self.terminal.append_notice(message)

    # -- external -----------------------------------------------------------
    def load_from_history(self, record) -> None:
        """Re-open a history entry in the terminal workspace."""
        self._on_clear()
        if record.request:
            self.terminal.append_prompt(record.request)
        self.terminal.append_command(record.command, record.shell.label, record.cwd)
        if record.output:
            self.terminal.append_output(record.output)
        if record.stderr:
            self.terminal.append_output(record.stderr, is_error=True)
        verdict = self.controller.reanalyze(record.command)
        suggestion = CommandSuggestion(
            request=record.request or "From history",
            command=record.command,
            shell=record.shell,
            explanation=record.explanation or "Restored from command history.",
            risk=verdict.risk,
            risk_reason=" ".join(verdict.reasons[:2]),
            generated_by="manual",
            model=record.model,
        )
        self.controller.set_suggestion(suggestion, verdict)
        self._prompt.setFocus()
