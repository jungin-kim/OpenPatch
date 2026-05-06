from __future__ import annotations

from pathlib import Path
from typing import Any

from repooperator_worker.services.common import ensure_relative_to_repo, resolve_project_path
from repooperator_worker.services.command_service import preview_command


def validate_repo_file(project_path: str, relative_path: str) -> Path:
    repo_path = resolve_project_path(project_path)
    target = ensure_relative_to_repo(repo_path, relative_path)
    parts = {part.lower() for part in Path(relative_path).parts}
    if ".git" in parts:
        raise ValueError("Writes inside .git are blocked.")
    return target


def command_policy_preview(command: list[str], *, project_path: str, reason: str | None = None) -> dict[str, Any]:
    return preview_command(command, project_path=project_path, reason=reason)

