from openpatch_worker.schemas import FileReadRequest, FileReadResponse
from openpatch_worker.services.common import ensure_relative_to_repo, resolve_project_path


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

    return FileReadResponse(
        project_path=request.project_path,
        relative_path=request.relative_path,
        content=content,
        truncated=len(raw_bytes) > request.max_bytes,
        bytes_read=len(truncated_bytes),
    )
