from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.common import ensure_relative_to_repo, resolve_project_path

SYMBOL_RE = re.compile(
    r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b|"
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\b|"
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)


@dataclass
class ThreadContext:
    active_repo: str
    branch: str | None
    recent_files: list[str] = field(default_factory=list)
    symbols: dict[str, str] = field(default_factory=dict)
    last_analyzed_file: str | None = None
    last_proposed_target_file: str | None = None
    last_candidate_files: list[str] = field(default_factory=list)
    last_proposal_id: str | None = None
    last_answer_summary: str | None = None
    context_source: str = "retrieval"

    @property
    def symbol_names(self) -> list[str]:
        return sorted(self.symbols)


def build_thread_context(request: AgentRunRequest) -> ThreadContext:
    context = ThreadContext(active_repo=request.project_path, branch=request.branch)
    for message in reversed(request.conversation_history):
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        for file_path in metadata.get("files_read") or []:
            _add_recent_file(context, str(file_path))
        selected = metadata.get("selected_target_file") or metadata.get("proposal_relative_path")
        if selected:
            context.last_proposed_target_file = str(selected)
            _add_recent_file(context, str(selected))
        candidates = metadata.get("clarification_candidates") or []
        if candidates and not context.last_candidate_files:
            context.last_candidate_files = [str(candidate) for candidate in candidates]
        if metadata.get("proposal_relative_path") and not context.last_proposal_id:
            context.last_proposal_id = str(metadata.get("proposal_relative_path"))
        for symbol in metadata.get("thread_context_symbols") or []:
            if context.recent_files:
                context.symbols.setdefault(str(symbol), context.recent_files[0])
        if message.role == "assistant" and not context.last_answer_summary:
            context.last_answer_summary = _summarize(message.content)

    for relative_path in list(context.recent_files):
        _load_file_symbols(request.project_path, relative_path, context)

    if not context.last_analyzed_file and context.recent_files:
        context.last_analyzed_file = context.recent_files[0]
    return context


def resolve_followup_file(request: AgentRunRequest, context: ThreadContext) -> tuple[str | None, str]:
    task = request.task
    lowered = task.lower()
    for symbol, relative_path in context.symbols.items():
        if symbol.lower() in lowered:
            return relative_path, "recent_thread"
    if _refers_to_previous_file(lowered) and context.last_analyzed_file:
        return context.last_analyzed_file, "recent_thread"
    if context.last_proposed_target_file and _refers_to_previous_change(lowered):
        return context.last_proposed_target_file, "recent_thread"
    return None, "retrieval"


def extract_symbols_from_text(content: str) -> list[str]:
    symbols: list[str] = []
    for match in SYMBOL_RE.finditer(content):
        symbol = next((group for group in match.groups() if group), None)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _add_recent_file(context: ThreadContext, relative_path: str) -> None:
    if relative_path and relative_path not in context.recent_files:
        context.recent_files.insert(0, relative_path)
    context.recent_files = context.recent_files[:12]


def _load_file_symbols(project_path: str, relative_path: str, context: ThreadContext) -> None:
    try:
        repo_path = resolve_project_path(project_path)
        target = ensure_relative_to_repo(repo_path, relative_path)
        if not target.is_file():
            return
        content = target.read_text(encoding="utf-8", errors="replace")[:80_000]
    except (OSError, ValueError):
        return
    for symbol in extract_symbols_from_text(content):
        context.symbols.setdefault(symbol, relative_path)


def _refers_to_previous_file(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "that file",
            "the file",
            "same file",
            "그 파일",
            "이 파일",
            "방금 파일",
            "위 파일",
        )
    )


def _refers_to_previous_change(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "that change",
            "same change",
            "proposal",
            "이대로",
            "그대로",
            "제안",
            "수정",
        )
    )


def _summarize(text: str, max_len: int = 300) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "..."
    return cleaned
