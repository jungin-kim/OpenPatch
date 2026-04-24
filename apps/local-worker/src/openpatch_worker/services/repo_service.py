from pathlib import Path

from openpatch_worker.models import RepoOpenRequest, RepoOpenResponse
from openpatch_worker.services.subprocess_utils import run_subprocess


def open_repository(request: RepoOpenRequest) -> RepoOpenResponse:
    repo_path = Path(request.local_path).expanduser().resolve()
    cloned = False
    updated = False

    if not repo_path.exists():
        if not request.clone_if_missing:
            raise ValueError(f"Repository path does not exist: {repo_path}")
        if not request.repository_url:
            raise ValueError("repository_url is required when clone_if_missing is true")
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _clone_repository(request.repository_url, repo_path)
        cloned = True
    elif not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")

    _ensure_git_repository(repo_path)

    if request.update_if_present and not cloned:
        _fetch_repository(repo_path)
        updated = True

    if request.branch:
        _checkout_branch(
            repo_path=repo_path,
            branch=request.branch,
            create_if_missing=request.create_branch_if_missing,
            base_ref=request.base_ref,
        )

    head_sha = _git_stdout(["git", "rev-parse", "HEAD"], repo_path)
    current_branch = _git_stdout(["git", "branch", "--show-current"], repo_path) or None

    message_parts = []
    if cloned:
        message_parts.append("repository cloned")
    else:
        message_parts.append("repository attached")
    if updated:
        message_parts.append("remote refs updated")
    if current_branch:
        message_parts.append(f"checked out {current_branch}")

    return RepoOpenResponse(
        local_path=str(repo_path),
        branch=current_branch,
        head_sha=head_sha,
        cloned=cloned,
        updated=updated,
        message=", ".join(message_parts),
    )


def _clone_repository(repository_url: str, repo_path: Path) -> None:
    # TODO: Add provider-aware clone flows and explicit credential handling hooks.
    result = run_subprocess(
        command=["git", "clone", repository_url, str(repo_path)],
        cwd=repo_path.parent,
        timeout_seconds=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git clone failed")


def _fetch_repository(repo_path: Path) -> None:
    # TODO: Add provider/auth integration for managed remotes and token refresh flows.
    result = run_subprocess(
        command=["git", "fetch", "--all", "--prune"],
        cwd=repo_path,
        timeout_seconds=300,
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
    create_if_missing: bool,
    base_ref: str | None,
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
        command=["git", "ls-remote", "--heads", "origin", branch],
        cwd=repo_path,
        timeout_seconds=60,
    )
    if existing_remote.returncode == 0 and existing_remote.stdout.strip():
        result = run_subprocess(
            command=["git", "checkout", "-b", branch, f"origin/{branch}"],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git checkout origin/{branch} failed")
        return

    if not create_if_missing:
        raise ValueError(
            f"Branch '{branch}' does not exist locally or on origin and create_branch_if_missing is false"
        )

    start_ref = base_ref or "HEAD"
    result = run_subprocess(
        command=["git", "checkout", "-b", branch, start_ref],
        cwd=repo_path,
        timeout_seconds=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git checkout -b {branch} failed")


def _git_stdout(command: list[str], repo_path: Path) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{' '.join(command)} failed")
    return result.stdout.strip()
