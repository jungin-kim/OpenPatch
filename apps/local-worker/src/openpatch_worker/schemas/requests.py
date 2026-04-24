from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class GitProviderMetadata(BaseModel):
    provider: str | None = Field(default=None, description="Git provider identifier.")
    clone_url: str | None = Field(
        default=None,
        description="Clone URL used when the repository is missing locally.",
    )
    default_branch: str | None = Field(
        default=None,
        description="Provider-reported default branch if known.",
    )


class RepoOpenRequest(BaseModel):
    project_path: str = Field(
        ...,
        description="Repository path relative to the configured local repo base directory.",
    )
    branch: str = Field(..., description="Branch to fetch and check out.")
    git_provider: str | None = Field(
        default=None,
        description="Git provider identifier such as 'gitlab'.",
    )
    git: GitProviderMetadata | None = Field(
        default=None,
        description="Optional git provider metadata used for clone and future provider integration.",
    )

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("project_path must not be empty")
        if path.is_absolute():
            raise ValueError("project_path must be relative")
        if ".." in path.parts:
            raise ValueError("project_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("branch must not be empty")
        return value.strip()

    @field_validator("git_provider")
    @classmethod
    def validate_git_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"gitlab"}:
            raise ValueError("git_provider must be one of: gitlab")
        return normalized


class FileReadRequest(BaseModel):
    project_path: str
    relative_path: str
    encoding: str = "utf-8"
    max_bytes: int = Field(default=100_000, ge=1, le=2_000_000)

    @field_validator("project_path", "relative_path")
    @classmethod
    def validate_relative_values(cls, value: str, info) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        if path.is_absolute():
            raise ValueError(f"{info.field_name} must be relative")
        if ".." in path.parts:
            raise ValueError(f"{info.field_name} must not escape its base directory")
        return value.strip("/")


class FileWriteRequest(BaseModel):
    project_path: str
    relative_path: str
    content: str
    encoding: str = "utf-8"

    @field_validator("project_path", "relative_path")
    @classmethod
    def validate_relative_values(cls, value: str, info) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        if path.is_absolute():
            raise ValueError(f"{info.field_name} must be relative")
        if ".." in path.parts:
            raise ValueError(f"{info.field_name} must not escape its base directory")
        return value.strip("/")


class CommandRunRequest(BaseModel):
    project_path: str
    command: str = Field(..., description="Shell command executed with `sh -lc`.")
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("project_path must not be empty")
        if path.is_absolute():
            raise ValueError("project_path must be relative")
        if ".." in path.parts:
            raise ValueError("project_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must not be empty")
        return value


class GitDiffRequest(BaseModel):
    project_path: str
    staged: bool = False
    relative_paths: list[str] | None = None

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("project_path must not be empty")
        if path.is_absolute():
            raise ValueError("project_path must be relative")
        if ".." in path.parts:
            raise ValueError("project_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("relative_paths")
    @classmethod
    def validate_relative_paths(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            path = Path(item)
            if not item.strip():
                raise ValueError("relative_paths items must not be empty")
            if path.is_absolute():
                raise ValueError("relative_paths items must be relative")
            if ".." in path.parts:
                raise ValueError("relative_paths items must not escape the repo base directory")
            cleaned.append(item.strip("/"))
        return cleaned


class GitBranchCreateRequest(BaseModel):
    project_path: str
    branch: str
    from_ref: str = "HEAD"
    checkout: bool = True

    @field_validator("project_path", "branch", "from_ref")
    @classmethod
    def validate_values(cls, value: str, info) -> str:
        if info.field_name == "project_path":
            path = Path(value)
            if not value.strip():
                raise ValueError("project_path must not be empty")
            if path.is_absolute():
                raise ValueError("project_path must be relative")
            if ".." in path.parts:
                raise ValueError("project_path must not escape the repo base directory")
            return value.strip("/")
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()


class GitCommitRequest(BaseModel):
    project_path: str
    message: str
    stage_all: bool = True

    @field_validator("project_path")
    @classmethod
    def validate_project_path_for_commit(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("project_path must not be empty")
        if path.is_absolute():
            raise ValueError("project_path must be relative")
        if ".." in path.parts:
            raise ValueError("project_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("message")
    @classmethod
    def validate_commit_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value.strip()


class GitPushRequest(BaseModel):
    project_path: str
    branch: str
    remote: str = "origin"
    set_upstream: bool = True
    git_provider: str | None = None

    @field_validator("project_path", "branch", "remote")
    @classmethod
    def validate_push_values(cls, value: str, info) -> str:
        if info.field_name == "project_path":
            path = Path(value)
            if not value.strip():
                raise ValueError("project_path must not be empty")
            if path.is_absolute():
                raise ValueError("project_path must be relative")
            if ".." in path.parts:
                raise ValueError("project_path must not escape the repo base directory")
            return value.strip("/")
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()

    @field_validator("git_provider")
    @classmethod
    def validate_push_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"gitlab"}:
            raise ValueError("git_provider must be one of: gitlab")
        return normalized


class GitMergeRequestCreateRequest(BaseModel):
    project_path: str
    git_provider: str
    source_branch: str
    target_branch: str
    title: str
    description: str | None = None

    @field_validator("project_path")
    @classmethod
    def validate_project_path_for_mr(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("project_path must not be empty")
        if path.is_absolute():
            raise ValueError("project_path must be relative")
        if ".." in path.parts:
            raise ValueError("project_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("git_provider")
    @classmethod
    def validate_mr_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"gitlab"}:
            raise ValueError("git_provider must be one of: gitlab")
        return normalized

    @field_validator("source_branch", "target_branch", "title")
    @classmethod
    def validate_required_strings(cls, value: str, info) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentRunRequest(BaseModel):
    repo_path: str = Field(
        ...,
        description="Repository path relative to the configured local repo base directory.",
    )
    task: str = Field(..., description="User task sent to the centralized model backend.")

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("repo_path must not be empty")
        if path.is_absolute():
            raise ValueError("repo_path must be relative")
        if ".." in path.parts:
            raise ValueError("repo_path must not escape the repo base directory")
        return value.strip("/")

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task must not be empty")
        return value.strip()


class AgentProposeFileRequest(BaseModel):
    repo_path: str = Field(
        ...,
        description="Repository path relative to the configured local repo base directory.",
    )
    relative_path: str = Field(
        ...,
        description="Target file path relative to the repository root.",
    )
    instruction: str = Field(
        ...,
        description="Requested change instruction for the target file.",
    )

    @field_validator("repo_path", "relative_path")
    @classmethod
    def validate_relative_values(cls, value: str, info) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        if path.is_absolute():
            raise ValueError(f"{info.field_name} must be relative")
        if ".." in path.parts:
            raise ValueError(f"{info.field_name} must not escape its base directory")
        return value.strip("/")

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be empty")
        return value.strip()
