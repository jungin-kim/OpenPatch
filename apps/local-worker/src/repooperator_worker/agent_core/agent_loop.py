from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.context_service import ContextService
from repooperator_worker.agent_core.hooks import HookManager
from repooperator_worker.agent_core.state import AgentCoreState
from repooperator_worker.agent_core.tool_orchestrator import ToolOrchestrator
from repooperator_worker.agent_core.tools.registry import ToolRegistry
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse


@dataclass
class AgentLoopDeps:
    context_service: ContextService
    tool_registry: ToolRegistry
    tool_orchestrator: ToolOrchestrator
    hook_manager: HookManager
    load_context: Callable[[AgentCoreState, AgentRunRequest], None]
    classify: Callable[[AgentCoreState, AgentRunRequest], None]
    create_initial_plan: Callable[[AgentCoreState], None]
    emit_plan_update: Callable[[AgentCoreState, AgentRunRequest, str], None]
    should_continue: Callable[..., bool]
    check_cancel: Callable[[AgentCoreState, AgentRunRequest], None]
    consume_steering: Callable[[AgentCoreState, AgentRunRequest], None]
    choose_next_action: Callable[[AgentCoreState, AgentRunRequest], AgentAction]
    execute_action: Callable[[AgentAction], ActionResult]
    append_action_event: Callable[[AgentAction, ActionResult], None]
    observe_result: Callable[[AgentCoreState, AgentAction, ActionResult, AgentRunRequest], None]
    update_plan: Callable[[AgentCoreState, AgentAction, ActionResult, AgentRunRequest], None]
    build_final_answer: Callable[[AgentCoreState, AgentRunRequest], str]
    validate_final_answer: Callable[[str, AgentCoreState, AgentRunRequest], str]
    build_final_response: Callable[[AgentCoreState, AgentRunRequest], AgentRunResponse]


class AgentLoop:
    def __init__(self, deps: AgentLoopDeps, *, max_wall_clock_seconds: int = 300) -> None:
        self.deps = deps
        self.max_wall_clock_seconds = max_wall_clock_seconds

    def run(self, state: AgentCoreState, request: AgentRunRequest) -> AgentRunResponse:
        started = time.perf_counter()
        self.deps.load_context(state, request)
        self.deps.classify(state, request)
        self.deps.create_initial_plan(state)
        self.deps.emit_plan_update(state, request, "Created initial plan")

        while self.deps.should_continue(state, started=started, max_wall_clock_seconds=self.max_wall_clock_seconds):
            self.deps.check_cancel(state, request)
            if state.cancellation_requested:
                break
            self.deps.consume_steering(state, request)
            action = self.deps.choose_next_action(state, request)
            state.current_step = action.reason_summary
            if action.type == "final_answer":
                break
            if action.type == "ask_clarification":
                state.stop_reason = "needs_clarification"
                missing = ", ".join(action.payload.get("missing_files") or [])
                state.final_response = (
                    action.payload.get("question")
                    or state.classifier_result.clarification_question
                    or (f"I could not find {missing}. Please confirm the repo-relative path or choose one of the candidates I found." if missing else "Could you clarify which files or workflow you want me to inspect?")
                )
                break

            state.actions_taken.append(action)
            result = self.deps.execute_action(action)
            state.action_results.append(result)
            self.deps.append_action_event(action, result)
            self.deps.observe_result(state, action, result, request)
            self.deps.update_plan(state, action, result, request)
            self.deps.check_cancel(state, request)
            if state.cancellation_requested:
                break
            if result.status == "waiting_approval":
                state.stop_reason = "waiting_approval"
                break
            if result.status in {"failed", "cancelled", "timed_out"}:
                state.stop_reason = result.status
                break

        if not state.final_response:
            state.final_response = self.deps.build_final_answer(state, request)
        state.final_response = self.deps.validate_final_answer(state.final_response, state, request)
        return self.deps.build_final_response(state, request)
