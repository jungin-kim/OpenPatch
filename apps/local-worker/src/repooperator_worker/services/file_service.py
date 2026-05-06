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
from repooperator_worker.services.permissions_service import permission_profile


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
    profile = permission_profile()
    if not profile["sandbox"].get("allowFileWrite"):
        raise ValueError(
            "File writes are disabled by the current permission profile."
        )

    repo_path = resolve_project_path(request.project_path)
    target_path = ensure_safe_write_path(repo_path, request.relative_path)

    if target_path.exists() and not target_path.is_file():
        raise ValueError(f"Target is not a file: {request.relative_path}")
    if not request.content.strip():
        raise ValueError("File content must not be empty.")
    if _looks_like_secret_dump(request.content):
        raise ValueError("The proposed file content appears to contain secret material and was blocked.")

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


def _looks_like_secret_dump(content: str) -> bool:
    lowered = content.lower()
    high_risk_markers = (
        "-----begin private key-----",
        "aws_secret_access_key=",
        "openai_api_key=",
        "github_token=",
        "gitlab_token=",
    )
    return any(marker in lowered for marker in high_risk_markers)
