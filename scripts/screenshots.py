"""Render every TermX page to PNG for visual review.

Used during development and by CI to catch layout regressions without a
display server:

    QT_QPA_PLATFORM=offscreen python scripts/screenshots.py --out docs/screenshots
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import tempfile
from datetime import UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/screenshots")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--pages", default="all")
    args = parser.parse_args()

    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

    from termx.ui.app import create_application

    app, _theme = create_application([sys.argv[0]])

    # Isolated database so screenshots never touch real user data.
    tmp_dir = Path(tempfile.mkdtemp(prefix="termx-shots-"))
    from termx.core import database as database_module

    original_init = database_module.Database.__init__

    def patched_init(self, path=None):
        original_init(self, tmp_dir / "termx.db")

    database_module.Database.__init__ = patched_init  # type: ignore[method-assign]

    from termx.ui.controller import AppController
    from termx.ui.main_window import MainWindow

    controller = AppController()
    _seed(controller)

    window = MainWindow(controller)
    window.resize(args.width, args.height)
    window.show()

    def pump(ms: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    pump(400)
    controller.refresh_ai_status()
    pump(600)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = (
        ["dashboard", "terminal", "history", "sessions", "models", "settings", "about"]
        if args.pages == "all"
        else args.pages.split(",")
    )
    for page in pages:
        window.navigate(page)
        # Long enough for the dashboard's growth animation to settle: capturing
        # mid-animation produced charts with zero-height bars.
        pump(700)
        app.processEvents()
        pixmap = window.grab()
        target = out_dir / f"{page}.png"
        pixmap.save(str(target))
        print(f"saved {target}  ({pixmap.width()}x{pixmap.height()})")

    from termx.ui.app import shutdown_application

    shutdown_application(QCoreApplication.instance(), window, controller)
    del window, controller
    gc.collect()
    return 0


def _seed(controller) -> None:
    """Insert representative demo data so screenshots show a used app."""
    from datetime import datetime, timedelta

    from termx.core.models import (
        CommandRecord,
        ExecutionStatus,
        RiskLevel,
        SessionRecord,
        ShellType,
    )

    now = datetime.now(UTC)
    sessions = [
        SessionRecord(
            title="Clean up the build folder",
            shell=ShellType.POWERSHELL,
            cwd=str(controller.cwd),
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=2, minutes=40),
            is_active=False,
            summary="Removed 2.1 GB of stale build artifacts and verified free space afterwards.",
        ),
        SessionRecord(
            title="Investigate slow laptop",
            shell=ShellType.POWERSHELL,
            cwd=str(controller.cwd),
            started_at=now - timedelta(days=1, hours=2),
            ended_at=now - timedelta(days=1, hours=1),
            is_active=False,
            summary="Found four background processes using 6 GB of RAM and stopped two of them.",
        ),
        SessionRecord(
            title="Disk space audit",
            shell=ShellType.POWERSHELL,
            cwd=str(controller.cwd),
            started_at=now - timedelta(days=2),
            ended_at=now - timedelta(days=2) + timedelta(minutes=25),
            is_active=False,
            summary="Audited drive usage and identified the largest folders under the profile.",
        ),
    ]
    for session in sessions:
        controller.db.create_session(session)

    samples = [
        (
            "Show all files in the current directory",
            "Get-ChildItem -Force | Format-Table Mode, LastWriteTime, Length, Name -AutoSize",
            "Lists every entry in the current directory, including hidden files, with size and modification time.",
            ExecutionStatus.SUCCESS,
            0,
            412,
            "    Directory: C:\\Users\\dev\\projects\\termx\n\n"
            "Mode  LastWriteTime      Length Name\n"
            "----  -------------      ------ ----\n"
            "d---- 11/12/2025  09:14          src\n"
            "-a--- 11/12/2025  09:14     1284  README.md\n",
            0,
        ),
        (
            "Find the largest files in this folder",
            "Get-ChildItem -Recurse -File | Sort-Object Length -Descending | Select-Object -First 15 "
            "@{N='SizeMB';E={[math]::Round($_.Length/1MB,2)}}, FullName",
            "Scans recursively and lists the fifteen largest files with their size in megabytes.",
            ExecutionStatus.SUCCESS,
            0,
            2890,
            "SizeMB FullName\n------ --------\n284.11 C:\\Users\\dev\\Videos\\capture.mkv\n"
            "96.42  C:\\Users\\dev\\Downloads\\installer.exe\n",
            0,
        ),
        (
            "Check available disk space",
            "Get-PSDrive -PSProvider FileSystem | Select-Object Name, "
            "@{N='UsedGB';E={[math]::Round($_.Used/1GB,2)}}, "
            "@{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}} | Format-Table -AutoSize",
            "Shows each mounted drive with used and free space in gigabytes.",
            ExecutionStatus.SUCCESS,
            0,
            233,
            "Name UsedGB FreeGB\n---- ------ ------\nC    412.65 89.14\nD    121.4  806.6\n",
            0,
        ),
        (
            "Which processes are using the most memory?",
            "Get-Process | Sort-Object WS -Descending | Select-Object -First 10 Name, Id, "
            "@{N='RAM_MB';E={[math]::Round($_.WS/1MB,1)}} | Format-Table -AutoSize",
            "Lists the ten processes holding the most resident memory.",
            ExecutionStatus.SUCCESS,
            0,
            640,
            "Name       Id RAM_MB\n----       -- ------\nchrome   8124 2214.5\nCode     4412  981.2\nTeams    9032  644.8\n",
            0,
        ),
        (
            "Remove all files in the temp folder older than 30 days",
            "Get-ChildItem $env:TEMP -Recurse -File | Where-Object { $_.LastWriteTime -lt "
            "(Get-Date).AddDays(-30) } | Remove-Item -Force",
            "Deletes files in the temp directory that have not been modified for 30 days.",
            ExecutionStatus.SUCCESS,
            0,
            8100,
            "",
            0,
        ),
        (
            "Show my network configuration",
            "Get-NetIPConfiguration | Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway",
            "Prints each adapter with its IP address and default gateway.",
            ExecutionStatus.FAILED,
            1,
            150,
            "",
            0,
        ),
        (
            "List the last 15 git commits",
            "git log --oneline --graph --decorate -n 15",
            "Displays recent commits as a compact graph with branch decorations.",
            ExecutionStatus.SUCCESS,
            0,
            129,
            "* 4f2a1b9 (HEAD -> main) Polish dashboard metrics\n* 91c0dd4 Add session resume\n* 2b7ee10 Initial TermX scaffold\n",
            1,
        ),
        (
            "Show how long this machine has been running",
            "$b = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime; "
            "[pscustomobject]@{ Booted=$b; Uptime=(New-TimeSpan -Start $b) } | Format-List",
            "Shows the last boot time and elapsed uptime.",
            ExecutionStatus.SUCCESS,
            0,
            388,
            "Booted : 11/11/2025 07:42:11\nUptime : 2.05:18:42\n",
            0,
        ),
        ("Clear the terminal screen", "Clear-Host", "Clears the visible terminal output.", ExecutionStatus.SUCCESS, 0, 12, "", 0),
        (
            "Find all TODO comments in this project",
            "Get-ChildItem -Recurse -File -Include *.py,*.md | Select-String -Pattern 'TODO' | Select-Object -First 20",
            "Searches project files for TODO markers.",
            ExecutionStatus.SUCCESS,
            0,
            1540,
            "src\\controller.py:88:  # TODO: batch history writes\nsrc\\ui\\terminal.py:41: # TODO: add search-in-output\n",
            1,
        ),
        (
            "Format the D drive",
            "Format-Volume -DriveLetter D -FileSystem NTFS -Confirm:$false",
            "Formats the D: volume, erasing every file on it.",
            ExecutionStatus.BLOCKED,
            None,
            0,
            "",
            0,
        ),
        (
            "Kill the notepad process",
            "Stop-Process -Name notepad -Force",
            "Stops the notepad process without prompting.",
            ExecutionStatus.SUCCESS,
            0,
            84,
            "",
            0,
        ),
    ]

    for index, (request, command, explanation, status, exit_code, duration, output, favorite) in enumerate(samples):
        record = CommandRecord(
            session_id=controller.session.id,
            request=request,
            command=command,
            shell=ShellType.POWERSHELL,
            explanation=explanation,
            risk=RiskLevel.DESTRUCTIVE
            if "Remove-Item" in command
            else (RiskLevel.BLOCKED if status is ExecutionStatus.BLOCKED else RiskLevel.SAFE),
            status=status,
            exit_code=exit_code,
            cwd=str(controller.cwd),
            output=output,
            stderr="" if status is not ExecutionStatus.FAILED else "Command failed.",
            duration_ms=duration,
            was_blocked=status is ExecutionStatus.BLOCKED,
            favorite=bool(favorite),
            model="qwen2.5-coder:7b",
            created_at=now - timedelta(hours=index * 5, minutes=index * 7),
        )
        if status is ExecutionStatus.FAILED:
            record.stderr = "Get-NetIPConfiguration : The term is not recognized as the name of a cmdlet."
        controller.db.add_command(record)

    # Terminal page should open with a realistic exchange.
    from termx.core.models import CommandSuggestion, SafetyVerdict

    suggestion = CommandSuggestion(
        request="find files larger than 100 MB and show their size",
        command="Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Length -gt 100MB } | "
        "Sort-Object Length -Descending | "
        "Select-Object @{N='SizeMB';E={[math]::Round($_.Length/1MB,2)}}, FullName | "
        "Format-Table -AutoSize",
        shell=ShellType.POWERSHELL,
        explanation="Walks the current folder tree, keeps only files bigger than 100 MB, "
        "sorts them from largest to smallest, and prints size in MB with the full path.",
        risk=RiskLevel.SAFE,
        risk_reason="Reads file metadata only; nothing is modified.",
        model="qwen2.5-coder:7b",
    )
    controller.set_suggestion(suggestion, SafetyVerdict(risk=RiskLevel.SAFE, reasons=["Read-only command."]))


if __name__ == "__main__":
    raise SystemExit(main())
