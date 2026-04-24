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
