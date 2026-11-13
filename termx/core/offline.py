"""Offline intelligence.

TermX must stay useful when Ollama is not installed or the model is missing.
This module provides:

* a curated intent library that maps common natural-language requests to
  verified commands for PowerShell, CMD, Bash and Zsh;
* a rule-based error explainer covering the most frequent shell failures.

Both are deterministic, fast, and testable — and they double as a safety net
when the model returns something unusable.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from termx.core.models import CommandSuggestion, ErrorExplanation, RiskLevel, ShellType


@dataclass(frozen=True)
class Intent:
    """A known natural-language intent with per-shell commands."""

    id: str
    keywords: tuple[str, ...]
    title: str
    commands: dict[ShellType, str]
    explanation: str
    risk: RiskLevel = RiskLevel.SAFE
    alternative: str | None = None

    def score(self, text: str) -> int:
        """Keyword overlap score; longer keyword matches weigh more."""
        total = 0
        for keyword in self.keywords:
            if " " in keyword:
                if keyword in text:
                    total += len(keyword.split()) * 3
            elif re.search(rf"\b{re.escape(keyword)}\b", text):
                total += 2
        return total


_INTENTS: tuple[Intent, ...] = (
    Intent(
        "list-files",
        ("list", "files", "ls", "dir", "directory", "contents", "show", "folder"),
        "List directory contents",
        {
            ShellType.POWERSHELL: "Get-ChildItem -Force | Format-Table Mode, LastWriteTime, Length, Name -AutoSize",
            ShellType.CMD: "dir /a",
            ShellType.BASH: "ls -lah --group-directories-first",
            ShellType.ZSH: "ls -lah --group-directories-first",
        },
        "Lists every entry in the current directory, including hidden files, with size and modification time.",
    ),
    Intent(
        "large-files",
        ("large", "biggest", "big", "size", "huge", "space", "consume"),
        "Find the largest files",
        {
            ShellType.POWERSHELL: (
                "Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | "
                "Sort-Object Length -Descending | Select-Object -First 15 "
                "@{N='SizeMB';E={[math]::Round($_.Length/1MB,2)}}, FullName | Format-Table -AutoSize"
            ),
            ShellType.CMD: ('forfiles /S /C "cmd /c if @fsize gtr 10485760 echo @fsize @path" 2>nul'),
            ShellType.BASH: "find . -type f -printf '%s\\t%p\\n' 2>/dev/null | sort -rn | head -15 | numfmt --to=iec",
            ShellType.ZSH: "find . -type f -size +10M -exec ls -lh {} + 2>/dev/null | sort -k5 -h | tail -15",
        },
        "Scans the current directory recursively and prints the 15 largest files with their sizes in MB.",
    ),
    Intent(
        "disk-space",
        ("disk", "space", "free", "storage", "drive", "capacity", "available"),
        "Check available disk space",
        {
            ShellType.POWERSHELL: (
                "Get-PSDrive -PSProvider FileSystem | "
                "Select-Object Name, @{N='UsedGB';E={[math]::Round($_.Used/1GB,2)}}, "
                "@{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}} | Format-Table -AutoSize"
            ),
            ShellType.CMD: "wmic logicaldisk get DeviceID,VolumeName,Size,FreeSpace",
            ShellType.BASH: "df -hT -x tmpfs -x devtmpfs",
            ShellType.ZSH: "df -h",
        },
        "Shows each mounted drive with its used and free space in GB.",
    ),
    Intent(
        "memory-usage",
        ("memory", "ram", "usage", "used", "consuming", "hogging"),
        "Show memory usage by process",
        {
            ShellType.POWERSHELL: (
                "Get-Process | Sort-Object WS -Descending | Select-Object -First 10 "
                "Name, Id, @{N='RAM_MB';E={[math]::Round($_.WS/1MB,1)}} | Format-Table -AutoSize"
            ),
            ShellType.CMD: "tasklist /fo table",
            ShellType.BASH: "ps aux --sort=-%mem | head -11",
            ShellType.ZSH: "ps aux -m | head -11",
        },
        "Lists the top ten processes by resident memory, so you can spot what is using your RAM.",
    ),
    Intent(
        "cpu-usage",
        ("cpu", "processor", "load", "heavy", "busy"),
        "Show CPU-heavy processes",
        {
            ShellType.POWERSHELL: (
                "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 "
                "Name, Id, @{N='CPU_s';E={[math]::Round($_.CPU,1)}} | Format-Table -AutoSize"
            ),
            ShellType.CMD: "wmic path Win32_PerfFormattedData_PerfProc_Process get Name,PercentProcessorTime",
            ShellType.BASH: "ps aux --sort=-%cpu | head -11",
            ShellType.ZSH: "ps aux -r | head -11",
        },
        "Ranks the ten processes with the highest cumulative CPU time.",
    ),
    Intent(
        "network-ip",
        ("ip", "address", "network", "ipconfig", "ipv4", "adapter"),
        "Show network configuration",
        {
            ShellType.POWERSHELL: "Get-NetIPConfiguration | Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway",
            ShellType.CMD: "ipconfig /all",
            ShellType.BASH: "ip -brief address",
            ShellType.ZSH: "ifconfig | grep -E '^[a-z]|inet '",
        },
        "Prints each network adapter with its IP address and default gateway.",
    ),
    Intent(
        "ping-host",
        ("ping", "reachable", "connectivity", "latency", "online"),
        "Test connectivity to a host",
        {
            ShellType.POWERSHELL: "Test-Connection -ComputerName 8.8.8.8 -Count 4",
            ShellType.CMD: "ping -n 4 8.8.8.8",
            ShellType.BASH: "ping -c 4 8.8.8.8",
            ShellType.ZSH: "ping -c 4 8.8.8.8",
        },
        "Sends four ICMP echo requests to 8.8.8.8 to confirm internet connectivity and measure latency.",
    ),
    Intent(
        "current-path",
        ("where", "path", "pwd", "cwd", "working", "location"),
        "Show the current directory",
        {
            ShellType.POWERSHELL: "Get-Location",
            ShellType.CMD: "cd",
            ShellType.BASH: "pwd",
            ShellType.ZSH: "pwd",
        },
        "Prints the absolute path of the directory the terminal is currently in.",
    ),
    Intent(
        "env-vars",
        ("environment", "env", "variables", "variable"),
        "List environment variables",
        {
            ShellType.POWERSHELL: "Get-ChildItem Env: | Sort-Object Name | Format-Table Name, Value -AutoSize",
            ShellType.CMD: "set",
            ShellType.BASH: "env | sort",
            ShellType.ZSH: "env | sort",
        },
        "Displays every environment variable visible to this shell session.",
        RiskLevel.CAUTION,
    ),
    Intent(
        "installed-programs",
        ("installed", "programs", "software", "applications", "apps"),
        "List installed applications",
        {
            ShellType.POWERSHELL: (
                "Get-ItemProperty "
                "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, "
                "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
                "| Where-Object DisplayName | Select-Object DisplayName, DisplayVersion, Publisher "
                "| Sort-Object DisplayName | Format-Table -AutoSize"
            ),
            ShellType.CMD: "wmic product get name,version",
            ShellType.BASH: "command -v dpkg >/dev/null && dpkg-query -W -f='${Package}\\t${Version}\\n' | head -60 || true",
            ShellType.ZSH: "brew list --versions 2>/dev/null | head -60 || ls /Applications",
        },
        "Reads the Windows uninstall registry keys and lists installed software with version and publisher.",
    ),
    Intent(
        "find-file",
        ("find", "search", "locate", "file", "named", "called"),
        "Search for files by name",
        {
            ShellType.POWERSHELL: "Get-ChildItem -Recurse -File -Filter *name* -ErrorAction SilentlyContinue | Select-Object -First 25 FullName",
            ShellType.CMD: "where /r . *name*",
            ShellType.BASH: "find . -type f -iname '*name*' 2>/dev/null | head -25",
            ShellType.ZSH: "find . -type f -iname '*name*' 2>/dev/null | head -25",
        },
        "Searches the current directory tree for files whose name contains the pattern and shows the first 25 matches.",
    ),
    Intent(
        "search-text",
        ("grep", "contains", "text", "search", "string", "content", "find in files"),
        "Search inside files",
        {
            ShellType.POWERSHELL: "Get-ChildItem -Recurse -File -Include *.txt,*.py,*.md | Select-String -Pattern 'search-term' | Select-Object -First 20",
            ShellType.CMD: 'findstr /S /I /N "search-term" *.*',
            ShellType.BASH: "grep -rIn --exclude-dir=.git 'search-term' . | head -20",
            ShellType.ZSH: "grep -rIn --exclude-dir=.git 'search-term' . | head -20",
        },
        "Recursively searches file contents for the given text and prints matching lines with file names and line numbers.",
    ),
    Intent(
        "system-info",
        ("system", "info", "specs", "hardware", "computer", "machine", "os", "version"),
        "Show system information",
        {
            ShellType.POWERSHELL: (
                "$os = Get-CimInstance Win32_OperatingSystem; "
                "$cs = Get-CimInstance Win32_ComputerSystem; "
                "[pscustomobject]@{ OS=$os.Caption; Version=$os.Version; "
                "RAM_GB=[math]::Round($cs.TotalPhysicalMemory/1GB,1); Model=$cs.Model } | Format-List"
            ),
            ShellType.CMD: "systeminfo",
            ShellType.BASH: "uname -a && (lsb_release -a 2>/dev/null || cat /etc/os-release | head -4)",
            ShellType.ZSH: "uname -a && sw_vers 2>/dev/null || cat /etc/os-release | head -4",
        },
        "Reports the operating system, version, total RAM, and machine model.",
    ),
    Intent(
        "running-processes",
        ("processes", "process", "running", "tasks", "apps running"),
        "List running processes",
        {
            ShellType.POWERSHELL: "Get-Process | Sort-Object -Property ProcessName | Format-Table Id, ProcessName, CPU, WS -AutoSize",
            ShellType.CMD: "tasklist /fo table",
            ShellType.BASH: "ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -25",
            ShellType.ZSH: "ps -eo pid,comm,%cpu,%mem | head -25",
        },
        "Lists running processes with their process ID, name, CPU time, and memory use.",
    ),
    Intent(
        "kill-process",
        ("kill", "terminate", "stop", "end process", "close process"),
        "Terminate a process by name",
        {
            ShellType.POWERSHELL: "Stop-Process -Name notepad -Force -WhatIf",
            ShellType.CMD: "taskkill /IM notepad.exe /F",
            ShellType.BASH: "pkill -f notepad",
            ShellType.ZSH: "pkill -f notepad",
        },
        "Stops the named process. Adjust the name to the process you want to end. -WhatIf previews without acting.",
        RiskLevel.CAUTION,
        alternative="Stop-Process -Name notepad -Force",
    ),
    Intent(
        "current-date",
        ("date", "time", "today", "clock", "now"),
        "Show the current date and time",
        {
            ShellType.POWERSHELL: "Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'",
            ShellType.CMD: "date /t && time /t",
            ShellType.BASH: "date '+%Y-%m-%d %H:%M:%S %Z'",
            ShellType.ZSH: "date '+%Y-%m-%d %H:%M:%S %Z'",
        },
        "Prints the current local date and time.",
    ),
    Intent(
        "git-status",
        ("git", "status", "repository", "changes", "uncommitted"),
        "Show git repository status",
        {
            ShellType.POWERSHELL: "git status --short --branch",
            ShellType.CMD: "git status --short --branch",
            ShellType.BASH: "git status --short --branch",
            ShellType.ZSH: "git status --short --branch",
        },
        "Shows the current branch and any staged, unstaged, or untracked changes in the repository.",
    ),
    Intent(
        "git-log",
        ("git", "log", "commits", "history", "recent commits"),
        "Show recent commits",
        {
            ShellType.POWERSHELL: "git log --oneline --graph --decorate -n 15",
            ShellType.CMD: "git log --oneline --graph --decorate -n 15",
            ShellType.BASH: "git log --oneline --graph --decorate -n 15",
            ShellType.ZSH: "git log --oneline --graph --decorate -n 15",
        },
        "Displays the last 15 commits as a compact graph with branch decorations.",
    ),
    Intent(
        "python-version",
        ("python", "version", "py"),
        "Check Python version",
        {
            ShellType.POWERSHELL: "python --version; py --version",
            ShellType.CMD: "python --version",
            ShellType.BASH: "python3 --version",
            ShellType.ZSH: "python3 --version",
        },
        "Prints the installed Python interpreter version.",
    ),
    Intent(
        "open-port",
        ("port", "listening", "open ports", "network connections"),
        "Check listening ports",
        {
            ShellType.POWERSHELL: "Get-NetTCPConnection -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize",
            ShellType.CMD: "netstat -ano | findstr LISTENING",
            ShellType.BASH: "ss -tulpn 2>/dev/null || netstat -tulpn",
            ShellType.ZSH: "lsof -nP -iTCP -sTCP:LISTEN",
        },
        "Lists TCP ports currently waiting for connections, with the owning process ID.",
    ),
    Intent(
        "docker-containers",
        ("docker", "containers", "container"),
        "List Docker containers",
        {
            ShellType.POWERSHELL: "docker ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'",
            ShellType.CMD: "docker ps -a",
            ShellType.BASH: "docker ps -a",
            ShellType.ZSH: "docker ps -a",
        },
        "Lists all Docker containers with image, status, and published ports.",
    ),
    Intent(
        "uptime",
        ("uptime", "boot", "since", "started"),
        "Show how long the machine has been running",
        {
            ShellType.POWERSHELL: (
                "$b = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime; "
                "[pscustomobject]@{ Booted=$b; Uptime=(New-TimeSpan -Start $b) } | Format-List"
            ),
            ShellType.CMD: 'net statistics workstation | findstr /i "since"',
            ShellType.BASH: "uptime -p; uptime -s",
            ShellType.ZSH: "uptime",
        },
        "Shows the last boot time and the elapsed uptime of the machine.",
    ),
    Intent(
        "user-info",
        ("whoami", "user", "account", "logged in"),
        "Show the current user",
        {
            ShellType.POWERSHELL: "whoami; [System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
            ShellType.CMD: "whoami",
            ShellType.BASH: "id -un && id",
            ShellType.ZSH: "id -un && id",
        },
        "Prints the account name of the user running this shell and its group memberships.",
    ),
    Intent(
        "folder-size",
        ("folder", "directory size", "how big", "size of"),
        "Measure folder sizes",
        {
            ShellType.POWERSHELL: (
                "Get-ChildItem -Directory | ForEach-Object { "
                "$s = (Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue "
                "| Measure-Object Length -Sum).Sum; "
                "[pscustomobject]@{ Folder=$_.Name; SizeMB=[math]::Round($s/1MB,2) } } "
                "| Sort-Object SizeMB -Descending | Format-Table -AutoSize"
            ),
            ShellType.CMD: 'for /d %d in (*) do @dir /s /-c "%d" | findstr /c:"File(s)"',
            ShellType.BASH: "du -sh */ 2>/dev/null | sort -rh | head -20",
            ShellType.ZSH: "du -sh */ 2>/dev/null | sort -rh | head -20",
        },
        "Computes the total size of every immediate subfolder and ranks them largest first.",
    ),
    Intent(
        "clear-screen",
        ("clear", "clean", "wipe screen", "reset screen"),
        "Clear the terminal",
        {
            ShellType.POWERSHELL: "Clear-Host",
            ShellType.CMD: "cls",
            ShellType.BASH: "clear",
            ShellType.ZSH: "clear",
        },
        "Clears the visible terminal output.",
    ),
    Intent(
        "create-folder",
        ("create", "make", "new folder", "mkdir"),
        "Create a directory",
        {
            ShellType.POWERSHELL: "New-Item -ItemType Directory -Path '.\\new-folder' -Force",
            ShellType.CMD: "mkdir new-folder",
            ShellType.BASH: "mkdir -p ./new-folder",
            ShellType.ZSH: "mkdir -p ./new-folder",
        },
        "Creates a new folder called new-folder in the current directory. Change the name as needed.",
        RiskLevel.CAUTION,
    ),
)


class OfflineEngine:
    """Deterministic fallback brain used when no model is available."""

    def __init__(self, intents: tuple[Intent, ...] = _INTENTS) -> None:
        self._intents = intents

    # -- generation ---------------------------------------------------------
    def match_intent(self, request: str) -> tuple[Intent, int] | None:
        text = (request or "").lower().strip()
        if not text:
            return None
        best: tuple[Intent, int] | None = None
        for intent in self._intents:
            score = intent.score(text)
            if score > 0 and (best is None or score > best[1]):
                best = (intent, score)
        return best

    def suggest(self, request: str, shell: ShellType) -> CommandSuggestion | None:
        matched = self.match_intent(request)
        if matched is None:
            return None
        intent, _score = matched
        command = intent.commands.get(shell) or intent.commands[ShellType.BASH]
        return CommandSuggestion(
            request=request,
            command=command,
            shell=shell,
            explanation=intent.explanation,
            risk=intent.risk,
            risk_reason="Classified by TermX's built-in safety library.",
            alternative=intent.alternative,
            notes=["Generated offline from TermX's intent library — install a local model for free-form requests."],
            generated_by="offline",
            model="offline-rules",
        )

    def examples(self, limit: int = 8) -> list[str]:
        seen: list[str] = []
        for intent in self._intents:
            text = intent.title[0].lower() + intent.title[1:]
            if text not in seen:
                seen.append(text)
            if len(seen) >= limit:
                break
        return seen

    # -- error explanation --------------------------------------------------
    def explain_error(
        self,
        command: str,
        stderr: str,
        stdout: str = "",
        exit_code: int | None = None,
        shell: ShellType = ShellType.POWERSHELL,
    ) -> ErrorExplanation:
        haystack = f"{stderr}\n{stdout}".lower()
        for pattern, explanation in _ERROR_RULES:
            if re.search(pattern, haystack, re.IGNORECASE):
                corrected = explanation.corrected(command, stderr, shell) if explanation.corrected else None
                return ErrorExplanation(
                    summary=explanation.summary,
                    cause=explanation.cause,
                    suggestions=list(explanation.suggestions),
                    corrected_command=corrected,
                    source="offline",
                    confidence=explanation.confidence,
                )

        if exit_code not in (None, 0):
            return ErrorExplanation(
                summary=f"The command exited with code {exit_code}.",
                cause="The shell reported failure but TermX has no specific rule for this message.",
                suggestions=[
                    "Read the error text above — it usually names the missing file, flag, or permission.",
                    "Run the command again with a verbose flag if one is available.",
                    "Ask TermX's AI Terminal to explain the error once a model is installed.",
                ],
                source="offline",
                confidence=0.3,
            )
        return ErrorExplanation(
            summary="No error output was captured.",
            cause="The command produced no stderr and exited successfully — or the failure was silent.",
            suggestions=["Check the exit code in the status bar.", "Re-run with verbose output."],
            source="offline",
            confidence=0.2,
        )

    # -- intent-based command extraction for free text ----------------------
    @staticmethod
    def extract_command_from_text(text: str, shell: ShellType) -> str | None:
        """Pull a command out of a chit-chat reply if the model ignored the schema."""
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("command:"):
                candidate = stripped.split(":", 1)[1].strip().strip("`")
                if candidate:
                    return candidate
        return None


@dataclass(frozen=True)
class _ErrorRule:
    summary: str
    cause: str
    suggestions: tuple[str, ...]
    confidence: float = 0.75
    corrected: object = None


def _fix_ps_not_recognized(command: str, stderr: str, shell: ShellType) -> str | None:
    """Suggest an installed cmdlet when PowerShell reports one as unknown."""
    match = re.search(r"['\"]([A-Za-z][\w-]+)['\"] (?:is not recognized|was not found)", stderr, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1)
    known = {
        "gci": "Get-ChildItem",
        "ls": "Get-ChildItem",
        "dir": "Get-ChildItem",
        "cat": "Get-Content",
        "rm": "Remove-Item",
        "cp": "Copy-Item",
        "mv": "Move-Item",
        "curl": "Invoke-WebRequest",
        "wget": "Invoke-WebRequest",
        "ps": "Get-Process",
        "kill": "Stop-Process",
        "clear": "Clear-Host",
        "cls": "Clear-Host",
    }
    replacement = known.get(token.lower())
    if not replacement:
        return None
    return re.sub(rf"\b{re.escape(token)}\b", replacement, command, count=1)


def _fix_path_spaces(command: str, stderr: str, shell: ShellType) -> str | None:
    match = re.search(r"'([^']*\s[^']*)'", stderr)
    if not match:
        return None
    path = match.group(1)
    if shell is ShellType.CMD:
        return command.replace(path, f'"{path}"')
    return command.replace(path, f"'{path}'") if f"'{path}'" not in command else None


_ERROR_RULES: tuple[tuple[str, _ErrorRule], ...] = (
    (
        r"is not recognized as (the name of|a name of) a cmdlet|command not found|not recognized as an internal",
        _ErrorRule(
            summary="The shell could not find that command or program.",
            cause="The name is misspelled, the tool is not installed, or it is not on PATH.",
            suggestions=(
                "Check the spelling of the command.",
                "Confirm the tool is installed (e.g. `Get-Command <name>` or `which <name>`).",
                "Add the tool's folder to PATH, or call it with its full path.",
            ),
            confidence=0.85,
            corrected=_fix_ps_not_recognized,
        ),
    ),
    (
        r"access is denied|permission denied|unauthorizedaccess|access to the path",
        _ErrorRule(
            summary="The command was blocked by file or system permissions.",
            cause="The account running TermX lacks rights to that path or resource.",
            suggestions=(
                "Re-run TermX as administrator, or retry from an elevated shell.",
                "Choose a location under your user profile instead of a protected folder.",
                "Check the file's ACLs with `Get-Acl <path>`.",
            ),
            confidence=0.9,
        ),
    ),
    (
        r"cannot find path|does not exist|no such file or directory|the system cannot find the (file|path)",
        _ErrorRule(
            summary="A file or directory in the command does not exist.",
            cause="The path is wrong, or it is relative to a different working directory.",
            suggestions=(
                "Verify the path with `Get-ChildItem` / `ls`.",
                "Check the current directory in the status bar.",
                "Wrap paths containing spaces in quotes.",
            ),
            confidence=0.9,
            corrected=_fix_path_spaces,
        ),
    ),
    (
        r"the term .* is not recognized|unrecognized option|unknown option|invalid parameter",
        _ErrorRule(
            summary="The shell rejected one of the command's arguments.",
            cause="The flag or parameter does not exist for this tool version.",
            suggestions=(
                "Check the tool's help (`Get-Help <cmd> -Full` or `<cmd> --help`).",
                "Remove or correct the offending flag.",
            ),
            confidence=0.8,
        ),
    ),
    (
        r"used by another process|being used by another process|resource busy|device or resource busy",
        _ErrorRule(
            summary="A file or resource is locked by another process.",
            cause="Another program holds an open handle to the file.",
            suggestions=(
                "Close the application that is using the file.",
                "Find the owner with `Get-Process | Where-Object {$_.Modules.FileName -like '*name*'}`.",
            ),
            confidence=0.85,
        ),
    ),
    (
        r"cannot overwrite|already exists",
        _ErrorRule(
            summary="The target already exists.",
            cause="The command refuses to replace an existing file or folder.",
            suggestions=("Rename the target or add a force flag only if overwriting is intended.",),
            confidence=0.8,
        ),
    ),
    (
        r"network|name or service not known|could not resolve host|connection refused|timed out",
        _ErrorRule(
            summary="A network request failed.",
            cause="DNS resolution, the connection, or the remote service is unavailable.",
            suggestions=(
                "Check connectivity with `Test-Connection 8.8.8.8` / `ping 8.8.8.8`.",
                "Confirm the host name and port are correct.",
                "Check firewall or proxy settings.",
            ),
            confidence=0.8,
        ),
    ),
    (
        r"not a git repository",
        _ErrorRule(
            summary="The current folder is not a git repository.",
            cause="The command ran outside a working tree.",
            suggestions=("cd into the repository root, or run `git init` to create one.",),
            confidence=0.95,
        ),
    ),
    (
        r"no module named|modulenotfounderror",
        _ErrorRule(
            summary="A required Python module is missing.",
            cause="The package is not installed in the active Python environment.",
            suggestions=(
                "Install it with `pip install <package>`.",
                "Confirm you are using the expected virtual environment.",
            ),
            confidence=0.95,
        ),
    ),
    (
        r"fatal: (?!.*not a git)",
        _ErrorRule(
            summary="Git reported a fatal error.",
            cause="The repository state does not allow this operation.",
            suggestions=("Run `git status` to inspect the working tree before retrying.",),
            confidence=0.7,
        ),
    ),
)


def platform_default_shell() -> ShellType:
    if sys.platform == "win32":
        return ShellType.POWERSHELL
    if sys.platform == "darwin":
        return ShellType.ZSH
    return ShellType.BASH
