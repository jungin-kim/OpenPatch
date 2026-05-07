from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.policies import command_policy_preview
from repooperator_worker.agent_core.tools.builtin import is_supported_text_file
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.command_service import run_command_with_policy
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.json_safe import json_safe
from repooperator_worker.services.skills_service import enabled_skill_context


@dataclass
class ContextPacket:
    repo_root_name: str
    repo_path: str
    branch: str | None
    git_status_summary: str | None = None
    recent_commits_summary: str | None = None
    project_instructions: dict[str, str] = field(default_factory=dict)
    high_signal_files: dict[str, str] = field(default_factory=dict)
    prior_files_read: list[str] = field(default_factory=list)
    prior_commands_run: list[str] = field(default_factory=list)
    skills_context: str = ""
    created_at: str = ""

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


class ContextService:
    def __init__(self, *, max_file_chars: int = 20_000, ttl_seconds: int = 300) -> None:
        self.max_file_chars = max_file_chars
        self.ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, str | None, str | None], tuple[float, ContextPacket]] = {}

    def collect(self, request: AgentRunRequest) -> ContextPacket:
        repo = resolve_project_path(request.project_path).resolve()
        branch = request.branch or self._git_branch(repo, request)
        key = (str(repo), branch, request.thread_id)
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] <= self.ttl_seconds:
            return cached[1]

        skills_context, _skills_used = enabled_skill_context()
        packet = ContextPacket(
            repo_root_name=repo.name,
            repo_path=str(repo),
            branch=branch,
            git_status_summary=self._git_command(repo, request, ["git", "status", "--short"]),
            recent_commits_summary=self._git_command(repo, request, ["git", "log", "--oneline", "-n", "5"]),
            project_instructions=self._read_named_files(
                repo,
                ["CLAUDE.md", "AGENTS.md", "REPOOPERATOR.md", ".repooperator/instructions.md"],
            ),
            high_signal_files=self._read_named_files(
                repo,
                [
                    "README.md",
                    "readme.md",
                    "package.json",
                    "pyproject.toml",
                    "Cargo.toml",
                    "go.mod",
                    "manifest.json",
                    "apps/web/package.json",
                    "apps/local-worker/pyproject.toml",
                ],
            ),
            prior_files_read=self._prior_metadata(request, keys=("files_read", "resolved_files")),
            prior_commands_run=self._prior_metadata(request, keys=("commands_run", "commands_planned")),
            skills_context=skills_context,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._cache[key] = (now, packet)
        return packet

    def clear(self) -> None:
        self._cache.clear()

    def _read_named_files(self, repo: Path, relative_paths: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        seen: set[str] = set()
        for rel in relative_paths:
            target = repo / rel
            try:
                marker = str(target.resolve()).lower()
            except OSError:
                marker = str(target).lower()
            if marker in seen or not target.is_file() or not is_supported_text_file(target):
                continue
            seen.add(marker)
            try:
                result[rel] = target.read_text(encoding="utf-8", errors="replace")[: self.max_file_chars]
            except OSError:
                continue
        return result

    def _prior_metadata(self, request: AgentRunRequest, *, keys: tuple[str, ...]) -> list[str]:
        values: list[str] = []
        for item in request.conversation_history[-12:]:
            metadata = item.metadata or {}
            for key in keys:
                raw = metadata.get(key) or []
                if isinstance(raw, str):
                    raw = [raw]
                for value in raw:
                    text = str(value).strip()
                    if text and text not in values:
                        values.append(text)
        return values[:40]

    def _git_branch(self, repo: Path, request: AgentRunRequest) -> str | None:
        summary = self._git_command(repo, request, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
        return summary.splitlines()[0].strip() if summary else None

    def _git_command(self, repo: Path, request: AgentRunRequest, command: list[str]) -> str | None:
        if not (repo / ".git").exists():
            return None
        try:
            preview = command_policy_preview(command, project_path=request.project_path, reason="Collect bounded repository context.")
        except Exception:
            return None
        if preview.get("blocked") or preview.get("needs_approval") or not preview.get("read_only"):
            return None
        try:
            result = run_command_with_policy(command, project_path=request.project_path, reason="Collect bounded repository context.")
        except Exception:
            return None
        text = str(result.get("stdout") or "").strip()
        return text[:4_000] or None


_DEFAULT_CONTEXT_SERVICE = ContextService()


def get_default_context_service() -> ContextService:
    return _DEFAULT_CONTEXT_SERVICE
