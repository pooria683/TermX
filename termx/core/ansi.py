"""ANSI escape sequence handling for terminal output.

Shell output frequently contains SGR colour codes (especially from PowerShell,
git, and ls aliases). TermX converts them into spans the Qt terminal widget can
render, instead of leaking raw escape codes into the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANSI_RE = re.compile(
    r"""
    \x1b                     # ESC
    (?:
        \[[0-?]*[ -/]*[@-~]  # CSI ... final byte
      | \][^\x07\x1b]*(?:\x07|\x1b\\)  # OSC ... BEL or ST
      | [@-Z\\-_]            # two-character sequences
    )
    """,
    re.VERBOSE,
)

# xterm 256-colour palette (compact representation of the standard cube).
_BASE16 = [
    "#000000",
    "#cd3131",
    "#0dbc79",
    "#e5e510",
    "#2472c8",
    "#bc3fbc",
    "#11a8cd",
    "#e5e5e5",
    "#666666",
    "#f14c4c",
    "#23d18b",
    "#f5f543",
    "#3b8eea",
    "#d670d6",
    "#29b8db",
    "#ffffff",
]


def _cube_level(index: int) -> int:
    return 0 if index == 0 else 55 + index * 40


def palette_color(index: int) -> str:
    """Return a hex colour for a 256-colour palette ``index``."""
    if index < 16:
        return _BASE16[index]
    if index < 232:
        n = index - 16
        return f"#{_cube_level(n // 36):02x}{_cube_level((n // 6) % 6):02x}{_cube_level(n % 6):02x}"
    level = 8 + (index - 232) * 10
    return f"#{level:02x}{level:02x}{level:02x}"


@dataclass
class TextSpan:
    text: str
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    dim: bool = False


@dataclass
class AnsiState:
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    dim: bool = False

    def reset(self) -> None:
        self.fg = self.bg = None
        self.bold = self.italic = self.underline = self.dim = False


def strip_ansi(text: str) -> str:
    """Remove every ANSI escape sequence from ``text``."""
    return ANSI_RE.sub("", text)


def _apply_sgr(state: AnsiState, params: list[int]) -> None:
    if not params:
        params = [0]
    i = 0
    while i < len(params):
        code = params[i]
        if code == 0:
            state.reset()
        elif code == 1:
            state.bold = True
        elif code == 2:
            state.dim = True
        elif code == 3:
            state.italic = True
        elif code == 4:
            state.underline = True
        elif code == 22:
            state.bold = state.dim = False
        elif code == 23:
            state.italic = False
        elif code == 24:
            state.underline = False
        elif 30 <= code <= 37:
            state.fg = _BASE16[code - 30]
        elif code == 39:
            state.fg = None
        elif 40 <= code <= 47:
            state.bg = _BASE16[code - 40]
        elif code == 49:
            state.bg = None
        elif 90 <= code <= 97:
            state.fg = _BASE16[code - 90 + 8]
        elif 100 <= code <= 107:
            state.bg = _BASE16[code - 100 + 8]
        elif code in (38, 48):
            target = "fg" if code == 38 else "bg"
            if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                setattr(state, target, palette_color(params[i + 2]))
                i += 2
            elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                r, g, b = params[i + 2], params[i + 3], params[i + 4]
                setattr(state, target, f"#{r:02x}{g:02x}{b:02x}")
                i += 4
        i += 1


def parse_ansi(text: str) -> list[TextSpan]:
    """Split ``text`` into styled spans. Newlines are preserved inside spans."""
    spans: list[TextSpan] = []
    state = AnsiState()
    position = 0
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            spans.append(
                TextSpan(
                    "".join(buffer),
                    fg=state.fg,
                    bg=state.bg,
                    bold=state.bold,
                    italic=state.italic,
                    underline=state.underline,
                    dim=state.dim,
                )
            )
            buffer.clear()

    for match in ANSI_RE.finditer(text):
        chunk = text[position : match.start()]
        if chunk:
            buffer.append(chunk)
        seq = match.group(0)
        if seq.startswith("\x1b[") and seq.endswith("m"):
            flush()
            body = seq[2:-1]
            try:
                params = [int(p) for p in body.replace(";", " ").split()] if body else []
            except ValueError:
                params = []
            _apply_sgr(state, params)
        # Non-SGR sequences (cursor moves, title changes) are dropped.
        position = match.end()

    tail = text[position:]
    if tail:
        buffer.append(tail)
    flush()
    return spans


def has_ansi(text: str) -> bool:
    return bool(ANSI_RE.search(text))
