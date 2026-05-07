from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from repooperator_worker.services.json_safe import json_safe


class TaskType(str, Enum):
    LOCAL_BASH = "local_bash"
    LOCAL_AGENT = "local_agent"
    REMOTE_AGENT = "remote_agent"
    WORKFLOW = "workflow"
    LOCAL_AGENT_REVIEW = "local_agent_review"
    LONG_REPOSITORY_SCAN = "long_repository_scan"
    COMMAND_MONITOR_PREVIEW_ONLY = "command_monitor_preview_only"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    KILLED = "killed"


@dataclass
class TaskOutputRef:
    ref_id: str
    kind: str
    uri: str
    preview: str = ""

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


ALLOWED_PLACEHOLDER_TASK_TYPES = {
    TaskType.LOCAL_AGENT_REVIEW,
    TaskType.LONG_REPOSITORY_SCAN,
    TaskType.COMMAND_MONITOR_PREVIEW_ONLY,
}


@dataclass
class AgentTask:
    task_id: str
    task_type: TaskType
    status: TaskStatus
    title: str
    created_at: str
    updated_at: str
    run_id: str | None = None
    owner_run_id: str | None = None
    output_ref: TaskOutputRef | str | None = None
    progress_summary: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


class TaskManager(Protocol):
    def create_task(self, task_type: TaskType, title: str, *, run_id: str | None = None, **metadata: Any) -> AgentTask:
        ...

    def update_task(self, task_id: str, *, status: TaskStatus | None = None, progress_summary: str | None = None, output_ref: TaskOutputRef | str | None = None, error: str | None = None) -> AgentTask:
        ...

    def get_task(self, task_id: str) -> AgentTask | None:
        ...

    def list_tasks(self) -> list[AgentTask]:
        ...

    def cancel_task(self, task_id: str) -> AgentTask:
        ...


class InMemoryTaskManager:
    """Task seam only. No background shell execution or autonomous daemon trigger is implemented."""

    def __init__(self) -> None:
        self._tasks: dict[str, AgentTask] = {}

    def create_task(self, task_type: TaskType, title: str, *, run_id: str | None = None, **metadata: Any) -> AgentTask:
        if task_type not in ALLOWED_PLACEHOLDER_TASK_TYPES:
            raise ValueError("Only placeholder task types are allowed; background execution is not enabled.")
        now = _now_iso()
        task = AgentTask(
            task_id=f"task_{uuid.uuid4().hex[:12]}",
            task_type=task_type,
            status=TaskStatus.PENDING,
            title=title,
            created_at=now,
            updated_at=now,
            run_id=run_id,
            owner_run_id=run_id,
            metadata=json_safe(metadata),
        )
        self._tasks[task.task_id] = task
        return task

    def update_task(self, task_id: str, *, status: TaskStatus | None = None, progress_summary: str | None = None, output_ref: TaskOutputRef | str | None = None, error: str | None = None) -> AgentTask:
        task = self._require(task_id)
        if status is not None:
            task.status = status
        if progress_summary is not None:
            task.progress_summary = progress_summary
        if output_ref is not None:
            task.output_ref = output_ref
        if error is not None:
            task.error = error
        task.updated_at = _now_iso()
        return task

    def get_task(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[AgentTask]:
        return list(self._tasks.values())

    def cancel_task(self, task_id: str) -> AgentTask:
        task = self._require(task_id)
        if task.status == TaskStatus.CANCELLED:
            return task
        return self.update_task(task_id, status=TaskStatus.CANCELLED, progress_summary="Cancellation requested.")

    def _require(self, task_id: str) -> AgentTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        return task


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
