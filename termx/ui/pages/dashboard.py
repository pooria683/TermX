"""Dashboard: at-a-glance activity, system status, and recent activity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import CommandRecord, ConnectionState, DashboardStats
from termx.ui import icons
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge, StatusDot
from termx.ui.widgets.buttons import PillButton
from termx.ui.widgets.cards import Card, SectionHeader, StatTile
from termx.ui.widgets.charts import BarChart, DonutChart
from termx.ui.widgets.misc import (
    ClickableFrame,
    Divider,
    ElidedLabel,
    EmptyState,
    clear_layout,
)


class DashboardPage(QWidget):
    """Overview of usage and system health."""

    open_terminal = Signal()
    open_history = Signal()
    open_sessions = Signal()
    open_settings = Signal()
    open_models = Signal()

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()
        self._stats: DashboardStats | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("PageBody")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        header = SectionHeader(
            "Dashboard",
            "Your terminal activity, AI health, and quick actions in one place.",
            self._palette,
        )
        new_cmd = PillButton("New request", "sparkles", self._palette, "Primary")
        new_cmd.setMinimumHeight(34)
        new_cmd.clicked.connect(self.open_terminal.emit)
        header.add_action(new_cmd)
        root.addWidget(header)

        root.addLayout(self._build_metrics())
        root.addLayout(self._build_main_row())
        root.addWidget(self._build_recent())
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.addStretch(1)

        self._connect_controller()
        self.refresh()

    # -- construction -------------------------------------------------------
    def _build_metrics(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.tile_total = StatTile("Commands run", "0", "all time", "terminal", self._palette.accent, self._palette)
        self.tile_success = StatTile("Success rate", "—", "of all commands", "success", self._palette.success, self._palette)
        self.tile_sessions = StatTile("Sessions", "0", "recorded", "sessions", self._palette.purple, self._palette)
        self.tile_ai = StatTile("AI commands", "0", "model-assisted", "brain", self._palette.cyan, self._palette)
        self.tile_total.clicked.connect(self.open_history.emit)
        self.tile_success.clicked.connect(self.open_history.emit)
        self.tile_sessions.clicked.connect(self.open_sessions.emit)
        self.tile_ai.clicked.connect(self.open_models.emit)
        for tile in (self.tile_total, self.tile_success, self.tile_sessions, self.tile_ai):
            row.addWidget(tile)
        return row

    def _build_main_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._build_activity_card(), 3)
        row.addWidget(self._build_health_card(), 2)
        return row

    def _build_activity_card(self) -> Card:
        card = Card(self._palette, "Activity", "Commands per day, last 14 days", "activity")
        self.chart = BarChart(self._palette, height=150, color=self._palette.accent, accent=self._palette.purple)
        card.add(self.chart)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(18)
        self._outcome_donut = DonutChart(self._palette, 118)
        stats_row.addWidget(self._outcome_donut, 0, Qt.AlignmentFlag.AlignLeft)

        detail = QVBoxLayout()
        detail.setSpacing(8)
        self._outcome_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label, color in (
            ("success", "Successful", self._palette.success),
            ("failed", "Failed", self._palette.danger),
            ("blocked", "Blocked", self._palette.warning),
        ):
            line = QHBoxLayout()
            line.setSpacing(7)
            dot = StatusDot(color, 6)
            line.addWidget(dot)
            name = QLabel(label)
            name.setObjectName("Muted")
            line.addWidget(name)
            line.addStretch(1)
            value = QLabel("0")
            value.setStyleSheet(f"color: {self._palette.text}; font-size: 12px; font-weight: 700;")
            line.addWidget(value)
            detail.addLayout(line)
            self._outcome_rows[key] = (name, value)

        detail.addSpacing(4)
        self._avg_duration = QLabel("Average runtime —")
        self._avg_duration.setObjectName("Dim")
        detail.addWidget(self._avg_duration)
        detail.addStretch(1)
        stats_row.addLayout(detail, 1)
        card.add_layout(stats_row)
        return card

    def _build_health_card(self) -> Card:
        card = Card(self._palette, "System status", "Live state of TermX and this machine", "cpu")

        self._health_rows: dict[str, tuple[StatusDot, QLabel, QLabel]] = {}
        for key, label, icon_name in (
            ("ai", "AI engine", "brain"),
            ("model", "Active model", "models"),
            ("shell", "Target shell", "code"),
            ("cwd", "Working directory", "folder"),
            ("database", "Local database", "database"),
        ):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 3, 0, 3)
            layout.setSpacing(8)
            dot = StatusDot(self._palette.text_dim, 6)
            layout.addWidget(dot)
            icon_label = QLabel()
            icon_label.setPixmap(icons.pixmap(icon_name, self._palette.text_dim, 13, 1.9))
            layout.addWidget(icon_label)
            name = QLabel(label)
            name.setObjectName("Muted")
            layout.addWidget(name)
            layout.addStretch(1)
            value = QLabel("—")
            value.setStyleSheet(f"color: {self._palette.text}; font-size: 11px; font-weight: 600;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(value)
            card.add(row)
            self._health_rows[key] = (dot, name, value)

        card.body.addSpacing(6)
        card.add(Divider())
        self._quick_actions = QWidget()
        actions = QHBoxLayout(self._quick_actions)
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        for label, icon_name, signal in (
            ("History", "history", self.open_history),
            ("Sessions", "sessions", self.open_sessions),
            ("Models", "brain", self.open_models),
            ("Settings", "settings", self.open_settings),
        ):
            button = PillButton(label, icon_name, self._palette)
            button.clicked.connect(signal.emit)
            actions.addWidget(button)
        actions.addStretch(1)
        card.add(self._quick_actions)
        return card

    def _build_recent(self) -> Card:
        card = Card(self._palette, "Recent activity", "Your last executions", "history")
        view_all = PillButton("View all", "chevron-right", self._palette)
        view_all.clicked.connect(self.open_history.emit)
        card.add_header_widget(view_all)
        self._recent_card = card
        self._recent_host = QWidget()
        self._recent_container = QVBoxLayout(self._recent_host)
        self._recent_container.setContentsMargins(0, 0, 0, 0)
        self._recent_container.setSpacing(0)
        card.add_recent = None  # placeholder to keep linters calm
        card.body.addWidget(self._recent_host)
        self._recent_empty = EmptyState(
            "No commands yet",
            "Run your first request from the AI Terminal and it will appear here.",
            "terminal",
            "Open AI Terminal",
            self._palette,
        )
        self._recent_empty.action_clicked.connect(self.open_terminal.emit)
        card.add(self._recent_empty)
        return card

    # -- controller ---------------------------------------------------------
    def _connect_controller(self) -> None:
        self.controller.history_changed.connect(self.refresh)
        self.controller.connection_changed.connect(lambda *_: self.refresh())
        self.controller.sessions_changed.connect(self.refresh)
        self.controller.models_changed.connect(lambda *_: self.refresh())
        self.controller.cwd_changed.connect(lambda *_: self.refresh())
        self.controller.shell_changed.connect(lambda *_: self.refresh())
        self.controller.settings_changed.connect(lambda *_: self.refresh())

    # -- refresh ------------------------------------------------------------
    def refresh(self) -> None:
        stats = self.controller.stats()
        self._stats = stats
        total = stats.total_commands

        self.tile_total.set_value(f"{total:,}")
        self.tile_total.set_caption("all time" if total else "no commands yet")
        self.tile_success.set_value(f"{stats.success_rate:.0f}%" if total else "—")
        self.tile_success.set_caption(f"{stats.successful:,} of {total:,} succeeded" if total else "waiting for data")
        self.tile_sessions.set_value(f"{stats.sessions:,}")
        self.tile_sessions.set_caption("one active now")
        self.tile_ai.set_value(f"{stats.ai_commands:,}")
        self.tile_ai.set_caption(f"{stats.favorites} favourited")

        # activity chart
        today = datetime.now(UTC).date()
        days = [today - timedelta(days=offset) for offset in range(13, -1, -1)]
        labels = [d.strftime("%d") for d in days]
        values = [stats.daily_counts.get(d.isoformat(), 0) for d in days]
        self.chart.set_data(labels, values)

        self._outcome_donut.set_data(
            [
                ("Success", stats.successful, self._palette.success),
                ("Failed", stats.failed, self._palette.danger),
                ("Blocked", stats.blocked, self._palette.warning),
            ],
            f"{stats.success_rate:.0f}%" if total else "—",
            "success rate",
        )
        self._outcome_rows["success"][1].setText(f"{stats.successful:,}")
        self._outcome_rows["failed"][1].setText(f"{stats.failed:,}")
        self._outcome_rows["blocked"][1].setText(f"{stats.blocked:,}")
        self._avg_duration.setText(
            f"Average runtime {stats.avg_duration_ms / 1000:.2f}s" if stats.avg_duration_ms else "Average runtime —"
        )

        # health
        c = self.controller
        dot, _name, value = self._health_rows["ai"]
        dot.set_color(c.connection_state.color)
        dot.set_pulse(c.connection_state is ConnectionState.CONNECTED)
        value.setText(c.connection_state.label)
        value.setStyleSheet(f"color: {c.connection_state.color}; font-size: 11px; font-weight: 600;")

        dot, _n, value = self._health_rows["model"]
        dot.set_color(self._palette.accent if c.models else self._palette.text_dim)
        value.setText(c.settings.model.split(":")[0] if c.settings.model else "—")

        dot, _n, value = self._health_rows["shell"]
        dot.set_color(self._palette.purple)
        value.setText(c.shell.label)

        dot, _n, value = self._health_rows["cwd"]
        dot.set_color(self._palette.cyan)
        from pathlib import Path

        home = str(Path.home())
        short = "~" + c.cwd[len(home) :] if c.cwd.startswith(home) else c.cwd
        value.setText(Path(short).name or short)

        dot, _n, value = self._health_rows["database"]
        dot.set_color(self._palette.success)
        size_kb = c.db.size_bytes() / 1024
        value.setText(f"{size_kb:.0f} KB")

        self._refresh_recent()

    def _refresh_recent(self) -> None:
        clear_layout(self._recent_container, keep=(self._recent_empty,))

        recent = self.controller.history(limit=6)
        if not recent:
            if self._recent_empty.parentWidget() is not self._recent_host:
                self._recent_container.addWidget(self._recent_empty)
            self._recent_empty.show()
        else:
            self._recent_empty.hide()
            for index, record in enumerate(recent):
                if index:
                    divider = Divider()
                    self._recent_container.addWidget(divider)
                    divider.show()
                row = self._recent_row(record)
                self._recent_container.addWidget(row)
                row.show()
        # Height is computed explicitly: adjustSize() runs before the page is
        # shown and would otherwise collapse the card to its header.
        rows = len(recent)
        needed = 62 + rows * 49 + (rows - 1 if rows > 0 else 0) + 18
        self._recent_card.setMinimumHeight(min(needed, 420))
        self._recent_host.updateGeometry()
        self._recent_card.updateGeometry()

    def _recent_row(self, record: CommandRecord) -> QWidget:
        row = ClickableFrame(object_name="CardHover")
        row.setStyleSheet(
            "QFrame#CardHover { border: none; background: transparent; }"
            f"QFrame#CardHover:hover {{ background-color: {self._palette.surface_alt}; border-radius: 6px; }}"
        )
        row.setFixedHeight(48)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 7, 4, 7)
        layout.setSpacing(10)

        dot = StatusDot(record.status.color, 7)
        dot.setFixedSize(16, 16)
        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title = ElidedLabel(record.request or record.command)
        title.setStyleSheet(f"color: {self._palette.text}; font-size: 12px; font-weight: 600;")
        text_col.addWidget(title)
        command = ElidedLabel(record.command)
        command.setStyleSheet(f"color: {self._palette.text_dim}; font-family: {self._palette.mono_stack}; font-size: 11px;")
        text_col.addWidget(command)
        layout.addLayout(text_col, 1)

        badge = Badge(record.shell.label, "#60A5FA")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        when = QLabel(_relative_time(record.created_at))
        when.setObjectName("Dim")
        when.setFixedWidth(52)
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(when)
        row.clicked.connect(self.open_history.emit)
        return row

    def on_shown(self) -> None:
        self.refresh()


def _relative_time(moment: datetime) -> str:
    now = datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = now - moment
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 604800:
        return f"{seconds // 86400}d ago"
    return moment.strftime("%d %b")
