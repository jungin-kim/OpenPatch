from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from repooperator_worker.agent_core.action_executor import ActionExecutor
from repooperator_worker.agent_core.actions import AgentAction
from repooperator_worker.agent_core.final_response import build_agent_response
from repooperator_worker.agent_core.repository_review import run_repository_review, should_use_repository_wide_review
from repooperator_worker.agent_core.state import AgentCoreState, ClassifierResult
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.model_client import ModelGenerationRequest, OpenAICompatibleModelClient, split_visible_reasoning
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


def run_controller_graph(request: AgentRunRequest, *, run_id: str | None = None) -> AgentRunResponse:
    run_id = run_id or "run_controller"
    _validate_active_repository(request)
    state = _initial_state(request, run_id)
    classifier = classify_intent(request)
    state.classifier_result = classifier
    skills_context, skills_used = enabled_skill_context()
    state.skills_used = skills_used
    executor = ActionExecutor(run_id=run_id, request=request)

    if classifier.needs_clarification:
        return build_agent_response(
            request,
            response=classifier.clarification_question or "Could you clarify which files or workflow you want me to inspect?",
            graph_path="agent_core:clarification",
            intent_classification=classifier.intent,
            run_id=run_id,
            skills_used=skills_used,
            stop_reason="needs_clarification",
        )

    if should_use_repository_wide_review(classifier):
        return run_repository_review(request=request, run_id=run_id, classifier=classifier, skills_used=skills_used)

    target_files = _existing_target_files(request, classifier.target_files)
    if target_files:
        action = AgentAction(
            type="read_file",
            reason_summary="Read structured target files before answering.",
            target_files=target_files,
            expected_output="File contents for grounded answer.",
        )
        state.actions_taken.append(action)
        result = executor.execute(action)
        state.action_results.append(result)
        state.files_read.extend(result.files_read)
        if result.status == "failed":
            return build_agent_response(
                request,
                response="I could not read the requested file safely: " + "; ".join(result.errors),
                graph_path="agent_core:read_file_failed",
                intent_classification=classifier.intent,
                run_id=run_id,
                files_read=state.files_read,
                skills_used=skills_used,
                stop_reason="failed",
            )
        answer = _answer_with_model(request, result.payload.get("contents") or {}, skills_context=skills_context)
        return build_agent_response(
            request,
            response=answer,
            files_read=state.files_read,
            graph_path="agent_core:read_file_answer",
            intent_classification=classifier.intent,
            run_id=run_id,
            skills_used=skills_used,
        )

    if classifier.intent in {"git_workflow_request", "gitlab_mr_request", "local_command_request"}:
        command = _command_for_classifier(classifier)
        action = AgentAction(
            type="inspect_git_state" if command[:1] == ["git"] else "preview_command",
            reason_summary=classifier.requested_action or "Preview requested command through policy.",
            command=command,
            expected_output="Command safety classification.",
        )
        result = executor.execute(action)
        return build_agent_response(
            request,
            response=_format_command_preview(command, result.command_result or {}),
            response_type="command_approval" if result.status == "waiting_approval" else "assistant_answer",
            command_approval=result.command_result if result.status == "waiting_approval" else None,
            commands_planned=[" ".join(command)],
            graph_path="agent_core:command_preview",
            intent_classification=classifier.intent,
            run_id=run_id,
            skills_used=skills_used,
            stop_reason="waiting_approval" if result.status == "waiting_approval" else "completed",
        )

    action = AgentAction(type="inspect_repo_tree", reason_summary="Inspect repository inventory for a grounded answer.")
    result = executor.execute(action)
    response = _answer_with_model(request, {}, repo_observation=result.observation, skills_context=skills_context)
    return build_agent_response(
        request,
        response=response,
        graph_path="agent_core:general_answer",
        intent_classification=classifier.intent,
        run_id=run_id,
        skills_used=skills_used,
        loop_iteration=max(1, len(state.actions_taken) + 1),
    )


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
    response = run_controller_graph(request, run_id=run_id)
    if response.reasoning:
        yield {"type": "reasoning_delta", "delta": response.reasoning, "source": "model_provided"}
    for chunk in _chunk_text(response.response):
        yield {"type": "assistant_delta", "delta": chunk}
    yield {"type": "final_message", "result": response.model_dump(mode="json")}


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


def _answer_with_model(
    request: AgentRunRequest,
    file_contents: dict[str, str],
    *,
    repo_observation: str = "",
    skills_context: str = "",
) -> str:
    try:
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
                pieces.append(str(delta.get("delta") or ""))
        raw = "".join(pieces) or OpenAICompatibleModelClient().generate_text(prompt)
        _hidden, visible = split_visible_reasoning(raw)
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
    repo = Path(request.project_path)
    existing: list[str] = []
    for item in target_files:
        candidate = (repo / item).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            existing.append(str(candidate.relative_to(repo.resolve())))
    return existing[:8]


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
