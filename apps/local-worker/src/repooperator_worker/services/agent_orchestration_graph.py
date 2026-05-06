"""LangGraph orchestration for repository answers, proposals, and tool plans."""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from repooperator_worker.config import get_settings
from repooperator_worker.schemas import (
    AgentProposeFileRequest,
    AgentRunRequest,
    AgentRunResponse,
    FileWriteRequest,
)
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.context_service import build_query_aware_context
from repooperator_worker.services.edit_service import propose_file_edit
from repooperator_worker.services.file_service import write_text_file
from repooperator_worker.services.event_service import append_run_event
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)
from repooperator_worker.services.response_quality_service import (
    clean_user_visible_response,
    language_guidance_for_task,
    user_prefers_korean,
)
from repooperator_worker.services.recommendation_context_service import (
    build_recommendation_context,
    recommendation_context_from_history,
    resolve_recommendation_followup,
    selected_recommendation_items,
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
    "review_recommendation",
    "write_request",
    "write_confirmation",
    "file_clarification_answer",
    "local_command_request",
    "git_workflow_request",
    "gitlab_mr_request",
    "multi_step_request",
    "pasted_prompt_or_spec",
    "apply_spec_to_repo",
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

REPOSITORY_REVIEW_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".swift",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".properties",
    ".gradle",
    ".md",
    ".rst",
    ".txt",
    ".html",
    ".css",
}

REPOSITORY_REVIEW_FILENAMES = {
    "dockerfile",
    "makefile",
    "requirements.txt",
    "requirements.in",
    "pyproject.toml",
    "package.json",
    "readme",
    "readme.md",
}

REPOSITORY_REVIEW_BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".rar",
    ".mp3",
    ".mp4",
    ".mov",
    ".wav",
    ".onnx",
    ".pt",
    ".pth",
    ".bin",
    ".sqlite",
    ".db",
    ".pyc",
}

REPOSITORY_REVIEW_EXTRA_SKIP_DIRS = {
    ".git",
    ".claude",
    "node_modules",
    "runtime",
    ".next",
    "dist",
    "build",
    "out",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
}

MAX_REPOSITORY_REVIEW_FILES = 12
MAX_REPOSITORY_REVIEW_BYTES = 120_000
MAX_REPOSITORY_REVIEW_PROMPT_CHARS = 22_000
SMALL_REVIEW_RETRY_CHARS = 12_000

FILE_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+")

SUPPORTED_INTENTS: set[str] = {
    "read_only_question",
    "repo_analysis",
    "recommend_change_targets",
    "review_recommendation",
    "write_request",
    "write_confirmation",
    "file_clarification_answer",
    "local_command_request",
    "git_workflow_request",
    "gitlab_mr_request",
    "multi_step_request",
    "pasted_prompt_or_spec",
    "apply_spec_to_repo",
    "ambiguous",
}

CLASSIFIER_SYSTEM_PROMPT = """\
You are RepoOperator's intent classifier. Decide what the user is asking the
repository agent to do. Return JSON only; do not include markdown or prose.

Schema:
{
  "intent": "read_only_question|repo_analysis|recommend_change_targets|review_recommendation|write_request|write_confirmation|file_clarification_answer|local_command_request|git_workflow_request|gitlab_mr_request|multi_step_request|pasted_prompt_or_spec|apply_spec_to_repo|ambiguous",
  "confidence": 0.0,
  "analysis_scope": "single_file|selected_files|repository_wide|unknown",
  "requested_workflow": "repository_review|file_review|code_change|git_workflow|command|other",
  "requires_repository_wide_review": false,
  "target_files": [],
  "target_symbols": [],
  "requested_action": "short action summary",
  "git_action": "git_status|git_recent_commit|git_commit_plan|git_push_plan|git_mr_create_plan|null",
  "needs_tool": null,
  "needs_clarification": false,
  "clarification_question": null
}

Intent guidance:
- read_only_question: answer or explain code without changing files or running local commands.
- repo_analysis: inspect the repository structure and explain architecture or health.
- recommend_change_targets: recommend concrete files to inspect or improve; do not require a file first.
- review_recommendation: review a file, symbol, or recent context and list concrete improvement suggestions without preparing a diff.
- write_request: user asks for a code/file change or a change proposal (single file).
- write_confirmation: user confirms a previous suggestion/proposal should be applied or prepared.
- file_clarification_answer: user chooses from previously offered candidate files.
- local_command_request: user asks to run a local command such as git status, npm install, or shell command.
- git_workflow_request: user asks to commit, push, inspect branch/status/diff/log, or otherwise perform git workflow steps.
- gitlab_mr_request: user asks about GitLab merge requests, pipelines, or MR creation.
- multi_step_request: user asks to perform 2 or more sequential operations (e.g. analyze A, analyze B, then update C; or modify file X and also fix file Y).
- pasted_prompt_or_spec: user pasted a structured prompt, external task spec, implementation plan, or instructions and has not clearly asked to apply it to the active repository.
- apply_spec_to_repo: user explicitly asks RepoOperator to apply a pasted/specification-style task to the active repository.
- ambiguous: there is not enough context to safely decide.

Use recent thread context, pending candidates, and pending proposals. Korean and
English requests are both expected. Do not expose hidden reasoning.

Important distinctions:
- Requests for improvement advice or review points are review_recommendation, not edits.
- Decide whether analysis scope is a single file, selected files, the whole repository, or unknown.
- Set requested_workflow to repository_review when the user wants whole-repository or file-by-file repository review.
- Set requires_repository_wide_review to true only when the repository-wide map/reduce review workflow is appropriate.
- Use file_review for selected-file review, code_change for edits, git_workflow for Git actions, command for local commands, and other when none apply.
- Requests to make or apply changes are write_request or write_confirmation depending on prior context.
- Requests about commit history are git_workflow_request with git_action "git_recent_commit".
- Requests to create a local commit from current changes are git_workflow_request with git_action "git_commit_plan".
- Long structured instructions that look like a prompt for another agent are pasted_prompt_or_spec unless the user explicitly asks to apply them to this repository.
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
    analysis_scope: str | None
    requested_workflow: str | None
    requires_repository_wide_review: bool
    file_hints: list[str]
    target_files: list[str]
    target_symbols: list[str]
    requested_action: str | None
    needs_tool: str | None
    git_action: str | None
    commands_planned: list[str]
    commands_run: list[str]
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
    recommendation_context: dict[str, Any] | None
    recommendation_resolution: dict[str, Any] | None
    pasted_prompt_or_spec: bool
    apply_spec_to_repo: bool
    plan_step_events: list[dict]  # SSE events emitted during multi-step execution
    activity_events: list[dict[str, Any]]
    loop_iteration: int
    stop_reason: str | None
    run_id: str


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
        diff_included=response_type in {"change_proposal", "edit_applied"},
        is_git_repository=True,
        files_read=files_read or [],
        response=response,
        response_type=response_type,
        agent_flow="langgraph",
        effective_worker_model=model_name,
        configured_model=settings.configured_model_name,
        **extra,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line_delta_counts(original: str, proposed: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in unified_diff(
        (original or "").splitlines(),
        (proposed or "").splitlines(),
        lineterm="",
    ):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _edit_archive_record(
    *,
    file_path: str,
    status: str,
    original: str,
    proposed: str,
    summary: str | None = None,
    proposal_id: str | None = None,
    plan_id: str | None = None,
    apply_result: str | None = None,
    tests: list[str] | None = None,
) -> dict[str, Any]:
    additions, deletions = _line_delta_counts(original, proposed)
    diff = "\n".join(
        unified_diff(
            (original or "").splitlines(),
            (proposed or "").splitlines(),
            fromfile=file_path,
            tofile=file_path,
            lineterm="",
        )
    )
    return {
        "file_path": file_path,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "diff": diff,
        "summary": summary or "Prepared a reviewed file change.",
        "timestamp": _utc_now(),
        "proposal_id": proposal_id or f"proposal-{uuid.uuid4().hex[:10]}",
        "plan_id": plan_id,
        "apply_result": apply_result,
        "tests": tests or [],
    }


def _activity_event(
    *,
    run_id: str,
    phase: str,
    label: str,
    detail: str = "",
    status: str = "completed",
    elapsed_ms: int | None = None,
    duration_ms: int | None = None,
    files: list[str] | None = None,
    command: str | None = None,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "type": "progress_delta",
        "id": f"activity-{uuid.uuid4().hex[:10]}",
        "run_id": run_id,
        "phase": phase,
        "label": label,
        "detail": detail,
        "status": status,
        "started_at": now,
        "ended_at": now if status in {"completed", "failed", "waiting"} else None,
        "duration_ms": elapsed_ms,
        "elapsed_ms": elapsed_ms,
        "files": files or [],
        "command": command,
        "proposal_id": proposal_id,
    }


def _append_activity_event(
    *,
    request: AgentRunRequest,
    run_id: str,
    phase: str,
    label: str,
    event_type: str,
    detail: str = "",
    status: str = "completed",
    elapsed_ms: int | None = None,
    duration_ms: int | None = None,
    files: list[str] | None = None,
    command: str | None = None,
    proposal_id: str | None = None,
    activity_id: str | None = None,
    current_action: str | None = None,
    observation: str | None = None,
    next_action: str | None = None,
    detail_delta: str | None = None,
    observation_delta: str | None = None,
    next_action_delta: str | None = None,
    summary_delta: str | None = None,
    safe_reasoning_summary: str | None = None,
    related_search_query: str | None = None,
    aggregate: dict[str, Any] | None = None,
    started_at: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    event = _activity_event(
        run_id=run_id,
        phase=phase,
        label=label,
        detail=detail,
        status=status,
        elapsed_ms=elapsed_ms,
        files=files,
        command=command,
        proposal_id=proposal_id,
    )
    event.update(
        {
            "event_type": event_type,
            "activity_id": activity_id,
            "thread_id": request.thread_id,
            "repo": request.project_path,
            "branch": request.branch,
            "updated_at": _utc_now(),
        }
    )
    if started_at:
        event["started_at"] = started_at
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if current_action:
        event["current_action"] = current_action
    if observation:
        event["observation"] = observation
    if next_action:
        event["next_action"] = next_action
    if detail_delta:
        event["detail_delta"] = detail_delta
    if observation_delta:
        event["observation_delta"] = observation_delta
    if next_action_delta:
        event["next_action_delta"] = next_action_delta
    if summary_delta:
        event["summary_delta"] = summary_delta
    if safe_reasoning_summary:
        event["safe_reasoning_summary"] = safe_reasoning_summary
    if related_search_query:
        event["related_search_query"] = related_search_query
    if aggregate is not None:
        event["aggregate"] = aggregate
    stored = append_run_event(run_id, event)
    if events is not None:
        events.append(stored)
    return stored


def _finalize_activity_events(events: list[dict[str, Any]], *, status: str = "completed") -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    now = _utc_now()
    for event in events:
        if event.get("status") == "running":
            finalized.append({**event, "status": status, "ended_at": event.get("ended_at") or now})
        else:
            finalized.append(event)
    return finalized


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
    trace = {
        "classifier": state.get("classifier") or "llm",
        "classifier_confidence": state.get("confidence"),
        "resolved_files": resolved_files,
        "resolved_symbols": state.get("target_symbols") or [],
        "validation_status": state.get("validation_status") or "pending",
    }
    optional = {
        "git_action": state.get("git_action"),
        "commands_planned": state.get("commands_planned") or [],
        "commands_run": state.get("commands_run") or [],
        "analysis_scope": state.get("analysis_scope"),
        "requested_workflow": state.get("requested_workflow"),
        "requires_repository_wide_review": bool(state.get("requires_repository_wide_review")),
        "recommendation_context_loaded": bool(state.get("recommendation_context")),
        "selected_recommendation_ids": (
            state.get("recommendation_resolution", {}).get("selected_recommendation_ids", [])
            if isinstance(state.get("recommendation_resolution"), dict)
            else []
        ),
        "pasted_prompt_or_spec": bool(state.get("pasted_prompt_or_spec")),
        "apply_spec_to_repo": bool(state.get("apply_spec_to_repo")),
        "plan_id": state.get("plan_id"),
        "plan_steps": state.get("plan_steps") or [],
        "proposal_validation_status": state.get("proposal_validation_status"),
        "retry_count": state.get("retry_count") or 0,
    }
    for key, value in optional.items():
        if value not in (None, False, [], ""):
            trace[key] = value
    return trace


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
    recommendation_context = recommendation_context_from_history(request)

    return {
        "settings": get_settings(),
        "pending": pending,
        "instruction": request.task,
        "skills_context": skills_context,
        "skills_used": skills_used,
        "thread_context": thread_context,
        "context_source": "retrieval",
        "context_reference": None,
        "recommendation_context": recommendation_context,
        "recommendation_resolution": None,
        "pasted_prompt_or_spec": False,
        "apply_spec_to_repo": False,
        "analysis_scope": "unknown",
        "requested_workflow": "other",
        "requires_repository_wide_review": False,
        "classifier": "llm",
        "validation_status": "not_started",
        "graph_path": "load_context",
        "loop_iteration": 0,
        "stop_reason": None,
        "activity_events": [],
        "run_id": state.get("run_id") or f"run-{uuid.uuid4().hex[:12]}",
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

    analysis_scope = _normalize_analysis_scope(classification.get("analysis_scope"))
    requested_workflow = _normalize_requested_workflow(classification.get("requested_workflow"))
    requires_repository_wide_review = bool(classification.get("requires_repository_wide_review"))

    return {
        "intent": intent,
        "confidence": confidence,
        "intent_reason": str(classification.get("requested_action") or ""),
        "analysis_scope": analysis_scope,
        "requested_workflow": requested_workflow,
        "requires_repository_wide_review": requires_repository_wide_review,
        "file_hints": file_hints,
        "target_files": target_files,
        "target_symbols": target_symbols,
        "requested_action": classification.get("requested_action"),
        "needs_tool": classification.get("needs_tool"),
        "git_action": _normalize_git_action(classification.get("git_action") or classification.get("requested_action")),
        "pasted_prompt_or_spec": intent == "pasted_prompt_or_spec",
        "apply_spec_to_repo": intent == "apply_spec_to_repo",
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
        if state.get("target_files"):
            return {
                "selected_file": state["target_files"][0],
                "candidates": [],
                "instruction": _find_previous_write_instruction(request) or request.task,
                "validation_status": "target_file_valid",
                "graph_path": f"{state.get('graph_path', '')}->resolve_target_files",
            }
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
        recommendation_context=state.get("recommendation_context"),
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
    if _should_use_repository_wide_review(state):
        return _repository_wide_review(state)

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
                    "Return concise bullets with file paths and reasons. Do not claim to edit files. "
                    + language_guidance_for_task(request.task)
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
            response, _reasoning = clean_user_visible_response(model_response, user_task=request.task)
    except (ValueError, RuntimeError) as exc:
        logger.info("recommend_change_targets using deterministic fallback: %r", exc)

    recommendation_context = build_recommendation_context(
        request=request,
        files_read=context.files_read,
        response=response,
        candidate_files=candidate_files,
    )

    result = _base_response(
        request,
        response=response,
        response_type="assistant_answer",
        files_read=context.files_read,
        recommendation_context=recommendation_context,
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


def _handle_pasted_spec(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    is_apply = state.get("intent") == "apply_spec_to_repo" or bool(state.get("apply_spec_to_repo"))
    if is_apply:
        plan_steps = [
            "Summarize the pasted specification into implementation areas.",
            "Inspect likely repository files before choosing edit targets.",
            "Confirm the affected files and scope before generating proposals.",
            "Generate diff proposals only after target validation.",
        ]
        response = (
            "I can apply this specification to the current repository, but it is broad enough to plan first.\n\n"
            "Plan:\n"
            + "\n".join(f"{idx}. {step}" for idx, step in enumerate(plan_steps, start=1))
            + "\n\nConfirm the scope or name the area you want to start with, and I will inspect the repository before proposing edits."
        )
        result = _base_response(
            request,
            response=response,
            response_type="assistant_answer",
            intent_classification=state.get("intent"),
            graph_path="apply_spec_plan",
            plan_id="plan_" + uuid.uuid4().hex[:10],
            plan_steps=plan_steps,
            **_classifier_debug(state),
        )
        return {"result": result, "graph_path": "apply_spec_plan"}

    response = (
        "This looks like a pasted prompt, task specification, or implementation plan rather than a direct repository edit request.\n\n"
        "What would you like me to do with it?\n"
        "- Summarize it\n"
        "- Rewrite it for another tool\n"
        "- Convert it into a checklist\n"
        "- Save it as a routine or skill\n"
        "- Apply it to the current repository after a plan review"
    )
    result = _base_response(
        request,
        response=response,
        response_type="assistant_answer",
        intent_classification=state.get("intent"),
        graph_path="pasted_prompt_or_spec",
        **_classifier_debug(state),
    )
    return {"result": result, "graph_path": "pasted_prompt_or_spec"}


def _resolve_recommendation_followup(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    context = state.get("recommendation_context")
    if not context:
        return {"graph_path": f"{state.get('graph_path', '')}->resolve_recommendation_followup_none"}
    resolution = resolve_recommendation_followup(
        request=request,
        recommendation_context=context,
    )
    updates: dict[str, Any] = {
        "recommendation_resolution": resolution,
        "graph_path": f"{state.get('graph_path', '')}->resolve_recommendation_followup",
    }
    if not resolution.get("refers_to_previous_recommendation"):
        return updates
    selected_items = selected_recommendation_items(
        context,
        resolution.get("selected_recommendation_ids") or [],
        resolution.get("selected_files") or [],
    )
    selected_files = sorted({file for item in selected_items for file in item.get("files", [])})
    if resolution.get("needs_clarification") or len(selected_files) > 1:
        updates["candidates"] = selected_files or context.get("recommended_files", [])
        updates["needs_clarification"] = True
        updates["clarification_question"] = resolution.get("clarification_question") or (
            "The previous recommendations cover multiple files. Choose which file or recommendation to turn into a proposal first."
        )
        return updates
    if len(selected_files) == 1:
        updates["selected_file"] = selected_files[0]
        updates["instruction"] = _instruction_from_recommendations(request.task, selected_items)
        updates["validation_status"] = "recommendation_target_valid"
    return updates


def _instruction_from_recommendations(task: str, items: list[dict[str, Any]]) -> str:
    changes: list[str] = []
    for item in items:
        changes.extend(str(change) for change in item.get("suggested_changes") or [])
    return "\n".join([task, "", "Use the prior structured recommendations:", *[f"- {change}" for change in changes]])


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
    proposal_id = f"proposal-{uuid.uuid4().hex[:10]}"
    write_text_file(
        FileWriteRequest(
            project_path=request.project_path,
            relative_path=proposal.relative_path,
            content=proposal.proposed_content,
        )
    )
    edit_archive = [
        _edit_archive_record(
            file_path=proposal.relative_path,
            status="modified",
            original=proposal.original_content,
            proposed=proposal.proposed_content,
            summary=proposal.context_summary,
            proposal_id=proposal_id,
            plan_id=state.get("plan_id"),
            apply_result=f"Modified {proposal.relative_path}",
        )
    ]
    summary = _generate_edit_result_summary(request, state, edit_archive)
    result = _base_response(
        request,
        response=summary,
        response_type="edit_applied",
        files_read=[proposal.relative_path],
        proposal_relative_path=proposal.relative_path,
        proposal_original_content=proposal.original_content,
        proposal_proposed_content=proposal.proposed_content,
        proposal_context_summary=proposal.context_summary,
        selected_target_file=proposal.relative_path,
        edit_archive=edit_archive,
        recommendation_context=state.get("recommendation_context"),
        proposal_validation_status=state.get("validation_status"),
        intent_classification=state.get("intent"),
        graph_path="edit_applied",
        loop_iteration=state.get("loop_iteration", 1),
        stop_reason="completed",
        skills_used=state.get("skills_used", []),
        thread_context_files=state.get("thread_context", ThreadContext(request.project_path, request.branch)).recent_files,
        thread_context_symbols=state.get("thread_context", ThreadContext(request.project_path, request.branch)).symbol_names,
        context_source=state.get("context_source"),
        **_context_reference_debug(state),
        **_classifier_debug(state),
    ).model_copy(update={"model": proposal.model})
    return {"result": result, "graph_path": "edit_applied"}


def _generate_edit_result_summary(
    request: AgentRunRequest,
    state: OrchestrationState,
    edit_archive: list[dict[str, Any]],
) -> str:
    files = [record["file_path"] for record in edit_archive]
    stats = ", ".join(
        f"`{record['file_path']}` +{record['additions']} -{record['deletions']}"
        for record in edit_archive
    )
    plan = state.get("plan") or state.get("instruction") or request.task
    tests = _suggest_tests_for_changed_files(files)
    fallback = (
        f"Modified {', '.join(f'`{file}`' for file in files)}.\n\n"
        f"What changed: {stats}.\n\n"
        f"Why: {plan[:500]}\n\n"
        "RepoOperator has not committed, pushed, or created a merge request."
    )
    if tests:
        fallback += "\n\nSuggested verification:\n" + "\n".join(f"- `{test}`" for test in tests)
    try:
        response = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "You are RepoOperator. Write a concise post-edit summary for the user. "
                    "Mention what changed, why, changed files, behavior impact, and suggested verification. "
                    "State naturally that no commit, push, or MR was created. "
                    + language_guidance_for_task(request.task)
                ),
                user_prompt=json.dumps(
                    {
                        "user_request": request.task,
                        "plan": plan,
                        "edit_archive": edit_archive,
                        "suggested_tests": tests,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        cleaned, _ = clean_user_visible_response(response, user_task=request.task)
        return cleaned or fallback
    except (ValueError, RuntimeError):
        return fallback


def _suggest_tests_for_changed_files(files: list[str]) -> list[str]:
    if any(file.endswith(".py") for file in files):
        return ["python -m pytest"]
    if any(file.endswith((".ts", ".tsx", ".js", ".jsx")) for file in files):
        return ["npm test"]
    if any("dockerfile" in file.lower() or file.endswith((".yml", ".yaml")) for file in files):
        return ["git diff --stat"]
    return ["git diff --stat"]


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


def _should_use_repository_wide_review(state: OrchestrationState) -> bool:
    if state.get("target_files") or state.get("file_hints"):
        return False
    if state.get("requires_repository_wide_review") is True:
        return True
    if state.get("analysis_scope") == "repository_wide":
        return True
    if state.get("requested_workflow") == "repository_review":
        return True
    return False


def _activity_id(prefix: str, value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip()).strip("-")
    return f"{prefix}:{safe[:160] or uuid.uuid4().hex[:8]}"


def _repository_wide_review(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    run_id = str(state.get("run_id") or f"run-{uuid.uuid4().hex[:12]}")
    started = time.perf_counter()
    activity_events: list[dict[str, Any]] = []
    repo_path = resolve_project_path(request.project_path)

    _append_activity_event(
        request=request,
        run_id=run_id,
        phase="Thinking",
        label="Planned repository review",
        detail="I will inventory readable source, config, and docs files, review each selected file separately, then summarize only confirmed findings.",
        event_type="activity_completed",
        activity_id="repository-review-plan",
        elapsed_ms=0,
        current_action="Planning a bounded repository review.",
        observation="No files have been reviewed yet.",
        next_action="Inventory readable files and skip generated, binary, dependency, or oversized paths.",
        safe_reasoning_summary=(
            "Repository-wide review is split by file so a timeout in one file does not create unsupported conclusions."
        ),
        events=activity_events,
    )

    inventory = _inventory_repository_review_files(repo_path)
    selected = inventory["selected"]
    skipped = inventory["skipped"]
    _append_activity_event(
        request=request,
        run_id=run_id,
        phase="Searching",
        label="Listed repository files",
        detail=f"Selected {len(selected)} readable file(s) and skipped {len(skipped)} unsupported, generated, dependency, or large file(s).",
        event_type="activity_completed",
        activity_id="repository-inventory",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        current_action="Inventorying repository files.",
        observation=f"Selected {len(selected)} readable file(s); skipped {len(skipped)} file(s).",
        next_action="Review selected files one at a time.",
        related_search_query="repository inventory",
        aggregate={
            "files_selected": len(selected),
            "files_skipped": len(skipped),
            "searches_count": 1,
        },
        events=activity_events,
    )

    if selected:
        _append_activity_event(
            request=request,
            run_id=run_id,
            phase="Searching",
            label="Selected files for review",
            detail=", ".join(selected[:8]) + (" ..." if len(selected) > 8 else ""),
            event_type="activity_completed",
            activity_id="repository-file-selection",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            current_action="Choosing review targets.",
            observation="Readable source, config, and documentation files were selected within the run limit.",
            next_action=f"Start with `{selected[0]}`." if selected else None,
            files=selected[:8],
            events=activity_events,
        )

    reviewed: list[dict[str, Any]] = []
    timed_out: list[dict[str, Any]] = []
    read_failures: list[dict[str, Any]] = []
    client: OpenAICompatibleModelClient | None = None
    try:
        client = OpenAICompatibleModelClient()
    except (ValueError, RuntimeError) as exc:
        logger.info("Repository review model client unavailable: %r", exc)

    for relative_path in selected:
        file_started = time.perf_counter()
        file_started_at = _utc_now()
        file_activity_id = _activity_id("review-file", relative_path)
        file_title = Path(relative_path).name
        read_summary = _progress_summary_for_file(
            relative_path=relative_path,
            phase="reading",
        )
        _append_activity_event(
            request=request,
            run_id=run_id,
            phase="Reading files",
            label=file_title,
            detail=read_summary["detail"],
            event_type="activity_started",
            activity_id=file_activity_id,
            status="running",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            files=[relative_path],
            current_action=read_summary["current_action"],
            observation=read_summary["observation"],
            next_action=read_summary["next_action"],
            safe_reasoning_summary=read_summary["safe_reasoning_summary"],
            started_at=file_started_at,
            events=activity_events,
        )
        read_result = _read_review_file(repo_path, relative_path)
        read_elapsed = int((time.perf_counter() - file_started) * 1000)
        if read_result.get("error"):
            read_failures.append({"file": relative_path, "reason": read_result["error"]})
            failure_summary = _progress_summary_for_file(
                relative_path=relative_path,
                phase="failed",
                observation=str(read_result["error"]),
            )
            _append_activity_event(
                request=request,
                run_id=run_id,
                phase="Reading files",
                label=file_title,
                detail=failure_summary["detail"],
                event_type="activity_failed",
                activity_id=file_activity_id,
                status="failed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                duration_ms=int((time.perf_counter() - file_started) * 1000),
                files=[relative_path],
                current_action=failure_summary["current_action"],
                observation=failure_summary["observation"],
                next_action=failure_summary["next_action"],
                safe_reasoning_summary=failure_summary["safe_reasoning_summary"],
                started_at=file_started_at,
                events=activity_events,
            )
            continue
        content = str(read_result["content"])
        read_observation = _file_read_observation(relative_path, content, bool(read_result.get("truncated")))
        review_summary = _progress_summary_for_file(
            relative_path=relative_path,
            phase="reviewing",
            content_preview=content[:1400],
            observation=read_observation,
        )
        _append_activity_event(
            request=request,
            run_id=run_id,
            phase="Reviewing",
            label=file_title,
            detail=review_summary["detail"],
            detail_delta=" " + review_summary["detail"],
            event_type="activity_updated",
            activity_id=file_activity_id,
            status="running",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            duration_ms=None,
            files=[relative_path],
            current_action=review_summary["current_action"],
            observation=review_summary["observation"],
            observation_delta=" " + review_summary["observation"],
            next_action=review_summary["next_action"],
            next_action_delta=" " + review_summary["next_action"],
            safe_reasoning_summary=review_summary["safe_reasoning_summary"],
            summary_delta=" " + review_summary["safe_reasoning_summary"],
            started_at=file_started_at,
            aggregate={"duration_ms": read_elapsed},
            events=activity_events,
        )
        review_result = _review_single_file(
            request=request,
            relative_path=relative_path,
            content=content,
            truncated=bool(read_result.get("truncated")),
            client=client,
        )
        if review_result.get("timed_out"):
            timed_out.append(review_result)
            timeout_observation = f"Model review did not return within {review_result.get('elapsed_seconds')}s."
            _append_activity_event(
                request=request,
                run_id=run_id,
                phase="Reviewing",
                label=file_title,
                detail=(
                    f"Timed out after {review_result.get('elapsed_seconds')}s. "
                    "Marking this file as not reviewed and continuing with the next file."
                ),
                event_type="activity_failed",
                activity_id=file_activity_id,
                status="failed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                duration_ms=int((time.perf_counter() - file_started) * 1000),
                files=[relative_path],
                current_action="Skipping this file after timeout.",
                observation=timeout_observation,
                observation_delta=" " + timeout_observation,
                next_action="Continue with the remaining selected files.",
                next_action_delta=" Continue with the remaining selected files.",
                safe_reasoning_summary="Timed-out files stay out of confirmed findings.",
                started_at=file_started_at,
                events=activity_events,
            )
            continue
        reviewed.append(review_result)
        completed_observation = _truncate_for_event(str(review_result.get("summary") or "Completed file-level review."))
        completed_summary = _progress_summary_for_file(
            relative_path=relative_path,
            phase="completed",
            content_preview=content[:1400],
            observation=completed_observation,
        )
        _append_activity_event(
            request=request,
            run_id=run_id,
            phase="Reviewing",
            label=file_title,
            detail=completed_summary["detail"],
            detail_delta=" " + completed_summary["detail"],
            event_type="activity_completed",
            activity_id=file_activity_id,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            duration_ms=int((time.perf_counter() - file_started) * 1000),
            files=[relative_path],
            current_action=completed_summary["current_action"],
            observation=completed_summary["observation"],
            observation_delta=" " + completed_summary["observation"],
            next_action=completed_summary["next_action"],
            next_action_delta=" " + completed_summary["next_action"],
            safe_reasoning_summary=completed_summary["safe_reasoning_summary"],
            summary_delta=" " + completed_summary["safe_reasoning_summary"],
            started_at=file_started_at,
            events=activity_events,
        )

    counters = {
        "files_read_count": len(reviewed) + len(timed_out),
        "files_reviewed_count": len(reviewed),
        "files_skipped_count": len(skipped) + len(read_failures),
        "searches_count": 1,
        "timed_out_count": len(timed_out),
        "commands_count": 0,
        "edits_count": 0,
    }
    _append_activity_event(
        request=request,
        run_id=run_id,
        phase="Searching",
        label=f"Explored {counters['files_read_count']} files, searched {counters['searches_count']} time",
        detail=(
            f"Reviewed {counters['files_reviewed_count']} file(s), "
            f"timed out on {counters['timed_out_count']} file(s), "
            f"and skipped {counters['files_skipped_count']} file(s)."
        ),
        event_type="activity_completed",
        activity_id="repository-review-aggregate",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        current_action="Aggregating completed file reviews.",
        observation=(
            f"Reviewed {counters['files_reviewed_count']} file(s), "
            f"timed out on {counters['timed_out_count']} file(s), "
            f"and skipped {counters['files_skipped_count']} file(s)."
        ),
        next_action="Prepare the final answer from completed evidence only.",
        aggregate=counters,
        events=activity_events,
    )

    response = _format_repository_review_response(
        request=request,
        selected_files=selected,
        reviewed=reviewed,
        timed_out=timed_out,
        skipped=skipped,
        read_failures=read_failures,
    )
    _append_activity_event(
        request=request,
        run_id=run_id,
        phase="Finished",
        label="Prepared evidence-based review summary",
        detail="The final answer only includes confirmed findings from files that completed review.",
        event_type="activity_completed",
        activity_id="repository-review-final-summary",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        current_action="Preparing final summary.",
        observation="Timed-out and skipped files are separated from confirmed findings.",
        next_action="Return the answer to the chat.",
        safe_reasoning_summary="Timed-out and skipped files are reported separately rather than used for conclusions.",
        events=activity_events,
    )

    thread_context = state.get("thread_context") or ThreadContext(request.project_path, request.branch)
    result = _base_response(
        request,
        response=response,
        response_type="assistant_answer",
        files_read=[item["file"] for item in reviewed],
        intent_classification=state.get("intent") or "repo_analysis",
        graph_path="repository_wide_review",
        skills_used=state.get("skills_used", []),
        thread_context_files=thread_context.recent_files,
        thread_context_symbols=thread_context.symbol_names,
        context_source="repository_wide_review",
        activity_events=activity_events,
        run_id=run_id,
        stop_reason="completed",
        **_classifier_debug(state),
    )
    return {"result": result, "graph_path": "repository_wide_review", "activity_events": activity_events}


def _inventory_repository_review_files(repo_path: Path) -> dict[str, list[Any]]:
    selected_paths: list[Path] = []
    skipped: list[dict[str, str]] = []
    source_candidates: list[Path] = []

    for path in sorted(repo_path.rglob("*"), key=lambda p: (len(p.relative_to(repo_path).parts), str(p).lower())):
        if len(selected_paths) >= MAX_REPOSITORY_REVIEW_FILES:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(repo_path)
        rel_text = str(rel)
        skip_reason = _review_skip_reason(path, rel)
        if skip_reason:
            skipped.append({"file": rel_text, "reason": skip_reason})
            continue
        source_candidates.append(path)

    priority_names = {"readme.md", "readme", "pyproject.toml", "package.json", "requirements.txt"}
    source_candidates.sort(
        key=lambda p: (
            0 if p.name.lower() in priority_names else 1,
            0 if p.suffix.lower() in {".py", ".kt", ".java", ".ts", ".tsx", ".js"} else 1,
            len(p.relative_to(repo_path).parts),
            str(p).lower(),
        )
    )
    selected_paths = source_candidates[:MAX_REPOSITORY_REVIEW_FILES]
    for path in source_candidates[MAX_REPOSITORY_REVIEW_FILES:]:
        skipped.append({"file": str(path.relative_to(repo_path)), "reason": "review file limit reached"})

    return {
        "selected": [str(path.relative_to(repo_path)) for path in selected_paths],
        "skipped": skipped,
    }


def _review_skip_reason(path: Path, relative_path: Path) -> str | None:
    parts = {part.lower() for part in relative_path.parts}
    if parts & {item.lower() for item in SKIP_DIRS | frozenset(REPOSITORY_REVIEW_EXTRA_SKIP_DIRS)}:
        return "generated, dependency, cache, or hidden workspace path"
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in REPOSITORY_REVIEW_BINARY_SUFFIXES:
        return "binary or unsupported file type"
    if suffix not in REPOSITORY_REVIEW_SUFFIXES and name not in REPOSITORY_REVIEW_FILENAMES:
        return "unsupported file type"
    try:
        size = path.stat().st_size
    except OSError:
        return "could not stat file"
    if size > MAX_REPOSITORY_REVIEW_BYTES:
        return f"larger than {MAX_REPOSITORY_REVIEW_BYTES} bytes"
    return None


def _read_review_file(repo_path: Path, relative_path: str) -> dict[str, Any]:
    path = (repo_path / relative_path).resolve()
    try:
        path.relative_to(repo_path.resolve())
    except ValueError:
        return {"error": "path is outside the active repository"}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"error": f"could not read file: {exc}"}
    if b"\0" in raw[:4096]:
        return {"error": "binary content detected"}
    truncated = len(raw) > MAX_REPOSITORY_REVIEW_PROMPT_CHARS
    content = raw[:MAX_REPOSITORY_REVIEW_PROMPT_CHARS].decode("utf-8", errors="replace")
    return {"content": content, "truncated": truncated}


def _file_read_observation(relative_path: str, content: str, truncated: bool) -> str:
    line_count = len(content.splitlines())
    suffix = " Content was truncated for review." if truncated else ""
    return f"Read {line_count} line(s) from `{relative_path}`.{suffix}"


def _progress_summary_for_file(
    *,
    relative_path: str,
    phase: str,
    content_preview: str = "",
    observation: str = "",
) -> dict[str, str]:
    path = Path(relative_path)
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    descriptor = _file_descriptor(path)
    if phase == "reading":
        return {
            "detail": f"Reading `{relative_path}`.",
            "current_action": f"Reading {descriptor}.",
            "observation": "No content has been inspected yet.",
            "next_action": "Review the file purpose and look for confirmed issues from its contents.",
            "safe_reasoning_summary": f"`{path.name}` is being inspected as {descriptor}.",
        }
    if phase == "reviewing":
        metadata = _content_metadata_summary(relative_path, content_preview)
        return {
            "detail": f"Read file content. Reviewing {descriptor}.",
            "current_action": f"Checking {descriptor} for concrete, file-backed findings.",
            "observation": metadata or observation or f"Read `{relative_path}`.",
            "next_action": "Use the file-level review result as evidence only if it completes.",
            "safe_reasoning_summary": _phase_summary_from_file(relative_path, suffix, lower_name, metadata),
        }
    if phase == "completed":
        return {
            "detail": "Completed file-level review.",
            "current_action": "File review complete.",
            "observation": observation or "No confirmed issue was reported from this file.",
            "next_action": "Move to the next selected file or aggregate completed results.",
            "safe_reasoning_summary": f"`{path.name}` has a completed review result and can be used as evidence.",
        }
    if phase == "failed":
        return {
            "detail": f"Could not review `{relative_path}`.",
            "current_action": "Skipping this file.",
            "observation": observation or "The file could not be read safely.",
            "next_action": "Continue with the remaining selected files.",
            "safe_reasoning_summary": f"`{path.name}` will not be used as confirmed evidence.",
        }
    return {
        "detail": f"Working on `{relative_path}`.",
        "current_action": "Inspecting file.",
        "observation": observation,
        "next_action": "Continue the repository review.",
        "safe_reasoning_summary": f"Progress is based on `{path.name}`.",
    }


def _file_descriptor(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name in {"readme", "readme.md"} or suffix in {".md", ".rst", ".txt"}:
        return "documentation"
    if name in {"package.json", "pyproject.toml", "requirements.txt", "requirements.in"}:
        return "dependency or packaging metadata"
    if suffix in {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".properties", ".gradle"}:
        return "configuration"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift", ".go", ".rs"}:
        return f"{suffix.lstrip('.')} source code"
    if name == "dockerfile":
        return "container configuration"
    return "readable repository file"


def _content_metadata_summary(relative_path: str, content_preview: str) -> str:
    path = Path(relative_path)
    name = path.name.lower()
    suffix = path.suffix.lower()
    lines = content_preview.splitlines()
    if name == "package.json":
        try:
            payload = json.loads(content_preview)
            deps = len(payload.get("dependencies") or {})
            dev_deps = len(payload.get("devDependencies") or {})
            scripts = sorted((payload.get("scripts") or {}).keys())[:5]
            script_text = f"; scripts: {', '.join(scripts)}" if scripts else ""
            return f"Found package metadata with {deps} dependencies and {dev_deps} dev dependencies{script_text}."
        except json.JSONDecodeError:
            return "Found package metadata, but the preview was not enough to parse it fully."
    if name in {"pyproject.toml", "requirements.txt", "requirements.in"}:
        return f"Found Python packaging/dependency metadata across {len(lines)} preview line(s)."
    if suffix == ".py":
        defs = sum(1 for line in lines if line.lstrip().startswith(("def ", "async def ", "class ")))
        return f"Found Python source with {defs} visible function/class definition(s) in the preview."
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        imports = sum(1 for line in lines if line.lstrip().startswith(("import ", "export ")))
        return f"Found web source with {imports} visible import/export line(s) in the preview."
    if suffix in {".kt", ".java", ".swift", ".go", ".rs"}:
        return f"Found application source code with {len(lines)} preview line(s)."
    if suffix in {".md", ".rst", ".txt"} or name in {"readme", "readme.md"}:
        headings = sum(1 for line in lines if line.lstrip().startswith("#"))
        return f"Found documentation with {headings} visible heading(s) in the preview."
    if suffix in {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".properties", ".gradle"}:
        return f"Found configuration content with {len(lines)} preview line(s)."
    return f"Read {len(lines)} preview line(s)."


def _phase_summary_from_file(relative_path: str, suffix: str, lower_name: str, metadata: str) -> str:
    path_name = Path(relative_path).name
    if lower_name in {"readme", "readme.md"}:
        return f"`{path_name}` documents setup or usage, so the review checks whether guidance matches the repository evidence."
    if lower_name == "package.json":
        return f"`{path_name}` controls web scripts and dependency versions, so the review checks packaging and build risk."
    if lower_name in {"pyproject.toml", "requirements.txt", "requirements.in"}:
        return f"`{path_name}` affects Python runtime setup, so the review checks dependency and packaging implications."
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift", ".go", ".rs"}:
        return f"`{path_name}` is source code; the review focuses on concrete behavior visible in that file."
    if suffix in {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".properties", ".gradle"}:
        return f"`{path_name}` is configuration, so the review checks settings and workflow impact."
    return metadata or f"`{path_name}` is being reviewed from its file content."


def _review_single_file(
    *,
    request: AgentRunRequest,
    relative_path: str,
    content: str,
    truncated: bool,
    client: OpenAICompatibleModelClient | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if client is None:
        return {
            "file": relative_path,
            "summary": _fallback_file_review_summary(relative_path, content, truncated),
            "confirmed": True,
            "fallback": True,
            "elapsed_seconds": int(time.perf_counter() - started),
        }

    attempts = 2 if len(content) <= SMALL_REVIEW_RETRY_CHARS else 1
    for attempt in range(attempts):
        try:
            raw_response = client.generate_text(
                ModelGenerationRequest(
                    system_prompt=(
                        "You are RepoOperator performing a file-level code review. "
                        "Use only the provided file content. Return concise visible review notes: "
                        "purpose, confirmed issues, improvement opportunities, and evidence. "
                        "If no issue is confirmed, say so. Do not include hidden reasoning.\n"
                        + language_guidance_for_task(request.task)
                    ),
                    user_prompt=(
                        f"Repository: {Path(request.project_path).name}\n"
                        f"File: {relative_path}\n"
                        f"Content truncated: {'yes' if truncated else 'no'}\n\n"
                        f"User review request:\n{request.task}\n\n"
                        f"File content:\n{content}"
                    ),
                )
            )
            clean_response, _reasoning = clean_user_visible_response(raw_response, user_task=request.task)
            return {
                "file": relative_path,
                "summary": clean_response.strip() or "Completed file-level review.",
                "confirmed": True,
                "attempts": attempt + 1,
                "elapsed_seconds": int(time.perf_counter() - started),
            }
        except (ValueError, RuntimeError, TimeoutError) as exc:
            if _is_timeout_exception(exc):
                if attempt + 1 < attempts:
                    continue
                return {
                    "file": relative_path,
                    "timed_out": True,
                    "error": "model_timeout",
                    "elapsed_seconds": max(1, int(time.perf_counter() - started)),
                    "summary": "Timed out before file-level review completed.",
                }
            return {
                "file": relative_path,
                "summary": f"Could not complete model review for this file: {_safe_error_summary(exc)}",
                "confirmed": False,
                "error": "model_error",
                "elapsed_seconds": int(time.perf_counter() - started),
            }

    return {
        "file": relative_path,
        "timed_out": True,
        "error": "model_timeout",
        "elapsed_seconds": max(1, int(time.perf_counter() - started)),
        "summary": "Timed out before file-level review completed.",
    }


def _is_timeout_exception(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text or isinstance(exc, TimeoutError)


def _safe_error_summary(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    if not text:
        return exc.__class__.__name__
    return text[:220]


def _fallback_file_review_summary(relative_path: str, content: str, truncated: bool) -> str:
    lines = content.splitlines()
    non_empty = [line for line in lines if line.strip()]
    suffix_note = " Content was truncated before review." if truncated else ""
    return (
        f"`{relative_path}` was read successfully. It contains {len(lines)} line(s) "
        f"({len(non_empty)} non-empty). No model review was available, so this is a structural observation only."
        f"{suffix_note}"
    )


def _format_repository_review_response(
    *,
    request: AgentRunRequest,
    selected_files: list[str],
    reviewed: list[dict[str, Any]],
    timed_out: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    read_failures: list[dict[str, str]],
) -> str:
    korean = user_prefers_korean(request.task)
    if korean:
        if not reviewed:
            lines = [
                "파일별 코드 리뷰가 완료되지 않았습니다.",
                "",
                "현재 확인 가능한 것은 저장소 구조와 파일 선택 결과뿐입니다. 타임아웃 또는 읽기 실패가 발생한 파일은 확인된 문제로 다루지 않았습니다.",
            ]
        else:
            lines = [
                f"분석 가능한 파일 {len(selected_files)}개 중 {len(reviewed)}개를 파일별로 검토했습니다.",
                "",
                "## 확인된 파일별 결과",
            ]
            for item in reviewed:
                lines.extend([f"- `{item['file']}`", f"  {_indent_one_line(str(item.get('summary') or '검토 완료'))}"])
        if timed_out:
            lines.extend(["", "## 타임아웃으로 검토하지 못한 파일"])
            lines.extend(
                f"- `{item['file']}`: {item.get('elapsed_seconds', 0)}초 후 타임아웃"
                for item in timed_out
            )
        if skipped or read_failures:
            lines.extend(["", "## 제외되거나 읽지 못한 파일"])
            for item in [*skipped[:12], *read_failures[:12]]:
                lines.append(f"- `{item['file']}`: {item['reason']}")
        lines.extend([
            "",
            "위 결론은 실제로 읽고 검토가 끝난 파일에만 근거합니다. 제외되거나 타임아웃된 파일에 대해서는 보안 문제나 구현 문제를 단정하지 않았습니다.",
        ])
        return "\n".join(lines)

    if not reviewed:
        lines = [
            "File-by-file code review did not complete.",
            "",
            "The reliable result is limited to repository inventory and file selection. Timed-out or unreadable files are not used as confirmed findings.",
        ]
    else:
        lines = [
            f"Reviewed {len(reviewed)} of {len(selected_files)} selected readable file(s).",
            "",
            "## Confirmed File-Level Results",
        ]
        for item in reviewed:
            lines.extend([f"- `{item['file']}`", f"  {_indent_one_line(str(item.get('summary') or 'Review completed.'))}"])
    if timed_out:
        lines.extend(["", "## Not Reviewed Due To Timeout"])
        lines.extend(
            f"- `{item['file']}`: timed out after {item.get('elapsed_seconds', 0)}s"
            for item in timed_out
        )
    if skipped or read_failures:
        lines.extend(["", "## Skipped Or Unreadable Files"])
        for item in [*skipped[:12], *read_failures[:12]]:
            lines.append(f"- `{item['file']}`: {item['reason']}")
    lines.extend([
        "",
        "I only treated completed per-file reviews as confirmed evidence. Skipped and timed-out files are listed separately.",
    ])
    return "\n".join(lines)


def _indent_one_line(text: str) -> str:
    return " ".join(text.split())[:900]


def _truncate_for_event(text: str, limit: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def _answer_read_only(state: OrchestrationState) -> dict[str, Any]:
    from repooperator_worker.services.agent_graph import run_agent_graph

    request = state["request"]
    if _should_use_repository_wide_review(state):
        return _repository_wide_review(state)

    skills_context = state.get("skills_context") or ""
    if state.get("intent") == "review_recommendation":
        request = request.model_copy(
            update={
                "task": (
                    f"{request.task}\n\n"
                    "Treat this as a review/recommendation request only. "
                    "List concrete improvements and risks. Do not prepare a diff or imply that files were changed."
                )
            }
        )
    if skills_context:
        request = request.model_copy(
            update={"task": f"{request.task}\n\nRelevant enabled skills:\n{skills_context}"}
        )

    update = {
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
    result = run_agent_graph(request)
    if state.get("intent") == "review_recommendation":
        update["recommendation_context"] = build_recommendation_context(
            request=request,
            files_read=result.files_read,
            response=result.response,
        )
        update["recommendation_context_loaded"] = True
    result = result.model_copy(update=update)
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

            preview = preview_command(install_cmd, project_path=request.project_path, reason=install_reason)
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

    # glab is installed — check auth status through the command policy path.
    try:
        from repooperator_worker.services.command_service import run_command_with_policy

        auth_check_payload = run_command_with_policy(
            ["glab", "auth", "status"],
            project_path=request.project_path,
            reason="Check GitLab CLI authentication status without exposing token values.",
        )
        auth_check = subprocess.CompletedProcess(
            ["glab", "auth", "status"],
            int(auth_check_payload.get("exit_code") or 0),
            auth_check_payload.get("stdout", ""),
            auth_check_payload.get("stderr", ""),
        )
        if auth_check.returncode != 0:
            host = _detect_git_remote_host(request) or "gitlab.com"
            login_command = "glab auth login" if host == "gitlab.com" else f"glab auth login --hostname {host}"
            result_response = _base_response(
                request,
                response=_format_glab_auth_failure(host, login_command),
                response_type="assistant_answer",
                intent_classification=state.get("intent"),
                graph_path="local_tool_request_auth_required",
                thread_context_files=tc_files,
                thread_context_symbols=tc_symbols,
                context_source=state.get("context_source"),
                **_classifier_debug(state),
            )
            return {"result": result_response, "graph_path": "local_tool_request"}
    except (ValueError, RuntimeError, PermissionError):
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
            err = _redact_text((result.get("stderr") or result.get("stdout") or "No output").strip())
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


def _detect_git_remote_host(request: AgentRunRequest) -> str | None:
    repo_cwd = _get_repo_cwd(request)
    if not repo_cwd:
        return None
    try:
        result = _run_policy_command_as_completed(
            ["git", "remote", "get-url", "origin"],
            request.project_path,
            reason="Read the repository remote host.",
        )
    except (ValueError, RuntimeError, PermissionError):
        return None
    url = (result.stdout or "").strip()
    if not url:
        return None
    if url.startswith("git@") and ":" in url:
        return url.split("@", 1)[1].split(":", 1)[0]
    parsed = urlparse(url)
    return parsed.hostname


def _format_glab_auth_failure(host: str, login_command: str) -> str:
    return (
        f"`glab` is installed, but GitLab authentication failed for `{host}`.\n\n"
        "Run this command in a terminal, then retry:\n\n"
        f"```bash\n{login_command}\n```\n\n"
        "If you use a token, configure a valid GitLab token without printing the token value. "
        "RepoOperator hides raw authentication diagnostics by default to avoid exposing secrets."
    )


def _plan_git_workflow(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    action = _normalize_git_action(state.get("git_action") or state.get("requested_action"))
    repo_path = resolve_project_path(request.project_path)
    thread_context = state.get("thread_context") or ThreadContext(request.project_path, request.branch)

    if action == "git_recent_commit":
        log = _run_git(repo_path, ["log", "-1", "--pretty=fuller", "--stat", "--decorate"])
        response = _format_recent_commit_response(request, log)
        return {
            "result": _base_response(
                request,
                response=response,
                response_type="assistant_answer",
                intent_classification=state.get("intent"),
                graph_path="git_recent_commit",
                thread_context_files=thread_context.recent_files,
                thread_context_symbols=thread_context.symbol_names,
                context_source=state.get("context_source"),
                **_classifier_debug({**state, "git_action": action, "commands_run": ["git log -1 --pretty=fuller --stat --decorate"]}),
            ),
            "graph_path": "git_recent_commit",
        }

    if action == "git_status":
        status = _run_git(repo_path, ["status", "--short"])
        stat = _run_git(repo_path, ["diff", "--stat"])
        response = _format_git_status_response(request, status, stat)
        commands = ["git status --short", "git diff --stat"]
        return {
            "result": _base_response(
                request,
                response=response,
                response_type="assistant_answer",
                intent_classification=state.get("intent"),
                graph_path="git_status",
                thread_context_files=thread_context.recent_files,
                thread_context_symbols=thread_context.symbol_names,
                context_source=state.get("context_source"),
                **_classifier_debug({**state, "git_action": action, "commands_run": commands}),
            ),
            "graph_path": "git_status",
        }

    if action == "git_commit_plan":
        status = _run_git(repo_path, ["status", "--short"])
        stat = _run_git(repo_path, ["diff", "--stat"])
        diff = _run_git(repo_path, ["diff"])
        changed_files = _changed_files_from_status(status.stdout)
        commands_run = ["git status --short", "git diff --stat", "git diff"]
        if status.returncode != 0:
            response = f"I could not inspect the working tree:\n\n```text\n{_redact_text(status.stderr or status.stdout)}\n```"
            return {
                "result": _base_response(
                    request,
                    response=response,
                    response_type="assistant_answer",
                    intent_classification=state.get("intent"),
                    graph_path="git_commit_plan_error",
                    context_source=state.get("context_source"),
                    **_classifier_debug({**state, "git_action": action, "commands_run": commands_run}),
                )
            }
        if not changed_files:
            response = "There is nothing to commit. The working tree has no modified, staged, or untracked files."
            return {
                "result": _base_response(
                    request,
                    response=response,
                    response_type="assistant_answer",
                    intent_classification=state.get("intent"),
                    graph_path="git_commit_plan_clean",
                    context_source=state.get("context_source"),
                    **_classifier_debug({**state, "git_action": action, "commands_run": commands_run}),
                )
            }
        message = _propose_commit_message(request, changed_files, stat.stdout, diff.stdout)
        commit_command = ["git", "commit", "-m", message]
        planned = ["git add --all", shlex.join(commit_command)]
        preview = _command_preview_for_repo(["git", "add", "--all"], repo_path, reason=(
            "Stage the current repository changes before creating the proposed commit. "
            f"Planned commit message: {message!r}. RepoOperator will not push."
        ))
        preview["next_command_approval"] = _command_preview_for_repo(
            commit_command,
            repo_path,
            reason=f"Create the local commit with message: {message!r}. RepoOperator will not push.",
        )
        response = _format_commit_plan_response(request, changed_files, stat.stdout, message, planned)
        return {
            "result": _base_response(
                request,
                response=response,
                response_type="command_approval",
                command_approval=preview,
                intent_classification=state.get("intent"),
                graph_path="git_commit_plan",
                thread_context_files=thread_context.recent_files,
                thread_context_symbols=thread_context.symbol_names,
                context_source=state.get("context_source"),
                **_classifier_debug({**state, "git_action": action, "commands_planned": planned, "commands_run": commands_run}),
            ),
            "graph_path": "git_commit_plan",
        }

    if action == "git_push_plan":
        branch = _run_git(repo_path, ["branch", "--show-current"])
        remotes = _run_git(repo_path, ["remote", "-v"])
        status = _run_git(repo_path, ["status", "--short"])
        upstream = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        branch_name = (branch.stdout or request.branch or "").strip()
        push_command = ["git", "push"] if upstream.returncode == 0 else ["git", "push", "--set-upstream", "origin", branch_name or "HEAD"]
        planned = [shlex.join(push_command)]
        commands_run = [
            "git branch --show-current",
            "git remote -v",
            "git status --short",
            "git rev-parse --abbrev-ref --symbolic-full-name @{u}",
        ]
        preview = _command_preview_for_repo(push_command, repo_path, reason="Push the current branch to the configured remote. This requires approval.")
        response = _format_push_plan_response(branch_name, remotes.stdout, status.stdout, upstream.stdout, planned[0])
        return {
            "result": _base_response(
                request,
                response=response,
                response_type="command_approval",
                command_approval=preview,
                intent_classification=state.get("intent"),
                graph_path="git_push_plan",
                context_source=state.get("context_source"),
                **_classifier_debug({**state, "git_action": action, "commands_planned": planned, "commands_run": commands_run}),
            ),
            "graph_path": "git_push_plan",
        }

    if action == "git_mr_create_plan":
        preview = _command_preview_for_repo(["glab", "mr", "create"], repo_path, reason="Create a GitLab merge request after you review the title, body, source branch, and target branch.")
        return {
            "result": _base_response(
                request,
                response=(
                    "RepoOperator can create a merge request after approval. "
                    "Before creating it, review the source branch, target branch, title, and body. "
                    "Use the approval card only when those details are correct."
                ),
                response_type="command_approval",
                command_approval=preview,
                intent_classification=state.get("intent"),
                graph_path="git_mr_create_plan",
                context_source=state.get("context_source"),
                **_classifier_debug({**state, "git_action": action, "commands_planned": ["glab mr create"]}),
            ),
            "graph_path": "git_mr_create_plan",
        }

    return _plan_git_workflow({**state, "git_action": "git_status"})


def _run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    result = _run_policy_command_as_completed(
        ["git", *args],
        str(repo_path),
        reason=f"Inspect git state with `{shlex.join(['git', *args])}`.",
    )
    try:
        from repooperator_worker.services.event_service import record_event

        record_event(
            event_type="git_workflow_step",
            repo=str(repo_path),
            status="ok" if result.returncode == 0 else "error",
            summary=shlex.join(["git", *args]),
            command=["git", *args],
            tool="git",
            error=_redact_text(result.stderr[:500]) if result.returncode else None,
        )
    except Exception:  # noqa: BLE001
        logger.debug("could not record git workflow event", exc_info=True)
    return result


def _run_policy_command_as_completed(
    command: list[str],
    project_path: str,
    *,
    reason: str,
) -> subprocess.CompletedProcess[str]:
    from repooperator_worker.services.command_service import run_command_with_policy

    payload = run_command_with_policy(command, project_path=project_path, reason=reason)
    return subprocess.CompletedProcess(
        command,
        int(payload.get("exit_code") or 0),
        payload.get("stdout", ""),
        payload.get("stderr", ""),
    )


def _normalize_git_action(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("git_recent_commit", "recent_commit", "latest_commit", "last_commit", "log", "commit info")):
        return "git_recent_commit"
    if "mr_create" in text or ("merge request" in text and "create" in text) or "mr create" in text:
        return "git_mr_create_plan"
    if "push" in text or "푸시" in text:
        return "git_push_plan"
    if "git_commit_plan" in text or "commit" in text:
        return "git_commit_plan"
    if any(token in text for token in ("diff", "status", "branch", "changes")):
        return "git_status"
    return "git_status"


def _changed_files_from_status(status_output: str) -> list[str]:
    files: list[str] = []
    for line in status_output.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append(path)
    return files


def _propose_commit_message(request: AgentRunRequest, changed_files: list[str], diff_stat: str, diff: str) -> str:
    fallback = "Update " + (Path(changed_files[0]).name if changed_files else "repository files")
    try:
        response = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "Write one concise git commit subject. Return only the subject line, "
                    "without quotes, markdown, or a trailing period."
                ),
                user_prompt="\n\n".join(
                    [
                        f"User request: {request.task}",
                        "Changed files:\n" + "\n".join(f"- {path}" for path in changed_files[:20]),
                        "Diff stat:\n" + (diff_stat[:2000] or "none"),
                        "Diff excerpt:\n" + (diff[:4000] or "none"),
                    ]
                ),
            )
        )
        cleaned = response.strip().splitlines()[0].strip("`\"' ")
        return cleaned[:120] or fallback
    except Exception:  # noqa: BLE001
        return fallback


def _command_preview_for_repo(argv: list[str], repo_path: Path, *, reason: str) -> dict[str, Any]:
    from repooperator_worker.services.command_service import preview_command

    return preview_command(argv, project_path=str(repo_path), reason=reason)


def _format_git_status_response(request: AgentRunRequest, status: subprocess.CompletedProcess[str], stat: subprocess.CompletedProcess[str]) -> str:
    if user_prefers_korean(request.task):
        if not status.stdout.strip():
            return "현재 작업 트리에 변경사항이 없습니다."
        return "현재 변경사항은 다음과 같습니다.\n\n```text\n" + _redact_text(status.stdout.strip()) + "\n```\n\nDiff 요약:\n```text\n" + (_redact_text(stat.stdout.strip()) or "No diff stat.") + "\n```"
    if not status.stdout.strip():
        return "The working tree has no modified, staged, or untracked files."
    return "Current working tree changes:\n\n```text\n" + _redact_text(status.stdout.strip()) + "\n```\n\nDiff summary:\n```text\n" + (_redact_text(stat.stdout.strip()) or "No diff stat.") + "\n```"


def _format_recent_commit_response(request: AgentRunRequest, log: subprocess.CompletedProcess[str]) -> str:
    if log.returncode != 0:
        return "I could not read the latest commit:\n\n```text\n" + _redact_text(log.stderr or log.stdout) + "\n```"
    if user_prefers_korean(request.task):
        return "현재 브랜치의 최신 커밋입니다.\n\n```text\n" + _redact_text(log.stdout.strip()) + "\n```"
    return "Latest commit information:\n\n```text\n" + _redact_text(log.stdout.strip()) + "\n```"


def _format_commit_plan_response(request: AgentRunRequest, changed_files: list[str], diff_stat: str, message: str, planned: list[str]) -> str:
    files = "\n".join(f"- `{path}`" for path in changed_files[:20])
    if user_prefers_korean(request.task):
        return (
            "커밋할 변경사항을 확인했습니다.\n\n"
            f"변경 파일:\n{files}\n\n"
            f"Diff 요약:\n```text\n{_redact_text(diff_stat.strip()) or 'No diff stat.'}\n```\n\n"
            f"제안 커밋 메시지: `{message}`\n\n"
            "아래 승인 카드로 먼저 변경사항을 stage합니다. 그 다음 커밋 명령을 승인하면 됩니다.\n"
            "계획된 명령:\n" + "\n".join(f"- `{cmd}`" for cmd in planned)
        )
    return (
        "I found changes that can be committed.\n\n"
        f"Changed files:\n{files}\n\n"
        f"Diff summary:\n```text\n{_redact_text(diff_stat.strip()) or 'No diff stat.'}\n```\n\n"
        f"Proposed commit message: `{message}`\n\n"
        "Approve the card below to stage the changes first. Then approve the commit command.\n"
        "Planned commands:\n" + "\n".join(f"- `{cmd}`" for cmd in planned)
    )


def _format_push_plan_response(branch: str, remotes: str, status: str, upstream: str, command: str) -> str:
    return (
        "Push plan for the active repository:\n\n"
        f"- Branch: `{branch or 'unknown'}`\n"
        f"- Upstream: `{upstream.strip() or 'not configured'}`\n"
        f"- Working tree status: `{status.strip() or 'clean'}`\n"
        f"- Command: `{command}`\n\n"
        "Remote configuration:\n```text\n" + _redact_text(remotes.strip()) + "\n```"
    )


def _redact_text(text: str) -> str:
    redacted = text or ""
    redacted = re.sub(r"(?i)(token|api[_-]?key|secret|password)=\S+", r"\1=[redacted]", redacted)
    redacted = re.sub(r"(?i)(glpat-|ghp_|sk-)[A-Za-z0-9_\-]+", "[redacted-token]", redacted)
    home = str(Path.home())
    if home:
        redacted = redacted.replace(home, "~")
    return redacted


def _run_local_command_request(state: OrchestrationState) -> dict[str, Any]:
    request = state["request"]
    from repooperator_worker.services.command_service import preview_command, run_command_with_policy

    command, reason = _command_for_classification(state)
    preview = preview_command(command, project_path=request.project_path, reason=reason)
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
        command_result = run_command_with_policy(
            command,
            approval_id=preview.get("approval_id"),
            project_path=request.project_path,
            reason=reason,
        )
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


def _decompose_and_execute(state: OrchestrationState) -> dict[str, Any]:
    """Execute a multi-step task: decompose, run each step, return combined result."""
    request = state["request"]
    if _should_use_repository_wide_review(state):
        return _repository_wide_review(state)

    started = time.perf_counter()
    plan_events: list[dict] = []
    step_results: list[dict[str, Any]] = []
    run_id = str(state.get("run_id") or f"run-{uuid.uuid4().hex[:12]}")
    plan_id = f"plan-{uuid.uuid4().hex[:10]}"
    steering_notes: list[str] = []

    steps = _parse_task_steps_with_llm(state)
    if not steps:
        # Fallback: treat as single write_request
        return {
            "intent": "write_request",
            "graph_path": f"{state.get('graph_path', '')}->decompose_fallback",
        }

    plan_created = _activity_event(
        run_id=run_id,
        phase="Planning",
        label=f"Created a {len(steps)}-step plan",
        detail=", ".join(str(step.get("description") or f"Step {i + 1}") for i, step in enumerate(steps[:6])),
        status="completed",
        elapsed_ms=0,
    )
    plan_created.update({"event_type": "plan_created", "plan_id": plan_id})
    append_run_event(run_id, plan_created)
    plan_events.append(plan_created)

    for i, step in enumerate(steps):
        from repooperator_worker.services.agent_run_coordinator import consume_steering, should_cancel

        if should_cancel(run_id):
            cancel_event = _activity_event(
                run_id=run_id,
                phase="Finished",
                label="Run cancelled",
                detail="Stopped at a safe checkpoint before the next plan step.",
                status="failed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
            cancel_event.update({"event_type": "run_cancelled", "plan_id": plan_id})
            append_run_event(run_id, cancel_event)
            plan_events.append(cancel_event)
            break
        steering = consume_steering(run_id)
        if steering:
            steering_text = " ".join(str(item.get("content") or "") for item in steering if item.get("content"))
            if steering_text:
                steering_notes.append(steering_text)
                step["instruction"] = f"{step.get('instruction') or request.task}\n\nSteering instruction: {steering_text}"
                steering_event = _activity_event(
                    run_id=run_id,
                    phase="Planning",
                    label="Applied steering instruction",
                    detail=(" ".join(steering_text.split()))[:220],
                    status="completed",
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
                steering_event.update({"event_type": "steering_applied_to_plan", "plan_id": plan_id})
                append_run_event(run_id, steering_event)
                plan_events.append(steering_event)
        step_id = f"{plan_id}-step-{i + 1}"
        elapsed_start = int((time.perf_counter() - started) * 1000)
        started_event = _activity_event(
            run_id=run_id,
            phase="Planning",
            label=f"Started step {i + 1} of {len(steps)}",
            detail=str(step.get("description") or "Processing repository step"),
            status="running",
            elapsed_ms=elapsed_start,
            files=[str(step.get("file"))] if step.get("file") else [],
        )
        started_event.update({"event_type": "plan_step_started", "plan_id": plan_id, "step_id": step_id})
        append_run_event(run_id, started_event)
        plan_events.append(started_event)

        result = _execute_plan_step({**state, "run_id": run_id, "plan_id": plan_id, "step_id": step_id}, step, step_results)
        step_results.append(result)

        elapsed_end = int((time.perf_counter() - started) * 1000)
        completed_event = {
            **started_event,
            "id": f"activity-{uuid.uuid4().hex[:10]}",
            "event_type": "plan_step_completed" if not result.get("error") else "plan_step_failed",
            "status": "completed" if not result.get("error") else "failed",
            "elapsed_ms": elapsed_end,
            "duration_ms": max(0, elapsed_end - elapsed_start),
            "ended_at": _utc_now(),
            "detail": result.get("response") or started_event.get("detail"),
        }
        append_run_event(run_id, completed_event)
        plan_events.append(completed_event)

    completed = _activity_event(
        run_id=run_id,
        phase="Finished",
        label=f"Completed {len(steps)} planned steps",
        detail="Prepared the final summary from executed work.",
        status="completed",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    completed.update({"event_type": "plan_completed", "plan_id": plan_id})
    append_run_event(run_id, completed)
    plan_events.append(completed)

    combined_text = _format_plan_summary(steps, step_results, request)

    applied_edits = [r for r in step_results if r.get("edit_archive")]
    edit_archive = [record for result in applied_edits for record in result.get("edit_archive", [])]
    last_edit = applied_edits[-1] if applied_edits else None
    all_files = list({r["file"] for r in step_results if r.get("file")})
    plan_steps_summary = [
        {
            "step_index": r.get("step_index", i),
            "description": steps[i].get("description", ""),
            "intent": r.get("intent", "read"),
            "file": r.get("file"),
            "elapsed_ms": r.get("elapsed_ms"),
            "has_proposal": bool(r.get("proposal_path")),
        }
        for i, r in enumerate(step_results)
    ]

    thread_context = state.get("thread_context") or ThreadContext(request.project_path, request.branch)
    result_response = _base_response(
        request,
        response=(
            _generate_edit_result_summary(request, state, edit_archive)
            if edit_archive
            else combined_text
        ),
        response_type="edit_applied" if edit_archive else "assistant_answer",
        files_read=all_files,
        intent_classification="multi_step_request",
        graph_path="decompose_and_execute",
        skills_used=state.get("skills_used", []),
        thread_context_files=thread_context.recent_files,
        thread_context_symbols=thread_context.symbol_names,
        context_source=state.get("context_source"),
        proposal_relative_path=last_edit["proposal_path"] if last_edit else None,
        proposal_original_content=last_edit["original_content"] if last_edit else None,
        proposal_proposed_content=last_edit["proposed_content"] if last_edit else None,
        proposal_context_summary=last_edit.get("context_summary") if last_edit else None,
        selected_target_file=last_edit["proposal_path"] if last_edit else None,
        edit_archive=edit_archive,
        stop_reason="completed",
        plan_steps_summary=plan_steps_summary,
        **_classifier_debug(state),
    )
    return {
        "result": result_response,
        "plan_step_events": plan_events,
        "graph_path": "decompose_and_execute",
    }


def _parse_task_steps_with_llm(state: OrchestrationState) -> list[dict[str, Any]]:
    """Use LLM to decompose a multi-step task into discrete steps."""
    request = state["request"]
    target_files = state.get("target_files", [])
    file_hints = state.get("file_hints", [])
    all_known = list(dict.fromkeys([*target_files, *file_hints]))[:12]

    system_prompt = """\
You are a task planner. Break the user's request into discrete steps. Return JSON array only.

Schema: [{"step_index": 0, "description": "...", "intent": "read|write", "file": "relative/path/or/null", "instruction": "specific instruction for this step"}]

intent:
- "read": analyze, inspect, describe, summarize (no file change)
- "write": modify, update, refactor, fix (requires a change proposal)

Rules:
- One file per step; keep steps focused
- If analysis followed by modification of the same file, split into separate steps
- Preserve the user's sequential intent ("analyze A, then update B")
- Do not invent files not mentioned in the request or known context
- Return 2–6 steps maximum
"""
    try:
        response = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=system_prompt,
                user_prompt=(
                    f"User request: {request.task}\n\n"
                    f"Known files: {', '.join(all_known) if all_known else 'none'}"
                ),
            )
        )
        steps = _parse_plan_json(response)
        if steps:
            return steps
    except Exception:
        logger.debug("LLM task decomposition failed; using file-hint fallback")

    # Fallback: one step per target file (last one is write if there are multiple)
    if not all_known:
        return []
    result: list[dict[str, Any]] = []
    for i, f in enumerate(all_known[:6]):
        is_last = i == len(all_known) - 1
        intent = "write" if is_last and len(all_known) > 1 else "read"
        result.append({
            "step_index": i,
            "description": ("Update" if intent == "write" else "Analyze") + f" {Path(f).name}",
            "intent": intent,
            "file": f,
            "instruction": request.task,
        })
    return result


def _parse_plan_json(response: str) -> list[dict[str, Any]]:
    text = response.strip()
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```").strip()
    # Extract JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
        if not isinstance(raw, list):
            return []
        steps: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            step: dict[str, Any] = {
                "step_index": int(item.get("step_index", len(steps))),
                "description": str(item.get("description", "Step")),
                "intent": "write" if str(item.get("intent", "read")).lower() == "write" else "read",
                "file": item.get("file") or None,
                "instruction": str(item.get("instruction", "")),
            }
            steps.append(step)
        return steps
    except (json.JSONDecodeError, ValueError):
        return []


def _execute_plan_step(
    state: OrchestrationState,
    step: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute a single plan step — read-only analysis or file change proposal."""
    request = state["request"]
    intent = step.get("intent", "read")
    file: str | None = step.get("file")
    instruction = step.get("instruction") or request.task
    started = time.perf_counter()
    run_id = str(state.get("run_id") or f"run-{uuid.uuid4().hex[:12]}")
    plan_id = str(state.get("plan_id") or "")
    step_id = str(state.get("step_id") or "")
    from repooperator_worker.services.agent_run_coordinator import should_cancel

    if should_cancel(run_id):
        return {
            "step_index": step.get("step_index", 0),
            "file": file,
            "intent": intent,
            "response": "Run cancelled before this step executed.",
            "elapsed_ms": 0,
            "error": "cancelled",
        }

    if intent == "write" and file:
        try:
            edit_started = _activity_event(
                run_id=run_id,
                phase="Editing",
                label=f"Editing {Path(file).name}",
                detail="Drafting and validating a repository-scoped file edit.",
                status="running",
                elapsed_ms=0,
                files=[file],
            )
            edit_started.update({"event_type": "file_edit_started", "plan_id": plan_id, "step_id": step_id})
            append_run_event(run_id, edit_started)
            proposal = propose_file_edit(
                AgentProposeFileRequest(
                    project_path=request.project_path,
                    relative_path=file,
                    instruction=instruction,
                )
            )
            validation_event = _activity_event(
                run_id=run_id,
                phase="Editing",
                label=f"Validated {Path(file).name}",
                detail="Target path and generated replacement passed deterministic validation.",
                status="completed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                files=[file],
            )
            validation_event.update({"event_type": "validation_completed", "plan_id": plan_id, "step_id": step_id})
            append_run_event(run_id, validation_event)
            write_text_file(
                FileWriteRequest(
                    project_path=request.project_path,
                    relative_path=proposal.relative_path,
                    content=proposal.proposed_content,
                )
            )
            edit_record = _edit_archive_record(
                file_path=proposal.relative_path,
                status="modified",
                original=proposal.original_content,
                proposed=proposal.proposed_content,
                summary=proposal.context_summary,
                proposal_id=f"proposal-{uuid.uuid4().hex[:10]}",
                plan_id=plan_id,
            )
            edit_completed = _activity_event(
                run_id=run_id,
                phase="Editing",
                label=f"Modified {Path(file).name}",
                detail=f"+{edit_record['additions']} -{edit_record['deletions']}",
                status="completed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                files=[file],
                proposal_id=edit_record.get("proposal_id"),
            )
            edit_completed.update({
                "event_type": "file_edit_completed",
                "changed_file": edit_record,
                "plan_id": plan_id,
                "step_id": step_id,
            })
            append_run_event(run_id, edit_completed)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "step_index": step.get("step_index", 0),
                "file": file,
                "intent": "write",
                "response": f"Modified `{file}`.",
                "proposal_path": proposal.relative_path,
                "original_content": proposal.original_content,
                "proposed_content": proposal.proposed_content,
                "context_summary": proposal.context_summary,
                "edit_archive": [edit_record],
                "elapsed_ms": elapsed_ms,
            }
        except (ValueError, RuntimeError) as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "step_index": step.get("step_index", 0),
                "file": file,
                "intent": "write",
                "response": f"Could not generate proposal for `{file}`: {exc}",
                "elapsed_ms": elapsed_ms,
            }

    # Read-only step — use file context + LLM
    if file:
        read_started = _activity_event(
            run_id=run_id,
            phase="Reading files",
            label=f"Reading {Path(file).name}",
            detail="Inspecting file before deciding the next step.",
            status="running",
            elapsed_ms=0,
            files=[file],
        )
        read_started.update({"event_type": "file_read_started", "plan_id": plan_id, "step_id": step_id})
        append_run_event(run_id, read_started)
    skills_context = state.get("skills_context") or ""
    prior_context_parts = [
        f"Prior analysis of {r['file']}:\n{str(r.get('response', ''))[:400]}"
        for r in prior_results
        if r.get("file") and r.get("intent") == "read"
    ]
    context = build_query_aware_context(request.project_path, instruction)

    answer = ""
    try:
        answer = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "You are RepoOperator. Analyze the repository context and respond to the user's request. "
                    "Be concise. Focus on the specific file if named.\n"
                    + language_guidance_for_task(request.task)
                ),
                user_prompt="\n\n".join(
                    part
                    for part in [
                        f"User request: {instruction}",
                        *prior_context_parts[:2],
                        skills_context[:500] if skills_context else None,
                        context.to_prompt_context(),
                    ]
                    if part
                ),
            )
        )
        answer, _ = clean_user_visible_response(answer, user_task=request.task)
    except (ValueError, RuntimeError) as exc:
        answer = f"Could not analyze `{file or 'context'}`: {exc}"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if file:
        read_completed = _activity_event(
            run_id=run_id,
            phase="Reading files",
            label=f"Read {Path(file).name}",
            detail="File context was included in the step observation.",
            status="completed",
            elapsed_ms=elapsed_ms,
            files=[file],
        )
        read_completed.update({"event_type": "file_read_completed", "plan_id": plan_id, "step_id": step_id})
        append_run_event(run_id, read_completed)
    return {
        "step_index": step.get("step_index", 0),
        "file": file,
        "intent": "read",
        "response": answer,
        "elapsed_ms": elapsed_ms,
    }


def _format_plan_summary(
    steps: list[dict[str, Any]],
    results: list[dict[str, Any]],
    request: AgentRunRequest,
) -> str:
    parts: list[str] = [f"Completed {len(steps)} step{'s' if len(steps) != 1 else ''}:\n"]
    for i, (step, result) in enumerate(zip(steps, results)):
        desc = step.get("description", f"Step {i + 1}")
        file = result.get("file") or step.get("file") or ""
        label = f"**Step {i + 1}: {desc}**"
        if result.get("proposal_path"):
            parts.append(f"{label}\n\nModified `{file}` after validation.\n")
        else:
            response = str(result.get("response", "No output."))
            parts.append(f"{label}\n\n{response[:800]}\n")
    return "\n---\n\n".join(parts)


MAX_LOOP_ITERATIONS = 8


def _controller_llm(state: OrchestrationState) -> dict[str, Any]:
    """Controller checkpoint for the agent loop.

    The classifier decides the current task category first; this controller then
    records a task goal and lightweight plan context before the next action is
    selected. Safety-critical validation still happens in the action nodes.
    """
    request = state["request"]
    intent = state.get("intent") or "ambiguous"
    existing_steps = state.get("plan_steps") or []
    if existing_steps:
        plan_steps = existing_steps
    elif intent in {"write_request", "write_confirmation", "file_clarification_answer"}:
        plan_steps = ["Resolve target context", "Draft a safe edit", "Validate the proposed diff"]
    elif intent in {"repo_analysis", "recommend_change_targets", "review_recommendation"}:
        plan_steps = ["Inspect relevant repository context", "Analyze findings", "Recommend next steps"]
    elif intent in {"git_workflow_request", "gitlab_mr_request", "local_command_request"}:
        plan_steps = ["Inspect repository/tool state", "Classify command risk", "Prepare an approval-safe result"]
    elif intent == "apply_spec_to_repo":
        plan_steps = ["Understand the pasted specification", "Identify affected areas", "Present a plan before edits"]
    else:
        plan_steps = ["Load context", "Answer with repository evidence"]

    return {
        "task_goal": request.task[:240],
        "plan_steps": plan_steps,
        "loop_iteration": 1,
        "graph_path": f"{state.get('graph_path', '')}->controller_llm",
    }


def _decide_next_action(state: OrchestrationState) -> dict[str, Any]:
    iteration = int(state.get("loop_iteration") or 0)
    if iteration > MAX_LOOP_ITERATIONS:
        result = _base_response(
            state["request"],
            response=(
                "RepoOperator reached its planning limit for this run. "
                "I kept the observations gathered so far; ask me to continue if you want another pass."
            ),
            response_type="assistant_answer",
            intent_classification=state.get("intent"),
            graph_path="loop_guardrail_max_iterations",
            stop_reason="max_iterations",
            loop_iteration=iteration,
            **_classifier_debug(state),
        )
        return {"result": result, "stop_reason": "max_iterations"}
    return {
        "current_step": _next_action_for_intent(state),
        "graph_path": f"{state.get('graph_path', '')}->decide_next_action",
    }


def _next_action_for_intent(state: OrchestrationState) -> str:
    return _after_classify(state)


def _after_decide_next_action(state: OrchestrationState) -> str:
    if state.get("result") is not None:
        return END
    return str(state.get("current_step") or _next_action_for_intent(state))


def _after_classify(state: OrchestrationState) -> str:
    intent = state.get("intent")
    if state.get("needs_clarification"):
        return "ask_clarification"
    if intent in {"pasted_prompt_or_spec", "apply_spec_to_repo"}:
        return "handle_pasted_spec"
    if intent == "read_only_question":
        return "answer_read_only"
    if intent == "gitlab_mr_request":
        return "run_local_tool_request"
    if intent == "git_workflow_request":
        return "plan_git_workflow"
    if intent == "local_command_request":
        return "run_local_command_request"
    if intent == "review_recommendation":
        return "answer_read_only"
    if intent in {"repo_analysis", "recommend_change_targets"}:
        return "recommend_change_targets"
    if intent == "multi_step_request":
        return "decompose_and_execute"
    if state.get("settings").permission_mode not in {"basic", "auto_review", "full_access"}:
        return "permission_required"
    # File clarification answers already have candidates set — skip context ref resolution
    if intent == "file_clarification_answer":
        return "resolve_target_files"
    if intent == "write_confirmation" and state.get("recommendation_context"):
        return "resolve_recommendation_followup"
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
    graph.add_node("controller_llm", _controller_llm)
    graph.add_node("decide_next_action", _decide_next_action)
    graph.add_node("resolve_context_reference", _resolve_context_reference)
    graph.add_node("resolve_target_files", _resolve_target_files)
    graph.add_node("ask_clarification", _ask_clarification)
    graph.add_node("recommend_change_targets", _recommend_change_targets)
    graph.add_node("handle_pasted_spec", _handle_pasted_spec)
    graph.add_node("resolve_recommendation_followup", _resolve_recommendation_followup)
    graph.add_node("decompose_and_execute", _decompose_and_execute)
    graph.add_node("generate_change_plan", _generate_change_plan)
    graph.add_node("generate_patch", _generate_patch)
    graph.add_node("validate_patch", _validate_patch)
    graph.add_node("return_proposal", _return_proposal)
    graph.add_node("permission_required", _permission_required)
    graph.add_node("proposal_error", _proposal_error)
    graph.add_node("answer_read_only", _answer_read_only)
    graph.add_node("run_local_tool_request", _run_local_tool_request)
    graph.add_node("run_local_command_request", _run_local_command_request)
    graph.add_node("plan_git_workflow", _plan_git_workflow)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "validate_active_repository")
    graph.add_edge("validate_active_repository", "classify_intent")
    graph.add_edge("classify_intent", "controller_llm")
    graph.add_edge("controller_llm", "decide_next_action")
    graph.add_conditional_edges("decide_next_action", _after_decide_next_action)
    graph.add_edge("resolve_context_reference", "resolve_target_files")
    graph.add_conditional_edges("resolve_target_files", _after_resolve)
    graph.add_edge("ask_clarification", END)
    graph.add_edge("recommend_change_targets", END)
    graph.add_edge("handle_pasted_spec", END)
    graph.add_conditional_edges("resolve_recommendation_followup", _after_resolve)
    graph.add_edge("generate_change_plan", "generate_patch")
    graph.add_edge("generate_patch", "validate_patch")
    graph.add_conditional_edges("validate_patch", _after_validate)
    graph.add_edge("return_proposal", END)
    graph.add_edge("permission_required", END)
    graph.add_edge("proposal_error", END)
    graph.add_edge("answer_read_only", END)
    graph.add_edge("run_local_tool_request", END)
    graph.add_edge("run_local_command_request", END)
    graph.add_edge("plan_git_workflow", END)
    graph.add_edge("decompose_and_execute", END)
    return graph


_COMPILED_GRAPH = _build_graph().compile()


def run_agent_orchestration_graph(request: AgentRunRequest) -> AgentRunResponse:
    final_state = _COMPILED_GRAPH.invoke({"request": request})
    result = final_state.get("result")
    if result is None:
        raise RuntimeError("Agent orchestration graph did not produce a result.")
    stop_reason = result.stop_reason or (
        "waiting_for_apply" if result.response_type == "change_proposal" else "completed"
    )
    return result.model_copy(
        update={
            "run_id": result.run_id or f"run-{uuid.uuid4().hex[:12]}",
            "loop_iteration": result.loop_iteration or int(final_state.get("loop_iteration") or 1),
            "stop_reason": stop_reason,
        }
    )


def _activity_for_node(
    node_name: str,
    node_state: dict[str, Any],
    *,
    run_id: str,
    elapsed_ms: int,
) -> dict[str, Any] | None:
    """Map internal graph updates to user-facing agent activity events."""
    phase = "Thinking"
    label = ""
    detail = ""
    files: list[str] = []
    command: str | None = None
    proposal_id: str | None = None
    status = "completed" if node_state.get("result") is not None else "running"

    if node_name == "load_context":
        label = "Loaded thread context"
        detail = "Restored repository, branch, recent files, pending proposals, and skills."
    elif node_name == "validate_active_repository":
        phase = "Repository"
        label = "Validated active repository"
    elif node_name == "classify_intent":
        label = "Understood the task"
        intent = str(node_state.get("intent") or "").replace("_", " ")
        detail = f"Classified as {intent}." if intent else ""
    elif node_name == "controller_llm":
        label = "Planning task"
        steps = node_state.get("plan_steps") or []
        detail = f"Prepared {len(steps)} step{'s' if len(steps) != 1 else ''}." if steps else ""
    elif node_name == "decide_next_action":
        label = "Selected next action"
        detail = "Chose the next safe repository action from the current plan."
    elif node_name == "resolve_context_reference":
        label = "Resolved recent context"
        ref = node_state.get("context_reference")
        ref_files = getattr(ref, "target_files", []) if ref else []
        files = list(ref_files[:4])
        detail = f"Using {files[0]} from recent thread context." if files else "Checked recent files, symbols, and proposals."
    elif node_name == "resolve_target_files":
        phase = "Reading files"
        selected = node_state.get("selected_file")
        label = "Selected target file" if selected else "Checked candidate files"
        files = [selected] if selected else list(node_state.get("candidates") or [])[:4]
        detail = selected or "Waiting for a safe file selection."
    elif node_name == "generate_change_plan":
        phase = "Planning"
        label = "Prepared edit plan"
    elif node_name == "generate_patch":
        phase = "Editing"
        label = "Drafted file changes"
    elif node_name == "validate_patch":
        phase = "Editing"
        label = "Validated proposed edit"
        detail = str(node_state.get("validation_status") or "")
    elif node_name == "return_proposal":
        phase = "Editing"
        label = "Applied validated edit"
        result = node_state.get("result")
        if result:
            proposal_id = (result.edit_archive or [{}])[0].get("proposal_id") if getattr(result, "edit_archive", None) else None
            files = [result.proposal_relative_path] if result.proposal_relative_path else []
    elif node_name == "answer_read_only":
        phase = "Finished"
        label = "Prepared answer"
    elif node_name == "ask_clarification":
        phase = "Finished"
        label = "Need clarification"
        status = "waiting"
    elif node_name == "recommend_change_targets":
        phase = "Planning"
        label = "Identified improvement candidates"
        result = node_state.get("result")
        files = list(getattr(result, "files_read", []) or [])[:6] if result else []
    elif node_name == "handle_pasted_spec":
        phase = "Planning"
        label = "Reviewed pasted specification"
    elif node_name == "resolve_recommendation_followup":
        phase = "Planning"
        label = "Loaded prior recommendations"
    elif node_name == "decompose_and_execute":
        phase = "Planning"
        steps = node_state.get("plan_step_events") or []
        label = "Completed multi-step plan" if steps else "Prepared multi-step plan"
        detail = f"{len(steps)} planned step{'s' if len(steps) != 1 else ''}."
    elif node_name == "run_local_tool_request":
        phase = "Commands"
        label = "Checked GitLab workflow"
        command = "glab mr list"
    elif node_name == "run_local_command_request":
        phase = "Commands"
        label = "Prepared command"
    elif node_name == "plan_git_workflow":
        phase = "Commands"
        label = "Prepared Git workflow"
        planned = node_state.get("commands_planned") or []
        command = planned[0] if planned else None
    elif node_name == "permission_required":
        phase = "Finished"
        label = "Waiting for permission"
        status = "waiting"
    elif node_name == "proposal_error":
        phase = "Editing"
        label = "Could not produce a valid edit"
        status = "failed"
    else:
        return None

    return _activity_event(
        run_id=run_id,
        phase=phase,
        label=label,
        detail=detail,
        status=status,
        elapsed_ms=elapsed_ms,
        files=files,
        command=command,
        proposal_id=proposal_id,
    )


def stream_agent_orchestration_graph(request: AgentRunRequest, *, run_id: str | None = None):
    """Generator that yields JSON-encoded SSE event payloads for LangGraph progress."""
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    initial_state: dict[str, Any] = {"request": request, "run_id": run_id}
    accumulated_result: AgentRunResponse | None = None
    started = time.perf_counter()
    last_activity_elapsed_ms = 0
    activity_events: list[dict[str, Any]] = []

    try:
        for update in _COMPILED_GRAPH.stream(initial_state, stream_mode="updates"):
            node_name = next(iter(update)) if update else None
            if not node_name:
                continue
            node_state: dict[str, Any] = update.get(node_name) or {}

            if "result" in node_state and node_state["result"] is not None:
                accumulated_result = node_state["result"]

            payload = _activity_for_node(
                node_name,
                node_state,
                run_id=run_id,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
            if payload:
                elapsed_ms = int(payload.get("elapsed_ms") or 0)
                payload["duration_ms"] = max(0, elapsed_ms - last_activity_elapsed_ms)
                last_activity_elapsed_ms = elapsed_ms
                if activity_events and activity_events[-1].get("status") == "running":
                    activity_events[-1] = {
                        **activity_events[-1],
                        "status": "completed",
                        "ended_at": payload.get("started_at") or _utc_now(),
                    }
                activity_events.append(payload)
                yield json.dumps(payload)

    except Exception as exc:
        logger.exception("Streaming graph error: %s", exc)
        yield json.dumps({"type": "error", "message": str(exc)})
        return

    if accumulated_result is not None:
        activity_events = _finalize_activity_events(activity_events)
        stop_reason = accumulated_result.stop_reason or (
            "waiting_for_apply"
            if accumulated_result.response_type == "change_proposal"
            else "completed"
        )
        accumulated_result = accumulated_result.model_copy(
            update={
                "run_id": accumulated_result.run_id or run_id,
                "activity_events": activity_events,
                "loop_iteration": accumulated_result.loop_iteration or 1,
                "stop_reason": stop_reason,
            }
        )
        if accumulated_result.reasoning:
            yield json.dumps(
                {
                    "type": "reasoning_delta",
                    "delta": accumulated_result.reasoning,
                    "source": "model_provided",
                }
            )
        for chunk in _chunk_stream_text(accumulated_result.response):
            yield json.dumps({"type": "assistant_delta", "delta": chunk})
        yield json.dumps({"type": "final_message", "result": accumulated_result.model_dump()})
    else:
        yield json.dumps({"type": "error", "message": "Agent did not produce a result."})


def _progress_phase_for_node(node_name: str) -> str:
    if node_name in {"load_context", "validate_active_repository", "classify_intent", "resolve_context_reference"}:
        return "context"
    if node_name in {"resolve_target_files", "ask_clarification"}:
        return "file_read"
    if node_name in {"generate_change_plan", "recommend_change_targets", "decompose_and_execute", "plan_step"}:
        return "planning"
    if node_name in {"run_local_tool_request", "run_local_command_request", "plan_git_workflow"}:
        return "commands"
    if node_name in {"generate_patch", "validate_patch", "return_proposal", "proposal_error"}:
        return "diff_generation"
    return "final_answer"


def _chunk_stream_text(text: str, *, chunk_size: int = 96):
    for start in range(0, len(text or ""), chunk_size):
        chunk = text[start : start + chunk_size]
        if chunk:
            yield chunk


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


def _normalize_analysis_scope(value: Any) -> str:
    scope = str(value or "unknown").strip()
    if scope in {"single_file", "selected_files", "repository_wide", "unknown"}:
        return scope
    return "unknown"


def _normalize_requested_workflow(value: Any) -> str:
    workflow = str(value or "other").strip()
    if workflow in {"repository_review", "file_review", "code_change", "git_workflow", "command", "other"}:
        return workflow
    return "other"


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
    if _looks_like_structured_external_spec(request.task):
        return _classification_payload(
            intent="pasted_prompt_or_spec",
            confidence=0.6,
            requested_action="handle_pasted_spec",
            analysis_scope="unknown",
            requested_workflow="other",
            classifier="deterministic_fallback",
        )
    if pending.get("candidates") and _matches_pending_candidate(request.task, pending["candidates"]):
        return _classification_payload(
            intent="file_clarification_answer",
            confidence=0.7,
            requested_action="select_candidate",
            analysis_scope="selected_files",
            requested_workflow="code_change",
            classifier="deterministic_fallback",
        )
    if file_hints:
        return _classification_payload(
            intent="write_request",
            confidence=0.55,
            target_files=file_hints,
            requested_action="edit_file",
            analysis_scope="selected_files",
            requested_workflow="code_change",
            classifier="deterministic_fallback",
        )
    if "mr" in lowered or "merge request" in lowered:
        return _classification_payload(
            intent="gitlab_mr_request",
            confidence=0.55,
            requested_action="list_merge_requests",
            needs_tool="glab",
            analysis_scope="unknown",
            requested_workflow="git_workflow",
            classifier="deterministic_fallback",
        )
    return _classification_payload(
        intent="ambiguous",
        confidence=0.2,
        requested_action="clarify_analysis_scope",
        analysis_scope="unknown",
        requested_workflow="other",
        needs_clarification=True,
        clarification_question="Do you want a whole-repository review, or should I inspect specific files?",
        classifier="deterministic_fallback",
    )


def _looks_like_structured_external_spec(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(text) < 900 or len(lines) < 12:
        return False
    structural_lines = sum(
        1
        for line in lines
        if line.startswith(("#", "-", "*"))
        or re.match(r"^\d+[\.)]\s+", line)
        or line.endswith(":")
    )
    imperative_blocks = sum(1 for line in lines if len(line.split()) >= 4 and line[0].isupper())
    return structural_lines >= 5 and imperative_blocks >= 3


def _classification_payload(
    *,
    intent: str,
    confidence: float,
    target_files: list[str] | None = None,
    target_symbols: list[str] | None = None,
    requested_action: str,
    needs_tool: str | None = None,
    classifier: str,
    analysis_scope: str = "unknown",
    requested_workflow: str = "other",
    requires_repository_wide_review: bool = False,
    needs_clarification: bool = False,
    clarification_question: str | None = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "confidence": confidence,
        "analysis_scope": analysis_scope,
        "requested_workflow": requested_workflow,
        "requires_repository_wide_review": requires_repository_wide_review,
        "target_files": target_files or [],
        "target_symbols": target_symbols or [],
        "requested_action": requested_action,
        "needs_tool": needs_tool,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "classifier": classifier,
    }


def _find_previous_write_instruction(request: AgentRunRequest) -> str | None:
    for message in reversed(request.conversation_history):
        if message.role == "user":
            return message.content
    return None
