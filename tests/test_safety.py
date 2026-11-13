"""Safety analysis: the gate that stops destructive commands."""

from __future__ import annotations

import pytest

from termx.core.models import RiskLevel, SafetyVerdict, ShellType
from termx.core.safety import SafetyAnalyzer


@pytest.fixture(scope="module")
def analyzer() -> SafetyAnalyzer:
    return SafetyAnalyzer()


READ_ONLY = [
    "Get-ChildItem",
    "ls -la",
    "Get-Process",
    "Get-ChildItem -Force | Format-Table Mode, LastWriteTime, Name",
    "git status",
    "git log --oneline -20",
    "Get-PSDrive -PSProvider FileSystem",
    "whoami",
    "Get-ChildItem -Recurse | Sort-Object Length -Descending | Select-Object -First 10",
]


@pytest.mark.parametrize("command", READ_ONLY)
def test_read_only_commands_are_not_destructive(analyzer: SafetyAnalyzer, command: str) -> None:
    verdict = analyzer.analyze(command, ShellType.POWERSHELL)
    assert isinstance(verdict, SafetyVerdict)
    assert verdict.risk is not RiskLevel.DESTRUCTIVE
    assert not verdict.blocked


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item -Recurse -Force C:\\Windows",
        "rm -rf /",
        "del /f /s /q C:\\*",
        "Format-Volume -DriveLetter D",
        "Format D: /fs:NTFS",
    ],
)
def test_destructive_commands_are_flagged(analyzer: SafetyAnalyzer, command: str) -> None:
    verdict = analyzer.analyze(command, ShellType.POWERSHELL)
    assert verdict.risk in (RiskLevel.DESTRUCTIVE, RiskLevel.BLOCKED)
    assert verdict.requires_confirmation


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item -Recurse -Force /",
        "rm -rf --no-preserve-root /",
        "format C:",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
    ],
)
def test_catastrophic_commands_are_blocked(analyzer: SafetyAnalyzer, command: str) -> None:
    verdict = analyzer.analyze(command, ShellType.BASH)
    assert verdict.blocked is True
    assert verdict.risk is RiskLevel.BLOCKED
    assert verdict.reasons, "a blocked command must explain why"


def test_empty_command_is_safe_but_confirmed(analyzer: SafetyAnalyzer) -> None:
    verdict = analyzer.analyze("   ")
    assert verdict.risk is RiskLevel.SAFE
    assert verdict.reasons


def test_verdicts_merge_to_the_worst_risk(analyzer: SafetyAnalyzer) -> None:
    safe = SafetyVerdict(risk=RiskLevel.SAFE, reasons=["read only"])
    scary = SafetyVerdict(risk=RiskLevel.DESTRUCTIVE, reasons=["deletes files"], requires_confirmation=True)
    merged = safe.merged(scary)
    assert merged.risk is RiskLevel.DESTRUCTIVE
    assert "deletes files" in merged.reasons
    assert merged.requires_confirmation


def test_blocked_flag_survives_merge() -> None:
    blocked = SafetyVerdict(risk=RiskLevel.BLOCKED, blocked=True, reasons=["forbidden"])
    merged = blocked.merged(SafetyVerdict(risk=RiskLevel.SAFE))
    assert merged.blocked is True


def test_is_read_only_helper(analyzer: SafetyAnalyzer) -> None:
    assert analyzer.is_read_only("Get-ChildItem", ShellType.POWERSHELL)
    assert not analyzer.is_read_only("Remove-Item build -Recurse", ShellType.POWERSHELL)


def test_analyzer_is_deterministic(analyzer: SafetyAnalyzer) -> None:
    command = "Remove-Item -Recurse -Force .\\dist"
    first, second = analyzer.analyze(command), analyzer.analyze(command)
    assert first.risk is second.risk
    assert first.reasons == second.reasons
