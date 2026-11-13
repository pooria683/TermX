"""Headless command-line interface.

TermX is primarily a desktop app, but a small CLI is genuinely useful:

    termx doctor                 diagnose environment and AI connectivity
    termx run "list large files" generate, show, and (after confirmation) run
    termx --ask "how do I ..."   ask the AI a question

The CLI shares the exact same core services as the GUI, which also makes the
whole pipeline testable without a display server.
"""

from __future__ import annotations

import argparse
import sys

from termx import APP_NAME, APP_TAGLINE, APP_VERSION
from termx.core.ai_service import AIService
from termx.core.database import Database
from termx.core.models import ConnectionState, ExecutionStatus
from termx.core.shell import ShellRunner, available_shells, detect_default_shell


def print_help() -> None:
    print(
        f"""{APP_NAME} {APP_VERSION} — {APP_TAGLINE}

USAGE
    termx                     Launch the desktop application
    termx doctor              Check Python, Qt, Ollama, models, and shells
    termx run "<request>"     Generate a command, confirm, then run it
    termx ask "<question>"    Ask the local AI a question
    termx history             Show recent command history
    termx --version           Print the version

OPTIONS for `run`
    --shell powershell|cmd|bash|zsh
    --yes                     Skip the confirmation prompt (use with care)
    --explain                 Also ask the AI to explain the command
"""
    )


def doctor() -> int:
    """Environment + AI diagnostics."""
    import platform

    print(f"{APP_NAME} {APP_VERSION}  ·  {APP_TAGLINE}\n")
    rows: list[tuple[str, str, bool]] = []
    rows.append(("Python", platform.python_version(), sys.version_info >= (3, 10)))
    try:
        from PySide6 import __version__ as pyside_version

        rows.append(("PySide6", pyside_version, True))
    except ImportError:
        rows.append(("PySide6", "not installed", False))
    rows.append(("Platform", f"{platform.system()} {platform.release()}", True))
    rows.append(("Shells", ", ".join(s.label for s in available_shells()), True))

    settings = Database().load_settings()
    rows.append(("Settings", f"{settings.model} @ {settings.ollama_host}", True))

    service = AIService(model=settings.model)
    service.configure(host=settings.ollama_host)
    state, detail = service.check_connection()
    rows.append(("Ollama", detail, state is ConnectionState.CONNECTED))
    if state is not ConnectionState.OFFLINE:
        models = service.list_models()
        rows.append(
            (
                "Models",
                ", ".join(m.name for m in models) if models else "none installed",
                bool(models),
            )
        )
    print(f"{'CHECK':<12} {'STATUS':<6} DETAIL")
    print("-" * 72)
    for name, detail, ok in rows:
        print(f"{name:<12} {'ok' if ok else 'WARN':<6} {detail}")
    service.client.close()
    print()
    if state is ConnectionState.OFFLINE:
        print("Ollama is not reachable. Install it from ollama.com and run `ollama serve`.")
        print("TermX still works using its offline command library.")
    return 0


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes", "")


def run_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="termx run", add_help=True)
    parser.add_argument("request", nargs="+", help="Natural-language request")
    parser.add_argument("--shell", choices=[s.value for s in available_shells()], default=None)
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args(argv)

    from pathlib import Path

    request = " ".join(args.request)
    shell = next((s for s in available_shells() if s.value == args.shell), None) or detect_default_shell()
    settings = Database().load_settings()
    service = AIService(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        offline_fallback=settings.offline_fallback,
    )
    service.configure(host=settings.ollama_host)

    print(f"Request: {request}")
    print(f"Shell:   {shell.label}\n")
    outcome = service.generate_command(request, shell, str(Path.cwd()))
    if not outcome.ok or outcome.suggestion is None:
        print(f"Could not generate a command: {outcome.error}", file=sys.stderr)
        return 1

    suggestion = outcome.suggestion
    verdict = service.validate_suggestion(suggestion)
    source = "offline library" if suggestion.generated_by == "offline" else suggestion.model
    print(f"Command: {suggestion.command}")
    print(f"Risk:    {verdict.risk.label}" + (f" ({'; '.join(verdict.reasons[:2])})" if verdict.reasons else ""))
    print(f"Source:  {source}")
    if suggestion.explanation:
        print(f"\n{suggestion.explanation}\n")

    if args.explain:
        text, _offline = service.explain_command(suggestion.command, shell)
        print(f"{text}\n")

    if verdict.blocked:
        print("Blocked by TermX safety rules. Refusing to run.", file=sys.stderr)
        return 2
    if not args.yes and not _confirm("Run this command? [Y/n] "):
        print("Cancelled.")
        return 0

    runner = ShellRunner()
    result = runner.run(suggestion.command, shell, str(Path.cwd()), settings.timeout_seconds)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
        if not result.stderr.endswith("\n"):
            print(file=sys.stderr)

    if result.status is ExecutionStatus.FAILED:
        explanation = service.explain_error(result)
        print(f"\nTermX diagnosis: {explanation.summary}", file=sys.stderr)
        for hint in explanation.suggestions:
            print(f"  • {hint}", file=sys.stderr)
        if explanation.corrected_command:
            print(f"  Try: {explanation.corrected_command}", file=sys.stderr)
    service.client.close()
    return 0 if result.status is ExecutionStatus.SUCCESS else 1


def ask(question: str) -> int:
    settings = Database().load_settings()
    service = AIService(model=settings.model)
    service.configure(host=settings.ollama_host)
    try:
        answer = service.ask(question, detect_default_shell())
    except Exception as exc:
        print(f"AI unavailable: {exc}", file=sys.stderr)
        return 1
    print(answer)
    service.client.close()
    return 0


def show_history(limit: int = 20) -> int:
    db = Database()
    records = db.list_commands(limit=limit)
    if not records:
        print("No command history yet.")
        return 0
    for record in records:
        when = record.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        print(f"{when}  [{record.status.value:<9}] {record.command}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print_help()
        return 0
    command, rest = args[0], args[1:]
    if command in ("-h", "--help", "help"):
        print_help()
        return 0
    if command in ("-V", "--version", "version"):
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if command == "doctor":
        return doctor()
    if command == "run":
        return run_command(rest)
    if command in ("ask", "--ask"):
        return ask(" ".join(rest))
    if command == "history":
        return show_history()
    print(f"Unknown command: {command}\n", file=sys.stderr)
    print_help()
    return 64


if __name__ == "__main__":
    sys.exit(main())
