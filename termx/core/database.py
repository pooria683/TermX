"""SQLite persistence layer for TermX.

A single connection guarded by a re-entrant lock is used: SQLite handles this
well for a desktop app, and it keeps the model simple and crash-safe. All
queries are parameterised; no string interpolation of user data.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from termx.core.models import (
    AppSettings,
    CommandRecord,
    DashboardStats,
    ExecutionStatus,
    RiskLevel,
    SessionRecord,
    ShellType,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'New session',
    shell         TEXT NOT NULL DEFAULT 'powershell',
    cwd           TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    summary       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    request     TEXT NOT NULL DEFAULT '',
    command     TEXT NOT NULL,
    shell       TEXT NOT NULL DEFAULT 'powershell',
    explanation TEXT NOT NULL DEFAULT '',
    risk        TEXT NOT NULL DEFAULT 'safe',
    status      TEXT NOT NULL DEFAULT 'success',
    exit_code   INTEGER,
    cwd         TEXT NOT NULL DEFAULT '',
    output      TEXT NOT NULL DEFAULT '',
    stderr      TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    was_blocked INTEGER NOT NULL DEFAULT 0,
    favorite    INTEGER NOT NULL DEFAULT 0,
    model       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_commands_session ON commands(session_id);
CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    name           TEXT PRIMARY KEY,
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    parameter_size TEXT NOT NULL DEFAULT '',
    quantization   TEXT NOT NULL DEFAULT '',
    family         TEXT NOT NULL DEFAULT '',
    modified_at    TEXT,
    last_used_at   TEXT
);
"""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class Database:
    """Thread-safe SQLite wrapper with the queries TermX needs."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from termx import get_user_data_dir

            path = get_user_data_dir() / "termx.db"
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    # -- setup --------------------------------------------------------------
    def _configure(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    @contextmanager
    def transaction(self):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # -- settings -----------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def load_settings(self) -> AppSettings:
        raw = self.get_setting("app_settings", None)
        if not raw:
            return AppSettings()
        try:
            return AppSettings.model_validate(raw)
        except Exception as exc:  # invalid stored settings -> defaults
            log.warning("Discarding invalid settings: %s", exc)
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self.set_setting("app_settings", settings.model_dump(mode="json"))

    # -- sessions -----------------------------------------------------------
    def create_session(self, session: SessionRecord) -> SessionRecord:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(id, title, shell, cwd, started_at, ended_at, is_active, summary) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    session.id,
                    session.title,
                    session.shell.value,
                    session.cwd,
                    _iso(session.started_at),
                    _iso(session.ended_at),
                    int(session.is_active),
                    session.summary,
                ),
            )
        return session

    def update_session(self, session: SessionRecord) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title=?, shell=?, cwd=?, ended_at=?, is_active=?, summary=? WHERE id=?",
                (
                    session.title,
                    session.shell.value,
                    session.cwd,
                    _iso(session.ended_at),
                    int(session.is_active),
                    session.summary,
                    session.id,
                ),
            )

    def end_session(self, session_id: str, summary: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET is_active=0, ended_at=?, summary=? WHERE id=?",
                (_iso(datetime.now(UTC)), summary, session_id),
            )

    def list_sessions(self, limit: int = 200, include_active: bool = True) -> list[SessionRecord]:
        query = """
            SELECT s.*,
                   (SELECT COUNT(*) FROM commands c WHERE c.session_id = s.id) AS cmd_count,
                   (SELECT COUNT(*) FROM commands c WHERE c.session_id = s.id AND c.status='success') AS ok_count,
                   (SELECT COUNT(*) FROM commands c WHERE c.session_id = s.id AND c.status IN ('failed','blocked')) AS fail_count
            FROM sessions s
            {where}
            ORDER BY s.started_at DESC LIMIT ?
        """
        where = "" if include_active else "WHERE s.is_active = 0"
        with self._lock:
            rows = self._conn.execute(query.format(where=where), (limit,)).fetchall()
        return [
            SessionRecord(
                id=row["id"],
                title=row["title"],
                shell=ShellType(row["shell"]),
                cwd=row["cwd"],
                started_at=_parse_dt(row["started_at"]) or datetime.now(UTC),
                ended_at=_parse_dt(row["ended_at"]),
                is_active=bool(row["is_active"]),
                summary=row["summary"],
                command_count=row["cmd_count"],
                success_count=row["ok_count"],
                failure_count=row["fail_count"],
            )
            for row in rows
        ]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            return None
        return SessionRecord(
            id=row["id"],
            title=row["title"],
            shell=ShellType(row["shell"]),
            cwd=row["cwd"],
            started_at=_parse_dt(row["started_at"]) or datetime.now(UTC),
            ended_at=_parse_dt(row["ended_at"]),
            is_active=bool(row["is_active"]),
            summary=row["summary"],
        )

    def rename_session(self, session_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM commands WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def active_session(self) -> SessionRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE is_active=1 ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return SessionRecord(
            id=row["id"],
            title=row["title"],
            shell=ShellType(row["shell"]),
            cwd=row["cwd"],
            started_at=_parse_dt(row["started_at"]) or datetime.now(UTC),
            is_active=True,
            summary=row["summary"],
        )

    # -- commands -----------------------------------------------------------
    def add_command(self, record: CommandRecord) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """INSERT INTO commands(session_id, request, command, shell, explanation, risk, status,
                                        exit_code, cwd, output, stderr, duration_ms, was_blocked,
                                        favorite, model, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.session_id,
                    record.request,
                    record.command,
                    record.shell.value,
                    record.explanation,
                    record.risk.value,
                    record.status.value,
                    record.exit_code,
                    record.cwd,
                    record.output,
                    record.stderr,
                    record.duration_ms,
                    int(record.was_blocked),
                    int(record.favorite),
                    record.model,
                    _iso(record.created_at),
                ),
            )
            return int(cursor.lastrowid or 0)

    def _row_to_record(self, row: sqlite3.Row) -> CommandRecord:
        return CommandRecord(
            id=row["id"],
            session_id=row["session_id"],
            request=row["request"],
            command=row["command"],
            shell=ShellType(row["shell"]),
            explanation=row["explanation"],
            risk=RiskLevel(row["risk"]) if row["risk"] in RiskLevel._value2member_map_ else RiskLevel.SAFE,
            status=ExecutionStatus(row["status"])
            if row["status"] in ExecutionStatus._value2member_map_
            else ExecutionStatus.SUCCESS,
            exit_code=row["exit_code"],
            cwd=row["cwd"],
            output=row["output"],
            stderr=row["stderr"],
            duration_ms=row["duration_ms"],
            was_blocked=bool(row["was_blocked"]),
            favorite=bool(row["favorite"]),
            model=row["model"],
            created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
        )

    def list_commands(
        self,
        limit: int = 200,
        offset: int = 0,
        search: str = "",
        session_id: str | None = None,
        favorites_only: bool = False,
    ) -> list[CommandRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(command LIKE ? OR request LIKE ? OR explanation LIKE ? OR output LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if favorites_only:
            clauses.append("favorite = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM commands {where} ORDER BY datetime(created_at) DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_commands(self, search: str = "", session_id: str | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(command LIKE ? OR request LIKE ? OR explanation LIKE ? OR output LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM commands {where}", params).fetchone()
        return int(row["n"]) if row else 0

    def get_command(self, command_id: int) -> CommandRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def toggle_favorite(self, command_id: int) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT favorite FROM commands WHERE id=?", (command_id,)).fetchone()
            if row is None:
                return False
            value = 0 if row["favorite"] else 1
            self._conn.execute("UPDATE commands SET favorite=? WHERE id=?", (value, command_id))
        return bool(value)

    def delete_command(self, command_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM commands WHERE id=?", (command_id,))

    def clear_history(self, keep_favorites: bool = True) -> int:
        with self._lock:
            where = "WHERE favorite = 0" if keep_favorites else ""
            cur = self._conn.execute(f"DELETE FROM commands {where}")
            return cur.rowcount if cur.rowcount > 0 else 0

    def prune_history(self, max_rows: int) -> int:
        """Keep only the newest ``max_rows`` entries. Returns the rows removed."""
        if max_rows <= 0:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                """DELETE FROM commands
                   WHERE favorite = 0 AND id NOT IN (
                       SELECT id FROM commands ORDER BY id DESC LIMIT ?
                   )""",
                (max_rows,),
            )
            return max(0, cursor.rowcount)

    def similar_commands(self, command: str, limit: int = 5) -> list[CommandRecord]:
        """Find previously executed commands resembling ``command``."""
        token = (command or "").strip().split(" ")[0]
        if not token:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM commands WHERE command LIKE ? ORDER BY datetime(created_at) DESC LIMIT ?",
                (f"%{token}%", limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    # -- models -------------------------------------------------------------
    def save_models(self, models: Iterable[Any]) -> None:
        with self._lock:
            for model in models:
                self._conn.execute(
                    """INSERT INTO models(name, size_bytes, parameter_size, quantization, family, modified_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET
                         size_bytes=excluded.size_bytes, parameter_size=excluded.parameter_size,
                         quantization=excluded.quantization, family=excluded.family,
                         modified_at=excluded.modified_at""",
                    (
                        model.name,
                        model.size_bytes,
                        model.parameter_size,
                        model.quantization,
                        model.family,
                        _iso(model.modified_at),
                    ),
                )

    def mark_model_used(self, name: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE models SET last_used_at=? WHERE name=?", (_iso(datetime.now(UTC)), name))

    def list_models(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM models ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    # -- analytics ----------------------------------------------------------
    def stats(self, days: int = 14) -> DashboardStats:
        with self._lock:
            totals = self._conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
                          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS bad,
                          SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) AS blocked,
                          SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) AS favs,
                          SUM(CASE WHEN model <> '' THEN 1 ELSE 0 END) AS ai_count,
                          AVG(NULLIF(duration_ms,0)) AS avg_dur
                   FROM commands"""
            ).fetchone()
            sessions = self._conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
            shell_rows = self._conn.execute("SELECT shell, COUNT(*) AS n FROM commands GROUP BY shell").fetchall()
            since = (datetime.now(UTC) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
            daily_rows = self._conn.execute(
                "SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM commands "
                "WHERE datetime(created_at) >= datetime(?) GROUP BY day",
                (_iso(since),),
            ).fetchall()
            top_rows = self._conn.execute(
                "SELECT request, COUNT(*) AS n FROM commands WHERE request <> '' GROUP BY request ORDER BY n DESC LIMIT 5"
            ).fetchall()

        total = int(totals["total"] or 0)
        ok = int(totals["ok"] or 0)
        return DashboardStats(
            total_commands=total,
            successful=ok,
            failed=int(totals["bad"] or 0),
            blocked=int(totals["blocked"] or 0),
            sessions=int(sessions or 0),
            ai_commands=int(totals["ai_count"] or 0),
            favorites=int(totals["favs"] or 0),
            avg_duration_ms=float(totals["avg_dur"] or 0.0),
            success_rate=(ok / total * 100.0) if total else 0.0,
            by_shell={row["shell"]: row["n"] for row in shell_rows},
            daily_counts={row["day"]: row["n"] for row in daily_rows},
            top_requests=[{"request": row["request"], "count": row["n"]} for row in top_rows],
        )

    def export_commands(self, path: str | Path, fmt: str = "json") -> int:
        """Export history to JSON, CSV or Markdown. Returns the rows written."""
        rows = self.list_commands(limit=100000)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            import csv

            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "id",
                        "created_at",
                        "request",
                        "command",
                        "shell",
                        "risk",
                        "status",
                        "exit_code",
                        "cwd",
                        "duration_ms",
                        "favorite",
                    ]
                )
                for record in rows:
                    writer.writerow(
                        [
                            record.id,
                            record.created_at.isoformat(),
                            record.request,
                            record.command,
                            record.shell.value,
                            record.risk.value,
                            record.status.value,
                            record.exit_code,
                            record.cwd,
                            record.duration_ms,
                            int(record.favorite),
                        ]
                    )
        elif fmt in ("md", "markdown"):
            target.write_text(self._as_markdown(rows), encoding="utf-8")
        else:
            payload = [record.model_dump(mode="json") for record in rows]
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return len(rows)

    @staticmethod
    def _as_markdown(rows: list[CommandRecord]) -> str:
        """Render history as a shareable Markdown report."""
        from datetime import datetime

        lines = ["# TermX Command History", "", f"Exported {datetime.now():%Y-%m-%d %H:%M}", ""]
        if not rows:
            lines.extend(["_No commands recorded yet._", ""])
        for record in rows:
            lines.append(f"## {record.request or record.command}")
            lines.append("")
            lines.append(f"- **Shell**: {record.shell.label}")
            lines.append(f"- **Risk**: {record.risk.label}")
            lines.append(f"- **Status**: {record.status.label}")
            lines.append(f"- **When**: {record.created_at:%Y-%m-%d %H:%M} UTC")
            if record.cwd:
                lines.append(f"- **Directory**: `{record.cwd}`")
            lines.append("")
            lines.append(f"```{record.shell.extension}")
            lines.append(record.command)
            lines.append("```")
            if record.explanation.strip():
                lines.extend(["", record.explanation.strip()])
            output = (record.output or "").strip() or (record.stderr or "").strip()
            if output:
                lines.extend(["", "```text", output[:4000], "```"])
            lines.append("")
        return "\n".join(lines)

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
