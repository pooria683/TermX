"""AI service: AI-vs-offline fallback, response parsing and safety override."""

from __future__ import annotations

import json

import pytest

from termx.core.ai_service import AIService
from termx.core.models import CommandSuggestion, RiskLevel, ShellType
from termx.core.ollama import OllamaError


class FakeClient:
    """Stand-in for the Ollama client with scripted answers."""

    def __init__(self, answer: str | None = None, *, online: bool = True, raises: bool = False) -> None:
        self.answer = answer
        self.online = online
        self.raises = raises
        self.calls: list[str] = []

    def ping(self):
        if not self.online:
            from termx.core.models import ConnectionState

            return ConnectionState.OFFLINE, "stubbed offline"
        from termx.core.models import ConnectionState

        return ConnectionState.CONNECTED, "stubbed online"

    def list_models(self):
        return []

    def resolve_model(self, preferred=None):
        if self.raises:
            raise OllamaError("no model")
        return preferred or "test-model"

    def chat(self, messages, model, **kwargs):
        self.calls.append(model)
        if self.raises:
            raise OllamaError("connection refused")
        return self.answer or ""

    def close(self):
        pass


def make_service(client) -> AIService:
    service = AIService(client=client)
    service.analyzer  # noqa: B018 - ensure the analyzer is constructed
    return service


VALID_PAYLOAD = json.dumps(
    {
        "command": "Get-ChildItem -File | Sort-Object Length -Descending | Select-Object -First 10",
        "explanation": "Lists the ten largest files in the current folder.",
        "risk": "safe",
        "risk_reason": "Only reads directory metadata.",
        "alternatives": ["Get-ChildItem | Sort-Object Length"],
    }
)


def test_ai_response_becomes_a_suggestion() -> None:
    service = make_service(FakeClient(VALID_PAYLOAD))
    outcome = service.generate_command("find the largest files", ShellType.POWERSHELL)

    assert outcome.ok
    assert outcome.suggestion is not None
    assert outcome.suggestion.command.startswith("Get-ChildItem")
    assert outcome.used_offline is False


def test_safety_overrides_an_optimistic_model() -> None:
    payload = json.dumps(
        {
            "command": "Remove-Item -Recurse -Force C:\\Windows",
            "explanation": "Cleans up Windows.",
            "risk": "safe",
        }
    )
    service = make_service(FakeClient(payload))
    outcome = service.generate_command("clean up windows", ShellType.POWERSHELL)

    assert outcome.suggestion is not None
    verdict = service.validate_suggestion(outcome.suggestion)
    assert verdict.risk in (RiskLevel.DESTRUCTIVE, RiskLevel.BLOCKED), "the static analyser must win"


def test_offline_fallback_when_the_model_is_unreachable() -> None:
    service = make_service(FakeClient(raises=True))
    outcome = service.generate_command("show all files in the current directory", ShellType.POWERSHELL)

    assert outcome.used_offline is True
    assert outcome.suggestion is not None
    assert "Get-ChildItem" in outcome.suggestion.command


def test_garbage_model_output_falls_back_cleanly() -> None:
    service = make_service(FakeClient("I am not sure what you mean, human."))
    outcome = service.generate_command("show all files in the current directory", ShellType.POWERSHELL)
    assert outcome.suggestion is not None
    assert outcome.ok


def test_unknown_request_offline_reports_an_error() -> None:
    service = make_service(FakeClient(raises=True))
    outcome = service.generate_command("write me a sonnet about middleware", ShellType.POWERSHELL)
    assert outcome.suggestion is None
    assert outcome.error


def test_answer_with_fenced_code_is_extracted() -> None:
    fenced = "Sure:\n\n```powershell\nGet-Process | Sort-Object CPU -Descending\n```\n\nThat shows CPU hogs."
    service = make_service(FakeClient(fenced))
    outcome = service.generate_command("which processes use the most cpu", ShellType.POWERSHELL)
    assert outcome.suggestion is not None
    assert "Get-Process" in outcome.suggestion.command


def test_explain_command_falls_back_offline() -> None:
    service = make_service(FakeClient(raises=True))
    text, used_offline = service.explain_command("Get-ChildItem", ShellType.POWERSHELL)
    assert used_offline is True
    assert text.strip()


def test_suggestion_model_validates_required_fields() -> None:
    with pytest.raises(Exception):
        CommandSuggestion()  # type: ignore[call-arg]
    suggestion = CommandSuggestion(request="list files", command="dir", shell=ShellType.CMD, explanation="Lists files.")
    assert suggestion.risk is RiskLevel.SAFE
