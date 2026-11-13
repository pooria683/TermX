"""Application controller: the seam between UI pages and the core services.

Pages never talk to the database, the shell, or Ollama directly. They call
methods here, and this object re-emits Qt signals when state changes. That
keeps every long-running operation off the GUI thread and every rule about
"what may run" in exactly one place.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal

from termx.core.ai_service import AIService, GenerationOutcome
from termx.core.database import Database
from termx.core.models import (
    AppSettings,
    CommandRecord,
    CommandSuggestion,
    ConnectionState,
    ExecutionResult,
    ExecutionStatus,
    ModelInfo,
    RiskLevel,
    SafetyVerdict,
    SessionRecord,
    ShellType,
)
from termx.core.safety import SafetyAnalyzer
from termx.core.shell import (
    ShellRunner,
    available_shells,
    detect_default_shell,
    normalize_cwd,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------------- #
class _Worker(QThread):
    """Base worker: a QThread whose ``run`` executes one job.

    Subclassing ``QThread`` (instead of ``moveToThread``) keeps every QObject
    owned by the GUI thread, so signals are queued correctly and nothing is
    ever deleted from a background thread — the safest pattern for a desktop
    app that starts and stops short jobs constantly.
    """

    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class GenerateWorker(_Worker):
    """Runs command generation in a background thread."""

    generated = Signal(object)  # GenerationOutcome

    def __init__(
        self,
        service: AIService,
        request: str,
        shell: ShellType,
        cwd: str,
        recent: list[str],
    ) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._shell = shell
        self._cwd = cwd
        self._recent = recent

    def run(self) -> None:
        try:
            outcome = self._service.generate_command(self._request, self._shell, self._cwd, self._recent)
            if not self.cancelled:
                self.generated.emit(outcome)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Generation worker failed")
            if not self.cancelled:
                self.generated.emit(GenerationOutcome(None, error=str(exc)))


class ExecuteWorker(_Worker):
    """Runs a shell command off the GUI thread."""

    completed = Signal(object)  # ExecutionResult
    output_chunk = Signal(str, str)  # (stream, text)

    def __init__(self, runner: ShellRunner, command: str, shell: ShellType, cwd: str, timeout: int) -> None:
        super().__init__()
        self._runner = runner
        self._command = command
        self._shell = shell
        self._cwd = cwd
        self._timeout = timeout

    def run(self) -> None:
        try:
            result = self._runner.run(
                self._command,
                self._shell,
                self._cwd,
                self._timeout,
                on_output=lambda stream, text: None if self.cancelled else self.output_chunk.emit(stream, text),
            )
            if self.cancelled:
                result.status = ExecutionStatus.CANCELLED
            self.completed.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Execution worker failed")
            self.failed.emit(str(exc))
            self.completed.emit(
                ExecutionResult(
                    command=self._command,
                    shell=self._shell,
                    cwd=self._cwd,
                    exit_code=1,
                    stderr=f"TermX could not run the command: {exc}",
                    status=ExecutionStatus.FAILED,
                )
            )


class ExplainWorker(_Worker):
    explained = Signal(str, bool)  # text, used_offline

    def __init__(self, service: AIService, command: str, shell: ShellType) -> None:
        super().__init__()
        self._service = service
        self._command = command
        self._shell = shell

    def run(self) -> None:
        try:
            text, offline = self._service.explain_command(self._command, self._shell)
            if not self.cancelled:
                self.explained.emit(text, offline)
        except Exception as exc:
            self.failed.emit(str(exc))


class DiagnoseWorker(_Worker):
    diagnosed = Signal(object)  # ErrorExplanation

    def __init__(self, service: AIService, result: ExecutionResult) -> None:
        super().__init__()
        self._service = service
        self._result = result

    def run(self) -> None:
        try:
            explanation = self._service.explain_error(self._result)
            if not self.cancelled:
                self.diagnosed.emit(explanation)
        except Exception as exc:
            self.failed.emit(str(exc))


class StatusWorker(_Worker):
    """Health check + model listing."""

    status = Signal(object, str, list)  # (state, detail, models)

    def __init__(self, service: AIService) -> None:
        super().__init__()
        self._service = service

    def run(self) -> None:
        try:
            state, detail = self._service.check_connection()
            if self.cancelled:
                return
            models = self._service.list_models() if state is not ConnectionState.OFFLINE else []
            if not self.cancelled:
                self.status.emit(state, detail, models)
        except Exception as exc:
            if not self.cancelled:
                self.status.emit(ConnectionState.OFFLINE, str(exc), [])


class ChatWorker(_Worker):
    """Free-form AI answer, streamed token by token."""

    token = Signal(str)
    answered = Signal(str)

    def __init__(self, service: AIService, question: str, shell: ShellType) -> None:
        super().__init__()
        self._service = service
        self._question = question
        self._shell = shell

    def run(self) -> None:
        try:
            text = self._service.ask(
                self._question,
                self._shell,
                on_token=lambda t: None if self.cancelled else self.token.emit(t),
            )
            if not self.cancelled:
                self.answered.emit(text)
        except Exception as exc:
            self.failed.emit(str(exc))


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #
class AppController(QObject):
    """Owns application state and orchestrates background work."""

    # state change notifications
    suggestion_ready = Signal(object, object)  # CommandSuggestion, SafetyVerdict
    generation_failed = Signal(str)
    generation_started = Signal()
    generation_finished = Signal()

    execution_started = Signal(str)  # command
    execution_output = Signal(str, str)  # stream, text
    execution_finished = Signal(object)  # ExecutionResult
    execution_failed = Signal(str)

    connection_changed = Signal(object, str)  # ConnectionState, detail
    models_changed = Signal(list)  # list[ModelInfo]
    shell_changed = Signal(object)  # ShellType
    cwd_changed = Signal(str)
    settings_changed = Signal(object)  # AppSettings
    history_changed = Signal()
    sessions_changed = Signal()
    stream_chunk = Signal(str)  # AI streaming text
    stream_finished = Signal(str)
    explanation_ready = Signal(str, bool)
    diagnosis_ready = Signal(object)  # ErrorExplanation
    notice = Signal(str, str)  # message, level
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db = Database()
        self.settings: AppSettings = self.db.load_settings()
        self.runner = ShellRunner()
        self.analyzer = SafetyAnalyzer()
        self.ai = AIService(
            model=self.settings.model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            offline_fallback=self.settings.offline_fallback,
        )
        self.ai.configure(host=self.settings.ollama_host)

        self.connection_state = ConnectionState.UNKNOWN
        self.connection_detail = "Not checked yet"
        self.models: list[ModelInfo] = []
        self.cwd: str = str(normalize_cwd(os.getcwd()))
        self.shell: ShellType = self._initial_shell()
        self.session: SessionRecord = self._start_session()
        self.suggestion: CommandSuggestion | None = None
        self.verdict: SafetyVerdict | None = None
        self.last_result: ExecutionResult | None = None
        self._threads: list[QThread] = []
        self._workers: dict[int, _Worker] = {}
        self._busy = False
        self._shutting_down = False

    # -- bootstrap ----------------------------------------------------------
    def _initial_shell(self) -> ShellType:
        shells = available_shells()
        preferred = self.settings.preferred_shell
        if self.settings.auto_detect_shell:
            detected = detect_default_shell()
            return detected if detected in shells else shells[0]
        return preferred if preferred in shells else shells[0]

    def _start_session(self) -> SessionRecord:
        active = self.db.active_session()
        if active is not None and self.settings.remember_sessions:
            return active
        if active is not None:
            self.db.end_session(active.id, "Closed when TermX restarted.")
        session = SessionRecord(
            title=f"Session {datetime.now(UTC).strftime('%d %b %Y, %H:%M')}",
            shell=self.shell,
            cwd=str(self.cwd),
        )
        self.db.create_session(session)
        return session

    # -- thread plumbing ----------------------------------------------------
    def _run_worker(self, worker: _Worker, *, busy: bool = False) -> None:
        """Start ``worker`` and keep a reference until it finishes."""
        if busy:
            self._set_busy(True)
            worker.finished.connect(lambda: self._set_busy(False), Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(lambda: self._retire_worker(worker), Qt.ConnectionType.QueuedConnection)
        self._threads.append(worker)
        self._workers[id(worker)] = worker
        worker.start()

    def _retire_worker(self, worker: _Worker) -> None:
        """Drop our reference to a finished worker on the GUI thread.

        ``QThread`` objects are not deleted eagerly: ``deleteLater()`` on a
        thread whose finished signal is still being delivered is a classic
        use-after-free. Once our reference goes away Python frees it naturally.
        """
        self._threads = [thread for thread in self._threads if thread is not worker]
        self._workers.pop(id(worker), None)
        worker.setParent(None) if worker.parent() is not None else None

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def shutdown(self) -> None:
        """Stop background jobs and flush state before the window closes.

        Workers override ``run()``, so ``quit()`` has no effect — they must be
        cancelled and then *waited for*. A thread still inside an httpx call
        when the interpreter finalises is exactly what produces the
        ``none_dealloc`` fatal error at exit, so waiting is not optional.
        """
        if self._shutting_down:
            return
        self._shutting_down = True

        workers = list(self._workers.values())
        for worker in workers:
            try:
                worker.cancel()
            except RuntimeError:  # already deleted by Qt
                continue
        for worker in workers:
            try:
                if not worker.isFinished():
                    worker.wait(6000)
            except RuntimeError:
                pass
        self._threads.clear()
        self._workers.clear()
        try:
            self.db.end_session(self.session.id, self.session.summary or "App closed.")
            self.db.prune_history(self.settings.max_history)
        except Exception:
            log.exception("Could not finalise session state")
        self.ai.client.close()
        self.db.close()

    # -- settings -----------------------------------------------------------
    def update_settings(self, settings: AppSettings) -> None:
        previous_model = self.settings.model
        self.settings = settings
        self.db.save_settings(settings)
        self.ai.configure(
            model=settings.model,
            host=settings.ollama_host,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            offline_fallback=settings.offline_fallback,
        )
        if settings.model != previous_model:
            self.db.mark_model_used(settings.model)
        self.settings_changed.emit(settings)

    def set_shell(self, shell: ShellType) -> None:
        if shell == self.shell:
            return
        self.shell = shell
        self.settings.preferred_shell = shell
        self.db.save_settings(self.settings)
        self.shell_changed.emit(shell)

    def set_cwd(self, path: str) -> None:
        resolved = normalize_cwd(path)
        self.cwd = str(resolved)
        self.session.cwd = self.cwd
        self.db.update_session(self.session)
        self.cwd_changed.emit(self.cwd)

    @property
    def version(self) -> str:
        from termx import APP_VERSION

        return APP_VERSION

    # -- AI status ----------------------------------------------------------
    def refresh_ai_status(self) -> None:
        worker = StatusWorker(self.ai)
        worker.status.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self._run_worker(worker)

    def _on_status(self, state: ConnectionState, detail: str, models: list[ModelInfo]) -> None:
        if self._shutting_down:
            return
        self.connection_state = state
        self.connection_detail = detail
        self.connection_changed.emit(state, detail)
        if models:
            self.models = models
            self.db.save_models(models)
            self.models_changed.emit(models)

    # -- generation ---------------------------------------------------------
    def generate(self, request: str) -> None:
        request = request.strip()
        if not request:
            return
        if self._busy:
            self.notice.emit("TermX is already working on a request.", "warning")
            return
        recent = [r.command for r in self.db.list_commands(limit=5)]
        worker = GenerateWorker(self.ai, request, self.shell, self.cwd, recent)
        worker.generated.connect(self._on_generated, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self.generation_finished.emit, Qt.ConnectionType.QueuedConnection)
        self.generation_started.emit()
        self._run_worker(worker, busy=True)

    def _on_generated(self, outcome: GenerationOutcome) -> None:
        if self._shutting_down:
            return
        if not outcome.ok or outcome.suggestion is None:
            self.generation_failed.emit(outcome.error or "TermX could not generate a command.")
            return
        suggestion = outcome.suggestion
        verdict = self.ai.validate_suggestion(suggestion)
        self.suggestion = suggestion
        self.verdict = verdict
        if outcome.used_offline and outcome.error:
            self.notice.emit("AI unavailable — used the offline command library.", "warning")
        self.suggestion_ready.emit(suggestion, verdict)

    def set_suggestion(self, suggestion: CommandSuggestion, verdict: SafetyVerdict) -> None:
        """Adopt an existing suggestion (e.g. 'run again' from history)."""
        self.suggestion = suggestion
        self.verdict = verdict
        self.suggestion_ready.emit(suggestion, verdict)

    def reanalyze(self, command: str) -> SafetyVerdict:
        verdict = self.analyzer.analyze(command, self.shell)
        self.verdict = verdict
        return verdict

    def explain(self, command: str) -> None:
        worker = ExplainWorker(self.ai, command, self.shell)
        worker.explained.connect(self.explanation_ready.emit, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(
            lambda msg: self.notice.emit(f"Explanation failed: {msg}", "error"),
            Qt.ConnectionType.QueuedConnection,
        )
        self._run_worker(worker, busy=True)

    def ask(self, question: str) -> None:
        worker = ChatWorker(self.ai, question, self.shell)
        worker.token.connect(self.stream_chunk.emit, Qt.ConnectionType.QueuedConnection)
        worker.answered.connect(self.stream_finished.emit, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(
            lambda msg: self.notice.emit(f"AI error: {msg}", "error"),
            Qt.ConnectionType.QueuedConnection,
        )
        self._run_worker(worker, busy=True)

    # -- execution ----------------------------------------------------------
    def execute(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        verdict = self.analyzer.analyze(command, self.shell)

        if verdict.blocked and self.settings.block_forbidden:
            blocked = ExecutionResult(
                command=command,
                shell=self.shell,
                cwd=self.cwd,
                exit_code=None,
                stderr="TermX blocked this command: " + " ".join(verdict.reasons),
                status=ExecutionStatus.BLOCKED,
                was_blocked=True,
            )
            self._persist(command, blocked, request=self.suggestion.request if self.suggestion else "")
            self.execution_started.emit(command)
            self.execution_finished.emit(blocked)
            self.notice.emit("Command blocked by the safety policy.", "error")
            return

        self._set_busy(True)
        self.execution_started.emit(command)
        worker = ExecuteWorker(self.runner, command, self.shell, self.cwd, self.settings.timeout_seconds)
        worker.output_chunk.connect(self.execution_output.emit, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(lambda result: self._on_execution_done(command, result), Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self.execution_failed.emit, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(lambda: self._set_busy(False), Qt.ConnectionType.QueuedConnection)
        self._run_worker(worker)

    def _on_execution_done(self, command: str, result: ExecutionResult) -> None:
        if self._shutting_down:
            return
        self.last_result = result
        record_request = self.suggestion.request if self.suggestion and self.suggestion.command else ""
        self._persist(command, result, request=record_request)
        self.execution_finished.emit(result)
        self.history_changed.emit()
        self.sessions_changed.emit()

        if result.status is ExecutionStatus.SUCCESS and result.stdout:
            self._maybe_update_cwd(command, result)

        should_diagnose = (
            result.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED)
            and self.settings.auto_explain_errors
            and (result.stderr.strip() or result.stdout.strip())
        )
        if should_diagnose:
            self.diagnose(result)

    def _maybe_update_cwd(self, command: str, result: ExecutionResult) -> None:
        """Track `cd`-style commands so the status bar stays accurate."""
        stripped = command.strip().split()
        if not stripped:
            return
        head = stripped[0].lower()
        if head in ("cd", "set-location", "sl", "chdir", "pushd") and len(stripped) > 1:
            target = " ".join(stripped[1:]).strip("'\"")
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = Path(self.cwd) / candidate
            if candidate.is_dir():
                self.set_cwd(str(candidate))

    def _persist(self, command: str, result: ExecutionResult, request: str = "") -> None:
        suggestion = self.suggestion
        record = CommandRecord(
            session_id=self.session.id,
            request=request,
            command=command,
            shell=result.shell,
            explanation=suggestion.explanation if suggestion and suggestion.command == command else "",
            risk=(
                suggestion.risk
                if suggestion and suggestion.command == command
                else (self.verdict.risk if self.verdict else RiskLevel.SAFE)
            ),
            status=result.status,
            exit_code=result.exit_code,
            cwd=result.cwd or self.cwd,
            output=result.stdout[-100_000:],
            stderr=result.stderr[-50_000:],
            duration_ms=result.duration_ms,
            was_blocked=result.was_blocked,
            model=suggestion.model if suggestion and suggestion.command == command else "",
        )
        self.db.add_command(record)
        self.session.command_count += 1
        if result.status is ExecutionStatus.SUCCESS:
            self.session.success_count += 1
        elif result.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED):
            self.session.failure_count += 1

    def cancel_execution(self) -> None:
        for worker in self._workers.values():
            if isinstance(worker, ExecuteWorker):
                worker.cancel()

    def diagnose(self, result: ExecutionResult) -> None:
        worker = DiagnoseWorker(self.ai, result)
        worker.diagnosed.connect(self.diagnosis_ready.emit, Qt.ConnectionType.QueuedConnection)
        self._run_worker(worker)

    # -- history ------------------------------------------------------------
    def history(self, limit: int = 200, offset: int = 0, search: str = "", favorites_only: bool = False) -> list[CommandRecord]:
        if self._shutting_down:
            return []
        return self.db.list_commands(limit, offset, search, favorites_only=favorites_only)

    def toggle_favorite(self, command_id: int) -> bool:
        value = self.db.toggle_favorite(command_id)
        self.history_changed.emit()
        return value

    def delete_history_entry(self, command_id: int) -> None:
        self.db.delete_command(command_id)
        self.history_changed.emit()

    def clear_history(self, keep_favorites: bool = True) -> int:
        removed = self.db.clear_history(keep_favorites)
        self.history_changed.emit()
        return removed

    def stats(self):
        if self._shutting_down:
            from termx.core.models import DashboardStats

            return DashboardStats()
        return self.db.stats()

    def export_history(self, path: str, fmt: str = "json") -> int:
        return self.db.export_commands(path, fmt)

    # -- sessions -----------------------------------------------------------
    def sessions(self, limit: int = 200) -> list[SessionRecord]:
        return self.db.list_sessions(limit)

    def new_session(self, title: str | None = None) -> SessionRecord:
        self.db.end_session(self.session.id, self.session.summary or "Ended.")
        session = SessionRecord(
            title=title or f"Session {datetime.now(UTC).strftime('%d %b %Y, %H:%M')}",
            shell=self.shell,
            cwd=self.cwd,
        )
        self.db.create_session(session)
        self.session = session
        self.sessions_changed.emit()
        return session

    def rename_session(self, session_id: str, title: str) -> None:
        self.db.rename_session(session_id, title)
        if session_id == self.session.id:
            self.session.title = title
        self.sessions_changed.emit()

    def delete_session(self, session_id: str) -> None:
        if session_id == self.session.id:
            self.new_session()
        self.db.delete_session(session_id)
        self.sessions_changed.emit()

    def session_commands(self, session_id: str) -> list[CommandRecord]:
        return self.db.list_commands(limit=1000, session_id=session_id)

    # -- misc ---------------------------------------------------------------
    def copy_text(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)
        self.notice.emit("Copied to clipboard.", "success")

    def platform_label(self) -> str:
        if sys.platform == "win32":
            return "Windows"
        if sys.platform == "darwin":
            return "macOS"
        return "Linux"
