from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse, FileWriteRequest
from repooperator_worker.services.common import get_repooperator_home_dir

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
]

MEMORY_TRIGGER_RE = re.compile(r"(?i)\bremember\b|기억해|기억해줘|잊지마")


def _memory_dir() -> Path:
    path = get_repooperator_home_dir() / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _memory_file() -> Path:
    return _memory_dir() / "memories.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sanitize(text: str, *, max_len: int = 800) -> str:
    cleaned = text.strip()
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "..."
    return cleaned


def add_memory(
    *,
    memory_type: str,
    content: str,
    source: str,
    repo: str | None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    record = {
        "id": f"mem_{uuid.uuid4().hex[:12]}",
        "type": memory_type,
        "content": _sanitize(content),
        "source": source,
        "repo": repo,
        "created_at": _now_iso(),
        "tags": tags or [],
    }
    with _memory_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def maybe_record_from_agent_run(request: AgentRunRequest, response: AgentRunResponse) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    task = request.task.strip()
    if MEMORY_TRIGGER_RE.search(task):
        records.append(
            add_memory(
                memory_type="user_preference",
                content=task,
                source="chat",
                repo=request.project_path,
                tags=["explicit"],
            )
        )
    if response.response_type == "change_proposal" and response.proposal_relative_path:
        # Store only a compact proposal summary. The actual diff remains in the thread/proposal flow.
        records.append(
            add_memory(
                memory_type="proposal_summary",
                content=f"Proposed change for {response.proposal_relative_path}: {response.response}",
                source="agent_run",
                repo=request.project_path,
                tags=["proposal", "pending-approval"],
            )
        )
    return records


def record_applied_file_write(request: FileWriteRequest) -> dict[str, Any]:
    return add_memory(
        memory_type="accepted_proposal_summary",
        content=f"Applied approved file change to {request.relative_path}.",
        source="apply",
        repo=request.project_path,
        tags=["accepted-proposal", "file-write"],
    )


def list_memory_items(limit: int = 100) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    path = _memory_file()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    items = items[-limit:]
    nodes = [
        {
            "id": item["id"],
            "label": item.get("type", "memory"),
            "repo": item.get("repo"),
        }
        for item in items
    ]
    return {
        "items": list(reversed(items)),
        "graph": {"nodes": nodes, "edges": []},
    }
