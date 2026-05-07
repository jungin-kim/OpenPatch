from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class PermissionMode(str, Enum):
    PLAN = "plan"
    DEFAULT = "default"
    AUTO = "auto"
    BYPASS = "bypass"


PermissionDecisionValue = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class PermissionDecision:
    decision: PermissionDecisionValue
    reason: str = ""
    approval_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, reason: str = "", **metadata: Any) -> "PermissionDecision":
        return cls(decision="allow", reason=reason, metadata=metadata)

    @classmethod
    def deny(cls, reason: str = "", **metadata: Any) -> "PermissionDecision":
        return cls(decision="deny", reason=reason, metadata=metadata)

    @classmethod
    def ask(cls, reason: str = "", *, approval_id: str | None = None, **metadata: Any) -> "PermissionDecision":
        return cls(decision="ask", reason=reason, approval_id=approval_id, metadata=metadata)


@dataclass(frozen=True)
class ToolPermissionContext:
    request: Any
    run_id: str
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    active_repository: str | None = None
    prior_denials: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None


def permission_mode_from_value(value: str | PermissionMode | None) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    normalized = str(value or PermissionMode.DEFAULT.value).strip().lower()
    for mode in PermissionMode:
        if normalized == mode.value:
            return mode
    return PermissionMode.DEFAULT
