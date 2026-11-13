"""AI orchestration layer.

Combines the Ollama client, prompt builders, the safety analyzer, and the
offline engine into a single service the UI can call without knowing any of
the details.

Every AI-generated command passes through :meth:`AIService.validate_suggestion`
so the risk shown to the user is *never* taken on trust from the model.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from termx.core.models import (
    AIResponse,
    CommandSuggestion,
    ConnectionState,
    ErrorExplanation,
    ExecutionResult,
    ModelInfo,
    RiskLevel,
    SafetyVerdict,
    ShellType,
)
from termx.core.offline import OfflineEngine
from termx.core.ollama import (
    OllamaClient,
    OllamaError,
    OllamaModelMissing,
    OllamaUnavailable,
    extract_json,
)
from termx.core.prompts import (
    PromptContext,
    build_error_messages,
    build_explain_messages,
    build_messages,
    build_summary_prompt,
)
from termx.core.safety import SafetyAnalyzer

log = logging.getLogger(__name__)


@dataclass
class GenerationOutcome:
    """Result of a generation request, including how it was produced."""

    suggestion: CommandSuggestion | None
    error: str | None = None
    used_offline: bool = False
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.suggestion is not None


class AIService:
    """High-level AI operations for the application."""

    def __init__(
        self,
        client: OllamaClient | None = None,
        analyzer: SafetyAnalyzer | None = None,
        offline: OfflineEngine | None = None,
        model: str = "qwen2.5-coder:7b",
        temperature: float = 0.15,
        max_tokens: int = 1024,
        offline_fallback: bool = True,
    ) -> None:
        self.client = client or OllamaClient()
        self.analyzer = analyzer or SafetyAnalyzer()
        self.offline = offline or OfflineEngine()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.offline_fallback = offline_fallback
        self._last_error: str | None = None

    # -- configuration ------------------------------------------------------
    def configure(
        self,
        *,
        model: str | None = None,
        host: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        offline_fallback: bool | None = None,
    ) -> None:
        if host:
            self.client.set_host(host)
        if model:
            self.model = model
        if temperature is not None:
            self.temperature = temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if offline_fallback is not None:
            self.offline_fallback = offline_fallback

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # -- health -------------------------------------------------------------
    def check_connection(self) -> tuple[ConnectionState, str]:
        return self.client.ping()

    def list_models(self) -> list[ModelInfo]:
        try:
            return self.client.list_models()
        except OllamaError as exc:
            self._last_error = str(exc)
            return []

    def resolve_model(self) -> str | None:
        try:
            return self.client.resolve_model(self.model)
        except OllamaError:
            return None

    # -- generation ---------------------------------------------------------
    def generate_command(
        self,
        request: str,
        shell: ShellType = ShellType.POWERSHELL,
        cwd: str = "",
        recent: list[str] | None = None,
    ) -> GenerationOutcome:
        """Turn a natural-language request into a validated suggestion."""
        text = (request or "").strip()
        if not text:
            return GenerationOutcome(None, error="Enter a request first.")

        context = PromptContext(shell=shell, cwd=cwd or "~", recent_commands=tuple(recent or ()))
        try:
            model = self.client.resolve_model(self.model)
            raw = self.client.chat(
                build_messages(text, context),
                model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                format_json=True,
            )
            parsed = self._parse_response(raw)
            if parsed is None:
                raise ValueError("The model returned an unusable response.")
            suggestion = self._build_suggestion(parsed, text, shell, model, generated_by="ai")
            self._last_error = None
            return GenerationOutcome(suggestion, raw=raw)
        except OllamaModelMissing as exc:
            self._last_error = str(exc)
        except OllamaUnavailable as exc:
            self._last_error = str(exc)
        except (OllamaError, ValueError, KeyError) as exc:
            self._last_error = f"The AI response could not be parsed ({exc})."
        except Exception as exc:  # defensive: never crash the UI thread
            log.exception("Unexpected generation failure")
            self._last_error = f"Unexpected AI error: {exc}"

        fallback = self._offline_fallback(text, shell)
        if fallback is not None:
            return GenerationOutcome(fallback, error=self._last_error, used_offline=True)
        return GenerationOutcome(None, error=self._last_error or "Command generation failed.")

    def _offline_fallback(self, request: str, shell: ShellType) -> CommandSuggestion | None:
        if not self.offline_fallback:
            return None
        suggestion = self.offline.suggest(request, shell)
        if suggestion is None:
            return None
        verdict = self.validate_suggestion(suggestion)
        suggestion.risk = verdict.risk
        if verdict.reasons:
            suggestion.risk_reason = " ".join(verdict.reasons[:2])
        return suggestion

    @staticmethod
    def _parse_response(raw: str) -> AIResponse | None:
        data = extract_json(raw)
        if not data:
            return None
        if "command" not in data and "answer" not in data:
            return None
        try:
            return AIResponse(
                answer=str(data.get("answer") or "").strip(),
                command=str(data.get("command") or "").strip(),
                shell=ShellType(str(data.get("shell") or "powershell").lower())
                if str(data.get("shell") or "").lower() in ShellType._value2member_map_
                else ShellType.POWERSHELL,
                explanation=str(data.get("explanation") or "").strip(),
                risk=SafetyAnalyzer.risk_from_label(str(data.get("risk") or "safe")),
                risk_reason=str(data.get("risk_reason") or "").strip(),
                alternative=(str(data["alternative"]).strip() or None) if data.get("alternative") else None,
                notes=[str(n) for n in (data.get("notes") or []) if str(n).strip()][:6],
            )
        except Exception as exc:
            log.debug("Could not validate AI response: %s", exc)
            return None

    def _build_suggestion(
        self, response: AIResponse, request: str, shell: ShellType, model: str, generated_by: str
    ) -> CommandSuggestion:
        command = response.command or self._command_from_answer(response.answer) or ""
        explanation = response.explanation or response.answer or ""
        suggestion = CommandSuggestion(
            request=request,
            command=command or "",
            shell=shell,
            explanation=explanation,
            risk=response.risk,
            risk_reason=response.risk_reason,
            alternative=response.alternative,
            notes=response.notes,
            model=model,
            generated_by=generated_by,  # type: ignore[arg-type]
        )
        if not command:
            suggestion.notes = [*suggestion.notes, "The model did not propose a runnable command."]
            return suggestion
        verdict = self.validate_suggestion(suggestion)
        suggestion.risk = verdict.risk
        if verdict.reasons:
            stated = f"Model assessment: {response.risk_reason or response.risk.label}."
            suggestion.risk_reason = f"{stated} TermX safety scan: {' '.join(verdict.reasons[:2])}"
        return suggestion

    @staticmethod
    def _command_from_answer(answer: str) -> str | None:
        """Recover a command when the model answered in prose."""
        for line in (answer or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(("command:", "run:")):
                return stripped.split(":", 1)[1].strip().strip("`") or None
        fenced = re.search(r"```[a-zA-Z]*\n(.+?)```", answer or "", re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        return None

    # -- validation ---------------------------------------------------------
    def validate_suggestion(self, suggestion: CommandSuggestion) -> SafetyVerdict:
        """Static safety scan; the verdict overrides the model's own label."""
        if not suggestion.command:
            return SafetyVerdict(risk=RiskLevel.SAFE, reasons=[], requires_confirmation=False)
        return self.analyzer.analyze(suggestion.command, suggestion.shell)

    def analyze_command(self, command: str, shell: ShellType) -> SafetyVerdict:
        return self.analyzer.analyze(command, shell)

    # -- explanation --------------------------------------------------------
    def explain_command(self, command: str, shell: ShellType) -> tuple[str, bool]:
        """Explain a command. Returns ``(text, used_offline)``."""
        try:
            model = self.client.resolve_model(self.model)
            text = self.client.chat(
                build_explain_messages(command, shell),
                model,
                temperature=0.2,
                max_tokens=512,
            )
            if text.strip():
                return text.strip(), False
        except OllamaError as exc:
            self._last_error = str(exc)
        return self._offline_explanation(command, shell), True

    @staticmethod
    def _offline_explanation(command: str, shell: ShellType) -> str:
        parts: list[str] = []
        tokens = [t for t in re.split(r"\s+", command.strip()) if t]
        if not tokens:
            return "There is no command to explain."
        head = tokens[0]
        flags = [t for t in tokens[1:] if t.startswith("-") or t.startswith("/")]
        parts.append(f"This runs `{head}` in {shell.label}.")
        if flags:
            parts.append("Arguments and switches used: " + ", ".join(f"`{f}`" for f in flags) + ".")
        lowered = command.lower()
        if any(k in lowered for k in ("remove-item", "rm ", "del ", "rmdir", "rd /s")):
            parts.append("It deletes files or folders, so double-check the path before running it.")
        elif any(k in lowered for k in ("get-", "ls", "dir", "cat", "type", "find", "grep", "select-")):
            parts.append("It only reads information and does not modify anything.")
        else:
            parts.append("Review the preview to confirm the effect before running it.")
        return " ".join(parts)

    # -- error diagnosis ----------------------------------------------------
    def explain_error(self, result: ExecutionResult) -> ErrorExplanation:
        try:
            model = self.client.resolve_model(self.model)
            raw = self.client.chat(
                build_error_messages(result.command, result.shell, result.cwd, result.exit_code, result.stdout, result.stderr),
                model,
                temperature=0.1,
                max_tokens=600,
                format_json=True,
            )
            data = extract_json(raw)
            if data.get("summary"):
                return ErrorExplanation(
                    summary=str(data.get("summary")),
                    cause=str(data.get("cause") or ""),
                    suggestions=[str(s) for s in (data.get("suggestions") or [])][:5],
                    corrected_command=(str(data.get("corrected_command") or "").strip() or None),
                    source="ai",
                    confidence=float(data.get("confidence") or 0.7),
                )
        except (OllamaError, ValueError, TypeError) as exc:
            self._last_error = str(exc)
        return self.offline.explain_error(result.command, result.stderr, result.stdout, result.exit_code, result.shell)

    # -- misc ---------------------------------------------------------------
    def summarize_session(self, title: str, commands: list[str]) -> str:
        if not commands:
            return "No commands were executed in this session."
        try:
            model = self.client.resolve_model(self.model)
            return self.client.chat(build_summary_prompt(title, commands), model, temperature=0.3, max_tokens=180).strip()
        except OllamaError:
            pass
        return f"{len(commands)} command{'s' if len(commands) != 1 else ''} executed in this session."

    def ask(self, question: str, shell: ShellType, on_token: Callable[[str], None] | None = None) -> str:
        """Free-form question answering, streaming tokens through ``on_token``."""
        try:
            model = self.client.resolve_model(self.model)
        except OllamaError as exc:
            raise OllamaUnavailable(str(exc)) from exc
        messages = [
            {"role": "system", "content": f"You are TermX, a concise terminal assistant. Use {shell.label} syntax."},
            {"role": "user", "content": question.strip()},
        ]
        chunks: list[str] = []
        for token in self.client.chat_stream(messages, model, temperature=self.temperature, max_tokens=self.max_tokens):
            chunks.append(token)
            if on_token:
                on_token(token)
        return "".join(chunks)
