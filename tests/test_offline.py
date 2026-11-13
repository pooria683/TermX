"""Offline command engine: examples, intent matching and error explanations."""

from __future__ import annotations

import pytest

from termx.core.models import RiskLevel, ShellType
from termx.core.offline import OfflineEngine


@pytest.fixture(scope="module")
def engine() -> OfflineEngine:
    return OfflineEngine()


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("show all files in the current directory", "Get-ChildItem"),
        ("find the largest files in this folder", "Length"),
        ("check available disk space", "PSDrive"),
        ("list running processes using the most memory", "Process"),
        ("show the current git status", "git status"),
    ],
)
def test_common_requests_map_to_commands(engine: OfflineEngine, prompt: str, expected: str) -> None:
    suggestion = engine.suggest(prompt, ShellType.POWERSHELL)
    assert suggestion is not None, f"no offline fallback for {prompt!r}"
    assert expected.lower() in suggestion.command.lower()
    assert suggestion.explanation.strip()


def test_suggestions_are_shell_specific(engine: OfflineEngine) -> None:
    powershell = engine.suggest("show all files in the current directory", ShellType.POWERSHELL)
    bash = engine.suggest("show all files in the current directory", ShellType.BASH)
    assert powershell is not None and bash is not None
    assert powershell.command != bash.command
    assert bash.shell is ShellType.BASH


def test_unknown_request_returns_none(engine: OfflineEngine) -> None:
    assert engine.suggest("compose a haiku about semicolons", ShellType.POWERSHELL) is None


def test_examples_are_usable_prompts(engine: OfflineEngine) -> None:
    examples = engine.examples(limit=6)
    assert len(examples) == 6
    assert all(isinstance(text, str) and text for text in examples)
    # Every advertised example must actually work offline.
    for text in examples:
        assert engine.suggest(text, ShellType.POWERSHELL) is not None


@pytest.mark.parametrize(
    "stderr,expected_word",
    [
        ("'gti' is not recognized as an internal or external command", "misspelled"),
        ("Access to the path 'C:\\Windows' is denied", "permission"),
        ("The term 'Get-Foo' is not recognized as the name of a cmdlet", "not installed"),
        ("No such file or directory", "does not exist"),
    ],
)
def test_errors_are_explained_with_advice(engine: OfflineEngine, stderr: str, expected_word: str) -> None:
    explanation = engine.explain_error("gti status", stderr, exit_code=1)
    blob = " ".join([explanation.summary, explanation.cause, *explanation.suggestions]).lower()
    assert explanation.summary, "an explanation must always have a summary"
    assert expected_word.lower() in blob


def test_explanation_can_offer_a_corrected_command(engine: OfflineEngine) -> None:
    explanation = engine.explain_error("gti status", "'gti' is not recognized as an internal or external command", exit_code=1)
    assert explanation.corrected_command is None or isinstance(explanation.corrected_command, str)
    assert explanation.suggestions, "the user needs actionable next steps"
    assert explanation.source == "offline"


def test_read_only_offline_suggestions_are_safe(engine: OfflineEngine) -> None:
    suggestion = engine.suggest("show all files in the current directory", ShellType.POWERSHELL)
    assert suggestion is not None
    assert suggestion.risk is RiskLevel.SAFE
