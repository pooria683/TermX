"""GUI smoke tests: every page builds, the window navigates, flows render.

These run headless (``QT_QPA_PLATFORM=offscreen``), so they also act as a
regression test for the paint/threading crashes fixed during development.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

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
from termx.ui.controller import AppController
from termx.ui.main_window import MainWindow
from termx.ui.misc_colors import qcolor
from termx.ui.theme import DARK, ThemeManager


@pytest.fixture()
def controller(tmp_path, qapp, monkeypatch):
    """A controller backed by a throwaway database and no network access."""

    def fake_status(self):
        self._on_status(ConnectionState.OFFLINE, "offline (tests)", [])

    monkeypatch.setattr(AppController, "refresh_ai_status", fake_status)
    ctrl = AppController()
    # Point every database access at the temp path for the test's lifetime.
    ctrl.db.close()
    from termx.core.database import Database

    ctrl.db = Database(tmp_path / "gui.db")
    try:
        yield ctrl
    finally:
        ctrl.shutdown()


@pytest.fixture()
def window(controller, qapp):
    win = MainWindow(controller)
    win.resize(1440, 900)
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_palette_colors_are_valid() -> None:
    assert qcolor(DARK.background).isValid()
    assert qcolor(DARK.accent).isValid()
    assert qcolor("rgba(76, 141, 255, 0.14)").alpha() > 0


def test_stylesheet_is_generated() -> None:
    sheet = ThemeManager().app_stylesheet()
    assert DARK.background in sheet
    assert "QPushButton" in sheet


def test_controller_starts_with_a_session(controller) -> None:
    assert controller.session is not None
    assert controller.session.id
    assert controller.cwd
    assert controller.shell in tuple(ShellType)


def test_all_pages_navigate(window, qapp) -> None:
    from termx.ui.main_window import PAGE_ORDER

    assert len(PAGE_ORDER) == 7
    for name in PAGE_ORDER:
        window.navigate(name)
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[name]


def test_pages_render_without_crashing(window, qapp, tmp_path) -> None:
    window.show()
    for name in ("terminal", "dashboard", "history", "sessions", "settings", "models", "about"):
        window.navigate(name)
        qapp.processEvents()
        pixmap = window.grab()
        assert not pixmap.isNull()
        assert pixmap.width() > 0


def test_suggestion_and_verdict_reach_the_terminal_page(window, qapp) -> None:
    window.navigate("terminal")
    suggestion = CommandSuggestion(
        request="show files",
        command="Get-ChildItem",
        shell=ShellType.POWERSHELL,
        explanation="Lists directory contents.",
        risk=RiskLevel.SAFE,
    )
    verdict = SafetyVerdict(risk=RiskLevel.SAFE, reasons=["read only"], requires_confirmation=False)
    window.controller.suggestion_ready.emit(suggestion, verdict)
    qapp.processEvents()

    page = window.pages["terminal"]
    assert page._preview is not None
    assert page._preview.current_command() == "Get-ChildItem"


def test_execution_output_is_appended_to_the_terminal(window, qapp) -> None:
    window.navigate("terminal")
    page = window.pages["terminal"]
    window.controller.execution_started.emit("Get-Date")
    window.controller.execution_output.emit("stdout", "hello from the shell\n")
    qapp.processEvents()

    texts = [entry.text for entry in page.terminal._entries]
    assert any("hello from the shell" in text for text in texts)


def test_failed_execution_offers_a_diagnosis(window, qapp) -> None:
    window.navigate("terminal")
    result = ExecutionResult(
        command="gti status",
        shell=ShellType.POWERSHELL,
        status=ExecutionStatus.FAILED,
        exit_code=1,
        stderr="'gti' is not recognized as an internal or external command",
        duration_ms=30,
    )
    window.controller.execution_finished.emit(result)
    window.controller.diagnosis_ready.emit(
        ErrorExplanation(summary="The shell cannot find that command.", cause="Typo.", suggestions=["Use git status."])
    )
    qapp.processEvents()
    assert window.pages["terminal"] is not None


def test_toast_shows_and_hides(window, qapp) -> None:
    window.show_toast("Saved", "success")
    qapp.processEvents()
    assert window._toast is not None
    window._hide_toast()
    qapp.processEvents()


def test_history_page_selects_the_newest_entry(window, qapp, controller, sample_record) -> None:
    controller.db.add_command(sample_record(request="newest entry"))
    window.navigate("history")
    page = window.pages["history"]
    page.reload()
    qapp.processEvents()

    assert page._records
    assert page._selected is not None
    assert page._selected.request == "newest entry"


def test_settings_page_round_trips(controller, qapp, window) -> None:
    window.navigate("settings")
    page = window.pages["settings"]
    settings = controller.settings.model_copy(update={"font_size": 12, "reduce_motion": True})
    controller.update_settings(settings)
    qapp.processEvents()
    assert controller.settings.font_size == 12
    assert page.collect().font_size == 12


def test_dashboard_refresh_is_repeatable(window, qapp) -> None:
    window.navigate("dashboard")
    page = window.pages["dashboard"]
    for _ in range(10):
        page.refresh()
        qapp.processEvents()
    assert page._stats is not None


def test_shutdown_is_idempotent(tmp_path, qapp) -> None:
    ctrl = AppController()
    ctrl.db.close()
    from termx.core.database import Database

    ctrl.db = Database(tmp_path / "shutdown.db")
    ctrl.shutdown()
    ctrl.shutdown()  # must not raise


def test_database_guard_after_shutdown(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setattr(AppController, "refresh_ai_status", lambda self: None)
    ctrl = AppController()
    ctrl.db.close()
    from termx.core.database import Database

    ctrl.db = Database(tmp_path / "guard.db")
    ctrl.shutdown()

    # Late events must not touch the closed database.
    assert ctrl.history() == []
    assert ctrl.stats().total_commands == 0
