from repooperator_worker.config import WRITE_MODE_AUTO_APPLY, WRITE_MODE_WRITE_WITH_APPROVAL, get_settings
from repooperator_worker.schemas import (
    FileReadRequest,
    FileReadResponse,
    FileWriteRequest,
    FileWriteResponse,
)
from repooperator_worker.services.common import (
    ensure_relative_to_repo,
    ensure_safe_write_path,
    resolve_project_path,
)
from repooperator_worker.services.event_service import record_event


def read_text_file(request: FileReadRequest) -> FileReadResponse:
    repo_path = resolve_project_path(request.project_path)
    target_path = ensure_relative_to_repo(repo_path, request.relative_path)

    if not target_path.exists():
        raise FileNotFoundError(f"File not found: {request.relative_path}")
    if not target_path.is_file():
        raise ValueError(f"Target is not a file: {request.relative_path}")

    raw_bytes = target_path.read_bytes()
    truncated_bytes = raw_bytes[: request.max_bytes]
    content = truncated_bytes.decode(request.encoding, errors="replace")

    response = FileReadResponse(
        project_path=request.project_path,
        relative_path=request.relative_path,
        content=content,
        truncated=len(raw_bytes) > request.max_bytes,
        bytes_read=len(truncated_bytes),
    )
    record_event(
        event_type="file_read",
        repo=request.project_path,
        summary=f"Read {request.relative_path}",
        files=[request.relative_path],
    )
    return response


def write_text_file(request: FileWriteRequest) -> FileWriteResponse:
    settings = get_settings()
    if settings.write_mode not in {WRITE_MODE_WRITE_WITH_APPROVAL, WRITE_MODE_AUTO_APPLY}:
        raise ValueError(
            "Write operations are disabled. "
            "Use Basic permissions or Auto review to apply repository-scoped changes."
        )

    repo_path = resolve_project_path(request.project_path)
    target_path = ensure_safe_write_path(repo_path, request.relative_path)

    if target_path.exists() and not target_path.is_file():
        raise ValueError(f"Target is not a file: {request.relative_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_content = request.content.encode(request.encoding)
    target_path.write_text(request.content, encoding=request.encoding)

    response = FileWriteResponse(
        project_path=request.project_path,
        relative_path=request.relative_path,
        bytes_written=len(encoded_content),
        message=f"Wrote {request.relative_path}",
    )
    record_event(
        event_type="apply",
        repo=request.project_path,
        summary=f"Applied write to {request.relative_path}",
        files=[request.relative_path],
    )
    return response
