from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.event_service import append_run_event


TERMINAL_ACTIVITY_STATUSES = {"completed", "failed", "cancelled", "timed_out", "waiting"}


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def activity_event(
    *,
    run_id: str,
    request: AgentRunRequest,
    activity_id: str,
    event_type: str,
    phase: str,
    label: str,
    status: str = "running",
    current_action: str | None = None,
    observation: str | None = None,
    next_action: str | None = None,
    detail: str = "",
    detail_delta: str | None = None,
    observation_delta: str | None = None,
    next_action_delta: str | None = None,
    safe_reasoning_summary_delta: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: int | None = None,
    related_files: list[str] | None = None,
    related_command: list[str] | str | None = None,
    aggregate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    event = {
        "id": f"{run_id}-event-{uuid.uuid4().hex[:10]}",
        "type": "progress_delta",
        "event_type": event_type,
        "activity_id": activity_id,
        "run_id": run_id,
        "thread_id": request.thread_id,
        "repo": request.project_path,
        "branch": request.branch,
        "phase": phase,
        "label": label,
        "status": status,
        "current_action": current_action,
        "observation": observation,
        "next_action": next_action,
        "detail": detail,
        "detail_delta": detail_delta,
        "observation_delta": observation_delta,
        "next_action_delta": next_action_delta,
        "safe_reasoning_summary_delta": safe_reasoning_summary_delta,
        "started_at": started_at or now,
        "updated_at": now,
        "ended_at": ended_at or (now if status in TERMINAL_ACTIVITY_STATUSES else None),
        "duration_ms": duration_ms,
        "related_files": related_files or [],
        "files": related_files or [],
        "related_command": related_command,
        "aggregate": aggregate,
    }
    return {key: value for key, value in event.items() if value is not None}


def append_activity_event(**kwargs: Any) -> dict[str, Any]:
    event = activity_event(**kwargs)
    try:
        return append_run_event(str(kwargs["run_id"]), event)
    except OSError:
        return event
    except PermissionError:
        return event


def merge_activity_states(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        activity_id = str(event.get("activity_id") or event.get("id") or "")
        if not activity_id:
            continue
        if activity_id not in states:
            states[activity_id] = dict(event)
            order.append(activity_id)
        else:
            merged = states[activity_id]
            for key, value in event.items():
                if value not in (None, "", [], {}):
                    if key.endswith("_delta") and merged.get(key):
                        merged[key] = str(merged[key]) + str(value)
                    else:
                        merged[key] = value
            states[activity_id] = merged
    return [states[item] for item in order]


def duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds() * 1000))
