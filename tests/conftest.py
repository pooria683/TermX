"""Shared fixtures: a throwaway database and an offscreen Qt application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests must never need a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TERMX_DISABLE_TELEMETRY", "1")


@pytest.fixture()
def db(tmp_path):
    """A fresh, isolated TermX database."""
    from termx.core.database import Database

    database = Database(tmp_path / "termx-test.db")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture()
def sample_record():
    """Factory for command records with sensible defaults."""
    from termx.core.models import CommandRecord, ExecutionStatus, RiskLevel, ShellType

    def make(**overrides):
        data = {
            "request": "show all files",
            "command": "Get-ChildItem",
            "shell": ShellType.POWERSHELL,
            "explanation": "Lists the contents of the current directory.",
            "risk": RiskLevel.SAFE,
            "status": ExecutionStatus.SUCCESS,
            "exit_code": 0,
            "cwd": "C:/Users/dev",
            "output": "a.txt\nb.txt",
            "duration_ms": 42,
            "model": "qwen2.5-coder:7b",
        }
        data.update(overrides)
        return CommandRecord(**data)

    return make


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one)."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from termx.ui.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    ThemeManager()
    yield app
