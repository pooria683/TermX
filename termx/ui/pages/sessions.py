"""Sessions page: browse, resume and manage remembered terminal sessions."""

from __future__ import annotations

from datetime import UTC

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import SessionRecord
from termx.ui import icons
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge, ShellBadge, StatusDot
from termx.ui.widgets.buttons import IconButton, PillButton
from termx.ui.widgets.cards import SectionHeader
from termx.ui.widgets.misc import ClickableFrame, EmptyState, clear_layout


class SessionCard(ClickableFrame):
    """Card representing one session."""

    resume = Signal(str)
    rename = Signal(str)
    delete = Signal(str)
    view = Signal(str)

    def __init__(self, session: SessionRecord, palette: Palette, active: bool = False) -> None:
        super().__init__(object_name="CardHover")
        self.session = session
        self._palette = palette
        self.setMinimumHeight(132)
        self.setStyleSheet(
            f"QFrame#CardHover {{ background-color: {palette.surface}; border: 1px solid "
            f"{palette.border_accent if active else palette.border}; border-radius: 14px; }}"
            f"QFrame#CardHover:hover {{ background-color: {palette.surface_alt}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        if active:
            dot = StatusDot(palette.success, 7, pulse=True)
            top.addWidget(dot)
        title = QLabel(session.title)
        title.setStyleSheet(f"color: {palette.text}; font-size: 13px; font-weight: 700;")
        top.addWidget(title, 1)
        self._menu_button = IconButton("settings", "Session actions", palette, size=18)
        self._menu_button.setToolTip("More actions")
        self._menu_button.clicked.connect(self._show_menu)
        top.addWidget(self._menu_button)
        layout.addLayout(top)

        summary = QLabel(session.summary or self._auto_summary())
        summary.setObjectName("Dim")
        summary.setWordWrap(True)
        summary.setMaximumHeight(32)
        layout.addWidget(summary)
        layout.addStretch(1)

        stats = QHBoxLayout()
        stats.setSpacing(6)
        shell = ShellBadge(session.shell, palette)
        stats.addWidget(shell)
        ok = Badge(f"{session.success_count} ok", palette.success)
        stats.addWidget(ok)
        if session.failure_count:
            stats.addWidget(Badge(f"{session.failure_count} failed", palette.danger))
        stats.addStretch(1)
        when = QLabel(self._when())
        when.setObjectName("Dim")
        stats.addWidget(when)
        layout.addLayout(stats)

        self.clicked.connect(lambda: self.view.emit(session.id))

    def _auto_summary(self) -> str:
        if self.session.command_count == 0:
            return "No commands executed yet."
        return f"{self.session.command_count} commands · {self.session.duration_seconds // 60} min"

    def _when(self) -> str:
        started = self.session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        local = started.astimezone()
        if self.session.is_active:
            return "active now"
        return local.strftime("%d %b, %H:%M")

    def _show_menu(self) -> None:
        menu = QMenu(self)
        resume = menu.addAction(icons.icon("play", self._palette.text_muted, 16), "Continue session")
        view = menu.addAction(icons.icon("eye", self._palette.text_muted, 16), "View commands")
        rename = menu.addAction(icons.icon("edit", self._palette.text_muted, 16), "Rename")
        menu.addSeparator()
        delete = menu.addAction(icons.icon("trash", self._palette.danger, 16), "Delete session")
        chosen = menu.exec(self._menu_button.mapToGlobal(self._menu_button.rect().bottomLeft()))
        if chosen is resume:
            self.resume.emit(self.session.id)
        elif chosen is view:
            self.view.emit(self.session.id)
        elif chosen is rename:
            self.rename.emit(self.session.id)
        elif chosen is delete:
            self.delete.emit(self.session.id)


class SessionsPage(QWidget):
    """All remembered sessions."""

    open_session = Signal(str)

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        content = QWidget()
        content.setObjectName("PageBody")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        header = SectionHeader(
            "Sessions",
            "TermX remembers every working session so you can pick up where you left off.",
            self._palette,
        )
        self._new = PillButton("New session", "plus", self._palette, "Primary")
        self._new.setMinimumHeight(34)
        self._new.clicked.connect(self._create_session)
        header.add_action(self._new)
        layout.addWidget(header)

        self._summary_bar = QFrame()
        self._summary_bar.setObjectName("Card")
        summary_layout = QHBoxLayout(self._summary_bar)
        summary_layout.setContentsMargins(18, 12, 18, 12)
        summary_layout.setSpacing(18)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {self._palette.text_muted}; font-size: 12px;")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch(1)
        layout.addWidget(self._summary_bar)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        layout.addWidget(self._grid_host)

        self._empty = EmptyState(
            "No sessions yet",
            "Sessions are created automatically when you start using the terminal.",
            "sessions",
            "Go to AI Terminal",
            self._palette,
        )
        layout.addWidget(self._empty)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addStretch(1)

        self.controller.sessions_changed.connect(self.reload)
        self.reload()

    # -- data ---------------------------------------------------------------
    def reload(self) -> None:
        clear_layout(self._grid)

        sessions = self.controller.sessions()
        total_commands = sum(s.command_count for s in sessions)
        self._summary_label.setText(
            f"<b style='color:{self._palette.text}'>{len(sessions)}</b> sessions  ·  "
            f"<b style='color:{self._palette.text}'>{total_commands}</b> commands recorded  ·  "
            f"<b style='color:{self._palette.text}'>1</b> active"
        )

        self._empty.setVisible(not sessions)
        self._grid_host.setVisible(bool(sessions))

        active_id = self.controller.session.id
        for index, session in enumerate(sessions):
            card = SessionCard(session, self._palette, active=session.id == active_id)
            card.resume.connect(self._resume)
            card.view.connect(self.open_session.emit)
            card.rename.connect(self._rename)
            card.delete.connect(self._delete)
            self._grid.addWidget(card, index // 3, index % 3)
            card.show()

        columns = 3
        for column in range(columns):
            self._grid.setColumnStretch(column, 1)

    # -- actions ------------------------------------------------------------
    def _create_session(self) -> None:
        session = self.controller.new_session()
        self.controller.notice.emit(f"Started “{session.title}”.", "success")
        self.reload()

    def _resume(self, session_id: str) -> None:
        if session_id == self.controller.session.id:
            self.open_session.emit(session_id)
            return
        answer = QMessageBox.question(
            self,
            "Continue session",
            "Continue this session? The current session will be closed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            existing = self.controller.db.get_session(session_id)
            if existing:
                existing.is_active = True
                self.controller.db.end_session(self.controller.session.id, "Switched sessions.")
                self.controller.db.update_session(existing)
                self.controller.session = existing
                self.controller.sessions_changed.emit()
                self.open_session.emit(session_id)

    def _rename(self, session_id: str) -> None:
        current = next((s for s in self.controller.sessions() if s.id == session_id), None)
        title, ok = QInputDialog.getText(
            self,
            "Rename session",
            "Session title:",
            QLineEdit.EchoMode.Normal,
            current.title if current else "",
        )
        if ok and title.strip():
            self.controller.rename_session(session_id, title.strip())
            self.reload()

    def _delete(self, session_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Delete session",
            "Delete this session and its recorded commands?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.delete_session(session_id)
            self.reload()

    def on_shown(self) -> None:
        self.reload()
