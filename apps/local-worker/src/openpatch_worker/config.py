import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_base_dir: Path
    default_command_timeout_seconds: int
    git_clone_timeout_seconds: int
    git_fetch_timeout_seconds: int
    gitlab_base_url: str | None
    gitlab_token: str | None


def get_settings() -> Settings:
    repo_base_dir = Path(
        os.getenv("LOCAL_REPO_BASE_DIR", Path.home() / ".openpatch" / "repos")
    ).expanduser().resolve()

    return Settings(
        repo_base_dir=repo_base_dir,
        default_command_timeout_seconds=int(
            os.getenv("OPENPATCH_COMMAND_TIMEOUT_SECONDS", "30")
        ),
        git_clone_timeout_seconds=int(os.getenv("OPENPATCH_GIT_CLONE_TIMEOUT_SECONDS", "300")),
        git_fetch_timeout_seconds=int(os.getenv("OPENPATCH_GIT_FETCH_TIMEOUT_SECONDS", "120")),
        gitlab_base_url=_normalize_optional_url(os.getenv("GITLAB_BASE_URL")),
        gitlab_token=_normalize_optional_value(os.getenv("GITLAB_TOKEN")),
    )


def _normalize_optional_url(value: str | None) -> str | None:
    normalized = _normalize_optional_value(value)
    if normalized is None:
        return None
    return normalized.rstrip("/")


def _normalize_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
