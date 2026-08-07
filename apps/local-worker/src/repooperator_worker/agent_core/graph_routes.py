from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.planner import (
    _has_action,
    _has_command_preview,
    _has_command_run,
    _has_search_for,
    _latest_command_preview,
    _latest_unrun_read_only_preview,
    _preview_read_only,
    build_task_frame,
    candidate_files_from_results,
    command_needed_for_task,
    current_edit_target_files,
    current_search_candidate_files,
    edit_requested,
    emit_target_resolution,
    known_context_files,
    pending_commit_context,
    propose_next_action_with_model,
    project_summary_files,
    resolve_target_files,
)
from repooperator_worker.agent_core.graph import support as graph_support
from repooperator_worker.agent_core.state import AgentCoreState
from repooperator_worker.agent_core.task_policy import (
    block_current_subtask,
    ensure_subtasks,
    minimum_evidence_missing_for_task,
    next_evidence_gathering_action,
    next_recovery_action,
    should_ask_clarification_now,
)
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.json_safe import json_safe


def choose_graph_next_action(state: AgentCoreState, request: AgentRunRequest) -> AgentAction:
    frame = build_task_frame(request, state)
    ensure_subtasks(state, request, frame)
    state.recommendation_context = json_safe({"task_frame": frame, "context_packet": state.context_packet})

    if state.actions_taken and state.action_results:
        previous_action = state.actions_taken[-1]
        previous_result = state.action_results[-1]
        if _is_ineffective_graph_result(previous_action, previous_result):
            recovery = next_recovery_action(state, request, frame, previous_action, previous_result)
            if recovery and not _repeats_graph_action(state, recovery):
                return recovery

    for chooser in (
        _next_approved_write_done_action,
        _next_off_topic_answer_action,
        _next_meta_answer_action,
        _next_web_fetch_action,
        _next_missing_file_action,
        _next_git_commit_action,
        _next_git_branch_action,
        # Before any model-driven chooser: an explicitly requested command
        # ("python calc.py 실행해줘") must reach the preview/approval flow —
        # model paths kept answering or editing instead of running it.
        _next_command_action,
        _next_mentioned_files_covered_action,
        _next_tool_calling_action,
        _next_explicit_target_action,
        _next_symbol_action,
        _next_policy_evidence_action,
        _next_model_planner_action,
        _next_search_candidate_action,
        _next_edit_action,
        _next_project_summary_action,
    ):
        action = chooser(state, request, frame)
        if action and not _repeats_graph_action(state, action):
            return _with_edit_targets_filled(action, state, request, frame)

    return AgentAction(type="final_answer", reason_summary="Enough evidence is available for a grounded answer.")


def _with_edit_targets_filled(action: AgentAction, state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction:
    """A model-proposed generate_edit/generate_change_set often arrives without
    target_files — the tool then loops over nothing and 'skips' in a second.
    Fill the targets from the resolved edit targets or the files already read."""
    if action.type not in {"generate_edit", "generate_change_set"}:
        return action
    if action.target_files or (action.payload or {}).get("target_files"):
        return action
    targets = current_edit_target_files(state, frame, request)
    if not targets:
        # The model may call generate_edit before any file was read — resolve
        # the files the user actually named.
        try:
            targets = resolve_target_files(request, getattr(frame, "mentioned_files", []) or [], preferred=known_context_files(request, state))
        except Exception:
            targets = []
    if not targets:
        targets = [path for path in getattr(state, "files_read", []) or [] if "." in Path(path).name][:4]
    if not targets:
        return action
    action.target_files = list(targets)
    if isinstance(action.payload, dict):
        action.payload.setdefault("target_files", list(targets))
    return action


def _next_approved_write_done_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """An explicitly approved direct file write just succeeded — the task is
    done. Without this the loop wandered into the change-set flow against the
    already-written file and reported a failure for work that succeeded."""
    results = getattr(state, "action_results", []) or []
    if not results:
        return None
    latest = results[-1]
    if getattr(latest, "status", "") != "success":
        return None
    payload = getattr(latest, "payload", None) or {}
    actions = getattr(state, "actions_taken", []) or []
    last_type = str(getattr(actions[-1], "type", "") or "") if actions else ""
    if last_type in {"create_file", "modify_file", "delete_file", "rename_file"} and payload.get("approved"):
        return AgentAction(type="final_answer", reason_summary="The approved file write completed; report the result.")
    return None


def _next_off_topic_answer_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """Obvious small talk (weather, news…) — answer the scope politely at once
    instead of grinding the repo-analysis loop for minutes."""
    from repooperator_worker.agent_core.intent import is_off_topic_request

    if getattr(state, "actions_taken", None) or getattr(state, "files_read", None):
        return None
    if is_off_topic_request(getattr(request, "task", "") or ""):
        return AgentAction(
            type="final_answer",
            reason_summary="Off-topic request — explain the agent's scope.",
            payload={"off_topic": True},
        )
    return None


def _next_missing_file_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """User explicitly named files that don't exist in the repo — say so honestly
    instead of answering something else.

    Uses the same fuzzy resolution as the explicit-target flow (a bare
    "Border.cs" resolving to "Assets/Scripts/Border.cs" is NOT missing); only
    fires when resolution finds nothing at all for the named files.
    """
    # A task carrying a URL is a web-fetch task; URL path segments look like
    # filenames ("peps/pep-0020.rst") and must not trigger the missing-file flow.
    from repooperator_worker.agent_core.intent import extract_urls

    if extract_urls(getattr(request, "task", "") or ""):
        return None
    # A create request ("utils.py 파일을 새로 만들어서 …", "create a new config.json")
    # names a file that SHOULD NOT exist yet — that is not a missing file, it is
    # the edit flow's job. Don't hijack it with "utils.py 파일을 찾지 못했어요".
    task_text = str(getattr(request, "task", "") or "")
    if re.search(r"만들어|만들 |생성해|생성하|새로 |새 파일|create|new file", task_text, re.IGNORECASE):
        return None
    mentioned = [str(f).strip().lstrip("/") for f in getattr(frame, "mentioned_files", []) or [] if str(f).strip()]
    # Only treat tokens that look like real filenames (have an extension) as
    # explicit targets. Bare words such as "README" or "코드" in a sentence
    # ("README와 코드를 읽고 설명해줘") are topics, not missing files.
    mentioned = [f for f in mentioned if "." in Path(f).name]
    if not mentioned:
        return None
    try:
        resolved = resolve_target_files(request, mentioned, preferred=known_context_files(request, state))
    except Exception:
        return None
    if resolved:
        return None
    # Contract: search the repository for the missing names first (the file may
    # exist under another path); only ask once the search came up empty.
    searched = any(getattr(a, "type", None) == "search_files" for a in getattr(state, "actions_taken", []) or [])
    if not searched:
        return AgentAction(
            type="search_files",
            reason_summary="Search for the named files before concluding they are missing.",
            payload={"queries": [Path(f).name for f in mentioned]},
        )
    return AgentAction(
        type="ask_clarification",
        reason_summary="Named files do not exist in this repository.",
        payload={"missing_files": mentioned},
    )


def _next_meta_answer_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """Meta / capability question ("what can you do?") — answer immediately about
    the agent instead of running the repo-analysis loop. Finalization fills the
    text via intent.capability_answer."""
    from repooperator_worker.agent_core.intent import is_meta_request

    if getattr(state, "actions_taken", None) or getattr(state, "files_read", None):
        return None
    if is_meta_request(getattr(request, "task", "") or ""):
        return AgentAction(
            type="final_answer",
            reason_summary="Meta/capability question — describe what the agent can do.",
        )
    return None


_GIT_COMMIT_INTENT_RE = __import__("re").compile(
    r"커밋\s*해|커밋해|커밋하고|커밋으로|메시지로\s*커밋|make a commit|commit (the|these|this|my|current)|커밋\s*좀",
    __import__("re").IGNORECASE,
)


_GIT_BRANCH_CREATE_RE = re.compile(r"(?:브랜치|branch)", re.IGNORECASE)
_GIT_BRANCH_CREATE_VERB_RE = re.compile(r"만들|생성|create|new", re.IGNORECASE)


def _next_git_branch_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """"feature/x 브랜치 만들어줘" goes straight to the gated git_branch_create
    tool — the model narrated branch creation without ever running git."""
    task = str(getattr(request, "task", "") or "")
    if not (_GIT_BRANCH_CREATE_RE.search(task) and _GIT_BRANCH_CREATE_VERB_RE.search(task)):
        return None
    if any(getattr(a, "type", None) == "git_branch_create" for a in getattr(state, "actions_taken", []) or []):
        return None
    name = ""
    quoted = re.search(r"['\"`]([\w./-]+)['\"`]", task)
    if quoted:
        name = quoted.group(1)
    if not name:
        slashed = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)\b", task)
        if slashed:
            name = slashed.group(1)
    if not name:
        named = re.search(r"([A-Za-z0-9_.-]{2,})\s*(?:라는|이라는|이란|란)", task)
        if named:
            name = named.group(1)
    if not name:
        return None
    return AgentAction(
        type="git_branch_create",
        reason_summary=f"Create the requested branch {name} through the gated git tool.",
        expected_output="Branch creation result.",
        payload={"branch": name, "name": name},
    )


def _next_git_commit_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """Explicit "commit this" requests go straight to the approval-gated
    git_commit tool. Without this the model wandered into the edit path and
    tried to build an (empty) patch instead of committing."""
    task = str(getattr(request, "task", "") or "")
    if not _GIT_COMMIT_INTENT_RE.search(task):
        return None
    # Combined requests ("최근 커밋 보여줘. 커밋해줘.") need the read part first —
    # the regular flow already sequences those correctly, so only take over for
    # a pure commit request.
    if __import__("re").search(r"보여줘|이력|로그|내역|history|show|\blog\b", task, __import__("re").IGNORECASE):
        return None
    if any(getattr(a, "type", None) == "git_commit" for a in getattr(state, "actions_taken", []) or []):
        return None
    import re as _re

    quoted = _re.search(r"['\"‘“]([^'\"’”]{2,72})['\"’”]", task)
    if quoted:
        message = quoted.group(1).strip()
    else:
        # No explicit message — derive one from what actually changed instead
        # of committing the request sentence itself ("방금 변경사항을 적당한
        # 메시지로 커밋해줘" ended up verbatim in git log).
        message = _derived_commit_message(request) or "Apply RepoOperator change set"
    return AgentAction(
        type="git_commit",
        reason_summary="User asked to commit the current changes (approval-gated).",
        payload={"message": message, "stage_all": True},
    )


def _derived_commit_message(request: AgentRunRequest) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(getattr(request, "project_path", "") or "."), "status", "--short"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return None
    files = [line[3:].strip() for line in out.splitlines() if line.strip()][:4]
    if not files:
        return None
    return "Update " + ", ".join(files)


def _next_web_fetch_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """If the task contains a URL, fetch it (once) instead of defaulting to
    reading local repo files. Approval-gated by the fetch_url tool policy."""
    from repooperator_worker.agent_core.intent import extract_urls

    urls = extract_urls(getattr(request, "task", "") or "")
    if not urls:
        return None
    for action in getattr(state, "actions_taken", []) or []:
        if getattr(action, "type", None) == "fetch_url":
            return None
    url = urls[0]
    return AgentAction(
        type="fetch_url",
        reason_summary=f"Fetch the URL the user asked about: {url}",
        expected_output="Fetched page content as untrusted evidence.",
        payload={"url": url},
    )


def _next_mentioned_files_covered_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """The user asked about specific files and every one of them has been read —
    answer now instead of letting the model wander until the loop budget dies
    ("read calc.py, big_module.py … max_loop_iterations")."""
    mentioned = [str(f).strip().lstrip("/") for f in getattr(frame, "mentioned_files", []) or [] if str(f).strip()]
    mentioned = [f for f in mentioned if "." in Path(f).name]
    # Use the BROAD edit signal here (text + hints + requested outputs): for
    # this chooser a false positive merely defers to the normal flow, while a
    # miss would cut off a legitimate edit run with a premature answer.
    if not mentioned or edit_requested(frame):
        return None
    # "python calc.py 실행해줘" mentions calc.py, but reading it is not the
    # task — the requested command still has to run (or reach its approval
    # gate) before wrapping up.
    if command_needed_for_task(frame, state):
        return None
    files_read = set(getattr(state, "files_read", []) or [])
    try:
        resolved = resolve_target_files(request, mentioned, preferred=known_context_files(request, state))
    except Exception:
        resolved = mentioned
    if not resolved or not set(resolved).issubset(files_read):
        return None
    if len(getattr(state, "actions_taken", []) or []) < 2:
        return None
    return AgentAction(
        type="final_answer",
        reason_summary="All files the user asked about have been read — answer from that evidence.",
    )


def _next_tool_calling_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    """Model-driven native tool-calling planner (primary when enabled)."""

    from repooperator_worker.agent_core.agentic_loop import propose_next_action_with_tool_calling

    return propose_next_action_with_tool_calling(request, state, frame)


def _next_explicit_target_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
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

    unresolved = [
        item
        for item in frame.mentioned_files
        if item and not any(Path(path).name.lower() == Path(item).name.lower() or path.lower() == item.lower() for path in resolved)
    ]
    if unresolved and not _has_search_for(state, unresolved):
        return AgentAction(
            type="search_files",
            reason_summary="Resolve mentioned files before asking for clarification.",
            expected_output="Repo-relative candidate paths.",
            payload={"queries": unresolved},
        )

    explicit_candidates = current_search_candidate_files(state, min_score=35.0)
    explicit_candidate_unread = [
        path
        for path in explicit_candidates
        if path not in state.files_read and any(Path(path).name.lower() == Path(item).name.lower() for item in unresolved)
    ]
    if explicit_candidate_unread:
        return AgentAction(
            type="read_file",
            reason_summary="Read the resolved high-confidence target file.",
            target_files=explicit_candidate_unread[:1],
            expected_output="File contents for grounded answer.",
        )

    if frame.mentioned_files and resolved and all(path in state.files_read for path in resolved) and not edit_requested(frame):
        return AgentAction(type="final_answer", reason_summary="Answer from the explicitly requested file evidence.")

    if unresolved and _has_search_for(state, unresolved):
        return _clarification_action(state, request, frame, missing_files=unresolved)
    return None


def _next_symbol_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    del request
    if frame.mentioned_symbols and not state.files_read and not _has_search_for(state, frame.mentioned_symbols):
        return AgentAction(
            type="search_files",
            reason_summary="Resolve mentioned symbols before answering.",
            target_symbols=frame.mentioned_symbols,
            expected_output="Repo-relative candidate paths.",
            payload={"queries": frame.mentioned_symbols},
        )
    return None


def _next_policy_evidence_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    evidence_action = next_evidence_gathering_action(state, request, frame)
    if evidence_action:
        return evidence_action
    if should_ask_clarification_now(state, request, frame):
        return _clarification_action(state, request, frame)
    return None


def _next_model_planner_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    return propose_next_action_with_model(
        request,
        state,
        frame,
        model_client_factory=graph_support.OpenAICompatibleModelClient,
    )


def _next_command_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    del request
    unrun_preview = _latest_unrun_read_only_preview(state)
    if unrun_preview:
        return AgentAction(
            type="run_approved_command",
            reason_summary="Run read-only command after policy preview.",
            command=list(unrun_preview.command_result.get("command") or []),
            expected_output="Command output for the user request.",
        )
    command = command_needed_for_task(frame, state)
    if not command:
        return None
    if not _has_command_preview(state, command):
        return AgentAction(
            type="inspect_git_state" if command[:1] == ["git"] else "preview_command",
            reason_summary="Preview the safe command needed for missing evidence.",
            command=command,
            expected_output="Command safety classification.",
        )
    preview = _latest_command_preview(state, command)
    preview_auto = bool(preview and isinstance(preview.command_result, dict) and preview.command_result.get("auto_approved_by_mode"))
    if preview and preview.status == "success" and (_preview_read_only(preview.command_result) or preview_auto) and not _has_command_run(state, command):
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


def _next_search_candidate_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    del request
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
    return None


_CREATION_INTENT_RE = re.compile(r"만들어|만들 |생성해|생성하|새로 |새 파일|create|new file", re.IGNORECASE)


def _creation_target_file(request: AgentRunRequest, frame: Any) -> str | None:
    """The named file for an explicit create request, if it doesn't exist yet."""
    task = str(getattr(request, "task", "") or "")
    if not _CREATION_INTENT_RE.search(task):
        return None
    for item in getattr(frame, "mentioned_files", []) or []:
        name = str(item).strip().lstrip("/")
        if not name or "." not in Path(name).name:
            continue
        try:
            resolved = resolve_target_files(request, [name])
        except Exception:
            resolved = []
        if not resolved:
            return name
    return None


def _edit_generation_came_up_empty(state: AgentCoreState) -> bool:
    """The latest generate_edit attempt produced zero proposals."""
    actions = list(getattr(state, "actions_taken", []) or [])
    results = list(getattr(state, "action_results", []) or [])
    for action, result in zip(reversed(actions[-len(results):] if results else []), reversed(results)):
        if str(getattr(action, "type", "") or "") not in {"generate_edit", "generate_change_set"}:
            continue
        payload = getattr(result, "payload", None) or {}
        if payload.get("edit_proposals") or (payload.get("change_set_proposal") or {}).get("changes"):
            return False
        return getattr(result, "status", "") in {"skipped", "failed"}
    return False


def _next_edit_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    if not edit_requested(frame):
        return None
    # A plan request ("…계획을 세워줘") must answer with the plan; generating a
    # patch here would skip the user's approval of the approach.
    from repooperator_worker.agent_core.intent import is_planning_request

    if is_planning_request(str(getattr(request, "task", "") or "")):
        return None
    edit_targets = current_edit_target_files(state, frame, request)
    if not edit_targets:
        creation_target = _creation_target_file(request, frame)
        if creation_target:
            # "utils.py 파일을 새로 만들어서 …" — the named file SHOULD NOT exist,
            # so target resolution finds nothing. Drive a create-operation
            # change set instead of asking the user what they meant.
            edit_targets = [creation_target]
    if edit_targets:
        if not (_has_action(state, "generate_change_set") or _has_action(state, "generate_edit")):
            return AgentAction(
                type="generate_edit",
                reason_summary="Prepare a ChangeSetProposal for validated current edit targets.",
                target_files=edit_targets,
                expected_output="Validated ChangeSetProposal with before/after diff summary.",
                payload={"task_frame": json_safe(frame), "current_edit_targets": edit_targets},
            )
        if _edit_generation_came_up_empty(state) and not _has_action(state, "generate_change_set"):
            # generate_edit ran but produced nothing (skipped) — retry through
            # the change-set pipeline, which has repair + per-file fallback,
            # before giving up. Answering here narrated an edit that never
            # happened ("주석을 추가했습니다" with zero proposals).
            return AgentAction(
                type="generate_change_set",
                reason_summary="Retry proposal generation through the change-set pipeline after an empty edit attempt.",
                target_files=edit_targets,
                expected_output="Validated ChangeSetProposal with per-file changes.",
                payload={"target_files": edit_targets, "task_frame": json_safe(frame)},
            )
        return AgentAction(type="final_answer", reason_summary="Report the proposed edit without claiming it was applied.")
    return _clarification_action(state, request, frame)


def _next_project_summary_action(state: AgentCoreState, request: AgentRunRequest, frame: Any) -> AgentAction | None:
    del frame
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
    return None


def _clarification_action(state: AgentCoreState, request: AgentRunRequest, frame: Any, *, missing_files: list[str] | None = None) -> AgentAction:
    missing = missing_files or minimum_evidence_missing_for_task(state, request, frame)
    checked = _checked_evidence_summary(state)
    question = _clarification_question(missing, checked, frame)
    block_current_subtask(state, question)
    payload: dict[str, Any] = {"question": question, "missing_evidence": missing, "checked_evidence": checked}
    if state.edit_target_candidates:
        payload["candidate_files_considered"] = [
            {
                "path": item.get("path"),
                "score": item.get("score"),
                "role": item.get("role"),
                "already_read": item.get("already_read"),
                "blocked_reason": item.get("blocked_reason"),
            }
            for item in state.edit_target_candidates[:8]
            if isinstance(item, dict)
        ]
    if missing_files:
        payload["missing_files"] = missing_files
    return AgentAction(
        type="ask_clarification",
        reason_summary="Ask a precise clarification after safe evidence gathering did not resolve the target.",
        payload=payload,
    )


def _repeats_graph_action(state: AgentCoreState, action: AgentAction) -> bool:
    signature = _graph_action_signature(action)
    if not signature:
        return False
    ineffective = 0
    for previous, result in zip(state.actions_taken, state.action_results):
        if _graph_action_signature(previous) != signature:
            continue
        if _is_ineffective_graph_result(previous, result):
            ineffective += 1
    return ineffective >= 1


def _graph_action_signature(action: AgentAction) -> tuple[str, str] | None:
    if action.type == "search_text":
        return (action.type, _normalize_search_query(action.payload.get("query") or ""))
    if action.type == "search_files":
        queries = [_normalize_search_query(item) for item in action.payload.get("queries") or [] if _normalize_search_query(item)]
        text_queries = [_normalize_search_query(item) for item in action.payload.get("text_queries") or [] if _normalize_search_query(item)]
        return (action.type, "|".join([*queries, *text_queries]))
    if action.type == "read_file":
        return (action.type, "|".join(sorted(action.target_files)))
    if action.command:
        return (action.type, shlex.join(action.command))
    return None


def _is_ineffective_graph_result(action: AgentAction, result: ActionResult) -> bool:
    if result.status in {"failed", "skipped", "timed_out"}:
        return True
    if action.type == "search_files":
        return not bool(result.payload.get("candidates"))
    if action.type == "search_text":
        return not bool(result.payload.get("matches"))
    return False


def _checked_evidence_summary(state: AgentCoreState) -> list[str]:
    checked: list[str] = []
    if any(action.type == "inspect_repo_tree" for action in state.actions_taken):
        checked.append("repository structure")
    searched: list[str] = []
    for action in state.actions_taken:
        if action.type == "search_files":
            searched.extend(str(item) for item in [*(action.payload.get("queries") or []), *(action.payload.get("text_queries") or [])] if str(item))
        elif action.type == "search_text":
            query = str(action.payload.get("query") or "")
            if query:
                searched.append(query)
    if searched:
        checked.append("searches: " + ", ".join(_dedupe_text(searched[:8])))
    if state.files_read:
        checked.append("files read: " + ", ".join(state.files_read[-8:]))
    return checked


def _clarification_question(missing: list[str], checked: list[str], frame: Any) -> str:
    missing_text = "; ".join(missing) if missing else "the remaining target or scope"
    checked_text = "; ".join(checked) if checked else "no repository evidence could be gathered"
    if edit_requested(frame):
        return (
            "I could not identify a safe implementation target from the repository evidence. "
            f"Checked: {checked_text}. Missing: {missing_text}. "
            "Please name the file, module, route, handler, or component that should own the change."
        )
    return (
        "I need one more detail before I can answer accurately. "
        f"Checked: {checked_text}. Missing: {missing_text}. "
        "Please narrow the file, module, or workflow to inspect next."
    )


def _normalize_search_query(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _dedupe_text(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
