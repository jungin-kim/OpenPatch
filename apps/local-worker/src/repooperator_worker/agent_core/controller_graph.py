from __future__ import annotations

import json
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from repooperator_worker.agent_core.action_executor import ActionExecutor
from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.events import append_activity_event
from repooperator_worker.agent_core.final_response import build_agent_response
from repooperator_worker.agent_core.repository_review import run_repository_review, should_use_repository_wide_review
from repooperator_worker.agent_core.state import AgentCoreState, ClassifierResult
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.model_client import ModelGenerationRequest, OpenAICompatibleModelClient, split_visible_reasoning
from repooperator_worker.services.common import ensure_relative_to_repo, resolve_project_path
from repooperator_worker.services.event_service import append_run_event, get_run, list_run_events
from repooperator_worker.services.json_safe import json_safe, safe_agent_response_payload, safe_repr
from repooperator_worker.services.response_quality_service import clean_user_visible_response
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

FILE_TOKEN_RE = re.compile(r"\b([\w./\\-]+\.[A-Za-z0-9]{1,8})\b")
SUPPORTED_INTENTS = {
    "read_only_question", "repo_analysis", "recommend_change_targets", "review_recommendation",
    "write_request", "write_confirmation", "file_clarification_answer", "local_command_request",
    "git_workflow_request", "gitlab_mr_request", "multi_step_request", "pasted_prompt_or_spec",
    "apply_spec_to_repo", "ambiguous",
}
SUPPORTED_STEERING_TYPES = {
    "add_target_file",
    "change_output_format",
    "cancel",
    "continue",
    "defer",
    "unknown",
}

STEERING_PROMPT = """\
You are RepoOperator's steering parser. Return JSON only.
Schema:
{
  "steering_type": "add_target_file|change_output_format|cancel|continue|defer|unknown",
  "target_files": [],
  "output_format": null,
  "confidence": 0.0,
  "reason": "short explanation"
}
Extract only a structured steering decision for an already-running agent. Do not route by language keywords.
"""


@dataclass
class SteeringDecision:
    steering_type: str = "unknown"
    target_files: list[str] | None = None
    output_format: str | None = None
    confidence: float = 0.0
    reason: str = ""


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
    executor = ActionExecutor(run_id=run_id, request=request)
    started = time.perf_counter()
    max_wall_clock_seconds = 300

    load_context(state, request)
    classify(state, request)
    create_initial_plan(state)
    emit_plan_update(state, request, "Created initial plan")

    while should_continue(state, started=started, max_wall_clock_seconds=max_wall_clock_seconds):
        check_cancel(state, request)
        if state.cancellation_requested:
            break
        consume_steering_for_state(state, request)
        action = controller_choose_next_action(state, request)
        state.current_step = action.reason_summary
        if action.type == "final_answer":
            break
        if action.type == "ask_clarification":
            state.stop_reason = "needs_clarification"
            state.final_response = state.classifier_result.clarification_question or "Could you clarify which files or workflow you want me to inspect?"
            break

        state.actions_taken.append(action)
        result = executor.execute(action)
        state.action_results.append(result)
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
        observe_result(state, action, result, request)
        update_plan(state, action, result, request)
        check_cancel(state, request)
        if state.cancellation_requested:
            break
        if result.status == "waiting_approval":
            state.stop_reason = "waiting_approval"
            break
        if result.status in {"failed", "cancelled", "timed_out"}:
            state.stop_reason = result.status
            break

    if not state.final_response:
        on_delta = _stream_final_delta(run_id) if stream_final_answer else None
        state.final_response = build_final_answer_text(state, request, skills_context=skills_context, on_delta=on_delta)
    return build_final_response(state, request)


def load_context(state: AgentCoreState, request: AgentRunRequest) -> None:
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
    )


def classify(state: AgentCoreState, request: AgentRunRequest) -> None:
    state.classifier_result = classify_intent(request)
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="controller-classify",
        event_type="activity_completed",
        phase="Thinking",
        label="Classified request",
        status="completed",
        observation=f"Intent: {state.classifier_result.intent}; scope: {state.classifier_result.analysis_scope}.",
    )


def create_initial_plan(state: AgentCoreState) -> None:
    classifier = state.classifier_result
    plan = ["Classify the request", "Choose the next safe action"]
    if classifier.needs_clarification:
        plan.append("Ask a clarification question")
    elif should_use_repository_wide_review(classifier):
        plan.extend(["Run repository-wide review", "Summarize completed evidence"])
    elif classifier.target_files or _file_tokens(state.user_task):
        plan.extend(["Read target files", "Answer from file evidence"])
    elif classifier.intent in {"git_workflow_request", "gitlab_mr_request", "local_command_request"}:
        plan.extend(["Preview command safety", "Run only approved or read-only command", "Report command result"])
    else:
        plan.extend(["Inspect repository tree", "Answer from gathered context"])
    state.plan = plan


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


def consume_steering_for_state(state: AgentCoreState, request: AgentRunRequest) -> None:
    try:
        from repooperator_worker.services.agent_run_coordinator import consume_steering

        items = consume_steering(state.run_id)
    except Exception:
        items = []
    for item in items:
        content = str(item.get("content") or "").strip()
        state.steering_instructions.append(item)
        applied = False
        decision = parse_steering_instruction(content, request, state)
        target_files = _existing_target_files(request, decision.target_files or [])
        if decision.steering_type == "add_target_file" and target_files:
            existing = list(state.classifier_result.target_files)
            for path in target_files:
                if path not in existing:
                    existing.append(path)
            state.classifier_result.target_files = existing
            applied = True
        if decision.steering_type == "change_output_format" and decision.output_format and decision.confidence >= 0.65:
            state.observations.append(f"Steering requested output format: {decision.output_format}.")
            applied = True
        if decision.steering_type == "cancel" and decision.confidence >= 0.8:
            state.cancellation_requested = True
            state.stop_reason = "cancelled"
            applied = True
        event_type = "steering_applied" if applied else "steering_deferred"
        append_activity_event(
            run_id=state.run_id,
            request=request,
            activity_id=f"controller-steering:{item.get('id') or len(state.steering_instructions)}",
            event_type="activity_completed",
            phase="Planning",
            label="Updated plan from steering" if applied else "Steering deferred",
            status="completed",
            observation=(
                decision.reason or "Steering updated structured run state."
                if applied
                else decision.reason or "Steering was recorded, but it did not safely map to the current action."
            ),
            detail=content[:220],
            aggregate={"steering_event_type": event_type, "decision": json_safe(decision)},
        )


def parse_steering_instruction(content: str, request: AgentRunRequest, state: AgentCoreState) -> SteeringDecision:
    raw_content = (content or "").strip()
    if not raw_content:
        return SteeringDecision(steering_type="defer", target_files=[], confidence=0.0, reason="Empty steering instruction.")
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=STEERING_PROMPT,
                user_prompt=json.dumps(
                    {
                        "task": request.task,
                        "steering": raw_content,
                        "current_target_files": state.classifier_result.target_files,
                        "files_read": state.files_read,
                        "stop_reason": state.stop_reason,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        decision = _validate_steering_payload(_parse_json(raw))
        if decision.steering_type != "unknown" and decision.confidence >= 0.5:
            return decision
    except Exception as exc:  # noqa: BLE001
        return SteeringDecision(steering_type="defer", target_files=[], confidence=0.0, reason=f"Steering parser unavailable: {safe_repr(exc, limit=160)}")

    file_targets = _file_tokens(raw_content)
    if file_targets:
        return SteeringDecision(
            steering_type="add_target_file",
            target_files=file_targets,
            confidence=0.55,
            reason="Detected explicit file path tokens; paths still require repository containment validation.",
        )
    return SteeringDecision(steering_type="defer", target_files=[], confidence=0.0, reason="No safe structured steering decision was available.")


def controller_choose_next_action(state: AgentCoreState, request: AgentRunRequest) -> AgentAction:
    classifier = state.classifier_result
    if classifier.needs_clarification:
        return AgentAction(type="ask_clarification", reason_summary="Ask for missing routing information.")
    if should_use_repository_wide_review(classifier) and not _has_action(state, "analyze_repository"):
        classifier_payload = json_safe(classifier)
        return AgentAction(
            type="analyze_repository",
            reason_summary="Run a bounded repository-wide review.",
            expected_output="Completed per-file review evidence.",
            payload=dict(classifier=classifier_payload),
        )
    target_files = _existing_target_files(request, classifier.target_files)
    unread = [path for path in target_files if path not in state.files_read]
    if unread:
        return AgentAction(
            type="read_file",
            reason_summary="Read structured target files before answering.",
            target_files=unread,
            expected_output="File contents for grounded answer.",
        )
    if classifier.intent in {"git_workflow_request", "gitlab_mr_request", "local_command_request"}:
        command = _command_for_classifier(classifier)
        if not _has_command_preview(state, command):
            return AgentAction(
                type="inspect_git_state" if command[:1] == ["git"] else "preview_command",
                reason_summary=classifier.requested_action or "Preview requested command through policy.",
                command=command,
                expected_output="Command safety classification.",
            )
        preview = _latest_command_preview(state, command)
        if preview and preview.status == "success" and _preview_read_only(preview.command_result):
            if not _has_command_run(state, command):
                return AgentAction(
                    type="run_approved_command",
                    reason_summary="Run read-only command after policy preview.",
                    command=command,
                    expected_output="Read-only command output.",
                )
        return AgentAction(type="final_answer", reason_summary="Answer from command preview or result.")
    if not _has_action(state, "inspect_repo_tree") and not state.files_read:
        return AgentAction(type="inspect_repo_tree", reason_summary="Inspect repository inventory for a grounded answer.")
    return AgentAction(type="final_answer", reason_summary="Enough evidence is available for a final answer.")


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
    command_result = _latest_command_result(state)
    if command_result:
        return _format_command_result(command_result)
    contents: dict[str, str] = {}
    for result in state.action_results:
        contents.update(result.payload.get("contents") or {})
    repo_observation = "\n".join(state.observations[-6:])
    return _answer_with_model(request, contents, repo_observation=repo_observation, skills_context=skills_context, on_delta=on_delta)


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


def _validate_steering_payload(payload: dict[str, Any]) -> SteeringDecision:
    steering_type = str(payload.get("steering_type") or "unknown")
    if steering_type not in SUPPORTED_STEERING_TYPES:
        steering_type = "unknown"
    target_files = [str(item).strip().lstrip("/") for item in payload.get("target_files") or [] if str(item).strip()]
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return SteeringDecision(
        steering_type=steering_type,
        target_files=target_files,
        output_format=str(payload.get("output_format")) if payload.get("output_format") else None,
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(payload.get("reason") or ""),
    )


def _answer_with_model(
    request: AgentRunRequest,
    file_contents: dict[str, str],
    *,
    repo_observation: str = "",
    skills_context: str = "",
    on_delta: Any | None = None,
) -> str:
    try:
        try:
            resolved_repo = str(resolve_project_path(request.project_path))
        except ValueError:
            resolved_repo = request.project_path
        prompt = ModelGenerationRequest(
            system_prompt=(
                "You are RepoOperator, a local-first coding agent proxy. Answer with visible, evidence-backed "
                "work summaries only. Do not include hidden reasoning. Keep the response grounded in the supplied "
                "repository context.\n"
                + (f"\nEnabled skills with provenance:\n{skills_context}\n" if skills_context else "")
            ),
            user_prompt=json.dumps(
                {
                    "task": request.task,
                    "repo": request.project_path,
                    "active_repository": f"source: {request.git_provider}\npath: {resolved_repo}",
                    "branch": request.branch,
                    "repo_observation": repo_observation,
                    "files": file_contents,
                },
                ensure_ascii=False,
            ),
        )
        pieces: list[str] = []
        reasoning: list[str] = []
        for delta in OpenAICompatibleModelClient().stream_text(prompt):
            if delta.get("type") == "reasoning_delta":
                reasoning.append(str(delta.get("delta") or ""))
            elif delta.get("type") == "assistant_delta":
                text = str(delta.get("delta") or "")
                pieces.append(text)
                if on_delta and text:
                    on_delta(text)
        raw = "".join(pieces) or OpenAICompatibleModelClient().generate_text(prompt)
        _reasoning, visible = split_visible_reasoning(raw)
        cleaned, _ = clean_user_visible_response(visible, user_task=request.task)
        return cleaned.strip() or _fallback_answer(request, file_contents, repo_observation)
    except Exception:
        return _fallback_answer(request, file_contents, repo_observation)


def _fallback_answer(request: AgentRunRequest, file_contents: dict[str, str], repo_observation: str) -> str:
    if file_contents:
        files = ", ".join(f"`{path}`" for path in file_contents)
        return f"I inspected {files}. Ask for a narrower change or review focus and I can continue from those files."
    return f"I inspected the repository inventory. {repo_observation or 'No specific target files were provided.'}"


def _initial_state(request: AgentRunRequest, run_id: str) -> AgentCoreState:
    return AgentCoreState(
        run_id=run_id,
        thread_id=request.thread_id,
        repo=request.project_path,
        branch=request.branch,
        user_task=request.task,
    )


def _existing_target_files(request: AgentRunRequest, target_files: list[str]) -> list[str]:
    repo = resolve_project_path(request.project_path).resolve()
    existing: list[str] = []
    for item in target_files:
        try:
            candidate = ensure_relative_to_repo(repo, item)
        except ValueError:
            continue
        if candidate.is_file():
            existing.append(str(candidate.relative_to(repo)))
    return existing[:8]


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


def _format_command_result(result: dict[str, Any]) -> str:
    command = str(result.get("display_command") or shlex.join(list(result.get("command") or [])))
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    status = result.get("status") or "ok"
    body = stdout or stderr or "No output."
    return f"Ran `{command}` and finished with status `{status}`.\n\n```text\n{body[:4000]}\n```"


def _safe_observation(action: AgentAction, result: ActionResult) -> str:
    if result.status == "waiting_approval":
        return "Command preview requires approval before execution."
    if result.files_read:
        files = ", ".join(result.files_read)
        return f"Read {files}."
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


def _command_for_classifier(classifier: ClassifierResult) -> list[str]:
    action = (classifier.git_action or classifier.requested_action or "").lower()
    if "diff" in action:
        return ["git", "diff", "--stat"]
    if "log" in action or "recent" in action:
        return ["git", "log", "--oneline", "-10"]
    if "push" in action:
        return ["git", "push"]
    if "commit" in action:
        return ["git", "status", "--short"]
    return ["git", "status", "--short"]


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
