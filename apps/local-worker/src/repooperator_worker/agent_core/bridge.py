from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from repooperator_worker.services.json_safe import json_safe


class BridgeStatus(str, Enum):
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    ARCHIVED = "archived"


@dataclass
class BridgeSession:
    session_id: str
    environment_id: str
    status: BridgeStatus = BridgeStatus.IDLE
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


@dataclass
class BridgeWorkItem:
    work_id: str
    session_id: str
    task: str
    project_path: str
    branch: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


class BridgeAdapter(Protocol):
    def register_environment(self, environment: dict[str, Any]) -> BridgeSession:
        ...

    def poll_work(self, session_id: str) -> list[BridgeWorkItem]:
        ...

    def ack_work(self, work_id: str) -> None:
        ...

    def send_result(self, work_id: str, result: dict[str, Any]) -> None:
        ...

    def heartbeat(self, session_id: str) -> BridgeStatus:
        ...

    def archive_session(self, session_id: str) -> None:
        ...


class NoOpBridgeAdapter:
    """No-network bridge seam. AgentRunCoordinator can later run BridgeWorkItem payloads."""

    def register_environment(self, environment: dict[str, Any]) -> BridgeSession:
        return BridgeSession(session_id="noop", environment_id=str(environment.get("id") or "local"), status=BridgeStatus.DISCONNECTED)

    def poll_work(self, session_id: str) -> list[BridgeWorkItem]:
        return []

    def ack_work(self, work_id: str) -> None:
        return None

    def send_result(self, work_id: str, result: dict[str, Any]) -> None:
        return None

    def heartbeat(self, session_id: str) -> BridgeStatus:
        return BridgeStatus.DISCONNECTED

    def archive_session(self, session_id: str) -> None:
        return None
