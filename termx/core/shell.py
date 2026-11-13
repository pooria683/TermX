"""Shell abstraction: command wrapping, shell detection, and process execution.

The runner is deliberately shell-agnostic: Windows targets launch through
PowerShell / CMD, POSIX targets through bash / zsh. The same code path is used
by the GUI, the CLI, and the tests.
"""

from __future__ import annotations

import codecs
import locale
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from termx.core.models import ExecutionResult, ExecutionStatus, ShellType

IS_WINDOWS = sys.platform == "win32"

#: Hard ceiling on captured output so a runaway command cannot exhaust memory.
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


class ShellNotFoundError(RuntimeError):
    """Raised when the requested shell is not installed."""


class ExecutionError(RuntimeError):
    """Raised when a command cannot be started at all."""


def detect_default_shell() -> ShellType:
    """Pick the most appropriate shell for the current platform."""
    if IS_WINDOWS:
        if shutil.which("pwsh") or shutil.which("powershell"):
            return ShellType.POWERSHELL
        return ShellType.CMD
    if os.environ.get("SHELL", "").endswith("zsh") and shutil.which("zsh"):
        return ShellType.ZSH
    return ShellType.BASH


def available_shells() -> list[ShellType]:
    """Shells that can actually be launched on this machine."""
    found: list[ShellType] = []
    checks = {
        ShellType.POWERSHELL: ("powershell", "pwsh"),
        ShellType.CMD: ("cmd",),
        ShellType.BASH: ("bash",),
        ShellType.ZSH: ("zsh",),
    }
    for shell, names in checks.items():
        if any(shutil.which(n) for n in names):
            found.append(shell)
    if not found:
        found.append(detect_default_shell())
    return found


def decode_output(data: bytes) -> str:
    """Decode subprocess bytes using the platform's console encoding first."""
    if not data:
        return ""
    encodings: list[str] = []
    if IS_WINDOWS:
        encodings.extend(["utf-8", locale.getpreferredencoding(False), "cp1252", "mbcs"])
    else:
        encodings.append(locale.getpreferredencoding(False) or "utf-8")
        encodings.append("utf-8")
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def normalize_cwd(path: str | os.PathLike[str] | None) -> Path:
    """Return an existing directory, falling back to the user's home."""
    candidate = Path(path).expanduser() if path else Path.home()
    try:
        if candidate.is_dir():
            return candidate
    except OSError:
        pass
    return Path.home()


@dataclass
class LaunchSpec:
    """Everything needed to launch a shell command."""

    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""


class ShellRunner:
    """Builds shell-specific launch specs and executes commands."""

    def __init__(self, max_output_bytes: int = MAX_OUTPUT_BYTES) -> None:
        self.max_output_bytes = max_output_bytes

    # -- launch specs -------------------------------------------------------
    def build_launch(self, command: str, shell: ShellType) -> LaunchSpec:
        """Convert a user/AI command into an argv list for ``shell``."""
        if shell is ShellType.POWERSHELL:
            exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
            argv = [
                exe,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
        elif shell is ShellType.CMD:
            exe = os.environ.get("COMSPEC") or shutil.which("cmd") or "cmd.exe"
            argv = [exe, "/d", "/s", "/c", command]
        elif shell is ShellType.ZSH:
            argv = [shutil.which("zsh") or "/bin/zsh", "-c", command]
        else:
            argv = [shutil.which("bash") or "/bin/bash", "-c", command]
        return LaunchSpec(argv=argv, env=self.build_env(), description=shell.label)

    @staticmethod
    def build_env() -> dict[str, str]:
        """Environment for child processes: UTF-8 output, no ANSI on Windows."""
        env = dict(os.environ)
        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "PYTHONIOENCODING": "utf-8",
                "TERMX": "1",
            }
        )
        if IS_WINDOWS:
            env.setdefault("PYTHONUTF8", "1")
            env["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
            env["POWERSHELL_UPDATECHECK"] = "Off"
        return env

    # -- synchronous execution ---------------------------------------------
    def run(
        self,
        command: str,
        shell: ShellType = ShellType.POWERSHELL,
        cwd: str | os.PathLike[str] | None = None,
        timeout: int = 120,
        on_output: Callable[[str, str], None] | None = None,
    ) -> ExecutionResult:
        """Run ``command`` to completion and return a full result.

        ``on_output`` receives ``(stream, text)`` chunks as they arrive, where
        ``stream`` is ``"stdout"`` or ``"stderr"``.
        """
        workdir = normalize_cwd(cwd)
        spec = self.build_launch(command, shell)
        started = time.monotonic()
        started_at = datetime.now(UTC)

        creationflags = 0
        preexec = None
        if IS_WINDOWS:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:

            def preexec() -> None:  # pragma: no cover - POSIX only
                try:
                    os.setsid()
                except OSError:
                    pass

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        truncated = False
        lock = threading.Lock()

        def make_reader(stream, sink: list[str], name: str):
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            def pump() -> None:
                nonlocal truncated
                total = 0
                try:
                    while True:
                        chunk = stream.read(4096)
                        if not chunk:
                            break
                        text = decoder.decode(chunk)
                        total += len(chunk)
                        if total > self.max_output_bytes:
                            truncated = True
                            break
                        if not text:
                            continue
                        with lock:
                            sink.append(text)
                        if on_output:
                            on_output(name, text)
                except (ValueError, OSError):
                    pass
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass

            return pump

        try:
            process = subprocess.Popen(
                spec.argv,
                cwd=str(workdir),
                env=spec.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                preexec_fn=preexec,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            duration = int((time.monotonic() - started) * 1000)
            return ExecutionResult(
                command=command,
                shell=shell,
                cwd=str(workdir),
                exit_code=127,
                stderr=f"Shell not found: {exc}",
                status=ExecutionStatus.FAILED,
                duration_ms=duration,
                started_at=started_at,
            )
        except OSError as exc:
            duration = int((time.monotonic() - started) * 1000)
            return ExecutionResult(
                command=command,
                shell=shell,
                cwd=str(workdir),
                exit_code=126,
                stderr=f"Could not start command: {exc}",
                status=ExecutionStatus.FAILED,
                duration_ms=duration,
                started_at=started_at,
            )

        threads = [
            threading.Thread(target=make_reader(process.stdout, stdout_parts, "stdout"), daemon=True),
            threading.Thread(target=make_reader(process.stderr, stderr_parts, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            exit_code = process.wait(timeout=10) if process.poll() is None else process.returncode

        for thread in threads:
            thread.join(timeout=2)

        duration = int((time.monotonic() - started) * 1000)
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        if timed_out:
            stderr += f"\n[TermX] Command timed out after {timeout}s and was terminated."

        status = ExecutionStatus.SUCCESS if (exit_code == 0 and not timed_out) else ExecutionStatus.FAILED
        return ExecutionResult(
            command=command,
            shell=shell,
            cwd=str(workdir),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            status=status,
            duration_ms=duration,
            started_at=started_at,
            truncated=truncated,
        )

    # -- streaming execution ------------------------------------------------
    def stream(
        self,
        command: str,
        shell: ShellType = ShellType.POWERSHELL,
        cwd: str | os.PathLike[str] | None = None,
        timeout: int = 120,
    ) -> Iterator[tuple[str, str]]:
        """Yield ``(stream, text)`` chunks as the command runs (generator)."""
        queue: list[tuple[str, str]] = []
        done = threading.Event()
        holder: dict[str, ExecutionResult] = {}

        def callback(stream_name: str, text: str) -> None:
            queue.append((stream_name, text))

        def worker() -> None:
            holder["result"] = self.run(command, shell, cwd, timeout, on_output=callback)
            done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while not done.is_set() or queue:
            if queue:
                yield queue.pop(0)
            else:
                done.wait(0.02)
        if "result" in holder:
            yield "__result__", holder["result"]  # type: ignore[misc]


def terminate_process_tree(process: subprocess.Popen) -> None:
    """Kill a process and all of its children, cross-platform."""
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        process.kill()
    except Exception:
        pass


class StreamingProcess:
    """Background, cancellable command execution used by the GUI."""

    def __init__(self, runner: ShellRunner | None = None) -> None:
        self.runner = runner or ShellRunner()
        self._process: subprocess.Popen | None = None
        self._cancelled = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def cancel(self) -> None:
        self._cancelled = True
        if self._process is not None:
            terminate_process_tree(self._process)
