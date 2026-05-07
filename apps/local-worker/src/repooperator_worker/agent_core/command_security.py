from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from repooperator_worker.services.json_safe import json_safe


@dataclass(frozen=True)
class CommandSecurityResult:
    allowed: bool
    reason: str = ""
    findings: list[str] | None = None

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


SHELL_METACHARS = ("|", ">", ">>", "<", "&&", "||", ";")
SUBSTITUTION_PATTERNS = (r"\$\(", r"`", r"<\(", r">\(", r"\$\{[^}]+\}")
BLOCKED_BUILTINS = {"eval", "exec", "source", ".", "zmodload", "emulate", "zpty", "ztcp", "zsocket"}
POWERSHELL_NAMES = {"powershell", "pwsh", "powershell.exe", "pwsh.exe"}
POWERSHELL_BLOCKED = ("invoke-expression", "iex", "start-process")


def validate_argv_shape(command: list[str] | str) -> CommandSecurityResult:
    if isinstance(command, str):
        if any(token in command for token in SHELL_METACHARS) or any(re.search(pattern, command) for pattern in SUBSTITUTION_PATTERNS):
            return CommandSecurityResult(False, "Command must be provided as argv, not a shell-shaped string.", ["shell_string"])
        return CommandSecurityResult(False, "Command must be provided as an argv list.", ["string_command"])
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        return CommandSecurityResult(False, "Command must be an argv list of strings.", ["invalid_argv"])
    if not command or not command[0].strip():
        return CommandSecurityResult(False, "Command is empty.", ["empty"])

    findings: list[str] = []
    executable = command[0].lower()
    if executable in {"bash", "sh", "zsh", "fish", "cmd", "cmd.exe"} and any(arg in {"-c", "-lc", "/c"} for arg in command[1:3]):
        findings.append("shell_interpreter_command_string")
    if executable in BLOCKED_BUILTINS:
        findings.append("blocked_shell_builtin")
    if executable in POWERSHELL_NAMES and any(term in " ".join(command[1:]).lower() for term in POWERSHELL_BLOCKED):
        findings.append("blocked_powershell_primitive")

    for arg in command:
        stripped = arg.strip()
        if any(re.search(pattern, stripped) for pattern in SUBSTITUTION_PATTERNS):
            findings.append("command_substitution")
        if stripped in SHELL_METACHARS or any(_metachar_present(stripped, token) for token in SHELL_METACHARS):
            findings.append("shell_metacharacter")
    if findings:
        return CommandSecurityResult(False, "Command argv shape was rejected before command policy preview.", sorted(set(findings)))
    return CommandSecurityResult(True, "Command argv shape accepted.", [])


def _metachar_present(value: str, token: str) -> bool:
    if token in {"|", "&&", "||", ";"}:
        return token in value
    if token in {">", ">>", "<"}:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", value))
    return False
