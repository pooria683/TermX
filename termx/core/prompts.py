"""Prompt engineering for TermX's command generation.

Prompts are kept in one place so they can be tuned, unit-tested, and kept in
sync with the JSON schema the parser expects.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

from termx.core.models import ShellType

RESPONSE_SCHEMA = """{
  "command": "the exact shell command to run (single line preferred; use newlines only for multi-step)",
  "explanation": "2-4 sentences explaining what the command does and why it is appropriate",
  "risk": "one of: safe | caution | destructive",
  "risk_reason": "short justification for the risk level",
  "alternative": "an optional safer or more modern alternative command",
  "notes": ["optional short tips, prerequisites, or platform caveats"]
}"""

SYSTEM_TEMPLATE = """You are TermX, an expert {platform} systems engineer embedded in a terminal assistant.

Your job: convert a user's natural-language request into ONE valid {shell_label} command.

HARD RULES
1. Reply with a single JSON object and nothing else. No markdown, no commentary.
2. The command must run unattended in {shell_label} on {platform}.
3. Never invent paths or usernames; use relative paths or {home_hint}.
4. Prefer read-only commands. Never delete data unless the user explicitly asks to.
5. If the request is ambiguous, choose the most common interpretation and mention it in "notes".
6. If the request cannot be expressed as a shell command, set "command" to "" and explain in "explanation".
7. Keep commands portable to {shell_label} {shell_note}.
8. Explain in plain language a non-expert can follow. Do not repeat the command verbatim in the explanation.

JSON SCHEMA
{schema}

Risk levels:
- "safe": read-only (listing, reading, querying, diagnostics).
- "caution": writes files, changes settings, needs elevation, network downloads.
- "destructive": deletes/overwrites data, kills processes, modifies boot/registry, disables security.

CONTEXT
- Shell: {shell_label}
- Working directory: {cwd}
- OS: {os_detail}
- Other TermX sessions used these commands recently: {recent}
"""

EXPLAIN_TEMPLATE = """You are TermX, explaining a shell command to a user who is not a shell expert.

Command ({shell_label}):
{command}

Write a clear explanation with:
- What the command does, step by step (cover each flag/parameter).
- What it changes on the system (files, processes, settings) or that it is read-only.
- Anything to watch out for.
- If there is a safer or simpler alternative, mention it.

Format: 3-6 short sentences or bullet points. No markdown headings. Be precise, no filler.
"""

ERROR_TEMPLATE = """You are TermX, diagnosing a failed shell command.

Shell: {shell_label}
Working directory: {cwd}
Command: {command}
Exit code: {exit_code}

--- stdout ---
{stdout}

--- stderr ---
{stderr}

Respond with a single JSON object and nothing else:
{{
  "summary": "one-line plain-language statement of what went wrong",
  "cause": "the technical root cause",
  "suggestions": ["2-4 concrete actions the user can take"],
  "corrected_command": "a fixed command, or empty string if a command will not help",
  "confidence": 0.0
}}

Only propose a corrected command when you are confident it is correct and non-destructive.
"""

SUGGEST_TEMPLATE = """You are TermX. The user is in {cwd} on {platform} using {shell_label}.

They typed a natural-language request. Produce ONE valid {shell_label} command for it, or an empty string.

Request: {request}

Respond with a single JSON object:
{{"command": "...", "explanation": "...", "risk": "safe|caution|destructive"}}
"""

CHAT_SYSTEM = """You are TermX, a concise terminal assistant running inside a desktop app.
Answer in at most 4 sentences. When a shell command helps, put it on its own line starting with "Command:".
Prefer {shell_label} syntax. Never invent system state you cannot observe."""


@dataclass(frozen=True)
class PromptContext:
    """Environment details injected into prompts."""

    shell: ShellType
    cwd: str
    recent_commands: tuple[str, ...] = ()

    @property
    def platform_name(self) -> str:
        if sys.platform == "win32":
            return "Windows"
        if sys.platform == "darwin":
            return "macOS"
        return "Linux"

    @property
    def home_hint(self) -> str:
        return "%USERPROFILE%" if sys.platform == "win32" else "~"

    @property
    def os_detail(self) -> str:
        return f"{platform.system()} {platform.release()} ({platform.machine()})"

    @property
    def shell_note(self) -> str:
        return {
            ShellType.POWERSHELL: "5.1 and 7+",
            ShellType.CMD: "Windows 10/11",
            ShellType.BASH: "4+",
            ShellType.ZSH: "5+",
        }.get(self.shell, "current version")


def build_system_prompt(context: PromptContext) -> str:
    recent = ", ".join(context.recent_commands[:5]) if context.recent_commands else "none"
    return SYSTEM_TEMPLATE.format(
        platform=context.platform_name,
        shell_label=context.shell.label,
        schema=RESPONSE_SCHEMA,
        cwd=context.cwd,
        home_hint=context.home_hint,
        os_detail=context.os_detail,
        shell_note=context.shell_note,
        recent=recent,
    )


def build_user_prompt(request: str, context: PromptContext) -> str:
    return (
        f"User request: {request.strip()}\n\n"
        f"Target shell: {context.shell.label}\n"
        f"Working directory: {context.cwd}\n"
        "Respond with the JSON object only."
    )


def build_messages(request: str, context: PromptContext) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": build_system_prompt(context)},
        {"role": "user", "content": build_user_prompt(request, context)},
    ]


def build_explain_messages(command: str, shell: ShellType) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are a precise, friendly terminal tutor. Answer in plain text only."},
        {"role": "user", "content": EXPLAIN_TEMPLATE.format(command=command.strip(), shell_label=shell.label)},
    ]


def build_error_messages(
    command: str, shell: ShellType, cwd: str, exit_code: int | None, stdout: str, stderr: str
) -> list[dict[str, str]]:
    content = ERROR_TEMPLATE.format(
        shell_label=shell.label,
        cwd=cwd,
        command=command,
        exit_code=exit_code if exit_code is not None else "unknown",
        stdout=(stdout or "(empty)")[-3000:],
        stderr=(stderr or "(empty)")[-3000:],
    )
    return [
        {"role": "system", "content": "You diagnose shell errors and reply with JSON only."},
        {"role": "user", "content": content},
    ]


def build_summary_prompt(session_title: str, commands: list[str]) -> list[dict[str, str]]:
    listing = "\n".join(f"- {c}" for c in commands[:25]) or "- (no commands)"
    return [
        {"role": "system", "content": "You summarise terminal sessions in two short sentences."},
        {
            "role": "user",
            "content": (
                f"Session: {session_title}\nCommands executed:\n{listing}\n\n"
                "Write a two-sentence summary of what the user accomplished and any unfinished work."
            ),
        },
    ]
