"""Database layer: persistence, search, favourites, stats and lifecycle."""

from __future__ import annotations

import pytest

from termx.core.models import ExecutionStatus, RiskLevel, SessionRecord, ShellType


def test_settings_round_trip(db) -> None:
    settings = db.load_settings()
    settings.model = "llama3.1:8b"
    settings.font_size = 13
    db.save_settings(settings)

    reloaded = db.load_settings()
    assert reloaded.model == "llama3.1:8b"
    assert reloaded.font_size == 13


def test_sessions_are_created_and_closed(db) -> None:
    session = db.create_session(SessionRecord(title="First", shell=ShellType.POWERSHELL, cwd="C:/dev"))
    assert db.active_session() is not None

    db.end_session(session.id, "done")
    closed = db.get_session(session.id)
    assert closed is not None
    assert closed.ended_at is not None
    assert closed.summary == "done"
    assert db.active_session() is None


def test_commands_persist_with_all_fields(db, sample_record) -> None:
    record = sample_record()
    record_id = db.add_command(record)
    stored = db.get_command(record_id)

    assert stored is not None
    assert stored.command == record.command
    assert stored.request == record.request
    assert stored.shell is ShellType.POWERSHELL
    assert stored.risk is RiskLevel.SAFE
    assert stored.status is ExecutionStatus.SUCCESS
    assert stored.output == record.output


def test_failed_commands_are_stored_with_stderr(db, sample_record) -> None:
    record = sample_record(status=ExecutionStatus.FAILED, exit_code=1, stderr="not recognized")
    command_id = db.add_command(record)
    stored = db.get_command(command_id)
    assert stored is not None
    assert stored.status is ExecutionStatus.FAILED
    assert stored.stderr == "not recognized"


def test_search_matches_request_or_command(db, sample_record) -> None:
    db.add_command(sample_record(request="find the biggest files", command="Get-ChildItem -Recurse"))
    db.add_command(sample_record(request="check disk space", command="Get-PSDrive"))

    assert len(db.list_commands(search="biggest")) == 1
    assert len(db.list_commands(search="Get-PSDrive")) == 1
    assert len(db.list_commands(search="nothing-matches")) == 0
    assert db.count_commands() == 2


def test_favourites_filter(db, sample_record) -> None:
    favourite_id = db.add_command(sample_record(favorite=True))
    db.add_command(sample_record())

    favourites = db.list_commands(favorites_only=True)
    assert len(favourites) == 1
    assert favourites[0].id == favourite_id

    assert db.toggle_favorite(favourite_id) is False
    assert db.get_command(favourite_id).favorite is False


def test_stats_aggregate_correctly(db, sample_record) -> None:
    for status in (ExecutionStatus.SUCCESS, ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
        db.add_command(sample_record(status=status, exit_code=0 if status is ExecutionStatus.SUCCESS else 1))
    db.add_command(sample_record(status=ExecutionStatus.BLOCKED, risk=RiskLevel.BLOCKED, was_blocked=True))

    stats = db.stats()
    assert stats.total_commands == 4
    assert stats.successful == 2
    assert stats.failed == 1
    assert stats.blocked == 1
    assert stats.success_rate == pytest.approx(50.0)
    assert stats.daily_counts, "the dashboard chart needs at least today's bucket"


def test_history_is_ordered_newest_first(db, sample_record) -> None:
    first = db.add_command(sample_record(request="first"))
    second = db.add_command(sample_record(request="second"))

    records = db.list_commands(limit=10)
    assert [r.id for r in records] == [second, first]


def test_clear_history_can_keep_favourites(db, sample_record) -> None:
    db.add_command(sample_record(favorite=True))
    db.add_command(sample_record())
    db.clear_history(keep_favorites=True)

    remaining = db.list_commands()
    assert len(remaining) == 1
    assert remaining[0].favorite is True


def test_prune_history_keeps_the_most_recent(db, sample_record) -> None:
    for index in range(10):
        db.add_command(sample_record(request=f"task {index}"))
    removed = db.prune_history(4)
    assert removed == 6
    assert len(db.list_commands(limit=100)) == 4


def test_export_produces_json_and_markdown(db, sample_record, tmp_path) -> None:
    db.add_command(sample_record())
    json_path = tmp_path / "history.json"
    md_path = tmp_path / "history.md"

    db.export_commands(json_path, fmt="json")
    db.export_commands(md_path, fmt="markdown")

    assert "Get-ChildItem" in json_path.read_text(encoding="utf-8")
    assert "Get-ChildItem" in md_path.read_text(encoding="utf-8")


def test_database_survives_reopening(tmp_path, sample_record) -> None:
    from termx.core.database import Database

    path = tmp_path / "persist.db"
    first = Database(path)
    first.add_command(sample_record(request="survives"))
    first.close()

    second = Database(path)
    try:
        assert len(second.list_commands()) == 1
    finally:
        second.close()


def test_size_bytes_is_reported(db, sample_record) -> None:
    db.add_command(sample_record())
    assert db.size_bytes() > 0
