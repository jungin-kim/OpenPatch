from pathlib import Path


def resolve_repo_path(path_value: str) -> Path:
    repo_path = Path(path_value).expanduser().resolve()
    if not repo_path.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")
    return repo_path


def ensure_relative_to_repo(repo_path: Path, relative_path: str) -> Path:
    target_path = (repo_path / relative_path).resolve()
    try:
        target_path.relative_to(repo_path)
    except ValueError as exc:
        raise ValueError("Target path must stay within repo_path") from exc
    return target_path
