from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal


class PermissionMode(str, Enum):
    PLAN = "plan"
    DEFAULT = "default"
    AUTO = "auto"
    BYPASS = "bypass"


PermissionDecisionValue = Literal["allow", "deny", "ask"]


class PermissionRuleSource(str, Enum):
    SYSTEM = "system"
    PROJECT = "project"
    USER = "user"
    SESSION = "session"
    TOOL_DEFAULT = "tool_default"


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


@dataclass(frozen=True)
class PermissionRule:
    id: str
    source: PermissionRuleSource
    tool_name: str
    decision: PermissionDecisionValue
    reason: str
    priority: int
    pattern: str | None = None
    predicate_name: str | None = None
    predicate: Callable[[dict[str, Any], ToolPermissionContext], bool] | None = None

    def matches(self, tool_name: str, payload: dict[str, Any], context: ToolPermissionContext) -> bool:
        if self.tool_name not in {"*", tool_name}:
            return False
        if self.predicate:
            return bool(self.predicate(payload, context))
        if self.pattern:
            return self.pattern in str(payload)
        return True

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source.value,
            "tool_name": self.tool_name,
            "decision": self.decision,
            "reason": self.reason,
            "priority": self.priority,
            "pattern": self.pattern,
            "predicate_name": self.predicate_name,
        }


@dataclass(frozen=True)
class PermissionAuditRecord:
    run_id: str
    tool_name: str
    decision: PermissionDecisionValue
    matched_rules: list[dict[str, Any]]
    command_preview: dict[str, Any] | None = None
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    reason: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tool_name": self.tool_name,
            "decision": self.decision,
            "matched_rules": self.matched_rules,
            "command_preview": self.command_preview,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


class PermissionPolicy:
    SOURCE_WEIGHT = {
        PermissionRuleSource.SYSTEM: 10_000,
        PermissionRuleSource.PROJECT: 7_500,
        PermissionRuleSource.USER: 5_000,
        PermissionRuleSource.SESSION: 2_500,
        PermissionRuleSource.TOOL_DEFAULT: 0,
    }
    DECISION_WEIGHT = {"deny": 3, "ask": 2, "allow": 1}

    def __init__(self, rules: list[PermissionRule] | None = None) -> None:
        self.rules = list(rules or [])

    def evaluate(
        self,
        *,
        tool_name: str,
        payload: dict[str, Any],
        context: ToolPermissionContext,
        base_decision: PermissionDecision,
    ) -> tuple[PermissionDecision, PermissionAuditRecord]:
        base_rule = PermissionRule(
            id=f"tool_default:{tool_name}",
            source=PermissionRuleSource.TOOL_DEFAULT,
            tool_name=tool_name,
            decision=base_decision.decision,
            reason=base_decision.reason or "Tool default decision.",
            priority=0,
        )
        matched = [rule for rule in self.rules if rule.matches(tool_name, payload, context)]
        matched.append(base_rule)
        selected = sorted(
            matched,
            key=lambda rule: (
                self.SOURCE_WEIGHT.get(rule.source, 0),
                rule.priority,
                self.DECISION_WEIGHT.get(rule.decision, 0),
            ),
            reverse=True,
        )[0]
        decision = PermissionDecision(
            decision=selected.decision,
            reason=selected.reason,
            approval_id=base_decision.approval_id,
            metadata={**base_decision.metadata, "matched_permission_rule": selected.model_dump()},
        )
        audit = PermissionAuditRecord(
            run_id=context.run_id,
            tool_name=tool_name,
            decision=decision.decision,
            matched_rules=[rule.model_dump() for rule in matched],
            command_preview=base_decision.metadata.get("command_preview"),
            reason=decision.reason,
        )
        return decision, audit


def permission_mode_from_value(value: str | PermissionMode | None) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    normalized = str(value or PermissionMode.DEFAULT.value).strip().lower()
    for mode in PermissionMode:
        if normalized == mode.value:
            return mode
    return PermissionMode.DEFAULT
