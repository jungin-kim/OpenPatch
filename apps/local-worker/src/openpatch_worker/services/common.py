from pathlib import Path

from openpatch_worker.config import get_settings


def get_repo_base_dir() -> Path:
    repo_base_dir = get_settings().repo_base_dir
    repo_base_dir.mkdir(parents=True, exist_ok=True)
    return repo_base_dir


def resolve_project_path(project_path: str) -> Path:
    repo_base_dir = get_repo_base_dir()
    repo_path = (repo_base_dir / project_path).resolve()
    try:
        repo_path.relative_to(repo_base_dir)
    except ValueError as exc:
        raise ValueError("Resolved repository path escapes LOCAL_REPO_BASE_DIR") from exc

    if not repo_path.exists():
        raise ValueError(
            f"Repository does not exist for project_path '{project_path}'. Open it first with /repo/open."
        )
    if not repo_path.is_dir():
        raise ValueError(f"Resolved repository path is not a directory: {repo_path}")
    return repo_path


def ensure_relative_to_repo(repo_path: Path, relative_path: str) -> Path:
    target_path = (repo_path / relative_path).resolve()
    try:
        target_path.relative_to(repo_path)
    except ValueError as exc:
        raise ValueError("Target path must stay within repo_path") from exc
    return target_path


def ensure_git_repository(repo_path: Path) -> None:
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        raise ValueError(f"Not a git repository: {repo_path}")
