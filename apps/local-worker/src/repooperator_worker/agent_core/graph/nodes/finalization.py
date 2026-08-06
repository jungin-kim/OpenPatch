"""Finalization nodes and response adapters for RepoOperator LangGraph."""

from __future__ import annotations

import difflib
import re
from typing import Any

from repooperator_worker.agent_core.graph.adapters import (
    _core_state_from_graph,
    _graph_transition_event,
    _invoke_subgraph_delta,
    _merge_updates,
    _pending_action,
    _request,
    _task_frame,
    _with_checkpoint_bump,
)
from repooperator_worker.agent_core.graph.nodes.context import refresh_context_pack_update
from repooperator_worker.agent_core.graph.state import RepoOperatorGraphState
from repooperator_worker.agent_core.graph_state import response_to_snapshot
from repooperator_worker.agent_core.graph.nodes.web import _web_source_notes_for_final
from repooperator_worker.agent_core.graph.final_answer_support import build_final_answer_text, build_final_response
from repooperator_worker.agent_core.final_synthesis import validate_or_repair_final_answer
from repooperator_worker.agent_core.events import normalize_validation_result
from repooperator_worker.agent_core.understanding_context import append_visible_rationale, build_evidence_basis, evidence_basis_update
from repooperator_worker.schemas import AgentRunResponse
from repooperator_worker.services.event_service import append_run_event
from repooperator_worker.services.json_safe import json_safe

def ask_clarification_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    action = _pending_action(state)
    request = _request(state)
    core = _core_state_from_graph(state)
    korean = _task_is_korean(request)
    missing = ", ".join(action.payload.get("missing_files") or []) if action else ""
    final_response = (
        action.payload.get("question")
        if action
        else None
    ) or core.classifier_result.clarification_question or (
        (
            f"{missing} 파일을 찾지 못했어요. 정확한 경로를 알려주시거나 제가 찾은 후보 중에서 골라주시겠어요?"
            if korean
            else f"I could not find {missing}. Please confirm the repo-relative path or choose one of the candidates I found."
        )
        if missing
        else (
            "어떤 파일이나 작업을 원하시는지 조금 더 구체적으로 알려주시겠어요?"
            if korean
            else "Could you clarify which files or workflow you want me to inspect?"
        )
    )
    # The model sometimes puts its *reasoning* in the question slot ("구체적인
    # 설명이 부족하여 clarifying question를 던져야 합니다"). A clarification the
    # user sees must actually ask something — if it doesn't, ask a real question.
    final_response = _ensure_actual_question(str(final_response), request, korean=korean)
    del request
    update = {
            "stop_reason": "needs_clarification",
            "final_response": final_response,
            "events_to_emit": [
                _graph_transition_event(state, "ask_clarification", operation="clarification", action_type="ask_clarification")
            ],
        }
    update = _merge_updates(
        update,
        append_visible_rationale(
            state,
            node="ask_clarification",
            action=action,
            summary="The available request context is still ambiguous, so I am asking for clarification instead of guessing.",
            basis_refs=[],
            safety_note="Clarifying preserves tool safety and avoids writing or claiming unsupported work.",
            uncertainty=[final_response],
        ),
    )
    return _with_checkpoint_bump(update)

def final_synthesis_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    from repooperator_worker.agent_core.graph.builder import build_finalization_graph

    context_update = refresh_context_pack_update(state, trigger_node="final_synthesis")
    working_state = {**dict(state), **{key: value for key, value in context_update.items() if key != "events_to_emit"}}
    update = _invoke_subgraph_delta(build_finalization_graph, working_state)
    next_state = _merge_updates(working_state, update)
    update = _merge_updates(update, evidence_basis_update(next_state, trigger_node="final_synthesis"))
    update = _merge_updates(
        update,
        append_visible_rationale(
            next_state,
            node="final_synthesis",
            action=None,
            summary="I am synthesizing the final answer from the current understanding, evidence basis, validation status, and proposal state.",
            basis_refs=[{"kind": "file", "path": path} for path in (next_state.get("files_read") or [])[:8]],
            safety_note="The final answer may cite evidence but must not dump raw context or non-public reasoning.",
            uncertainty=[],
        ),
    )
    update.setdefault("events_to_emit", []).append(
        _graph_transition_event(state, "final_synthesis", subgraph="finalization_graph", operation="final_synthesis")
    )
    return _with_checkpoint_bump(_merge_updates(context_update, update))

def final_quality_guard_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    return {
        "events_to_emit": [_graph_transition_event(state, "quality_guard", subgraph="finalization_graph", operation="quality_guard")]
    }

def final_repair_answer_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    return {
        "events_to_emit": [_graph_transition_event(state, "repair_final_answer", subgraph="finalization_graph", operation="repair_final_answer")]
    }

def final_build_response_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    request = _request(state)
    core = _core_state_from_graph(state)
    # Meta / capability question ("what can you do?") — answer about the agent
    # itself instead of forcing a repository summary. Off-topic small talk gets
    # a polite scope answer immediately.
    if not core.final_response:
        from repooperator_worker.agent_core.intent import (
            capability_answer,
            is_meta_request,
            is_off_topic_request,
            off_topic_answer,
        )

        task_text = str(getattr(request, "task", "") or "")
        if is_off_topic_request(task_text):
            core.final_response = off_topic_answer(_task_is_korean(request))
        elif is_meta_request(task_text) and not getattr(core, "files_changed", None):
            repo_name = str(getattr(request, "project_path", "") or "").rstrip("/").split("/")[-1] or None
            core.final_response = capability_answer(repo_name)
    proposal = state.get("change_set_proposal") if isinstance(state.get("change_set_proposal"), dict) else None
    if proposal and proposal.get("changes") and proposal.get("status") in {"invalid", "repairable", "blocked"}:
        validation = proposal.get("validation") if isinstance(proposal.get("validation"), dict) else {}
        errors = "; ".join(str(item) for item in validation.get("errors") or [proposal.get("proposal_error")] if item)
        # Speak the user's language and propose the next step instead of dumping
        # an internal validation error.
        attempted = [str(c.get("path")) for c in proposal.get("changes") or [] if isinstance(c, dict) and c.get("path")]
        real_files = [str(item) for item in (state.get("files_read") or [])][:5]
        if _task_is_korean(request):
            core.final_response = (
                "제안한 변경을 검증하는 과정에서 문제가 있어 파일을 수정하지 않았습니다.\n\n"
                + (f"- 시도한 대상: {', '.join(attempted[:5])}\n" if attempted else "")
                + (f"- 이 저장소에서 확인된 파일: {', '.join(real_files)}\n" if real_files else "")
                + f"- 원인: {errors or '알 수 없는 검증 오류'}\n\n"
                "수정할 파일을 지정해서 다시 요청해 주시겠어요? (예: \"main.py에 실명 메시지 명령어 추가해줘\")"
            )
        else:
            core.final_response = (
                "I prepared a change but its validation failed, so no files were modified.\n\n"
                + (f"- Attempted targets: {', '.join(attempted[:5])}\n" if attempted else "")
                + (f"- Files that exist here: {', '.join(real_files)}\n" if real_files else "")
                + f"- Reason: {errors or 'unknown validation error'}\n\n"
                "Could you point me at the file to change and ask again? (e.g. \"add the command to main.py\")"
            )
    if not core.final_response:
        on_delta = _stream_final_delta(core.run_id) if state.get("stream_final_answer") else None
        packet_context = ""
        if isinstance(core.context_packet, dict):
            packet_context = str(core.context_packet.get("skills_context") or "")
        core.final_response = build_final_answer_text(
            core,
            request,
            skills_context=packet_context or str(state.get("skills_context") or ""),
            on_delta=on_delta,
        )
    draft_response = core.final_response
    core.final_response = validate_or_repair_final_answer(core.final_response, core, request)
    # Deterministic scope/meta answers are canonical — re-apply them after the
    # evidence repair, which otherwise replaces them with "need more files"
    # boilerplate (an off-topic answer legitimately has zero file evidence).
    from repooperator_worker.agent_core.intent import is_off_topic_request as _is_off_topic

    if _is_off_topic(str(getattr(request, "task", "") or "")):
        from repooperator_worker.agent_core.intent import off_topic_answer as _off_topic_answer

        core.final_response = _off_topic_answer(_task_is_korean(request))
    if _is_explanation_only_edit_request(state) and not state.get("files_changed") and "no files were modified" not in core.final_response.lower():
        core.final_response = core.final_response.rstrip() + "\n\nNo files were modified."
    # Clarification backstop: if the answer *narrates* that it should ask a
    # question ("…질문합니다") without actually asking one, replace it with a
    # real question the user can answer.
    if _ASKING_NARRATION_RE.search(core.final_response) and not any(
        m in core.final_response or m in core.final_response.lower() for m in _QUESTION_MARKERS
    ):
        core.final_response = _ensure_actual_question("", request, korean=_task_is_korean(request))
    # Honesty backstop: never let the answer claim an edit was applied when no
    # file actually changed. This catches the failure mode where the model
    # narrates a change ("the docstring has been added") without applying it.
    if not state.get("files_changed") and _claims_edit_applied(core.final_response):
        core.final_response = (
            core.final_response.rstrip()
            + "\n\n⚠️ Note: no files were actually modified on disk. "
            "The change above was drafted but not applied — re-run the request or use Propose change to apply it."
        )
    source_notes = _web_source_notes_for_final(state)
    if source_notes and "Source notes:" not in core.final_response:
        core.final_response = core.final_response.rstrip() + "\n\nSource notes:\n" + "\n".join(source_notes)
    core.final_response = _ensure_final_evidence_grounding(core.final_response, state)
    if core.final_response != draft_response:
        from repooperator_worker.agent_core.events import append_work_trace

        append_work_trace(
            run_id=core.run_id,
            request=request,
            activity_id="final-synthesis-repair",
            phase="Finished",
            label="Rebuilt final answer",
            status="completed",
            safe_reasoning_summary="The draft answer did not match the gathered evidence, so I rebuilt it from collected files.",
            observation="Final answer repaired without storing the rejected draft text.",
            safety_note="Rejected draft text is not exposed in events.",
        )
    return {
        "final_response": core.final_response,
        "events_to_emit": [_graph_transition_event(state, "build_response", subgraph="finalization_graph", operation="build_response")],
    }

def final_emit_message_node(state: RepoOperatorGraphState) -> dict[str, Any]:
    request = _request(state)
    core = _core_state_from_graph(state)
    response = _response_with_change_set_payload(
        build_final_response(core, request).model_copy(update={"agent_flow": "langgraph"}),
        state,
    )
    return {
        "response_snapshot": response_to_snapshot(response),
        "events_to_emit": [_graph_transition_event(state, "emit_final_message", subgraph="finalization_graph", operation="emit_final_message")],
    }

def _response_with_change_set_payload(response: AgentRunResponse, state: RepoOperatorGraphState) -> AgentRunResponse:
    workflow_updates = _workflow_response_updates(state)
    recommendation_context = _runtime_recommendation_context(response, state)
    proposal = state.get("change_set_proposal")
    if not isinstance(proposal, dict) or not proposal.get("changes"):
        updates = dict(workflow_updates)
        if recommendation_context:
            updates["recommendation_context"] = recommendation_context
        return response.model_copy(update=json_safe(updates)) if updates else response
    validation = proposal.get("validation") if isinstance(proposal.get("validation"), dict) else {}
    validation_status = str(validation.get("status") or proposal.get("status") or "planned")
    errors = [str(item) for item in validation.get("errors") or proposal.get("proposal_errors") or []]
    archive_status = "applied" if proposal.get("applied") or proposal.get("status") == "applied" or state.get("apply_status") == "applied" else ("rejected" if proposal.get("status") == "rejected" else validation_status)
    archive = [_edit_archive_record_from_change(change, archive_status) for change in proposal.get("changes") or [] if isinstance(change, dict)]
    archive = [item for item in archive if item]
    first = (proposal.get("changes") or [{}])[0]
    if proposal.get("applied") or proposal.get("status") == "applied" or state.get("apply_status") == "applied":
        response_type = "edit_applied"
    elif proposal.get("status") == "rejected" or state.get("apply_status") == "rejected":
        response_type = "change_proposal"
    else:
        response_type = "change_proposal" if validation_status == "valid" else "proposal_error"
    updates: dict[str, Any] = {
        **workflow_updates,
        "response_type": response_type,
        "change_set_proposal": json_safe(proposal),
        "edit_archive": archive,
        "proposal_validation_status": validation_status,
        "validation_status": validation_status,
        "edit_mode": state.get("edit_mode"),
        "proposal_id": proposal.get("proposal_id"),
        "proposal_status": proposal.get("status"),
        "apply_status": state.get("apply_status") or proposal.get("apply_status"),
        "applied_change_set_id": state.get("applied_change_set_id") or proposal.get("applied_change_set_id"),
        "post_apply_validation_status": state.get("post_apply_validation_status") or proposal.get("post_apply_validation_status"),
    }
    if recommendation_context:
        plan = proposal.get("plan") if isinstance(proposal.get("plan"), dict) else None
        updates["recommendation_context"] = json_safe({**recommendation_context, "implementation_plan": plan} if plan else recommendation_context)
    if errors:
        updates["proposal_error_details"] = "; ".join(errors)
    if isinstance(first, dict):
        updates.update(
            {
                "proposal_relative_path": first.get("path"),
                "proposal_original_content": first.get("original_content") or "",
                "proposal_proposed_content": first.get("proposed_content") or "",
                "proposal_context_summary": ((proposal.get("plan") or {}).get("summary") if isinstance(proposal.get("plan"), dict) else None),
                "selected_target_file": first.get("path"),
            }
        )
    if workflow_updates.get("git_approval"):
        updates["response_type"] = "git_approval"
        updates["response"] = workflow_updates.get("response")
        updates["command_approval"] = workflow_updates.get("command_approval")
    return response.model_copy(update=json_safe(updates))


def _runtime_recommendation_context(response: AgentRunResponse, state: RepoOperatorGraphState) -> dict[str, Any]:
    context = dict(response.recommendation_context or {})
    understanding = state.get("user_understanding_context") if isinstance(state.get("user_understanding_context"), dict) else None
    evidence_basis = state.get("evidence_basis") if isinstance(state.get("evidence_basis"), dict) else None
    target_selection = state.get("target_selection_diagnostics") if isinstance(state.get("target_selection_diagnostics"), dict) else None
    candidates = target_selection.get("candidates") if target_selection else state.get("edit_target_candidates")
    if understanding:
        context["user_understanding_context"] = understanding
    if evidence_basis:
        context["evidence_basis"] = evidence_basis
    if target_selection:
        context["target_selection"] = target_selection
    if candidates:
        context["edit_target_candidates"] = candidates
    return json_safe(context)

def _workflow_response_updates(state: RepoOperatorGraphState) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    selection = state.get("validation_command_selection") if isinstance(state.get("validation_command_selection"), dict) else None
    validation_results = [item for item in state.get("validation_results") or [] if isinstance(item, dict)]
    latest_validation = next(
        (normalized for item in reversed(validation_results) if (normalized := normalize_validation_result(item))),
        None,
    )
    if selection:
        updates["validation_command_selection"] = json_safe(selection)
        updates["validation_commands"] = list(selection.get("candidates") or [])
    if latest_validation:
        updates["validation_result"] = json_safe(latest_validation)
    if state.get("post_apply_validation_status"):
        updates["post_apply_validation_status"] = state.get("post_apply_validation_status")

    workflow = state.get("git_workflow") if isinstance(state.get("git_workflow"), dict) else None
    if workflow:
        updates["git_workflow"] = json_safe(workflow)
    pending = state.get("pending_approval") if isinstance(state.get("pending_approval"), dict) else {}
    if pending.get("kind") in {"git_commit", "git_push", "github_create_pr", "gitlab_create_mr"}:
        git_approval = _git_approval_payload(pending)
        updates["git_approval"] = git_approval
        updates["command_approval"] = git_approval.get("command_approval")
        updates["response_type"] = "git_approval"
        updates["response"] = _git_approval_text(git_approval)
    return updates

def _git_approval_payload(pending: dict[str, Any]) -> dict[str, Any]:
    kind = str(pending.get("kind") or "")
    command: list[str]
    title: str
    if kind == "git_commit":
        message = str(pending.get("message") or "")
        command = ["git", "commit", "-m", message]
        title = "Commit approval required"
    elif kind == "git_push":
        remote = str(pending.get("remote") or "origin")
        branch = str(pending.get("branch") or "HEAD")
        command = ["git", "push", "--set-upstream", remote, branch]
        title = "Push approval required"
    elif kind == "gitlab_create_mr":
        title = "Merge request approval required"
        command = ["glab", "mr", "create", "--title", str(pending.get("title") or "RepoOperator change set")]
    else:
        title = "Pull request approval required"
        command = ["gh", "pr", "create", "--title", str(pending.get("title") or "RepoOperator change set")]
    command_approval = {
        "type": "command_approval",
        "approval_id": str(pending.get("approval_id") or f"{kind}:approval"),
        "command": command,
        "display_command": " ".join(command),
        "cwd": None,
        "risk": "medium",
        "read_only": False,
        "needs_network": kind in {"git_push", "github_create_pr", "gitlab_create_mr"},
        "touches_outside_repo": False,
        "needs_approval": True,
        "blocked": False,
        "reason": str(pending.get("reason") or f"{kind} requires approval."),
        "pattern": " ".join(command[:3]),
        "options": ["yes", "no_explain"],
    }
    return {
        "kind": kind,
        "title": title,
        "message": pending.get("message"),
        "files": pending.get("files") or [],
        "remote": pending.get("remote"),
        "branch": pending.get("branch"),
        "source_branch": pending.get("source_branch"),
        "target_branch": pending.get("target_branch"),
        "review_title": pending.get("title"),
        "body": pending.get("body") or pending.get("description"),
        "commit_summary": pending.get("commit_summary"),
        "reason": command_approval["reason"],
        "command_approval": command_approval,
    }

def _git_approval_text(approval: dict[str, Any]) -> str:
    lines = [str(approval.get("title") or "Git approval required"), str(approval.get("reason") or "This git action requires approval.")]
    summary = approval.get("commit_summary") if isinstance(approval.get("commit_summary"), dict) else {}
    if approval.get("message"):
        lines.append(f"Proposed message: {approval.get('message')}")
    if summary.get("validation_status"):
        lines.append(f"Validation status: {summary.get('validation_status')}")
    files = [str(path) for path in approval.get("files") or []]
    if files:
        lines.append("Changed files: " + ", ".join(f"`{path}`" for path in files))
    lines.append("No git write has been performed yet.")
    return "\n".join(lines)

def _edit_archive_record_from_change(change: dict[str, Any], validation_status: str) -> dict[str, Any]:
    path = str(change.get("path") or "")
    if not path:
        return {}
    operation = str(change.get("operation") or "modify")
    original = str(change.get("original_content") or "")
    proposed = "" if operation == "delete" else str(change.get("proposed_content") or "")
    if operation == "create":
        original = ""
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            proposed.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    additions = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return {
        "file_path": path,
        "file": path,
        "operation": operation,
        "status": "applied" if validation_status == "applied" else ("rejected" if validation_status == "rejected" else ("proposed" if validation_status == "valid" else "failed")),
        "summary": str(change.get("summary") or ""),
        "additions": additions,
        "deletions": deletions,
        "diff": diff,
        "diff_available": bool(diff.strip()),
        "proposal_id": "proposal:" + path,
        "validation_status": validation_status,
    }

def _is_explanation_only_edit_request(state: RepoOperatorGraphState) -> bool:
    frame = _task_frame(state)
    if frame is None:
        return False
    text = str(getattr(frame, "user_goal", "") or "")
    lowered = text.lower()
    asks_how = bool(re.search(r"\bhow\s+(would|do|can|should)\b", lowered)) or any(term in text for term in ("어떻게", "어떤 식으로"))
    mentions_change = bool(re.search(r"\b(change|edit|add|fix|implement|refactor|update)\b", lowered)) or any(term in text for term in ("추가", "고쳐", "구현", "수정"))
    return asks_how and mentions_change

def _task_is_korean(request: Any) -> bool:
    try:
        from repooperator_worker.services.response_quality_service import user_prefers_korean

        return user_prefers_korean(str(getattr(request, "task", "") or ""))
    except Exception:
        return False


_QUESTION_MARKERS = ("?", "까요", "나요", "주시겠어요", "해주세요", "알려주세요", "please confirm", "could you")
# Meta-narration about asking, without actually asking ("…질문합니다").
_ASKING_NARRATION_RE = re.compile(r"질문합니다|질문해야|질문을 던져|clarifying question|명확히 하기 위해|묻겠습니다")


def _ensure_actual_question(text: str, request: Any, *, korean: bool) -> str:
    """Guarantee the clarification shown to the user actually asks something."""
    lowered = text.lower()
    if any(marker in text or marker in lowered for marker in _QUESTION_MARKERS):
        return text
    goal = str(getattr(request, "task", "") or "").strip()
    goal_part = f' "{goal[:80]}"' if goal else ""
    if korean:
        return (
            f"요청하신 내용{goal_part}을 진행하기 전에 확인이 필요해요. "
            "어떤 동작을 원하시는지 조금 더 구체적으로 알려주시겠어요? "
            "(예: 어떤 명령어 이름으로, 어떤 사용자에게, 어떤 형식으로 동작해야 하는지)"
        )
    return (
        f"Before I proceed with{goal_part or ' this request'}, could you describe the expected behavior "
        "a bit more concretely? (e.g. command name, target users, exact behavior)"
    )


def _claims_edit_applied(text: str) -> bool:
    """Whether the answer asserts a file change was actually applied/completed."""
    if not text:
        return False
    lowered = text.lower()
    english = bool(
        re.search(
            r"\b(has been|have been|i(?:'ve| have)|successfully)\b.*\b(added|modified|updated|changed|created|edited|applied|implemented|removed|deleted|fixed)\b",
            lowered,
        )
    ) or bool(re.search(r"\b(added|updated|modified|created|edited|applied|implemented)\b.*\bto\b.*\.(py|js|ts|tsx|jsx|java|go|rs|rb|c|cpp|css|md|json|yml|yaml)\b", lowered))
    korean = any(term in text for term in ("추가했습니다", "수정했습니다", "변경했습니다", "적용했습니다", "구현했습니다", "생성했습니다", "삭제했습니다", "반영했습니다"))
    return english or korean


def _ensure_final_evidence_grounding(text: str, state: RepoOperatorGraphState) -> str:
    if not text.strip():
        return text
    lowered = text.lower()
    if "context_pack_report" in lowered or "evidence_basis" in lowered or "visible_rationale_log" in lowered:
        return text
    basis = state.get("evidence_basis") if isinstance(state.get("evidence_basis"), dict) else build_evidence_basis(dict(state), "final_synthesis")
    files = [
        str(item.get("path"))
        for item in basis.get("files", []) if isinstance(item, dict) and item.get("path") and item.get("retained") is not False
    ]
    proposal = basis.get("active_proposal") if isinstance(basis.get("active_proposal"), dict) else None
    if proposal and proposal.get("proposal_id") and str(proposal.get("proposal_id")) not in text:
        return text.rstrip() + f"\n\nProposal id: {proposal.get('proposal_id')}."
    missing_files = [path for path in files[:3] if path not in text]
    if missing_files and not any(marker in lowered for marker in ("could you clarify", "please clarify", "waiting for approval")):
        cited = ", ".join(f"`{path}`" for path in missing_files)
        return text.rstrip() + f"\n\nBased on: {cited}."
    return text

def _stream_final_delta(run_id: str):
    def emit(delta: str) -> None:
        # Tokens are forwarded live as the model produces them (true streaming),
        # so they are already paced by generation speed — no artificial delay.
        try:
            append_run_event(run_id, {"type": "assistant_delta", "delta": delta, "streaming_mode": "model_stream"})
        except OSError:
            return

    return emit
