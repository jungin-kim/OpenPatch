from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal


class HookEventType(str, Enum):
    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    PERMISSION_REQUEST = "PermissionRequest"
    STOP = "Stop"


HookDecision = Literal["allow", "deny", "ask", "none"]


@dataclass
class HookResult:
    continue_: bool = True
    decision: HookDecision = "none"
    updated_input: dict[str, Any] | None = None
    additional_context: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class HookEvent:
    event_type: HookEventType
    tool_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result: Any | None = None
    run_id: str | None = None
    request: Any | None = None


HookCallable = Callable[[HookEvent], HookResult | None]


class HookManager:
    """Small hook seam used by the runtime; no user hook loading is wired yet."""

    def __init__(self) -> None:
        self._pre_tool_hooks: list[HookCallable] = []
        self._post_tool_hooks: list[HookCallable] = []
        self._post_failure_hooks: list[HookCallable] = []
        self._permission_hooks: list[HookCallable] = []

    def register_pre_tool_hook(self, hook: HookCallable) -> None:
        self._pre_tool_hooks.append(hook)

    def register_post_tool_hook(self, hook: HookCallable) -> None:
        self._post_tool_hooks.append(hook)

    def register_post_tool_failure_hook(self, hook: HookCallable) -> None:
        self._post_failure_hooks.append(hook)

    def register_permission_hook(self, hook: HookCallable) -> None:
        self._permission_hooks.append(hook)

    def run_pre_tool(self, *, tool_name: str, payload: dict[str, Any], run_id: str, request: Any) -> HookResult:
        return self._run(
            self._pre_tool_hooks,
            HookEvent(HookEventType.PRE_TOOL_USE, tool_name=tool_name, payload=payload, run_id=run_id, request=request),
        )

    def run_post_tool(self, *, tool_name: str, payload: dict[str, Any], result: Any, run_id: str, request: Any) -> HookResult:
        return self._run(
            self._post_tool_hooks,
            HookEvent(HookEventType.POST_TOOL_USE, tool_name=tool_name, payload=payload, result=result, run_id=run_id, request=request),
        )

    def run_post_tool_failure(self, *, tool_name: str, payload: dict[str, Any], result: Any, run_id: str, request: Any) -> HookResult:
        return self._run(
            self._post_failure_hooks,
            HookEvent(HookEventType.POST_TOOL_USE_FAILURE, tool_name=tool_name, payload=payload, result=result, run_id=run_id, request=request),
        )

    def run_permission_request(self, *, tool_name: str, payload: dict[str, Any], run_id: str, request: Any) -> HookResult:
        return self._run(
            self._permission_hooks,
            HookEvent(HookEventType.PERMISSION_REQUEST, tool_name=tool_name, payload=payload, run_id=run_id, request=request),
        )

    def _run(self, hooks: list[HookCallable], event: HookEvent) -> HookResult:
        merged = HookResult()
        for hook in hooks:
            result = hook(event) or HookResult()
            if result.updated_input is not None:
                merged.updated_input = {**(merged.updated_input or event.payload), **result.updated_input}
                event = HookEvent(
                    event.event_type,
                    tool_name=event.tool_name,
                    payload=merged.updated_input,
                    result=event.result,
                    run_id=event.run_id,
                    request=event.request,
                )
            if result.additional_context:
                merged.additional_context = "\n".join(
                    item for item in [merged.additional_context, result.additional_context] if item
                )
            if result.decision != "none":
                merged.decision = result.decision
            if result.reason:
                merged.reason = result.reason
            if not result.continue_ or result.decision == "deny":
                merged.continue_ = False
                return merged
        return merged
