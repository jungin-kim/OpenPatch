"""Thread context extraction and symbol tracking.

Public API
----------
- build_thread_context  — build ThreadContext from conversation history
- extract_symbols_from_text — extract defined symbols from source text

Context references are resolved by context_reference_service. This module only
extracts durable thread state and validates exact symbol/file carry-over.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.common import ensure_relative_to_repo, get_repooperator_home_dir, resolve_project_path

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
    context = _load_durable_context(request) or ThreadContext(active_repo=request.project_path, branch=request.branch)
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


def update_thread_context(request: AgentRunRequest, response: Any) -> None:
    if not request.thread_id:
        return
    context = build_thread_context(request)
    for file_path in getattr(response, "files_read", []) or []:
        _add_recent_file(context, str(file_path))
    for file_path in getattr(response, "resolved_files", []) or []:
        _add_recent_file(context, str(file_path))
    selected = getattr(response, "selected_target_file", None) or getattr(response, "proposal_relative_path", None)
    if selected:
        context.last_proposed_target_file = str(selected)
        _add_recent_file(context, str(selected))
    if getattr(response, "proposal_relative_path", None):
        context.last_proposal_id = str(getattr(response, "proposal_relative_path"))
    if getattr(response, "recommendation_context", None):
        context.last_answer_summary = "Stored structured repository recommendations."
    if getattr(response, "response", None):
        context.last_answer_summary = _summarize(str(getattr(response, "response")))
    for symbol in getattr(response, "resolved_symbols", []) or []:
        if context.recent_files:
            context.symbols.setdefault(str(symbol), context.recent_files[0])
    context.context_source = "durable_thread"
    _save_durable_context(request.thread_id, context)


def resolve_followup_file(request: AgentRunRequest, context: ThreadContext) -> tuple[str | None, str]:
    """Deprecated exact-symbol fallback; use context_reference_service for references."""
    lowered = request.task.lower()
    for symbol, relative_path in context.symbols.items():
        if symbol.lower() in lowered:
            return relative_path, "recent_thread"
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


def _summarize(text: str, max_len: int = 300) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "..."
    return cleaned


def _thread_context_path(thread_id: str) -> Path:
    safe = "".join(ch for ch in thread_id if ch.isalnum() or ch in {"_", "-"})
    path = get_repooperator_home_dir() / "threads"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe}.context.json"


def _load_durable_context(request: AgentRunRequest) -> ThreadContext | None:
    if not request.thread_id:
        return None
    path = _thread_context_path(request.thread_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("active_repo") != request.project_path:
        return None
    return ThreadContext(
        active_repo=request.project_path,
        branch=request.branch or payload.get("branch"),
        recent_files=[str(item) for item in payload.get("recent_files", []) if isinstance(item, str)],
        symbols={str(key): str(value) for key, value in (payload.get("symbols") or {}).items()},
        last_analyzed_file=payload.get("last_analyzed_file"),
        last_proposed_target_file=payload.get("last_proposed_target_file"),
        last_candidate_files=[str(item) for item in payload.get("last_candidate_files", []) if isinstance(item, str)],
        last_proposal_id=payload.get("last_proposal_id"),
        last_answer_summary=payload.get("last_answer_summary"),
        context_source="durable_thread",
    )


def _save_durable_context(thread_id: str, context: ThreadContext) -> None:
    payload = {
        "active_repo": context.active_repo,
        "branch": context.branch,
        "recent_files": context.recent_files[:20],
        "symbols": context.symbols,
        "last_analyzed_file": context.last_analyzed_file,
        "last_proposed_target_file": context.last_proposed_target_file,
        "last_candidate_files": context.last_candidate_files[:20],
        "last_proposal_id": context.last_proposal_id,
        "last_answer_summary": context.last_answer_summary,
    }
    _thread_context_path(thread_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_thread_context_items(limit: int = 100) -> dict[str, Any]:
    directory = get_repooperator_home_dir() / "threads"
    items: list[dict[str, Any]] = []
    if not directory.exists():
        return {"items": []}
    for path in sorted(directory.glob("*.context.json"), key=lambda item: item.stat().st_mtime if item.exists() else 0):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            items.append({"thread_id": path.name.removesuffix(".context.json"), **payload})
    return {"items": list(reversed(items[-limit:]))}
