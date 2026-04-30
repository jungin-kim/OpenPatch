import json
import re
from pathlib import Path

from repooperator_worker.config import WRITE_MODE_AUTO_APPLY, WRITE_MODE_WRITE_WITH_APPROVAL, get_settings
from repooperator_worker.schemas import AgentProposeFileRequest, AgentProposeFileResponse
from repooperator_worker.services.common import (
    ensure_git_repository,
    ensure_safe_write_path,
    resolve_project_path,
)
from repooperator_worker.services.context_service import build_minimal_repo_context
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)

MAX_FILE_CHARS = 12_000


def propose_file_edit(request: AgentProposeFileRequest) -> AgentProposeFileResponse:
    settings = get_settings()
    if settings.write_mode not in {WRITE_MODE_WRITE_WITH_APPROVAL, WRITE_MODE_AUTO_APPLY}:
        raise ValueError(
            "Write operations are disabled. "
            "Use Basic permissions or Auto review to enable repository-scoped change proposals."
        )

    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)
    target_path = ensure_safe_write_path(repo_path, request.relative_path)
    original_content = _read_existing_text(target_path)
    repo_context = build_minimal_repo_context(request.project_path)
    client = OpenAICompatibleModelClient()

    system_prompt = (
        "You are RepoOperator, a coding assistant preparing a safe file edit proposal. "
        "Return JSON only, with exactly this shape: "
        "{\"replacement\": \"full replacement file content\"}. "
        "The replacement must be the complete updated content of the target file. "
        "Do not include markdown fences, explanations, refusal text, or commentary."
    )
    user_prompt = (
        f"Task:\n{request.instruction}\n\n"
        f"Target file: {request.relative_path}\n\n"
        f"Repository context:\n{repo_context.prompt_context}\n\n"
        f"Current file content:\n{original_content}"
    )

    raw_output = client.generate_text(
        ModelGenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    ).strip()
    proposed_content = _parse_and_validate_model_edit(raw_output, original_content)

    return AgentProposeFileResponse(
        project_path=request.project_path,
        relative_path=request.relative_path,
        model=client.model_name,
        context_summary=repo_context.summary,
        original_content=original_content,
        proposed_content=proposed_content,
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


def _parse_and_validate_model_edit(raw_output: str, original_content: str) -> str:
    """Extract full replacement content and reject refusals/prose masquerading as diffs."""
    content = _normalize_model_file_content(raw_output.strip())
    if not content:
        raise ValueError("The model did not return a file edit.")

    refusal_patterns = [
        "i'm sorry",
        "i am sorry",
        "can't assist",
        "cannot assist",
        "can't help",
        "cannot help",
        "죄송",
    ]
    lowered = content.lower()
    if any(pattern in lowered for pattern in refusal_patterns):
        raise ValueError("The model refused instead of returning a valid file edit.")

    json_candidate = _extract_json_object(content)
    if json_candidate is not None:
        try:
            payload = json.loads(json_candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("The model returned invalid JSON instead of a file edit.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The model returned JSON that is not a file edit object.")
        if isinstance(payload.get("replacement"), str):
            return _validate_replacement_content(payload["replacement"], original_content)
        if isinstance(payload.get("content"), str):
            return _validate_replacement_content(payload["content"], original_content)
        if "response" in payload:
            raise ValueError("The model returned a response object instead of a file edit.")
        raise ValueError("The model JSON did not include replacement file content.")

    return _validate_replacement_content(content, original_content)


def _extract_json_object(content: str) -> str | None:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.match(r"^\s*(\{.*?\})", stripped, flags=re.DOTALL)
    if match and '"response"' in match.group(1):
        return match.group(1)
    return None


def _validate_replacement_content(replacement: str, original_content: str) -> str:
    if not isinstance(replacement, str):
        raise ValueError("Replacement content must be a string.")
    if not replacement.strip():
        raise ValueError("The proposed replacement was empty.")
    if replacement == original_content:
        raise ValueError("The proposed replacement did not change the file.")
    lower = replacement.strip().lower()
    if lower.startswith("{") and '"response"' in lower:
        raise ValueError("The proposed replacement looks like a model response object, not file content.")
    prose_starts = (
        "here is ",
        "here's ",
        "the following ",
        "i would ",
        "you can ",
        "to optimize ",
    )
    if any(lower.startswith(start) for start in prose_starts):
        raise ValueError("The model returned prose instead of replacement file content.")
    return replacement
