from pathlib import Path

from openpatch_worker.schemas import AgentProposeFileRequest, AgentProposeFileResponse
from openpatch_worker.services.common import (
    ensure_git_repository,
    ensure_safe_write_path,
    resolve_project_path,
)
from openpatch_worker.services.context_service import build_minimal_repo_context
from openpatch_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)

MAX_FILE_CHARS = 12_000


def propose_file_edit(request: AgentProposeFileRequest) -> AgentProposeFileResponse:
    repo_path = resolve_project_path(request.repo_path)
    ensure_git_repository(repo_path)
    target_path = ensure_safe_write_path(repo_path, request.relative_path)
    original_content = _read_existing_text(target_path)
    context_summary, repo_context = build_minimal_repo_context(request.repo_path)
    client = OpenAICompatibleModelClient()

    system_prompt = (
        "You are OpenPatch, a coding assistant preparing an explicit file edit proposal. "
        "Return only the full replacement file content for the target file. "
        "Do not include markdown fences, explanations, or commentary."
    )
    user_prompt = (
        f"Task:\n{request.instruction}\n\n"
        f"Target file: {request.relative_path}\n\n"
        f"Repository context:\n{repo_context}\n\n"
        f"Current file content:\n{original_content}"
    )

    proposed_content = client.generate_text(
        ModelGenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    ).strip()

    return AgentProposeFileResponse(
        repo_path=request.repo_path,
        relative_path=request.relative_path,
        model=client.model_name,
        context_summary=context_summary,
        original_content=original_content,
        proposed_content=_normalize_model_file_content(proposed_content),
    )


def _read_existing_text(target_path: Path) -> str:
    if not target_path.exists():
        return ""
    if not target_path.is_file():
        raise ValueError(f"Target is not a file: {target_path.name}")
    return target_path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]


def _normalize_model_file_content(content: str) -> str:
    if content.startswith("```") and content.endswith("```"):
        stripped = content.strip("`").split("\n", 1)
        if len(stripped) == 2:
            return stripped[1].rsplit("\n", 1)[0]
    return content
