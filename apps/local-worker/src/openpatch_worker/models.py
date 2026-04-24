from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str
    service: str


class RepoOpenRequest(BaseModel):
    local_path: str = Field(..., description="Target local repository path.")
    repository_url: str | None = Field(
        default=None,
        description="Remote URL to clone when the repository does not exist locally.",
    )
    branch: str | None = Field(
        default=None,
        description="Branch to checkout after clone or update.",
    )
    clone_if_missing: bool = Field(
        default=True,
        description="Clone the repository if the target path does not yet exist.",
    )
    update_if_present: bool = Field(
        default=False,
        description="Fetch and optionally fast-forward update the repository if it exists.",
    )
    create_branch_if_missing: bool = Field(
        default=False,
        description="Create the requested branch if it does not already exist locally or remotely.",
    )
    base_ref: str | None = Field(
        default=None,
        description="Base ref for creating a new branch when needed.",
    )

    @field_validator("local_path")
    @classmethod
    def validate_local_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("local_path must not be empty")
        return value


class RepoOpenResponse(BaseModel):
    local_path: str
    branch: str | None = None
    head_sha: str
    cloned: bool = False
    updated: bool = False
    message: str


class FileReadRequest(BaseModel):
    repo_path: str
    relative_path: str
    encoding: str = "utf-8"
    max_bytes: int = Field(default=100_000, ge=1, le=2_000_000)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        file_path = Path(value)
        if file_path.is_absolute():
            raise ValueError("relative_path must be relative to repo_path")
        if ".." in file_path.parts:
            raise ValueError("relative_path must not escape repo_path")
        return value


class FileReadResponse(BaseModel):
    repo_path: str
    relative_path: str
    content: str
    truncated: bool
    bytes_read: int


class CommandRunRequest(BaseModel):
    repo_path: str
    command: list[str] = Field(..., min_length=1)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    env: dict[str, str] | None = None


class CommandRunResponse(BaseModel):
    repo_path: str
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class GitDiffRequest(BaseModel):
    repo_path: str
    staged: bool = False
    base_ref: str | None = None
    paths: list[str] | None = None

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        for item in value:
            path = Path(item)
            if path.is_absolute():
                raise ValueError("diff paths must be relative")
            if ".." in path.parts:
                raise ValueError("diff paths must not escape repo_path")
        return value


class GitDiffResponse(BaseModel):
    repo_path: str
    diff: str
