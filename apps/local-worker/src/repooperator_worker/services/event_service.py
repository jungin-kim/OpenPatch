from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.common import get_repooperator_home_dir


def _runs_dir() -> Path:
    path = get_repooperator_home_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runs_file() -> Path:
    return _runs_dir() / "runs.jsonl"


_RUN_LOCK = RLock()


def _run_dir(run_id: str) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in {"_", "-"})
    path = _runs_dir() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_meta_file(run_id: str) -> Path:
    return _run_dir(run_id) / "meta.json"


def _run_events_file(run_id: str) -> Path:
    return _run_dir(run_id) / "events.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def start_active_run(
    *,
    run_id: str,
    request: AgentRunRequest,
    thread_id: str | None = None,
) -> dict[str, Any]:
    effective_thread_id = thread_id or request.thread_id
    record = {
        "id": run_id,
        "thread_id": effective_thread_id,
        "repo": request.project_path,
        "branch": request.branch,
        "task_summary": summarize_user_message(request.task),
        "status": "running",
        "started_at": _now_iso(),
        "completed_at": None,
        "final_result": None,
        "error": None,
    }
    with _RUN_LOCK:
        try:
            _run_meta_file(run_id).write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    return record


def append_run_event(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    with _RUN_LOCK:
        events = list_run_events(run_id)
        sequence = int(event.get("sequence") or len(events) + 1)
        meta = get_run(run_id) or {}
        record = {
            "run_id": run_id,
            "thread_id": event.get("thread_id") or meta.get("thread_id"),
            "repo": event.get("repo") or meta.get("repo"),
            "branch": event.get("branch") or meta.get("branch"),
            "sequence": sequence,
            "timestamp": event.get("timestamp") or _now_iso(),
            **event,
        }
        try:
            with _run_events_file(run_id).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass
    return record


def complete_active_run(
    *,
    run_id: str,
    status: str,
    final_result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    with _RUN_LOCK:
        meta = get_run(run_id) or {"id": run_id}
        if meta.get("status") in {"cancelled", "cancelling"} and status == "completed":
            status = "cancelled"
        meta.update(
            {
                "status": status,
                "completed_at": _now_iso(),
                "final_result": final_result,
                "error": error,
            }
        )
        try:
            _run_meta_file(run_id).write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    return meta


def request_run_cancellation(run_id: str) -> dict[str, Any]:
    append_run_event(
        run_id,
        {
            "type": "progress_delta",
            "phase": "Finished",
            "label": "Cancellation requested",
            "detail": "RepoOperator will stop this run at the next safe checkpoint.",
            "status": "waiting",
        },
    )
    return complete_active_run(run_id=run_id, status="cancelled", error="Cancelled by user.")


def record_run_steering(run_id: str, content: str) -> dict[str, Any]:
    event = append_run_event(
        run_id,
        {
            "type": "progress_delta",
            "event_type": "steering_received",
            "phase": "Planning",
            "label": "Received steering instruction",
            "detail": summarize_user_message(content, max_len=220),
            "status": "completed",
        },
    )
    meta = get_run(run_id) or {"id": run_id}
    steering = list(meta.get("steering_instructions") or [])
    steering.append(
        {
            "content": summarize_user_message(content, max_len=500),
            "created_at": _now_iso(),
            "accepted": True,
            "reason": "Recorded for the active run. The agent applies steering at safe checkpoints when supported.",
        }
    )
    meta["steering_instructions"] = steering
    try:
        _run_meta_file(run_id).write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return event


def get_run(run_id: str) -> dict[str, Any] | None:
    path = _run_meta_file(run_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def list_run_events(run_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
    path = _run_events_file(run_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if int(event.get("sequence") or 0) > after_sequence:
            events.append(event)
    return events


def get_active_runs(thread_id: str | None = None) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for meta_path in _runs_dir().glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("status") != "running":
            continue
        if thread_id and meta.get("thread_id") != thread_id:
            continue
        active.append(meta)
    return sorted(active, key=lambda item: str(item.get("started_at") or ""), reverse=True)


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
    try:
        with _runs_file().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
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
    try:
        with _runs_file().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
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
