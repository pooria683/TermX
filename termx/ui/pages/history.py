"""Command History page: searchable, filterable, exportable transcript log."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from termx.core.models import CommandRecord
from termx.ui import icons
from termx.ui.controller import AppController
from termx.ui.theme import Palette
from termx.ui.widgets.badges import Badge, RiskBadge, ShellBadge
from termx.ui.widgets.buttons import IconButton, PillButton
from termx.ui.widgets.cards import SectionHeader
from termx.ui.widgets.inputs import SearchField
from termx.ui.widgets.misc import Divider, EmptyState


class HistoryPage(QWidget):
    """Browsable history with detail inspection."""

    open_in_terminal = Signal(object)

    PAGE_SIZE = 200

    def __init__(self, controller: AppController, palette: Palette | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.controller = controller
        self._palette = palette or Palette()
        self._records: list[CommandRecord] = []
        self._selected: CommandRecord | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = SectionHeader(
            "Command History",
            "Every command TermX has executed, with output, exit codes, and AI context.",
            self._palette,
        )
        self._export = PillButton("Export", "download", self._palette)
        self._export.clicked.connect(self._export_history)
        header.add_action(self._export)
        self._clear = PillButton("Clear history", "trash", self._palette, "Danger")
        self._clear.clicked.connect(self._clear_history)
        header.add_action(self._clear)
        root.addWidget(header)

        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_body(), 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.reload)

        self.controller.history_changed.connect(self.reload)
        self.reload()

    # -- construction -------------------------------------------------------
    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self._search = SearchField("Search commands, requests, output…", self._palette)
        self._search.text_changed.connect(lambda _t: self._search_timer.start())
        bar.addWidget(self._search, 1)

        self._favorites = PillButton("Favourites", "star", self._palette)
        self._favorites.setCheckable(True)
        self._favorites.toggled.connect(lambda _v: self.reload())
        bar.addWidget(self._favorites)

        self._count_label = QLabel("0 entries")
        self._count_label.setObjectName("Dim")
        bar.addWidget(self._count_label)

        refresh = IconButton("refresh", "Refresh", self._palette)
        refresh.clicked.connect(self.reload)
        bar.addWidget(refresh)
        return bar

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)

        table_frame = QFrame()
        table_frame.setObjectName("Card")
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(8, 8, 8, 8)
        table_layout.setSpacing(0)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["", "REQUEST / COMMAND", "SHELL", "RISK", "STATUS", "WHEN"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setDefaultSectionSize(48)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 30)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((2, 104), (3, 100), (4, 100), (5, 110)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self._table.setColumnWidth(column, width)
        self._table.itemSelectionChanged.connect(self._on_selection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        table_layout.addWidget(self._table)

        self._empty = EmptyState(
            "No commands found",
            "Run something in the AI Terminal, or adjust your search filters.",
            "history",
            "",
            self._palette,
        )
        table_layout.addWidget(self._empty)

        splitter.addWidget(table_frame)
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([720, 420])
        return splitter

    def _build_detail(self) -> QWidget:
        p = self._palette
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self._detail_placeholder = EmptyState(
            "Select an entry",
            "Pick a command to inspect its output, risk assessment, and metadata.",
            "eye",
            "",
            p,
        )
        layout.addWidget(self._detail_placeholder)

        self._detail_widget = QWidget()
        detail = QVBoxLayout(self._detail_widget)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._detail_title = QLabel("Command")
        self._detail_title.setObjectName("CardTitle")
        self._detail_title.setWordWrap(True)
        title_row.addWidget(self._detail_title, 1)
        self._detail_fav = IconButton("star", "Toggle favourite", p)
        self._detail_fav.clicked.connect(self._toggle_favorite)
        title_row.addWidget(self._detail_fav)
        detail.addLayout(title_row)

        badges = QHBoxLayout()
        badges.setSpacing(6)
        self._detail_shell = ShellBadge()
        badges.addWidget(self._detail_shell)
        self._detail_risk = RiskBadge()
        badges.addWidget(self._detail_risk)
        self._detail_status = Badge("Success", p.success)
        badges.addWidget(self._detail_status)
        badges.addStretch(1)
        detail.addLayout(badges)

        self._detail_meta = QLabel()
        self._detail_meta.setObjectName("Dim")
        self._detail_meta.setWordWrap(True)
        detail.addWidget(self._detail_meta)

        detail.addWidget(Divider())

        code_label = QLabel("COMMAND")
        code_label.setObjectName("CardCaption")
        detail.addWidget(code_label)
        self._detail_command = QTextEdit()
        self._detail_command.setObjectName("CodeEdit")
        self._detail_command.setReadOnly(True)
        self._detail_command.setMaximumHeight(84)
        detail.addWidget(self._detail_command)

        out_label = QLabel("OUTPUT")
        out_label.setObjectName("CardCaption")
        detail.addWidget(out_label)
        self._detail_output = QTextEdit()
        self._detail_output.setObjectName("CodeEdit")
        self._detail_output.setReadOnly(True)
        detail.addWidget(self._detail_output, 1)

        self._detail_explanation = QLabel()
        self._detail_explanation.setWordWrap(True)
        self._detail_explanation.setStyleSheet(f"color: {p.text_muted}; font-size: 11px;")
        detail.addWidget(self._detail_explanation)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        run_again = PillButton("Open in terminal", "terminal", p, "Primary")
        run_again.clicked.connect(self._open_selected)
        actions.addWidget(run_again)
        copy = PillButton("Copy", "copy", p)
        copy.clicked.connect(self._copy_selected)
        actions.addWidget(copy)
        delete = PillButton("Delete", "trash", p, "Danger")
        delete.clicked.connect(self._delete_selected)
        actions.addWidget(delete)
        actions.addStretch(1)
        detail.addLayout(actions)

        layout.addWidget(self._detail_widget)
        self._detail_widget.hide()
        return frame

    # -- data ---------------------------------------------------------------
    def reload(self) -> None:
        search = self._search.text().strip()
        favorites = self._favorites.isChecked()
        self._records = self.controller.history(limit=self.PAGE_SIZE, search=search, favorites_only=favorites)
        self._populate_table()
        total = self.controller.db.count_commands(search)
        shown = len(self._records)
        self._count_label.setText(
            f"{total:,} entr{'y' if total == 1 else 'ies'}" + (f" · showing {shown}" if shown < total else "")
        )

    def _populate_table(self) -> None:
        table = self._table
        table.setUpdatesEnabled(False)
        table.clearContents()
        table.setRowCount(len(self._records))
        p = self._palette

        for row, record in enumerate(self._records):
            fav = QTableWidgetItem("★" if record.favorite else "")
            fav.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            fav.setForeground(Qt.GlobalColor.yellow if hasattr(Qt, "GlobalColor") else None)
            from PySide6.QtGui import QColor

            fav.setForeground(QColor(p.warning))
            fav.setData(Qt.ItemDataRole.UserRole, record.id)
            table.setItem(row, 0, fav)

            first = record.request or record.command
            item = QTableWidgetItem(first)
            item.setToolTip(f"{record.command}\n\n{record.explanation}")
            item.setForeground(QColor(p.text))
            sub = record.command if record.request else ""
            if sub:
                item.setToolTip(f"{sub}\n\n{record.explanation}")
            table.setItem(row, 1, item)

            shell_item = QTableWidgetItem(record.shell.label)
            shell_item.setForeground(QColor(ShellBadge.COLORS.get(record.shell, p.text_muted)))
            table.setItem(row, 2, shell_item)

            risk_item = QTableWidgetItem(record.risk.label)
            risk_item.setForeground(QColor(record.risk.color))
            table.setItem(row, 3, risk_item)

            status_item = QTableWidgetItem(record.status.label)
            status_item.setForeground(QColor(record.status.color))
            table.setItem(row, 4, status_item)

            when = QTableWidgetItem(_format_time(record.created_at))
            when.setForeground(QColor(p.text_dim))
            table.setItem(row, 5, when)

        table.setUpdatesEnabled(True)
        self._empty.setVisible(not self._records)
        table.setVisible(bool(self._records))

        # Select the newest entry so the detail pane is never blank on arrival.
        if self._records:
            table.selectRow(0)
            self._on_selection()
        else:
            self._on_selection()

    # -- selection ----------------------------------------------------------
    def _on_selection(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._selected = None
            self._detail_widget.hide()
            self._detail_placeholder.show()
            return
        index = rows[0].row()
        if 0 <= index < len(self._records):
            self._selected = self._records[index]
            self._render_detail(self._selected)

    def _render_detail(self, record: CommandRecord) -> None:
        p = self._palette
        self._detail_placeholder.hide()
        self._detail_widget.show()
        self._detail_title.setText(record.request or record.command[:80])
        self._detail_shell.set_shell(record.shell)
        self._detail_risk.set_risk(record.risk)
        self._detail_status.set_text(record.status.label)
        self._detail_status.set_color(record.status.color)
        self._detail_command.setPlainText(record.command)
        output = record.output or record.stderr or "(no output captured)"
        self._detail_output.setPlainText(output)

        meta_bits = [
            record.created_at.astimezone().strftime("%d %b %Y · %H:%M:%S"),
            f"{record.duration_ms / 1000:.2f}s",
        ]
        if record.exit_code is not None:
            meta_bits.append(f"exit {record.exit_code}")
        if record.cwd:
            meta_bits.append(record.cwd)
        if record.model:
            meta_bits.append(f"model: {record.model}")
        self._detail_meta.setText("  ·  ".join(meta_bits))
        self._detail_explanation.setText(record.explanation)
        self._detail_explanation.setVisible(bool(record.explanation))
        self._detail_fav.set_icon_name("star-filled" if record.favorite else "star")
        self._detail_fav.set_color(p.warning if record.favorite else None)

    # -- actions ------------------------------------------------------------
    def _open_selected(self) -> None:
        if self._selected:
            self.open_in_terminal.emit(self._selected)

    def _copy_selected(self) -> None:
        if self._selected:
            QGuiApplication.clipboard().setText(self._selected.command)

    def _toggle_favorite(self) -> None:
        if not self._selected or self._selected.id is None:
            return
        value = self.controller.toggle_favorite(self._selected.id)
        self._selected.favorite = value
        self._render_detail(self._selected)
        self.reload()

    def _delete_selected(self) -> None:
        if not self._selected or self._selected.id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete entry",
            "Remove this command from history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.delete_history_entry(self._selected.id)
            self._selected = None
            self._detail_widget.hide()
            self._detail_placeholder.show()
            self.reload()

    def _clear_history(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Clear history")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Delete all command history?")
        box.setInformativeText("Favourites are kept. This cannot be undone.")
        keep = box.addButton("Keep favourites", QMessageBox.ButtonRole.AcceptRole)
        everything = box.addButton("Delete everything", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is keep:
            removed = self.controller.clear_history(keep_favorites=True)
            self.controller.notice.emit(f"Removed {removed} entries.", "success")
        elif box.clickedButton() is everything:
            removed = self.controller.clear_history(keep_favorites=False)
            self.controller.notice.emit(f"Removed {removed} entries.", "success")
        self.reload()

    def _export_history(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export history",
            f"termx-history-{datetime.now():%Y%m%d}.json",
            "JSON (*.json);;CSV (*.csv);;Markdown (*.md)",
        )
        if not path:
            return
        fmt = "csv" if path.endswith(".csv") else ("md" if path.endswith(".md") else "json")
        try:
            count = self.controller.export_history(path, fmt)
            self.controller.notice.emit(f"Exported {count} entries to {path}", "success")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _show_context_menu(self, position) -> None:
        index = self._table.indexAt(position)
        if not index.isValid():
            return
        record = self._records[index.row()]
        menu = QMenu(self)
        open_action = menu.addAction(icons.icon("terminal", self._palette.text_muted, 16), "Open in terminal")
        copy_action = menu.addAction(icons.icon("copy", self._palette.text_muted, 16), "Copy command")
        copy_output = menu.addAction(icons.icon("copy", self._palette.text_muted, 16), "Copy output")
        menu.addSeparator()
        fav_action = menu.addAction(
            icons.icon("star", self._palette.text_muted, 16),
            "Remove favourite" if record.favorite else "Add favourite",
        )
        menu.addSeparator()
        delete_action = menu.addAction(icons.icon("trash", self._palette.danger, 16), "Delete entry")

        chosen = menu.exec(self._table.viewport().mapToGlobal(position))
        if chosen is open_action:
            self.open_in_terminal.emit(record)
        elif chosen is copy_action:
            QGuiApplication.clipboard().setText(record.command)
        elif chosen is copy_output:
            QGuiApplication.clipboard().setText(record.output or record.stderr)
        elif chosen is fav_action and record.id is not None:
            self.controller.toggle_favorite(record.id)
            self.reload()
        elif chosen is delete_action and record.id is not None:
            self.controller.delete_history_entry(record.id)
            self.reload()

    def on_shown(self) -> None:
        self.reload()


def _format_time(moment: datetime) -> str:

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    now = datetime.now(local.tzinfo)
    if local.date() == now.date():
        return local.strftime("%H:%M")
    return local.strftime("%d %b %H:%M")
