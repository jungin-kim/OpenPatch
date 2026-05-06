from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.event_service import record_event
from repooperator_worker.services.command_service import preview_command, run_command_with_policy
from repooperator_worker.services.permissions_service import permission_profile

READ_ONLY_COMMANDS = {
    ("git", "status"),
    ("git", "branch"),
    ("git", "diff", "--stat"),
    ("glab", "mr", "list"),
    ("glab", "mr", "view"),
    ("glab", "pipeline", "list"),
}

MUTATING_PREFIXES = {
    ("git", "checkout", "-b"),
    ("git", "add"),
    ("git", "commit"),
    ("git", "push"),
    ("glab", "mr", "create"),
}


@dataclass(frozen=True)
class ToolCommand:
    argv: list[str]
    kind: str
    requires_confirmation: bool
    allowed: bool
    reason: str


def get_tools_status() -> dict[str, Any]:
    profile = permission_profile()
    tools = []
    for tool in ("git", "glab"):
        path = shutil.which(tool)
        version = _version(tool) if path else None
        auth_status = _auth_status(tool) if path else "missing"
        tools.append(
            {
                "name": tool,
                "installed": bool(path),
                "path": path,
                "version": version,
                "auth_status": auth_status,
            }
        )
    return {
        "tools": tools,
        "permissions": {
            "mode": profile["mode"],
            "sandbox_scope": profile["sandbox"]["scope"],
            **profile["tools"],
        },
    }


def preview_tool_run(argv: list[str]) -> dict[str, Any]:
    command = _classify(argv)
    payload = {
        "argv": command.argv,
        "kind": command.kind,
        "requires_confirmation": command.requires_confirmation,
        "allowed": command.allowed,
        "reason": command.reason,
        "cwd": str(_active_repo_path()) if _active_repo_path() else None,
    }
    if command.allowed:
        payload["command_preview"] = preview_command(command.argv, reason=command.reason)
    return payload


def run_tool(argv: list[str], confirmed: bool = False, approval_id: str | None = None) -> dict[str, Any]:
    command = _classify(argv)
    repo_path = _active_repo_path()
    if repo_path is None:
        raise ValueError("Open a repository before running local tools.")
    if not command.allowed:
        raise ValueError(command.reason)
    if command.requires_confirmation and not approval_id:
        raise ValueError("This command requires explicit confirmation before it can run.")
    result = run_command_with_policy(
        command.argv,
        approval_id=approval_id,
        remember_for_session=confirmed,
        project_path=str(repo_path),
        reason=command.reason,
    )
    record_event(
        event_type="tool_run",
        repo=str(repo_path),
        status=result.get("status", "ok"),
        summary=" ".join(command.argv),
        tool=command.argv[0],
        command=command.argv,
        error=(result.get("stderr") or "")[:500] if result.get("exit_code") else None,
    )
    return {
        "argv": command.argv,
        "cwd": str(repo_path),
        "returncode": result.get("exit_code"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


def _classify(argv: list[str]) -> ToolCommand:
    clean = [part.strip() for part in argv if part and part.strip()]
    if not clean:
        return ToolCommand([], "invalid", False, False, "Command is empty.")
    if clean[0] not in {"git", "glab"}:
        return ToolCommand(clean, "blocked", False, False, "Only git and glab are currently supported.")
    if shutil.which(clean[0]) is None:
        return ToolCommand(clean, "missing", False, False, f"{clean[0]} is not installed.")

    key = tuple(clean[:3]) if clean[:3] in [list(item) for item in READ_ONLY_COMMANDS] else tuple(clean[:2])
    if tuple(clean[:3]) in READ_ONLY_COMMANDS or tuple(clean[:2]) in READ_ONLY_COMMANDS:
        return ToolCommand(clean, "read-only", False, True, "Safe read-only command.")
    for prefix in MUTATING_PREFIXES:
        if tuple(clean[: len(prefix)]) == prefix:
            return ToolCommand(clean, "mutating", True, True, "Mutating command requires explicit confirmation.")
    return ToolCommand(clean, "blocked", False, False, "Command is not in RepoOperator's allowlist.")


def _active_repo_path() -> Path | None:
    active = get_active_repository()
    if not active:
        return None
    return resolve_project_path(active.project_path)


def _version(tool: str) -> str | None:
    try:
        import subprocess

        result = subprocess.run([tool, "--version"], text=True, capture_output=True, timeout=5, check=False)
    except OSError:
        return None
    return (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else None


def _auth_status(tool: str) -> str:
    if tool == "glab":
        try:
            import subprocess

            result = subprocess.run(["glab", "auth", "status"], text=True, capture_output=True, timeout=8, check=False)
        except OSError:
            return "unknown"
        if result.returncode == 0:
            return "authenticated"
        return "not authenticated"
    return "not applicable"
