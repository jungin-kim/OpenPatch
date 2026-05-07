from __future__ import annotations

import json
import re
import shlex
import time
from pathlib import Path
from typing import Any, Iterator

from repooperator_worker.agent_core.action_executor import is_supported_text_file
from repooperator_worker.agent_core.agent_loop import AgentLoop, AgentLoopDeps
from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.context_service import get_default_context_service
from repooperator_worker.agent_core.events import append_activity_event
from repooperator_worker.agent_core.final_synthesis import (
    _answer_with_model,
    collect_file_contents,
    synthesize_answer_from_evidence,
    validate_or_repair_final_answer,
)
from repooperator_worker.agent_core.final_response import build_agent_response
from repooperator_worker.agent_core.hooks import HookManager
from repooperator_worker.agent_core.planner import NEXT_ACTION_PROMPT, PLANNER_ACTION_TYPES, TaskFrame
from repooperator_worker.agent_core.state import AgentCoreState, ClassifierResult
from repooperator_worker.agent_core.steering import (
    STEERING_PROMPT,
    SUPPORTED_STEERING_TYPES,
    SteeringDecision,
    _validate_steering_payload,
    consume_steering_for_state,
    parse_steering_instruction,
)
from repooperator_worker.agent_core.tool_orchestrator import ToolOrchestrator
from repooperator_worker.agent_core.tools.registry import get_default_tool_registry
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.model_client import ModelGenerationRequest, OpenAICompatibleModelClient
from repooperator_worker.services.common import ensure_relative_to_repo, resolve_project_path
from repooperator_worker.services.event_service import append_run_event, get_run, list_run_events
from repooperator_worker.services.json_safe import json_safe, safe_agent_response_payload, safe_repr
from repooperator_worker.services.skills_service import enabled_skill_context
from repooperator_worker.services.active_repository import get_active_repository

CLASSIFIER_PROMPT = """\
You are RepoOperator's intent classifier. Return JSON only.
Schema:
{
  "intent": "read_only_question|repo_analysis|recommend_change_targets|review_recommendation|write_request|write_confirmation|file_clarification_answer|local_command_request|git_workflow_request|gitlab_mr_request|multi_step_request|pasted_prompt_or_spec|apply_spec_to_repo|ambiguous",
  "confidence": 0.0,
  "analysis_scope": "single_file|selected_files|repository_wide|unknown",
  "requested_workflow": "repository_review|file_review|code_change|git_workflow|command|other",
  "retrieval_goal": "answer|review|edit|git|command",
  "target_files": [],
  "target_symbols": [],
  "file_types_requested": [],
  "requested_action": "short structured action label",
  "git_action": null,
  "needs_tool": null,
  "needs_clarification": false,
  "clarification_question": null,
  "requires_repository_wide_review": false
}
Do not route by matching user-language phrases. Extract structured intent.
"""

FILE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_./\\-])([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,8})(?![A-Za-z0-9_./\\-])")
SOURCE_SUFFIXES = {".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift", ".go", ".rs", ".rb", ".php", ".c", ".cpp", ".h", ".hpp"}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {".md", ".txt", ".rst", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".gradle"}
SEARCH_SKIP_DIRS = {".git", ".claude", "node_modules", "runtime", ".next", "dist", "build", "out", "coverage", ".venv", "venv", "__pycache__"}
EDIT_DISCOVERY_TEXT_SIGNALS = ["Save", "Load", "BinaryFormatter", "JsonUtility", "persistentDataPath", "PlayerData"]
SUPPORTED_INTENTS = {
    "read_only_question", "repo_analysis", "recommend_change_targets", "review_recommendation",
    "write_request", "write_confirmation", "file_clarification_answer", "local_command_request",
    "git_workflow_request", "gitlab_mr_request", "multi_step_request", "pasted_prompt_or_spec",
    "apply_spec_to_repo", "ambiguous",
}
def run_controller_graph(
    request: AgentRunRequest,
    *,
    run_id: str | None = None,
    stream_final_answer: bool = False,
) -> AgentRunResponse:
    run_id = run_id or "run_controller"
    _validate_active_repository(request)
    state = _initial_state(request, run_id)
    skills_context, skills_used = enabled_skill_context()
    state.skills_used = skills_used
    registry = get_default_tool_registry()
    hook_manager = HookManager()
    context_service = get_default_context_service()
    orchestrator = ToolOrchestrator(run_id=run_id, request=request, registry=registry, hook_manager=hook_manager)

    def append_action_event(action: AgentAction, result: ActionResult) -> None:
        _append_run_event_safe(
            run_id,
            {
                "type": "action_result",
                "event_type": "action_result",
                "status": result.status,
                "action": action.model_dump(),
                "result": result.model_dump(),
            },
        )

    def synthesize(state_for_answer: AgentCoreState, request_for_answer: AgentRunRequest) -> str:
        on_delta = _stream_final_delta(run_id) if stream_final_answer else None
        packet_context = ""
        if isinstance(state_for_answer.context_packet, dict):
            packet_context = str(state_for_answer.context_packet.get("skills_context") or "")
        return build_final_answer_text(
            state_for_answer,
            request_for_answer,
            skills_context=packet_context or skills_context,
            on_delta=on_delta,
        )

    loop = AgentLoop(
        AgentLoopDeps(
            context_service=context_service,
            tool_registry=registry,
            tool_orchestrator=orchestrator,
            hook_manager=hook_manager,
            load_context=load_context,
            classify=classify,
            create_initial_plan=create_initial_plan,
            emit_plan_update=emit_plan_update,
            should_continue=should_continue,
            check_cancel=check_cancel,
            consume_steering=consume_steering_for_state,
            choose_next_action=controller_choose_next_action,
            execute_action=orchestrator.execute_action,
            append_action_event=append_action_event,
            observe_result=observe_result,
            update_plan=update_plan,
            build_final_answer=synthesize,
            validate_final_answer=validate_or_repair_final_answer,
            build_final_response=build_final_response,
        )
    )
    return loop.run(state, request)


def load_context(state: AgentCoreState, request: AgentRunRequest) -> None:
    packet = get_default_context_service().collect(request)
    state.context_packet = packet.model_dump()
    high_signal = sorted(packet.high_signal_files)
    instructions = sorted(packet.project_instructions)
    state.observations.append("Loaded request context for the active repository.")
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="controller-load-context",
        event_type="activity_completed",
        phase="Thinking",
        label="Loaded context",
        status="completed",
        observation="Loaded request, repository, branch, thread, and skill context.",
        aggregate={
            "repo_root_name": packet.repo_root_name,
            "branch": packet.branch,
            "high_signal_files": high_signal,
            "project_instruction_files": instructions,
            "prior_files_read": packet.prior_files_read,
            "prior_commands_run": packet.prior_commands_run,
            "git_status_available": bool(packet.git_status_summary),
            "recent_commits_available": bool(packet.recent_commits_summary),
        },
    )


def classify(state: AgentCoreState, request: AgentRunRequest) -> None:
    state.classifier_result = classify_intent(request)
    frame = build_task_frame(request, state)
    state.recommendation_context = json_safe({"task_frame": frame, "context_packet": state.context_packet})
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="controller-frame-request",
        event_type="activity_completed",
        phase="Thinking",
        label="Framed request",
        status="completed",
        observation=f"Goal framed with {len(frame.mentioned_files)} mentioned file(s) and {len(frame.likely_capabilities)} likely capability hint(s).",
        aggregate={"task_frame": json_safe(frame)},
    )


def create_initial_plan(state: AgentCoreState) -> None:
    state.plan = [
        "Frame the user's goal",
        "Resolve missing evidence",
        "Use safe primitive actions",
        "Answer only from gathered evidence or ask a precise clarification",
    ]


def should_continue(state: AgentCoreState, *, started: float, max_wall_clock_seconds: int) -> bool:
    if state.stop_reason or state.cancellation_requested:
        return False
    if state.loop_iteration >= state.max_loop_iterations:
        state.stop_reason = "max_loop_iterations"
        return False
    if len(state.files_read) >= state.max_file_reads:
        state.stop_reason = "max_file_reads"
        return False
    if len(state.commands_run) >= state.max_commands:
        state.stop_reason = "max_commands"
        return False
    if time.perf_counter() - started > max_wall_clock_seconds:
        state.stop_reason = "timed_out"
        return False
    state.loop_iteration += 1
    return True


def check_cancel(state: AgentCoreState, request: AgentRunRequest) -> None:
    try:
        run = get_run(state.run_id) or {}
    except OSError:
        run = {}
    if run.get("status") not in {"cancelled", "cancelling"}:
        return
    state.cancellation_requested = True
    state.stop_reason = "cancelled"
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="controller-cancelled",
        event_type="activity_completed",
        phase="Finished",
        label="Run cancelled",
        status="cancelled",
        observation="Cancellation was requested. RepoOperator stopped at the next safe checkpoint.",
    )


def controller_choose_next_action(state: AgentCoreState, request: AgentRunRequest) -> AgentAction:
    frame = build_task_frame(request, state)
    state.recommendation_context = json_safe({"task_frame": frame, "context_packet": state.context_packet})

    resolved = resolve_target_files(request, frame.mentioned_files, preferred=known_context_files(request, state))
    unread = [path for path in resolved if path not in state.files_read]
    if unread:
        emit_target_resolution(state, request, frame.mentioned_files, resolved)
        return AgentAction(
            type="read_file",
            reason_summary="Read resolved target files before answering.",
            target_files=unread,
            expected_output="File contents for grounded answer.",
        )

    unresolved = [item for item in frame.mentioned_files if item and not any(Path(path).name.lower() == Path(item).name.lower() or path.lower() == item.lower() for path in resolved)]
    if unresolved and not _has_search_for(state, unresolved):
        return AgentAction(
            type="search_files",
            reason_summary="Resolve mentioned files before asking for clarification.",
            expected_output="Repo-relative candidate paths.",
            payload={"queries": unresolved},
        )

    explicit_candidates = current_search_candidate_files(state, min_score=35.0)
    explicit_candidate_unread = [
        path for path in explicit_candidates
        if path not in state.files_read and any(Path(path).name.lower() == Path(item).name.lower() for item in unresolved)
    ]
    if explicit_candidate_unread:
        return AgentAction(
            type="read_file",
            reason_summary="Read the resolved high-confidence target file.",
            target_files=explicit_candidate_unread[:1],
            expected_output="File contents for grounded answer.",
        )

    if frame.mentioned_symbols and not state.files_read and not _has_search_for(state, frame.mentioned_symbols):
        return AgentAction(
            type="search_files",
            reason_summary="Resolve mentioned symbols before answering.",
            target_symbols=frame.mentioned_symbols,
            expected_output="Repo-relative candidate paths.",
            payload={"queries": frame.mentioned_symbols},
        )

    if unresolved and _has_search_for(state, unresolved):
        return AgentAction(
            type="ask_clarification",
            reason_summary="Ask a precise file clarification after repository search did not find targets.",
            payload={"missing_files": unresolved},
        )

    planned = propose_next_action_with_model(request, state, frame)
    if planned:
        return planned

    unrun_preview = _latest_unrun_read_only_preview(state)
    if unrun_preview:
        return AgentAction(
            type="run_approved_command",
            reason_summary="Run read-only command after policy preview.",
            command=list(unrun_preview.command_result.get("command") or []),
            expected_output="Command output for the user request.",
        )

    command = command_needed_for_task(frame, state)
    if command:
        if not _has_command_preview(state, command):
            return AgentAction(
                type="inspect_git_state" if command[:1] == ["git"] else "preview_command",
                reason_summary="Preview the safe command needed for missing evidence.",
                command=command,
                expected_output="Command safety classification.",
            )
        preview = _latest_command_preview(state, command)
        if preview and preview.status == "success" and _preview_read_only(preview.command_result) and not _has_command_run(state, command):
            return AgentAction(
                type="run_approved_command",
                reason_summary="Run read-only command after policy preview.",
                command=command,
                expected_output="Command output for the user request.",
            )
        if pending_commit_context(frame) and _has_command_run(state, ["git", "log", "--oneline", "-n", "5"]) and not _has_command_preview(state, ["git", "status", "--short"]):
            return AgentAction(
                type="inspect_git_state",
                reason_summary="Inspect git status before discussing a possible commit.",
                command=["git", "status", "--short"],
                expected_output="Working tree status.",
            )
        return AgentAction(type="final_answer", reason_summary="Answer from command evidence.")

    searched_candidates = candidate_files_from_results(state, edit_related=edit_requested(frame))
    candidate_unread = [path for path in searched_candidates if path not in state.files_read]
    if candidate_unread:
        read_limit = 1 if edit_requested(frame) else 4
        return AgentAction(
            type="read_file",
            reason_summary="Read best candidate files found by repository search.",
            target_files=candidate_unread[:read_limit],
            expected_output="Candidate file contents.",
        )

    if edit_requested(frame):
        edit_targets = current_edit_target_files(state, frame, request)
        if edit_targets:
            if not _has_action(state, "generate_edit"):
                return AgentAction(
                    type="generate_edit",
                    reason_summary="Prepare a proposed patch for validated current edit targets.",
                    target_files=edit_targets,
                    expected_output="Proposed diff and before/after summary.",
                    payload={"task_frame": json_safe(frame), "current_edit_targets": edit_targets},
                )
            return AgentAction(type="final_answer", reason_summary="Report the proposed edit without claiming it was applied.")
        if not _has_action(state, "inspect_repo_tree"):
            return AgentAction(type="inspect_repo_tree", reason_summary="Inspect repository before locating edit targets.")
        edit_queries = likely_edit_file_queries(frame)
        if not _has_search_for(state, edit_queries):
            return AgentAction(
                type="search_files",
                reason_summary="Search repository for likely edit targets.",
                expected_output="Repo-relative candidate paths.",
                payload={"queries": edit_queries, "text_queries": EDIT_DISCOVERY_TEXT_SIGNALS},
            )
        return AgentAction(type="ask_clarification", reason_summary="Ask which file to edit after search did not find a safe target.")

    if not state.files_read and not _has_action(state, "inspect_repo_tree"):
        return AgentAction(type="inspect_repo_tree", reason_summary="Inspect repository inventory before answering.")

    project_files = project_summary_files(request)
    unread_project_files = [path for path in project_files if path not in state.files_read]
    if unread_project_files and len(state.files_read) < 4:
        return AgentAction(
            type="read_file",
            reason_summary="Read high-signal project files for a project-level answer.",
            target_files=unread_project_files[:4],
            expected_output="Project purpose and technology evidence.",
        )

    if not state.files_read and unresolved:
        return AgentAction(
            type="ask_clarification",
            reason_summary="Ask a precise file clarification after repository search did not find targets.",
            payload={"missing_files": unresolved},
        )
    return AgentAction(type="final_answer", reason_summary="Enough evidence is available for a grounded answer.")


def observe_result(state: AgentCoreState, action: AgentAction, result: ActionResult, request: AgentRunRequest) -> None:
    if result.files_read:
        for path in result.files_read:
            if path not in state.files_read:
                state.files_read.append(path)
    if result.files_changed:
        for path in result.files_changed:
            if path not in state.files_changed:
                state.files_changed.append(path)
    if result.command_result and result.command_result.get("display_command"):
        command = str(result.command_result.get("display_command"))
        if result.status == "success" and result.command_result.get("exit_code") is not None:
            state.commands_run.append(command)
    if result.status == "waiting_approval":
        state.pending_approval = result.command_result
    observation = _safe_observation(action, result)
    if observation:
        state.observations.append(observation)
        append_activity_event(
            run_id=state.run_id,
            request=request,
            activity_id=f"controller-observe:{action.action_id}",
            event_type="activity_completed",
            phase="Observing",
            label="Recorded observation",
            status="completed",
            observation=observation,
            related_files=result.files_read,
            related_command=action.command,
        )
    if action.type == "analyze_repository":
        response = result.payload.get("response")
        if isinstance(response, AgentRunResponse):
            state.final_response = response.response
        elif isinstance(response, dict):
            state.final_response = str(response.get("response") or "")


def update_plan(state: AgentCoreState, action: AgentAction, result: ActionResult, request: AgentRunRequest) -> None:
    if result.status == "waiting_approval":
        state.plan.append("Wait for user approval before running the command")
    elif result.next_recommended_action:
        state.plan.append(f"Consider next safe action: {result.next_recommended_action}")
    elif result.status == "success":
        state.plan.append(f"Completed: {action.type}")
    emit_plan_update(state, request, "Updated plan")


def emit_plan_update(state: AgentCoreState, request: AgentRunRequest, label: str) -> None:
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="controller-plan",
        event_type="activity_updated",
        phase="Planning",
        label=label,
        status="running",
        observation="; ".join(state.plan[-4:]),
        aggregate={"plan_steps": list(state.plan), "loop_iteration": state.loop_iteration},
    )


def build_final_answer_text(
    state: AgentCoreState,
    request: AgentRunRequest,
    *,
    skills_context: str = "",
    on_delta: Any | None = None,
) -> str:
    if state.cancellation_requested or state.stop_reason == "cancelled":
        completed = "; ".join(state.observations[-4:]) or "No action completed before cancellation."
        return f"Run cancelled. Completed work before stopping: {completed}"
    if state.pending_approval:
        return _format_command_preview(list(state.pending_approval.get("command") or []), state.pending_approval)
    if state.stop_reason in {"failed", "timed_out", "max_loop_iterations", "max_file_reads", "max_commands"}:
        suffix = "; ".join(state.observations[-3:])
        return f"I stopped because {state.stop_reason}. Completed observations: {suffix or 'none'}"
    repository_review = _repository_review_response(state)
    if repository_review:
        return repository_review.response
    edit_proposal = _latest_edit_proposal(state)
    if edit_proposal:
        return _format_edit_proposal(edit_proposal)
    command_result = _latest_command_result(state)
    if command_result:
        return _format_command_result(command_result, pending_commit=pending_commit_context(build_task_frame(request, state)))
    contents: dict[str, str] = {}
    for result in state.action_results:
        contents.update(result.payload.get("contents") or {})
    repo_observation = "\n".join(state.observations[-6:])
    answer = _answer_with_model(request, contents, state=state, repo_observation=repo_observation, skills_context=skills_context, on_delta=on_delta)
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="final-synthesis-prepared",
        event_type="activity_completed",
        phase="Finished",
        label="Prepared evidence-based answer",
        status="completed",
        observation="Prepared the final answer from gathered evidence.",
    )
    return answer


def build_final_response(state: AgentCoreState, request: AgentRunRequest) -> AgentRunResponse:
    review_response = _repository_review_response(state)
    if review_response and state.stop_reason not in {"cancelled", "waiting_approval"}:
        return _response_json_safe(review_response.model_copy(update={"loop_iteration": state.loop_iteration}), request)
    response_type = "command_approval" if state.pending_approval else "assistant_answer"
    graph_path = "agent_core:" + (
        "cancelled" if state.stop_reason == "cancelled"
        else "command_preview" if state.pending_approval
        else "read_file_answer" if state.files_read
        else "general_answer"
    )
    return _response_json_safe(build_agent_response(
        request,
        response=state.final_response,
        response_type=response_type,
        files_read=state.files_read,
        graph_path=graph_path,
        intent_classification=state.classifier_result.intent,
        run_id=state.run_id,
        skills_used=state.skills_used,
        stop_reason=state.stop_reason or "completed",
        loop_iteration=max(1, state.loop_iteration),
        command_approval=state.pending_approval,
        commands_planned=[shlex.join(list(state.pending_approval.get("command") or []))] if state.pending_approval else [],
        commands_run=state.commands_run,
        activity_events=[],
    ), request)


def _validate_active_repository(request: AgentRunRequest) -> None:
    try:
        active = get_active_repository()
    except Exception:
        active = None
    if active is None:
        return
    requested = str(request.project_path)
    active_path = str(active.project_path)
    if requested != active_path:
        raise ValueError(
            "The active repository changed before this run started. "
            "Open the repository again or start a new thread for the stale request."
        )
    if request.branch and active.branch and request.branch != active.branch:
        raise ValueError("The active branch changed before this run started.")


def stream_controller_graph(request: AgentRunRequest, *, run_id: str | None = None) -> Iterator[dict[str, Any]]:
    before_sequence = _latest_sequence(run_id) if run_id else 0
    response = run_controller_graph(request, run_id=run_id, stream_final_answer=True)
    for event in list_run_events(run_id or response.run_id or "", after_sequence=before_sequence):
        if event.get("type") == "assistant_delta":
            before_sequence = int(event.get("sequence") or before_sequence)
            yield event
    if response.reasoning:
        yield {"type": "reasoning_delta", "delta": response.reasoning, "source": "model_provided"}
    if not _streamed_assistant_delta(run_id or ""):
        for chunk in _chunk_text(response.response):
            yield {"type": "assistant_delta", "delta": chunk, "streaming_mode": "post_hoc_chunking"}
    final = _response_json_safe(response.model_copy(update={"activity_events": []}), request)
    yield {"type": "final_message", "result": safe_agent_response_payload(final)}


def classify_intent(request: AgentRunRequest) -> ClassifierResult:
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=CLASSIFIER_PROMPT,
                user_prompt=json.dumps(
                    {
                        "task": request.task,
                        "recent_messages": [
                            {"role": item.role, "content": item.content[:500], "metadata": item.metadata}
                            for item in request.conversation_history[-8:]
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        payload = _parse_json(raw)
    except Exception:
        payload = {}
    return _validate_classifier_payload(payload, request)


def _validate_classifier_payload(payload: dict[str, Any], request: AgentRunRequest) -> ClassifierResult:
    intent = str(payload.get("intent") or "ambiguous")
    if intent not in SUPPORTED_INTENTS:
        intent = "ambiguous"
    target_files = [str(item).strip().lstrip("/") for item in payload.get("target_files") or [] if str(item).strip()]
    if not target_files:
        target_files = _file_tokens(request.task)
    confidence = float(payload.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    return ClassifierResult(
        intent=intent,
        confidence=confidence,
        analysis_scope=str(payload.get("analysis_scope") or "unknown"),
        requested_workflow=str(payload.get("requested_workflow") or "other"),
        retrieval_goal=str(payload.get("retrieval_goal") or "answer"),
        target_files=target_files,
        target_symbols=[str(item) for item in payload.get("target_symbols") or []],
        file_types_requested=[str(item) for item in payload.get("file_types_requested") or []],
        requested_action=str(payload.get("requested_action") or intent),
        git_action=payload.get("git_action"),
        needs_tool=payload.get("needs_tool"),
        needs_clarification=bool(payload.get("needs_clarification")),
        clarification_question=payload.get("clarification_question"),
        requires_repository_wide_review=bool(payload.get("requires_repository_wide_review")),
        raw=payload,
    )


def propose_next_action_with_model(request: AgentRunRequest, state: AgentCoreState, task_frame: TaskFrame) -> AgentAction | None:
    registry = get_default_tool_registry()
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=NEXT_ACTION_PROMPT,
                user_prompt=json.dumps(
                    {
                        "task": request.task,
                        "task_frame": json_safe(task_frame),
                        "context_packet": json_safe(state.context_packet or {}),
                        "available_actions": registry.allowed_action_types(),
                        "available_tools": registry.specs_for_model(),
                        "state": {
                            "observations": state.observations[-8:],
                            "files_read": state.files_read,
                            "files_changed": state.files_changed,
                            "commands_run": state.commands_run,
                            "actions_taken": [action.model_dump() for action in state.actions_taken[-8:]],
                            "action_results": [_summarize_action_result(result) for result in state.action_results[-8:]],
                            "plan": state.plan[-6:],
                            "loop_iteration": state.loop_iteration,
                            "budgets": {
                                "max_file_reads": state.max_file_reads,
                                "max_commands": state.max_commands,
                            },
                        },
                        "safety_constraints": [
                            "All target files must stay inside the repository.",
                            "Commands must be previewed through command policy before running.",
                            "Mutating commands require approval and must not run automatically.",
                            "Final answers need gathered evidence unless the user only needs a simple clarification.",
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        payload = _parse_json(raw)
    except Exception:
        return None
    return validate_model_next_action(payload, request, state, task_frame)


def validate_model_next_action(payload: dict[str, Any], request: AgentRunRequest, state: AgentCoreState, task_frame: TaskFrame) -> AgentAction | None:
    action_type = str(payload.get("action_type") or "")
    allowed_action_types = set(get_default_tool_registry().allowed_action_types())
    if action_type not in allowed_action_types:
        return None
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.55:
        return None
    reason = _safe_reason_summary(payload.get("reason_summary") or f"Use {action_type} for the next safe step.")
    target_files = [str(item).strip().lstrip("/") for item in payload.get("target_files") or [] if str(item).strip()]
    target_symbols = [str(item).strip() for item in payload.get("target_symbols") or payload.get("symbol_queries") or [] if str(item).strip()]
    search_queries = [str(item).strip() for item in payload.get("search_queries") or [] if str(item).strip()]
    text_queries = [str(item).strip() for item in payload.get("text_queries") or [] if str(item).strip()]
    file_globs = [str(item).strip() for item in payload.get("file_globs") or [] if str(item).strip()]
    command = [str(item) for item in payload.get("command") or [] if str(item)]
    expected = str(payload.get("expected_output") or "")

    if action_type in {"read_file", "generate_edit"}:
        resolved = resolve_target_files(request, target_files, preferred=known_context_files(request, state))
        if not resolved:
            queries = _dedupe([*target_files, *target_symbols, *search_queries, *file_globs])
            if queries or text_queries:
                return AgentAction(
                    type="search_files",
                    reason_summary="Resolve model-proposed targets before reading or proposing edits.",
                    target_symbols=target_symbols,
                    expected_output="Ranked repo-contained candidate files.",
                    payload={"queries": queries, "text_queries": text_queries, "file_globs": file_globs, "source": "model_planner"},
                )
            return None
        unread = [path for path in resolved if path not in state.files_read]
        if action_type == "read_file":
            if not unread:
                return None
            return AgentAction(type="read_file", reason_summary=reason, target_files=unread, expected_output=expected)
        valid_edit_targets = set(current_edit_target_files(state, task_frame, request, model_targets=resolved))
        if not valid_edit_targets:
            queries = _dedupe([*target_files, *target_symbols, *search_queries, *file_globs])
            if queries or text_queries:
                return AgentAction(
                    type="search_files",
                    reason_summary="Find validated edit targets before preparing a patch.",
                    target_symbols=target_symbols,
                    expected_output="Ranked repo-contained candidate files.",
                    payload={"queries": queries, "text_queries": text_queries or EDIT_DISCOVERY_TEXT_SIGNALS, "file_globs": file_globs, "source": "model_planner"},
                )
            return None
        if not state.files_read and unread:
            return AgentAction(type="read_file", reason_summary="Read target files before preparing an edit proposal.", target_files=unread, expected_output="File contents for edit proposal.")
        unread_valid = [path for path in valid_edit_targets if path not in state.files_read]
        if unread_valid:
            return AgentAction(type="read_file", reason_summary="Read target files before preparing an edit proposal.", target_files=unread_valid, expected_output="File contents for edit proposal.")
        return AgentAction(type="generate_edit", reason_summary=reason, target_files=list(valid_edit_targets), expected_output=expected, payload={"source": "model_planner", "current_edit_targets": list(valid_edit_targets)})

    if action_type == "search_files":
        queries = _dedupe([*search_queries, *target_files, *file_globs, *target_symbols])
        if not queries and not text_queries:
            return None
        if _has_search_for(state, queries or text_queries):
            return None
        return AgentAction(
            type="search_files",
            reason_summary=reason,
            target_symbols=target_symbols,
            expected_output=expected or "Ranked repo-contained candidate files.",
            payload={"queries": queries, "text_queries": text_queries, "file_globs": file_globs, "source": "model_planner"},
        )

    if action_type in {"preview_command", "inspect_git_state", "run_approved_command"}:
        if not command:
            return None
        if action_type == "run_approved_command" and not (_latest_command_preview(state, command) and _preview_read_only(_latest_command_preview(state, command).command_result)):
            return AgentAction(
                type="inspect_git_state" if command[:1] == ["git"] else "preview_command",
                reason_summary=reason,
                command=command,
                expected_output="Command safety classification.",
            )
        preview_action = "inspect_git_state" if command[:1] == ["git"] else "preview_command"
        if not _has_command_preview(state, command):
            return AgentAction(type=preview_action, reason_summary=reason, command=command, expected_output="Command safety classification.")
        preview = _latest_command_preview(state, command)
        if preview and preview.status == "success" and _preview_read_only(preview.command_result) and not _has_command_run(state, command):
            return AgentAction(type="run_approved_command", reason_summary=reason, command=command, expected_output=expected or "Command output.")
        return None

    if action_type == "ask_clarification":
        attempted_search = any(action.type in {"search_files", "inspect_repo_tree"} for action in state.actions_taken)
        if not attempted_search and not payload.get("requires_approval"):
            return None
        return AgentAction(type="ask_clarification", reason_summary=reason, payload={"question": str(payload.get("question") or reason)})

    if action_type == "final_answer":
        enough = bool(payload.get("enough_evidence")) and has_substantive_evidence(state)
        if not enough:
            return None
        return AgentAction(type="final_answer", reason_summary=reason)

    if action_type == "analyze_repository":
        if _has_action(state, "analyze_repository"):
            return None
        return AgentAction(type="analyze_repository", reason_summary=reason, expected_output=expected, payload={"classifier": state.classifier_result})

    if action_type == "inspect_repo_tree" and not _has_action(state, "inspect_repo_tree"):
        return AgentAction(type="inspect_repo_tree", reason_summary=reason, expected_output=expected)
    return None


def _safe_reason_summary(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text[:180] or "Choose the next safe primitive action."


def _summarize_action_result(result: ActionResult) -> dict[str, Any]:
    return json_safe(
        {
            "status": result.status,
            "observation": result.observation[:240],
            "files_read": result.files_read,
            "files_changed": result.files_changed,
            "command": result.command_result.get("display_command") if result.command_result else None,
            "payload_keys": sorted(result.payload.keys()),
            "candidates": result.payload.get("candidates") or [],
        }
    )


def has_substantive_evidence(state: AgentCoreState) -> bool:
    if collect_file_contents(state):
        return True
    if state.commands_run:
        return True
    if _latest_edit_proposal(state) or _repository_review_response(state):
        return True
    if state.pending_approval:
        return True
    return False


def _initial_state(request: AgentRunRequest, run_id: str) -> AgentCoreState:
    return AgentCoreState(
        run_id=run_id,
        thread_id=request.thread_id,
        repo=request.project_path,
        branch=request.branch,
        user_task=request.task,
    )


def build_task_frame(request: AgentRunRequest, state: AgentCoreState) -> TaskFrame:
    classifier = state.classifier_result
    mentioned_files = _dedupe([*getattr(classifier, "target_files", []), *_file_tokens(request.task)])
    symbols = _dedupe([*getattr(classifier, "target_symbols", []), *symbol_tokens(request.task)])
    capabilities: list[str] = []
    if getattr(classifier, "retrieval_goal", "") in {"edit", "git", "command", "review", "answer"}:
        capabilities.append(f"weak_{classifier.retrieval_goal}")
    if getattr(classifier, "needs_tool", None):
        capabilities.append(f"weak_tool:{classifier.needs_tool}")
    if mentioned_files or symbols:
        capabilities.append("file_read")
    if not capabilities:
        capabilities.append("open_planning")
    constraints = []
    if mentioned_files:
        constraints.append("Use explicitly mentioned files before broader context.")
    return TaskFrame(
        user_goal=request.task,
        mentioned_files=mentioned_files,
        mentioned_symbols=symbols,
        constraints=constraints,
        likely_capabilities=_dedupe(capabilities),
        answer_style="concise_synthesis",
        safety_notes=["Treat legacy intent as a weak hint only."],
        uncertainty=[],
        should_ask_clarification=bool(classifier.needs_clarification and not mentioned_files),
        clarification_question=classifier.clarification_question,
        legacy_intent=classifier.intent,
    )


def files_from_recent_context(request: AgentRunRequest) -> list[str]:
    files: list[str] = []
    for item in request.conversation_history[-8:]:
        metadata = item.metadata or {}
        for key in ("files_read", "resolved_files"):
            for path in metadata.get(key) or []:
                if isinstance(path, str):
                    files.append(path)
        files.extend(_file_tokens(item.content or ""))
    return files


def symbol_tokens(text: str) -> list[str]:
    symbols: list[str] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]{2,})\b", text or ""):
        token = match.group(1)
        if "." not in token and token not in symbols:
            symbols.append(token)
    return symbols[:8]


def resolve_target_files(request: AgentRunRequest, target_files: list[str], *, preferred: list[str] | None = None) -> list[str]:
    repo = resolve_project_path(request.project_path).resolve()
    preferred = preferred or []
    all_files = searchable_repo_files(repo)
    resolved: list[str] = []
    for item in target_files:
        cleaned = str(item).strip().strip("`'\"")
        if not cleaned:
            continue
        try:
            candidate = ensure_relative_to_repo(repo, cleaned)
            if candidate.is_file():
                rel = str(candidate.relative_to(repo))
                if rel not in resolved:
                    resolved.append(rel)
                    continue
        except ValueError:
            pass
        lowered = cleaned.lower()
        preferred_matches = [path for path in preferred if path.lower() == lowered or Path(path).name.lower() == Path(cleaned).name.lower()]
        matches = preferred_matches or [path for path in all_files if path.lower() == lowered]
        if not matches:
            basename = Path(cleaned).name.lower()
            matches = [path for path in all_files if Path(path).name.lower() == basename]
        for rel in sorted(matches, key=file_match_priority):
            if rel not in resolved:
                resolved.append(rel)
                break
    return resolved[:8]


def searchable_repo_files(repo: Path) -> list[str]:
    files: list[str] = []
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo)
        if any(part.lower() in SEARCH_SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name.lower() not in {"readme", "makefile", "dockerfile"}:
            continue
        files.append(str(rel))
    return files


def file_match_priority(path: str) -> tuple[int, int, str]:
    parts = [part.lower() for part in Path(path).parts]
    generated = int(any(part in SEARCH_SKIP_DIRS for part in parts))
    source_bonus = 0 if Path(path).suffix.lower() in SOURCE_SUFFIXES else 1
    script_bonus = 0 if any(part in {"assets", "scripts", "src", "app", "apps"} for part in parts) else 1
    return (generated, source_bonus + script_bonus, path.lower())


def known_context_files(request: AgentRunRequest, state: AgentCoreState) -> list[str]:
    prior: list[str] = []
    if isinstance(state.context_packet, dict):
        prior = [str(item) for item in state.context_packet.get("prior_files_read") or []]
    return _dedupe([*state.files_read, *prior, *files_from_recent_context(request)])


def emit_target_resolution(state: AgentCoreState, request: AgentRunRequest, requested: list[str], resolved: list[str]) -> None:
    if _has_resolution_event(state):
        return
    state.observations.append(f"Resolved target files: {', '.join(resolved)}.")
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="resolve-target-files",
        event_type="activity_completed",
        phase="Searching",
        label="Resolved target files",
        status="completed",
        observation=f"Resolved {len(resolved)} target file(s).",
        current_action="Resolving mentioned file names to repo-relative paths.",
        next_action="Read resolved files before answering.",
        related_files=resolved,
        aggregate={"requested_files": requested, "resolved_files": resolved},
    )


def _has_resolution_event(state: AgentCoreState) -> bool:
    return any(item.startswith("Resolved target files:") for item in state.observations)


def command_needed_for_task(frame: TaskFrame, state: AgentCoreState) -> list[str] | None:
    text_command = command_needed_for_text(frame.user_goal)
    if text_command and not _has_command_run(state, text_command):
        return text_command
    if pending_commit_context(frame) and _has_command_run(state, ["git", "log", "--oneline", "-n", "5"]) and not _has_command_run(state, ["git", "status", "--short"]):
        return ["git", "status", "--short"]
    return None


def command_needed_for_text(text: str) -> list[str] | None:
    # Fallback-only compatibility heuristic. The model next-action planner is the primary planner.
    lowered = (text or "").lower()
    if ("git log" in lowered) or ("commit" in lowered and "recent" in lowered) or ("커밋" in text and "최근" in text):
        return ["git", "log", "--oneline", "-n", "5"]
    return None


def pending_commit_context(frame: TaskFrame) -> bool:
    # Fallback-only compatibility heuristic for commit approval messaging.
    lowered = frame.user_goal.lower()
    return "commit it" in lowered or "commit changes" in lowered or "커밋해" in frame.user_goal or "커밋 해" in frame.user_goal


def edit_requested(frame: TaskFrame) -> bool:
    return "weak_edit" in frame.likely_capabilities or edit_requested_text(frame.user_goal)


def edit_requested_text(text: str) -> bool:
    # Fallback-only compatibility heuristic. It must not run before explicit evidence or model planning.
    lowered = (text or "").lower()
    return any(token in lowered for token in ("fix", "change", "replace", "remove", "edit", "patch", "safe")) or any(token in text for token in ("고쳐", "바꿔", "변경", "제거", "수정", "안전"))


def likely_edit_file_queries(frame: TaskFrame) -> list[str]:
    queries = list(frame.mentioned_files)
    return _dedupe(queries) or ["*.cs"]


def _has_search_for(state: AgentCoreState, queries: list[str]) -> bool:
    wanted = {item.lower() for item in queries}
    for action in state.actions_taken:
        if action.type != "search_files":
            continue
        previous = {str(item).lower() for item in action.payload.get("queries") or []}
        if wanted & previous or not wanted:
            return True
    return False


def candidate_files_from_results(state: AgentCoreState, *, edit_related: bool = False) -> list[str]:
    min_score = 18.0 if edit_related else 1.0
    detail_candidates = current_search_candidate_files(state, min_score=min_score)
    if detail_candidates:
        return detail_candidates[:8]
    candidates: list[str] = []
    for result in state.action_results:
        for path in result.payload.get("candidates") or []:
            if isinstance(path, str) and path not in candidates:
                candidates.append(path)
    return candidates[:8]


def current_search_candidate_files(state: AgentCoreState, *, min_score: float = 1.0) -> list[str]:
    candidates: list[str] = []
    for result in reversed(state.action_results):
        details = result.payload.get("candidate_details") or []
        if not details:
            continue
        for detail in sorted(details, key=lambda item: -float(item.get("score") or 0.0)):
            path = str(detail.get("path") or "")
            score = float(detail.get("score") or 0.0)
            if path and score >= min_score and path not in candidates:
                candidates.append(path)
        if candidates:
            return candidates
    return []


def current_edit_target_files(
    state: AgentCoreState,
    frame: TaskFrame,
    request: AgentRunRequest,
    *,
    model_targets: list[str] | None = None,
) -> list[str]:
    explicit = set(resolve_target_files(request, frame.mentioned_files, preferred=known_context_files(request, state)))
    model_set = set(model_targets or [])
    high_confidence = set(current_search_candidate_files(state, min_score=24.0)[:2])
    candidates = [*explicit, *model_set, *high_confidence]
    valid: list[str] = []
    for path in candidates:
        if path not in state.files_read:
            continue
        if path in valid:
            continue
        if path in explicit or path in high_confidence:
            valid.append(path)
        elif path in model_set and (path in explicit or path in high_confidence):
            valid.append(path)
    return valid[:3]


def project_summary_files(request: AgentRunRequest) -> list[str]:
    repo = resolve_project_path(request.project_path).resolve()
    priority = ["README.md", "readme.md", "package.json", "pyproject.toml", "apps/web/package.json", "apps/local-worker/pyproject.toml"]
    files: list[str] = []
    seen_resolved: set[str] = set()
    for path in priority:
        target = (repo / path)
        if not target.is_file():
            continue
        if not is_supported_text_file(target):
            continue
        marker = str(target.resolve()).lower()
        if marker in seen_resolved:
            continue
        seen_resolved.add(marker)
        files.append(path)
    return files[:4]


def _existing_target_files(request: AgentRunRequest, target_files: list[str]) -> list[str]:
    return resolve_target_files(request, target_files)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _has_action(state: AgentCoreState, action_type: str) -> bool:
    return any(action.type == action_type for action in state.actions_taken)


def _has_command_preview(state: AgentCoreState, command: list[str]) -> bool:
    return any(action.command == command and action.type in {"preview_command", "inspect_git_state"} for action in state.actions_taken)


def _latest_command_preview(state: AgentCoreState, command: list[str]) -> ActionResult | None:
    preview_action_ids = {
        action.action_id
        for action in state.actions_taken
        if action.command == command and action.type in {"preview_command", "inspect_git_state"}
    }
    for result in reversed(state.action_results):
        if result.action_id in preview_action_ids:
            return result
    return None


def _latest_unrun_read_only_preview(state: AgentCoreState) -> ActionResult | None:
    for result in reversed(state.action_results):
        command = list((result.command_result or {}).get("command") or [])
        if command and _preview_read_only(result.command_result) and not _has_command_run(state, command):
            return result
    return None


def _has_command_run(state: AgentCoreState, command: list[str]) -> bool:
    return any(action.command == command and action.type == "run_approved_command" for action in state.actions_taken)


def _preview_read_only(command_result: dict[str, Any] | None) -> bool:
    return bool(command_result and command_result.get("read_only") and not command_result.get("needs_approval") and not command_result.get("blocked"))


def _repository_review_response(state: AgentCoreState) -> AgentRunResponse | None:
    for result in reversed(state.action_results):
        response = result.payload.get("response")
        if isinstance(response, AgentRunResponse):
            return response
        if isinstance(response, dict):
            try:
                return AgentRunResponse.model_validate(response)
            except Exception:
                continue
    return None


def _latest_command_result(state: AgentCoreState) -> dict[str, Any] | None:
    for result in reversed(state.action_results):
        if result.command_result and result.command_result.get("exit_code") is not None:
            return result.command_result
    return None


def _latest_edit_proposal(state: AgentCoreState) -> dict[str, Any] | None:
    for result in reversed(state.action_results):
        proposals = result.payload.get("edit_proposals") or []
        if proposals:
            return {"applied": bool(result.payload.get("applied")), "proposals": proposals}
    return None


def _format_edit_proposal(payload: dict[str, Any]) -> str:
    proposals = [item for item in payload.get("proposals") or [] if isinstance(item, dict)]
    if not proposals:
        return "I prepared no file changes because there was not enough safe evidence to build a minimal patch."
    sections = ["I prepared a proposed patch only. No files were modified in this run."]
    for item in proposals[:3]:
        file_path = str(item.get("file") or "unknown file")
        before = str(item.get("before_summary") or "before state recorded")
        after = str(item.get("after_summary") or "after state recorded")
        diff = str(item.get("diff_summary") or "").strip()
        notes = [str(note) for note in item.get("risk_notes") or [] if str(note)]
        notes_text = ("\nRisk notes: " + "; ".join(notes)) if notes else ""
        sections.append(
            f"\n`{file_path}`\nBefore: {before}\nAfter: {after}{notes_text}\n\n```diff\n{diff[:3000]}\n```"
        )
    return "\n".join(sections)


def _format_command_result(result: dict[str, Any], *, pending_commit: bool = False) -> str:
    command = str(result.get("display_command") or shlex.join(list(result.get("command") or [])))
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    status = result.get("status") or "ok"
    body = stdout or stderr or "No output."
    suffix = ""
    if pending_commit:
        suffix = "\n\nI did not create a commit. Committing requires an explicit approval path and a commit message."
    return f"Ran `{command}` and finished with status `{status}`.\n\n```text\n{body[:4000]}\n```{suffix}"


def _safe_observation(action: AgentAction, result: ActionResult) -> str:
    if result.status == "waiting_approval":
        return "Command preview requires approval before execution."
    if result.files_read:
        files = ", ".join(result.files_read)
        return f"Read {files}."
    if action.type == "generate_edit" and result.status == "success":
        proposals = result.payload.get("edit_proposals") or []
        files = ", ".join(str(item.get("file")) for item in proposals if isinstance(item, dict))
        return f"Prepared proposed edit for {files}. No files were written."
    if action.type == "search_files" and result.status == "success":
        candidates = result.payload.get("candidates") or []
        return f"Found candidate files: {', '.join(candidates[:8])}."
    if action.type == "analyze_repository" and result.status == "success":
        return "Completed repository-wide review and collected per-file evidence."
    if result.command_result and result.command_result.get("exit_code") is not None:
        return f"Ran `{result.command_result.get('display_command')}` with exit code {result.command_result.get('exit_code')}."
    if result.observation:
        return " ".join(str(result.observation).split())[:500]
    return ""


def _stream_final_delta(run_id: str):
    def emit(delta: str) -> None:
        _append_run_event_safe(run_id, {"type": "assistant_delta", "delta": delta, "streaming_mode": "model_stream"})

    return emit


def _streamed_assistant_delta(run_id: str) -> bool:
    if not run_id:
        return False
    return any(event.get("type") == "assistant_delta" for event in list_run_events(run_id))


def _latest_sequence(run_id: str | None) -> int:
    if not run_id:
        return 0
    events = list_run_events(run_id)
    return max((int(event.get("sequence") or 0) for event in events), default=0)


def _append_run_event_safe(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        return append_run_event(run_id, json_safe(event))
    except OSError:
        return json_safe(event)


def _response_json_safe(response: AgentRunResponse, request: AgentRunRequest) -> AgentRunResponse:
    try:
        payload = safe_agent_response_payload(response)
        json.dumps(payload, ensure_ascii=False)
        return response
    except Exception as exc:  # noqa: BLE001
        safe_payload = json_safe(response)
        safe_payload["response"] = (
            "The review completed, but RepoOperator hit an internal metadata serialization error. "
            "The readable summary is below...\n\n"
            + str(safe_payload.get("response") or response.response)
        )
        safe_payload["activity_events"] = json_safe(safe_payload.get("activity_events") or [])
        safe_payload["stop_reason"] = safe_payload.get("stop_reason") or "completed_with_metadata_error"
        _append_run_event_safe(
            response.run_id or "run_controller",
            {
                "type": "error",
                "event_type": "metadata_serialization_error",
                "status": "failed",
                "message": safe_repr(exc, limit=220),
            },
        )
        return build_agent_response(
            request,
            response=str(safe_payload.get("response") or ""),
            response_type=str(safe_payload.get("response_type") or "assistant_answer"),
            files_read=list(safe_payload.get("files_read") or []),
            graph_path=str(safe_payload.get("graph_path") or "agent_core:metadata_sanitized"),
            intent_classification=safe_payload.get("intent_classification"),
            run_id=safe_payload.get("run_id"),
            skills_used=list(safe_payload.get("skills_used") or []),
            stop_reason=str(safe_payload.get("stop_reason") or "completed_with_metadata_error"),
            loop_iteration=int(safe_payload.get("loop_iteration") or 1),
            activity_events=list(safe_payload.get("activity_events") or []),
        )


def _format_command_preview(command: list[str], preview: dict[str, Any]) -> str:
    text = " ".join(command)
    if preview.get("needs_approval"):
        return f"`{text}` requires approval before RepoOperator can run it. Reason: {preview.get('reason') or 'command policy'}"
    return f"`{text}` is allowed by command policy. I did not run a mutating command."


def _file_tokens(task: str) -> list[str]:
    files: list[str] = []
    for match in FILE_TOKEN_RE.finditer(task):
        candidate = match.group(1).strip("`'\".,)")
        if candidate.lower().startswith(("http://", "https://")):
            continue
        if candidate not in files:
            files.append(candidate)
    return files


def _parse_json(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _chunk_text(text: str, chunk_size: int = 96) -> Iterator[str]:
    for start in range(0, len(text or ""), chunk_size):
        chunk = text[start : start + chunk_size]
        if chunk:
            yield chunk
