"""Generate concise chat summaries after an approved proposal is applied."""

from __future__ import annotations

from typing import Any

from repooperator_worker.services.event_service import record_event
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)
from repooperator_worker.services.response_quality_service import (
    clean_user_visible_response,
    language_guidance_for_task,
    user_prefers_korean,
)


def generate_apply_summary(payload: dict[str, Any]) -> dict[str, Any]:
    user_request = str(payload.get("user_request") or "")
    relative_path = str(payload.get("relative_path") or "the selected file")
    proposal_summary = str(payload.get("proposal_summary") or "")
    diff_summary = str(payload.get("diff_summary") or "")
    fallback = _fallback_summary(user_request, relative_path, proposal_summary, diff_summary)

    response = fallback
    reasoning = None
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "You are RepoOperator. After an approved diff was applied, write a concise "
                    "user-facing summary. Include what changed, why, changed files, behavior impact, "
                    "and one practical follow-up test command when possible. "
                    "Do not claim to commit, push, or run tests unless that happened. "
                    + language_guidance_for_task(user_request)
                ),
                user_prompt="\n\n".join(
                    [
                        f"User request: {user_request}",
                        f"Changed file: {relative_path}",
                        f"Proposal summary: {proposal_summary}",
                        f"Diff summary:\n{diff_summary[:4000]}",
                    ]
                ),
            )
        )
        cleaned, reasoning = clean_user_visible_response(raw, user_task=user_request)
        if cleaned:
            response = cleaned
    except Exception:  # noqa: BLE001
        pass

    record_event(
        event_type="apply_summary",
        repo=str(payload.get("project_path") or ""),
        branch=payload.get("branch"),
        status="ok",
        summary=response,
        files=[relative_path] if relative_path else [],
    )
    return {
        "response": response,
        "response_type": "assistant_answer",
        "relative_path": relative_path,
        "reasoning": reasoning,
    }


def _fallback_summary(user_request: str, relative_path: str, proposal_summary: str, diff_summary: str) -> str:
    if user_prefers_korean(user_request):
        return (
            f"적용 완료했습니다. `{relative_path}`에 승인된 변경사항을 반영했습니다. "
            f"{proposal_summary or '요청한 수정 방향에 맞춰 파일 내용을 업데이트했습니다.'} "
            "변경 내용은 아직 커밋하거나 푸시하지 않았습니다. 다음으로 관련 테스트나 실행 명령을 확인해 보세요."
        )
    return (
        f"Applied the approved changes to `{relative_path}`. "
        f"{proposal_summary or 'The file was updated according to the requested change.'} "
        "RepoOperator has not committed or pushed anything. Next, run the relevant test or smoke check for this file."
    )
