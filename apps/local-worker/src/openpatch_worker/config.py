import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_base_dir: Path
    default_command_timeout_seconds: int
    git_clone_timeout_seconds: int
    git_fetch_timeout_seconds: int


def get_settings() -> Settings:
    repo_base_dir = Path(
        os.getenv("OPENPATCH_REPO_BASE_DIR", Path.home() / ".openpatch" / "repos")
    ).expanduser().resolve()

    return Settings(
        repo_base_dir=repo_base_dir,
        default_command_timeout_seconds=int(
            os.getenv("OPENPATCH_COMMAND_TIMEOUT_SECONDS", "30")
        ),
        git_clone_timeout_seconds=int(os.getenv("OPENPATCH_GIT_CLONE_TIMEOUT_SECONDS", "300")),
        git_fetch_timeout_seconds=int(os.getenv("OPENPATCH_GIT_FETCH_TIMEOUT_SECONDS", "120")),
    )
