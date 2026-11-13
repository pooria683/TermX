"""Shell runner: launch specs, real execution and error capture."""

from __future__ import annotations

import sys

import pytest

from termx.core.models import ExecutionStatus, ShellType
from termx.core.shell import ShellRunner, available_shells, normalize_cwd

POSIX = sys.platform != "win32"


def test_powershell_launch_disables_profiles() -> None:
    spec = ShellRunner().build_launch("Get-ChildItem", ShellType.POWERSHELL)
    argv = spec.argv
    assert "-NoProfile" in argv
    assert "-NonInteractive" in argv
    assert argv[-1] == "Get-ChildItem"


def test_cmd_launch_uses_cmd_c() -> None:
    argv = ShellRunner().build_launch("dir", ShellType.CMD).argv
    assert "/c" in argv
    assert argv[-1] == "dir"


@pytest.mark.skipif(not POSIX, reason="POSIX shells only")
def test_bash_launch_uses_dash_c() -> None:
    argv = ShellRunner().build_launch("ls", ShellType.BASH).argv
    assert argv[1] == "-c"
    assert argv[-1] == "ls"


def test_build_env_forces_utf8() -> None:
    env = ShellRunner.build_env()
    assert env["PYTHONIOENCODING"].lower().startswith("utf-8")


@pytest.mark.skipif(not POSIX, reason="requires a POSIX shell")
def test_executes_and_captures_output() -> None:
    result = ShellRunner().run("echo termx-ok", ShellType.BASH, timeout=30)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert "termx-ok" in result.stdout
    assert result.duration_ms >= 0


@pytest.mark.skipif(not POSIX, reason="requires a POSIX shell")
def test_failures_report_exit_code_and_stderr() -> None:
    result = ShellRunner().run("ls /definitely/not/here", ShellType.BASH, timeout=30)
    assert result.status in (ExecutionStatus.FAILED, ExecutionStatus.SUCCESS)
    assert result.exit_code != 0
    assert result.stderr.strip()


@pytest.mark.skipif(not POSIX, reason="requires a POSIX shell")
def test_streaming_callback_receives_chunks() -> None:
    chunks: list[tuple[str, str]] = []
    ShellRunner().run("echo streamed", ShellType.BASH, timeout=30, on_output=lambda s, t: chunks.append((s, t)))
    assert chunks
    assert any("streamed" in text for stream, text in chunks if stream == "stdout")


@pytest.mark.skipif(not POSIX, reason="requires a POSIX shell")
def test_timeout_is_enforced() -> None:
    result = ShellRunner().run("sleep 10", ShellType.BASH, timeout=1)
    assert result.status in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED)
    assert result.exit_code != 0


@pytest.mark.skipif(not POSIX, reason="requires a POSIX shell")
def test_runs_in_requested_directory(tmp_path) -> None:
    result = ShellRunner().run("pwd", ShellType.BASH, cwd=tmp_path, timeout=30)
    assert str(tmp_path) in result.stdout


def test_output_is_truncated_for_huge_results() -> None:
    runner = ShellRunner(max_output_bytes=1000)
    spec = runner.build_launch("echo hi", ShellType.BASH if POSIX else ShellType.POWERSHELL)
    assert spec.argv


def test_available_shells_is_never_empty() -> None:
    shells = available_shells()
    assert shells, "TermX must always offer at least one shell"


def test_normalize_cwd_accepts_existing_folder(tmp_path) -> None:
    from pathlib import Path

    assert normalize_cwd(str(tmp_path)) == Path(tmp_path)


def test_normalize_cwd_falls_back_for_garbage() -> None:
    from pathlib import Path

    resolved = normalize_cwd("Z:/definitely/not/a/real/path/termx")
    assert resolved == Path.home()
    assert resolved.is_dir()
