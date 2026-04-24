from pathlib import Path

from openpatch_worker.config import get_settings
from openpatch_worker.schemas import RepoOpenRequest, RepoOpenResponse
from openpatch_worker.services.common import get_repo_base_dir
from openpatch_worker.services.subprocess_utils import run_subprocess


def open_repository(request: RepoOpenRequest) -> RepoOpenResponse:
    repo_base_dir = get_repo_base_dir()
    repo_path = _resolve_repo_path(repo_base_dir, request.project_path)
    cloned = False

    if not repo_path.exists():
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        clone_url = _get_clone_url(request)
        _clone_repository(clone_url, repo_path)
        cloned = True
    elif not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")

    _ensure_git_repository(repo_path)
    _fetch_repository(repo_path)
    _checkout_branch(repo_path=repo_path, branch=request.branch)

    head_sha = _git_stdout(["git", "rev-parse", "HEAD"], repo_path)
    current_branch = _git_stdout(["git", "branch", "--show-current"], repo_path) or request.branch
    message = "repository cloned and branch checked out" if cloned else "repository fetched and branch checked out"

    return RepoOpenResponse(
        project_path=request.project_path,
        local_repo_path=str(repo_path),
        branch=current_branch,
        head_sha=head_sha,
        cloned=cloned,
        message=message,
    )


def _resolve_repo_path(repo_base_dir: Path, project_path: str) -> Path:
    repo_path = (repo_base_dir / project_path).resolve()
    try:
        repo_path.relative_to(repo_base_dir)
    except ValueError as exc:
        raise ValueError("Resolved repository path escapes OPENPATCH_REPO_BASE_DIR") from exc
    return repo_path


def _get_clone_url(request: RepoOpenRequest) -> str:
    if request.git and request.git.clone_url:
        return request.git.clone_url
    raise ValueError(
        "Repository is missing locally and no git.clone_url was provided for clone."
    )


def _clone_repository(clone_url: str, repo_path: Path) -> None:
    # TODO: Add provider-specific auth hooks for private repository access.
    result = run_subprocess(
        command=["git", "clone", clone_url, str(repo_path)],
        cwd=repo_path.parent,
        timeout_seconds=get_settings().git_clone_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git clone failed for {clone_url}")


def _fetch_repository(repo_path: Path) -> None:
    # TODO: Add provider-aware auth refresh when remote access needs explicit credentials.
    result = run_subprocess(
        command=["git", "fetch", "--all", "--prune"],
        cwd=repo_path,
        timeout_seconds=get_settings().git_fetch_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git fetch failed")


def _ensure_git_repository(repo_path: Path) -> None:
    result = run_subprocess(
        command=["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ValueError(f"Not a git repository: {repo_path}")


def _checkout_branch(
    repo_path: Path,
    branch: str,
) -> None:
    existing_local = run_subprocess(
        command=["git", "rev-parse", "--verify", branch],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if existing_local.returncode == 0:
        result = run_subprocess(
            command=["git", "checkout", branch],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git checkout {branch} failed")
        return

    existing_remote = run_subprocess(
        command=["git", "show-ref", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=repo_path,
        timeout_seconds=60,
    )
    if existing_remote.returncode == 0:
        result = run_subprocess(
            command=["git", "checkout", "-B", branch, f"origin/{branch}"],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git checkout origin/{branch} failed")
        return

    raise ValueError(
        f"Branch '{branch}' was not found locally or on origin for repository {repo_path.name}"
    )


def _git_stdout(command: list[str], repo_path: Path) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{' '.join(command)} failed")
    return result.stdout.strip()
