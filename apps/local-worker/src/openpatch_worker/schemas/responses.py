from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    repo_base_dir: str


class RepoOpenResponse(BaseModel):
    project_path: str
    local_repo_path: str
    branch: str
    head_sha: str
    cloned: bool
    message: str


class FileReadResponse(BaseModel):
    project_path: str
    relative_path: str
    content: str
    truncated: bool
    bytes_read: int


class FileWriteResponse(BaseModel):
    project_path: str
    relative_path: str
    bytes_written: int
    message: str


class CommandRunResponse(BaseModel):
    project_path: str
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class GitDiffResponse(BaseModel):
    project_path: str
    diff: str


class AgentRunResponse(BaseModel):
    repo_path: str
    model: str
    context_summary: str
    response: str


class AgentProposeFileResponse(BaseModel):
    repo_path: str
    relative_path: str
    model: str
    context_summary: str
    original_content: str
    proposed_content: str
