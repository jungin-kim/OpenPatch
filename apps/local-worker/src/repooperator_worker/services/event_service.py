from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.common import get_repooperator_home_dir


def _runs_dir() -> Path:
    path = get_repooperator_home_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runs_file() -> Path:
    return _runs_dir() / "runs.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def summarize_user_message(message: str, *, max_len: int = 180) -> str:
    cleaned = " ".join(message.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "..."
    return cleaned


def record_agent_run(
    *,
    run_id: str,
    request: AgentRunRequest,
    response: AgentRunResponse | None,
    status: str,
    latency_ms: int,
    error: str | None = None,
) -> dict[str, Any]:
    record = {
        "id": run_id,
        "timestamp": _now_iso(),
        "repo": request.project_path,
        "branch": request.branch,
        "user_message_summary": summarize_user_message(request.task),
        "intent": response.intent_classification if response else None,
        "graph_path": response.graph_path if response else None,
        "agent_flow": response.agent_flow if response else "langgraph",
        "model": response.model if response else None,
        "status": status,
        "latency_ms": latency_ms,
        "files_read": response.files_read if response else [],
        "thread_context_files": response.thread_context_files if response else [],
        "thread_context_symbols": response.thread_context_symbols if response else [],
        "proposal_id": response.proposal_relative_path if response else None,
        "error": error,
    }
    with _runs_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def record_event(
    *,
    event_type: str,
    repo: str | None = None,
    branch: str | None = None,
    status: str = "ok",
    summary: str = "",
    files: list[str] | None = None,
    tool: str | None = None,
    command: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    record = {
        "id": new_run_id(),
        "timestamp": _now_iso(),
        "type": event_type,
        "repo": repo,
        "branch": branch,
        "status": status,
        "summary": summarize_user_message(summary),
        "files_read": files or [],
        "tool": tool,
        "command": command,
        "error": error,
    }
    with _runs_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def list_recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    path = _runs_file()
    if not path.exists():
        return []
    runs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(runs[-limit:]))
