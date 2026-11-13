"""TermX — AI-powered intelligent terminal for Windows.

TermX translates natural language into safe, explainable shell commands and
executes them after explicit user confirmation.
"""

from __future__ import annotations

__all__ = [
    "APP_NAME",
    "APP_TAGLINE",
    "APP_VERSION",
    "ORGANIZATION",
    "get_user_data_dir",
]

APP_NAME = "TermX"
APP_VERSION = "1.0.0"
APP_TAGLINE = "AI-Powered Intelligent Terminal"
ORGANIZATION = "TermX Labs"
PROJECT_URL = "https://github.com/pooria683/TermX"
LICENSE_NAME = "MIT"


def get_user_data_dir():
    """Return the per-user application data directory, creating it if needed."""
    import os
    import sys
    from pathlib import Path

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    path = base / "TermX"
    path.mkdir(parents=True, exist_ok=True)
    return path
