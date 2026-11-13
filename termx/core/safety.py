"""Static command safety analysis.

TermX never executes a command blindly: every generated or manually typed
command is scanned by this engine first. The engine is intentionally
conservative and deterministic — it is the last line of defence, independent
of whatever the language model claims about risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from termx.core.models import RiskLevel, SafetyVerdict, ShellType


# --------------------------------------------------------------------------- #
# Rule definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    """A single safety rule."""

    id: str
    pattern: str
    risk: RiskLevel
    reason: str
    shells: tuple[ShellType, ...] = ()
    flags: int = re.IGNORECASE

    def applies_to(self, shell: ShellType) -> bool:
        return not self.shells or shell in self.shells


_S = ShellType
_ALL = ()
_PS = (_S.POWERSHELL,)
_CMD = (_S.CMD,)
_POSIX = (_S.BASH, _S.ZSH)

RULES: tuple[Rule, ...] = (
    # ----- catastrophic / irreversible --------------------------------------
    # Catastrophic rules deliberately ignore the shell filter: a destructive
    # pattern must be blocked whichever shell the user happens to have selected.
    Rule(
        "rm-root",
        r"\brm\b[^\n]*\s--[a-z-]+[^\n]*\s/\s*($|;|&|\|)|"
        r"\brm\s+(-[a-zA-Z]+\s+)*-?[a-zA-Z]*(r[a-zA-Z]*f|f[a-zA-Z]*r)[a-zA-Z]*\s+(-[a-zA-Z-]+\s+)*/\s*($|;|&|\|)",
        RiskLevel.BLOCKED,
        "Recursively deleting the filesystem root is irreversible.",
    ),
    Rule(
        "rm-root-glob",
        r"\brm\b[^\n]*\s-{1,2}[a-zA-Z-]*[rf][a-zA-Z-]*[^\n]*\s/\*",
        RiskLevel.BLOCKED,
        "Deleting /* destroys the operating system.",
    ),
    Rule("format-volume", r"\bformat(-volume)?\s+[a-z](:|/$|$)", RiskLevel.BLOCKED, "Formatting a volume erases every file on it."),
    Rule("format-D", r"\bformat\s+[a-z]:", RiskLevel.BLOCKED, "Formatting a volume erases every file on it."),
    Rule(
        "format-volume-letter",
        r"\bformat-volume\b[^\n]*-driveletter\s+[a-z]\b",
        RiskLevel.BLOCKED,
        "Formatting a volume erases every file on it.",
    ),
    Rule(
        "diskpart-clean", r"\bdiskpart\b[\s\S]*\bclean\b", RiskLevel.BLOCKED, "DISKPART clean wipes the partition table of a disk."
    ),
    Rule("mkfs", r"\bmkfs(\.\w+)?\s+/dev/", RiskLevel.BLOCKED, "Formatting a block device destroys all data on it.", _POSIX),
    Rule(
        "dd-device",
        r"\bdd\s+[^\n]*of=/dev/(sd|nvme|hd|disk)",
        RiskLevel.BLOCKED,
        "Writing raw bytes to a block device destroys the disk.",
        _POSIX,
    ),
    Rule("fork-bomb", r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:", RiskLevel.BLOCKED, "Fork bomb — will exhaust system resources."),
    Rule(
        "shutdown-now",
        r"\bshutdown\b[^\n]*(\/s|\/r|-h|-r|--poweroff|--reboot)",
        RiskLevel.CAUTION,
        "Powers the machine off or restarts it immediately.",
        (_S.POWERSHELL, _S.CMD),
    ),
    Rule("stop-computer", r"\bstop-computer\b", RiskLevel.CAUTION, "Shuts down this computer immediately.", _PS),
    Rule("clear-disk", r"\bclear-disk\b", RiskLevel.BLOCKED, "Clear-Disk erases partition and volume data.", _PS),
    Rule(
        "initialize-disk",
        r"\binitialize-disk\b",
        RiskLevel.DESTRUCTIVE,
        "Initialize-Disk destroys the existing partition layout.",
        _PS,
    ),
    Rule("remove-partition", r"\bremove-partition\b", RiskLevel.DESTRUCTIVE, "Removes a disk partition and its data.", _PS),
    Rule("bcdedit", r"\bbcdedit\b", RiskLevel.DESTRUCTIVE, "Editing boot configuration can make Windows unbootable."),
    # ----- credential / privacy exposure ------------------------------------
    Rule("net-user-add", r"\bnet\s+user\s+\S+\s+\S+\s+/add", RiskLevel.DESTRUCTIVE, "Creates a new local user account.", _CMD),
    Rule("add-localuser", r"\bnew-localuser\b", RiskLevel.DESTRUCTIVE, "Creates a new local user account.", _PS),
    Rule(
        "disable-defender",
        r"\bset-mppreference\b[^\n]*-disable",
        RiskLevel.DESTRUCTIVE,
        "Disables Windows Defender protection.",
        _PS,
    ),
    Rule(
        "firewall-off",
        r"\bset-netfirewallprofile\b[^\n]*-enabled\s+(false|0)",
        RiskLevel.DESTRUCTIVE,
        "Turns off the Windows firewall.",
        _PS,
    ),
    Rule(
        "netsh-firewall-off",
        r"\bnetsh\s+advfirewall\s+set\b[^\n]*\boff\b",
        RiskLevel.DESTRUCTIVE,
        "Turns off the Windows firewall.",
        _CMD,
    ),
    Rule("reg-delete", r"\breg\s+delete\b", RiskLevel.CAUTION, "Deletes registry keys or values.", _CMD),
    Rule(
        "remove-item-registry",
        r"\bremove-item\b[^\n]*hklm:|hkey_local_machine",
        RiskLevel.DESTRUCTIVE,
        "Deletes registry keys under HKLM.",
        _PS,
    ),
    # ----- privilege escalation ---------------------------------------------
    Rule(
        "runas-admin",
        r"\bstart-process\b[^\n]*\b-verb\s+runas",
        RiskLevel.CAUTION,
        "Launches a process elevated (UAC prompt).",
        _PS,
    ),
    Rule("sudo", r"\bsudo\b", RiskLevel.CAUTION, "Runs the command with administrator rights.", _POSIX),
    Rule("takeown", r"\btakeown\b", RiskLevel.CAUTION, "Takes ownership of files, changing ACLs.", _CMD),
    Rule("icacls-grant", r"\bicacls\b[^\n]*\b/grant\b", RiskLevel.CAUTION, "Changes file permissions.", _CMD),
    # ----- data loss --------------------------------------------------------
    Rule(
        "rm-force-recursive",
        r"\brm\b[^\n]*(?:\s-[a-zA-Z]*r[a-zA-Z]*f|\s-[a-zA-Z]*f[a-zA-Z]*r|\s-[rf]{2}\b|"
        r"\s-{1,2}[a-z-]*(recursive|force))",
        RiskLevel.DESTRUCTIVE,
        "Recursively and forcibly deletes files.",
    ),
    Rule(
        "rm-recursive",
        r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\b",
        RiskLevel.DESTRUCTIVE,
        "Recursively deletes files and folders.",
        _POSIX,
    ),
    Rule("remove-item-recurse", r"\bremove-item\b[^\n]*-recurse", RiskLevel.DESTRUCTIVE, "Recursively deletes files or folders."),
    Rule("remove-item-force", r"\bremove-item\b[^\n]*-force", RiskLevel.DESTRUCTIVE, "Force-deletes items without prompting."),
    Rule(
        "remove-item-root",
        r"\bremove-item\b[^\n]*\s(?:[a-z]:\\?|/)\s*($|;|&|\|)",
        RiskLevel.BLOCKED,
        "Deleting a drive root or the filesystem root is irreversible.",
    ),
    Rule("del-recursive", r"\b(rd|rmdir)\s+/s", RiskLevel.DESTRUCTIVE, "Recursively deletes a directory tree.", _CMD),
    Rule(
        "del-wipe",
        r"\bdel\s+(/[a-z]+\s+)+\S",
        RiskLevel.DESTRUCTIVE,
        "Force-deletes files, possibly including whole directories, without prompting.",
        _CMD,
    ),
    Rule(
        "del-wipe-any-shell",
        r"\bdel\s+(/[a-z]+\s+)*/[fsq][a-z/\s]",
        RiskLevel.DESTRUCTIVE,
        "Force-deletes files, possibly including whole directories, without prompting.",
    ),
    Rule("del-root", r"\bdel\b[^\n]*\s[a-z]:\\\*?\s*($|;|&|\|)", RiskLevel.BLOCKED, "Wiping a whole drive is irreversible."),
    Rule("git-clean", r"\bgit\s+clean\b[^\n]*-[a-z]*[fd]", RiskLevel.DESTRUCTIVE, "Permanently removes untracked files.", _POSIX),
    Rule("git-reset-hard", r"\bgit\s+reset\b[^\n]*--hard", RiskLevel.DESTRUCTIVE, "Discards all uncommitted changes."),
    Rule(
        "git-push-force", r"\bgit\s+push\b[^\n]*(--force|-f)\b", RiskLevel.CAUTION, "Force-pushes and can overwrite remote history."
    ),
    Rule("drop-database", r"\bdrop\s+(database|schema)\b", RiskLevel.DESTRUCTIVE, "Drops an entire database or schema."),
    Rule("truncate-table", r"\btruncate\s+table\b", RiskLevel.DESTRUCTIVE, "Deletes every row of a table."),
    Rule("dd-overwrite", r"\bdd\s+[^\n]*of=", RiskLevel.CAUTION, "dd writes raw data and can overwrite files.", _POSIX),
    Rule("chmod-777", r"\bchmod\s+(-r\s+)?777\b", RiskLevel.CAUTION, "Grants full access to everyone.", _POSIX),
    Rule(
        "move-system",
        r"\bmove-item\b[^\n]*c:\\windows",
        RiskLevel.DESTRUCTIVE,
        "Moves system files — Windows may stop working.",
        _PS,
    ),
    # ----- network / download -----------------------------------------------
    Rule(
        "invoke-expression",
        r"\b(invoke-expression|iex)\b",
        RiskLevel.DESTRUCTIVE,
        "Executes dynamically downloaded or built strings — a common malware pattern.",
        _PS,
    ),
    Rule(
        "download-execute",
        r"\b(curl|wget|invoke-webrequest|iwr)\b[^\n]*\|\s*(bash|sh|iex|powershell)",
        RiskLevel.DESTRUCTIVE,
        "Pipes a remote script straight into an interpreter.",
    ),
    Rule(
        "encoded-command",
        r"\s-(e|enc|encodedcommand)\s+[A-Za-z0-9+/=]{20,}",
        RiskLevel.DESTRUCTIVE,
        "Runs a base64-encoded PowerShell payload, hiding its content.",
        _PS,
    ),
    Rule(
        "disable-execution-policy",
        r"\bset-executionpolicy\b[^\n]*\b(unrestricted|bypass)\b",
        RiskLevel.DESTRUCTIVE,
        "Lowers PowerShell's script execution protections.",
        _PS,
    ),
    Rule(
        "network-fetch",
        r"\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm)\b",
        RiskLevel.CAUTION,
        "Downloads content from the network.",
    ),
    Rule(
        "package-install",
        r"\b(pip3?|npm|yarn|pnpm|winget|choco|scoop|apt(-get)?|brew|gem|cargo|dotnet)\s+(install|add|i)\b",
        RiskLevel.CAUTION,
        "Installs software or packages onto this machine.",
    ),
    Rule(
        "package-remove",
        r"\b(pip3?|npm|yarn|pnpm|winget|choco|scoop|apt(-get)?|brew|gem|cargo)\s+(uninstall|remove|rm)\b",
        RiskLevel.CAUTION,
        "Removes installed software or packages.",
    ),
    Rule(
        "publish-remote",
        r"\bgit\s+push\b|\bdocker\s+push\b|\bnpm\s+publish\b|\btwine\s+upload\b",
        RiskLevel.CAUTION,
        "Sends data to a remote server.",
    ),
    Rule("netcat-listen", r"\bnc\s+-l", RiskLevel.CAUTION, "Opens a listening network socket.", _POSIX),
    Rule(
        "ssh-keygen-overwrite", r"\bssh-keygen\b[^\n]*-f\s+\S+\s+[^\n]*-y", RiskLevel.CAUTION, "May overwrite an existing SSH key."
    ),
    # ----- processes / services ---------------------------------------------
    Rule("stop-process-all", r"\bstop-process\b[^\n]*-(name\s+)?\*", RiskLevel.CAUTION, "Terminates every matching process.", _PS),
    Rule("taskkill-force", r"\btaskkill\b[^\n]*/f", RiskLevel.CAUTION, "Force-kills processes; unsaved work is lost.", _CMD),
    Rule(
        "kill-all", r"\bkillall\b|\bkill\s+-9\s+-1\b", RiskLevel.CAUTION, "Kills processes without letting them clean up.", _POSIX
    ),
    Rule("sc-delete", r"\bsc(\.exe)?\s+delete\b", RiskLevel.CAUTION, "Deletes a Windows service.", _CMD),
    Rule("remove-service", r"\bremove-service\b", RiskLevel.CAUTION, "Deletes a Windows service.", _PS),
    Rule(
        "disable-service",
        r"\bset-service\b[^\n]*-startuptype\s+disabled",
        RiskLevel.CAUTION,
        "Disables a service permanently.",
        _PS,
    ),
    # ----- read-only / benign hints -----------------------------------------
    Rule("list-dir", r"^\s*(get-childitem|ls|dir|gci)\b", RiskLevel.SAFE, "Lists directory contents."),
    Rule("get-location", r"^\s*(get-location|pwd|cd|set-location)\b", RiskLevel.SAFE, "Reads or changes the working directory."),
    Rule("read-file", r"^\s*(get-content|cat|type|head|tail|less|more)\b", RiskLevel.SAFE, "Reads file contents."),
    Rule(
        "system-info",
        r"^\s*(get-(computerinfo|process|service|date|volume|disk|netip|netadapter)|"
        r"systeminfo|whoami|hostname|ipconfig|ver|uname)\b",
        RiskLevel.SAFE,
        "Reads system information.",
    ),
)

_WHITELIST_START = re.compile(
    r"^\s*(get-|select-|where-|sort-|measure-|format-|out-|test-|resolve-|find-|"
    r"dir\b|ls\b|cat\b|type\b|echo\b|pwd\b|whoami\b|hostname\b|ipconfig\b|systeminfo\b|"
    r"tree\b|where\b|which\b|df\b|du\b|free\b|uname\b|date\b|time\b|env\b|ver\b|"
    r"git\s+(status|log|diff|show|branch|rev-parse|remote|describe|shortlog|blame|ls-files)\b|"
    r"docker\s+(ps|images|logs|inspect|version)\b|"
    r"python3?\s+--version|node\s+--version|npm\s+--version|pip3?\s+(list|show|--version)|"
    r"head\b|tail\b|wc\b|stat\b|file\b|grep\b|rg\b|jq\b|curl\s+-I)",
    re.IGNORECASE,
)

# Multi-command separators: each segment is analysed independently.
_SEGMENT_SPLIT = re.compile(r"(\|\||&&|;|\||\n)")

# Dangerous redirect targets.
_REDIRECT_RULES = (
    (re.compile(r">\s*(/dev/sd|\\\\\.\\physicaldrive)", re.IGNORECASE), "Redirecting output to a raw device destroys it."),
    (
        re.compile(r">\s*[a-z]:\\\\?(windows|system32)", re.IGNORECASE),
        "Overwriting files inside the Windows directory breaks the OS.",
    ),
)


class SafetyAnalyzer:
    """Deterministic rule-based risk assessment for shell commands."""

    def __init__(self, rules: tuple[Rule, ...] = RULES) -> None:
        self._rules = rules
        self._compiled = [(rule, re.compile(rule.pattern, rule.flags)) for rule in rules]

    # -- public API ---------------------------------------------------------
    def analyze(
        self,
        command: str,
        shell: ShellType = ShellType.POWERSHELL,
        *,
        block_forbidden: bool = True,
        confirm_destructive: bool = True,
    ) -> SafetyVerdict:
        """Return a :class:`SafetyVerdict` for ``command``."""
        text = (command or "").strip()
        if not text:
            return SafetyVerdict(risk=RiskLevel.SAFE, reasons=["Empty command."], requires_confirmation=False)

        risk = RiskLevel.SAFE
        reasons: list[str] = []
        matched: list[str] = []
        order = {RiskLevel.SAFE: 0, RiskLevel.CAUTION: 1, RiskLevel.DESTRUCTIVE: 2, RiskLevel.BLOCKED: 3}

        segments = [seg for seg in _SEGMENT_SPLIT.split(text) if seg and seg.strip() not in ("|", "||", "&&", ";")]
        # Analyse the whole text as well: some patterns span pipelines.
        for candidate in [text, *segments]:
            for rule, regex in self._compiled:
                if not rule.applies_to(shell):
                    continue
                if rule.id in matched:
                    continue
                if regex.search(candidate):
                    matched.append(rule.id)
                    if order[rule.risk] > order[risk]:
                        risk = rule.risk
                    reasons.append(rule.reason)

        for regex, message in _REDIRECT_RULES:
            if regex.search(text):
                matched.append("dangerous-redirect")
                risk = RiskLevel.BLOCKED
                reasons.append(message)

        if risk is RiskLevel.SAFE and not _WHITELIST_START.match(text):
            # Unknown verbs get a light caution so the user reads the preview.
            risk = RiskLevel.CAUTION
            reasons.append("TermX could not classify this command as read-only — review it before running.")

        if risk is RiskLevel.SAFE and not reasons:
            reasons.append("Read-only command with no detected side effects.")

        blocked = risk is RiskLevel.BLOCKED and block_forbidden
        requires_confirmation = risk is not RiskLevel.SAFE or confirm_destructive
        return SafetyVerdict(
            risk=risk,
            reasons=list(dict.fromkeys(reasons)),
            requires_confirmation=requires_confirmation,
            blocked=blocked,
            matched_rules=matched,
        )

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def risk_from_label(label: str | None) -> RiskLevel:
        """Parse a model-supplied risk label defensively."""
        if not label:
            return RiskLevel.SAFE
        value = str(label).strip().lower()
        mapping = {
            "safe": RiskLevel.SAFE,
            "low": RiskLevel.SAFE,
            "read-only": RiskLevel.SAFE,
            "readonly": RiskLevel.SAFE,
            "caution": RiskLevel.CAUTION,
            "medium": RiskLevel.CAUTION,
            "moderate": RiskLevel.CAUTION,
            "destructive": RiskLevel.DESTRUCTIVE,
            "high": RiskLevel.DESTRUCTIVE,
            "dangerous": RiskLevel.DESTRUCTIVE,
            "blocked": RiskLevel.BLOCKED,
            "critical": RiskLevel.BLOCKED,
            "forbidden": RiskLevel.BLOCKED,
        }
        return mapping.get(value, RiskLevel.CAUTION)

    def is_read_only(self, command: str, shell: ShellType = ShellType.POWERSHELL) -> bool:
        return self.analyze(command, shell).risk is RiskLevel.SAFE
