"""Final answer and response assembly for LangGraph agent runs."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.events import append_activity_event, append_work_trace
from repooperator_worker.agent_core.final_response import build_agent_response
from repooperator_worker.agent_core.final_synthesis import _answer_with_model
from repooperator_worker.agent_core.planner import (
    TaskFrame,
    _format_command_result,
    _format_edit_proposal,
    _latest_command_result,
    _latest_edit_proposal,
    _repository_review_response,
    build_task_frame,
    current_edit_target_files,
    edit_requested,
    likely_feature_context_files,
    pending_commit_context,
)
from repooperator_worker.agent_core.state import AgentCoreState
from repooperator_worker.agent_core.task_policy import group_inventory, repository_file_inventory
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.event_service import append_run_event
from repooperator_worker.services.json_safe import json_safe, safe_agent_response_payload, safe_repr


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
    repository_review = _repository_review_response(state)
    if repository_review:
        return repository_review.response
    approved_write = _latest_approved_write_result(state)
    if approved_write:
        return approved_write
    edit_proposal = _latest_edit_proposal(state)
    if edit_proposal:
        return _format_edit_proposal(edit_proposal)
    proposal_error = _latest_proposal_error(state)
    if proposal_error:
        try:
            from repooperator_worker.services.response_quality_service import user_prefers_korean

            if user_prefers_korean(str(getattr(request, "task", "") or "")):
                return (
                    "검증을 통과한 제안 패치를 만들지 못했습니다. "
                    f"사유: {proposal_error}. 파일은 수정되지 않았습니다."
                )
        except Exception:
            pass
        return (
            "I could not prepare a validated proposal-only patch. "
            f"Reason: {proposal_error}. No files were modified."
        )
    frame_for_edit = build_task_frame(request, state)
    if _unfulfilled_edit_request(state, frame_for_edit):
        # An edit was asked for, nothing was proposed or applied — say so.
        # Letting the model synthesize here produced confident narration of
        # changes that never happened ("주석을 추가했습니다", zero proposals).
        try:
            from repooperator_worker.services.response_quality_service import user_prefers_korean

            if user_prefers_korean(str(getattr(request, "task", "") or "")):
                return (
                    "요청하신 수정 패치를 이번 실행에서는 준비하지 못했습니다. 파일은 수정되지 않았습니다.\n"
                    "다시 시도하거나 대상 파일/변경 내용을 조금 더 구체적으로 알려주시면 이어서 준비하겠습니다."
                )
        except Exception:
            pass
        return (
            "I was not able to prepare the requested edit in this run — no files were modified. "
            "Please retry, or narrow down the target file/change and I will prepare the patch."
        )
    command_result = _latest_command_result(state)
    if command_result:
        return _format_command_result(command_result, pending_commit=pending_commit_context(build_task_frame(request, state)))
    if _is_broad_analysis_request(build_task_frame(request, state)) and state.files_read:
        return _format_broad_analysis_answer(state, request)
    if state.stop_reason in {"failed", "timed_out"}:
        return _build_evidence_limited_answer(state, request)
    if state.stop_reason in {"max_loop_iterations", "max_file_reads", "max_commands"} and not state.files_read and not state.commands_run:
        # Budget exhausted with nothing gathered — be honest about it. But when
        # files WERE read before the cap, fall through to model synthesis: a
        # budget cap is not a reason to discard real evidence ("read calc.py,
        # big_module.py" followed by "근거가 부족합니다" reads as a malfunction).
        return _build_evidence_limited_answer(state, request)
    contents: dict[str, str] = {}
    for result in state.action_results:
        contents.update(result.payload.get("contents") or {})
    repo_observation = "\n".join(state.observations[-6:])
    append_work_trace(
        run_id=state.run_id,
        request=request,
        activity_id="final-synthesis-preparing",
        phase="Finished",
        label="Preparing final answer",
        status="running",
        safe_reasoning_summary="Preparing an evidence-based answer from the gathered files and observations.",
        current_action="Synthesize the final response from collected evidence.",
        related_files=list(contents.keys()),
    )
    answer = _answer_with_model(request, contents, state=state, repo_observation=repo_observation, skills_context=skills_context, on_delta=on_delta)
    append_activity_event(
        run_id=state.run_id,
        request=request,
        activity_id="final-synthesis-prepared",
        event_type="activity_completed",
        phase="Finished",
        label="Prepared evidence-based answer",
        status="completed",
        safe_reasoning_summary="Prepared an evidence-based answer from gathered files and observations.",
        observation="Prepared the final answer from gathered evidence.",
    )
    return answer


def build_final_response(state: AgentCoreState, request: AgentRunRequest) -> AgentRunResponse:
    review_response = _repository_review_response(state)
    if review_response and state.stop_reason not in {"cancelled", "waiting_approval"}:
        return _response_json_safe(review_response.model_copy(update={"loop_iteration": state.loop_iteration, "agent_flow": "langgraph"}), request)
    response_type = "command_approval" if state.pending_approval else "assistant_answer"
    final_text = state.final_response
    if state.pending_approval and not (final_text or "").strip():
        # A blank message next to the approval card left the user guessing what
        # they were approving — describe the gated command/file write instead.
        final_text = _format_command_preview(list(state.pending_approval.get("command") or []), state.pending_approval)
    graph_path = "agent_core:" + (
        "cancelled" if state.stop_reason == "cancelled"
        else "command_preview" if state.pending_approval
        else "read_file_answer" if state.files_read
        else "general_answer"
    )
    return _response_json_safe(
        build_agent_response(
            request,
            response=final_text,
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
            agent_flow="langgraph",
        ),
        request,
    )


def _build_evidence_limited_answer(state: AgentCoreState, request: AgentRunRequest) -> str:
    frame = build_task_frame(request, state)
    checked: list[str] = []
    if state.files_read:
        checked.append("read " + ", ".join(f"`{path}`" for path in state.files_read[-6:]))
    if state.commands_run:
        checked.append("ran " + ", ".join(f"`{cmd}`" for cmd in state.commands_run[-3:]))
    recent_observations = [item for item in state.observations[-4:] if item]
    if recent_observations:
        checked.append("observed " + "; ".join(recent_observations))

    missing: list[str] = []
    if edit_requested(frame):
        context_files = likely_feature_context_files(request)
        if "main.py" in context_files and "main.py" not in state.files_read:
            missing.append("`main.py` should be read before choosing an implementation target")
        if not current_edit_target_files(state, frame, request):
            missing.append("the exact file or component that should own the requested feature is still not confirmed")
        if not _latest_edit_proposal(state):
            missing.append("no proposal-only edit was generated")
    elif not state.files_read and not state.commands_run:
        missing.append("no repository file or command evidence was gathered")

    korean = False
    try:
        from repooperator_worker.services.response_quality_service import user_prefers_korean

        korean = user_prefers_korean(str(getattr(request, "task", "") or ""))
    except Exception:
        korean = False
    if korean:
        lines = ["아직 근거가 충분히 확보되지 않아 확정적인 답을 드리기 어렵습니다."]
        lines.append("확인한 것: " + (("; ".join(checked)) if checked else "완료된 저장소 근거가 없습니다."))
        if missing:
            lines.append("부족한 근거: " + "; ".join(_dedupe_text(missing)) + ".")
        if edit_requested(frame):
            lines.append("다음 단계: 수정할 파일을 확정해 주시거나, 제가 엔트리포인트를 읽고 제안용 패치를 준비하도록 계속 진행 여부를 알려주세요.")
        else:
            lines.append("다음 단계: 살펴볼 파일이나 작업을 알려주시면 이어서 조사하겠습니다.")
        return "\n".join(lines)
    lines = ["I do not have enough confirmed evidence to give a final implementation answer yet."]
    lines.append("Checked: " + (("; ".join(checked)) if checked else "no completed repository evidence."))
    if missing:
        lines.append("Missing evidence: " + "; ".join(_dedupe_text(missing)) + ".")
    if edit_requested(frame):
        lines.append("Next safe step: confirm the target file or let me continue by reading the likely entrypoint and then preparing a proposal-only patch.")
    else:
        lines.append("Next safe step: confirm the specific file or workflow to inspect next, or let me continue gathering repository evidence.")
    return "\n".join(lines)


def _latest_proposal_error(state: AgentCoreState) -> str | None:
    for result in reversed(state.action_results):
        error = result.payload.get("proposal_error")
        if error:
            return str(error)
    return None


def _is_broad_analysis_request(frame: TaskFrame) -> bool:
    text = " ".join([frame.user_goal, *frame.requested_outputs]).lower()
    return any(term in text for term in ("all", "every", "whole", "entire", "directory structure", "source tree", "codebase", "전체", "모든")) and any(
        term in text for term in ("source", "file", "module", "project", "repo", "directory", "folder", "파일", "모듈", "구조")
    )


def _format_broad_analysis_answer(state: AgentCoreState, request: AgentRunRequest) -> str:
    contents: dict[str, str] = {}
    for result in state.action_results:
        contents.update(result.payload.get("contents") or {})
    inventory = repository_file_inventory(request)
    groups = group_inventory(inventory)
    analyzed = list(contents.keys())
    remaining_groups: list[str] = []
    for group, files in groups.items():
        remaining = [path for path in files if path not in analyzed]
        if remaining:
            remaining_groups.append(f"- {group}: {len(remaining)} remaining ({', '.join(remaining[:6])})")
    role_lines = ["| File | Role |", "| --- | --- |"]
    for path, content in contents.items():
        role_lines.append(f"| `{path}` | {_file_role_summary(path, content)} |")
    analyzed_text = ", ".join(f"`{path}`" for path in analyzed) or "none"
    remaining_text = "\n".join(remaining_groups) if remaining_groups else "- No remaining readable groups found in the current inventory."
    return "\n".join(
        [
            "I analyzed the first bounded batch of repository files.",
            "",
            f"Analyzed batch: {analyzed_text}",
            "",
            "File role table:",
            *role_lines,
            "",
            "Remaining groups/files:",
            remaining_text,
            "",
            "Next safe continuation: read the next bounded batch from the remaining groups and extend the same table.",
        ]
    )


def _file_role_summary(path: str, content: str) -> str:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if name.startswith("readme") or suffix in {".md", ".rst", ".txt"}:
        return "documentation or project overview"
    if suffix in {".json", ".toml", ".yaml", ".yml", ".gradle", ".xml"} or name in {"makefile", "dockerfile"}:
        return "configuration/build metadata"
    functions = re.findall(r"^\s*(?:def|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content, flags=re.MULTILINE)
    classes = re.findall(r"^\s*(?:class|interface|struct)\s+([A-Za-z_][A-Za-z0-9_]*)\b", content, flags=re.MULTILINE)
    exported = re.findall(r"\bexport\s+(?:function|class|const)\s+([A-Za-z_][A-Za-z0-9_]*)", content)
    names = [*functions[:3], *classes[:3], *exported[:3]]
    if names:
        return "source module defining " + ", ".join(_dedupe_text(names[:5]))
    return "source or support file"


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
            agent_flow="langgraph",
        )


def _unfulfilled_edit_request(state: AgentCoreState, frame: Any) -> bool:
    """True when the user's own words asked for an edit but this run produced
    no proposal, applied no change, and gated nothing for approval."""
    try:
        from repooperator_worker.agent_core.agentic_loop import _is_change_request

        if not _is_change_request(frame):
            return False
    except Exception:
        return False
    if state.pending_approval:
        return False
    if _latest_edit_proposal(state) or _latest_proposal_error(state):
        return False
    for result in getattr(state, "action_results", []) or []:
        payload = getattr(result, "payload", None) or {}
        if (payload.get("change_set_proposal") or {}).get("changes") or payload.get("edit_proposals"):
            return False
        if getattr(result, "files_changed", None):
            return False
    return bool(_has_edit_attempt(state))


def _has_edit_attempt(state: AgentCoreState) -> bool:
    return any(
        str(getattr(action, "type", "") or "") in {"generate_edit", "generate_change_set", "apply_change_set"}
        for action in getattr(state, "actions_taken", []) or []
    )


def _latest_approved_write_result(state: AgentCoreState) -> str | None:
    """A user-approved direct file write that succeeded is the outcome of the
    run — report it, even if later steps (e.g. a redundant change-set attempt
    against the already-written file) recorded errors."""
    actions = list(getattr(state, "actions_taken", []) or [])
    results = list(getattr(state, "action_results", []) or [])
    for action, result in zip(reversed(actions[-len(results):] if results else []), reversed(results)):
        action_type = str(getattr(action, "type", "") or "")
        if action_type not in {"create_file", "modify_file", "delete_file", "rename_file"}:
            continue
        payload = getattr(result, "payload", None) or {}
        if getattr(result, "status", "") != "success" or not payload.get("approved"):
            continue
        path = str(payload.get("path") or "").strip() or "요청하신 파일"
        verbs = {"create_file": "생성했습니다", "modify_file": "수정했습니다", "delete_file": "삭제했습니다", "rename_file": "이름을 변경했습니다"}
        return f"승인해 주신 대로 `{path}` 파일을 {verbs.get(action_type, '처리했습니다')}. 작업이 완료되었습니다."
    return None


def _format_command_preview(command: list[str], preview: dict[str, Any]) -> str:
    kind = str(preview.get("kind") or "")
    payload = preview.get("approval_payload") if isinstance(preview.get("approval_payload"), dict) else {}
    if not command and (kind in {"create_file", "write_file", "file_write"} or payload.get("path")):
        # File-write approvals have no shell command; an empty "``" preview
        # rendered as a blank final message. Describe the write instead.
        path = str(payload.get("path") or "").strip() or "(unknown path)"
        content = str(payload.get("content") or "")
        snippet = content[:600].rstrip()
        lines = [f"`{path}` 파일 작성을 승인해 주세요. 승인하시면 아래 내용으로 저장됩니다."]
        if snippet:
            lines.append(f"\n```\n{snippet}\n```")
        if len(content) > 600:
            lines.append(f"(내용 일부만 표시 — 총 {len(content)}자)")
        return "\n".join(lines)
    if not command and (kind == "git_branch_create" or payload.get("branch")):
        branch = str(payload.get("branch") or payload.get("name") or "").strip() or "(unknown)"
        return f"`{branch}` 브랜치 생성을 승인해 주세요. 승인하시면 로컬 브랜치를 만듭니다."
    text = " ".join(command)
    if not text.strip():
        # No command and no recognizable file payload — never render "``".
        return "승인이 필요한 작업이 있습니다. 승인 카드에서 내용을 확인하고 진행 여부를 결정해 주세요."
    if preview.get("needs_approval"):
        return f"`{text}` requires approval before RepoOperator can run it. Reason: {preview.get('reason') or 'command policy'}"
    return f"`{text}` is allowed by command policy. I did not run a mutating command."


def _dedupe_text(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
