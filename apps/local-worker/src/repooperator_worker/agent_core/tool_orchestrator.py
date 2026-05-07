from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.hooks import HookManager
from repooperator_worker.agent_core.permissions import PermissionMode, ToolPermissionContext, permission_mode_from_value
from repooperator_worker.agent_core.tools.base import (
    ToolExecutionContext,
    ToolResult,
    agent_action_to_tool_payload,
    tool_result_to_action_result,
)
from repooperator_worker.agent_core.tools.registry import ToolRegistry, get_default_tool_registry
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.event_service import get_run
from repooperator_worker.services.json_safe import json_safe, safe_repr


class ToolOrchestrator:
    def __init__(
        self,
        *,
        run_id: str,
        request: AgentRunRequest,
        registry: ToolRegistry | None = None,
        hook_manager: HookManager | None = None,
        permission_mode: PermissionMode | str | None = None,
    ) -> None:
        self.run_id = run_id
        self.request = request
        self.registry = registry or get_default_tool_registry()
        self.hook_manager = hook_manager or HookManager()
        self.permission_mode = permission_mode_from_value(permission_mode)
        self.prior_denials: list[dict[str, Any]] = []

    def execute_action(self, action: AgentAction) -> ActionResult:
        started = time.perf_counter()
        try:
            result = self.execute_tool(action.type, agent_action_to_tool_payload(action))
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(
                tool_name=action.type,
                status="failed",
                observation="Action failed.",
                payload={"errors": [safe_repr(exc, limit=500)]},
            )
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        action_result = tool_result_to_action_result(action, result)
        if "errors" in result.payload and action_result.status == "failed":
            action_result.errors = [str(item) for item in result.payload.get("errors") or []]
        return action_result

    def execute_tool(self, tool_name: str, payload: dict[str, Any]) -> ToolResult:
        tool = self.registry.get(tool_name)
        validated = json_safe(tool.validate_input(dict(payload), self.request))
        if self._is_cancelled():
            return ToolResult(tool_name=tool_name, status="cancelled", observation="Run was cancelled before tool execution.")

        pre_hook = self.hook_manager.run_pre_tool(tool_name=tool_name, payload=validated, run_id=self.run_id, request=self.request)
        if pre_hook.updated_input is not None:
            validated = json_safe(pre_hook.updated_input)
        if not pre_hook.continue_ or pre_hook.decision == "deny":
            return ToolResult(
                tool_name=tool_name,
                status="skipped",
                observation=pre_hook.reason or "Tool blocked by pre-tool hook.",
                payload={"hook_decision": pre_hook.decision, "hook_reason": pre_hook.reason},
            )

        permission_context = ToolPermissionContext(
            request=self.request,
            run_id=self.run_id,
            permission_mode=self.permission_mode,
            active_repository=self._active_repository_path(),
            prior_denials=list(self.prior_denials),
            reason=str(validated.get("reason_summary") or ""),
        )
        decision = tool.check_permission(validated, permission_context)
        if decision.decision == "ask":
            self.hook_manager.run_permission_request(tool_name=tool_name, payload=validated, run_id=self.run_id, request=self.request)
            metadata = json_safe(decision.metadata)
            return ToolResult(
                tool_name=tool_name,
                status="waiting_approval",
                observation=decision.reason or "Tool requires approval.",
                command_result=metadata.get("command_preview") if isinstance(metadata, dict) else None,
                payload={"permission_decision": json_safe(decision)},
                next_recommended_action="request_approval",
            )
        if decision.decision == "deny":
            self.prior_denials.append({"tool": tool_name, "reason": decision.reason, "metadata": json_safe(decision.metadata)})
            return ToolResult(
                tool_name=tool_name,
                status="failed",
                observation=decision.reason or "Tool denied by permission policy.",
                payload={"permission_decision": json_safe(decision)},
            )

        context = ToolExecutionContext(
            request=self.request,
            run_id=self.run_id,
            permission_mode=self.permission_mode,
            active_repository=permission_context.active_repository,
        )
        try:
            result = tool.call(validated, context)
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(tool_name=tool_name, status="failed", observation="Tool execution failed.", payload={"errors": [safe_repr(exc, limit=500)]})
            self.hook_manager.run_post_tool_failure(tool_name=tool_name, payload=validated, result=result, run_id=self.run_id, request=self.request)
            return result

        result = self._cap_result(result, max_chars=tool.spec.max_result_chars)
        post_hook = self.hook_manager.run_post_tool(tool_name=tool_name, payload=validated, result=result, run_id=self.run_id, request=self.request)
        if not post_hook.continue_ or post_hook.decision == "deny":
            return ToolResult(
                tool_name=tool_name,
                status="skipped",
                observation=post_hook.reason or "Tool result blocked by post-tool hook.",
                payload={"hook_decision": post_hook.decision, "hook_reason": post_hook.reason, "original_result": result.model_dump()},
            )
        return result

    def _is_cancelled(self) -> bool:
        try:
            run = get_run(self.run_id) or {}
        except OSError:
            run = {}
        return run.get("status") in {"cancelled", "cancelling"}

    def _active_repository_path(self) -> str | None:
        try:
            active = get_active_repository()
        except Exception:
            active = None
        return str(active.project_path) if active else None

    def _cap_result(self, result: ToolResult, *, max_chars: int) -> ToolResult:
        updated = result
        payload = json_safe(result.payload)
        metadata: dict[str, Any] = {}
        if len(result.observation or "") > max_chars:
            updated = replace(updated, observation=(result.observation or "")[:max_chars] + "\n[truncated]")
            metadata["observation_truncated"] = True
        try:
            payload_chars = len(json.dumps(payload, ensure_ascii=False))
        except TypeError:
            payload = json_safe(payload)
            payload_chars = len(json.dumps(payload, ensure_ascii=False))
        if payload_chars > max_chars:
            payload = _truncate_payload(payload, max_chars=max_chars)
            metadata.update(
                {
                    "payload_truncated": True,
                    "original_payload_chars": payload_chars,
                    "artifact_store": "not_configured",
                }
            )
        if metadata:
            payload = {**payload, "_artifact": metadata}
            updated = replace(updated, payload=payload)
        return updated


def _truncate_payload(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "\n[truncated]"
    if isinstance(value, list):
        result = []
        remaining = max_chars
        for item in value:
            if remaining <= 0:
                result.append("[truncated]")
                break
            truncated = _truncate_payload(item, max_chars=_child_limit(remaining, max_chars))
            result.append(truncated)
            remaining -= len(safe_repr(truncated, limit=max_chars))
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        remaining = max_chars
        for key, item in value.items():
            if remaining <= 0:
                result[str(key)] = "[truncated]"
                break
            truncated = _truncate_payload(item, max_chars=_child_limit(remaining, max_chars))
            result[str(key)] = truncated
            remaining -= len(str(key)) + len(safe_repr(truncated, limit=max_chars))
        return result
    return json_safe(value)


def _child_limit(remaining: int, max_chars: int) -> int:
    return max(32, min(max_chars, max(1, remaining // 2)))
