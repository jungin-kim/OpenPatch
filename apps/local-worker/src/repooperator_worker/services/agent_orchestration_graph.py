"""LangGraph orchestration for repository answers, proposals, and tool plans."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from repooperator_worker.config import (
    WRITE_MODE_AUTO_APPLY,
    WRITE_MODE_WRITE_WITH_APPROVAL,
    get_settings,
)
from repooperator_worker.schemas import (
    AgentProposeFileRequest,
    AgentRunRequest,
    AgentRunResponse,
)
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.context_service import build_query_aware_context
from repooperator_worker.services.edit_service import propose_file_edit
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)
from repooperator_worker.services.retrieval_service import SKIP_DIRS
from repooperator_worker.services.skills_service import enabled_skill_context
from repooperator_worker.services.thread_context_service import (
    ThreadContext,
    build_thread_context,
)

logger = logging.getLogger(__name__)

Intent = Literal[
    "read_only_question",
    "repo_analysis",
    "recommend_change_targets",
    "write_request",
    "write_confirmation",
    "file_clarification_answer",
    "local_command_request",
    "git_workflow_request",
    "gitlab_mr_request",
    "ambiguous",
]

SUPPORTED_SUFFIXES = {
    ".py",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".md",
    ".txt",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".sh",
}

FILE_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+")

SUPPORTED_INTENTS: set[str] = {
    "read_only_question",
    "repo_analysis",
    "recommend_change_targets",
    "write_request",
    "write_confirmation",
    "file_clarification_answer",
    "local_command_request",
    "git_workflow_request",
    "gitlab_mr_request",
    "ambiguous",
}

CLASSIFIER_SYSTEM_PROMPT = """\
You are RepoOperator's intent classifier. Decide what the user is asking the
repository agent to do. Return JSON only; do not include markdown or prose.

Schema:
{
  "intent": "read_only_question|repo_analysis|recommend_change_targets|write_request|write_confirmation|file_clarification_answer|local_command_request|git_workflow_request|gitlab_mr_request|ambiguous",
  "confidence": 0.0,
  "target_files": [],
  "target_symbols": [],
  "requested_action": "short action summary",
  "needs_tool": null,
  "needs_clarification": false,
  "clarification_question": null
}

Intent guidance:
- read_only_question: answer or explain code without changing files or running local commands.
- repo_analysis: inspect the repository structure and explain architecture or health.
- recommend_change_targets: recommend concrete files to inspect or improve; do not require a file first.
- write_request: user asks for a code/file change or a change proposal.
- write_confirmation: user confirms a previous suggestion/proposal should be applied or prepared.
- file_clarification_answer: user chooses from previously offered candidate files.
- local_command_request: user asks to run a local command such as git status, npm install, or shell command.
- git_workflow_request: user asks to commit, push, inspect branch/status/diff/log, or otherwise perform git workflow steps.
- gitlab_mr_request: user asks about GitLab merge requests, pipelines, or MR creation.
- ambiguous: there is not enough context to safely decide.

Use recent thread context, pending candidates, and pending proposals. Korean and
English requests are both expected. Do not expose hidden reasoning.
"""


class PendingState(TypedDict, total=False):
    candidates: list[str]
    selected_file: str | None
    suggestion: str | None
    proposal_file: str | None


class OrchestrationState(TypedDict, total=False):
    request: AgentRunRequest
    settings: Any
    pending: PendingState
    intent: Intent
    confidence: float
    intent_reason: str
    file_hints: list[str]
    target_files: list[str]
    target_symbols: list[str]
    requested_action: str | None
    needs_tool: str | None
    needs_clarification: bool
    clarification_question: str | None
    classifier: str
    validation_status: str
    candidates: list[str]
    selected_file: str | None
    instruction: str
    plan: str
    proposal: Any
    result: AgentRunResponse | None
    graph_path: str
    error: str | None
    skills_context: str
    skills_used: list[str]
    thread_context: ThreadContext
    context_source: str
    context_reference: Any  # ContextReferenceResult | None


def _base_response(
    request: AgentRunRequest,
    *,
    response: str,
    response_type: str,
    files_read: list[str] | None = None,
    **extra: Any,
) -> AgentRunResponse:
    settings = get_settings()
    try:
        model_name = OpenAICompatibleModelClient().model_name
    except (ValueError, RuntimeError):
        model_name = settings.configured_model_name or "unknown"
    return AgentRunResponse(
        project_path=request.project_path,
        git_provider=request.git_provider,
        active_repository_source=request.git_provider,
        active_repository_path=request.project_path,
        active_branch=request.branch,
        task=request.task,
        model=model_name,
        branch=request.branch,
        repo_root_name=Path(request.project_path).name or request.project_path,
        context_summary="",
        top_level_entries=[],
        readme_included=False,
        diff_included=response_type == "change_proposal",
        is_git_repository=True,
        files_read=files_read or [],
        response=response,
        response_type=response_type,
        agent_flow="langgraph",
        **extra,
    )


def _context_reference_debug(state: OrchestrationState) -> dict[str, Any]:
    ref = state.get("context_reference")
    if ref is None:
        return {}
    trace = ref.to_debug_trace()
    return {
        "context_reference_resolver": trace.get("context_reference_resolver"),
        "resolved_reference_type": trace.get("resolved_reference_type"),
        "reference_confidence": trace.get("confidence"),
        "reference_clarification_needed": trace.get("clarification_needed"),
    }


def _classifier_debug(state: OrchestrationState) -> dict[str, Any]:
    resolved_files = []
    if state.get("selected_file"):
        resolved_files = [state["selected_file"]]
    elif state.get("target_files"):
        resolved_files = state.get("target_files", [])
    elif state.get("candidates"):
        resolved_files = state.get("candidates", [])
    return {
        "classifier": state.get("classifier") or "llm",
        "classifier_confidence": state.get("confidence"),
        "resolved_files": resolved_files,
        "resolved_symbols": state.get("target_symbols") or [],
        "validation_status": state.get("validation_status") or "pending",
    }


def _load_context(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    pending: PendingState = {}
    for message in reversed(request.conversation_history):
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        response_type = metadata.get("response_type")
        if response_type == "clarification" and metadata.get("clarification_candidates"):
            pending["candidates"] = list(metadata.get("clarification_candidates") or [])
            pending["suggestion"] = message.content
            break
        if response_type == "proposal_error" and metadata.get("selected_target_file"):
            pending["selected_file"] = str(metadata.get("selected_target_file"))
            pending["suggestion"] = message.content
            break
        if response_type == "change_proposal" and metadata.get("proposal_relative_path"):
            pending["proposal_file"] = str(metadata.get("proposal_relative_path"))
            pending["selected_file"] = str(metadata.get("proposal_relative_path"))
            pending["suggestion"] = message.content
            break
        if response_type == "assistant_answer" and not pending.get("suggestion"):
            pending["suggestion"] = message.content

    skills_context, skills_used = enabled_skill_context()
    thread_context = build_thread_context(request)

    return {
        "settings": get_settings(),
        "pending": pending,
        "instruction": request.task,
        "skills_context": skills_context,
        "skills_used": skills_used,
        "thread_context": thread_context,
        "context_source": "retrieval",
        "context_reference": None,
        "classifier": "llm",
        "validation_status": "not_started",
        "graph_path": "load_context",
    }


def _validate_active_repository_context(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    active_repository = get_active_repository()
    if active_repository is None:
        return {"graph_path": f"{state.get('graph_path', '')}->validate_active_repository"}
    if request.git_provider and active_repository.git_provider != request.git_provider:
        raise ValueError(
            "Active repository source changed before the answer was generated. "
            "Open the selected repository again and retry."
        )
    if active_repository.project_path != request.project_path:
        raise ValueError(
            "Active repository context does not match this agent request. "
            f"Active: {active_repository.git_provider}:{active_repository.project_path}; "
            f"request: {request.git_provider or 'unknown'}:{request.project_path}."
        )
    if request.branch and active_repository.branch and request.branch != active_repository.branch:
        raise ValueError(
            "Active repository branch changed before the answer was generated. "
            f"Active branch: {active_repository.branch}; request branch: {request.branch}."
        )
    return {"graph_path": f"{state.get('graph_path', '')}->validate_active_repository"}


def _classify_intent(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    pending = state.get("pending", {})
    thread_context: ThreadContext = state.get("thread_context") or ThreadContext(
        request.project_path,
        request.branch,
    )
    file_hints = _extract_file_hints(request.task)
    classification = _classify_with_llm(state, file_hints)
    if classification is None:
        classification = _fallback_classification(state, file_hints)

    intent = _normalize_intent(classification.get("intent"))
    confidence = _safe_float(classification.get("confidence"), default=0.0)
    target_files = _validate_classifier_files(
        request.project_path,
        [str(item) for item in classification.get("target_files") or []],
    )
    target_symbols = [
        str(symbol)
        for symbol in (classification.get("target_symbols") or [])
        if str(symbol) in thread_context.symbols or str(symbol).strip()
    ][:8]

    if not target_files and target_symbols:
        target_files = _validate_classifier_files(
            request.project_path,
            [thread_context.symbols[symbol] for symbol in target_symbols if symbol in thread_context.symbols],
        )

    candidates = []
    if intent == "file_clarification_answer" and pending.get("candidates"):
        selected = _select_from_candidates(request.task, pending["candidates"])
        if selected:
            target_files = [selected]
        else:
            candidates = list(pending["candidates"])

    if classification.get("needs_clarification") and not candidates:
        candidates = target_files or pending.get("candidates") or thread_context.recent_files[:8]

    return {
        "intent": intent,
        "confidence": confidence,
        "intent_reason": str(classification.get("requested_action") or ""),
        "file_hints": file_hints,
        "target_files": target_files,
        "target_symbols": target_symbols,
        "requested_action": classification.get("requested_action"),
        "needs_tool": classification.get("needs_tool"),
        "needs_clarification": bool(classification.get("needs_clarification")),
        "clarification_question": classification.get("clarification_question"),
        "classifier": str(classification.get("classifier") or "llm"),
        "candidates": candidates,
        "validation_status": "classified",
        "graph_path": f"{state.get('graph_path', '')}->classify_intent",
    }


def _resolve_target_files(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    pending = state.get("pending", {})
    intent = state.get("intent", "read_only_question")

    if intent == "file_clarification_answer":
        candidates = pending.get("candidates", [])
        selected = _select_from_candidates(request.task, candidates)
        if selected:
            return {
                "selected_file": selected,
                "candidates": [],
                "instruction": _find_previous_write_instruction(request) or request.task,
                "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
            }
        return {"candidates": candidates}

    if intent == "write_confirmation":
        proposal_file = pending.get("proposal_file")
        if proposal_file:
            result = _base_response(
                request,
                response=(
                    f"A proposal for `{proposal_file}` is already ready. "
                    "Review the diff and click Apply to modify the file."
                ),
                response_type="assistant_answer",
                selected_target_file=proposal_file,
                intent_classification=intent,
                graph_path="write_confirmation_existing_proposal",
                **_classifier_debug(state),
            )
            return {"result": result}
        if pending.get("selected_file"):
            return {
                "selected_file": pending["selected_file"],
                "instruction": _find_previous_write_instruction(request) or request.task,
                "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
            }
        # LLM context reference resolver did not find a file — last resort: thread context
        thread_context: ThreadContext = state.get("thread_context") or ThreadContext(request.project_path, request.branch)
        if thread_context.last_analyzed_file:
            return {
                "selected_file": thread_context.last_analyzed_file,
                "instruction": _find_previous_write_instruction(request) or request.task,
                "graph_path": f"{state.get('graph_path', '')}->resolve_target_files_thread_fallback",
            }

    if intent == "write_request" and pending.get("selected_file"):
        return {
            "selected_file": pending["selected_file"],
            "instruction": request.task,
            "validation_status": "target_file_valid",
            "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
        }
    if intent in {"write_request", "write_confirmation", "file_clarification_answer"} and state.get("target_files"):
        return {
            "selected_file": state["target_files"][0],
            "instruction": _find_previous_write_instruction(request) or request.task,
            "validation_status": "target_file_valid",
            "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
        }
    if intent == "write_request" and state.get("candidates"):
        return {
            "selected_file": None,
            "candidates": state.get("candidates", []),
            "validation_status": "needs_clarification",
            "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
        }

    hints = state.get("file_hints", [])
    if not hints:
        hints = _extract_file_hints(_find_previous_write_instruction(request) or "")
    selected, candidates = _resolve_file_hints(request.project_path, hints)
    return {
        "selected_file": selected,
        "candidates": candidates,
        "validation_status": "target_file_valid" if selected else "needs_clarification",
        "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
    }


def _permission_required(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    result = _base_response(
        request,
        response=(
            "This looks like a change request. Switch to Auto review to let "
            "RepoOperator propose a diff for your approval."
        ),
        response_type="permission_required",
        intent_classification=state.get("intent"),
        graph_path="permission_required",
        thread_context_files=state.get("thread_context", ThreadContext(request.project_path, request.branch)).recent_files,
        thread_context_symbols=state.get("thread_context", ThreadContext(request.project_path, request.branch)).symbol_names,
        context_source=state.get("context_source"),
        **_classifier_debug(state),
    )
    return {"result": result, "graph_path": "permission_required"}


def _ask_clarification(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    candidates = state.get("candidates", [])
    thread_context: ThreadContext = state.get("thread_context") or ThreadContext(request.project_path, request.branch)
    context_ref = state.get("context_reference")

    # Use LLM-generated clarification question when available
    llm_question = state.get("clarification_question") or (context_ref.clarification_question if context_ref else None)

    if candidates:
        rendered = "\n".join(f"- `{candidate}`" for candidate in candidates)
        base = llm_question or "I found multiple possible targets in the recent context. Choose one to continue."
        response = f"{base}\n\n{rendered}"
    elif llm_question:
        response = llm_question
        if thread_context.recent_files:
            file_list = "\n".join(f"- `{f}`" for f in thread_context.recent_files[:5])
            response = f"{llm_question}\n\nRecent files:\n{file_list}"
            candidates = list(thread_context.recent_files[:5])
    elif thread_context.last_analyzed_file:
        response = (
            f"Should I apply this change to `{thread_context.last_analyzed_file}`? "
            "Reply with the target name to confirm, or share a different target."
        )
        candidates = [thread_context.last_analyzed_file]
    elif thread_context.recent_files:
        file_list = "\n".join(f"- `{f}`" for f in thread_context.recent_files[:5])
        response = (
            f"I found recent files from this session:\n\n{file_list}\n\n"
            "Choose one of these targets, or describe the change and I will recommend where to apply it."
        )
        candidates = list(thread_context.recent_files[:5])
    else:
        response = (
            "I need one target from the current repository context before preparing a change. "
            "You can choose a recent file, name a symbol, or ask RepoOperator to recommend targets."
        )
    result = _base_response(
        request,
        response=response,
        response_type="clarification",
        clarification_candidates=candidates,
        intent_classification=state.get("intent"),
        graph_path="clarification",
        skills_used=state.get("skills_used", []),
        thread_context_files=thread_context.recent_files,
        thread_context_symbols=thread_context.symbol_names,
        context_source=state.get("context_source"),
        **_context_reference_debug(state),
        **_classifier_debug(state),
    )
    return {"result": result, "graph_path": "clarification"}


def _recommend_change_targets(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    context = build_query_aware_context(request.project_path, request.task)
    repo_path = resolve_project_path(request.project_path)
    candidate_files = _recommend_candidate_files(repo_path)
    skills_context = state.get("skills_context") or ""

    fallback_lines = [
        "Here are concrete files worth inspecting first:",
        "",
    ]
    for relative_path, reason in candidate_files[:8]:
        fallback_lines.append(f"- `{relative_path}` — {reason}")
    fallback = "\n".join(fallback_lines) if candidate_files else (
        "I could not find obvious source or configuration files yet. Start with the README and top-level configuration files."
    )

    response = fallback
    try:
        model_response = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "You are RepoOperator. Recommend concrete repository files to inspect or modify. "
                    "Do not ask the user to provide a file path. Use the provided repository context. "
                    "Return concise bullets with file paths and reasons. Do not claim to edit files."
                ),
                user_prompt="\n\n".join(
                    part
                    for part in [
                        f"User request: {request.task}",
                        skills_context,
                        context.to_prompt_context(),
                        "Candidate files:\n"
                        + "\n".join(f"- {path}: {reason}" for path, reason in candidate_files[:12]),
                    ]
                    if part
                ),
            )
        )
        if model_response.strip():
            response = model_response.strip()
    except (ValueError, RuntimeError) as exc:
        logger.info("recommend_change_targets using deterministic fallback: %r", exc)

    result = _base_response(
        request,
        response=response,
        response_type="assistant_answer",
        files_read=context.files_read,
        intent_classification=state.get("intent"),
        graph_path="recommend_change_targets",
        skills_used=state.get("skills_used", []),
        thread_context_files=state.get("thread_context", ThreadContext(request.project_path, request.branch)).recent_files,
        thread_context_symbols=state.get("thread_context", ThreadContext(request.project_path, request.branch)).symbol_names,
        context_source=state.get("context_source"),
        **_context_reference_debug(state),
        **_classifier_debug(state),
    ).model_copy(
        update={
            "context_summary": context.summary,
            "top_level_entries": context.top_level_entries,
            "readme_included": bool(context.readme_excerpt),
            "is_git_repository": context.is_git_repository,
            "branch": context.branch or request.branch,
            "active_branch": context.branch or request.branch,
        }
    )
    return {"result": result, "graph_path": "recommend_change_targets"}


def _generate_change_plan(state: OrchestrationState) -> dict[str, Any]:
    selected_file = state.get("selected_file")
    request = state["request"]
    plan = (
        f"Modify {selected_file} according to the user's request. "
        "Keep the change focused, preserve behavior unless an optimization is requested, "
        "and return a complete replacement for the selected file."
    )
    return {
        "plan": plan,
        "instruction": state.get("instruction") or request.task,
        "validation_status": state.get("validation_status") or "target_file_valid",
        "graph_path": f"{state.get('graph_path', '')}->generate_change_plan",
    }


def _generate_patch(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    selected_file = state.get("selected_file")
    if not selected_file:
        return {"error": "No target file selected."}
    try:
        proposal = propose_file_edit(
            AgentProposeFileRequest(
                project_path=request.project_path,
                relative_path=selected_file,
                instruction=f"{state.get('instruction')}\n\nChange plan:\n{state.get('plan')}",
            )
        )
    except (ValueError, RuntimeError) as exc:
        return {
            "error": str(exc),
            "graph_path": f"{state.get('graph_path', '')}->generate_patch",
        }
    return {
        "proposal": proposal,
        "graph_path": f"{state.get('graph_path', '')}->generate_patch",
    }


def _validate_patch(state: OrchestrationState) -> dict[str, Any]:
    proposal = state.get("proposal")
    if proposal is None:
        return {"error": state.get("error") or "No proposal was generated."}
    if proposal.relative_path != state.get("selected_file"):
        return {"error": "Proposal target did not match the selected file.", "validation_status": "invalid_proposal_target"}
    if proposal.original_content == proposal.proposed_content:
        return {"error": "Proposal did not change the selected file.", "validation_status": "invalid_empty_change"}
    if not proposal.proposed_content.strip():
        return {"error": "Proposal replacement content was empty.", "validation_status": "invalid_empty_replacement"}
    return {"validation_status": "valid_proposal", "graph_path": f"{state.get('graph_path', '')}->validate_patch"}


def _return_proposal(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    proposal = state["proposal"]
    result = _base_response(
        request,
        response=f"Proposed change to `{proposal.relative_path}`. Review the diff and apply if it looks correct.",
        response_type="change_proposal",
        files_read=[proposal.relative_path],
        proposal_relative_path=proposal.relative_path,
        proposal_original_content=proposal.original_content,
        proposal_proposed_content=proposal.proposed_content,
        proposal_context_summary=proposal.context_summary,
        selected_target_file=proposal.relative_path,
        intent_classification=state.get("intent"),
        graph_path="proposal",
        skills_used=state.get("skills_used", []),
        thread_context_files=state.get("thread_context", ThreadContext(request.project_path, request.branch)).recent_files,
        thread_context_symbols=state.get("thread_context", ThreadContext(request.project_path, request.branch)).symbol_names,
        context_source=state.get("context_source"),
        **_context_reference_debug(state),
        **_classifier_debug(state),
    ).model_copy(update={"model": proposal.model})
    return {"result": result, "graph_path": "proposal"}


def _proposal_error(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    error = state.get("error") or "RepoOperator could not produce a valid diff."
    result = _base_response(
        request,
        response="RepoOperator could not produce a valid diff. Try a more specific request.",
        response_type="proposal_error",
        selected_target_file=state.get("selected_file"),
        intent_classification=state.get("intent"),
        graph_path="proposal_error",
        proposal_error_details=error,
        skills_used=state.get("skills_used", []),
        thread_context_files=state.get("thread_context", ThreadContext(request.project_path, request.branch)).recent_files,
        thread_context_symbols=state.get("thread_context", ThreadContext(request.project_path, request.branch)).symbol_names,
        context_source=state.get("context_source"),
        **_classifier_debug(state),
    )
    return {"result": result, "graph_path": "proposal_error"}


def _answer_read_only(state: OrchestrationState) -> dict[str, Any]:
    from repooperator_worker.services.agent_graph import run_agent_graph

    request = state["request"]
    skills_context = state.get("skills_context") or ""
    if skills_context:
        request = request.model_copy(
            update={"task": f"{request.task}\n\nRelevant enabled skills:\n{skills_context}"}
        )

    result = run_agent_graph(request).model_copy(
        update={
            "intent_classification": state.get("intent") or "read_only_question",
            "graph_path": "read_only",
            "agent_flow": "langgraph",
            "skills_used": state.get("skills_used", []),
            "classifier": state.get("classifier") or "llm",
            "classifier_confidence": state.get("confidence"),
            "resolved_files": state.get("target_files") or [],
            "resolved_symbols": state.get("target_symbols") or [],
            "validation_status": state.get("validation_status") or "classified",
        }
    )
    return {"result": result, "graph_path": "read_only"}


def _run_local_tool_request(state: OrchestrationState) -> dict[str, Any]:
    import shutil

    request = state["request"]
    thread_context = state.get("thread_context") or ThreadContext(request.project_path, request.branch)
    tc_files = thread_context.recent_files
    tc_symbols = thread_context.symbol_names

    # Check glab availability first
    glab_path = shutil.which("glab")

    if not glab_path:
        # Suggest install with an approval card structure
        install_cmd, install_reason = _detect_glab_install_command()
        if install_cmd:
            from repooperator_worker.services.command_service import preview_command

            preview = preview_command(install_cmd, reason=install_reason)
            result_response = _base_response(
                request,
                response=(
                    "`glab` (the GitLab CLI) is needed to read merge request information from the active repository, "
                    "but it is not installed.\n\n"
                    f"Install command: `{' '.join(install_cmd)}`\n\n"
                    "Approve the installation below, or install it manually and retry."
                ),
                response_type="command_approval",
                command_approval=preview,
                intent_classification=state.get("intent"),
                graph_path="local_tool_request_install_prompt",
                thread_context_files=tc_files,
                thread_context_symbols=tc_symbols,
                context_source=state.get("context_source"),
                **_classifier_debug(state),
            )
        else:
            result_response = _base_response(
                request,
                response=(
                    "`glab` (the GitLab CLI) is needed to read merge request information, but it is not installed.\n\n"
                    "Install it manually:\n"
                    "- macOS: `brew install glab`\n"
                    "- Linux: `brew install glab` or `snap install glab`\n"
                    "- See: https://gitlab.com/gitlab-org/cli#installation\n\n"
                    "After installing, run `glab auth login` and retry."
                ),
                response_type="assistant_answer",
                intent_classification=state.get("intent"),
                graph_path="local_tool_request_missing_glab",
                thread_context_files=tc_files,
                thread_context_symbols=tc_symbols,
                context_source=state.get("context_source"),
                **_classifier_debug(state),
            )
        return {"result": result_response, "graph_path": "local_tool_request"}

    # glab is installed — check auth status
    try:
        import subprocess

        auth_check = subprocess.run(
            ["glab", "auth", "status"],
            cwd=_get_repo_cwd(request),
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
        if auth_check.returncode != 0:
            result_response = _base_response(
                request,
                response=(
                    "`glab` is installed but not authenticated with GitLab.\n\n"
                    "Run:\n```\nglab auth login\n```\n"
                    "or set `GITLAB_TOKEN` / `GLAB_TOKEN` environment variable and restart the worker.\n\n"
                    f"Auth status output:\n```\n{(auth_check.stderr or auth_check.stdout or '').strip()[:800]}\n```"
                ),
                response_type="assistant_answer",
                intent_classification=state.get("intent"),
                graph_path="local_tool_request_auth_required",
                thread_context_files=tc_files,
                thread_context_symbols=tc_symbols,
                context_source=state.get("context_source"),
                **_classifier_debug(state),
            )
            return {"result": result_response, "graph_path": "local_tool_request"}
    except (OSError, subprocess.TimeoutExpired):
        pass

    # glab authenticated — run mr list
    try:
        from repooperator_worker.services.tool_service import run_tool

        result = run_tool(["glab", "mr", "list"])
        if result.get("returncode") == 0:
            output = result.get("stdout", "").strip() or "No open merge requests found."
            response = "GitLab merge requests for the active repository:\n\n```text\n" + output + "\n```"
            status = "assistant_answer"
        else:
            err = (result.get("stderr") or result.get("stdout") or "No output").strip()
            response = (
                "I could not list merge requests with `glab mr list`.\n\n"
                f"```text\n{err[:1000]}\n```\n\n"
                "Check that you are in a GitLab repository and `glab` is authenticated."
            )
            status = "assistant_answer"
    except (ValueError, RuntimeError) as exc:
        response = f"Could not run `glab mr list`: {exc}"
        status = "assistant_answer"

    result_response = _base_response(
        request,
        response=response,
        response_type=status,
        intent_classification=state.get("intent"),
        graph_path="local_tool_request",
        skills_used=state.get("skills_used", []),
        thread_context_files=tc_files,
        thread_context_symbols=tc_symbols,
        context_source=state.get("context_source"),
        **_classifier_debug(state),
    )
    return {"result": result_response, "graph_path": "local_tool_request"}


def _detect_glab_install_command() -> tuple[list[str], str]:
    """Return (install_argv, reason) for the best available package manager, or ([], '') if none found."""
    import shutil

    if shutil.which("brew"):
        return ["brew", "install", "glab"], "Install the GitLab CLI using Homebrew. This uses the network."
    if shutil.which("snap"):
        return ["snap", "install", "glab"], "Install the GitLab CLI using snap. This uses the network."
    return [], ""


def _get_repo_cwd(request: AgentRunRequest) -> str | None:
    try:
        return str(resolve_project_path(request.project_path))
    except Exception:
        return None


def _run_local_command_request(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    from repooperator_worker.services.command_service import preview_command, run_command_with_policy

    command, reason = _command_for_classification(state)
    preview = preview_command(command, reason=reason)
    if preview.get("blocked"):
        result = _base_response(
            request,
            response=f"I will not run `{preview.get('display_command')}`. {preview.get('reason')}",
            response_type="command_denied",
            command_approval=preview,
            intent_classification=state.get("intent"),
            graph_path="command_denied",
            context_source=state.get("context_source"),
            **_classifier_debug(state),
        )
        return {"result": result, "graph_path": "command_denied"}
    if preview.get("needs_approval"):
        result = _base_response(
            request,
            response="RepoOperator needs your approval before running this local command.",
            response_type="command_approval",
            command_approval=preview,
            intent_classification=state.get("intent"),
            graph_path="command_approval",
            context_source=state.get("context_source"),
            **_classifier_debug(state),
        )
        return {"result": result, "graph_path": "command_approval"}
    try:
        command_result = run_command_with_policy(command, approval_id=preview.get("approval_id"))
        response = (
            f"Ran `{command_result.get('display_command')}` in `{command_result.get('cwd')}` "
            f"and exited with {command_result.get('exit_code')}."
        )
        result = _base_response(
            request,
            response=response,
            response_type="command_result",
            command_result=command_result,
            intent_classification=state.get("intent"),
            graph_path="command_result",
            context_source=state.get("context_source"),
            **_classifier_debug(state),
        )
        return {"result": result, "graph_path": "command_result"}
    except (ValueError, RuntimeError, PermissionError) as exc:
        result = _base_response(
            request,
            response=f"RepoOperator could not run the command: {exc}",
            response_type="command_error",
            command_approval=preview,
            intent_classification=state.get("intent"),
            graph_path="command_error",
            context_source=state.get("context_source"),
            **_classifier_debug(state),
        )
        return {"result": result, "graph_path": "command_error"}


def _resolve_context_reference(state: OrchestrationState) -> dict[str, Any]:
    """LLM-based context reference resolution node.

    Determines what file/symbol/proposal the user's message refers to and
    populates pending.selected_file when resolution is confident.
    Runs only for write-intent paths where an explicit file was not supplied.
    """
    from repooperator_worker.services.context_reference_service import resolve_context_reference

    request = state["request"]
    thread_context: ThreadContext = state.get("thread_context") or ThreadContext(
        request.project_path, request.branch
    )
    pending = state.get("pending") or {}

    history = [
        {"role": m.role, "content": m.content}
        for m in (request.conversation_history or [])
    ]

    suggestion_summary = pending.get("suggestion")
    if suggestion_summary and len(suggestion_summary) > 300:
        suggestion_summary = suggestion_summary[:297] + "..."

    ref_result = resolve_context_reference(
        task=request.task,
        conversation_history=history,
        project_path=request.project_path,
        recent_files=thread_context.recent_files,
        last_analyzed_file=thread_context.last_analyzed_file,
        symbols=thread_context.symbols,
        suggestion_summary=suggestion_summary,
        proposal_file=pending.get("proposal_file"),
        candidate_files=pending.get("candidates", []),
    )

    updates: dict[str, Any] = {
        "context_reference": ref_result,
        "context_source": ref_result.resolver,
        "graph_path": f"{state.get('graph_path', '')}->resolve_context_reference",
    }

    if ref_result.refers_to_previous_context and ref_result.target_files:
        updated_pending = dict(pending)
        if not updated_pending.get("selected_file"):
            updated_pending["selected_file"] = ref_result.target_files[0]
        updates["pending"] = updated_pending
    elif ref_result.needs_clarification:
        candidates = ref_result.target_files or pending.get("candidates") or thread_context.recent_files
        if candidates:
            updates["candidates"] = list(candidates[:8])

    return updates


def _after_classify(state: OrchestrationState) -> str:
    intent = state.get("intent")
    if intent == "read_only_question":
        return "answer_read_only"
    if intent == "gitlab_mr_request":
        return "run_local_tool_request"
    if intent in {"local_command_request", "git_workflow_request"}:
        return "run_local_command_request"
    if intent in {"repo_analysis", "recommend_change_targets"}:
        return "recommend_change_targets"
    if state.get("settings").write_mode not in {
        WRITE_MODE_WRITE_WITH_APPROVAL,
        WRITE_MODE_AUTO_APPLY,
    }:
        return "permission_required"
    # File clarification answers already have candidates set — skip context ref resolution
    if intent == "file_clarification_answer":
        return "resolve_target_files"
    # All write intents go through LLM context reference resolution first
    return "resolve_context_reference"


def _after_resolve(state: OrchestrationState) -> str:
    if state.get("result") is not None:
        return END
    if state.get("selected_file"):
        return "generate_change_plan"
    return "ask_clarification"


def _after_validate(state: OrchestrationState) -> str:
    return "proposal_error" if state.get("error") else "return_proposal"


def _build_graph():
    graph = StateGraph(OrchestrationState)
    graph.add_node("load_context", _load_context)
    graph.add_node("validate_active_repository", _validate_active_repository_context)
    graph.add_node("classify_intent", _classify_intent)
    graph.add_node("resolve_context_reference", _resolve_context_reference)
    graph.add_node("resolve_target_files", _resolve_target_files)
    graph.add_node("ask_clarification", _ask_clarification)
    graph.add_node("recommend_change_targets", _recommend_change_targets)
    graph.add_node("generate_change_plan", _generate_change_plan)
    graph.add_node("generate_patch", _generate_patch)
    graph.add_node("validate_patch", _validate_patch)
    graph.add_node("return_proposal", _return_proposal)
    graph.add_node("permission_required", _permission_required)
    graph.add_node("proposal_error", _proposal_error)
    graph.add_node("answer_read_only", _answer_read_only)
    graph.add_node("run_local_tool_request", _run_local_tool_request)
    graph.add_node("run_local_command_request", _run_local_command_request)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "validate_active_repository")
    graph.add_edge("validate_active_repository", "classify_intent")
    graph.add_conditional_edges("classify_intent", _after_classify)
    graph.add_edge("resolve_context_reference", "resolve_target_files")
    graph.add_conditional_edges("resolve_target_files", _after_resolve)
    graph.add_edge("ask_clarification", END)
    graph.add_edge("recommend_change_targets", END)
    graph.add_edge("generate_change_plan", "generate_patch")
    graph.add_edge("generate_patch", "validate_patch")
    graph.add_conditional_edges("validate_patch", _after_validate)
    graph.add_edge("return_proposal", END)
    graph.add_edge("permission_required", END)
    graph.add_edge("proposal_error", END)
    graph.add_edge("answer_read_only", END)
    graph.add_edge("run_local_tool_request", END)
    graph.add_edge("run_local_command_request", END)
    return graph


_COMPILED_GRAPH = _build_graph().compile()


def run_agent_orchestration_graph(request: AgentRunRequest) -> AgentRunResponse:
    final_state = _COMPILED_GRAPH.invoke({"request": request})
    result = final_state.get("result")
    if result is None:
        raise RuntimeError("Agent orchestration graph did not produce a result.")
    return result


def _node_progress_message(node_name: str, node_state: dict[str, Any]) -> str | None:
    if node_name == "load_context":
        return "Loading repository context"
    if node_name == "validate_active_repository":
        return "Validating active repository"
    if node_name == "classify_intent":
        intent = node_state.get("intent", "")
        return f"Intent: {intent.replace('_', ' ')}" if intent else "Classifying intent"
    if node_name == "resolve_context_reference":
        ref = node_state.get("context_reference")
        if ref and getattr(ref, "refers_to_previous_context", False):
            files = getattr(ref, "target_files", [])
            return f"Reference resolved: {files[0]}" if files else "Context reference resolved"
        return "Resolving context reference"
    if node_name == "resolve_target_files":
        selected = node_state.get("selected_file")
        return f"Target: {selected}" if selected else "Resolving target file"
    if node_name == "generate_change_plan":
        return "Planning changes"
    if node_name == "generate_patch":
        return "Generating diff"
    if node_name == "validate_patch":
        return "Validating"
    if node_name == "return_proposal":
        return "Proposal ready"
    if node_name == "answer_read_only":
        return "Generating answer"
    if node_name == "ask_clarification":
        return "Asking for clarification"
    if node_name == "recommend_change_targets":
        return "Identifying change targets"
    if node_name == "run_local_tool_request":
        return "Running GitLab tool"
    if node_name == "run_local_command_request":
        return "Running command"
    if node_name == "permission_required":
        return "Checking permissions"
    if node_name == "proposal_error":
        return "Proposal failed"
    return None


def stream_agent_orchestration_graph(request: AgentRunRequest):
    """Generator that yields JSON-encoded SSE event payloads for LangGraph progress."""
    initial_state: dict[str, Any] = {"request": request}
    accumulated_result: AgentRunResponse | None = None

    try:
        for update in _COMPILED_GRAPH.stream(initial_state, stream_mode="updates"):
            node_name = next(iter(update)) if update else None
            if not node_name:
                continue
            node_state: dict[str, Any] = update.get(node_name) or {}

            if "result" in node_state and node_state["result"] is not None:
                accumulated_result = node_state["result"]

            message = _node_progress_message(node_name, node_state)
            if message:
                yield json.dumps({"type": "progress", "node": node_name, "message": message})

    except Exception as exc:
        logger.exception("Streaming graph error: %s", exc)
        yield json.dumps({"type": "error", "message": str(exc)})
        return

    if accumulated_result is not None:
        yield json.dumps({"type": "done", "result": accumulated_result.model_dump()})
    else:
        yield json.dumps({"type": "error", "message": "Agent did not produce a result."})


def _command_for_classification(state: OrchestrationState) -> tuple[list[str], str]:
    """Plan a deterministic command only after LLM intent classification."""
    action = str(state.get("requested_action") or "").strip().lower()
    tool = str(state.get("needs_tool") or "").strip().lower()

    if tool == "npm" or "install_dependencies" in action or action == "npm_install":
        return ["npm", "install"], "Install project dependencies. This may modify files and use the network."
    if tool == "pip" or action == "pip_install":
        return ["pip", "install"], "Install Python dependencies. This may modify the environment and use the network."
    if "delete_recursive" in action:
        return ["rm", "-rf", "/tmp/something"], "Delete files recursively. This is destructive."
    if "push" in action:
        return ["git", "push"], "Push commits to the configured remote. This requires explicit approval."
    if "commit" in action:
        return ["git", "status", "--short"], (
            "Check which files are staged or modified before preparing a commit. "
            "RepoOperator will propose the commit steps after reviewing status."
        )
    if "diff" in action:
        return ["git", "diff", "--stat"], "Show a summary of file changes in the working tree."
    if "log" in action:
        return ["git", "log", "--oneline", "-10"], "Show the last 10 commit log entries."
    if "branch" in action:
        return ["git", "branch", "--show-current"], "Show the currently checked-out branch."
    return ["git", "status", "--short"], "Check the current repository working tree status."


def _extract_file_hints(text: str) -> list[str]:
    hints: list[str] = []
    for raw in FILE_TOKEN_RE.findall(text):
        token = raw.strip(".,:;()[]{}<>`'\"")
        if not token or token.startswith("http"):
            continue
        path = Path(token)
        lower_name = path.name.lower()
        if (
            path.suffix.lower() in SUPPORTED_SUFFIXES
            or "dockerfile" in lower_name
            or "dockfile" in lower_name
            or "/" in token
            or "\\" in token
        ):
            if token not in hints:
                hints.append(token.replace("\\", "/"))
    return hints


def _matches_pending_candidate(text: str, candidates: list[str]) -> bool:
    return _select_from_candidates(text, candidates) is not None


def _select_from_candidates(text: str, candidates: list[str]) -> str | None:
    hints = _extract_file_hints(text)
    lowered = text.lower()
    for candidate in candidates:
        if candidate.lower() in lowered:
            return candidate
    for hint in hints:
        hint_name = Path(hint).name.lower()
        exact = [c for c in candidates if c == hint or Path(c).name.lower() == hint_name]
        if len(exact) == 1:
            return exact[0]
        root_matches = [c for c in exact if "/" not in c]
        if len(root_matches) == 1:
            return root_matches[0]
    return None


def _resolve_file_hints(project_path: str, hints: list[str]) -> tuple[str | None, list[str]]:
    if not hints:
        return None, []
    repo_path = resolve_project_path(project_path)
    files = _list_supported_files(repo_path)
    for hint in hints:
        selected, candidates = _resolve_one_hint(repo_path, files, hint)
        if selected or candidates:
            return selected, candidates
    closest = _closest_files(repo_path, files, hints[0])
    return None, closest


def _list_supported_files(repo_path: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_path).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        name = path.name.lower()
        if path.suffix.lower() in SUPPORTED_SUFFIXES or "dockerfile" in name or "." not in path.name:
            files.append(path)
    files.sort(key=lambda p: (len(p.relative_to(repo_path).parts), str(p.relative_to(repo_path)).lower()))
    return files


def _resolve_one_hint(repo_path: Path, files: list[Path], hint: str) -> tuple[str | None, list[str]]:
    normalized_hint = hint.strip("/").lower()
    if "/" in normalized_hint:
        exact_rel = [p for p in files if str(p.relative_to(repo_path)).replace("\\", "/").lower() == normalized_hint]
        if len(exact_rel) == 1:
            return str(exact_rel[0].relative_to(repo_path)), []
    hint_name = Path(hint).name.lower()
    exact_name = [p for p in files if p.name == Path(hint).name]
    if len(exact_name) == 1:
        return str(exact_name[0].relative_to(repo_path)), []
    if len(exact_name) > 1:
        return None, [str(p.relative_to(repo_path)) for p in exact_name[:8]]
    ci_name = [p for p in files if p.name.lower() == hint_name]
    if len(ci_name) == 1:
        return str(ci_name[0].relative_to(repo_path)), []
    if len(ci_name) > 1:
        return None, [str(p.relative_to(repo_path)) for p in ci_name[:8]]
    fuzzy = _closest_files(repo_path, files, hint_name)
    if len(fuzzy) == 1:
        return fuzzy[0], []
    return None, fuzzy


def _closest_files(repo_path: Path, files: list[Path], hint: str) -> list[str]:
    scored: list[tuple[int, Path]] = []
    hint_name = Path(hint).name.lower()
    for path in files:
        name = path.name.lower()
        distance = _levenshtein(hint_name, name)
        if hint_name in name or name in hint_name:
            distance = min(distance, 1)
        if distance <= max(2, len(hint_name) // 4):
            scored.append((distance, path))
    scored.sort(key=lambda item: (item[0], len(item[1].parts), str(item[1]).lower()))
    return [str(path.relative_to(repo_path)) for _, path in scored[:5]]


def _recommend_candidate_files(repo_path: Path) -> list[tuple[str, str]]:
    files = _list_supported_files(repo_path)
    recommendations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in files:
        rel = str(path.relative_to(repo_path))
        if rel in seen:
            continue
        seen.add(rel)
        name = path.name.lower()
        reason: str | None = None
        if name in {"readme.md", "package.json", "pyproject.toml", "docker-compose.yml", "docker-compose.yaml"}:
            reason = "top-level project configuration or documentation"
        elif "dockerfile" in name:
            reason = "container build/runtime configuration"
        elif path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            reason = "source file likely to contain application behavior"
        elif path.suffix.lower() in {".yml", ".yaml", ".toml", ".json"}:
            reason = "configuration file that often affects runtime behavior"
        elif path.suffix.lower() == ".md":
            reason = "documentation that may need product or setup updates"
        if reason:
            recommendations.append((rel, reason))
    recommendations.sort(
        key=lambda item: (
            0 if "/" not in item[0] else 1,
            0 if Path(item[0]).name.lower() in {"readme.md", "package.json", "pyproject.toml"} else 1,
            item[0].lower(),
        )
    )
    return recommendations[:12]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _classify_with_llm(
    state: OrchestrationState,
    file_hints: list[str],
) -> dict[str, Any] | None:
    request = state["request"]
    pending = state.get("pending", {})
    thread_context: ThreadContext = state.get("thread_context") or ThreadContext(
        request.project_path,
        request.branch,
    )
    recent_messages = [
        {"role": message.role, "content": message.content[:500]}
        for message in request.conversation_history[-8:]
        if message.role in {"user", "assistant"}
    ]
    classifier_hints = {
        "file_hints": file_hints,
        "has_pending_candidates": bool(pending.get("candidates")),
        "has_pending_proposal": bool(pending.get("proposal_file")),
        "recent_files_count": len(thread_context.recent_files),
        "recent_symbols_count": len(thread_context.symbols),
    }
    try:
        client = OpenAICompatibleModelClient()
        text = client.generate_text(
            ModelGenerationRequest(
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                user_prompt=json.dumps(
                    {
                        "message": request.task,
                        "active_repo": request.project_path,
                        "active_branch": request.branch,
                        "recent_messages": recent_messages,
                        "last_analyzed_file": thread_context.last_analyzed_file,
                        "recent_files": thread_context.recent_files[:8],
                        "mentioned_symbols": thread_context.symbol_names[:12],
                        "pending_candidates": pending.get("candidates", []),
                        "pending_proposal": pending.get("proposal_file"),
                        "pending_selected_file": pending.get("selected_file"),
                        "pending_suggestion": (pending.get("suggestion") or "")[:500],
                        "classifier_hints": classifier_hints,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        payload = _parse_classifier_json(text)
        if payload and _normalize_intent(payload.get("intent")) in SUPPORTED_INTENTS:
            payload["classifier"] = "llm"
            return payload
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM intent classification unavailable; using deterministic fallback hints: %r", exc)
    return None


def _parse_classifier_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    try:
        payload = json.loads(cleaned)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None


def _normalize_intent(value: Any) -> Intent:
    intent = str(value or "ambiguous").strip()
    if intent == "local_tool_request":
        return "gitlab_mr_request"
    if intent in SUPPORTED_INTENTS:
        return intent  # type: ignore[return-value]
    return "ambiguous"


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _validate_classifier_files(project_path: str, files: list[str]) -> list[str]:
    if not files:
        return []
    try:
        repo_path = resolve_project_path(project_path).resolve()
    except (OSError, ValueError):
        return []
    valid: list[str] = []
    for item in files:
        if not item:
            continue
        candidate = (repo_path / item.lstrip("/")).resolve()
        try:
            candidate.relative_to(repo_path)
        except ValueError:
            continue
        if candidate.is_file():
            relative = str(candidate.relative_to(repo_path))
            if relative not in valid:
                valid.append(relative)
    return valid


def _fallback_classification(state: OrchestrationState, file_hints: list[str]) -> dict[str, Any]:
    """Low-priority fallback used only when the configured model is unavailable."""
    request = state["request"]
    pending = state.get("pending", {})
    lowered = request.task.lower()
    if pending.get("candidates") and _matches_pending_candidate(request.task, pending["candidates"]):
        return _classification_payload(
            intent="file_clarification_answer",
            confidence=0.7,
            requested_action="select_candidate",
            classifier="deterministic_fallback",
        )
    if file_hints:
        return _classification_payload(
            intent="write_request",
            confidence=0.55,
            target_files=file_hints,
            requested_action="edit_file",
            classifier="deterministic_fallback",
        )
    if "mr" in lowered or "merge request" in lowered:
        return _classification_payload(
            intent="gitlab_mr_request",
            confidence=0.55,
            requested_action="list_merge_requests",
            needs_tool="glab",
            classifier="deterministic_fallback",
        )
    return _classification_payload(
        intent="read_only_question",
        confidence=0.4,
        requested_action="answer",
        classifier="deterministic_fallback",
    )


def _classification_payload(
    *,
    intent: str,
    confidence: float,
    target_files: list[str] | None = None,
    target_symbols: list[str] | None = None,
    requested_action: str,
    needs_tool: str | None = None,
    classifier: str,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "confidence": confidence,
        "target_files": target_files or [],
        "target_symbols": target_symbols or [],
        "requested_action": requested_action,
        "needs_tool": needs_tool,
        "needs_clarification": False,
        "clarification_question": None,
        "classifier": classifier,
    }


def _find_previous_write_instruction(request: AgentRunRequest) -> str | None:
    for message in reversed(request.conversation_history):
        if message.role == "user":
            return message.content
    return None
