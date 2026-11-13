"""Pydantic domain models shared across TermX layers.

Every object that crosses a layer boundary (AI -> service -> UI -> database)
is validated here so malformed data cannot reach the shell or the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ShellType(str, Enum):
    """Shell flavours TermX can target."""

    POWERSHELL = "powershell"
    CMD = "cmd"
    BASH = "bash"
    ZSH = "zsh"

    @property
    def label(self) -> str:
        return {
            ShellType.POWERSHELL: "PowerShell",
            ShellType.CMD: "Command Prompt",
            ShellType.BASH: "Bash",
            ShellType.ZSH: "Zsh",
        }[self]

    @property
    def executable(self) -> str:
        return {
            ShellType.POWERSHELL: "powershell.exe",
            ShellType.CMD: "cmd.exe",
            ShellType.BASH: "/bin/bash",
            ShellType.ZSH: "/bin/zsh",
        }[self]

    @property
    def extension(self) -> str:
        return "ps1" if self is ShellType.POWERSHELL else ("bat" if self is ShellType.CMD else "sh")

    @property
    def is_posix(self) -> bool:
        return self in (ShellType.BASH, ShellType.ZSH)


class RiskLevel(str, Enum):
    """How dangerous a command is judged to be."""

    SAFE = "safe"
    CAUTION = "caution"
    DESTRUCTIVE = "destructive"
    BLOCKED = "blocked"

    @property
    def label(self) -> str:
        return {
            RiskLevel.SAFE: "Read-only",
            RiskLevel.CAUTION: "Caution",
            RiskLevel.DESTRUCTIVE: "Destructive",
            RiskLevel.BLOCKED: "Blocked",
        }[self]

    @property
    def color(self) -> str:
        return {
            RiskLevel.SAFE: "#2DD4BF",
            RiskLevel.CAUTION: "#FBBF24",
            RiskLevel.DESTRUCTIVE: "#F87171",
            RiskLevel.BLOCKED: "#EF4444",
        }[self]


class ExecutionStatus(str, Enum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        return {
            ExecutionStatus.AWAITING_CONFIRMATION: "Awaiting confirmation",
            ExecutionStatus.RUNNING: "Running",
            ExecutionStatus.SUCCESS: "Success",
            ExecutionStatus.FAILED: "Failed",
            ExecutionStatus.BLOCKED: "Blocked",
            ExecutionStatus.CANCELLED: "Cancelled",
        }[self]

    @property
    def color(self) -> str:
        return {
            ExecutionStatus.AWAITING_CONFIRMATION: "#FBBF24",
            ExecutionStatus.RUNNING: "#60A5FA",
            ExecutionStatus.SUCCESS: "#34D399",
            ExecutionStatus.FAILED: "#F87171",
            ExecutionStatus.BLOCKED: "#EF4444",
            ExecutionStatus.CANCELLED: "#94A3B8",
        }[self]


class ConnectionState(str, Enum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    OFFLINE = "offline"

    @property
    def label(self) -> str:
        return {
            ConnectionState.UNKNOWN: "Checking",
            ConnectionState.CONNECTED: "AI online",
            ConnectionState.DEGRADED: "Degraded",
            ConnectionState.OFFLINE: "AI offline",
        }[self]

    @property
    def color(self) -> str:
        return {
            ConnectionState.UNKNOWN: "#64748B",
            ConnectionState.CONNECTED: "#34D399",
            ConnectionState.DEGRADED: "#FBBF24",
            ConnectionState.OFFLINE: "#F87171",
        }[self]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class StrictModel(BaseModel):
    """Base model: extra fields rejected, enum values serialised."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# AI / generation
# --------------------------------------------------------------------------- #
class CommandSuggestion(StrictModel):
    """A command proposed by the AI for a natural-language request."""

    id: str = Field(default_factory=lambda: _new_id("cmd"))
    request: str = Field(min_length=1, max_length=4000)
    command: str = Field(min_length=1, max_length=20000)
    shell: ShellType = ShellType.POWERSHELL
    explanation: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    risk_reason: str = ""
    alternative: str | None = None
    notes: list[str] = Field(default_factory=list)
    model: str = ""
    generated_by: Literal["ai", "offline", "manual"] = "ai"
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("command")
    @classmethod
    def _strip_fences(cls, value: str) -> str:
        """Defensively strip markdown fences that models sometimes add."""
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        for prefix in ("PS> ", "PS C:\\> ", "$ ", "> "):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
        return text


class AIResponse(StrictModel):
    """Structured reply returned by the AI provider."""

    answer: str = ""
    command: str = ""
    shell: ShellType = ShellType.POWERSHELL
    explanation: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    risk_reason: str = ""
    alternative: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_content(self) -> AIResponse:
        if not self.answer and not self.command:
            raise ValueError("AI response must contain an answer or a command")
        return self


class ErrorExplanation(StrictModel):
    """Human explanation of a failed command, produced by AI or the offline engine."""

    summary: str
    cause: str = ""
    suggestions: list[str] = Field(default_factory=list)
    corrected_command: str | None = None
    source: Literal["ai", "offline", "none"] = "offline"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
class ExecutionResult(StrictModel):
    """Outcome of one shell execution."""

    execution_id: str = Field(default_factory=lambda: _new_id("run"))
    command: str
    shell: ShellType = ShellType.POWERSHELL
    cwd: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    status: ExecutionStatus = ExecutionStatus.SUCCESS
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=_utcnow)
    was_blocked: bool = False
    truncated: bool = False

    @property
    def combined_output(self) -> str:
        parts = [p for p in (self.stdout, self.stderr) if p]
        return "\n".join(parts)


class SafetyVerdict(StrictModel):
    """Result of static safety analysis of a command."""

    risk: RiskLevel = RiskLevel.SAFE
    reasons: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    blocked: bool = False
    matched_rules: list[str] = Field(default_factory=list)

    def merged(self, other: SafetyVerdict) -> SafetyVerdict:
        order = {RiskLevel.SAFE: 0, RiskLevel.CAUTION: 1, RiskLevel.DESTRUCTIVE: 2, RiskLevel.BLOCKED: 3}
        worst = self if order[self.risk] >= order[other.risk] else other
        return SafetyVerdict(
            risk=worst.risk,
            reasons=list(dict.fromkeys([*self.reasons, *other.reasons])),
            requires_confirmation=self.requires_confirmation or other.requires_confirmation,
            blocked=self.blocked or other.blocked,
            matched_rules=list(dict.fromkeys([*self.matched_rules, *other.matched_rules])),
        )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
class CommandRecord(StrictModel):
    """A single row of command history."""

    id: int | None = None
    session_id: str | None = None
    request: str = ""
    command: str
    shell: ShellType = ShellType.POWERSHELL
    explanation: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    status: ExecutionStatus = ExecutionStatus.SUCCESS
    exit_code: int | None = None
    cwd: str = ""
    output: str = ""
    stderr: str = ""
    duration_ms: int = 0
    was_blocked: bool = False
    favorite: bool = False
    model: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class SessionRecord(StrictModel):
    """A terminal session grouping executed commands."""

    id: str = Field(default_factory=lambda: _new_id("sess"))
    title: str = "New session"
    shell: ShellType = ShellType.POWERSHELL
    cwd: str = ""
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    command_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    is_active: bool = True
    summary: str = ""

    @property
    def duration_seconds(self) -> int:
        end = self.ended_at or _utcnow()
        return max(0, int((end - self.started_at).total_seconds()))


class ModelInfo(StrictModel):
    """Metadata about an Ollama model available locally."""

    name: str
    size_bytes: int = 0
    parameter_size: str = ""
    quantization: str = ""
    family: str = ""
    modified_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return self.name.split(":")[0]

    @property
    def size_label(self) -> str:
        if self.size_bytes <= 0:
            return "—"
        gib = self.size_bytes / (1024**3)
        return f"{gib:.1f} GB"


class AppSettings(StrictModel):
    """User-configurable application settings (persisted in the database)."""

    model: str = "qwen2.5-coder:7b"
    ollama_host: str = "http://localhost:11434"
    temperature: float = Field(default=0.15, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    preferred_shell: ShellType = ShellType.POWERSHELL
    auto_detect_shell: bool = True
    confirm_execution: bool = True
    confirm_destructive: bool = True
    block_forbidden: bool = True
    auto_explain_errors: bool = True
    stream_output: bool = True
    timeout_seconds: int = Field(default=120, ge=5, le=3600)
    max_history: int = Field(default=2000, ge=50, le=100000)
    remember_sessions: bool = True
    font_size: int = Field(default=13, ge=9, le=24)
    reduce_motion: bool = False
    show_sidebar_labels: bool = True
    offline_fallback: bool = True


class DashboardStats(StrictModel):
    """Aggregated metrics rendered on the dashboard."""

    total_commands: int = 0
    successful: int = 0
    failed: int = 0
    blocked: int = 0
    sessions: int = 0
    ai_commands: int = 0
    favorites: int = 0
    avg_duration_ms: float = 0.0
    success_rate: float = 0.0
    by_shell: dict[str, int] = Field(default_factory=dict)
    daily_counts: dict[str, int] = Field(default_factory=dict)
    top_requests: list[dict[str, Any]] = Field(default_factory=list)
    recent: list[CommandRecord] = Field(default_factory=list)
