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
    try:
        with _memory_file().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return record
    from repooperator_worker.services.event_service import record_event

    record_event(
        event_type="memory_write",
        repo=repo,
        summary=f"Stored {memory_type} memory",
    )
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
    graph = _build_memory_graph(items)
    return {
        "items": list(reversed(items)),
        "graph": graph,
    }


def _build_memory_graph(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    from repooperator_worker.services.event_service import list_recent_runs
    from repooperator_worker.services.skills_service import discover_skills
    from repooperator_worker.services.thread_service import list_threads

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(node_id: str, label: str, node_type: str) -> None:
        nodes.setdefault(node_id, {"id": node_id, "label": label, "type": node_type})

    def add_edge(source: str, target: str, label: str) -> None:
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "label": label})

    for item in items:
        mem_id = f"memory:{item['id']}"
        add_node(mem_id, item.get("type", "memory"), "memory")
        repo = item.get("repo")
        if repo:
            repo_id = f"repo:{repo}"
            add_node(repo_id, Path(repo).name or repo, "repository")
            add_edge(mem_id, repo_id, "belongs to")

    try:
        threads = list_threads().threads
    except Exception:
        threads = []
    for thread in threads[:50]:
        thread_id = f"thread:{thread.id}"
        add_node(thread_id, thread.title, "thread")
        repo_id = f"repo:{thread.repo.local_repo_path or thread.repo.project_path}"
        add_node(repo_id, Path(thread.repo.local_repo_path or thread.repo.project_path).name, "repository")
        add_edge(thread_id, repo_id, "uses repo")
        for message in thread.messages[-20:]:
            metadata = message.metadata or {}
            for file_path in metadata.get("files_read") or metadata.get("thread_context_files") or []:
                file_id = f"file:{repo_id}:{file_path}"
                add_node(file_id, str(file_path), "file")
                add_edge(thread_id, file_id, "read")
            for symbol in metadata.get("thread_context_symbols") or []:
                symbol_id = f"symbol:{repo_id}:{symbol}"
                add_node(symbol_id, str(symbol), "symbol")
                add_edge(thread_id, symbol_id, "mentions")

    for run in list_recent_runs(80):
        run_id = f"run:{run.get('id')}"
        add_node(run_id, str(run.get("id")), "run")
        repo = run.get("repo")
        if repo:
            repo_id = f"repo:{repo}"
            add_node(repo_id, Path(str(repo)).name or str(repo), "repository")
            add_edge(run_id, repo_id, "ran in")
        for file_path in (run.get("files_read") or []) + (run.get("thread_context_files") or []):
            file_id = f"file:{repo}:{file_path}"
            add_node(file_id, str(file_path), "file")
            add_edge(run_id, file_id, "used")
        for symbol in run.get("thread_context_symbols") or []:
            symbol_id = f"symbol:{repo}:{symbol}"
            add_node(symbol_id, str(symbol), "symbol")
            add_edge(run_id, symbol_id, "saw")
        if run.get("proposal_id"):
            proposal_id = f"proposal:{run.get('proposal_id')}"
            add_node(proposal_id, str(run.get("proposal_id")), "proposal")
            add_edge(run_id, proposal_id, "created")

    for skill in discover_skills().get("skills", []):
        skill_id = f"skill:{skill.get('source_path')}:{skill.get('name')}"
        add_node(skill_id, str(skill.get("name")), "skill")
        for run in list(nodes.values()):
            if run.get("type") == "run":
                add_edge(skill_id, run["id"], "available to")

    return {"nodes": list(nodes.values()), "edges": edges}
